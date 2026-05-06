import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import os
from datetime import datetime, timezone, timedelta
import feedparser
from urllib.parse import quote
from streamlit_autorefresh import st_autorefresh

# =====================
# 頁面設定
# =====================
st.set_page_config(layout="wide", page_title="台股戰情室 Pro")

st.markdown("""
<style>
html,body,[class*='st-']{background-color:#000;color:#eee;}
.block-container{padding:1rem!important; max-width:98%!important;}
.stTextInput input,.stNumberInput input{
    background-color:#222!important; color:#fff!important; border:1px solid #555!important;
}
.order-table{width:100%;border-collapse:collapse;font-family:Consolas,"Courier New",monospace;font-size:18px;}
.order-table th{color:#aaa;font-size:15px;border-bottom:1px solid #333;padding:8px 4px;text-align:center;}
.order-table td{padding:7px 4px;vertical-align:middle;}
.order-price{font-weight:bold;font-size:20px;}
.bar-bg{width:100%;height:16px;background:#1a1a1a;border-radius:3px;position:relative;}
.buy-bar{height:16px;background:#ff3b3b;border-radius:3px;float:right;}
.sell-bar{height:16px;background:#00e676;border-radius:3px;float:left;}
.card{background:#111;padding:16px;border-radius:10px;border:1px solid #333;}

/* 客製化暗黑滾動條 */
::-webkit-scrollbar {width: 6px;}
::-webkit-scrollbar-track {background: transparent;}
::-webkit-scrollbar-thumb {background: #444; border-radius: 3px;}
::-webkit-scrollbar-thumb:hover {background: #666;}
</style>
""", unsafe_allow_html=True)

# =====================
# 股票字典 (上市 + 上櫃 + ETF)
# =====================
@st.cache_data(ttl=86400)
def load_market_dict():
    market_dict = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 官方 OpenAPI 快速抓取
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=headers, timeout=5)
        if r.status_code == 200:
            for i in r.json():
                market_dict[i["Code"]] = i["Name"]
                market_dict[i["Name"]] = i["Code"]
    except: pass

    try:
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=headers, timeout=5)
        if r2.status_code == 200:
            for i in r2.json():
                code = i.get("SecuritiesCompanyCode") or i.get("Code")
                name = i.get("CompanyName") or i.get("Name")
                if code and name:
                    market_dict[code] = name
                    market_dict[name] = code
    except: pass

    # ISIN 暴力解析備援 (上市)
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        tables = pd.read_html(url)
        df = tables[0]
        for i in range(len(df)):
            try:
                raw = str(df.iloc[i,0]).strip()
                parts = raw.replace("　", " ").split(maxsplit=1)
                if len(parts) == 2:
                    code, name = parts[0].strip(), parts[1].strip()
                    if code.isalnum(): 
                        market_dict[code] = name
                        market_dict[name] = code
            except: pass
    except: pass

    # ISIN 暴力解析備援 (上櫃)
    try:
        url_otc = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
        tables_otc = pd.read_html(url_otc)
        df_otc = tables_otc[0]
        for i in range(len(df_otc)):
            try:
                raw = str(df_otc.iloc[i,0]).strip()
                parts = raw.replace("　", " ").split(maxsplit=1)
                if len(parts) == 2:
                    code, name = parts[0].strip(), parts[1].strip()
                    if code.isalnum():
                        market_dict[code] = name
                        market_dict[name] = code
            except: pass
    except: pass

    # ETF 補充清單
    etf_extra = {
        "0050":"元大台灣50", "0056":"元大高股息", "006208":"富邦台50",
        "00878":"國泰永續高股息", "00919":"群益台灣精選高息",
        "00929":"復華台灣科技優息", "00940":"元大台灣價值高息",
        "00713":"元大高息低波", "00757":"統一FANG+", "00679B":"元大美債20年",
        "1711":"永光", "2330":"台積電", "2313":"華通",
        "2603":"長榮", "2454":"聯發科", "2317":"鴻海"
    }
    for k, v in etf_extra.items():
        market_dict[k] = v
        market_dict[v] = k

    return market_dict

MASTER_DICT = load_market_dict()

# =====================
# 頂部控制列
# =====================
c1, c2, c3, c4 = st.columns([3, 2, 1.5, 2.5])

with c1:
    page = st.radio("📌 頁面切換", ["📊 K線分析", "⚡ 即時趨勢", "📰 AI新聞預測"], horizontal=True)

with c2:
    stock_input = st.text_input("🔍 股票代號 / 中文名稱", value="1711").strip()
    symbol = stock_input
    stock_name = stock_input

    # ===== 精準優先 / 模糊搜尋 =====
    if stock_input in MASTER_DICT:
        if stock_input.isdigit() or stock_input.endswith("B"):
            symbol = stock_input
            stock_name = MASTER_DICT.get(symbol, symbol)
        else:
            symbol = MASTER_DICT.get(stock_input, stock_input)
            stock_name = stock_input
    else:
        exact_match = None
        fuzzy_match = None
        
        for k, v in MASTER_DICT.items():
            if isinstance(v, str):
                if stock_input == v:
                    exact_match = (k, v)
                    break 
                elif stock_input in v and not fuzzy_match:
                    fuzzy_match = (k, v) 
        
        if exact_match:
            symbol, stock_name = exact_match
        elif fuzzy_match:
            symbol, stock_name = fuzzy_match
        else:
            symbol, stock_name = stock_input, stock_input

    display_name = f"{symbol} {stock_name}"

with c3:
    tf_label = st.selectbox("📈 K線週期", ["日K", "週K", "月K"])
    tf_map = {"日K":"1d", "週K":"1wk", "月K":"1mo"}
    period_map = {"日K":"6mo", "週K":"2y", "月K":"5y"}
    tf = tf_map[tf_label]
    period = period_map[tf_label]
    time_unit_map = {"日K":"日線", "週K":"週線", "月K":"月線"}
    time_unit = time_unit_map[tf_label]

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
        # Streamlit Cloud 檔案寫入可能無法跨重啟保留，但防呆機制已完善
        try:
            with open(TOKEN_FILE, "w") as f:
                f.write(api_key)
        except: pass

p1, p2 = st.columns(2)

with p1:
    qty = st.number_input("📦 持股張數", value=1.0, min_value=0.0, step=1.0)

with p2:
    cost = st.number_input("💰 平均成本", value=50.0, min_value=0.0, step=0.1)

st_autorefresh(interval=15000, key="auto_refresh")

# =====================
# 資料擷取引擎
# =====================
def flatten_columns(df):
    if not df.empty and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=30)
def fetch_history(symbol, period, interval):
    symbol = str(symbol).strip()
    df = yf.download(f"{symbol}.TW", period=period, interval=interval, progress=False, threads=False, auto_adjust=False)
    suffix = ".TW"

    if df.empty:
        df = yf.download(f"{symbol}.TWO", period=period, interval=interval, progress=False, threads=False, auto_adjust=False)
        suffix = ".TWO"

    df = flatten_columns(df)

    if not df.empty:
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df = df.tail(80)

    return df, suffix

@st.cache_data(ttl=10)
def fetch_intraday(symbol, suffix):
    # 🔥 盤後防呆：改為抓取 5d 再過濾最新一天，確保換日或休市時圖表仍有資料
    df_i = yf.download(f"{symbol}{suffix}", period="5d", interval="1m", progress=False, threads=False, auto_adjust=False)
    df_i = flatten_columns(df_i)

    if not df_i.empty:
        df_i = df_i.dropna(subset=["Close"])
        if df_i.index.tz is None:
            df_i.index = df_i.index.tz_localize("Asia/Taipei")
        else:
            df_i.index = df_i.index.tz_convert("Asia/Taipei")
        
        # 濾出最後一個交易日
        latest_day = df_i.index.date.max()
        df_i = df_i[df_i.index.date == latest_day]

    return df_i

def fetch_fugle_quote(symbol, api_key):
    q = {}
    if not api_key:
        return q
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}"
        headers = {"X-API-KEY": api_key}
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200:
            q = r.json()
    except:
        pass
    return q

def fetch_fugle_trades(symbol, api_key):
    if not api_key:
        return []
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/trades/{symbol}"
        headers = {"X-API-KEY": api_key}
        r = requests.get(url, headers=headers, timeout=3)

        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list): return data
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], list): return data["data"]
                if "trades" in data and isinstance(data["trades"], list): return data["trades"]
    except:
        pass
    return []

def price_color(price, prev_c):
    if price == 0 or prev_c == 0: return "#fff"
    if price > prev_c: return "#ff3b3b"
    elif price < prev_c: return "#00e676"
    return "#fff"

def format_trade_time(raw_time):
    try:
        raw_str = str(raw_time).strip()
        if raw_str.isdigit():
            ts = float(raw_str)
            if len(raw_str) > 10:
                ts = ts / (10 ** (len(raw_str) - 10))
            dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
            return dt.strftime("%H:%M:%S")
        else:
            return raw_str.split("T")[-1].split(".")[0] if "T" in raw_str else raw_str.split(".")[0]
    except:
        return str(raw_time)[:8]

# =====================
# 圖表渲染元件
# =====================
def donut_chart(title, value, label, color):
    value = max(0, min(100, int(value)))
    fig = go.Figure(data=[
        go.Pie(
            values=[value, 100 - value], hole=0.72, textinfo="none", sort=False,
            marker=dict(colors=[color, "#222"]), showlegend=False
        )
    ])
    fig.update_layout(
        template="plotly_dark", height=260, margin=dict(l=5, r=5, t=40, b=5),
        title=dict(text=title, x=0.5, font=dict(size=20)),
        annotations=[dict(text=f"<b>{value}%</b><br>{label}", x=0.5, y=0.5, showarrow=False, font=dict(size=24, color="#fff"))],
        paper_bgcolor="#111", plot_bgcolor="#111"
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

        rows += f"<tr><td style='width:55px; text-align:right; color:#aaa;'>{b_size_text}</td><td style='width:170px;'><div class='bar-bg'><div class='buy-bar' style='width:{b_width}%;'></div></div></td><td class='order-price' style='width:85px; text-align:right; color:{b_color};'>{b_price_text}</td><td style='width:55px; text-align:center; color:#555;'>│</td><td class='order-price' style='width:85px; text-align:left; color:{a_color};'>{a_price_text}</td><td style='width:170px;'><div class='bar-bg'><div class='sell-bar' style='width:{a_width}%;'></div></div></td><td style='width:55px; text-align:left; color:#aaa;'>{a_size_text}</td></tr>"

    html = f"<div style='background:#050505; padding:12px; border-radius:10px; border:1px solid #222;'><div style='text-align:center; color:#ffcc00; font-size:20px; font-weight:bold; margin-bottom:8px;'>現價 {curr:.2f}</div><table class='order-table'><thead><tr><th>買量</th><th></th><th>買價</th><th></th><th>賣價</th><th></th><th>賣量</th></tr></thead><tbody>{rows}</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)

def render_trade_details(trades, prev_c):
    st.markdown("### 📜 成交明細")
    if not trades:
        st.info("📡 尚無成交明細資料。")
        return

    rows = []
    for t in trades[:60]:
        price = t.get("price", t.get("tradePrice", 0))
        size = t.get("size", t.get("tradeVolume", t.get("volume", 0)))
        raw_time = t.get("time", t.get("at", t.get("date", "")))
        try: price_f = float(price)
        except: price_f = 0
        c = price_color(price_f, prev_c)
        time_text = format_trade_time(raw_time)

        rows.append(f"<tr><td style='color:#aaa; border-bottom:1px solid #222; padding:6px;'>{time_text}</td><td style='color:{c}; font-weight:bold; text-align:right; border-bottom:1px solid #222; padding:6px;'>{price_f:.2f}</td><td style='color:#ddd; text-align:right; border-bottom:1px solid #222; padding:6px;'>{size}</td></tr>")

    html = f"<div class='card'><div style='max-height:320px; overflow-y:auto; padding-right:5px;'><table style='width:100%; border-collapse:collapse; font-family:Consolas,\"Courier New\",monospace; font-size:16px;'><thead style='position:sticky; top:0; background:#111; z-index:2;'><tr style='color:#aaa; border-bottom:1px solid #444;'><th style='text-align:left; padding:8px 6px;'>時間</th><th style='text-align:right; padding:8px 6px;'>成交價</th><th style='text-align:right; padding:8px 6px;'>成交量</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>"
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
        except: continue

        if price > 0 and size > 0:
            price_volume[price] = price_volume.get(price, 0) + size

    trade_total = sum(price_volume.values())

    if trade_total == 0 and df_i is not None and not df_i.empty and "Volume" in df_i.columns:
        try: trade_total = int(df_i["Volume"].sum())
        except: trade_total = 0

    bid_pct = (bid_total / total_order * 100) if total_order else 0
    ask_pct = (ask_total / total_order * 100) if total_order else 0

    html = f"<div class='card'><div style='display:flex; gap:14px;'><div style='flex:1; text-align:center;'><div style='color:#aaa;'>委託買量</div><div style='font-size:28px; color:#ff3b3b; font-weight:bold;'>{bid_total:,}</div><div style='color:#888; font-size:12px;'>{bid_pct:.1f}%</div></div><div style='flex:1; text-align:center;'><div style='color:#aaa;'>委託賣量</div><div style='font-size:28px; color:#00e676; font-weight:bold;'>{ask_total:,}</div><div style='color:#888; font-size:12px;'>{ask_pct:.1f}%</div></div><div style='flex:1; text-align:center;'><div style='color:#aaa;'>總成交量</div><div style='font-size:28px; color:#ffcc00; font-weight:bold;'>{int(trade_total):,}</div><div style='color:#888; font-size:12px;'>今日累計</div></div></div><div style='margin-top:16px;'><div style='height:14px; background:#1a1a1a; border-radius:4px; display:flex; overflow:hidden;'><div style='width:{bid_pct}%; background:#ff3b3b;'></div><div style='width:{ask_pct}%; background:#00e676;'></div></div><div style='display:flex; justify-content:space-between; color:#aaa; margin-top:6px; font-size:12px;'><span>委買佔比</span><span>委賣佔比</span></div></div></div>"
    st.markdown(html, unsafe_allow_html=True)

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
        rows += f"<tr><td style='color:{c}; font-weight:bold; text-align:right; padding:6px;'>{price:.2f}</td><td style='width:70%; padding:6px;'><div style='height:16px; background:#1a1a1a; border-radius:3px;'><div style='height:16px; width:{width}%; background:#ffcc00; border-radius:3px;'></div></div></td><td style='text-align:right; color:#ddd; padding:6px;'>{vol}</td></tr>"

    html_price_volume = f"<div class='card' style='margin-top:12px;'><div style='max-height:320px; overflow-y:auto; padding-right:5px;'><table style='width:100%; border-collapse:collapse; font-family:Consolas,\"Courier New\",monospace;'><thead style='position:sticky; top:0; background:#111; z-index:2; color:#aaa; border-bottom:1px solid #333;'><tr><th style='text-align:right; padding-bottom:8px;'>價格</th><th style='text-align:center; padding-bottom:8px;'>量條</th><th style='text-align:right; padding-bottom:8px;'>成交量</th></tr></thead><tbody>{rows}</tbody></table></div></div>"
    st.markdown(html_price_volume, unsafe_allow_html=True)

# =====================
# 載入主資料
# =====================
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

# 🔥 防禦 None 回傳地雷
bids = q.get("bids") or []
asks = q.get("asks") or []
trades = fetch_fugle_trades(symbol, api_key) or []

profit = (curr - cost) * qty * 1000
diff = curr - prev_c
pct = (diff / prev_c * 100) if prev_c else 0

df_i_for_summary = fetch_intraday(symbol, suffix)

# =====================
# 📊 K線分析
# =====================
if page == "📊 K線分析":
    st.markdown(f"## 📊 {display_name}")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.02)

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="K線", increasing_line_color="#ff3b3b", decreasing_line_color="#00e676",
        increasing_fillcolor="#ff3b3b", decreasing_fillcolor="#00e676"
    ), row=1, col=1)

    if cost > 0:
        fig.add_trace(go.Scatter(x=df.index, y=[cost] * len(df), mode="lines", name="成本線", line=dict(color="cyan", width=2, dash="dash")), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=[curr] * len(df), mode="lines", name="現價線", line=dict(color="yellow", width=2, dash="dot")), row=1, col=1)

    vol_colors = ["rgba(255,59,59,0.5)" if c >= o else "rgba(0,230,118,0.5)" for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="成交量", marker_color=vol_colors), row=2, col=1)

    if tf == "1d":
        dt_obs = df.index.strftime("%Y-%m-%d").tolist()
        dt_all = pd.date_range(start=df.index[0], end=df.index[-1]).strftime("%Y-%m-%d").tolist()
        dt_breaks = [d for d in dt_all if d not in dt_obs]
        fig.update_xaxes(rangebreaks=[dict(values=dt_breaks)])

    fig.update_layout(template="plotly_dark", height=700, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h"), hovermode="x unified")
    fig.update_yaxes(side="right", gridcolor="#222")

    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    detail_col, volume_col = st.columns([5, 4])
    with detail_col:
        render_trade_details(trades, prev_c)
    with volume_col:
        render_volume_summary(bids, asks, trades, df_i_for_summary, prev_c)

# =====================
# ⚡ 即時趨勢
# =====================
elif page == "⚡ 即時趨勢":
    st.markdown(f"## ⚡ {display_name}")
    df_i = fetch_intraday(symbol, suffix)

    if not df_i.empty:
        now_ts = pd.Timestamp.now(tz="Asia/Taipei").floor("min")
        realtime_row = pd.DataFrame([[curr] * len(df_i.columns)], columns=df_i.columns, index=[now_ts])
        df_plot = pd.concat([df_i, realtime_row]).sort_index()
        df_plot = df_plot[~df_plot.index.duplicated(keep="last")]

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["Close"], mode="lines", name="即時價格", line=dict(color="yellow", width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=[prev_c] * len(df_plot), mode="lines", name="昨收線", line=dict(color="#777", dash="dash")), row=1, col=1)

        if "Volume" in df_plot.columns:
            fig.add_trace(go.Bar(x=df_plot.index, y=df_plot["Volume"], name="分鐘量", marker_color="rgba(255,255,255,0.3)"), row=2, col=1)

        today = df_plot.index[-1].date()
        t_start = pd.Timestamp(f"{today} 09:00", tz="Asia/Taipei")
        t_end = pd.Timestamp(f"{today} 13:30", tz="Asia/Taipei")
        fig.update_xaxes(range=[t_start, t_end], tickformat="%H:%M")
        fig.update_layout(template="plotly_dark", height=700, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h"), hovermode="x unified")

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("⚠️ 無盤中資料，可能尚未開盤、已收盤，或 YFinance 分鐘資料延遲。")

# =====================
# 📰 AI新聞預測
# =====================
elif page == "📰 AI新聞預測":
    st.markdown(f"## 📰 {display_name} 最新新聞與 AI 預測")

    search_q = quote(f"{symbol} {stock_name}")
    rss_url = f"https://news.google.com/rss/search?q={search_q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
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
                st.markdown(f"<div style='background:#111; padding:15px; border-radius:10px; border:1px solid #333; margin-bottom:10px;'><div style='color:#888; font-size:13px; margin-bottom:5px;'>#{i} {pub}</div><a href='{link}' target='_blank' style='color:#fff; text-decoration:none; font-size:18px; font-weight:bold;'>{title}</a></div>", unsafe_allow_html=True)

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
            if latest_vol > vol_ma5 * 1.5: volume_score, volume_status = 85, "爆量"
            elif latest_vol > vol_ma5: volume_score, volume_status = 70, "量增"
            elif latest_vol < vol_ma5 * 0.7: volume_score, volume_status = 35, "量縮"
            else: volume_score, volume_status = 55, "正常"

            ai_score = int(trend_score * 0.6 + volume_score * 0.4)

            if trend_score >= 80: trend_text = "強勢突破"
            elif trend_score >= 60: trend_text = "偏多"
            elif trend_score <= 40: trend_text = "偏空"
            else: trend_text = "震盪"

            if ai_score >= 75: ai_text, ai_color = "🚀 強勢偏多", "#ff3b3b"
            elif ai_score >= 60: ai_text, ai_color = "📈 偏多", "#ffa500"
            elif ai_score <= 40: ai_text, ai_color = "📉 偏空", "#00e676"
            else: ai_text, ai_color = "⏳ 觀望", "#888"

            g1, g2, g3 = st.columns(3)
            with g1: st.plotly_chart(donut_chart("📊 趨勢分析表", trend_score, trend_text, "#ffcc00"), use_container_width=True)
            with g2: st.plotly_chart(donut_chart("📦 量能表", volume_score, volume_status, "#00e5ff"), use_container_width=True)
            with g3: st.plotly_chart(donut_chart("🤖 人工智慧預測", ai_score, ai_text, ai_color), use_container_width=True)

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
            st.caption("⚠️ AI 分析與技術指標評分僅供參考，不構成任何投資建議。市場瞬息萬變，投資人應自行謹慎評估風險。")

        else:
            st.warning("⚠️ 歷史資料不足 20 根 K 棒，無法計算 AI 預測模型。")

    except Exception as e:
        st.error(f"新聞載入失敗：{e}")

# =====================
# 底部資訊 (全頁共用)
# =====================
st.markdown("---")
b1, b2 = st.columns([4, 6])

with b1:
    curr_color = price_color(curr, prev_c)
    pnl_color = "#ff3b3b" if profit > 0 else "#00e676" if profit < 0 else "#fff"

    st.markdown(f"<div style='background:#111; padding:20px; border-radius:10px; border:1px solid #333; height:100%;'><h3>💰 庫存狀態</h3><p style='color:#aaa;'>{display_name}</p><p style='color:#aaa;'>成本：{cost:.2f} ｜ 張數：{qty:.0f}</p><p style='font-size:24px; color:{curr_color}; font-weight:bold;'>現價：{curr:.2f} <span style='font-size:18px;'>({diff:+.2f} / {pct:+.2f}%)</span></p><h3>📊 總盈虧</h3><div style='font-size:42px; font-weight:bold; color:{pnl_color};'>{int(profit):,} 元</div></div>", unsafe_allow_html=True)

with b2:
    st.markdown("### ⚖️ 即時五檔明細")
    render_order_book(bids, asks, prev_c, curr)
