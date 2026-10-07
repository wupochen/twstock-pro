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


def test_live_bar_not_completed_and_recently_closed_bar_can_still_change():
    first = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112005.json"), at("11:20:05"), 1)
    later = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112650.json"), at("11:26:50"), 1)
    a = {r["start"]: r for r in first.rows}[at("11:19:00")]
    b = {r["start"]: r for r in later.rows}[at("11:19:00")]
    assert (a["volume"], a["close"]) == (21, 2575) and (b["volume"], b["close"]) == (30, 2570)   # 真的被修正
    assert a["completed"] is False            # 結束後 5 秒：還不算完成（緩衝 60 秒）
    assert b["completed"] is True
    assert cd.live_bar(first)["start"] == at("11:19:00")
    assert all(r["completed"] for r in cd.completed_bars(first))
    # 緩衝設 0 會把還在變的 K 棒當成完成 → 這就是不能設 0 的原因
    assert cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112005.json"), at("11:20:05"), 1,
                            grace_seconds=0).rows[-1]["completed"] is True


def test_5m_boundaries_and_matches_completed_1m():
    m5 = cd.fugle_candles(raw("fugle_candles_2330_5m_20261007_112656.json"), at("11:26:56"), 5)
    assert all(r["start"].minute % 5 == 0 and r["start"].second == 0 for r in m5.rows)
    m1 = cd.fugle_candles(raw("fugle_candles_2330_1m_20261007_112650.json"), at("11:26:50"), 1)
    agg = {b["start"]: b for b in cd.aggregate(cd.completed_bars(m1), 5)}
    done5 = [r for r in m5.rows if r["completed"] and r["start"] in agg]
    assert len(done5) >= 25
    for r in done5:
        a = agg[r["start"]]
        assert (a["open"], a["high"], a["low"], a["close"], a["volume"]) == \
               (r["open"], r["high"], r["low"], r["close"], r["volume"]), r["start"]
    with pytest.raises(ValueError):
        cd.aggregate(m1.rows, 5)               # 含未完成 K 棒不准聚合


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
    assert sec.meta["grace_seconds"] == 60 and sec.meta["as_of_means"]
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
