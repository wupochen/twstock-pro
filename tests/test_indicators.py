# -*- coding: utf-8 -*-
"""Gate 2.3：indicators.py 與 everlight_app.py 原始程式碼逐值比對。

「舊版」不是複製一份公式，而是測試時直接從 everlight_app.py 讀出原始程式碼片段執行，
所以只要主程式的公式被改，或 indicators.py 被改，這裡都會失敗。

比對方式（GPT 規定）：index 相同、NaN 位置相同、非 NaN 值誤差 < 1e-10。
"""
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import indicators as ind

ROOT = Path(__file__).resolve().parents[1]
# Gate 2.3 接線後，主程式已改成呼叫 indicators.py；「舊版公式」改讀接線前的原檔（9f36ed4 原封不動保存）
APP_LINES = (ROOT / "tests" / "fixtures" / "legacy" / "everlight_app_9f36ed4.py.txt").read_text(encoding="utf-8").splitlines()
FIX = ROOT / "tests" / "fixtures"
TOL = 1e-10


def load_daily():
    return pd.read_csv(FIX / "indicators_ohlcv.csv", index_col="Date", parse_dates=True)


def load_1m():
    return pd.read_csv(FIX / "indicators_intraday_1m.csv", index_col="Datetime", parse_dates=True)


def app_block(start_marker, end_marker, occurrence=1):
    """取出 everlight_app.py 從 start_marker 那行到 end_marker 那行（含）的原始程式碼。"""
    hits = [i for i, l in enumerate(APP_LINES) if start_marker in l]
    assert len(hits) >= occurrence, f"主程式找不到：{start_marker}"
    s = hits[occurrence - 1]
    e = next(i for i in range(s, len(APP_LINES)) if end_marker in APP_LINES[i])
    return textwrap.dedent("\n".join(APP_LINES[s:e + 1]))


def run_old(code, **env):
    ns = {"pd": pd, "np": np, **env}
    exec(code, ns)
    return ns


def assert_same(old, new, name):
    old = pd.Series(old, dtype="float64") if not isinstance(old, pd.Series) else old.astype("float64")
    new = new.astype("float64")
    assert old.index.equals(new.index), f"{name}: index 不同"
    assert (old.isna() == new.isna()).all(), f"{name}: NaN 位置不同"
    m = old.notna()
    diff = (old[m] - new[m]).abs().max() if m.any() else 0.0
    assert diff < TOL, f"{name}: 最大誤差 {diff}"


KLINE_COLS = ["MA5", "MA10", "MA20", "9H", "9L", "RSV", "K", "D", "EMA12", "EMA26",
              "DIF", "MACD", "OSC", "RSI", "STD20", "BB_UP", "BB_DN"]


def test_fixture_has_edge_cases():
    df = load_daily()
    assert len(df) >= 300  # 足夠算 MA240 與長線暖機
    flat = df.iloc[100:112]
    assert (flat["High"] == flat["Low"]).all() and (flat["Volume"] == 0).all()


def test_kline_page_block_identical():
    """K線頁 df_calc 全部 17 個欄位逐值相同。"""
    df = load_daily()
    code = app_block("df_calc['MA5'] = df_calc['Close'].rolling(5).mean()", "df_calc['BB_DN'] =")
    old = run_old(code, df_calc=df.copy())["df_calc"]
    new = ind.compute_kline_indicators(df)
    for c in KLINE_COLS:
        assert_same(old[c], new[c], c)
    # 確認測到了邊界：RSV 在完全不動的區段是 NaN
    assert old["RSV"].iloc[108:112].isna().all()


@pytest.mark.parametrize("n", [5, 10, 20, 60, 240])
def test_sma_all_windows(n):
    """MA5/10/20/60/240：用主程式的 MA5 寫法換成 n 天。"""
    df = load_daily()
    line = app_block("df_calc['MA5'] = df_calc['Close'].rolling(5).mean()", "df_calc['MA5']")
    code = line.replace("'MA5'", "'X'").replace("rolling(5)", f"rolling({n})")
    old = run_old(code, df_calc=df.copy())["df_calc"]["X"]
    assert_same(old, ind.sma(df["Close"], n), f"MA{n}")


def test_strategy_page_scalars_identical():
    """操作策略頁的 ma5/ma10/ma20/osc/rsi14（取最後一根）一致，並逐根比對每個時間點。"""
    df_all = load_daily()
    code = app_block('ma5 = df["Close"].rolling(5).mean().iloc[-1]', "rsi14 = (100 - (100 / (1 + rs))).iloc[-1]")
    for end in (30, 112, 150, 220, 300, len(df_all)):
        df = df_all.iloc[:end]
        ns = run_old(code, df=df)
        _, _, _, _, osc = ind.macd(df["Close"])
        pairs = {
            "ma5": ind.sma(df["Close"], 5).iloc[-1],
            "ma10": ind.sma(df["Close"], 10).iloc[-1],
            "ma20": ind.sma(df["Close"], 20).iloc[-1],
            "osc": osc.iloc[-1],
            "rsi14": ind.rsi(df["Close"]).iloc[-1],
        }
        for k, v in pairs.items():
            o = ns[k]
            assert (pd.isna(o) and pd.isna(v)) or abs(o - v) < TOL, (end, k, o, v)


def test_vwap_series_identical():
    df = load_1m()
    code = app_block('df_plot["VWAP"] = (df_plot["Close"] * df_plot["Volume"]).cumsum()',
                     'df_plot["VWAP"] = df_plot["VWAP"].bfill()')
    old = run_old(code, df_plot=df.copy())["df_plot"]["VWAP"]
    assert_same(old, ind.vwap_series(df["Close"], df["Volume"]), "VWAP線")


@pytest.mark.parametrize("zero_volume", [False, True])
def test_vwap_total_identical(zero_volume):
    df = load_1m().copy()
    if zero_volume:
        df["Volume"] = 0.0
    code = app_block('vwap = (df_i["Close"] * df_i["Volume"]).sum()', "else curr")
    old = run_old(code, df_i=df, curr=44.2)["vwap"]
    new = ind.vwap_total(df["Close"], df["Volume"], fallback=44.2)
    assert abs(old - new) < TOL


def test_admin_diagnostic_d_identical():
    """管理後台診斷 D 的 OSC、RSI 寫法也一致。"""
    df = load_daily()
    code = app_block("ema12 = c.ewm(span=12, adjust=False).mean()", "rsi_s = 100 - (100 / (1 + g / l_))")
    ns = run_old(code, c=df["Close"], dlt=df["Close"].diff())
    _, _, _, _, osc = ind.macd(df["Close"])
    assert_same(ns["osc_s"], osc, "診斷D OSC")
    assert_same(ns["rsi_s"], ind.rsi(df["Close"]), "診斷D RSI")


def test_rsi_edge_values():
    df = load_daily()
    r = ind.rsi(df["Close"])
    assert r.iloc[219] > 90.0  # 連漲 20 根，RSI 很高（Wilder 平滑不會剛好到 100）
