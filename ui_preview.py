# -*- coding: utf-8 -*-
"""新介面預覽頁（GPT 平行工作 P-B）。

- 只用虛構資料（9999 範例科技），頁面頂部永久顯示「示意資料／非真實行情」。
- 不 import engine、不連任何 API，也不讀 everlight_app.py。
- 啟動：streamlit run ui_preview.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import ui_theme as ui
from ui_theme import C, badge, card, section, term, tip

st.set_page_config(page_title="台股戰情室｜新介面預覽", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(ui.css(), unsafe_allow_html=True)
st.markdown(ui.demo_banner(), unsafe_allow_html=True)

# ── 虛構資料 ─────────────────────────────────────────
NAME, CODE = "範例科技", "9999"
REF, PRICE = 50.20, 52.30
LIMIT_UP, LIMIT_DN = 55.20, 45.20
T = "10:42:15"


@st.cache_data
def demo_daily(n=140):
    rng = np.random.default_rng(9999)
    idx = pd.bdate_range(end="2026-10-05", periods=n)
    c = 38 * np.exp(np.cumsum(rng.normal(0.0025, 0.018, n)))
    c = c / c[-1] * REF
    o = c * (1 + rng.normal(0, 0.006, n))
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.008, n)))
    l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.008, n)))
    v = rng.integers(3000, 18000, n) * (1 + (np.arange(n) > n - 8) * 0.8)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


df = demo_daily()

# ── 頂部 ─────────────────────────────────────────────
top_l, top_r = st.columns([3, 1])
with top_l:
    st.text_input("🔍 輸入股票代號或名稱", value=f"{CODE} {NAME}", disabled=True,
                  help="預覽頁固定顯示虛構股票")
with top_r:
    newbie = st.toggle("🔰 新手模式", value=True, help="開啟後，每個名詞下面直接顯示白話說明")

chg = PRICE - REF
meta = (badge(f"即時・富果 {T}（示意）", "live") + badge("示意資料", "demo") +
        f"<br>{term('參考價', 'ref_price')} {REF:.2f}　｜　{term('漲停', 'limit_up')} "
        f"<span style='color:{C['up']}'>{LIMIT_UP:.2f}</span>　｜　{term('跌停', 'limit_down')} "
        f"<span style='color:{C['down']}'>{LIMIT_DN:.2f}</span>")
st.markdown(ui.hero(NAME, CODE, PRICE, chg, chg / REF * 100, meta), unsafe_allow_html=True)

# ── 四個週期：方向／風險／可操作 ─────────────────────
st.markdown(section("看你要做多久", "daytrade"), unsafe_allow_html=True)
if newbie:
    st.markdown("<div class='newbie'>先選你打算持有多久。同一檔股票，當沖和長線的看法可能完全不同。"
                "每個週期都固定分成三格：方向（往哪邊）、風險（追進去危不危險）、現在能不能做。</div>",
                unsafe_allow_html=True)

HORIZONS = {
    "⚡ 當沖": dict(
        d="偏多", dw="3 個有效家族中，2 個支持偏多、1 個中性<br>・"
        + term("內外盤比", "ask_ratio") + " 58%，現價在 " + term("VWAP", "vwap") + " 51.86 之上<br>・"
        + term("同時段量比", "same_time_volume_ratio") + " 1.82 倍放量；尚未突破開盤 30 分鐘區間（中性）",
        r="中", rw="⚠️ 今日振幅 6.1%，比平常大",
        a="可操作", aw="盤中、資料 3 秒前更新、未鎖漲跌停"),
    "📅 短線": dict(
        d="偏多", dw="4 個有效家族中，3 個支持偏多、1 個中性<br>・"
        + term("均線多頭排列", "ma_alignment") + "・" + term("KD", "kd") + " 黃金交叉・"
        + term("外資", "foreign") + "連 3 買",
        r="高", rw="⚠️ " + term("RSI", "rsi") + " 82 過熱<br>⚠️ " + term("乖離率", "bias") + "：MA20 正乖離 +16.2%",
        a="不宜追價", aw="今日已漲 4.2%，方向雖偏多但已漲多，可等拉回再評估"),
    "🌊 波段": dict(
        d="中性偏多", dw="3 個有效家族中，1 個支持偏多、2 個中性<br>・"
        + term("月營收", "revenue") + "家族：資料不足（只有 2 個月），不計入",
        r="中", rw="⚠️ " + term("融資增減", "margin_change") + " 3 日 +11.4%",
        a="等待回測", aw="價格離 MA20 較遠，等回到均線附近再看"),
    "🏛️ 長線": dict(
        d="資料不足", dw="5 個家族中只有 2 個有資料，少於一半<br>・缺 "
        + term("EPS", "eps") + "（必要資料）",
        r="低", rw="沒有風險標記",
        a="資料不足", aw="EPS 補齊後才會判斷"),
}
tabs = st.tabs(list(HORIZONS))
for tab, (label, h) in zip(tabs, HORIZONS.items()):
    with tab:
        st.markdown(ui.status3(h["d"], h["dw"], h["r"], h["rw"], h["a"], h["aw"], newbie), unsafe_allow_html=True)
        if label == "⚡ 當沖":
            # 當沖強度表（GPT 建議；百分比區間是 v0 固定區間，第三段回測前不是最佳進場點）
            rows_dt = [
                ("今日漲跌幅", "ref_price", f"<span style='color:{C['up']}'>+4.18%</span>", "偏強區（+2%～+5%），仍要看量、外盤、均價"),
                ("同時段量比", "same_time_volume_ratio", "1.82 倍", "明顯放量（比過去 20 天 10:42 的平均累計量）"),
                ("外盤比", "ask_ratio", f"<span style='color:{C['up']}'>58%</span>", "主動買略多"),
                ("現價 vs VWAP", "vwap", f"<span style='color:{C['up']}'>高於 +0.85%</span>", "今天買進的人平均是賺的"),
                ("開盤 30 分鐘區間", "opening_range", "51.40～52.60", "目前在區間內，尚未突破"),
            ]
            trs = "".join(f"<tr><td>{term(n, k)}</td><td style='font-weight:800'>{v}</td>"
                          f"<td style='color:{C['muted']}'>{note}</td></tr>" for n, k, v, note in rows_dt)
            st.markdown(section("當沖強度表") + f"<table class='ob' style='font-size:14.5px'>{trs}</table>"
                        + badge("即時・富果（示意）", "live") + badge("漲跌幅區間為 v0 固定區間，尚未回測", "est"),
                        unsafe_allow_html=True)
        with st.expander("為什麼？（支持理由／反方理由／資料狀況）"):
            st.markdown(
                "<ul class='reason'><li>✅ 支持：上面列出的偏多家族</li>"
                "<li>❌ 反方：沒有家族偏空；風險標記另外列在 ② 風險</li>"
                "<li>📋 資料狀況：日K 140 根（已收完）、法人 10/05 盤後、內外盤 即時</li>"
                "<li>📌 規則版本 v0，尚未經歷史回測驗證；方向不是買賣建議</li></ul>",
                unsafe_allow_html=True)

# ── 關鍵數字卡片 ─────────────────────────────────────
st.markdown(section("盤中關鍵數字"), unsafe_allow_html=True)
k1, k2, k3, k4 = st.columns(4)
k1.markdown(card(term("量比", "volume_ratio", newbie), "1.8 倍", badge("即時", "live")), unsafe_allow_html=True)
k2.markdown(card(term("內外盤比", "ask_ratio", newbie), "外盤 58%", badge("即時・富果", "live"), C["up"]),
            unsafe_allow_html=True)
k3.markdown(card(term("VWAP 當日均價", "vwap", newbie), "51.86", badge("即時・富果", "live")),
            unsafe_allow_html=True)
k4.markdown(card(term("成交量", "volume", newbie), "18,420 張", badge("即時", "live")), unsafe_allow_html=True)

# ── K線圖 ───────────────────────────────────────────
st.markdown(section("K線圖", "kline"), unsafe_allow_html=True)
if newbie:
    g = ui.glossary
    st.markdown(f"<div class='newbie'>{ui.esc(g.get('red_k').term)}：{ui.esc(g.get('red_k').plain_language)}。"
                f"{ui.esc(g.get('green_k').term)}：{ui.esc(g.get('green_k').plain_language)}。"
                f"{ui.esc(g.get('ma').term)}：{ui.esc(g.get('ma').plain_language)}（黃線 MA5、藍線 MA20、紫線 MA60）。</div>",
                unsafe_allow_html=True)
d = df.tail(90).copy()
for n in (5, 20, 60):
    d[f"MA{n}"] = df["Close"].rolling(n).mean().tail(90)
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close, name="K線",
                             increasing=dict(line=dict(color=C["up"]), fillcolor=C["up"]),
                             decreasing=dict(line=dict(color=C["down"]), fillcolor=C["down"])), row=1, col=1)
for n, colr in ((5, C["gold"]), (20, C["blue"]), (60, C["purple"])):
    fig.add_trace(go.Scatter(x=d.index, y=d[f"MA{n}"], name=f"MA{n}", line=dict(color=colr, width=1.4)), row=1, col=1)
fig.add_trace(go.Bar(x=d.index, y=d.Volume / 1000, name="成交量（千張）",
                     marker_color=np.where(d.Close >= d.Open, C["up"], C["down"])), row=2, col=1)
fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=C["panel"],
                  height=460, margin=dict(l=8, r=8, t=8, b=8), xaxis_rangeslider_visible=False,
                  legend=dict(orientation="h", y=1.02, x=0, font=dict(color=C["text"])), font=dict(size=12, color=C["text"]))
fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor=C["line"])
fig.update_yaxes(gridcolor=C["line"])
st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
st.markdown(badge("日K・yfinance・第三方（示意）", "delayed") + badge("只用已收完的日K判斷", "after"),
            unsafe_allow_html=True)

# ── 五檔＋法人 ───────────────────────────────────────
c_ob, c_inst = st.columns(2)
with c_ob:
    st.markdown(section("五檔掛單", "orderbook"), unsafe_allow_html=True)
    bids = [(52.20, 312), (52.10, 455), (52.00, 820), (51.90, 260), (51.80, 198)]
    asks = [(52.30, 140), (52.40, 386), (52.50, 512), (52.60, 233), (52.70, 175)]
    mx = max(s for _, s in bids + asks)
    rows = "".join(
        f"<tr><td style='width:28%'><div class='bar' style='background:{C['up']};width:{bs / mx * 100:.0f}%;margin-left:auto'></div></td>"
        f"<td style='text-align:right;color:{C['muted']}'>{bs:,}</td><td style='text-align:right;color:{C['up']};font-weight:800'>{bp:.2f}</td>"
        f"<td style='color:{C['down']};font-weight:800'>{ap:.2f}</td><td style='color:{C['muted']}'>{as_:,}</td>"
        f"<td style='width:28%'><div class='bar' style='background:{C['down']};width:{as_ / mx * 100:.0f}%'></div></td></tr>"
        for (bp, bs), (ap, as_) in zip(bids, asks))
    st.markdown(f"<table class='ob'><tr style='color:{C['muted']};font-size:12px'><td></td><td style='text-align:right'>張</td>"
                f"<td style='text-align:right'>買價</td><td>賣價</td><td>張</td><td></td></tr>{rows}</table>"
                + badge(f"即時・富果 {T}（示意）", "live"), unsafe_allow_html=True)
    if newbie:
        st.markdown(f"<div class='newbie'>{ui.esc(ui.glossary.get('orderbook').plain_language)}。"
                    f"{ui.esc(ui.glossary.get('orderbook').common_misunderstanding)}</div>", unsafe_allow_html=True)
with c_inst:
    st.markdown(section("三大法人（近 5 日）", "institutional"), unsafe_allow_html=True)
    days = ["10/01", "10/02", "10/03", "10/04", "10/05"]
    data = {"外資": [-120, 340, 512, 288, 406], "投信": [35, 60, -12, 88, 120], "自營商": [-40, 12, 25, -8, 31]}
    f2 = go.Figure()
    for k, colr in zip(data, (C["blue"], C["gold"], C["purple"])):
        f2.add_trace(go.Bar(x=days, y=data[k], name=k, marker_color=colr))
    f2.update_layout(template="plotly_dark", barmode="group", height=260, paper_bgcolor="rgba(0,0,0,0)",
                     plot_bgcolor=C["panel"], margin=dict(l=8, r=8, t=8, b=8), legend=dict(orientation="h", y=1.1, font=dict(color=C["text"])), font=dict(color=C["text"]),
                     yaxis_title="張")
    st.plotly_chart(f2, use_container_width=True, config={"displayModeBar": False})
    st.markdown(badge("盤後・FinMind（示意）資料日 10/05", "after") + badge("單位：張", "after"),
                unsafe_allow_html=True)

# ── 風險參考價 ───────────────────────────────────────
st.markdown(section("風險參考價（v0 固定規則，尚未經歷史回測驗證）", "stop_loss"), unsafe_allow_html=True)
r1, r2, r3, r4 = st.columns(4)
r1.markdown(card(term("停損參考", "stop_loss", newbie), "49.60", "近 5 日最低價與 1.5×ATR 取較緊者", C["down"]),
            unsafe_allow_html=True)
r2.markdown(card(term("理論停利 1（1.5R）", "take_profit", newbie), "56.40",
                 f"⚠️ 高於今日{term('漲停', 'limit_up')}價 {LIMIT_UP:.2f}，今日無法到達，需隔日重算", C["up"]),
            unsafe_allow_html=True)
r3.markdown(card(term("R 倍數", "r_multiple", newbie), "1R = 2.70 元", "現價到停損的距離"), unsafe_allow_html=True)
r4.markdown(card(term("買 1 張最多虧", "cost", newbie), "約 2,990 元", "已含手續費與證交稅", C["gold"]),
            unsafe_allow_html=True)

# ── 資料狀況 ─────────────────────────────────────────
st.markdown(section("資料狀況清單", "third_party"),
            unsafe_allow_html=True)
STATUS = [
    ("現價／五檔／內外盤", "富果", ("即時", "live"), T, "否"),
    ("日K", "yfinance", ("第三方", "delayed"), "10/05 收盤", "否"),
    ("三大法人", "FinMind", ("盤後", "after"), "10/05", "否"),
    ("月營收", "FinMind", ("盤後", "after"), "2026/08（9/08 公布）", "否"),
    ("EPS", "—", ("缺資料", "demo"), "—", "—"),
]
rows = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{badge(*c)}</td><td>{d_}</td><td>{e}</td></tr>" for a, b, c, d_, e in STATUS)
st.markdown(f"<table class='ob' style='font-size:14px'><tr style='color:{C['muted']}'><td>資料</td><td>來源</td><td>類型</td>"
            f"<td>資料時間</td><td>估算</td></tr>{rows}</table>", unsafe_allow_html=True)

st.markdown("<div class='foot'>本頁為介面示意，數字全部虛構。正式版的方向、風險、可操作由判斷引擎產生，"
            "並經過回測驗證後才會移除「尚未回測」標示。本站內容為資訊整理，不是投資建議。</div>",
            unsafe_allow_html=True)
