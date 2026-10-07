# -*- coding: utf-8 -*-
"""Gate 2.2：富果 K 線／大盤 adapter（全部用 2026-10-07 盤中 RAW_CAPTURE）。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import candles as cd
import data_bundle as db
from market_coordinator import FetchStatus, MarketDataCoordinator, Source

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "tests" / "fixtures" / "raw"
TPE = timezone(timedelta(hours=8))


def raw(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def at(hms):
    h, m, s = (int(x) for x in hms.split(":"))
    return datetime(2026, 10, 7, h, m, s, tzinfo=TPE)


def test_all_new_fixtures_are_declared_raw_capture():
    origins = json.loads((RAW / "ORIGINS.json").read_text(encoding="utf-8"))
    for p in RAW.glob("fugle_*_20261007_11*.json"):
        assert origins[p.name]["origin"] == "RAW_CAPTURE", p.name


def test_bar_time_is_start_sorted_and_volume_in_lots():
    sec = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112005.json"), at("11:20:05"), 1)
    assert sec.meta["time_semantics"] == "bar_start" and sec.meta["volume_unit"] == "lots"
    assert sec.rows[0]["start"] == at("09:00:00") and sec.rows[0]["end"] == at("09:01:00")
    starts = [r["start"] for r in sec.rows]
    assert starts == sorted(starts)
    early = sum(r["volume"] for r in sec.rows if r["start"] < at("09:32:00"))
    q = raw("fugle_quote_2330_20261007_0932.json")
    assert early == 4901 and q["total"]["tradeVolume"] - early == 3      # 與報價總量（張）只差 09:32 那根
    assert sec.as_of == at("11:19:00") and sec.source_type.name == "VENDOR"


def test_average_is_day_vwap():
    sec = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112005.json"), at("11:20:05"), 1)
    by = {r["start"]: r for r in sec.rows}
    assert by[at("09:31:00")]["day_average"] <= 2568.99 <= by[at("09:32:00")]["day_average"]


def test_bars_are_provisional_until_settle_lag_and_revisions_are_real():
    first = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112005.json"), at("11:20:05"), 1)
    later = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112650.json"), at("11:26:50"), 1)
    a = {r["start"]: r for r in first.rows}[at("11:19:00")]
    b = {r["start"]: r for r in later.rows}[at("11:19:00")]
    assert (a["volume"], a["close"]) == (21, 2575) and (b["volume"], b["close"]) == (30, 2570)   # 真的被修正
    assert a["state"] == cd.PROVISIONAL and b["state"] == cd.SETTLED          # 結束後 5 秒暫定；6 分多鐘後 SETTLED
    assert first.meta["has_final_flag"] is False
    # 資料源沒有「已定案」欄位
    assert set(raw("fugle_candles_2330_1m_20261007_112005.json")["data"][0]) == \
        {"date", "open", "high", "low", "close", "volume", "average"}
    assert all(r["state"] == cd.SETTLED for r in cd.settled_bars(first))
    assert all(r["state"] == cd.PROVISIONAL for r in cd.provisional_bars(first))
    # 結束後 120 秒才 SETTLED：11:20:05 時，11:17 那根（11:18 結束）剛好過 2 分鐘 → 最後 SETTLED 是 11:17
    assert first.meta["latest_bar_as_of"] == at("11:19:00")
    assert first.meta["latest_settled_bar_as_of"] == at("11:17:00")
    with pytest.raises(ValueError):
        cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112005.json"), at("11:20:05"), 1, settle_seconds=30)


def test_revision_study_supports_settle_seconds():
    study = raw("fugle_candles_revision_study_20261007.json")
    r = cd.revision_lags(study["obs"])
    assert r["2330"]["watched"] == 37 and r["1711"]["watched"] == 37
    assert r["2330"]["revised_after_end"] + r["1711"]["revised_after_end"] == 29
    worst = max(r["2330"]["max_lag"], r["1711"]["max_lag"])
    assert worst == 18 and worst * 6 <= cd.DEFAULT_SETTLE_SECONDS < 60 * 5
    assert r["2701"]["revised_after_end"] == 0


def test_5m_boundaries_and_matches_settled_1m():
    m5 = cd.fugle_candles(raw("fugle_candles_2330_5m_20261007_112656.json"), at("11:26:56"), 5)
    assert all(r["start"].minute % 5 == 0 and r["start"].second == 0 for r in m5.rows)
    m1 = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112650.json"), at("11:26:50"), 1)
    settled = cd.settled_bars(m1)
    last_end = settled[-1]["end"]
    agg = {b["start"]: b for b in cd.aggregate(settled, 5) if b["end"] <= last_end}
    same = [r for r in m5.rows if r["start"] in agg]
    assert len(same) >= 24
    for r in same:
        a = agg[r["start"]]
        assert (a["open"], a["high"], a["low"], a["close"], a["volume"]) == \
               (r["open"], r["high"], r["low"], r["close"], r["volume"]), r["start"]
    with pytest.raises(ValueError):
        cd.aggregate(m1.rows, 5)               # 含暫定 K 棒不准聚合


def test_low_liquidity_no_filler_bars():
    sec = cd.fugle_candles(raw("fugle_candles_1438_1m_lowliq_20261007_112221.json"), at("11:22:21"), 1)
    assert [r["start"] for r in sec.rows] == [at("10:56:00"), at("11:07:00")]
    assert all(r["volume"] > 0 for r in sec.rows)
    s2701 = cd.fugle_candles(raw("fugle_candles_2701_5m_lowliq_20261007_112243.json"), at("11:22:43"), 5)
    assert len(s2701.rows) == 7


def test_wrong_timeframe_or_order_or_empty():
    r = raw("fugle_candles_2330_5m_20261007_112011.json")
    with pytest.raises(ValueError):
        cd.fugle_candles(r, at("11:20:11"), 1)
    bad = dict(r, data=list(reversed(r["data"])))
    with pytest.raises(ValueError):
        cd.fugle_candles(bad, at("11:20:11"), 5)
    empty = cd.fugle_candles(dict(r, data=[]), at("09:00:30"), 5)
    assert empty.availability == db.Availability.UNAVAILABLE and empty.as_of is None
    with pytest.raises(ValueError):
        cd.fugle_candles(r, datetime(2026, 10, 7, 11, 20), 5)     # 沒時區


def test_bundle_metadata_and_status_line():
    b = db.DataBundle("2330")
    b.add("5分K", "Fugle", lambda: cd.fugle_candles(raw("fugle_candles_2330_5m_20261007_112011.json"), at("11:20:11"), 5))
    sec = b.get("5分K")
    assert sec.meta["settle_seconds"] == 120 and sec.meta["as_of_means"] and sec.meta["latest_settled_bar_as_of"] is not None
    assert "5分K：Fugle（VENDOR），資料時間 2026-10-07 11:20:00" in b.data_status_text()[0]


def test_index_quote():
    s1 = cd.fugle_index_quote(raw("fugle_quote_IX0001_20261007_112047.json"), at("11:20:47"))
    assert s1.items["last"].value == 49722.62 and s1.items["change"].value == -99.93
    assert s1.meta["trade_volume_unit"].startswith("未確認") and "發行量加權" in s1.name
    s2 = cd.fugle_index_quote(raw("fugle_quote_IX0043_20261007_112052.json"), at("11:20:52"))
    assert s2.items["last"].value is not None
    with pytest.raises(ValueError):
        cd.fugle_index_quote(raw("fugle_quote_2330_20261007_0932.json"), at("09:32:06"))


def test_snapshot_is_forbidden_on_current_plan():
    assert raw("fugle_snapshot_actives_TSE_403_20261007_112102.json") == {"message": "Forbidden", "statusCode": 403}


def test_trades_default_newest_first_and_lots():
    t = raw("fugle_trades_2330_limit50_20261007_112127.json")["data"]
    assert len(t) == 50 and t[0]["serial"] > t[-1]["serial"] and t[0]["volume"] > t[-1]["volume"]


def test_coordinator_candles_keys_and_as_of():
    calls = []
    payload = {"1": raw("fugle_candles_2330_1m_20261007_112005.json"), "5": raw("fugle_candles_2330_5m_20261007_112011.json")}

    def fetch(sym, timeframe):
        calls.append((sym, timeframe))
        return payload[timeframe]
    c = MarketDataCoordinator({"candles": Source(fetch, "Fugle", 30, cd.candles_as_of)})
    r1 = c.get("candles", "2330", timeframe="1")
    r5 = c.get("candles", "2330", timeframe="5")
    assert r1.data_as_of == at("11:19:00") and r5.data_as_of == at("11:20:00")
    for _ in range(5):
        assert c.get("candles", "2330", timeframe="1").status == FetchStatus.CACHED
    assert calls == [("2330", "1"), ("2330", "5")]


def test_module_isolated():
    src = (ROOT / "candles.py").read_text(encoding="utf-8")
    imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
    for mod in ("streamlit", "everlight_app", "requests", "yfinance"):
        assert not any(mod in l for l in imports)


def test_otc_and_etf_quotes_same_adapter():
    """上櫃（6488）與 ETF（0050）用同一個報價 adapter；富果 type 對 ETF 也是 EQUITY，
    所以商品類型不能靠富果判斷（要用 pricing 的 AssetInfo）。"""
    otc = raw("fugle_quote_6488_otc_20261007_113941.json")
    etf = raw("fugle_quote_0050_etf_20261007_113946.json")
    assert (otc["exchange"], otc["market"]) == ("TPEx", "OTC")
    assert etf["type"] == "EQUITY"
    for r, t in ((otc, "11:39:41"), (etf, "11:39:46")):
        sec = db.fugle_quote(r, at(t))
        assert sec.availability == db.Availability.AVAILABLE
        assert abs(sec.items["vwap"].value - sec.items["avg_price"].value) <= 0.01
        assert sec.items["is_limit_up_price"].value is None          # null 保持 None


def test_close_auction_bar():
    """收盤：13:25～13:29 沒有 K 棒，13:30 一根是收盤集合競價（單一價），10 分鐘後重抓沒有任何修正。"""
    obs = raw("fugle_candles_close_study_20261007.json")["obs"]
    for o in obs:
        times = [b[0] for b in o["bars"]]
        assert times[-2:] == ["13:24", "13:30"]
        o_, h, l, c = o["bars"][-1][1:5]
        assert o_ == h == l == c
    first = {o["s"]: o["bars"] for o in obs[:2]}
    later = {o["s"]: o["bars"] for o in obs[2:]}
    assert first == later
