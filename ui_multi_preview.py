# -*- coding: utf-8 -*-
"""多檔同時看盤預覽頁（第四段先行 P-E／P-F，只用虛構資料）。

每格（股票格）內容：
  1 代號／名稱／現價／漲跌幅
  2 主畫面（每格可自選）：即時走勢／技術分析／分K／籌碼／五檔
  3 方向／風險／能不能做（三個獨立狀態，不合成一顆總燈）
  4 當沖強度一行：同時段量比／外盤比／距 VWAP
  5 資料狀態點（綠＝即時、黃＝延遲、灰＝無資料）＋時間
  動作：放大／新分頁

使用者可在側邊欄「看盤設定」自己開關：
  條件提醒、自選清單、排行榜格、大盤格、時間對照、新手提示、技術分析副圖。

- 版面（每格代號＋畫面）存在網址 ?w=代號,…&v=畫面,…（可加書籤）；放大頁共用同一份清單。
- 6 格是 compact mode：圖表較矮、原因只留一行、次要文字隱藏。
- 不 import engine、不連任何 API。正式接資料時改由 MarketDataCoordinator 集中抓取。
- 排行、提醒只描述現象，不給買賣建議。
啟動：streamlit run ui_multi_preview.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import glossary
import pricing
import ui_theme as ui
from ui_theme import C, tip

st.set_page_config(page_title="台股戰情室｜多檔看盤預覽", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(ui.css(), unsafe_allow_html=True)
st.markdown("""
<style>
.block-container { max-width: 100% !important; padding-left: 1.2rem; padding-right: 1.2rem; }
.cell .top { display:flex; justify-content:space-between; align-items:baseline; gap:8px; }
.cell .nm { font-size:17px; font-weight:900; }
.cell .cd { color:#8b97a8; font-size:13px; margin-left:6px; }
.cell .px { font-size:26px; font-weight:900; font-variant-numeric: tabular-nums; text-align:right; }
.cell .chg { font-size:13px; font-weight:800; text-align:right; }
.compact .px { font-size:22px; } .compact .nm { font-size:15px; }
.lights { display:flex; gap:6px; margin:6px 0 2px; flex-wrap:wrap; }
.light { flex:1; min-width:78px; border-radius:9px; padding:3px 8px; background:#151c28; border-left:4px solid var(--c); }
.light .k { color:#8b97a8; font-size:11px; font-weight:700; }
.light .v { color:var(--c); font-size:14px; font-weight:900; }
.why1 { color:#c3ccd8; font-size:12.5px; margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.hint { color:#9fb3c8; font-size:12px; margin-top:4px; border-left:3px solid #3ea6ff; padding-left:6px; }
.dt { display:flex; gap:12px; flex-wrap:wrap; font-size:12.5px; color:#c3ccd8; margin-top:4px;
      background:#151c28; border-radius:8px; padding:3px 8px; font-variant-numeric: tabular-nums; }
.dt b { font-weight:900; }
.foot { display:flex; justify-content:space-between; align-items:center; gap:6px; }
.fresh { font-size:12px; color:#c3ccd8; display:flex; align-items:center; gap:6px; }
.dot { width:9px; height:9px; border-radius:50%; display:inline-block; }
.zoom { color:#3ea6ff !important; font-size:13px; font-weight:800; text-decoration:none; border:1px solid #3ea6ff55;
        border-radius:8px; padding:2px 8px; white-space:nowrap; }
.zoom:hover { background:#3ea6ff22; }
.nodata { height:var(--h); display:flex; align-items:center; justify-content:center; color:#8b97a8;
          border:1px dashed #243042; border-radius:10px; margin:6px 0; font-size:14px; text-align:center; }
.alertbar { background:#3a2a06; border:1px solid #f5b942; color:#ffe2a6; border-radius:10px; padding:6px 12px;
            margin:4px 0 10px; font-size:14px; font-weight:700; }
.alerting { animation: blink 1.2s ease-in-out infinite; border-radius:10px; padding:2px 8px; margin-bottom:4px;
            background:#3a2a06; color:#ffe2a6; font-size:12.5px; font-weight:800; }
.alerting-static { border:2px solid #f5b942; border-radius:10px; padding:2px 8px; margin-bottom:4px;
            background:#3a2a06; color:#ffe2a6; font-size:12.5px; font-weight:800; }
@keyframes blink { 0%,100% { box-shadow:0 0 0 0 rgba(245,185,66,.0);} 50% { box-shadow:0 0 0 3px rgba(245,185,66,.75);} }
.ob { width:100%; border-collapse:collapse; font-variant-numeric: tabular-nums; font-size:13.5px; }
.ob td { padding:3px 5px; border-bottom:1px solid #243042; }
.rk td { padding:4px 6px; border-bottom:1px solid #243042; font-size:13.5px; }
div[data-testid="stVerticalBlockBorderWrapper"] { background:#0f141d; border-color:#243042 !important; border-radius:14px !important; }
div[role="radiogroup"] label p { color:#e8edf5 !important; font-weight:700; }
section[data-testid="stSidebar"] { background:#0b0f16 !important; border-right:1px solid #243042; }
section[data-testid="stSidebar"] * { color:#e8edf5; }
section[data-testid="stSidebar"] button { background:#151c28 !important; border:1px solid #2c3a50 !important; }
section[data-testid="stSidebar"] .stCaption, section[data-testid="stSidebar"] small { color:#8b97a8 !important; }
label[data-testid="stWidgetLabel"] p { color:#c3ccd8 !important; font-weight:700; }
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div, input, textarea {
  background:#151c28 !important; color:#e8edf5 !important; border-color:#243042 !important; }
div[data-baseweb="select"] span, div[data-baseweb="select"] div { color:#e8edf5 !important; }
div[data-baseweb="popover"] li, ul[role="listbox"] { background:#151c28 !important; color:#e8edf5 !important; }
.stButton > button, .stFormSubmitButton > button { background:#151c28 !important; color:#e8edf5 !important;
  border:1px solid #2c3a50 !important; font-weight:800; }
.stButton > button:hover { border-color:#3ea6ff !important; color:#3ea6ff !important; }
div[data-testid="stForm"] { border-color:#243042 !important; }
</style>""", unsafe_allow_html=True)
st.markdown(ui.demo_banner(), unsafe_allow_html=True)

# ════════════════════════════════════════════════
# 虛構資料
# ════════════════════════════════════════════════
STOCKS = {
    "9991": dict(name="範例電子", ref=50.20, d="偏多", r="高", a="不宜追價", fresh="live", age=3,
                 why="均線多頭、外資連 3 買；RSI 82 過熱、今日已漲 4%", seed=1),
    "9992": dict(name="範例半導體", ref=612.0, d="中性偏多", r="中", a="可操作", fresh="live", age=2,
                 why="站上均價、同時段放量；法人中性", seed=2),
    "9993": dict(name="範例航運", ref=38.45, d="偏空", r="中", a="資料不足", fresh="stale", age=75,
                 why="跌破均價、內盤較多；報價超過 60 秒沒更新", seed=3),
    "9994": dict(name="範例生技", ref=88.6, d="資料不足", r="低", a="資料不足", fresh="none", age=None,
                 why="目前抓不到這檔的報價", seed=4),
    "9995": dict(name="範例金融", ref=27.15, d="中性", r="低", a="可操作", fresh="live", age=4,
                 why="價格在均價附近、量能正常", seed=5),
    "9996": dict(name="範例光電", ref=144.5, d="偏多", r="中", a="無法正常交易", fresh="live", age=1,
                 why="漲停鎖單，賣方幾乎沒有掛單", seed=6),
    "9997": dict(name="範例鋼鐵", ref=31.6, d="中性偏空", r="低", a="可操作", fresh="live", age=5,
                 why="價格在均價下方、量縮", seed=7),
    "9998": dict(name="範例網通", ref=233.0, d="中性偏多", r="中", a="可操作", fresh="live", age=2,
                 why="同時段放量、外盤略多", seed=8),
}
SPECIAL = {"RANK": "📊 排行榜", "INDEX": "🏛️ 大盤"}
CODES = list(STOCKS)
T = "10:42:15"
FRESH = {"live": ("#3ee08f", "即時"), "stale": ("#f5b942", "延遲"), "none": ("#6b7686", "無資料")}

# panel_mode（GPT：正式定義，不讓 UI 各自用文字判斷）
VIEWS = {"rt": "即時走勢", "ta": "技術分析", "k1": "1分K", "k5": "5分K", "k15": "15分K", "chip": "籌碼", "ob": "五檔"}
K_MIN = {"k1": 1, "k5": 5, "k15": 15}
INTRADAY_VIEWS = {"rt", "k1", "k5", "k15"}   # 只有這些會跟著時間對照
WATCHLISTS = {
    "今天當沖": ["9991", "9992", "9993", "9996", "9998", "9995"],
    "波段觀察": ["9992", "9998", "9991", "9997", "9995", "9993"],
    "長期觀察": ["9992", "9995", "9997", "9994", "9998", "9991"],
}
ALERT_RULES = {
    "below_vwap": "跌破當日均價（VWAP）",
    "above_vwap": "站上當日均價（VWAP）",
    "vol_spike": "同時段量比大於 2 倍",
    "near_limit_up": "距離漲停不到 1%",
    "dir_bull": "方向變成偏多",
    "dir_bear": "方向變成偏空",
    "stale": "資料延遲或抓不到",
}


@st.cache_data
def intraday(code: str, n: int = 103):
    s = STOCKS[code]
    if s["fresh"] == "none":
        return None
    rng = np.random.default_rng(s["seed"])
    drift = {"偏多": 0.0006, "中性偏多": 0.0003, "偏空": -0.0005, "中性偏空": -0.0002}.get(s["d"], 0.0)
    px = s["ref"] * np.exp(np.cumsum(rng.normal(drift, 0.0022, n)))
    if s["a"] == "無法正常交易":  # 示意鎖漲停：最後一段停在漲停
        up = float(pricing.limit_prices(s["ref"]).up)  # 漲停價依升降單位向下對齊
        px = np.minimum(px * 1.06, up)
        px[-25:] = up
    px = np.array([float(pricing.align_price(v, mode="nearest")) for v in px])  # 對齊合法升降單位
    vol = rng.integers(20, 400, n).astype(float)
    if s["a"] != "無法正常交易":
        quiet = rng.random(n) < 0.12            # 約 12% 的分鐘沒有成交
        quiet[0] = False
        vol[quiet] = 0
        for i in np.where(quiet)[0]:
            px[i] = px[i - 1]                    # 沒成交的分鐘沿用上一筆，只用來畫線
    idx = pd.date_range("2026-10-06 09:00", periods=n, freq="1min")
    vwap = np.cumsum(px * vol) / np.cumsum(vol)
    ask_ratio = float(np.clip(0.5 + (px[-1] / s["ref"] - 1) * 4 + rng.normal(0, 0.03), 0.2, 0.9))
    stvr = float(np.round(rng.uniform(0.6, 2.4), 2))
    return dict(df=pd.DataFrame({"px": px, "vwap": vwap, "vol": vol}, index=idx), ask_ratio=ask_ratio, stvr=stvr)


@st.cache_data
def daily(code: str, n: int = 80):
    s = STOCKS[code]
    rng = np.random.default_rng(100 + s["seed"])
    c = np.exp(np.cumsum(rng.normal(0.001, 0.018, n)))
    c = c / c[-1] * s["ref"]
    o = c * (1 + rng.normal(0, 0.006, n))
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.008, n)))
    l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.008, n)))
    idx = pd.bdate_range(end="2026-10-05", periods=n)
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c,
                       "Volume": rng.integers(2000, 20000, n)}, index=idx)
    return df


@st.cache_data
def chips(code: str):
    rng = np.random.default_rng(200 + STOCKS[code]["seed"])
    days = ["10/01", "10/02", "10/03", "10/04", "10/05"]
    return days, {k: rng.integers(-600, 800, 5).tolist() for k in ("外資", "投信", "自營商")}


@st.cache_data
def index_series(name: str, n: int = 103):
    rng = np.random.default_rng(301 if name == "加權指數" else 377)
    base = 22850.0 if name == "加權指數" else 262.4
    v = base * np.exp(np.cumsum(rng.normal(0.0002, 0.0007, n)))
    return pd.Series(v, index=pd.date_range("2026-10-06 09:00", periods=n, freq="1min")), base


def now_change(code: str):
    d = intraday(code)
    if d is None:
        return None
    last = float(d["df"]["px"].iloc[-1])
    return last, last - STOCKS[code]["ref"], (last / STOCKS[code]["ref"] - 1) * 100


# ════════════════════════════════════════════════
# 圖表
# ════════════════════════════════════════════════
def _layout(fig, height):
    fig.update_layout(template="plotly_dark", height=height, margin=dict(l=4, r=4, t=4, b=4), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(showgrid=False, tickfont=dict(size=10, color=C["muted"]))
    fig.update_yaxes(gridcolor="#1c2533", tickfont=dict(size=10, color=C["muted"]), side="right")
    return fig


def chart_rt(df: pd.DataFrame, ref: float, height: int, at_time=None):
    last = df["px"].iloc[-1]
    col = ui.color_for_change(last - ref)
    fig = go.Figure()
    fig.add_hline(y=ref, line=dict(color="#56637a", width=1, dash="dot"))
    fig.add_trace(go.Scatter(x=df.index, y=df["px"], mode="lines", line=dict(color=col, width=1.8),
                             hovertemplate="%{x|%H:%M}　%{y:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=df.index, y=df["vwap"], mode="lines", line=dict(color="#e8edf5", width=1, dash="dot"),
                             hoverinfo="skip"))
    if at_time is not None:
        fig.add_vline(x=at_time, line=dict(color=C["gold"], width=1.5))
    _layout(fig, height)
    fig.update_xaxes(tickformat="%H:%M", nticks=5)
    return fig


def chart_k(df: pd.DataFrame, minutes: int, height: int, at_time=None):
    k = df.loc[df["vol"] > 0, "px"].resample(f"{minutes}min").ohlc().dropna()
    fig = go.Figure(go.Candlestick(x=k.index, open=k.open, high=k.high, low=k.low, close=k.close,
                                   increasing=dict(line=dict(color=C["up"]), fillcolor=C["up"]),
                                   decreasing=dict(line=dict(color=C["down"]), fillcolor=C["down"])))
    if at_time is not None:
        fig.add_vline(x=at_time, line=dict(color=C["gold"], width=1.5))
    _layout(fig, height)
    fig.update_xaxes(tickformat="%H:%M", nticks=5, rangeslider_visible=False)
    return fig


def chart_ta(code: str, height: int, sub: str):
    d = daily(code).tail(60).copy()
    full = daily(code)
    for n, colr in ((5, C["gold"]), (20, C["blue"])):
        d[f"MA{n}"] = full["Close"].rolling(n).mean().tail(60)
    rows = 2 if sub != "不顯示" else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28] if rows == 2 else [1],
                        vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close,
                                 increasing=dict(line=dict(color=C["up"]), fillcolor=C["up"]),
                                 decreasing=dict(line=dict(color=C["down"]), fillcolor=C["down"])), row=1, col=1)
    for n, colr in ((5, C["gold"]), (20, C["blue"])):
        fig.add_trace(go.Scatter(x=d.index, y=d[f"MA{n}"], line=dict(color=colr, width=1.2), hoverinfo="skip"),
                      row=1, col=1)
    if rows == 2:
        import indicators as ind
        if sub == "KD":
            _, _, _, k, dd = ind.kd(full["High"], full["Low"], full["Close"])
            fig.add_trace(go.Scatter(x=d.index, y=k.tail(60), line=dict(color=C["gold"], width=1.2)), row=2, col=1)
            fig.add_trace(go.Scatter(x=d.index, y=dd.tail(60), line=dict(color=C["blue"], width=1.2)), row=2, col=1)
        elif sub == "MACD":
            _, _, _, _, osc = ind.macd(full["Close"])
            o = osc.tail(60)
            fig.add_trace(go.Bar(x=d.index, y=o, marker_color=np.where(o >= 0, C["up"], C["down"])), row=2, col=1)
        elif sub == "RSI":
            fig.add_trace(go.Scatter(x=d.index, y=ind.rsi(full["Close"]).tail(60), line=dict(color=C["gold"], width=1.2)),
                          row=2, col=1)
    _layout(fig, height + (40 if rows == 2 else 0))
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], rangeslider_visible=False, nticks=4)
    return fig


def chart_chip(code: str, height: int):
    days, data = chips(code)
    fig = go.Figure()
    for k, colr in zip(data, (C["blue"], C["gold"], C["purple"])):
        fig.add_trace(go.Bar(x=days, y=data[k], name=k, marker_color=colr))
    _layout(fig, height)
    fig.update_layout(barmode="group", showlegend=True,
                      legend=dict(orientation="h", y=1.15, x=0, font=dict(size=10, color=C["text"])))
    return fig


def orderbook_html(code: str) -> str:
    nc = now_change(code)
    if nc is None:
        return "<div class='nodata' style='--h:120px'>沒有五檔資料</div>"
    last = nc[0]
    rng = np.random.default_rng(400 + STOCKS[code]["seed"])
    tick = float(pricing.tick_size(last))
    bids = [(last - tick * i, int(rng.integers(50, 900))) for i in range(5)]
    asks = [(last + tick * (i + 1), int(rng.integers(50, 900))) for i in range(5)]
    if STOCKS[code]["a"] == "無法正常交易":
        asks = [(None, 0)] * 5
    mx = max(s for _, s in bids + asks) or 1
    rows = ""
    for (bp, bs), (ap, as_) in zip(bids, asks):
        ap_s = "—" if ap is None else f"{ap:.2f}"
        rows += (f"<tr><td style='width:22%'><div style='background:{C['up']};height:6px;border-radius:3px;"
                 f"width:{bs / mx * 100:.0f}%;margin-left:auto'></div></td><td style='text-align:right;color:#8b97a8'>{bs:,}</td>"
                 f"<td style='text-align:right;color:{C['up']};font-weight:800'>{bp:.2f}</td>"
                 f"<td style='color:{C['down']};font-weight:800'>{ap_s}</td><td style='color:#8b97a8'>{as_ or ''}</td>"
                 f"<td style='width:22%'><div style='background:{C['down']};height:6px;border-radius:3px;"
                 f"width:{as_ / mx * 100:.0f}%'></div></td></tr>")
    return f"<table class='ob'>{rows}</table>"


PRICE_RULES = {"below_vwap", "above_vwap", "vol_spike", "near_limit_up", "dir_bull", "dir_bear"}


def rule_state(code: str, rule: str) -> str:
    """ARMED＝等待中、TRIGGERED＝條件成立、STALE＝資料延遲或沒資料，暫停判斷（不拿舊資料一直觸發）。"""
    if rule in PRICE_RULES and STOCKS[code]["fresh"] != "live":
        return "STALE"
    return "TRIGGERED" if rule_hit(code, rule) else "ARMED"


def rule_hit(code: str, rule: str) -> bool:
    s = STOCKS[code]
    d = intraday(code)
    if rule == "stale":
        return s["fresh"] != "live"
    if rule == "dir_bull":
        return s["d"] == "偏多"
    if rule == "dir_bear":
        return s["d"] == "偏空"
    if d is None:
        return False
    last, vw = float(d["df"]["px"].iloc[-1]), float(d["df"]["vwap"].iloc[-1])
    if rule == "below_vwap":
        return last < vw
    if rule == "above_vwap":
        return last > vw
    if rule == "vol_spike":
        return d["stvr"] > 2
    if rule == "near_limit_up":
        up = float(pricing.limit_prices(s["ref"]).up)
        return (up - last) / up < 0.01
    return False


# ════════════════════════════════════════════════
# 側邊欄：看盤設定（使用者自己開關）
# ════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### ⚙️ 看盤設定")
    st.caption("每個功能都可以自己開關。預覽頁設定只存在這次瀏覽；正式版會存到你的帳號。")
    f_alert = st.toggle("🔔 條件提醒", value=True)
    f_rank = st.toggle("📊 允許排行榜格", value=True)
    f_index = st.toggle("🏛️ 允許大盤格", value=True)
    f_blink = st.toggle("✨ 提醒閃爍效果", value=True, help="關掉後改成醒目邊框，不會一直閃")
    f_time = st.toggle("🕒 時間對照（即時走勢／分K 對同一時間）", value=False)
    f_hint = st.toggle("🔰 新手提示", value=True)
    ta_sub = st.selectbox("技術分析副圖（一次一個）", ["KD", "MACD", "RSI", "不顯示"], index=0,
                          help="多檔畫面一次只顯示一個副圖；放大頁可以分頁看")

    def _reset_cells():
        st.query_params["v"] = ",".join(["rt"] * 6)
        for k in [k for k in st.session_state if str(k).startswith(("slot_", "view_", "rank_"))]:
            del st.session_state[k]

    st.button("↺ 重設所有格子的畫面", on_click=_reset_cells, help="全部格子回到「即時走勢」")

    rules = []
    if f_alert:
        st.markdown("#### 🔔 我的提醒條件")
        if "rules" not in st.session_state:
            st.session_state.rules = [("9991", "above_vwap"), ("9993", "below_vwap"), ("9996", "near_limit_up"),
                                       ("9995", "vol_spike")]
        for i, (c, r) in enumerate(st.session_state.rules):
            cols = st.columns([3, 1.3])
            state = rule_state(c, r)
            badge_ = {"TRIGGERED": "🔔 條件成立", "ARMED": "🟢 等待中", "STALE": "⚪ 資料延遲，暫停判斷"}[state]
            cols[0].markdown(f"<span style='font-size:13px'>{c} {STOCKS[c]['name']}：{ALERT_RULES[r]}<br>"
                             f"<b style='font-size:12px'>{badge_}</b></span>", unsafe_allow_html=True)
            if cols[1].button("刪除", key=f"del_rule_{i}", help="刪除這條提醒"):
                st.session_state.rules.pop(i)
                st.rerun()
        with st.form("add_rule", clear_on_submit=True):
            nc_ = st.selectbox("股票", CODES, format_func=lambda c: f"{c} {STOCKS[c]['name']}")
            nr_ = st.selectbox("條件", list(ALERT_RULES), format_func=ALERT_RULES.get)
            if st.form_submit_button("＋ 新增提醒"):
                st.session_state.rules.append((nc_, nr_))
                st.rerun()
        rules = list(st.session_state.rules)
        st.caption("提醒只描述「條件成立」，不是買賣建議。資料延遲時暫停判斷。"
                   "預覽頁不會在背景監控；正式版接上即時資料後才會持續檢查，並避免同一條件重複一直跳。")

    st.markdown("#### 💾 儲存")
    st.caption("股票清單和版面分開存：同一組股票可以配不同版面。")
    if "layouts" not in st.session_state:
        st.session_state.layouts = {}
    if "my_lists" not in st.session_state:
        st.session_state.my_lists = {}

    def _save_layout():
        name = st.session_state.get("layout_name", "").strip() or f"我的版面 {len(st.session_state.layouts) + 1}"
        st.session_state.layouts[name] = tuple(str(st.query_params.get("v", "")).split(","))
        st.toast(f"已儲存版面「{name}」（每格看什麼畫面）。")

    def _save_list():
        name = st.session_state.get("list_name", "").strip() or f"我的清單 {len(st.session_state.my_lists) + 1}"
        st.session_state.my_lists[name] = tuple(str(st.query_params.get("w", "")).split(","))
        st.toast(f"已儲存自選清單「{name}」（哪幾檔、什麼順序）。")

    st.text_input("自選清單名稱", value="", placeholder="例如：今天想看的", key="list_name")
    st.button("儲存目前股票為自選清單", on_click=_save_list)
    st.text_input("版面名稱", value="", placeholder="例如：早盤當沖", key="layout_name")
    st.button("儲存目前版面", on_click=_save_layout)


hits = {}
for c, r in rules:
    if rule_state(c, r) == "TRIGGERED":
        hits.setdefault(c, []).append(ALERT_RULES[r])


# ════════════════════════════════════════════════
# 版面狀態：存在網址
# ════════════════════════════════════════════════
def valid_slot(x: str) -> bool:
    return x in STOCKS or (x == "RANK" and f_rank) or (x == "INDEX" and f_index)


def parse_list(raw, ok, default):
    if not raw:
        return list(default)
    out = [x for x in str(raw).split(",") if ok(x)]
    return out or list(default)


watch = parse_list(st.query_params.get("w"), valid_slot, WATCHLISTS["今天當沖"])
# 同一檔不重複（特殊格可以只有一個）
seen = []
for x in watch:
    if x not in seen:
        seen.append(x)
watch = seen[:6]
views = parse_list(st.query_params.get("v"), lambda x: x in VIEWS, ["rt"] * 6)
views = (views + ["rt"] * 6)[:6]


def qs(watch_, views_=None) -> str:
    q = "w=" + ",".join(watch_)
    if views_:
        q += "&v=" + ",".join(views_)
    return q


# ════════════════════════════════════════════════
# 放大模式（單檔）
# ════════════════════════════════════════════════
focus = st.query_params.get("focus")
if focus is not None:
    if focus not in STOCKS or focus not in watch:
        st.warning("這個代號不在看盤清單裡，已回到多檔看盤。")
    else:
        s = STOCKS[focus]
        st.markdown(f"<a class='zoom' href='?{qs(watch, views)}' target='_self'>← 回多檔看盤</a>",
                    unsafe_allow_html=True)
        nc = now_change(focus)
        if nc is None:
            st.markdown(ui.hero(s["name"], focus, 0, 0, 0, ui.badge("無資料", "demo")), unsafe_allow_html=True)
            st.info("暫時抓不到這檔的資料。")
        else:
            st.markdown(ui.hero(s["name"], focus, nc[0], nc[1], nc[2],
                                ui.badge(f"即時・富果 {T}（示意）", "live") + ui.badge("示意資料", "demo")),
                        unsafe_allow_html=True)
            st.markdown(ui.status3(s["d"], ui.esc(s["why"]), s["r"], "（示意）", s["a"], "（示意）"),
                        unsafe_allow_html=True)
            tabs = st.tabs(["即時走勢", "技術分析（KD）", "技術分析（MACD）", "技術分析（RSI）", "分K", "籌碼", "五檔"])
            with tabs[0]:
                st.plotly_chart(chart_rt(intraday(focus)["df"], s["ref"], 420), use_container_width=True)
            for t_, sub in zip(tabs[1:4], ("KD", "MACD", "RSI")):   # 放大頁才能同時看多個副圖
                with t_:
                    st.plotly_chart(chart_ta(focus, 420, sub), use_container_width=True, key=f"focus_ta_{sub}")
            with tabs[4]:
                km = st.radio("週期", [1, 5, 15], index=1, horizontal=True, format_func=lambda m: f"{m} 分K")
                st.plotly_chart(chart_k(intraday(focus)["df"], km, 420), use_container_width=True)
            with tabs[5]:
                st.plotly_chart(chart_chip(focus, 360), use_container_width=True)
            with tabs[6]:
                st.markdown(orderbook_html(focus), unsafe_allow_html=True)
        st.caption("正式版的放大頁就是完整的單檔頁（K線、五檔、法人、風險參考價、資料狀況）。")
        st.stop()

# ════════════════════════════════════════════════
# 上方工具列
# ════════════════════════════════════════════════
c1, c2, c5, c3, c4 = st.columns([1.3, 1.4, 1.3, 1.5, 1.1])
with c1:
    layout = st.radio("版面", ["4 格（2×2）", "6 格（3×2）"], horizontal=True, label_visibility="collapsed")
n = 4 if layout.startswith("4") else 6
with c2:
    wl = st.selectbox("📋 自選清單", ["（目前的）"] + list(WATCHLISTS) + list(st.session_state.my_lists),
                      help="一鍵換整組股票（只換股票，不動每格的畫面設定）")
with c5:
    lay = st.selectbox("🗂️ 我的版面", ["（目前的）"] + list(st.session_state.layouts),
                       help="套用儲存過的版面（每格看什麼畫面），不動股票清單")
with c3:
    all_view = st.selectbox("🔀 全部切換", ["（各格自己選）"] + list(VIEWS.values()),
                            help="一鍵把所有股票格切成同一種畫面（排行榜、大盤格不受影響）")
with c4:
    st.selectbox("自動更新", ["每 5 秒", "每 10 秒", "每 30 秒", "暫停"], index=1, label_visibility="collapsed",
                 help="預覽頁不會真的更新；正式版由 MarketDataCoordinator 集中排程抓取")

if wl in WATCHLISTS:
    watch = list(WATCHLISTS[wl])
elif wl in st.session_state.my_lists:
    watch = [x for x in st.session_state.my_lists[wl] if valid_slot(x)] or watch
if lay in st.session_state.layouts:
    views = ([x for x in st.session_state.layouts[lay] if x in VIEWS] + ["rt"] * 6)[:6]
if all_view != "（各格自己選）":
    code_of = {v: k for k, v in VIEWS.items()}
    views = [code_of[all_view]] * 6

slots = (watch + [c for c in CODES if c not in watch])[:6]

at_time = None
if f_time:
    tmin = pd.Timestamp("2026-10-06 09:00")
    t = st.slider("🕒 時間對照：即時走勢、分K 同時看這個時間（日K、籌碼、五檔不受影響）",
                  min_value=0, max_value=102, value=60, format="%d 分鐘")
    at_time = tmin + pd.Timedelta(minutes=t)
    st.caption(f"目前對照時間：{at_time:%H:%M}")

if hits:
    msg = "　".join(f"🔔 條件成立｜{c} {STOCKS[c]['name']}：{'、'.join(v)}" for c, v in hits.items())
    st.markdown(f"<div class='alertbar'>{ui.esc(msg)}</div>", unsafe_allow_html=True)


# ════════════════════════════════════════════════
# 格子
# ════════════════════════════════════════════════
def light(k: str, v: str, color: str) -> str:
    return f"<div class='light' style='--c:{color}'><div class='k'>{k}</div><div class='v'>{ui.esc(v)}</div></div>"


def slot_picker(i: int, current: str):
    opts = list(CODES) + ([x for x in ("RANK", "INDEX") if (x == "RANK" and f_rank) or (x == "INDEX" and f_index)])
    idx = opts.index(current) if current in opts else 0
    return st.selectbox(f"第 {i + 1} 格", opts, index=idx, key=f"slot_{i}_{current}", label_visibility="collapsed",
                        format_func=lambda c: SPECIAL.get(c, f"{c} {STOCKS[c]['name']}" if c in STOCKS else c))


def view_picker(i: int, current: str):
    return st.selectbox(f"第 {i + 1} 格畫面", list(VIEWS), index=list(VIEWS).index(current),
                        key=f"view_{i}_{current}", label_visibility="collapsed", format_func=VIEWS.get)


def time_note(df: pd.DataFrame):
    """時間對照：該分鐘沒有成交就照實說，不拿上一筆冒充當時成交價。"""
    if at_time is None:
        return
    row = df.loc[at_time] if at_time in df.index else None
    if row is not None and row["vol"] > 0:
        st.markdown(f"<div class='dt'>🕒 {at_time:%H:%M} 成交價 <b>{row['px']:.2f}</b></div>", unsafe_allow_html=True)
    else:
        prev = df.loc[(df.index <= at_time) & (df["vol"] > 0), "px"]
        last_s = f"（最後一筆成交 {prev.iloc[-1]:.2f}，{prev.index[-1]:%H:%M}）" if len(prev) else ""
        st.markdown(f"<div class='dt'>🕒 {at_time:%H:%M} 該分鐘無成交{last_s}</div>", unsafe_allow_html=True)


def stock_cell(i: int, code: str, view: str, height: int, compact: bool):
    s = STOCKS[code]
    d = intraday(code)
    nc = now_change(code)
    head = f"<div><span class='nm'>{ui.esc(s['name'])}</span><span class='cd'>{code}</span></div>"
    if nc is None:
        price_html = "<div><div class='px' style='color:#8b97a8'>—</div><div class='chg' style='color:#8b97a8'>無報價</div></div>"
    else:
        last, chg, pct = nc
        col = ui.color_for_change(chg)
        arrow = "▲" if chg > 0 else "▼" if chg < 0 else "－"
        price_html = (f"<div><div class='px' style='color:{col}'>{last:,.2f}</div>"
                      f"<div class='chg' style='color:{col}'>{arrow} {abs(chg):.2f}（{pct:+.2f}%）</div></div>")
    alert = ""
    if code in hits:
        cls = "alerting" if f_blink else "alerting-static"
        alert = f"<div class='{cls}'>🔔 條件成立：{ui.esc('、'.join(hits[code]))}</div>"
    hint = ""
    if f_hint:   # 新手提示一律取自 glossary（SSOT）
        key_ = ("locked_up" if s["a"] == "無法正常交易" else "stale" if s["fresh"] == "stale"
                else "insufficient" if s["fresh"] == "none" else None)
        if key_:
            g_ = glossary.get(key_)
            hint = f"<div class='hint'>💡 {ui.esc(g_.term)}：{ui.esc(g_.plain_language)}。</div>"
    st.markdown(
        f"<div class='cell{' compact' if compact else ''}'>{alert}<div class='top'>{head}{price_html}</div>"
        f"<div class='lights'>{light('方向', s['d'], ui.DIRECTION_COLOR.get(s['d'], C['flat']))}"
        f"{light('風險', s['r'], ui.RISK_COLOR.get(s['r'], C['flat']))}"
        f"{light('能不能做', s['a'], ui.ACTION_COLOR.get(s['a'], C['flat']))}</div>"
        f"<div class='why1' title='{ui.esc(s['why'])}'>{ui.esc(s['why'])}</div>{hint}</div>",
        unsafe_allow_html=True)

    if view in INTRADAY_VIEWS and d is None:
        st.markdown(f"<div class='nodata' style='--h:{height}px'>暫時抓不到這檔的資料<br>其他格不受影響</div>",
                    unsafe_allow_html=True)
    elif view == "rt":
        st.plotly_chart(chart_rt(d["df"], s["ref"], height, at_time), use_container_width=True,
                        config={"displayModeBar": False}, key=f"rt_{i}_{code}")
        time_note(d["df"])
    elif view in K_MIN:
        st.plotly_chart(chart_k(d["df"], K_MIN[view], height, at_time), use_container_width=True,
                        config={"displayModeBar": False}, key=f"k_{i}_{code}")
        time_note(d["df"])
    elif view == "ta":
        st.plotly_chart(chart_ta(code, height, ta_sub), use_container_width=True,
                        config={"displayModeBar": False}, key=f"ta_{i}_{code}")
        st.markdown("<div class='fresh' style='margin-top:-4px'>日K・只用已收完的K線（示意）</div>",
                    unsafe_allow_html=True)
    elif view == "chip":
        st.plotly_chart(chart_chip(code, height), use_container_width=True,
                        config={"displayModeBar": False}, key=f"chip_{i}_{code}")
        st.markdown("<div class='fresh' style='margin-top:-4px'>盤後・資料日 10/05・單位：張（示意）</div>",
                    unsafe_allow_html=True)
    elif view == "ob":
        st.markdown(orderbook_html(code), unsafe_allow_html=True)

    if d is not None:
        df = d["df"]
        last, vw = float(df["px"].iloc[-1]), float(df["vwap"].iloc[-1])
        gap = (last / vw - 1) * 100
        acol = C["up"] if d["ask_ratio"] > 0.5 else C["down"]
        st.markdown(
            f"<div class='dt'><span>同時段量比{tip('same_time_volume_ratio')} <b>{d['stvr']:.2f} 倍</b></span>"
            f"<span>外盤比{tip('ask_ratio')} <b style='color:{acol}'>{d['ask_ratio'] * 100:.0f}%</b></span>"
            f"<span>距 VWAP{tip('vwap')} <b style='color:{ui.color_for_change(gap)}'>{gap:+.2f}%</b></span></div>",
            unsafe_allow_html=True)

    dcol, dtxt = FRESH[s["fresh"]]
    when = "—" if s["age"] is None else (f"{T}（{s['age']} 秒前）" if not compact else f"{s['age']} 秒前")
    src = "" if compact else "富果・"
    st.markdown(
        f"<div class='foot'><span class='fresh'><span class='dot' style='background:{dcol}'></span>"
        f"{dtxt}・{src}{when}（示意）</span>"
        f"<a class='zoom' href='?focus={code}&{qs(slots_now + list(slots[n:]), views_now + list(views[n:6]))}' target='_blank' "
        f"title='在新分頁打開，可拖到另一個螢幕'>⤢ 放大／新分頁</a></div>",
        unsafe_allow_html=True)


RANK_KINDS = {"成交量": "vol", "漲幅": "up", "跌幅": "down", "外資買超": "fi"}


def rank_cell(i: int, height: int):
    st.markdown("<b>示意排行榜</b>", unsafe_allow_html=True)
    kind = st.radio("排行", list(RANK_KINDS), horizontal=True, key=f"rank_kind_{i}", label_visibility="collapsed")
    rows = []
    for c in CODES:
        nc = now_change(c)
        if nc is None:
            continue
        d = intraday(c)
        rows.append(dict(code=c, pct=nc[2], vol=float(d["df"]["vol"].sum()), fi=chips(c)[1]["外資"][-1]))
    key = {"vol": "vol", "up": "pct", "down": "pct", "fi": "fi"}[RANK_KINDS[kind]]
    rows.sort(key=lambda r: r[key], reverse=RANK_KINDS[kind] != "down")
    target = st.selectbox("放到第幾格", [j + 1 for j in range(n) if j != i], key=f"rank_target_{i}",
                          index=None, placeholder="① 先選要放到第幾格",
                          format_func=lambda j: f"放到第 {j} 格")
    if target is None:
        st.markdown("<div class='fresh'>② 再點下面的股票（沒選格子前不會換）</div>", unsafe_allow_html=True)
    for rk, r in enumerate(rows[:6], 1):
        col_a, col_b = st.columns([3, 2])
        val = {"vol": f"{r['vol']:,.0f} 張", "pct": f"{r['pct']:+.2f}%", "fi": f"{r['fi']:+,} 張"}[key]
        if col_a.button(f"{rk}. {r['code']} {STOCKS[r['code']]['name']}", key=f"rk_{i}_{r['code']}",
                        use_container_width=True, disabled=target is None):
            new = list(slots_now) + list(slots[n:])
            if r["code"] in new:  # 已在別格 → 兩格交換，避免同一檔出現兩次
                new[new.index(r["code"])] = new[target - 1]
            new[target - 1] = r["code"]
            st.query_params["w"] = ",".join(new[:6])
            st.query_params["v"] = ",".join(views_now + list(views[n:6]))
            st.rerun()
        col_b.markdown(f"<div style='padding-top:8px;font-weight:800;color:"
                       f"{ui.color_for_change(r['pct']) if key == 'pct' else C['text']}'>{val}</div>",
                       unsafe_allow_html=True)
    st.markdown("<div class='fresh'>排行只呈現數字高低，不代表推薦（示意）</div>", unsafe_allow_html=True)


def index_cell(i: int, height: int):
    for name in ("加權指數", "櫃買指數"):
        sr, base = index_series(name)
        last = float(sr.iloc[-1])
        chg = last - base
        col = ui.color_for_change(chg)
        st.markdown(f"<div class='top' style='display:flex;justify-content:space-between'><b>{name}</b>"
                    f"<span style='color:{col};font-weight:900'>{last:,.2f}　{chg:+,.2f}（{chg / base * 100:+.2f}%）</span></div>",
                    unsafe_allow_html=True)
        fig = go.Figure()
        fig.add_hline(y=base, line=dict(color="#56637a", width=1, dash="dot"))
        fig.add_trace(go.Scatter(x=sr.index, y=sr, line=dict(color=col, width=1.6), hoverinfo="skip"))
        if at_time is not None:
            fig.add_vline(x=at_time, line=dict(color=C["gold"], width=1.5))
        _layout(fig, height // 2)
        fig.update_xaxes(tickformat="%H:%M", nticks=4)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=f"idx_{i}_{name}")
    st.markdown("<div class='fresh'>大盤指數（示意）</div>", unsafe_allow_html=True)


# ── 先決定每格內容（使用者在格子內改代號／畫面）────────
slots_now = list(slots[:n])
views_now = list(views[:n])
cols_per_row = 2 if n == 4 else 3
compact = n == 6
h = 220 if n == 4 else 150

grid = []
for r in range(0, n, cols_per_row):
    grid.extend(st.columns(cols_per_row, gap="small"))

for i, colw in enumerate(grid[:n]):
    with colw:
        with st.container(border=True):
            p1, p2 = st.columns([3, 2])
            with p1:
                slots_now[i] = slot_picker(i, slots_now[i])
            if slots_now[i] in STOCKS:
                with p2:
                    views_now[i] = view_picker(i, views_now[i])
            x = slots_now[i]
            if x == "RANK":
                rank_cell(i, h)
            elif x == "INDEX":
                index_cell(i, h)
            else:
                stock_cell(i, x, views_now[i], h, compact)

# 網址存完整 6 格（4 格模式時，第 5、6 格保留原本的設定，切回 6 格不會不見）
full_slots = slots_now + [x for x in slots[n:] + watch[n:] if x not in slots_now][:6 - n]
full_views = views_now + list(views[n:6])
st.query_params["w"] = ",".join(full_slots[:6])
st.query_params["v"] = ",".join(full_views[:6])

st.markdown("<div style='margin-top:12px;color:#8b97a8;font-size:12px'>"
            "資料狀態：🟢 即時　🟡 延遲（超過 60 秒沒更新）　⚪ 無資料。"
            "灰色虛線＝參考價（昨收）；白色虛線＝當日均價（VWAP）。"
            "方向／風險／能不能做由判斷引擎產生，這裡是示意。本站內容為資訊整理，不是投資建議。</div>",
            unsafe_allow_html=True)
