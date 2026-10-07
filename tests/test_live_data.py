# -*- coding: utf-8 -*-
"""新單檔頁（真資料）view model：用 RAW_CAPTURE，不連網。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import live_data as ld
from data_bundle import DAILY, FUNDAMENTALS, INSTITUTIONAL, ORDER_BOOK, QUOTE, REVENUE
from data_license import BlockAudit, ViewerScope
from schema import MarketSession

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "tests" / "fixtures" / "raw"
TPE = timezone(timedelta(hours=8))


def raw(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def at(hms, day=7):
    h, m, s = (int(x) for x in hms.split(":"))
    return datetime(2026, 10, day, h, m, s, tzinfo=TPE)


def daily_df():
    idx = pd.bdate_range(end="2026-10-06", periods=80)
    c = pd.Series(range(80), index=idx, dtype=float) + 2400
    return pd.DataFrame({"Open": c, "High": c + 5, "Low": c - 5, "Close": c + 1, "Volume": 30_000_000.0})


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def fixture_fetchers(calls):
    def rec(kind, value):
        def f(symbol, **p):
            calls.append((kind, symbol, tuple(sorted(p.items()))))
            if isinstance(value, Exception):
                raise value
            return value
        return f
    c1 = raw("fugle_candles_2330_1m_20261007_112005.json")
    c5 = raw("fugle_candles_2330_5m_20261007_112011.json")

    def candles(symbol, timeframe=None, **_):
        calls.append(("candles", symbol, timeframe))
        return c1 if timeframe == "1" else c5
    return {ld.K_QUOTE: rec("quote", raw("fugle_quote_2330_20261007_0932.json")), ld.K_CANDLES: candles,
            ld.K_INST: rec("inst", raw("finmind_institutional_1416.json")),
            ld.K_REVENUE: rec("rev", raw("finmind_revenue_1711.json")),
            ld.K_DAILY: rec("daily", daily_df()), ld.K_INFO: rec("info", RuntimeError("yfinance 基本面為空"))}


def run(viewer=ViewerScope.OWNER, t=at("11:21:00"), audit=None):
    calls = []
    clock = Clock(t)
    coord = ld.make_coordinator(fixture_fetchers(calls), now=clock)
    res = ld.fetch_all(coord, "2330")
    return ld.build_view_model("2330", res, t, viewer, audit), coord, calls, clock


def test_viewer_scope_owner_only_when_email_listed():
    assert ld.viewer_scope("Me@X.com", ["me@x.com"]) == ViewerScope.OWNER
    assert ld.viewer_scope(None, ["me@x.com"]) == ViewerScope.EXTERNAL
    assert ld.viewer_scope("me@x.com", []) == ViewerScope.EXTERNAL
    assert ld.viewer_scope("other@x.com", ["me@x.com", ""]) == ViewerScope.EXTERNAL


def test_market_session():
    assert ld.market_session(at("09:00:00")) == MarketSession.OPEN
    assert ld.market_session(at("08:45:00")) == MarketSession.PRE_OPEN
    assert ld.market_session(at("13:31:00")) == MarketSession.CLOSED
    assert ld.market_session(datetime(2026, 10, 10, 10, 0, tzinfo=TPE)) == MarketSession.CLOSED   # 週六


def test_owner_sees_real_sections_and_engine_disabled():
    v, *_ = run()
    for name in (QUOTE, ORDER_BOOK, "1分K", "5分K", INSTITUTIONAL, REVENUE, DAILY):
        assert name in v.sections, name
    assert FUNDAMENTALS not in v.sections                    # yfinance info 失敗 → 不顯示
    assert any(l.section == FUNDAMENTALS and l.fetch_status == "抓取失敗" for l in v.status)
    assert v.engine_state == ld.ENGINE_DISABLED != ld.DATA_INSUFFICIENT
    assert v.name and v.value(QUOTE, "last_price") is not None and v.value(QUOTE, "reference_price") is not None
    assert v.flow is not None and v.flow.ask_ratio is not None and v.flow.classified_share is not None
    assert v.vwap_check is True                                # 自算 VWAP = 富果 avgPrice


def test_candle_states_use_fetch_time_and_are_listed():
    v, *_ = run()
    k1 = v.get("1分K")
    groups = ld.candle_rows_for_chart(k1)
    assert groups["SETTLED"] and groups["PROVISIONAL"]
    line = next(l for l in v.status if l.section == "1分K")
    assert "暫定" in line.note and "已穩定" in line.note


def test_external_viewer_blocks_per_section_and_audits():
    audit = BlockAudit()
    v, *_ = run(ViewerScope.EXTERNAL, audit=audit)
    assert v.sections == {} or all(s.source_name not in ("Fugle", "FinMind", "yfinance") for s in v.sections.values())
    assert not v.page_has_live_quote and v.flow is None
    assert {b[0] for b in v.blocked} >= {QUOTE, ORDER_BOOK, "1分K", INSTITUTIONAL, DAILY}
    assert all("尚未取得對外顯示授權" in b[2] for b in v.blocked)
    assert len(audit.records) == len(v.blocked)
    assert all(l.availability == "未授權對外顯示" for l in v.status if l.section in {b[0] for b in v.blocked})


def test_rerun_uses_cache_and_one_call_per_kind():
    v, coord, calls, clock = run()
    n = len(calls)
    assert n == 7                                            # quote、1分、5分、法人、營收、日K、基本面
    ld.fetch_all(coord, "2330")
    assert len(calls) == n                                   # 全部快取；基本面失敗在退避內不重打
    assert sum(1 for c in calls if c[0] == "quote") == 1
    clock.t += timedelta(seconds=6)
    ld.fetch_all(coord, "2330")
    assert sum(1 for c in calls if c[0] == "quote") == 2     # 報價 TTL 5 秒


def test_fugle_budget_respected():
    v, coord, calls, clock = run()
    assert coord.calls_last_minute("Fugle") == 3
    assert ld.FUGLE_BUDGET_PER_MINUTE < 60


def test_quote_failure_keeps_other_sections():
    calls = []
    f = fixture_fetchers(calls)
    f[ld.K_QUOTE] = lambda s, **p: (_ for _ in ()).throw(RuntimeError("HTTP 429"))
    coord = ld.make_coordinator(f, now=Clock(at("11:21:00")))
    v = ld.build_view_model("2330", ld.fetch_all(coord, "2330"), at("11:21:00"), ViewerScope.OWNER)
    assert QUOTE not in v.sections and "1分K" in v.sections and DAILY in v.sections
    assert any(l.section == QUOTE and "HTTP 429" in l.note for l in v.status)


def test_otc_suffix():
    assert ld.yf_suffix_for(raw("fugle_quote_6488_otc_20261007_113941.json")) == ".TWO"
    assert ld.yf_suffix_for(raw("fugle_quote_2330_20261007_0932.json")) == ".TW"
    assert ld.yf_suffix_for(None) == ".TW"


def test_fetchers_never_send_without_key():
    sent = []
    f = ld.make_fetchers(lambda: "", lambda: "", http_get=lambda *a, **k: sent.append(a))
    with pytest.raises(RuntimeError):
        f[ld.K_QUOTE]("2330")
    with pytest.raises(RuntimeError):
        f[ld.K_INST]("2330")
    assert sent == []


def test_fetchers_build_fugle_request():
    seen = {}

    class R:
        status_code = 200

        def json(self):
            return {"ok": 1}

    def get(url, **kw):
        seen.update(url=url, **kw)
        return R()
    f = ld.make_fetchers(lambda: "K", lambda: "T", http_get=get)
    f[ld.K_CANDLES]("2330", timeframe="5")
    assert seen["url"].endswith("/intraday/candles/2330") and seen["params"] == {"timeframe": "5"}
    assert seen["headers"] == {"X-API-KEY": "K"}


def test_after_close_freshness_wording():
    v, *_ = run(t=at("14:30:00"))
    line = next(l for l in v.status if l.section == QUOTE)
    assert line.freshness == ld.CLOSED_FRESHNESS_TEXT
    assert next(l for l in v.status if l.section == INSTITUTIONAL).freshness != ld.CLOSED_FRESHNESS_TEXT


def test_freshness_thresholds_are_named_settings():
    assert ld.FRESHNESS_MAX_AGE[QUOTE] == ld.QUOTE_STALE_SECONDS == 60
    assert ld.FRESHNESS_MAX_AGE["1分K"] == ld.CANDLE_1M_STALE_SECONDS > 120
