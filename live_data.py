# -*- coding: utf-8 -*-
"""新單檔頁（真資料）的資料層：抓取設定＋把原始資料組成畫面要用的 view model。

- 不 import streamlit（可以用 RAW_CAPTURE 測試）。
- 所有抓取都經過 MarketDataCoordinator（快取、限流、失敗沿用上一次）。
- 每個資料區塊都經過 data_license.filter_displayable_sections（以區塊為單位擋，不整頁封）。
- 判斷引擎（Gate 2.4）還沒接：三格固定顯示 ENGINE_DISABLED「判斷引擎尚未啟用」，
  和 DATA_INSUFFICIENT「資料不足」是兩種不同狀態，不可混用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from candles import (PROVISIONAL, SETTLED, candle_section_name, candles_as_of, fugle_candles)
from data_bundle import (DAILY, FUNDAMENTALS, INSTITUTIONAL, ORDER_BOOK, QUOTE, REVENUE, TPE, Availability,
                         DataBundle, Freshness, Section, SourceError, assess_freshness, build_bundle,
                         from_epoch_us, require_aware)
from data_license import BlockAudit, ViewerScope, filter_displayable_sections
from intraday_flow import AskBidBreakdown, ask_bid_breakdown, vwap_matches_avg_price
from market_coordinator import FetchResult, FetchStatus, MarketDataCoordinator, Source
from pricing import asset_info
from schema import MarketSession

# ── 判斷引擎狀態（Gate 2.4 前固定）──────────────────────────
ENGINE_DISABLED = "判斷引擎尚未啟用"
DATA_INSUFFICIENT = "資料不足"          # 給引擎啟用後用；現在畫面不會出現在三格
ENGINE_DISABLED_WHY = "方向、風險、能不能做的判斷規則還在開發（下一階段），這裡先不給結論。"

# ── 抓取種類（coordinator kind）────────────────────────────
K_QUOTE = "fugle_quote"
K_CANDLES = "fugle_candles"
K_INST = "finmind_inst"
K_REVENUE = "finmind_revenue"
K_DAILY = "yf_daily"
K_INFO = "yf_info"

FUGLE_BASE = "https://api.fugle.tw/marketdata/v1.0/stock/intraday"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

# 新鮮度門檻（秒）：UI operational threshold，只用來標「最新／過期」，不是市場規則；之後可由後台調整
QUOTE_STALE_SECONDS = 60
ORDER_BOOK_STALE_SECONDS = 60
CANDLE_1M_STALE_SECONDS = 180      # 1 分 K 有 120 秒 settle，再加傳輸餘裕
CANDLE_5M_STALE_SECONDS = 420
FRESHNESS_MAX_AGE = {QUOTE: QUOTE_STALE_SECONDS, ORDER_BOOK: ORDER_BOOK_STALE_SECONDS,
                     "1分K": CANDLE_1M_STALE_SECONDS, "5分K": CANDLE_5M_STALE_SECONDS}
CLOSED_FRESHNESS_TEXT = "市場已收盤，不以盤中門檻判斷新鮮度"
FUGLE_BUDGET_PER_MINUTE = 50          # 免費方案 60/分，留 10 次餘裕給其他頁面


# ════════════════════════════════════════════════
# 觀看者
# ════════════════════════════════════════════════
def viewer_scope(email: Optional[str], owner_emails: Iterable[str]) -> ViewerScope:
    """登入 email 在擁有者清單內才是 OWNER；沒登入、清單空、不在清單 → EXTERNAL。"""
    owners = {e.strip().lower() for e in owner_emails if e and e.strip()}
    if email and email.strip().lower() in owners:
        return ViewerScope.OWNER
    return ViewerScope.EXTERNAL


def market_session(now: datetime) -> MarketSession:
    """台股一般交易時段（不含假日表；假日表之後接交易所行事曆）。"""
    t = require_aware(now, "now").astimezone(TPE)
    if t.weekday() >= 5:
        return MarketSession.CLOSED
    if t.time() < time(8, 30):
        return MarketSession.CLOSED
    if t.time() < time(9, 0):
        return MarketSession.PRE_OPEN
    if t.time() <= time(13, 30):
        return MarketSession.OPEN
    return MarketSession.CLOSED


# ════════════════════════════════════════════════
# 抓取函式（http_get 可注入；預設 requests.get）
# ════════════════════════════════════════════════
def _http_get(http_get, url, **kw):
    if http_get is None:
        import requests
        http_get = requests.get
    r = http_get(url, timeout=kw.pop("timeout", 8), **kw)
    if getattr(r, "status_code", 200) != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.json()


def make_fetchers(fugle_key: Callable[[], str], finmind_token: Callable[[], str], http_get=None,
                  yf_module=None, today: Callable[[], date] = lambda: datetime.now(TPE).date()) -> Dict[str, Callable]:
    """回傳 {kind: fetch(symbol, **params)}。金鑰用函式取得，不存在物件裡。"""

    def fugle(path):
        def f(symbol, **params):
            key = fugle_key()
            if not key:
                raise RuntimeError("沒有設定 FUGLE_TOKEN")
            return _http_get(http_get, f"{FUGLE_BASE}/{path}/{symbol}", headers={"X-API-KEY": key},
                             params={k: v for k, v in params.items() if v is not None} or None)
        return f

    def finmind(dataset, days):
        def f(symbol, **_):
            tok = finmind_token()
            if not tok:
                raise RuntimeError("沒有設定 FINMIND_TOKEN")
            start = (today() - timedelta(days=days)).isoformat()
            return _http_get(http_get, FINMIND_URL, headers={"Authorization": f"Bearer {tok}"},
                             params={"dataset": dataset, "data_id": symbol, "start_date": start}, timeout=12)
        return f

    def yf():
        if yf_module is not None:
            return yf_module
        import yfinance
        return yfinance

    def yf_daily(symbol, suffix=".TW", **_):
        df = yf().Ticker(symbol + suffix).history(period="1y", interval="1d", auto_adjust=False)
        if df is None or len(df) == 0:
            raise RuntimeError(f"yfinance 沒有 {symbol}{suffix} 的日K")
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_convert(TPE).tz_localize(None)
        return df

    def yf_info(symbol, suffix=".TW", **_):
        info = yf().Ticker(symbol + suffix).info
        if not isinstance(info, dict) or not info:
            raise RuntimeError("yfinance 基本面為空")
        return info

    return {K_QUOTE: fugle("quote"), K_CANDLES: fugle("candles"),
            K_INST: finmind("TaiwanStockInstitutionalInvestorsBuySell", 60),
            K_REVENUE: finmind("TaiwanStockMonthRevenue", 800),
            K_DAILY: yf_daily, K_INFO: yf_info}


def _quote_as_of(raw):
    return from_epoch_us(raw.get("lastUpdated")) if isinstance(raw, dict) else None


def make_coordinator(fetchers: Dict[str, Callable], now=None) -> MarketDataCoordinator:
    kw = {"now": now} if now else {}
    return MarketDataCoordinator({
        K_QUOTE: Source(fetchers[K_QUOTE], "Fugle", ttl_seconds=5, as_of=_quote_as_of),
        K_CANDLES: Source(fetchers[K_CANDLES], "Fugle", ttl_seconds=15, as_of=candles_as_of),
        K_INST: Source(fetchers[K_INST], "FinMind", ttl_seconds=1800),
        K_REVENUE: Source(fetchers[K_REVENUE], "FinMind", ttl_seconds=3600),
        K_DAILY: Source(fetchers[K_DAILY], "yfinance", ttl_seconds=600),
        K_INFO: Source(fetchers[K_INFO], "yfinance", ttl_seconds=3600),
    }, api_budget_per_minute={"Fugle": FUGLE_BUDGET_PER_MINUTE}, error_backoff_seconds=15, **kw)


def fetch_all(coord: MarketDataCoordinator, symbol: str, yf_suffix: str = ".TW") -> Dict[str, FetchResult]:
    """一次頁面更新要的全部資料（每種 1 次；快取內不會重打）。"""
    return {
        K_QUOTE: coord.get(K_QUOTE, symbol),
        "candles_1": coord.get(K_CANDLES, symbol, timeframe="1"),
        "candles_5": coord.get(K_CANDLES, symbol, timeframe="5"),
        K_INST: coord.get(K_INST, symbol),
        K_REVENUE: coord.get(K_REVENUE, symbol),
        K_DAILY: coord.get(K_DAILY, symbol, suffix=yf_suffix),
        K_INFO: coord.get(K_INFO, symbol, suffix=yf_suffix),
    }


def yf_suffix_for(quote_raw: Optional[dict]) -> str:
    """上櫃（富果 market=OTC）用 .TWO，其餘 .TW。"""
    return ".TWO" if isinstance(quote_raw, dict) and quote_raw.get("market") == "OTC" else ".TW"


# ════════════════════════════════════════════════
# View model
# ════════════════════════════════════════════════
@dataclass
class FetchLine:
    """資料狀況清單的一行（含抓取狀態，例如「抓取失敗，沿用上一次資料」）。"""
    section: str
    source: str
    as_of: Optional[datetime]
    availability: str
    freshness: str
    fetch_status: str
    note: str = ""


@dataclass
class LiveView:
    symbol: str
    viewer: ViewerScope
    session: MarketSession
    now: datetime
    name: str = ""
    market: str = ""
    sections: Dict[str, Section] = field(default_factory=dict)      # 只放可顯示的
    blocked: List[Tuple[str, str, str]] = field(default_factory=list)  # (區塊, 來源, 白話原因)
    flow: Optional[AskBidBreakdown] = None
    vwap_check: Optional[bool] = None
    engine_state: str = ENGINE_DISABLED
    engine_why: str = ENGINE_DISABLED_WHY
    status: List[FetchLine] = field(default_factory=list)
    errors: List[SourceError] = field(default_factory=list)

    def get(self, name: str) -> Optional[Section]:
        return self.sections.get(name)

    def value(self, sec: str, key: str):
        s = self.sections.get(sec)
        return s.items[key].value if s and key in s.items else None

    @property
    def page_has_live_quote(self) -> bool:
        return QUOTE in self.sections


def _status_text(r: Optional[FetchResult]) -> str:
    if r is None:
        return "沒有抓"
    return {FetchStatus.FRESH: "剛抓到", FetchStatus.CACHED: "用快取"}.get(r.status, r.status.value)


def build_view_model(symbol: str, results: Dict[str, Optional[FetchResult]], now: datetime,
                     viewer: ViewerScope, audit: Optional[BlockAudit] = None) -> LiveView:
    """原始抓取結果 → 畫面資料。純函式（除了寫 audit）。"""
    now = require_aware(now, "now")
    session = market_session(now)
    raw = lambda k: (results.get(k).value if results.get(k) is not None and results.get(k).ok else None)  # noqa: E731
    q = raw(K_QUOTE)
    failed = {}
    for k, sec_name, src in ((K_QUOTE, QUOTE, "Fugle"), (K_INST, INSTITUTIONAL, "FinMind"),
                             (K_REVENUE, REVENUE, "FinMind"), (K_DAILY, DAILY, "yfinance"),
                             (K_INFO, FUNDAMENTALS, "yfinance")):
        r = results.get(k)
        if r is not None and not r.ok:
            failed[sec_name] = (src, r.error or "沒有資料")
    meta = {"type": "ETF"} if isinstance(q, dict) and q.get("type") == "ETF" else None
    bundle: DataBundle = build_bundle(
        symbol, now, asset_info=asset_info(symbol, meta), market_session=session,
        fugle_quote_raw=q, finmind_inst_raw=raw(K_INST), finmind_revenue_raw=raw(K_REVENUE),
        yf_daily_df=raw(K_DAILY), yf_info=raw(K_INFO), today=now.astimezone(TPE).date(), failed=failed)

    # K 線（富果）：fetched_at 用「實際抓到的時間」，不是畫面時間（快取時兩者不同）
    for tf in (1, 5):
        r = results.get(f"candles_{tf}")
        name = candle_section_name(tf)
        if r is not None and r.ok:
            bundle.add(name, "Fugle", lambda r=r, tf=tf: fugle_candles(r.value, r.last_success_at or now, tf))
        elif r is not None:
            bundle.errors.append(SourceError(name, "Fugle", r.error or "沒有資料"))

    # 報價區塊的 fetched_at 也改成實際抓到時間
    rq = results.get(K_QUOTE)
    for nm in (QUOTE, ORDER_BOOK):
        s = bundle.get(nm)
        if s is not None and rq is not None and rq.last_success_at:
            s.fetched_at = rq.last_success_at

    for nm, age in FRESHNESS_MAX_AGE.items():
        s = bundle.get(nm)
        if s is not None and session == MarketSession.OPEN:
            assess_freshness(s, now, age)

    shown, blocked = filter_displayable_sections(bundle.sections.values(), viewer, "單檔頁", audit)
    view = LiveView(symbol, viewer, session, now,
                    name=str(q.get("name") or "") if isinstance(q, dict) else "",
                    market=str(q.get("market") or "") if isinstance(q, dict) else "",
                    sections={s.name: s for s in shown},
                    blocked=[(s.name, s.source_name, why) for s, why in blocked],
                    errors=list(bundle.errors))
    if QUOTE in view.sections:
        view.flow = ask_bid_breakdown(view.sections[QUOTE])
        view.vwap_check = vwap_matches_avg_price(view.sections[QUOTE])

    kind_of = {QUOTE: K_QUOTE, ORDER_BOOK: K_QUOTE, "1分K": "candles_1", "5分K": "candles_5", INSTITUTIONAL: K_INST,
               REVENUE: K_REVENUE, DAILY: K_DAILY, FUNDAMENTALS: K_INFO}
    blocked_names = {b[0] for b in view.blocked}
    for s in bundle.sections.values():
        if s.name in blocked_names:
            view.status.append(FetchLine(s.name, s.source_name, None, "未授權對外顯示", "—", "—",
                                         "只有網站擁有者看得到"))
            continue
        r = results.get(kind_of.get(s.name, ""))
        note = s.note
        if s.name.endswith("分K"):
            settled_n = sum(1 for row in s.rows if row["state"] == SETTLED)
            prov_n = len(s.rows) - settled_n
            note = f"已穩定 {settled_n} 根、暫定 {prov_n} 根（暫定的可能被資料源修正）"
        fresh = s.freshness.value
        if s.name in FRESHNESS_MAX_AGE and session != MarketSession.OPEN:
            fresh = CLOSED_FRESHNESS_TEXT
        view.status.append(FetchLine(s.name, s.source_name, s.as_of, s.availability.value,
                                     fresh, _status_text(r), note))
    for e in bundle.errors:
        view.status.append(FetchLine(e.section, e.source_name, None, Availability.UNAVAILABLE.value,
                                     Freshness.UNKNOWN.value, "抓取失敗", e.message))
    return view


def rendered_sources(view: LiveView) -> List[str]:
    """這次畫面實際顯示的來源（給 capabilities.multi_user_display）。"""
    return sorted({s.source_name for s in view.sections.values()})


def candle_rows_for_chart(sec: Section) -> Dict[str, list]:
    """K 線圖用：分成已穩定／暫定兩組，畫面要標示暫定的那幾根。"""
    out = {SETTLED: [], PROVISIONAL: []}
    for r in sec.rows:
        out[r["state"]].append(r)
    return out
