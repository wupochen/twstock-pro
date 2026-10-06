# -*- coding: utf-8 -*-
"""技術指標（第二段 Gate 2.3：只搬移、不改公式）。

每個函式都是從 everlight_app.py 原樣搬出來的公式，原始位置寫在註解裡。
tests/test_indicators.py 會直接讀 everlight_app.py 的原始程式碼執行，
逐值比對（index 相同、NaN 位置相同、其餘誤差 < 1e-10）。

規則：
- 不准在這裡「順便改良」公式（例如換 RSI 算法、改 KD 初始值）。
- 要改公式請另開規格、交 GPT 審，並在第三段回測後才可以改。
- ATR 不在這裡：舊版沒有 ATR，ATR 已在 pricing.py（第二段新增、已 CLOSED）。
"""
from __future__ import annotations

import pandas as pd


def sma(close: pd.Series, n: int) -> pd.Series:
    """簡單均線。原：everlight_app.py `df_calc['Close'].rolling(n).mean()`。"""
    return close.rolling(n).mean()


def kd(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, com: int = 2):
    """KD(9,3)。原：everlight_app.py K線頁 9H/9L/RSV/K/D 區塊。

    回傳 (nH, nL, RSV, K, D)。
    """
    nh = pd.to_numeric(high, errors="coerce").rolling(n).max()
    nl = pd.to_numeric(low, errors="coerce").rolling(n).min()
    rsv_den = (nh - nl).replace(0, float("nan"))
    rsv = (pd.to_numeric(close, errors="coerce") - nl) / rsv_den * 100
    rsv = pd.to_numeric(rsv, errors="coerce")
    k = rsv.ewm(com=com, adjust=False).mean()
    d = k.ewm(com=com, adjust=False).mean()
    return nh, nl, rsv, k, d


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD。原：everlight_app.py EMA12/EMA26/DIF/MACD/OSC。

    回傳 (EMA_fast, EMA_slow, DIF, MACD, OSC)。
    """
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    sig = dif.ewm(span=signal, adjust=False).mean()
    osc = dif - sig
    return ema_f, ema_s, dif, sig, osc


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI（ewm alpha=1/n）。原：everlight_app.py delta/gain/loss/rs/RSI。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def bollinger(close: pd.Series, n: int = 20, k: float = 2):
    """布林通道。原：everlight_app.py STD20/BB_UP/BB_DN（中線為 MA20）。

    回傳 (MID, STD, UP, DN)。
    """
    mid = close.rolling(n).mean()
    std = close.rolling(n).std()
    return mid, std, mid + k * std, mid - k * std


def vwap_series(close: pd.Series, volume: pd.Series) -> pd.Series:
    """累積 VWAP 線（1 分K估算）。原：everlight_app.py 即時趨勢頁 df_plot["VWAP"]。"""
    v = (close * volume).cumsum() / volume.cumsum().replace(0, pd.NA)
    return v.bfill().fillna(close)


def vwap_total(close: pd.Series, volume: pd.Series, fallback: float) -> float:
    """全日 VWAP 單一數值（1 分K估算）。原：everlight_app.py 評分頁／策略頁 vwap。"""
    return (close * volume).sum() / volume.sum() if volume.sum() > 0 else fallback


def compute_kline_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """一次算出 K線頁用到的所有欄位，欄位名稱與舊版 df_calc 完全相同。"""
    out = df.copy()
    out["MA5"] = sma(out["Close"], 5)
    out["MA10"] = sma(out["Close"], 10)
    out["MA20"] = sma(out["Close"], 20)
    out["9H"], out["9L"], out["RSV"], out["K"], out["D"] = kd(out["High"], out["Low"], out["Close"])
    out["EMA12"], out["EMA26"], out["DIF"], out["MACD"], out["OSC"] = macd(out["Close"])
    out["RSI"] = rsi(out["Close"])
    _, out["STD20"], out["BB_UP"], out["BB_DN"] = bollinger(out["Close"])
    return out
