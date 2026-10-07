# -*- coding: utf-8 -*-
"""Gate 2.2：行情協調器（MarketDataCoordinator）。

目的：多檔看盤 4／6 格時，所有格子共用同一份快取，不會每次 rerun、每一格各自打 API。

規則
- 同一個（資料種類, 股票代號）在 TTL 內只抓一次；其他格子／rerun 直接拿快取。
- 一次要多檔時先去重，同一檔只抓一次。
- 某一檔失敗只影響那一檔：其他檔照常；那一檔若之前有成功過，給「上一次的資料＋標示過期」，
  從來沒成功過就給「沒有資料」，絕不拋例外給 UI。
- 每分鐘呼叫上限（預設值只是保守設定，不是富果官方數字；正式上線前要依方案確認）：
  超過上限就不再打 API，改給快取並標示「已達呼叫上限」。
- 統計：每種資料打了幾次 API、命中幾次快取、失敗幾次，給管理後台看。

本模組不 import streamlit、不 import 任何資料來源套件；抓資料的函式由外部注入。
"""
from __future__ import annotations

import threading
import time as _time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple


class FetchStatus(str, Enum):
    FRESH = "剛抓到"              # 這次真的打了 API 並成功
    CACHED = "快取"               # TTL 內，沿用之前成功的結果
    STALE_AFTER_ERROR = "抓取失敗，沿用上一次資料"
    RATE_LIMITED = "已達呼叫上限，沿用上一次資料"
    UNAVAILABLE = "沒有資料"


@dataclass
class FetchResult:
    kind: str
    symbol: str
    status: FetchStatus
    value: Any = None                 # 成功時抓到的原始資料（RAW，未經加工）
    fetched_at: Optional[float] = None   # 這份資料實際抓到的時間（monotonic 秒，僅供計算年齡）
    age_seconds: Optional[float] = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def is_stale(self) -> bool:
        return self.status in (FetchStatus.STALE_AFTER_ERROR, FetchStatus.RATE_LIMITED)


@dataclass
class _Entry:
    value: Any = None
    fetched_at: Optional[float] = None
    last_error: str = ""
    last_error_at: Optional[float] = None


@dataclass
class Stats:
    api_calls: Dict[str, int] = field(default_factory=dict)
    cache_hits: Dict[str, int] = field(default_factory=dict)
    errors: Dict[str, int] = field(default_factory=dict)
    rate_limited: Dict[str, int] = field(default_factory=dict)

    def _inc(self, d: Dict[str, int], kind: str) -> None:
        d[kind] = d.get(kind, 0) + 1

    def summary(self) -> List[str]:
        kinds = sorted(set(self.api_calls) | set(self.cache_hits) | set(self.errors) | set(self.rate_limited))
        return [f"{k}：打 API {self.api_calls.get(k, 0)} 次、用快取 {self.cache_hits.get(k, 0)} 次、"
                f"失敗 {self.errors.get(k, 0)} 次、因上限略過 {self.rate_limited.get(k, 0)} 次" for k in kinds]


class MarketDataCoordinator:
    """所有格子共用的資料入口。

    fetchers：{資料種類: fn(symbol) -> 原始資料}；fn 可以拋例外，協調器會接住。
    ttl：{資料種類: 秒數}；沒寫的種類用 default_ttl。
    max_calls_per_minute：所有種類合計的 API 上限（None＝不限）。
    clock：可注入（測試用），預設 time.monotonic。
    """

    def __init__(self, fetchers: Dict[str, Callable[[str], Any]], *, ttl: Optional[Dict[str, float]] = None,
                 default_ttl: float = 5.0, max_calls_per_minute: Optional[int] = 50,
                 error_backoff: float = 10.0, clock: Callable[[], float] = _time.monotonic):
        self._fetchers = dict(fetchers)
        self._ttl = dict(ttl or {})
        self._default_ttl = default_ttl
        self._max_per_min = max_calls_per_minute
        self._error_backoff = error_backoff     # 失敗後多久內不重打同一檔（避免一檔壞掉拖垮配額）
        self._clock = clock
        self._cache: Dict[Tuple[str, str], _Entry] = {}
        self._calls: Deque[float] = deque()
        self._lock = threading.Lock()
        self._key_locks: Dict[Tuple[str, str], threading.Lock] = {}
        self.stats = Stats()

    # ── 內部 ──────────────────────────────────────
    def ttl_for(self, kind: str) -> float:
        return self._ttl.get(kind, self._default_ttl)

    def _key_lock(self, key: Tuple[str, str]) -> threading.Lock:
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def _take_budget(self) -> bool:
        if self._max_per_min is None:
            return True
        now = self._clock()
        with self._lock:
            while self._calls and now - self._calls[0] >= 60.0:
                self._calls.popleft()
            if len(self._calls) >= self._max_per_min:
                return False
            self._calls.append(now)
            return True

    def calls_last_minute(self) -> int:
        now = self._clock()
        with self._lock:
            return sum(1 for t in self._calls if now - t < 60.0)

    def _result(self, kind, symbol, status, entry: Optional[_Entry], error="") -> FetchResult:
        if entry is None or entry.value is None:
            return FetchResult(kind, symbol, FetchStatus.UNAVAILABLE if status != FetchStatus.FRESH else status,
                               error=error or (entry.last_error if entry else ""))
        return FetchResult(kind, symbol, status, entry.value, entry.fetched_at,
                           self._clock() - entry.fetched_at, error)

    # ── 對外 ──────────────────────────────────────
    def get(self, kind: str, symbol: str, *, force: bool = False) -> FetchResult:
        """拿一檔資料。永不拋例外。"""
        if kind not in self._fetchers:
            return FetchResult(kind, symbol, FetchStatus.UNAVAILABLE, error=f"沒有設定「{kind}」的資料來源")
        key = (kind, symbol)
        with self._key_lock(key):          # 同一檔同時被多格要求 → 只有一個真的去抓
            entry = self._cache.get(key)
            now = self._clock()
            ttl = self.ttl_for(kind)
            if not force and entry and entry.fetched_at is not None and now - entry.fetched_at < ttl:
                self.stats._inc(self.stats.cache_hits, kind)
                return self._result(kind, symbol, FetchStatus.CACHED, entry)
            if (not force and entry and entry.last_error_at is not None
                    and now - entry.last_error_at < self._error_backoff
                    and (entry.fetched_at is None or entry.last_error_at > entry.fetched_at)):
                self.stats._inc(self.stats.cache_hits, kind)
                return self._result(kind, symbol, FetchStatus.STALE_AFTER_ERROR, entry, entry.last_error)
            if not self._take_budget():
                self.stats._inc(self.stats.rate_limited, kind)
                return self._result(kind, symbol, FetchStatus.RATE_LIMITED, entry,
                                    "這一分鐘的呼叫次數已用完")
            self.stats._inc(self.stats.api_calls, kind)
            try:
                value = self._fetchers[kind](symbol)
                if value is None:
                    raise ValueError("來源回傳空值")
            except Exception as e:  # noqa: BLE001 — 單檔失敗只影響單檔
                self.stats._inc(self.stats.errors, kind)
                entry = entry or _Entry()
                entry.last_error, entry.last_error_at = f"{type(e).__name__}: {e}", self._clock()
                self._cache[key] = entry
                return self._result(kind, symbol, FetchStatus.STALE_AFTER_ERROR, entry, entry.last_error)
            entry = _Entry(value=value, fetched_at=self._clock())
            self._cache[key] = entry
            return self._result(kind, symbol, FetchStatus.FRESH, entry)

    def get_many(self, kind: str, symbols: Iterable[str]) -> Dict[str, FetchResult]:
        """多格一次要：去重後每檔最多抓一次；回傳 {代號: 結果}，順序依第一次出現。"""
        out: Dict[str, FetchResult] = {}
        for s in symbols:
            if s and s not in out:
                out[s] = self.get(kind, s)
        return out

    def invalidate(self, kind: Optional[str] = None, symbol: Optional[str] = None) -> int:
        with self._lock:
            keys = [k for k in self._cache if (kind is None or k[0] == kind) and (symbol is None or k[1] == symbol)]
            for k in keys:
                del self._cache[k]
        return len(keys)


# ── Streamlit 接線（之後才用；放這裡只是讓「整個 app 共用一個協調器」有固定寫法）──
def shared_coordinator_factory(build: Callable[[], MarketDataCoordinator]):
    """回傳一個 getter：在 Streamlit 裡用 st.cache_resource 包起來，跨 rerun、跨格子共用同一個實例。

    用法（接線時才寫，不在本模組 import streamlit）：
        get_coord = st.cache_resource(shared_coordinator_factory(lambda: MarketDataCoordinator({...})))
    """
    def _get() -> MarketDataCoordinator:
        return build()
    return _get
