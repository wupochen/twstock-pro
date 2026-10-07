# -*- coding: utf-8 -*-
"""排行（與資料提供者無關）。先做好、等方案／授權到位再打開（見 capabilities.INTRADAY_RANKING）。

排行種類一定要分清楚，畫面不得混用：
- MARKET_INTRADAY：盤中全市場排行（需要富果開發者以上 snapshot，或 Shioaji scanner）
- AFTER_HOURS：盤後全市場排行（官方盤後資料）
- WATCHLIST：只在使用者自選股之間排序（不是市場排行，標題必須寫明）

富果 snapshot adapter 依官方文件欄位寫成（DOC_BASED），目前憑證 403 拿不到真實資料；
開通當天必須先抓 RAW_CAPTURE 與文件範例比對，通過才算驗收。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from data_bundle import TPE, from_epoch_us, num, require_aware
from data_license import status_of


class RankScope(str, Enum):
    MARKET_INTRADAY = "盤中全市場排行"
    AFTER_HOURS = "盤後全市場排行"
    WATCHLIST = "自選股排序（非市場排行）"


class RankKind(str, Enum):
    CHANGE_PERCENT_UP = "漲幅"
    CHANGE_PERCENT_DOWN = "跌幅"
    CHANGE_VALUE_UP = "漲點"
    CHANGE_VALUE_DOWN = "跌點"
    VOLUME = "成交量"
    VALUE = "成交值"


@dataclass(frozen=True)
class RankingRow:
    rank: int
    symbol: str
    name: str
    price: Optional[float]
    change: Optional[float]
    change_percent: Optional[float]
    volume_lots: Optional[float]     # 張
    value_twd: Optional[float]       # 元
    as_of: Optional[datetime]
    source: str
    scope: RankScope
    kind: RankKind

    @property
    def distribution_status(self) -> str:
        return status_of(self.source).value


@dataclass
class Ranking:
    scope: RankScope
    kind: RankKind
    market: str
    source: str
    as_of: Optional[datetime]
    rows: List[RankingRow]
    fixture_origin: str = ""          # DOC_BASED／RAW_CAPTURE（測試資料來源等級）


class RankingProvider(Protocol):
    name: str

    def fetch(self, market: str, kind: RankKind) -> Ranking: ...


# ── 富果 snapshot（DOC_BASED）─────────────────────────────
FUGLE_ENDPOINT = {
    RankKind.CHANGE_PERCENT_UP: ("snapshot/movers/{m}", {"direction": "up", "change": "percent"}),
    RankKind.CHANGE_PERCENT_DOWN: ("snapshot/movers/{m}", {"direction": "down", "change": "percent"}),
    RankKind.CHANGE_VALUE_UP: ("snapshot/movers/{m}", {"direction": "up", "change": "value"}),
    RankKind.CHANGE_VALUE_DOWN: ("snapshot/movers/{m}", {"direction": "down", "change": "value"}),
    RankKind.VOLUME: ("snapshot/actives/{m}", {"trade": "volume"}),
    RankKind.VALUE: ("snapshot/actives/{m}", {"trade": "value"}),
}


def _snapshot_time(d: str, t: str) -> Optional[datetime]:
    try:
        dd = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H%M%S")
    except (TypeError, ValueError):
        return None
    return dd.replace(tzinfo=TPE)


def fugle_snapshot_ranking(raw: Dict[str, Any], kind: RankKind, market: str,
                           fixture_origin: str = "DOC_BASED") -> Ranking:
    """富果 snapshot movers／actives → Ranking。欄位依官方文件；張、元的單位與 quote 端點一致（待 RAW_CAPTURE 確認）。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise ValueError("富果排行格式錯誤")
    if raw.get("market") not in (None, market):
        raise ValueError(f"要求 {market}，回傳是 {raw.get('market')}")
    snap_time = _snapshot_time(raw.get("date"), raw.get("time"))
    rows = []
    for i, r in enumerate(raw["data"], 1):
        as_of = from_epoch_us(r.get("lastUpdated")) or snap_time
        rows.append(RankingRow(i, str(r.get("symbol")), str(r.get("name") or ""), num(r.get("closePrice")),
                               num(r.get("change")), num(r.get("changePercent")), num(r.get("tradeVolume")),
                               num(r.get("tradeValue")), as_of, "Fugle", RankScope.MARKET_INTRADAY, kind))
    return Ranking(RankScope.MARKET_INTRADAY, kind, market, "Fugle", snap_time, rows, fixture_origin)


def watchlist_ranking(quotes: Dict[str, Dict[str, Any]], kind: RankKind, source: str) -> Ranking:
    """只在自選股之間排序；scope 一定是 WATCHLIST，畫面標題要寫「自選股排序（非市場排行）」。"""
    key = {RankKind.CHANGE_PERCENT_UP: ("change_percent", True), RankKind.CHANGE_PERCENT_DOWN: ("change_percent", False),
           RankKind.CHANGE_VALUE_UP: ("change", True), RankKind.CHANGE_VALUE_DOWN: ("change", False),
           RankKind.VOLUME: ("volume_lots", True), RankKind.VALUE: ("value_twd", True)}[kind]
    items = [(s, q) for s, q in quotes.items() if q.get(key[0]) is not None]
    items.sort(key=lambda x: x[1][key[0]], reverse=key[1])
    rows = [RankingRow(i, s, q.get("name", ""), q.get("price"), q.get("change"), q.get("change_percent"),
                       q.get("volume_lots"), q.get("value_twd"), q.get("as_of"), source, RankScope.WATCHLIST, kind)
            for i, (s, q) in enumerate(items, 1)]
    as_of = max((r.as_of for r in rows if r.as_of), default=None)
    return Ranking(RankScope.WATCHLIST, kind, "自選", source, as_of, rows)
