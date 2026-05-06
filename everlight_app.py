import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import os
import datetime
import feedparser
from urllib.parse import quote  
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide", page_title="台股戰情室 Pro")

st.markdown("""<style>
html,body,[class*='st-']{background-color:#000;color:#eee;} 
.block-container{padding:1rem!important; max-width:98%!important;} 
.stTextInput input, .stNumberInput input {
    background-color:#222!important; color:#fff!important; border:1px solid #555!important;
}
</style>""", unsafe_allow_html=True)

# =====================
# 股票名稱字典
# =====================
@st.cache_data(ttl=86400)
def load_market_dict():
    d = {"1711": "永光", "永光": "1711", "2330": "台積電", "台積電": "2330", "2313": "華通", "華通": "2313"}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=5)
        if r.status_code == 200:
            for i in r.json():
                d[i["Code"]] = i["Name"]
                d[i["Name"]] = i["Code"]
    except:
        pass
    return d

MASTER_DICT = load_market_dict()

# =====================
# 頂部控制列
# =====================
c1, c2, c3, c4 = st.columns([3, 1.8, 1.4, 2.6])

with c1:
    page = st.radio("📌 頁面切換", ["📊 K線分析", "⚡ 即時趨勢", "📰 AI新聞預測"], horizontal=True)

with c2:
    # 🔥 細節修復 1：過濾全形與半形空白
    raw_input = st.text_input("🔍 股票代號 / 名稱", "1711")
    user_input = raw_input.replace("　", "").replace(" ", "").strip()
    
    if user_input.isdigit():
        symbol = user_input
        stock_name = MASTER_DICT.get(symbol, symbol)
    else:
        symbol = MASTER_DICT.get(user_input, user_input)
        stock_name = user_input

with c3:
    tf_label = st.selectbox("📈 K線週期", ["日K", "週K", "月K"])
    tf_map = {"日K": "1d", "週K": "1wk", "月K": "1mo"}
    period_map = {"日K": "6mo", "週K": "2y", "月K": "5y"}
    tf = tf_map[tf_label]
    period = period_map[tf_label]
    # 🔥 細節修復 2：動態擷取「日/週/月」字眼供 AI 預測使用
    time_unit = tf_label.replace("K", "")

with c4:
    TOKEN_FILE = "fugle_token.txt"

    def get_token():
        return open(TOKEN_FILE, "r").read().strip() if os.path.exists(TOKEN_FILE) else ""

    api_key = st.text_input("🔑 Fugle Token", value=get_token(), type="password")
    if api_key and api_key != get_token():
        with open(TOKEN_FILE, "w") as f:
            f.write(api_key)

# =====================
# 持股設定
# =====================
p1, p2 = st.columns(2)
with p1:
    qty = st.number_input("📦 持股張數", value=1.0, min_value=0.0, step=1.0)
with p2:
    cost = st.number_input("💰 平均成本", value=50.0, min_value=0.0, step=0.1)

st_autorefresh(interval=15000, key="auto_refresh")

# =====================
# 工具函式
# =====================
def flatten_columns(df):
    if not df.empty and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=30)
def fetch_history(symbol, period, interval):
    df = yf.download(f"{symbol}.TW", period=period, interval=interval, progress=False)
    suffix = ".TW"

    if df.empty:
        df = yf.download(f"{symbol}.TWO", period=period, interval=interval, progress=False)
        suffix = ".TWO"

    df = flatten_columns(df)

    if not df.empty:
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        limit_map = {"1d": 80, "1wk": 80, "1mo": 80}
        df = df.tail(limit_map.get(interval, 80))

    return df, suffix

@st.cache_data(ttl=10)
def fetch_intraday(symbol, suffix):
    df_i = yf.download(f"{symbol}{suffix}", period="1d", interval="1m", progress=False)
    df_i = flatten_columns(df_i)

    if not df_i.empty:
        df_i = df_i.dropna(subset=["Close"])
        if df_i.index.tz is None:
            df_i.index = df_i.index.tz_localize("Asia/Taipei")
        else:
            df_i.index = df_i.index.tz_convert("Asia/Taipei")

    return df_i

def fetch_fugle_quote(symbol, api_key):
    q = {}
    if not api_key: return q
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
        headers = {"X-API-KEY": api_key}
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200: q = r.json()
    except: pass
    return q

def price_color(price, prev_c):
    # 🔥 細節修復 4：增強顏色判斷防呆，避免 0 元時誤判
    if price == 0 or prev_c == 0: return "#fff"
    if price > prev_c: return "#ff3b3b"
    elif price < prev_c: return "#00e676"
    return "#fff"

# =====================
# 資料處理
# =====================
df, suffix = fetch_history(symbol, period, tf)

if df.empty:
    st.error(f"查無歷史資料，請確認股票代號 ({symbol}) 是否正確。")
    st.stop()

curr_yf = float(df["Close"].iloc[-1])
prev_c = float(df["Close"].iloc[-2]) if len(df) > 1 else curr_yf
open_p = float(df["Open"].iloc[-1])

q = fetch_fugle_quote(symbol, api_key)

curr = q.get("trade", {}).get("price", curr_yf)
if curr in [None, 0] or pd.isna(curr): curr = q.get("close", {}).get("price", curr_yf)
if curr in [None, 0] or pd.isna(curr): curr = curr_yf

open_p = q.get("priceOpen", {}).get("price", open_p)
if open_p in [None, 0] or pd.isna(open_p): open_p = float(df["Open"].iloc[-1])

bids, asks = q.get("bids", []), q.get("asks", [])

profit = (curr - cost) * qty * 1000
diff = curr - prev_c
pct = (diff / prev_c * 100) if prev_c else 0

# =====================
# 📊 K線分析頁
# =====================
if page == "📊 K線分析":
    st.markdown(f"## 📊 {stock_name} ({symbol}) {tf_label} 分析")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.02)

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="K線", increasing_line_color="#ff3b3b", decreasing_line_color="#00e676",
        increasing_fillcolor="#ff3b3b", decreasing_fillcolor="#00e676"
    ), row=1, col=1)

    if cost > 0:
        fig.add_trace(go.Scatter(x=df.index, y=[cost] * len(df), name="持股成本線", mode="lines", line=dict(color="cyan", width=2, dash="dash")), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=[curr] * len(df), name="即時現價線", mode="lines", line=dict(color="yellow", width=2, dash="dot")), row=1, col=1)

    vol_colors = ["rgba(255,59,59,0.45)" if c >= o else "rgba(0,230,118,0.45)" for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="成交量", marker_color=vol_colors), row=2, col=1)

    if tf == "1d":
        dt_obs = df.index.strftime("%Y-%m-%d").tolist()
        dt_all = pd.date_range(start=df.index[0], end=df.index[-1]).strftime("%Y-%m-%d").tolist()
        dt_breaks = [d for d in dt_all if d not in dt_obs]
        fig.update_xaxes(rangebreaks=[dict(values=dt_breaks)])

    fig.update_layout(template="plotly_dark", height=640, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hovermode="x unified")
    fig.update_yaxes(side="right", gridcolor="#222")
    st.plotly_chart(fig, use_container_width=True)

# =====================
# ⚡ 即時趨勢頁
# =====================
elif page == "⚡ 即時趨勢":
    st.markdown(f"## ⚡ {stock_name} ({symbol}) 即時趨勢")
    df_i = fetch_intraday(symbol, suffix)

    if not df_i.empty:
        now_ts = pd.Timestamp.now(tz="Asia/Taipei").floor("min")
        realtime_row = pd.DataFrame([[curr] * len(df_i.columns)], columns=df_i.columns, index=[now_ts])
        df_plot = pd.concat([df_i, realtime_row]).sort_index()
        df_plot = df_plot[~df_plot.index.duplicated(keep="last")]

        today = df_plot.index[-1].date()
        t_start = pd.Timestamp(f"{today} 09:00", tz="Asia/Taipei")
        t_end = pd.Timestamp(f"{today} 13:30", tz="Asia/Taipei")
        df_plot = df_plot[(df_plot.index >= t_start) & (df_plot.index <= t_end)]

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)

        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["Close"], name="即時價格", mode="lines", line=dict(color="yellow", width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=[prev_c] * len(df_plot), name="昨收線", mode="lines", line=dict(color="#888", width=1, dash="dash")), row=1, col=1)

        if "Volume" in df_plot.columns:
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot["Volume"], name="分鐘量", marker_color="rgba(255,255,255,0.3)"), row=2, col=1)

        fig.update_xaxes(range=[t_start, t_end], tickformat="%H:%M")
        fig.update_yaxes(side="right", gridcolor="#222")
        fig.update_layout(template="plotly_dark", height=640, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("無盤中資料，可能尚未開盤、已收盤，或延遲。")

# =====================
# 📰 AI新聞預測頁 
# =====================
elif page == "📰 AI新聞預測":
    st.markdown(f"## 📰 {stock_name} ({symbol}) 最新新聞與 AI 預測")

    search_q = quote(f"{symbol} {stock_name}")
    rss_url = f"https://news.google.com/rss/search?q={search_q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    try:
        feed = feedparser.parse(rss_url)
        articles = feed.entries[:10]

        st.markdown("### 🗞️ 最新新聞")
        # 🔥 細節修復 3：新聞數量判斷提示
        if len(articles) == 0:
            st.info("📡 查無近期相關新聞。")
        else:
            if len(articles) < 10:
                st.caption(f"ℹ️ 僅找到 {len(articles)} 篇相關新聞。")
            
            for i, art in enumerate(articles, start=1):
                title = art.title
                link = art.link
                pub = art.published if hasattr(art, "published") else ""

                st.markdown(f"""
                <div style="background:#111; padding:15px; border-radius:10px; border:1px solid #333; margin-bottom:10px;">
                    <div style="color:#888; font-size:13px; margin-bottom:5px;">#{i} {pub}</div>
                    <a href="{link}" target="_blank" style="color:#fff; text-decoration:none; font-size:18px; font-weight:bold;">{title}</a>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("## 🤖 AI 綜合預測")

        if len(df) >= 20:
            ma5 = df["Close"].rolling(5).mean().iloc[-1]
            ma20 = df["Close"].rolling(20).mean().iloc[-1]
            recent_high = df["High"].rolling(20).max().iloc[-1]
            recent_low = df["Low"].rolling(20).min().iloc[-1]
            vol_ma5 = df["Volume"].rolling(5).mean().iloc[-1]
            latest_vol = df["Volume"].iloc[-1]

            trend = "震盪"
            if curr > ma20: trend = "偏多"
            if curr > recent_high: trend = "強勢突破"
            if curr < ma20: trend = "偏空"

            volume_status = "正常"
            if latest_vol > vol_ma5 * 1.5: volume_status = "爆量"
            elif latest_vol < vol_ma5 * 0.7: volume_status = "量縮"

            score = 0
            if curr > ma5: score += 2
            if curr > ma20: score += 2
            if latest_vol > vol_ma5: score += 2
            if curr > recent_high: score += 3

            ai_text = "觀望"
            if score >= 7: ai_text = "🚀 強勢偏多"
            elif score >= 4: ai_text = "📈 偏多"
            elif score <= 2: ai_text = "📉 偏空"

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"""
                <div style="background:#111; padding:20px; border-radius:10px; border:1px solid #333; text-align:center;">
                    <h3 style="margin-top:0;">📊 趨勢分析</h3>
                    <div style="font-size:32px; color:#ffcc00; font-weight:bold;">{trend}</div>
                </div>""", unsafe_allow_html=True)
            with c2:
                st.markdown(f"""
                <div style="background:#111; padding:20px; border-radius:10px; border:1px solid #333; text-align:center;">
                    <h3 style="margin-top:0;">📦 量能分析</h3>
                    <div style="font-size:32px; color:#00e5ff; font-weight:bold;">{volume_status}</div>
                </div>""", unsafe_allow_html=True)
            with c3:
                ai_color = "#ff3b3b" if score >= 4 else "#00e676"
                st.markdown(f"""
                <div style="background:#111; padding:20px; border-radius:10px; border:1px solid #333; text-align:center;">
                    <h3 style="margin-top:0;">🤖 AI 預測</h3>
                    <div style="font-size:32px; color:{ai_color}; font-weight:bold;">{ai_text}</div>
                    <div style="color:#aaa; margin-top:10px;">AI分數：{score}/10</div>
                </div>""", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown(f"""
            ### 🧠 AI 詳細技術參數
            - **目前股價**：{curr:.2f}
            - **5{time_unit}均線**：{ma5:.2f}
            - **20{time_unit}均線**：{ma20:.2f}
            - **20{time_unit}高點**：{recent_high:.2f}
            - **20{time_unit}低點**：{recent_low:.2f}
            """)
            
            # 🔥 細節修復 5：加入免責聲明
            st.caption("⚠️ **免責聲明**：AI 綜合預測與技術指標評分僅供學習與參考，不構成任何投資建議。市場瞬息萬變，投資人應自行謹慎評估風險。")
        else:
            st.warning("⚠️ 歷史資料不足 20 根 K 棒，無法計算 AI 預測模型。")

    except Exception as e:
        st.error(f"新聞或預測模組載入失敗：{e}")

# =====================
# 底部資訊 (通用：盈虧 + 五檔)
# =====================
st.markdown("---")
colA, colB = st.columns([4, 6])

with colA:
    pnl_color = "#ff3b3b" if profit > 0 else "#00e676" if profit < 0 else "#fff"
    curr_color = price_color(curr, prev_c)

    st.markdown(f"""
    <div style="background:#111; padding:20px; border-radius:10px; border:1px solid #333; height:100%;">
        <h3 style="margin-top:0;">💰 庫存狀態</h3>
        <p style="font-size:18px; color:#aaa; margin-bottom:5px;">股票：{stock_name} ({symbol})</p>
        <p style="font-size:18px; color:#aaa; margin-bottom:5px;">成本：{cost:.2f}｜張數：{qty:.0f}</p>
        <p style="font-size:20px; margin-bottom:20px;">現價：<strong style="color:{curr_color};">{curr:.2f} ({diff:+.2f} / {pct:+.2f}%)</strong></p>
        <h3 style="margin-bottom:0;">📊 總盈虧估算</h3>
        <div style="font-size:42px; font-weight:bold; color:{pnl_color};">{int(profit):,} 元</div>
    </div>
    """, unsafe_allow_html=True)

with colB:
    st.markdown("<h3 style='margin-top:0;'>⚖️ 即時五檔委託明細</h3>", unsafe_allow_html=True)

    if bids or asks:
        all_vols = [x.get("size", 0) for x in bids + asks]
        max_v = max(all_vols) if all_vols else 1

        cb, ca = st.columns(2)

        with cb:
            st.markdown("<div style='text-align:center;color:#aaa;margin-bottom:8px;'>買進</div>", unsafe_allow_html=True)
            for b in bids[:5]:
                sz, prc = b.get("size", 0), b.get("price", 0)
                w = (sz / max_v) * 100 if max_v else 0
                c_color = price_color(prc, prev_c)
                st.markdown(f"""
                <div style="display:flex; justify-content:flex-end; align-items:center; margin-bottom:8px;">
                    <span style="color:#888; font-size:14px; margin-right:10px;">{sz}</span>
                    <div style="width:120px; background:#222; height:14px; position:relative;">
                        <div style="position:absolute; right:0; width:{w}%; background:#ff3399; height:14px;"></div>
                    </div>
                    <span style="color:{c_color}; font-weight:bold; margin-left:10px; width:65px; text-align:right; font-size:16px;">{prc:.2f}</span>
                </div>
                """, unsafe_allow_html=True)

        with ca:
            st.markdown("<div style='text-align:center;color:#aaa;margin-bottom:8px;'>賣出</div>", unsafe_allow_html=True)
            for a in asks[:5][::-1]:
                sz, prc = a.get("size", 0), a.get("price", 0)
                w = (sz / max_v) * 100 if max_v else 0
                c_color = price_color(prc, prev_c)
                st.markdown(f"""
                <div style="display:flex; align-items:center; margin-bottom:8px;">
                    <span style="color:{c_color}; font-weight:bold; margin-right:10px; width:65px; text-align:left; font-size:16px;">{prc:.2f}</span>
                    <div style="width:120px; background:#222; height:14px; position:relative;">
                        <div style="position:absolute; left:0; width:{w}%; background:#00e5ff; height:14px;"></div>
                    </div>
                    <span style="color:#888; font-size:14px; margin-left:10px;">{sz}</span>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("📡 等待五檔連線，或目前非盤中時間。")
