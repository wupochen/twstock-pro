# -*- coding: utf-8 -*-
"""Gate 2.3：everlight_app.py 接線到 indicators.py 前後，每個呼叫點的結果逐值相同。

做法：同一份 fixture，分別執行「接線前原檔」的程式片段和「接線後主程式」的程式片段，
比對所有產出的變數（Series：index、NaN 位置、誤差 < 1e-10；純量：誤差 < 1e-10）。
"""
import math
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import indicators as ind

ROOT = Path(__file__).resolve().parents[1]
NEW = (ROOT / "everlight_app.py").read_text(encoding="utf-8").splitlines()
OLD = (ROOT / "tests" / "fixtures" / "legacy" / "everlight_app_9f36ed4.py.txt").read_text(encoding="utf-8").splitlines()
FIX = ROOT / "tests" / "fixtures"
TOL = 1e-10


def block(lines, start, end, occurrence=1):
    hits = [i for i, l in enumerate(lines) if start in l]
    assert len(hits) >= occurrence, f"找不到：{start}"
    s = hits[occurrence - 1]
    e = next(i for i in range(s, len(lines)) if end in lines[i])
    return textwrap.dedent("\n".join(lines[s:e + 1]))


def run(code, **env):
    ns = {"pd": pd, "np": np, "ind": ind, **env}
    exec(code, ns)
    return ns


def same(a, b, name):
    if isinstance(a, pd.DataFrame):
        assert list(a.columns) == list(b.columns), f"{name}: 欄位不同"
        for c in a.columns:
            same(a[c], b[c], f"{name}.{c}")
        return
    if isinstance(a, pd.Series):
        a, b = a.astype("float64"), b.astype("float64")
        assert a.index.equals(b.index), f"{name}: index 不同"
        assert (a.isna() == b.isna()).all(), f"{name}: NaN 位置不同"
        m = a.notna()
        assert ((a[m] - b[m]).abs().max() if m.any() else 0) < TOL, name
        return
    a, b = float(a), float(b)
    assert (math.isnan(a) and math.isnan(b)) or abs(a - b) < TOL, f"{name}: {a} vs {b}"


@pytest.fixture
def daily():
    return pd.read_csv(FIX / "indicators_ohlcv.csv", index_col="Date", parse_dates=True)


@pytest.fixture
def m1():
    return pd.read_csv(FIX / "indicators_intraday_1m.csv", index_col="Datetime", parse_dates=True)


def test_kline_page(daily):
    old = run(block(OLD, "df_calc['MA5'] = df_calc['Close'].rolling(5).mean()", "df_calc['BB_DN'] ="), df_calc=daily.copy())
    new = run(block(NEW, "df_calc = ind.compute_kline_indicators(df_calc)", "df_calc = ind.compute_kline_indicators(df_calc)"),
              df_calc=daily.copy())
    same(old["df_calc"], new["df_calc"], "df_calc")


def test_strategy_page(daily):
    old = run(block(OLD, 'ma5 = df["Close"].rolling(5).mean().iloc[-1]', "rsi14 = (100 - (100 / (1 + rs))).iloc[-1]"), df=daily)
    new = run(block(NEW, 'ma5 = ind.sma(df["Close"], 5).iloc[-1]', "rsi14 = ind.rsi(df['Close'], 14).iloc[-1]"), df=daily)
    for v in ("ma5", "ma10", "ma20", "high20", "low20", "osc", "rsi14"):
        same(old[v], new[v], v)


@pytest.mark.parametrize("zero", [False, True])
def test_realtime_vwap_line_and_vma(m1, zero):
    df = m1.copy()
    if zero:
        df.iloc[:5, df.columns.get_loc("Volume")] = 0
    old = run(block(OLD, 'df_plot["VWAP"] = (df_plot["Close"]', 'df_plot["VWAP"] = df_plot["VWAP"].bfill()'), df_plot=df.copy())
    new = run(block(NEW, 'df_plot["VWAP"] = ind.vwap_series(', 'df_plot["VWAP"] = ind.vwap_series('), df_plot=df.copy())
    same(old["df_plot"]["VWAP"], new["df_plot"]["VWAP"], "VWAP")
    o = run(block(OLD, 'df_plot["VMA"] =', 'df_plot["VMA"] ='), df_plot=df.copy())
    n = run(block(NEW, 'df_plot["VMA"] =', 'df_plot["VMA"] ='), df_plot=df.copy())
    same(o["df_plot"]["VMA"], n["df_plot"]["VMA"], "VMA")


@pytest.mark.parametrize("zero", [False, True])
def test_score_page(daily, m1, zero):
    df_i = m1.copy()
    if zero:
        df_i["Volume"] = 0
    env = dict(df=daily, df_i=df_i, curr=123.45)
    old = run(block(OLD, "ma5, ma20, h20, vma20, vc =", "ma5, ma20, h20, vma20, vc ="), **env)
    new = run(block(NEW, "ma5, ma20, h20, vma20, vc =", "ma5, ma20, h20, vma20, vc ="), **env)
    for v in ("ma5", "ma20", "h20", "vma20", "vc"):
        same(old[v], new[v], v)
    old = run(block(OLD, 'vwap = (df_i["Close"] * df_i["Volume"]).sum()', 'vwap = (df_i["Close"]').strip(), **env)
    new = run(block(NEW, "vwap = ind.vwap_total(df_i", "vwap = ind.vwap_total(df_i").strip(), **env)
    same(old["vwap"], new["vwap"], "vwap")
    expr_old = 'df["Volume"].rolling(20).mean().iloc[-1] / 270 * 2'
    expr_new = 'ind.sma(df["Volume"], 20).iloc[-1] / 270 * 2'
    assert any(expr_old in l for l in OLD) and any(expr_new in l for l in NEW)
    same(eval(expr_old, {"df": daily}), eval(expr_new, {"df": daily, "ind": ind}), "日均量門檻")


@pytest.mark.parametrize("occ", [1, 2])
def test_summary_vwap_both_sites(m1, occ):
    env = dict(df_i_for_summary=m1, vol_sum=m1["Volume"].sum(), curr=1.0)
    o = run(block(OLD, "vwap_val = (df_i_for_summary", "vwap_val = (df_i_for_summary", occ).strip(), **env)
    n = run(block(NEW, "vwap_val = ind.vwap_total(df_i_for_summary", "vwap_val = ind.vwap_total(df_i_for_summary", occ).strip(), **env)
    same(o["vwap_val"], n["vwap_val"], "vwap_val")


def test_admin_diagnostic_d(daily):
    c = daily["Close"]
    old = run(block(OLD, "ema12 = c.ewm(span=12, adjust=False).mean()", '"MA20": c.rolling(20).mean()', 1), c=c)
    new = run(block(NEW, "osc_s = ind.macd(c)[4]", '"MA20": ind.sma(c, 20)'), c=c)
    same(old["tbl"], new["tbl"], "tbl")


def test_no_formula_left_in_app():
    """主程式不再自己寫均線／EMA／RSI 公式（只剩 20 日最高價 rolling max，不屬於 indicators）。"""
    src = "\n".join(NEW)
    assert ".ewm(" not in src
    rolling = [l.strip() for l in NEW if ".rolling(" in l]
    assert len(rolling) == 1 and 'df["High"].rolling(20).max()' in rolling[0]
    assert "import indicators as ind" in src
