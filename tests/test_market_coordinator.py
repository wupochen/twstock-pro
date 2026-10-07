# -*- coding: utf-8 -*-
"""Gate 2.2：MarketDataCoordinator 與內外盤對帳。"""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import data_bundle as db
from intraday_flow import FlowQuality, ask_bid_breakdown, vwap_matches_avg_price
from market_coordinator import FetchStatus, MarketDataCoordinator, RequestKey, Source

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "tests" / "fixtures" / "raw"
T0 = datetime(2026, 10, 7, 2, 30, tzinfo=timezone.utc)      # 10:30 台北


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def tick(self, s):
        self.t += timedelta(seconds=s)


def _coord(fetch, *, ttl=5, budget=None, as_of=None, **kw):
    clk = Clock()
    c = MarketDataCoordinator({"quote": Source(fetch, "Fugle", ttl, as_of)}, now=clk,
                              api_budget_per_minute=budget, **kw)
    return c, clk


def test_ttl_cache_and_counts():
    calls = []
    c, clk = _coord(lambda s: calls.append(s) or {"s": s})
    assert c.get("quote", "2330").status == FetchStatus.FRESH
    assert c.get("quote", "2330").status == FetchStatus.CACHED
    clk.tick(5.1)
    assert c.get("quote", "2330").status == FetchStatus.FRESH
    assert calls == ["2330", "2330"]
    assert c.stats.api_calls["quote"] == 2 and c.stats.cache_hits["quote"] == 1


def test_request_key_includes_params():
    calls = []
    c = MarketDataCoordinator({"candles": Source(lambda s, **p: calls.append((s, p)) or [1], "Fugle", 60)})
    for tf in ("1", "5", "1", "15", "5"):
        c.get("candles", "2330", timeframe=tf)
    assert calls == [("2330", {"timeframe": "1"}), ("2330", {"timeframe": "5"}), ("2330", {"timeframe": "15"})]
    assert RequestKey.make("candles", "2330", timeframe="5", limit=None) == RequestKey.make("candles", "2330", timeframe="5")
    assert RequestKey.make("trades", "2330", limit=500, offset=0) == RequestKey.make("trades", "2330", offset=0, limit=500)
    assert RequestKey.make("candles", "2330", timeframe="5").label() == "candles:2330[timeframe=5]"


def test_programmer_errors_raise():
    c, _ = _coord(lambda s: {"s": s})
    with pytest.raises(ValueError):
        c.get("candles", "2330")                 # 沒設定的種類
    with pytest.raises(TypeError):
        c.get("quote", 2330)                     # 代號型別錯
    with pytest.raises(TypeError):
        c.get("quote", "2330", fields=["a"])     # 參數不能比對
    with pytest.raises(TypeError):
        MarketDataCoordinator({"quote": lambda s: s})
    with pytest.raises(ValueError):
        c.set_budget("Fugle", -1)


def test_get_many_dedups_symbols():
    calls = []
    c, _ = _coord(lambda s: calls.append(s) or {"s": s})
    out = c.get_many("quote", ["2330", "1711", "2330", "", "1711", "2317"])
    assert list(out) == ["2330", "1711", "2317"]
    assert sorted(calls) == ["1711", "2317", "2330"]


def test_source_failure_isolated():
    def f(s):
        if s == "BAD":
            raise ConnectionError("timeout")
        return {"s": s}
    c, _ = _coord(f)
    out = c.get_many("quote", ["2330", "BAD", "1711"])
    assert out["2330"].ok and out["1711"].ok
    bad = out["BAD"]
    assert not bad.ok and bad.status == FetchStatus.UNAVAILABLE and "timeout" in bad.error
    assert bad.last_attempt_at == T0 and bad.last_success_at is None


def test_stale_keeps_three_times_apart():
    state = {"fail": False}

    def f(s):
        if state["fail"]:
            raise ConnectionError("down")
        return {"t": T0 - timedelta(seconds=2)}          # 資料本身 10:29:58
    c, clk = _coord(f, as_of=lambda v: v["t"], error_backoff_seconds=10)
    ok = c.get("quote", "2330")
    assert ok.data_as_of == T0 - timedelta(seconds=2) and ok.last_success_at == T0 and ok.error == ""
    state["fail"] = True
    clk.tick(61)                                        # 10:31:01 重試失敗
    r = c.get("quote", "2330")
    assert r.status == FetchStatus.STALE_AFTER_ERROR and r.is_stale and "down" in r.error
    assert r.data_as_of == T0 - timedelta(seconds=2)    # 資料時間不變
    assert r.last_success_at == T0                      # 成功時間不變
    assert r.last_attempt_at == T0 + timedelta(seconds=61)
    # 退避期間不重打
    n = c.stats.api_calls["quote"]
    clk.tick(3)
    assert c.get("quote", "2330").status == FetchStatus.STALE_AFTER_ERROR
    assert c.stats.api_calls["quote"] == n
    # 退避結束、來源恢復
    state["fail"] = False
    clk.tick(10)
    r = c.get("quote", "2330")
    assert r.status == FetchStatus.FRESH and r.error == "" and r.last_success_at == r.last_attempt_at


def test_none_from_source_is_a_failure_not_data():
    c, _ = _coord(lambda s: None)
    r = c.get("quote", "2330")
    assert not r.ok and r.status == FetchStatus.UNAVAILABLE and "空值" in r.error


def test_budget_is_config_per_provider():
    calls = []
    clk = Clock()
    c = MarketDataCoordinator({"quote": Source(lambda s: calls.append(("q", s)) or 1, "Fugle", 5),
                               "inst": Source(lambda s: calls.append(("i", s)) or 1, "FinMind", 5)},
                              api_budget_per_minute={"Fugle": 3}, now=clk)
    for s in ("A", "B", "C"):
        c.get("quote", s)
    clk.tick(6)
    r = c.get("quote", "A")
    assert r.status == FetchStatus.RATE_LIMITED and r.value == 1 and r.is_stale
    assert c.get("quote", "D").status == FetchStatus.UNAVAILABLE
    assert c.get("inst", "A").status == FetchStatus.FRESH        # 另一個提供者不受影響
    assert c.calls_last_minute("Fugle") == 3 and c.calls_last_minute("FinMind") == 0
    c.set_budget("Fugle", None)                                   # 後台改設定
    assert c.get("quote", "D").status == FetchStatus.FRESH


def test_concurrent_requests_for_same_key_fetch_once():
    calls, gate = [], threading.Event()

    def f(s):
        calls.append(s)
        gate.wait(1)
        return {"s": s}
    c = MarketDataCoordinator({"quote": Source(f, "Fugle", 60)})
    ts = [threading.Thread(target=c.get, args=("quote", "2330")) for _ in range(6)]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join()
    assert calls == ["2330"]


def test_stats_and_invalidate():
    c, _ = _coord(lambda s: {"s": s})
    c.get("quote", "2330"); c.get("quote", "2330")
    assert c.stats.summary() == ["quote：打 API 1 次、用快取 1 次、失敗 0 次、因上限略過 0 次"]
    assert c.invalidate(symbol="2330") == 1


def test_six_cells_rerun_does_not_refetch():
    at = AppTest.from_file(str(ROOT / "tests" / "apps" / "coord_grid_app.py"), default_timeout=60).run()
    assert not at.exception
    for _ in range(4):
        at.button[0].click().run()
    calls = at.session_state["_calls"]
    # 6 格（9991 出現兩次但畫面不同 → 兩個鍵），5 次 rerun 仍是每個鍵一次
    assert sorted(calls, key=str) == sorted([("9991", None), ("9992", "5"), ("9993", None), ("9991", "5"),
                                             ("9996", None), ("9994", "5")], key=str)
    h = "\n".join(m.value for m in at.markdown)
    assert h.count(":CACHED") == 5 and "9996/quote:UNAVAILABLE" in h


def _quote(mut=None):
    raw = json.loads((RAW / "fugle_quote_2330_20261007_0932.json").read_text(encoding="utf-8"))
    if mut:
        mut(raw["total"])
    return db.fugle_quote(raw, datetime(2026, 10, 7, 1, 32, 6, tzinfo=timezone.utc))


def test_ask_bid_chain_on_real_2330():
    sec = _quote()
    b = ask_bid_breakdown(sec)
    assert (b.total, b.at_ask, b.at_bid, b.unclassified) == (4904, 1383, 948, 2573)
    assert b.consistent and round(b.ask_ratio, 4) == round(1383 / 2331, 4)
    assert round(b.classified_share, 3) == 0.475
    assert b.quality == FlowQuality.LOW_COVERAGE                 # 47.5% < 50%
    assert b.display_pair() == ("外盤比：59.3%", "可歸類成交：47.5%")
    assert b.ask_ratio == sec.items["ask_ratio"].value           # 與 data_bundle 同一公式
    assert vwap_matches_avg_price(sec) is True
    assert sec.items["vwap"].data_kind.name == "CALC"


def test_ask_bid_edge_cases():
    b = ask_bid_breakdown(_quote(lambda t: t.pop("tradeVolumeAtBid")))
    assert b.ask_ratio is None and b.quality == FlowQuality.UNAVAILABLE
    b = ask_bid_breakdown(_quote(lambda t: t.update(tradeVolumeAtBid=9999)))
    assert not b.consistent and b.quality == FlowQuality.INCONSISTENT
    b = ask_bid_breakdown(_quote(lambda t: t.update(tradeVolumeAtBid=0, tradeVolumeAtAsk=0)))
    assert b.ask_ratio is None and b.quality == FlowQuality.UNAVAILABLE   # 不是 0%
    assert b.display_pair()[0] == "外盤比：—"
    b = ask_bid_breakdown(_quote(lambda t: t.update(tradeVolumeAtBid=2000, tradeVolumeAtAsk=2500)))
    assert b.quality == FlowQuality.NORMAL


def test_module_is_isolated():
    for name in ("market_coordinator.py", "intraday_flow.py"):
        src = (ROOT / name).read_text(encoding="utf-8")
        imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
        for mod in ("streamlit", "everlight_app", "requests", "fugle", "yfinance", "FinMind"):
            assert not any(mod in l for l in imports), (name, mod)
    assert "watchlist" not in (ROOT / "market_coordinator.py").read_text(encoding="utf-8").lower()
