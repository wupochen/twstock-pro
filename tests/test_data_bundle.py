# -*- coding: utf-8 -*-
"""Gate 2.1：DataBundle 與 adapter 測試（GPT 列的 12 項＋真實資料 round-trip）。"""
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import data_bundle as DB
from pricing import asset_info
from schema import DataKind, MarketSession, SourceType

RAW = Path(__file__).resolve().parent / "fixtures" / "raw"
NOW = datetime(2026, 10, 7, 1, 32, 7, tzinfo=timezone.utc)   # 台北 09:32:07


def load(name):
    return json.loads((RAW / name).read_text(encoding="utf-8"))


# 1. 富果正常報價 → metadata 正確
def test_fugle_quote_metadata_and_values():
    q = DB.fugle_quote(load("fugle_quote_2330_20261007_0932.json"), NOW)
    assert q.source_name == "Fugle" and q.source_type == SourceType.VENDOR
    assert q.as_of == datetime(2026, 10, 7, 1, 32, 6, 161047, tzinfo=timezone.utc)
    assert q.fetched_at == NOW and q.as_of != q.fetched_at                    # 10. 分開
    assert q.items["last_price"].value == 2580 and q.items["reference_price"].value == 2585
    assert q.items["volume_at_ask"].value == 1383 and q.items["volume_at_bid"].value == 948
    for k in ("last_price", "trade_volume", "volume_at_ask"):
        assert q.items[k].data_kind == DataKind.RAW                           # 9. RAW vs CALC
    for k in ("ask_ratio", "vwap"):
        assert q.items[k].data_kind == DataKind.CALC
    assert abs(q.items["ask_ratio"].value - 1383 / (1383 + 948)) < 1e-12
    # VWAP 換算驗證：與富果自己的 avgPrice 一致 → 證明 tradeVolume 單位是「張」
    assert abs(q.items["vwap"].value - q.items["avg_price"].value) < 0.01
    assert q.items["is_limit_up_price"].value is None                        # null 保持 None
    assert q.availability == DB.Availability.AVAILABLE


def test_fugle_order_book_matches_ui_record():
    ob = DB.fugle_order_book(load("fugle_quote_2330_20261007_0932.json"), NOW)
    assert [l["price"] for l in ob.items["bids"].value] == [2575, 2570, 2565, 2560, 2555]
    assert [l["size"] for l in ob.items["asks"].value] == [273, 468, 409, 668, 1097]


# 2. 缺 bids/asks → 不造假
def test_missing_book_is_not_fabricated():
    raw = load("fugle_quote_2330_20261007_0932.json")
    del raw["asks"]
    ob = DB.fugle_order_book(raw, NOW)
    assert ob.items["asks"].value is None and ob.availability == DB.Availability.PARTIAL
    locked = DB.fugle_order_book(load("fugle_quote_1711_20261006_close_locked.json"), NOW)
    assert locked.items["asks"].value == [] and "漲停" in locked.note          # 真的沒有掛單 ≠ 沒資料
    q = DB.fugle_quote(load("fugle_quote_1711_20261006_close_locked.json"), NOW)
    assert q.items["is_limit_up_price"].value is True and q.items["is_limit_down_price"].value is None
    assert q.items["vwap"].value is None                                    # 沒有 tradeValue 就不算


# 3. FinMind 12,944 股 → 12.944 張；4. 真正 0 → 0.0；缺值 → None
def test_finmind_institutional_units_and_none():
    s = DB.finmind_institutional(load("finmind_institutional_1416.json"), NOW)
    rows = {r["date"]: r for r in s.rows}
    assert rows["2026-10-01"]["外資"] == pytest.approx(12.944)
    assert rows["2026-10-02"]["外資"] == pytest.approx(-42.184)
    assert rows["2026-10-05"]["外資"] == pytest.approx(-116.285)
    assert rows["2026-10-01"]["投信"] == 0.0                                 # 來源明確 0
    assert rows["2026-10-02"]["投信"] is None                                # 來源 null，不能變 0
    assert rows["2026-10-05"]["投信"] is None and rows["2026-10-05"]["合計"] is None
    assert s.meta["raw_unit"] == "shares" and s.meta["normalized_unit"] == "lots" and s.meta["conversion"] == "/1000"
    assert s.availability == DB.Availability.PARTIAL and s.source_type == SourceType.THIRD_PARTY


def test_twse_t86_official_round_trip():
    s = DB.twse_t86(load("twse_t86_20261006.json"), "2330", NOW)
    assert s.source_name == "TWSE" and s.source_type == SourceType.OFFICIAL
    assert s.items["外資"].value == pytest.approx(-1672.231)
    assert s.items["投信"].value == pytest.approx(154.586)
    assert s.items["合計"].value == pytest.approx(-1121.670)
    assert s.as_of == datetime(2026, 10, 6, 5, 30, tzinfo=timezone.utc)
    otc = DB.twse_t86(load("twse_t86_20261006.json"), "6488", NOW)
    assert otc.availability == DB.Availability.UNAVAILABLE and "上櫃" in otc.note


# 5. yfinance NaN → None；盤中今天這根分開
def test_yfinance_daily_nan_and_live_bar():
    idx = pd.to_datetime(["2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"])
    df = pd.DataFrame({"Open": [1, 2, np.nan, 4], "High": [1, 2, 3, 4], "Low": [1, 2, 3, 4],
                       "Close": [1, 2, 3, 4], "Volume": [10, 20, 30, 40]}, index=idx)
    s = DB.yfinance_daily(df, NOW, MarketSession.OPEN, today=date(2026, 10, 7))
    assert len(s.rows) == 3 and s.meta["live_bar"]["date"] == date(2026, 10, 7)
    assert s.rows[2]["open"] is None and s.availability == DB.Availability.PARTIAL
    closed = DB.yfinance_daily(df, NOW, MarketSession.CLOSED, today=date(2026, 10, 7))
    assert len(closed.rows) == 4 and closed.meta["live_bar"] is None


def test_yfinance_fundamentals_none():
    s = DB.yfinance_fundamentals({"trailingEps": 3.2, "trailingPE": float("nan"), "returnOnEquity": None}, NOW)
    assert s.items["eps"].value == 3.2 and s.items["pe"].value is None and s.items["roe"].value is None
    assert s.availability == DB.Availability.PARTIAL


# 6. 月營收只用 revenue_year / revenue_month
def test_revenue_period_from_year_month_only():
    s = DB.finmind_revenue(load("finmind_revenue_1711.json"), NOW)
    assert [r["period"] for r in s.rows] == ["2026/06", "2026/07", "2026/08"]
    assert s.rows[-1]["revenue"] == 747000000                               # 9/01 那筆是 8 月營收
    assert s.meta["skipped"] == 1 and s.availability == DB.Availability.PARTIAL
    # as_of＝資料所屬期間（8 月底），公布時間另外放，不能混成「資料月份」
    assert s.as_of == datetime(2026, 8, 31, 15, 59, 59, tzinfo=timezone.utc)
    assert s.rows[-1]["published_at"] == datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
    assert s.meta["as_of_means"] == "period_end" and "（09/08 公布）" in s.note


# 7. naive datetime → fail
def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        DB.fugle_quote(load("fugle_quote_2330_20261007_0932.json"), datetime(2026, 10, 7, 9, 32))
    with pytest.raises(ValueError):
        DB.build_bundle("2330", datetime(2026, 10, 7))


# 8. 部分失敗 → 其他來源仍在
def test_partial_success():
    b = DB.build_bundle(
        "2330", NOW, fugle_quote_raw=load("fugle_quote_2330_20261007_0932.json"),
        t86_raw={"stat": "很抱歉，沒有符合條件的資料!"},                            # 這個 adapter 會丟例外
        finmind_inst_raw=load("finmind_institutional_1416.json"),
        failed={"日K": ("yfinance", "ConnectionError: 403")})
    assert b.get(DB.QUOTE) and b.get(DB.ORDER_BOOK) and b.get(DB.INSTITUTIONAL)
    assert b.get(DB.INSTITUTIONAL_OFFICIAL) is None
    errs = {(e.section, e.source_name) for e in b.errors}
    assert ("三大法人（證交所）", "TWSE") in errs and ("日K", "yfinance") in errs


# 11. asset_info 帶進 bundle；12. 自動產生資料狀況清單
def test_asset_info_and_data_status():
    b = DB.build_bundle("2330", NOW, asset_info=asset_info("2330"), market_session=MarketSession.OPEN,
                        fugle_quote_raw=load("fugle_quote_2330_20261007_0932.json"),
                        finmind_revenue_raw=load("finmind_revenue_1711.json"),
                        failed={"日K": ("yfinance", "timeout")})
    assert b.asset_info.asset_type == "STOCK" and b.market_session == MarketSession.OPEN
    lines = b.data_status_text()
    assert any(l.startswith("即時報價：Fugle（VENDOR），資料時間 2026-10-07 09:32:06，正常") for l in lines)
    # 新鮮度另外判：assess_freshness 之後才出現「最新／過期」
    DB.assess_freshness(b.get(DB.QUOTE), NOW, 60)
    assert any("09:32:06，正常，最新" in l for l in b.data_status_text())
    DB.assess_freshness(b.get(DB.QUOTE), NOW + timedelta(seconds=120), 60)
    assert b.get(DB.QUOTE).freshness == DB.Freshness.STALE
    assert b.get(DB.QUOTE).availability == DB.Availability.AVAILABLE      # 有資料但過期，兩個維度分開
    assert any(l.startswith("月營收：FinMind（THIRD_PARTY）") and "最新 2026/08" in l for l in lines)
    assert any(l.startswith("日K：yfinance") and "無法取得" in l for l in lines)


def test_num_helper():
    assert DB.num("1,234") == 1234 and DB.num("--") is None and DB.num(float("nan")) is None
    assert DB.num(0) == 0.0 and DB.num(None) is None and DB.num(True) is None


def test_adapters_do_no_judgement():
    """adapter 不得產生多空、分數、指標類欄位。"""
    src = (Path(__file__).resolve().parents[1] / "data_bundle.py").read_text(encoding="utf-8")
    for bad in ("偏多", "偏空", "score", "rsi(", "kd(", "macd(", "import indicators", "import engine"):
        assert bad not in src, bad


def test_yfinance_delay_is_measured_not_hardcoded():
    idx = pd.date_range("2026-10-07 09:00", periods=11, freq="1min", tz="Asia/Taipei")
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)
    ref = datetime(2026, 10, 7, 1, 30, 8, tzinfo=timezone.utc)              # 富果 09:30:08
    s = DB.yfinance_intraday(df, NOW, reference_time=ref)
    assert s.meta["latest_bar_time"] == datetime(2026, 10, 7, 1, 10, tzinfo=timezone.utc)
    assert s.meta["observed_delay_seconds"] == 20 * 60 + 8
    assert DB.describe_delay(s.meta["observed_delay_seconds"]) == "實測延遲約 20 分鐘"
    no_ref = DB.yfinance_intraday(df, NOW)
    assert no_ref.meta["observed_delay_seconds"] is None and "無法判斷" in no_ref.note
    src = (Path(__file__).resolve().parents[1] / "data_bundle.py").read_text(encoding="utf-8")
    assert "20 分鐘" not in src                                             # 不寫死


def test_build_bundle_is_orchestration_only():
    import inspect
    body = inspect.getsource(DB.build_bundle)
    for bad in ("vwap", "ask_ratio", "assess_freshness", "Freshness", " / ", "fallback", "priority"):
        assert bad not in body, bad


def test_fixture_origins_declared():
    origins = json.loads((RAW / "ORIGINS.json").read_text(encoding="utf-8"))
    files = {p.name for p in RAW.glob("*.json")} - {"ORIGINS.json"}
    assert files == set(k for k in origins if not k.startswith("_"))
    for k, v in origins.items():
        if not k.startswith("_"):
            assert v["origin"] in ("RAW_CAPTURE", "RECONSTRUCTED_FROM_UAT", "SYNTHETIC_WITH_REAL_FIELDS"), k
