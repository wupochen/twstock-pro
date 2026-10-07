# -*- coding: utf-8 -*-
"""Gate 2.2：MarketDataCoordinator 與內外盤對帳。"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

import data_bundle as db
from intraday_flow import ask_bid_breakdown, vwap_matches_avg_price
from market_coordinator import FetchStatus, MarketDataCoordinator

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "tests" / "fixtures" / "raw"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _coord(fetch, **kw):
    clk = Clock()
    kw.setdefault("ttl", {"quote": 5})
    return MarketDataCoordinator({"quote": fetch}, clock=clk, **kw), clk


def test_ttl_cache_and_counts():
    calls = []
    c, clk = _coord(lambda s: calls.append(s) or {"s": s})
    assert c.get("quote", "2330").status == FetchStatus.FRESH
    assert c.get("quote", "2330").status == FetchStatus.CACHED
    clk.t += 5.1
    assert c.get("quote", "2330").status == FetchStatus.FRESH
    assert calls == ["2330", "2330"]
    assert c.stats.api_calls["quote"] == 2 and c.stats.cache_hits["quote"] == 1


def test_get_many_dedups_symbols():
    calls = []
    c, _ = _coord(lambda s: calls.append(s) or {"s": s})
    out = c.get_many("quote", ["2330", "1711", "2330", "", "1711", "2317"])
    assert list(out) == ["2330", "1711", "2317"]
    assert sorted(calls) == ["1711", "2317", "2330"]


def test_single_symbol_failure_isolated_and_never_raises():
    def f(s):
        if s == "BAD":
            raise ConnectionError("timeout")
        return {"s": s}
    c, _ = _coord(f)
    out = c.get_many("quote", ["2330", "BAD", "1711"])
    assert out["2330"].ok and out["1711"].ok
    bad = out["BAD"]
    assert not bad.ok and bad.status == FetchStatus.UNAVAILABLE and "timeout" in bad.error


def test_failure_after_success_serves_last_good_marked_stale():
    state = {"fail": False}

    def f(s):
        if state["fail"]:
            raise ConnectionError("down")
        return {"px": 100}
    c, clk = _coord(f, error_backoff=10)
    c.get("quote", "2330")
    state["fail"] = True
    clk.t += 6
    r = c.get("quote", "2330")
    assert r.status == FetchStatus.STALE_AFTER_ERROR and r.value == {"px": 100} and r.is_stale
    assert r.age_seconds == 6
    # 退避期間不重打
    n = c.stats.api_calls["quote"]
    clk.t += 3
    assert c.get("quote", "2330").status == FetchStatus.STALE_AFTER_ERROR
    assert c.stats.api_calls["quote"] == n
    # 退避結束、來源恢復
    state["fail"] = False
    clk.t += 10
    assert c.get("quote", "2330").status == FetchStatus.FRESH


def test_none_from_source_is_a_failure_not_data():
    c, _ = _coord(lambda s: None)
    r = c.get("quote", "2330")
    assert not r.ok and r.status == FetchStatus.UNAVAILABLE


def test_rate_limit_stops_calling_and_serves_cache():
    calls = []
    c, clk = _coord(lambda s: calls.append(s) or {"s": s}, max_calls_per_minute=3)
    for s in ("A", "B", "C"):
        c.get("quote", s)
    clk.t += 6                              # TTL 過了，但這一分鐘額度用完
    r = c.get("quote", "A")
    assert r.status == FetchStatus.RATE_LIMITED and r.value == {"s": "A"}
    assert c.get("quote", "D").status == FetchStatus.UNAVAILABLE
    assert len(calls) == 3 and c.calls_last_minute() == 3
    clk.t += 60
    assert c.get("quote", "A").status == FetchStatus.FRESH


def test_concurrent_requests_for_same_symbol_fetch_once():
    calls, gate = [], threading.Event()

    def f(s):
        calls.append(s)
        gate.wait(1)
        return {"s": s}
    c = MarketDataCoordinator({"quote": f}, ttl={"quote": 60})
    ts = [threading.Thread(target=c.get, args=("quote", "2330")) for _ in range(6)]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join()
    assert calls == ["2330"]


def test_unknown_kind_and_stats_text():
    c, _ = _coord(lambda s: {"s": s})
    assert c.get("candles", "2330").status == FetchStatus.UNAVAILABLE
    c.get("quote", "2330"); c.get("quote", "2330")
    assert c.stats.summary() == ["quote：打 API 1 次、用快取 1 次、失敗 0 次、因上限略過 0 次"]
    assert c.invalidate(symbol="2330") == 1


def test_six_cells_rerun_does_not_refetch():
    at = AppTest.from_file(str(ROOT / "tests" / "apps" / "coord_grid_app.py"), default_timeout=60).run()
    assert not at.exception
    for _ in range(4):
        at.button[0].click().run()
    calls = at.session_state["_calls"]
    assert sorted(calls) == ["9991", "9992", "9993", "9994", "9996"]   # 6 格 5 檔，5 次 rerun 仍各一次
    h = "\n".join(m.value for m in at.markdown)
    assert h.count(":CACHED") == 5 and "9996:UNAVAILABLE" in h          # 壞掉那格只壞自己


def test_ask_bid_chain_on_real_2330():
    raw = json.loads((RAW / "fugle_quote_2330_20261007_0932.json").read_text(encoding="utf-8"))
    sec = db.fugle_quote(raw, datetime(2026, 10, 7, 1, 32, 6, tzinfo=timezone.utc))
    b = ask_bid_breakdown(sec)
    assert (b.total, b.at_ask, b.at_bid, b.unclassified) == (4904, 1383, 948, 2573)
    assert b.consistent and round(b.ask_ratio, 4) == round(1383 / 2331, 4)
    assert round(b.classified_share, 3) == 0.475
    assert b.ask_ratio == sec.items["ask_ratio"].value      # 與 data_bundle 同一公式
    assert vwap_matches_avg_price(sec) is True


def test_ask_bid_incomplete_and_inconsistent():
    raw = json.loads((RAW / "fugle_quote_2330_20261007_0932.json").read_text(encoding="utf-8"))
    raw["total"].pop("tradeVolumeAtBid")
    sec = db.fugle_quote(raw, datetime(2026, 10, 7, 1, 32, tzinfo=timezone.utc))
    assert ask_bid_breakdown(sec).ask_ratio is None
    raw["total"]["tradeVolumeAtBid"] = 9999
    sec = db.fugle_quote(raw, datetime(2026, 10, 7, 1, 32, tzinfo=timezone.utc))
    assert not ask_bid_breakdown(sec).consistent


def test_module_is_isolated():
    for name in ("market_coordinator.py", "intraday_flow.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
        for mod in ("streamlit", "everlight_app", "requests", "fugle", "yfinance", "FinMind"):
            assert not any(mod in l for l in imports), (name, mod)
