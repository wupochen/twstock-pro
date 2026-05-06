import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests, os, feedparser
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide", page_title="台股戰情室 Pro")

st.markdown("""
<style>
html,body,[class*='st-']{background-color:#000;color:#eee;}
.block-container{padding:1rem!important; max-width:98%!important;}
.stTextInput input,.stNumberInput input{background-color:#222!important;color:#fff!important;border:1px solid #555!important;}
.order-table{width:100%;border-collapse:collapse;font-family:Consolas,"Courier New",monospace;font-size:18px;}
.order-table th{color:#aaa;font-size:15px;border-bottom:1px solid #333;padding:8px 4px;text-align:center;}
.order-table td{padding:7px 4px;vertical-align:middle;}
.order-price{font-weight:bold;font-size:20px;}
.bar-bg{width:100%;height:16px;background:#1a1a1a;border-radius:3px;position:relative;}
.buy-bar{height:16px;background:#ff3b3b;border-radius:3px;float:right;}
.sell-bar{height:16px;background:#00e676;border-radius:3px;float:left;}
.card{background:#111;padding:16px;border-radius:10px;border:1px solid #333;}
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=86400)
def load_market_dict():
    d = {"1711":"永光","永光":"1711","2330":"台積電","台積電":"2330","2313":"華通","華通":"2313"}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=5)
        if r.status_code == 200:
            for i in r.json():
                d[i["Code"]] = i["Name"]
                d[i["Name"]] = i["Code"]
    except:
        pass
    try:
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=5)
        if r2.status_code == 200:
            for i in r2.json():
                code = i.get("SecuritiesCompanyCode") or i.get("Code")
                name = i.get("CompanyName") or i.get("Name")
                if code and name:
                    d[code] = name
                    d[name] = code
    except:
        pass
    return d

MASTER_DICT = load_market_dict()

c1, c2, c3, c4 = st.columns([3, 2, 1.5, 2.5])

with c1:
    page = st.radio("📌 頁面切換", ["📊 K線分析", "⚡ 即時趨勢", "📰 AI新聞預測"], horizontal=True)

with c2:
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
    tf_map = {"日K":"1d", "週K":"1wk", "月K":"1mo"}
    period_map = {"日K":"6mo", "週K":"2y", "月K":"5y"}
    tf = tf_map[tf_label]
    period = period_map[tf_label]
    time_unit = {"日K":"日線", "週K":"週線", "月K":"月線"}[tf_label]

with c4:
    TOKEN_FILE = "fugle_token.txt"

    def get_token():
        try:
            if "FUGLE_API" in st.secrets:
                return st.secrets["FUGLE_API"]
        except:
            pass
        if os.path.exists(TOKEN_FILE):
            return open(TOKEN_FILE, "r").read().strip()
        return ""

    api_key = st.text_input("🔑 Fugle Token", value=get_token(), type="password")

    try:
        has_secret = "FUGLE_API" in st.secrets
    except:
        has_secret = False

    if api_key and api_key != get_token() and not has_secret:
        with open(TOKEN_FILE, "w") as f:
            f.write(api_key)

p1, p2 = st.columns(2)
with p1:
    qty = st.number_input("📦 持股張數", value=1.0, min_value=0.0, step=1.0)
with p2:
    cost = st.number_input("💰 平均成本", value=50.0, min_value=0.0, step=0.1)

st_autorefresh(interval=15000, key="auto_refresh")

def flatten_columns(df):
    if not df.empty and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=30)
def fetch_history(symbol, period, interval):
    symbol = str(symbol).strip()
    try:
        df = yf.download(f"{symbol}.TW", period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
        suffix = ".TW"
    except:
        df = pd.DataFrame()
        suffix = ".TW"

    if df.empty:
        try:
            df = yf.download(f"{symbol}.TWO", period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
            suffix = ".TWO"
        except:
            df = pd.DataFrame()
            suffix = ".TW"

    df = flatten_columns(df)

    if not df.empty:
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df = df.tail(80)

    return df, suffix

@st.cache_data(ttl=10)
def fetch_intraday(symbol, suffix):
    try:
        df_i = yf.download(
            f"{symbol}{suffix}",
            period="5d",
            interval="1m",
            auto_adjust=False,
            progress=False,
            threads=False
        )
    except:
        df_i = pd.DataFrame()

    df_i = flatten_columns(df_i)

    if not df_i.empty:
        df_i = df_i.dropna(subset=["Close"])

        if df_i.index.tz is None:
            df_i.index = df_i.index.tz_localize("Asia/Taipei")
        else:
            df_i.index = df_i.index.tz_convert("Asia/Taipei")

        latest_day = df_i.index.date.max()
        df_i = df_i[df_i.index.date == latest_day]

    return df_i

def fetch_fugle_quote(symbol, api_key):
    if not api_key:
        return {}
    try:
        r = requests.get(
            f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}",
            headers={"X-API-KEY": api_key},
            timeout=3
        )
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return {}

def fetch_fugle_trades(symbol, api_key):
    if not api_key:
        return []
    try:
        r = requests.get(
            f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/trades/{symbol}",
            headers={"X-API-KEY": api_key},
            timeout=3
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if isinstance(data.get("data"), list):
                    return data["data"]
                if isinstance(data.get("trades"), list):
                    return data["trades"]
    except:
        pass
    return []

def price_color(price, prev_c):
    if price == 0 or prev_c == 0:
        return "#fff"
    if price > prev_c:
        return "#ff3b3b"
    if price < prev_c:
        return "#00e676"
    return "#fff"

def volume_colors(df_plot):
    colors = []
    prev_close = None
    for _, row in df_plot.iterrows():
        close = row.get("Close", None)
        open_p = row.get("Open", None)

        if pd.notna(open_p):
            is_up = close >= open_p
        elif prev_close is not None:
            is_up = close >= prev_close
        else:
            is_up = True

        colors.append("rgba(255,59,59,0.65)" if is_up else "rgba(0,230,118,0.65)")
        prev_close = close
    return colors

def format_trade_time(raw_time):
    try:
        raw_str = str(raw_time).strip()
        if raw_str.isdigit():
            ts = float(raw_str)
            if len(raw_str) > 10:
                ts = ts / (10 ** (len(raw_str) - 10))
            dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
            return dt.strftime("%H:%M:%S")
        return raw_str.split("T")[-1].split(".")[0] if "T" in raw_str else raw_str.split(".")[0]
    except:
        return str(raw_time)[:8]

def donut_chart(title, value, label, color):
    value = max(0, min(100, int(value)))
    fig = go.Figure(data=[go.Pie(values=[value, 100-value], hole=0.72, textinfo="none", sort=False, marker=dict(colors=[color, "#222"]), showlegend=False)])
    fig.update_layout(
        template="plotly_dark",
        height=260,
        margin=dict(l=5, r=5, t=40, b=5),
        title=dict(text=title, x=0.5, font=dict(size=20)),
        annotations=[dict(text=f"<b>{value}%</b><br>{label}", x=0.5, y=0.5, showarrow=False, font=dict(size=24, color="#fff"))],
        paper_bgcolor="#111",
        plot_bgcolor="#111"
    )
    return fig

def render_order_book(bids, asks, prev_c, curr):
    if not bids and not asks:
        st.info("📡 五檔尚未連線或非盤中時間")
        return

    all_vols = [x.get("size", 0) for x in bids + asks]
    max_v = max(all_vols) if all_vols else 1
    buy5, sell5 = bids[:5], asks[:5]
    rows = ""

    for i in range(5):
        b_price = buy5[i].get("price", 0) if i < len(buy5) else 0
        b_size = buy5[i].get("size", 0) if i < len(buy5) else 0
        a_price = sell5[i].get("price", 0) if i < len(sell5) else 0
        a_size = sell5[i].get("size", 0) if i < len(sell5) else 0

        b_width = int((b_size / max_v) * 100) if max_v else 0
        a_width = int((a_size / max_v) * 100) if max_v else 0

        b_color = price_color(b_price, prev_c) if b_price > 0 else "#777"
        a_color = price_color(a_price, prev_c) if a_price > 0 else "#777"

        b_price_text = f"{b_price:.2f}" if b_price > 0 else "--"
        a_price_text = f"{a_price:.2f}" if a_price > 0 else "--"
        b_size_text = f"{b_size}" if b_size > 0 else ""
        a_size_text = f"{a_size}" if a_size > 0 else ""

        rows += f"<tr><td style='width:55px;text-align:right;color:#aaa;'>{b_size_text}</td><td style='width:170px;'><div class='bar-bg'><div class='buy-bar' style='width:{b_width}%;'></div></div></td><td class='order-price' style='width:85px;text-align:right;color:{b_color};'>{b_price_text}</td><td style='width:55px;text-align:center;color:#555;'>│</td><td class='order-price' style='width:85px;text-align:left;color:{a_color};'>{a_price_text}</td><td style='width:170px;'><div class='bar-bg'><div class='sell-bar' style='width:{a_width}%;'></div></div></td><td style='width:55px;text-align:left;color:#aaa;'>{a_size_text}</td></tr>"

    html = f"<div style='background:#050505;padding:12px;border-radius:10px;border:1px solid #222;'><div style='text-align:center;color:#ffcc00;font-size:20px;font-weight:bold;margin-bottom:8px;'>現價 {curr:.2f}</div><table class='order-table'><thead><tr><th>買量</th><th></th><th>買價</th><th></th><th>賣價</th><th></th><th>賣量</th></tr></thead><tbody>{rows}</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)

def render_trade_details(trades, prev_c):
    st.markdown("### 📜 成交明細")
    if not trades:
        st.info("📡 尚無成交明細資料。")
        return

    rows = []
    for t in trades[:12]:
        price = t.get("price", t.get("tradePrice", 0))
        size = t.get("size", t.get("tradeVolume", t.get("volume", 0)))
        raw_time = t.get("time", t.get("at", t.get("date", "")))

        try:
            price_f = float(price)
        except:
            price_f = 0

        c = price_color(price_f, prev_c)
        time_text = format_trade_time(raw_time)

        rows.append(f"<tr><td style='color:#aaa;border-bottom:1px solid #222;padding:6px;'>{time_text}</td><td style='color:{c};font-weight:bold;text-align:right;border-bottom:1px solid #222;padding:6px;'>{price_f:.2f}</td><td style='color:#ddd;text-align:right;border-bottom:1px solid #222;padding:6px;'>{size}</td></tr>")

    html = f"<div class='card'><table style='width:100%;border-collapse:collapse;font-family:Consolas,\"Courier New\",monospace;font-size:16px;'><thead><tr style='color:#aaa;border-bottom:1px solid #444;'><th style='text-align:left;padding:8px 6px;'>時間</th><th style='text-align:right;padding:8px 6px;'>成交價</th><th style='text-align:right;padding:8px 6px;'>成交量</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)

def render_volume_summary(bids, asks, trades, df_i, prev_c):
    st.markdown("### 📊 委託 / 成交量統計")

    bid_total = sum([x.get("size", 0) for x in bids])
    ask_total = sum([x.get("size", 0) for x in asks])
    total_order = bid_total + ask_total
    price_volume = {}

    for t in trades:
        price = t.get("price", t.get("tradePrice", 0))
        size = t.get("size", t.get("tradeVolume", t.get("volume", 0)))
        try:
            price = float(price)
            size = int(size)
        except:
            continue
        if price > 0 and size > 0:
            price_volume[price] = price_volume.get(price, 0) + size

    trade_total = sum(price_volume.values())

    if trade_total == 0 and df_i is not None and not df_i.empty and "Volume" in df_i.columns:
        try:
            trade_total = int(df_i["Volume"].sum())
        except:
            trade_total = 0

    bid_pct = (bid_total / total_order * 100) if total_order else 0
    ask_pct = (ask_total / total_order * 100) if total_order else 0

    html = f"<div class='card'><div style='display:flex;gap:14px;'><div style='flex:1;text-align:center;'><div style='color:#aaa;'>委託買量</div><div style='font-size:28px;color:#ff3b3b;font-weight:bold;'>{bid_total:,}</div><div style='color:#888;font-size:12px;'>{bid_pct:.1f}%</div></div><div style='flex:1;text-align:center;'><div style='color:#aaa;'>委託賣量</div><div style='font-size:28px;color:#00e676;font-weight:bold;'>{ask_total:,}</div><div style='color:#888;font-size:12px;'>{ask_pct:.1f}%</div></div><div style='flex:1;text-align:center;'><div style='color:#aaa;'>總成交量</div><div style='font-size:28px;color:#ffcc00;font-weight:bold;'>{int(trade_total):,}</div><div style='color:#888;font-size:12px;'>今日累計</div></div></div><div style='margin-top:16px;'><div style='height:14px;background:#1a1a1a;border-radius:4px;display:flex;overflow:hidden;'><div style='width:{bid_pct}%;background:#ff3b3b;'></div><div style='width:{ask_pct}%;background:#00e676;'></div></div><div style='display:flex;justify-content:space-between;color:#aaa;margin-top:6px;font-size:12px;'><span>委買佔比</span><span>委賣佔比</span></div></div></div>"
    st.markdown(html, unsafe_allow_html=True)

    st.markdown("### 📘 委託五檔量")

    buy_rows, sell_rows = "", ""
    for i in range(5):
        b_price = bids[i].get("price", 0) if i < len(bids) else 0
        b_size = bids[i].get("size", 0) if i < len(bids) else 0
        a_price = asks[i].get("price", 0) if i < len(asks) else 0
        a_size = asks[i].get("size", 0) if i < len(asks) else 0

        b_price_text = f"{b_price:.2f}" if b_price > 0 else "--"
        a_price_text = f"{a_price:.2f}" if a_price > 0 else "--"

        buy_rows += f"<tr><td style='color:#aaa;'>買{i+1}</td><td style='color:{price_color(b_price, prev_c)};font-weight:bold;text-align:right;'>{b_price_text}</td><td style='text-align:right;color:#ddd;'>{b_size}</td></tr>"
        sell_rows += f"<tr><td style='color:#aaa;'>賣{i+1}</td><td style='color:{price_color(a_price, prev_c)};font-weight:bold;text-align:right;'>{a_price_text}</td><td style='text-align:right;color:#ddd;'>{a_size}</td></tr>"

    html_order = f"<div class='card' style='margin-top:12px;'><div style='display:flex;gap:18px;'><div style='flex:1;'><h4 style='margin-top:0;color:#ff3b3b;'>買1 ~ 買5</h4><table style='width:100%;border-collapse:collapse;font-family:Consolas,\"Courier New\",monospace;'><thead style='color:#aaa;'><tr><th style='text-align:left;'>檔位</th><th style='text-align:right;'>價格</th><th style='text-align:right;'>量</th></tr></thead><tbody>{buy_rows}</tbody></table></div><div style='flex:1;'><h4 style='margin-top:0;color:#00e676;'>賣1 ~ 賣5</h4><table style='width:100%;border-collapse:collapse;font-family:Consolas,\"Courier New\",monospace;'><thead style='color:#aaa;'><tr><th style='text-align:left;'>檔位</th><th style='text-align:right;'>價格</th><th style='text-align:right;'>量</th></tr></thead><tbody>{sell_rows}</tbody></table></div></div></div>"
    st.markdown(html_order, unsafe_allow_html=True)

    st.markdown("### 📈 今日成交價量分布（低 → 高）")

    if not price_volume:
        st.info("📡 尚無逐價成交量資料。")
        return

    max_trade_vol = max(price_volume.values()) if price_volume else 1
    rows = ""

    for price in sorted(price_volume.keys()):
        vol = price_volume[price]
        width = int((vol / max_trade_vol) * 100)
        c = price_color(price, prev_c)
        rows += f"<tr><td style='color:{c};font-weight:bold;text-align:right;padding:6px;'>{price:.2f}</td><td style='width:70%;padding:6px;'><div style='height:16px;background:#1a1a1a;border-radius:3px;'><div style='height:16px;width:{width}%;background:#ffcc00;border-radius:3px;'></div></div></td><td style='text-align:right;color:#ddd;padding:6px;'>{vol}</td></tr>"

    html_price_volume = f"<div class='card' style='margin-top:12px;'><table style='width:100%;border-collapse:collapse;font-family:Consolas,\"Courier New\",monospace;'><thead style='color:#aaa;border-bottom:1px solid #333;'><tr><th style='text-align:right;'>價格</th><th style='text-align:center;'>量條</th><th style='text-align:right;'>成交量</th></tr></thead><tbody>{rows}</tbody></table></div>"
    st.markdown(html_price_volume, unsafe_allow_html=True)

df, suffix = fetch_history(symbol, period, tf)

if df.empty:
    st.error(f"查無歷史資料，請確認股票代號 ({symbol}) 是否正確。")
    st.stop()

curr_yf = float(df["Close"].iloc[-1])
prev_c = float(df["Close"].iloc[-2]) if len(df) > 1 else curr_yf
open_p = float(df["Open"].iloc[-1])

q = fetch_fugle_quote(symbol, api_key)
trade_price = q.get("lastPrice") or q.get("trade", {}).get("price") or q.get("lastTrade", {}).get("price")

if trade_price not in [None, 0] and not pd.isna(trade_price):
    curr = float(trade_price)
else:
    curr = curr_yf

bids = q.get("bids", [])
asks = q.get("asks", [])
trades = fetch_fugle_trades(symbol, api_key)

profit = (curr - cost) * qty * 1000
diff = curr - prev_c
pct = (diff / prev_c * 100) if prev_c else 0

df_i_for_summary = None
if page == "📊 K線分析":
    df_i_for_summary = fetch_intraday(symbol, suffix)

if page == "📊 K線分析":
    st.markdown(f"## 📊 {stock_name} ({symbol})")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.02)

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="K線", increasing_line_color="#ff3b3b", decreasing_line_color="#00e676",
        increasing_fillcolor="#ff3b3b", decreasing_fillcolor="#00e676"
    ), row=1, col=1)

    if cost > 0:
        fig.add_trace(go.Scatter(
            x=df.index, y=[cost]*len(df), mode="lines", name="成本線",
            line=dict(color="cyan", width=2, dash="dash")
        ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df.index, y=[curr]*len(df), mode="lines", name="現價線",
        line=dict(color="yellow", width=2, dash="dot")
    ), row=1, col=1)

    vol_colors = ["rgba(255,59,59,0.5)" if c >= o else "rgba(0,230,118,0.5)" for o, c in zip(df["Open"], df["Close"])]

    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"], name="成交量", marker_color=vol_colors
    ), row=2, col=1)

    if tf == "1d":
        dt_obs = df.index.strftime("%Y-%m-%d").tolist()
        dt_all = pd.date_range(start=df.index[0], end=df.index[-1]).strftime("%Y-%m-%d").tolist()
        dt_breaks = [d for d in dt_all if d not in dt_obs]
        fig.update_xaxes(rangebreaks=[dict(values=dt_breaks)])

    fig.update_layout(
        template="plotly_dark", height=700, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=20, b=10),
        legend=dict(orientation="h"),
        hovermode="x unified"
    )
    fig.update_yaxes(side="right", gridcolor="#222")

    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    detail_col, volume_col = st.columns([5, 4])

    with detail_col:
        render_trade_details(trades, prev_c)

    with volume_col:
        render_volume_summary(bids, asks, trades, df_i_for_summary, prev_c)

elif page == "⚡ 即時趨勢":
    st.markdown(f"## ⚡ {stock_name} ({symbol}) 即時趨勢 / 盤後保留")

    df_i = fetch_intraday(symbol, suffix)

    if not df_i.empty:
        latest_date = df_i.index.date.max()

        now_ts = pd.Timestamp.now(tz="Asia/Taipei").floor("min")

        if now_ts.date() == latest_date:
            realtime_row = pd.DataFrame(
                [[curr] * len(df_i.columns)],
                columns=df_i.columns,
                index=[now_ts]
            )
            df_plot = pd.concat([df_i, realtime_row]).sort_index()
            df_plot = df_plot[~df_plot.index.duplicated(keep="last")]
        else:
            df_plot = df_i.copy()

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)

        fig.add_trace(go.Scatter(
            x=df_plot.index,
            y=df_plot["Close"],
            mode="lines",
            name="即時價格",
            line=dict(color="yellow", width=2)
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df_plot.index,
            y=[prev_c] * len(df_plot),
            mode="lines",
            name="昨收線",
            line=dict(color="#777", dash="dash")
        ), row=1, col=1)

        if "Volume" in df_plot.columns:
            fig.add_trace(go.Bar(
                x=df_plot.index,
                y=df_plot["Volume"],
                name="分鐘量（紅漲綠跌）",
                marker_color=volume_colors(df_plot)
            ), row=2, col=1)

        t_start = pd.Timestamp(f"{latest_date} 09:00", tz="Asia/Taipei")
        t_end = pd.Timestamp(f"{latest_date} 13:30", tz="Asia/Taipei")

        fig.update_xaxes(range=[t_start, t_end], tickformat="%H:%M")

        fig.update_layout(
            template="plotly_dark",
            height=700,
            margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h"),
            hovermode="x unified"
        )

        fig.update_yaxes(side="right", gridcolor="#222")

        st.plotly_chart(fig, use_container_width=True)

        st.caption("📌 盤中顯示即時資料；盤後保留最後一個交易日 09:00～13:30 走勢。分鐘量：紅色代表該分鐘收高，綠色代表該分鐘收低。")

    else:
        st.warning("⚠️ 無盤中資料，可能資料源延遲或該股票無分鐘資料。")

elif page == "📰 AI新聞預測":
    st.markdown(f"## 📰 {stock_name} ({symbol}) 最新新聞與 AI 預測")

    search_q = quote(f"{symbol} {stock_name}")
    rss_url = f"https://news.google.com/rss/search?q={search_q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        rss_res = requests.get(rss_url, headers=headers, timeout=5)
        feed = feedparser.parse(rss_res.content)
        articles = feed.entries[:10]

        st.markdown("### 🗞️ 最新新聞")

        if len(articles) == 0:
            st.info("📡 查無近期相關新聞")
        else:
            for i, art in enumerate(articles, start=1):
                title = art.title
                link = art.link
                pub = art.published if hasattr(art, "published") else ""

                st.markdown(
                    f"<div style='background:#111;padding:15px;border-radius:10px;border:1px solid #333;margin-bottom:10px;'>"
                    f"<div style='color:#888;font-size:13px;margin-bottom:5px;'>#{i} {pub}</div>"
                    f"<a href='{link}' target='_blank' style='color:#fff;text-decoration:none;font-size:18px;font-weight:bold;'>{title}</a>"
                    f"</div>",
                    unsafe_allow_html=True
                )

        st.markdown("---")
        st.markdown("## 🤖 AI 三環分析")

        if len(df) >= 20:
            ma5 = df["Close"].rolling(5).mean().iloc[-1]
            ma20 = df["Close"].rolling(20).mean().iloc[-1]
            recent_high = df["High"].rolling(20).max().iloc[-1]
            recent_low = df["Low"].rolling(20).min().iloc[-1]
            vol_ma5 = df["Volume"].rolling(5).mean().iloc[-1]
            latest_vol = df["Volume"].iloc[-1]

            trend_score = 50
            if curr > ma5: trend_score += 15
            if curr > ma20: trend_score += 20
            if curr > recent_high: trend_score += 25
            if curr < ma20: trend_score -= 25
            trend_score = max(0, min(100, trend_score))

            volume_score = 50
            if latest_vol > vol_ma5 * 1.5:
                volume_score, volume_status = 85, "爆量"
            elif latest_vol > vol_ma5:
                volume_score, volume_status = 70, "量增"
            elif latest_vol < vol_ma5 * 0.7:
                volume_score, volume_status = 35, "量縮"
            else:
                volume_score, volume_status = 55, "正常"

            ai_score = int(trend_score * 0.6 + volume_score * 0.4)

            if trend_score >= 80:
                trend_text = "強勢突破"
            elif trend_score >= 60:
                trend_text = "偏多"
            elif trend_score <= 40:
                trend_text = "偏空"
            else:
                trend_text = "震盪"

            if ai_score >= 75:
                ai_text, ai_color = "🚀 強勢偏多", "#ff3b3b"
            elif ai_score >= 60:
                ai_text, ai_color = "📈 偏多", "#ffa500"
            elif ai_score <= 40:
                ai_text, ai_color = "📉 偏空", "#00e676"
            else:
                ai_text, ai_color = "⏳ 觀望", "#888"

            g1, g2, g3 = st.columns(3)

            with g1:
                st.plotly_chart(donut_chart("📊 趨勢分析表", trend_score, trend_text, "#ffcc00"), use_container_width=True)
            with g2:
                st.plotly_chart(donut_chart("📦 量能表", volume_score, volume_status, "#00e5ff"), use_container_width=True)
            with g3:
                st.plotly_chart(donut_chart("🤖 人工智慧預測", ai_score, ai_text, ai_color), use_container_width=True)

            st.markdown("---")
            st.markdown(f"""
            ### 🧠 AI 詳細技術參數
            - **目前股價**：{curr:.2f}
            - **5期均線（{time_unit}）**：{ma5:.2f}
            - **20期均線（{time_unit}）**：{ma20:.2f}
            - **20期高點（{time_unit}）**：{recent_high:.2f}
            - **20期低點（{time_unit}）**：{recent_low:.2f}
            - **最新成交量**：{latest_vol:,.0f}
            - **5期均量（{time_unit}）**：{vol_ma5:,.0f}
            - **AI 綜合分數**：{ai_score}/100
            """)

            st.caption("⚠️ AI 分析與技術指標評分僅供參考，不構成任何投資建議。")

        else:
            st.warning("⚠️ 歷史資料不足 20 根 K 棒，無法計算 AI 預測模型。")

    except Exception as e:
        st.error(f"新聞載入失敗：{e}")

st.markdown("---")
b1, b2 = st.columns([4, 6])

with b1:
    curr_color = price_color(curr, prev_c)
    pnl_color = "#ff3b3b" if profit > 0 else "#00e676" if profit < 0 else "#fff"

    st.markdown(
        f"<div style='background:#111;padding:20px;border-radius:10px;border:1px solid #333;height:100%;'>"
        f"<h3>💰 庫存狀態</h3>"
        f"<p style='color:#aaa;'>{stock_name} ({symbol})</p>"
        f"<p style='color:#aaa;'>成本：{cost:.2f} ｜ 張數：{qty:.0f}</p>"
        f"<p style='font-size:24px;color:{curr_color};font-weight:bold;'>現價：{curr:.2f} <span style='font-size:18px;'>({diff:+.2f} / {pct:+.2f}%)</span></p>"
        f"<h3>📊 總盈虧</h3>"
        f"<div style='font-size:42px;font-weight:bold;color:{pnl_color};'>{int(profit):,} 元</div>"
        f"</div>",
        unsafe_allow_html=True
    )

with b2:
    st.markdown("### ⚖️ 即時五檔明細")
    render_order_book(bids, asks, prev_c, curr)
