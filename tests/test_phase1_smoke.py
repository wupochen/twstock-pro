"""
第一段止血：煙霧測試（用合成資料，不連網）
- 模擬「漲停鎖單」情境：現價 = 漲停價、賣方無掛單
- 檢查每個頁面都能跑完、沒有例外
- 檢查停損停利 validator、名稱修正、缺值顯示
注意：這裡的數字是「合成測試資料」，不是真實行情。
"""
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "everlight_app.py")


def make_daily(n=260, last_close=48.60, prev_close=44.20):
    idx = pd.bdate_range(end=pd.Timestamp.now(tz="Asia/Taipei").normalize().tz_localize(None), periods=n)
    closes = np.linspace(38, 41.75, n - 2).tolist() + [prev_close, last_close]
    df = pd.DataFrame({
        "Open": [c * 0.995 for c in closes],
        "High": [c * 1.01 for c in closes],
        "Low": [c * 0.99 for c in closes],
        "Close": closes,
        "Adj Close": closes,
        "Volume": [2_000_000] * (n - 1) + [20_000_000],
    }, index=idx)
    df.iloc[-1, df.columns.get_loc("High")] = last_close  # 今天收在最高 = 漲停
    return df


def make_1m(last_close=48.60):
    day = pd.Timestamp.now(tz="Asia/Taipei").normalize()
    idx = pd.date_range(day + pd.Timedelta(hours=9), day + pd.Timedelta(hours=10, minutes=30), freq="1min")
    closes = np.linspace(44.6, last_close, len(idx))
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes,
                         "Adj Close": closes, "Volume": [50_000] * len(idx)}, index=idx)


def fake_download(ticker, period=None, interval=None, **kw):
    if interval == "1m":
        return make_1m()
    if interval in ("1wk", "1mo"):
        return make_daily().resample("W").last()
    return make_daily()


class FakeResp:
    def __init__(self, payload, status=200, text=""):
        self._p, self.status_code, self.text = payload, status, text

    def json(self):
        return self._p


LIMIT_UP_QUOTE = {
    "lastPrice": 48.60, "referencePrice": 44.20, "previousClose": 44.20,
    "lastUpdated": int(pd.Timestamp.now().timestamp() * 1e6),
    "isLimitUpPrice": True, "isLimitUpBid": True,
    "bids": [{"price": 48.60, "size": 21331}, {"price": 48.55, "size": 11}],
    "asks": [],
    "total": {"tradeVolume": 30000},
}
TRADES = [{"price": 48.60, "size": s, "time": int(pd.Timestamp.now().timestamp() * 1e6)} for s in (5, 30, 60, 2)]


def fake_get(url, *a, **kw):
    if "intraday/quote" in url:
        return FakeResp(LIMIT_UP_QUOTE)
    if "intraday/trades" in url:
        return FakeResp({"data": TRADES})
    if "finmindtrade" in url:
        ds = (kw.get("params") or {}).get("dataset", "")
        if ds == "TaiwanStockMonthRevenue":
            rows = []
            for i in range(24):
                p = pd.Timestamp("2024-10-01") + pd.DateOffset(months=i)
                rows.append({"date": (p + pd.DateOffset(months=1)).strftime("%Y-%m-%d"),
                             "revenue": 7e8 + i * 1e6, "revenue_year": p.year, "revenue_month": p.month})
            return FakeResp({"data": rows})
        if ds == "TaiwanStockInstitutionalInvestorsBuySell":
            d = pd.Timestamp.now().strftime("%Y-%m-%d")
            return FakeResp({"data": [{"date": d, "name": "Foreign_Investor", "buy": 2_000_000, "sell": 1_752_000},
                                      {"date": d, "name": "Dealer_self", "buy": 100_000, "sell": 10_000}]})
        if ds == "TaiwanStockMarginPurchaseShortSale":
            d = pd.Timestamp.now().strftime("%Y-%m-%d")
            return FakeResp({"data": [{"date": d, "MarginPurchaseTodayBalance": 19212, "ShortSaleTodayBalance": 130}]})
        return FakeResp({"data": []})
    return FakeResp([], 404)


class FakeTicker:
    def __init__(self, *a, **k):
        # 缺值情境：沒有 dividendYield / payoutRatio
        self.info = {"trailingEps": 0.14, "trailingPE": 347.14, "priceToBook": 2.99,
                     "returnOnEquity": 0.007, "revenueGrowth": 0.073, "dividendRate": 9.99, "trailingAnnualDividendRate": 0.30,
                     "debtToEquity": 35.18, "country": "Taiwan", "currency": "TWD"}
        self.financials = pd.DataFrame()


PAGES = ["📊 K線分析", "⚡ 即時趨勢", "🧮 規則綜合評分", "📑 基本面分析", "🧩 籌碼分析", "🎯 操作策略", "🔐 管理後台"]


def run_page(page):
    with mock.patch("yfinance.download", side_effect=fake_download), \
         mock.patch("yfinance.Ticker", FakeTicker), \
         mock.patch("requests.get", side_effect=fake_get), \
         mock.patch.dict("os.environ", {}):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["FINMIND_TOKEN"] = "test"
        at.secrets["FUGLE_TOKEN"] = "test"
        at.secrets["ADMIN_PASSWORD"] = "pw"
        at.run()
        at.radio[0].set_value(page).run()
        return at


def all_text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + \
            [w.value for w in at.warning] + [i.value for i in at.info]
    return "\n".join(str(p) for p in parts)


@pytest.mark.parametrize("page", PAGES)
def test_page_runs(page):
    at = run_page(page)
    assert not at.exception, [e.value for e in at.exception]


def test_strategy_validator_blocks_bad_take_profit():
    t = all_text(run_page("🎯 操作策略"))
    # 合成資料當天創 20 日新高 → 第二停利 = 現價，必須被擋下
    assert "停損停利需重新計算" in t
    assert "第二停利" in t


def test_rule_page_has_no_ai_wording():
    t = all_text(run_page("🧮 規則綜合評分"))
    for bad in ["AI 深度解析", "AI 綜合總結", "主力吃貨", "造市者", "高股息殖利率亦能", "大戶偏進貨", "散戶偏進貨"]:
        assert bad not in t, bad
    assert "規則摘要" in t
    assert "無法判斷方向" in t   # 漲停鎖單時不能說偏買偏賣


def test_fundamentals_missing_and_units():
    t = all_text(run_page("📑 基本面分析"))
    assert "0.70%" in t            # ROE 0.007 → 0.70%
    assert "0.62%" in t            # 殖利率 = 近12個月股利 0.30 ÷ 48.60（不可用 dividendRate 9.99）
    assert "近12個月現金股利 ÷ 現價" in t
    assert "獲利尚可" not in t
    assert "負債權益比" in t


def test_kline_net_pnl_and_source():
    t = all_text(run_page("📊 K線分析"))
    assert "即時・富果" in t
    assert "稅費後估算損益" in t
    assert "漲停鎖單" in t


def test_fallback_without_fugle_is_not_labelled_live():
    with mock.patch("yfinance.download", side_effect=fake_download), \
         mock.patch("yfinance.Ticker", FakeTicker), \
         mock.patch("requests.get", side_effect=fake_get):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["FINMIND_TOKEN"] = "test"
        at.secrets["FUGLE_TOKEN"] = ""
        at.run()
        assert not at.exception
        t = all_text(at)
        assert "即時・富果" not in t
        assert "第三方 yfinance" in t


def test_minute_kline_runs():
    at = run_page("📊 K線分析")
    at.selectbox[0].set_value("5分K").run()
    assert not at.exception, [e.value for e in at.exception]


def test_limit_price_but_not_locked():
    """現價在漲停價、但賣方仍有掛單 → 只能說「現價漲停」，不能說「鎖單」"""
    q = dict(LIMIT_UP_QUOTE, asks=[{"price": 48.60, "size": 15}])
    def get2(url, *a, **kw):
        if "intraday/quote" in url:
            return FakeResp(q)
        return fake_get(url, *a, **kw)
    with mock.patch("yfinance.download", side_effect=fake_download), \
         mock.patch("yfinance.Ticker", FakeTicker), \
         mock.patch("requests.get", side_effect=get2):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["FINMIND_TOKEN"] = "test"
        at.secrets["FUGLE_TOKEN"] = "test"
        at.run()
        assert not at.exception
        t = all_text(at)
        assert "現價漲停" in t
        assert "漲停鎖單" not in t


def test_revenue_month_uses_revenue_month_field():
    """B22：date=2026-10-01 那筆是 2026/09 營收，月份要顯示 2026/09"""
    t = all_text(run_page("📑 基本面分析"))
    # 合成資料最後一筆：revenue_year/month = 2026/09，date = 2026-10-01
    assert "<td>2026/09</td>" in t
    assert "<td>2026/10</td>" not in t


def test_b02_institutional_units_small_stock():
    """B02 回歸測試：FinMind 單位是「股」，量小的股票也要 ÷1000（12,944 股 → 12.944 張，不得顯示成 12,944 張）"""
    def get_small(url, *a, **kw):
        ds = (kw.get("params") or {}).get("dataset", "")
        if "finmindtrade" in url and ds == "TaiwanStockInstitutionalInvestorsBuySell":
            d = pd.Timestamp.now().strftime("%Y-%m-%d")
            return FakeResp({"data": [{"date": d, "name": "Foreign_Investor", "buy": 112944, "sell": 100000}]})
        return fake_get(url, *a, **kw)
    import streamlit as st
    st.cache_data.clear()  # 避免沿用前一個測試快取的法人資料
    with mock.patch("yfinance.download", side_effect=fake_download), \
         mock.patch("yfinance.Ticker", FakeTicker), \
         mock.patch("requests.get", side_effect=get_small):
        at = AppTest.from_file(APP, default_timeout=60)
        at.secrets["FINMIND_TOKEN"] = "test"
        at.secrets["FUGLE_TOKEN"] = "test"
        at.run()
        at.radio[0].set_value("🧩 籌碼分析").run()
        assert not at.exception
        t = all_text(at)
        assert "12.9 張" in t
        assert "12,944 張" not in t
