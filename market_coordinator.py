# -*- coding: utf-8 -*-
"""Gate 2.2：行情協調器（MarketDataCoordinator）。

目的：多檔看盤 4／6 格時，所有格子共用同一份快取，不會每次 rerun、每一格各自打 API。

規則
- 快取鍵 = 資料種類 + 代號 + 會影響回傳內容的參數（例：("candles","2330",timeframe="5")）。
  由 RequestKey.make() 統一正規化，各頁不得自己拼字串。
- 同一個鍵在 TTL 內只抓一次；一次要多檔時先去重；同一鍵同時被多格要求只抓一次。
- 錯誤分兩種：
  * 資料來源錯誤（網路、API、回傳空值）→ 隔離在那一檔，回傳結果物件，不讓整頁炸掉。
  * 程式設計錯誤（未設定的資料種類、代號型別錯、參數不能比對）→ 直接拋 ValueError／TypeError，讓測試抓得到。
- 沿用舊資料時保留三個時間，畫面不得把「剛重試過」當成「資料是新的」：
  data_as_of（資料本身的時間）、last_success_at（最後一次成功抓到）、last_attempt_at（最後一次嘗試）。
- 呼叫上限 api_budget_per_minute 是設定值，依「資料提供者」分開計算；預設值只是保守設定，
  不是富果官方數字，正式方案確定後由後台設定。

架構邊界：這個協調器只放「公共行情」，可以全 app 共用（st.cache_resource）。
使用者自己的自選股、提醒條件、版面不得放進來，那些屬於各自的 session。

本模組不 import streamlit、不 import 任何資料來源套件；抓資料的函式由外部注入。
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Tuple


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FetchStatus(str, Enum):
    FRESH = "剛抓到"
    CACHED = "快取"
    STALE_AFTER_ERROR = "抓取失敗，沿用上一次資料"
    RATE_LIMITED = "已達呼叫上限，沿用上一次資料"
    UNAVAILABLE = "沒有資料"


@dataclass(frozen=True)
class RequestKey:
    kind: str
    symbol: str
    params: Tuple[Tuple[str, Any], ...] = ()

    @staticmethod
    def make(kind: str, symbol: str, **params) -> "RequestKey":
        if not isinstance(kind, str) or not kind:
            raise TypeError("kind 必須是非空字串")
        if not isinstance(symbol, str) or not symbol:
            raise TypeError("symbol 必須是非空字串")
        items = []
        for k in sorted(params):
            v = params[k]
            if v is None:
                continue                      # None 等於沒給這個參數
            try:
                hash(v)
            except TypeError:
                raise TypeError(f"參數 {k} 必須可比對（不能是 list/dict）") from None
            items.append((k, v))
        return RequestKey(kind, symbol, tuple(items))

    def label(self) -> str:
        p = ",".join(f"{k}={v}" for k, v in self.params)
        return f"{self.kind}:{self.symbol}" + (f"[{p}]" if p else "")


@dataclass
class FetchResult:
    key: RequestKey
    status: FetchStatus
    value: Any = None                         # 成功抓到的原始資料（RAW）
    data_as_of: Optional[datetime] = None     # 資料本身的時間（由 as_of 函式從資料取出，取不到就是 None）
    last_success_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    error: str = ""

    @property
    def kind(self) -> str:
        return self.key.kind

    @property
    def symbol(self) -> str:
        return self.key.symbol

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def is_stale(self) -> bool:
        return self.ok and self.status in (FetchStatus.STALE_AFTER_ERROR, FetchStatus.RATE_LIMITED)


@dataclass
class _Entry:
    value: Any = None
    data_as_of: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    last_error: str = ""
    last_error_at: Optional[datetime] = None


@dataclass
class Source:
    """一種資料的設定。"""
    fetch: Callable[..., Any]                          # fetch(symbol, **params) -> 原始資料
    provider: str = "default"                          # 限流與統計依提供者分開（例：Fugle、FinMind）
    ttl_seconds: float = 5.0
    as_of: Optional[Callable[[Any], Optional[datetime]]] = None   # 從原始資料取出資料時間


@dataclass
class Stats:
    api_calls: Dict[str, int] = field(default_factory=dict)
    cache_hits: Dict[str, int] = field(default_factory=dict)
    errors: Dict[str, int] = field(default_factory=dict)
    rate_limited: Dict[str, int] = field(default_factory=dict)

    @staticmethod
    def _inc(d: Dict[str, int], kind: str) -> None:
        d[kind] = d.get(kind, 0) + 1

    def summary(self) -> List[str]:
        kinds = sorted(set(self.api_calls) | set(self.cache_hits) | set(self.errors) | set(self.rate_limited))
        return [f"{k}：打 API {self.api_calls.get(k, 0)} 次、用快取 {self.cache_hits.get(k, 0)} 次、"
                f"失敗 {self.errors.get(k, 0)} 次、因上限略過 {self.rate_limited.get(k, 0)} 次" for k in kinds]


class MarketDataCoordinator:
    """所有格子共用的公共行情入口。

    sources：{資料種類: Source}
    api_budget_per_minute：{提供者: 每分鐘上限}；沒寫的提供者不限。
    error_backoff_seconds：失敗後多久內不重打同一鍵（避免一檔壞掉吃光額度）。
    now：回傳 aware datetime 的時鐘（測試可注入）。
    """

    def __init__(self, sources: Dict[str, Source], *, api_budget_per_minute: Optional[Dict[str, int]] = None,
                 error_backoff_seconds: float = 10.0, now: Callable[[], datetime] = _utcnow):
        for k, s in sources.items():
            if not isinstance(s, Source):
                raise TypeError(f"{k} 的設定必須是 Source")
        self._sources = dict(sources)
        self._budget = dict(api_budget_per_minute or {})
        self._backoff = error_backoff_seconds
        self._now = now
        self._cache: Dict[RequestKey, _Entry] = {}
        self._calls: Dict[str, Deque[datetime]] = {}
        self._lock = threading.Lock()
        self._key_locks: Dict[RequestKey, threading.Lock] = {}
        self.stats = Stats()

    # ── 設定 ──────────────────────────────────────
    def set_budget(self, provider: str, per_minute: Optional[int]) -> None:
        with self._lock:
            if per_minute is None:
                self._budget.pop(provider, None)
            else:
                if not isinstance(per_minute, int) or per_minute < 0:
                    raise ValueError("每分鐘上限必須是 ≥0 的整數")
                self._budget[provider] = per_minute

    def _source(self, kind: str) -> Source:
        if kind not in self._sources:
            raise ValueError(f"沒有設定「{kind}」這種資料（程式設計錯誤）")
        return self._sources[kind]

    # ── 內部 ──────────────────────────────────────
    def _key_lock(self, key: RequestKey) -> threading.Lock:
        with self._lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def _take_budget(self, provider: str) -> bool:
        limit = self._budget.get(provider)
        if limit is None:
            return True
        now = self._now()
        with self._lock:
            q = self._calls.setdefault(provider, deque())
            while q and (now - q[0]).total_seconds() >= 60.0:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def calls_last_minute(self, provider: str) -> int:
        now = self._now()
        with self._lock:
            return sum(1 for t in self._calls.get(provider, ()) if (now - t).total_seconds() < 60.0)

    @staticmethod
    def _result(key: RequestKey, status: FetchStatus, e: Optional[_Entry], error: str = "") -> FetchResult:
        if e is None:
            return FetchResult(key, FetchStatus.UNAVAILABLE, error=error)
        if e.value is None:
            status = FetchStatus.UNAVAILABLE
        return FetchResult(key, status, e.value, e.data_as_of, e.last_success_at, e.last_attempt_at,
                           error or (e.last_error if status != FetchStatus.FRESH else ""))

    # ── 對外 ──────────────────────────────────────
    def get(self, kind: str, symbol: str, *, force: bool = False, **params) -> FetchResult:
        """拿一份資料。資料來源出錯 → 回傳結果物件；程式設計錯誤 → 拋例外。"""
        src = self._source(kind)
        key = RequestKey.make(kind, symbol, **params)
        with self._key_lock(key):
            e = self._cache.get(key)
            now = self._now()
            if (not force and e and e.last_success_at is not None
                    and (now - e.last_success_at).total_seconds() < src.ttl_seconds
                    and (e.last_error_at is None or e.last_error_at <= e.last_success_at)):
                Stats._inc(self.stats.cache_hits, kind)
                return self._result(key, FetchStatus.CACHED, e)
            if (not force and e and e.last_error_at is not None
                    and (now - e.last_error_at).total_seconds() < self._backoff
                    and (e.last_success_at is None or e.last_error_at > e.last_success_at)):
                Stats._inc(self.stats.cache_hits, kind)
                return self._result(key, FetchStatus.STALE_AFTER_ERROR, e)
            if not self._take_budget(src.provider):
                Stats._inc(self.stats.rate_limited, kind)
                return self._result(key, FetchStatus.RATE_LIMITED, e, f"{src.provider} 這一分鐘的呼叫次數已用完")
            Stats._inc(self.stats.api_calls, kind)
            e = e or _Entry()
            e.last_attempt_at = now
            try:
                value = src.fetch(symbol, **dict(key.params))
                if value is None:
                    raise ValueError("來源回傳空值")
                as_of = src.as_of(value) if src.as_of else None
            except Exception as ex:  # noqa: BLE001 — 資料來源錯誤只影響這一鍵
                Stats._inc(self.stats.errors, kind)
                e.last_error, e.last_error_at = f"{type(ex).__name__}: {ex}", now
                self._cache[key] = e
                return self._result(key, FetchStatus.STALE_AFTER_ERROR, e)
            e.value, e.data_as_of, e.last_success_at = value, as_of, now
            e.last_error, e.last_error_at = "", None
            self._cache[key] = e
            return self._result(key, FetchStatus.FRESH, e)

    def get_many(self, kind: str, symbols: Iterable[str], **params) -> Dict[str, FetchResult]:
        """多格一次要：去重（空字串略過）；每個代號最多抓一次；回傳 {代號: 結果}。"""
        out: Dict[str, FetchResult] = {}
        for s in symbols:
            if s == "":
                continue
            if s not in out:
                out[s] = self.get(kind, s, **params)
        return out

    def invalidate(self, kind: Optional[str] = None, symbol: Optional[str] = None) -> int:
        with self._lock:
            keys = [k for k in self._cache if (kind is None or k.kind == kind) and (symbol is None or k.symbol == symbol)]
            for k in keys:
                del self._cache[k]
        return len(keys)
