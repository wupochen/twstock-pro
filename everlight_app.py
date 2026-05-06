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
.card{background:#111;padding:16px;border-radius:10px;border:1px solid #333; transition: 0.3s;}
.card:hover{box-shadow: 0px 4px 15px rgba(255, 255, 255, 0.1);}
.fin-table{width:100%; border-collapse:collapse; font-size:15px;}
.fin-table th{background:#222; color:#ffcc00; padding:10px; border-bottom:2px solid #444; text-align:left;}
.fin-table td{padding:10px; border-bottom:1px solid #333; color:#ddd; vertical-align:middle;}
.fin-table tr:hover td{background:#1a1a1a;}

/* 客製化暗黑滾動條 */
::-webkit-scrollbar {width: 6px; height: 6px;}
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

    etf_extra = {
        "0050":"元大台灣50", "0056":"元大高股息", "006208":"富邦台50",
        "00878":"國泰永續高股息", "00919":"群益台灣精選高息",
        "00929":"復華台灣科技優息", "00940":"元大台灣價值高息",
        "00713":"元大高息低波", "00757":"統一FANG+", "00679B":"元大美債20年",
        "1711":"永光", "2330":"台積電", "2313":"華通",
        "2603":"長榮", "2618":"長榮航", "2454":"聯發科", "2317":"鴻海"
    }
    for k, v in etf_extra.items():
        market_dict[k] = v
        market_dict[v] = k

    return market_dict

MASTER_DICT = load_market_dict()

INDUSTRY_BACKUP = {
    "2330": "半導體業", "2317": "其他電子業", "2454": "半導體業",
    "2603": "航運業", "2618": "航運業", "1711": "化學工業",
    "2313": "電子零組件業", "0050": "ETF", "0056": "ETF",
    "00878": "ETF", "00919": "ETF", "00679B": "債券ETF"
}

# =====================
# 頂部控制列
# =====================
c1, c2, c3, c4 = st.columns([3, 2, 1.5, 2.5])

with c1:
    page = st.radio("📌 頁面切換", ["📊 K線分析", "⚡ 即時趨勢", "📰 AI新聞預測", "📑 基本面分析"], horizontal=True)

with c2:
    stock_input = st.text_input("🔍 股票代號 / 中文名稱", value="1711").strip()
    symbol = stock_input
    stock_name = stock_input

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

    ma1, ma2, ma3 = st.columns(3)
    with ma1: show_ma5 = st.checkbox("5線", True)
    with ma2: show_ma10 = st.checkbox("10線", True)
    with ma3: show_ma20 = st.checkbox("20線", True)

with c4:
    TOKEN_FILE = "fugle_token.txt"

    def get_token():
        try:
            if "FUGLE_API" in st.secrets:
                return st.secrets["FUGLE_API"]
        except: pass
        if os.path.exists(TOKEN_FILE):
            return open(TOKEN_FILE, "r").read().strip()
        return ""

    api_key = st.text_input("🔑 Fugle Token", value=get_token(), type="password")

    try: has_secret = "FUGLE_API" in st.secrets
    except: has_secret = False

    if api_key and api_key != get_token() and not has_secret:
        try:
            with open(TOKEN_FILE, "w") as f: f.write(api_key)
        except: pass

p1, p2 = st.columns(2)
with p1: qty = st.number_input("📦 持股張數", value=1.0, min_value=0.0, step=1.0)
with p2: cost = st.number_input("💰 平均成本", value=50.0, min_value=0.0, step=0.1)

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
    df_i = yf.download(f"{symbol}{suffix}", period="5d", interval="1m", progress=False, threads=False, auto_adjust=False)
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

@st.cache_data(ttl=3600)
def fetch_fundamentals(symbol, suffix):
    try:
        t = yf.Ticker(f"{symbol}{suffix}")
        info = t.info
    except: info = {}
    
    try:
        fin = t.financials
        if fin is not None and not fin.empty: fin = fin.T.sort_index()
        else: fin = pd.DataFrame()
    except: fin = pd.DataFrame()
    
    return info, fin

# 🔥 新增每月營收資料擷取 (強力防呆)
@st.cache_data(ttl=3600)
def fetch_monthly_revenue(symbol):
    res_df = pd.DataFrame()
    try:
        url = f"https://tw.stock.yahoo.com/quote/{symbol}/revenue"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=5)
        dfs = pd.read_html(r.text)
        
        for df in dfs:
            # 尋找類似 Yahoo 營收表格的結構
            if len(df.columns) >= 5 and ('單月營收' in str(df.columns) or '月營收' in str(df.columns) or '年增率' in str(df.columns)):
                # 重新命名防呆
                cols = ["月份", "營收", "MoM", "去年同月", "YoY", "累計營收", "累計YoY"]
                df.columns = cols[:len(df.columns)]
                
                data = []
                for _, row in df.iterrows():
                    m = str(row.get("月份", "")).strip()
                    if "月" not in m: continue # 濾除表頭或其他雜訊
                    
                    rev_str = str(row.get("營收", "0")).replace(",", "")
                    mom_str = str(row.get("MoM", "0")).replace("%", "").replace(",", "")
                    yoy_str = str(row.get("YoY", "0")).replace("%", "").replace(",", "")
                    
                    try:
                        # Yahoo 上通常是千元，轉成億元 (1億 = 10萬千元)
                        rev_val = float(rev_str) / 100000 
                        mom_val = float(mom_str)
                        yoy_val = float(yoy_str)
                        data.append({
                            "月份": m, 
                            "營收（億元台幣）": round(rev_val, 2), 
                            "月增率 MoM": mom_val, 
                            "年增率 YoY": yoy_val
                        })
                    except: pass
                
                if data:
                    res_df = pd.DataFrame(data).head(12)
                    break
    except: pass
    return res_df

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

def fetch_fugle_trades(symbol, api_key):
    if not api_key: return []
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
    except: pass
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
            if len(raw_str) > 10: ts = ts / (10 ** (len(raw_str) - 10))
            dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
            return dt.strftime("%H:%M:%S")
        else: return raw_str.split("T")[-1].split(".")[0] if "T" in raw_str else raw_str.split(".")[0]
    except: return str(raw_time)[:8]

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
        paper_bgcolor="#000", plot_bgcolor="#000",
        title=dict(text=title, x=0.5, font=dict(size=20)),
        annotations=[dict(text=f"<b>{value}%</b><br>{label}", x=0.5, y=0.5, showarrow=False, font=dict(size=24, color="#fff"))]
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

        b_width, a_width = int((b_size / max_v) * 100) if max_v else 0, int((a_size / max_v) * 100) if max_v else 0
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
    html = f"<div class='card' style='padding:0;'><div style='max-height:320px; overflow-y:auto; padding:15px;'><table style='width:100%; border-collapse:collapse; font-family:Consolas,\"Courier New\",monospace; font-size:16px;'><thead style='position:sticky; top:-15px; background:#111; z-index:2;'><tr style='color:#aaa;'><th style='text-align:left; padding:8px 6px; background:#111; border-bottom:1px solid #444;'>時間</th><th style='text-align:right; padding:8px 6px; background:#111; border-bottom:1px solid #444;'>成交價</th><th style='text-align:right; padding:8px 6px; background:#111; border-bottom:1px solid #444;'>成交量</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>"
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

    html_price_volume = f"<div class='card' style='padding:0; margin-top:12px;'><div style='max-height:320px; overflow-y:auto; padding:15px;'><table style='width:100%; border-collapse:collapse; font-family:Consolas,\"Courier New\",monospace;'><thead style='position:sticky; top:-15px; background:#111; z-index:2; color:#aaa;'><tr style='border-bottom:1px solid #333;'><th style='text-align:right; padding-bottom:8px; background:#111;'>價格</th><th style='text-align:center; padding-bottom:8px; background:#111;'>量條</th><th style='text-align:right; padding-bottom:8px; background:#111;'>成交量</th></tr></thead><tbody>{rows}</tbody></table></div></div>"
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

if trade_price not in [None, 0] and not pd.isna(trade_price): curr = float(trade_price)
else: curr = curr_yf

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

    if cost > 0: fig.add_trace(go.Scatter(x=df.index, y=[cost] * len(df), mode="lines", name="成本線", line=dict(color="cyan", width=2, dash="dash")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=[curr] * len(df), mode="lines", name="現價線", line=dict(color="yellow", width=2, dash="dot")), row=1, col=1)

    if show_ma5: fig.add_trace(go.Scatter(x=df.index, y=df["Close"].rolling(5).mean(), mode="lines", line=dict(color="#FFD700", width=1.5), name="MA5"), row=1, col=1)
    if show_ma10: fig.add_trace(go.Scatter(x=df.index, y=df["Close"].rolling(10).mean(), mode="lines", line=dict(color="#00E5FF", width=1.5), name="MA10"), row=1, col=1)
    if show_ma20: fig.add_trace(go.Scatter(x=df.index, y=df["Close"].rolling(20).mean(), mode="lines", line=dict(color="#FF66FF", width=1.5), name="MA20"), row=1, col=1)

    vol_colors = ["rgba(255,59,59,0.5)" if c >= o else "rgba(0,230,118,0.5)" for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="成交量", marker_color=vol_colors), row=2, col=1)

    if tf == "1d":
        dt_obs = df.index.strftime("%Y-%m-%d").tolist()
        dt_all = pd.date_range(start=df.index[0], end=df.index[-1]).strftime("%Y-%m-%d").tolist()
        dt_breaks = [d for d in dt_all if d not in dt_obs]
        fig.update_xaxes(rangebreaks=[dict(values=dt_breaks)])

    fig.update_layout(
        template="plotly_dark", height=700, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h"), hovermode="x unified",
        paper_bgcolor="#000", plot_bgcolor="#000"
    )
    fig.update_xaxes(gridcolor="#111")
    fig.update_yaxes(side="right", gridcolor="#111")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    detail_col, volume_col = st.columns([5, 4])
    with detail_col: render_trade_details(trades, prev_c)
    with volume_col: render_volume_summary(bids, asks, trades, df_i_for_summary, prev_c)

# =====================
# ⚡ 即時趨勢
# =====================
elif page == "⚡ 即時趨勢":
    st.markdown(f"## ⚡ {display_name} 即時走勢")
    if not df_i_for_summary.empty:
        df_i = df_i_for_summary.copy()
        now_ts = pd.Timestamp.now(tz="Asia/Taipei").floor("min")
        if "High" not in df_i.columns: df_i["High"] = df_i["Close"]
        if "Low" not in df_i.columns: df_i["Low"] = df_i["Close"]
        
        realtime_row = pd.DataFrame([[df_i["Open"].iloc[-1] if not df_i.empty else curr, curr, curr, curr, 0]], 
                                    columns=["Open", "High", "Low", "Close", "Volume"], index=[now_ts])
        df_plot = pd.concat([df_i, realtime_row]).sort_index()
        df_plot = df_plot[~df_plot.index.duplicated(keep="last")]

        df_plot["VWAP"] = (df_plot["Close"] * df_plot["Volume"]).cumsum() / df_plot["Volume"].cumsum().replace(0, pd.NA)
        df_plot["VWAP"] = df_plot["VWAP"].bfill().fillna(df_plot["Close"])

        high_val = max(df_plot["High"].max(), curr)
        low_val = min(df_plot["Low"].min(), curr)
        amp_pct = ((high_val - low_val) / low_val) * 100 if low_val > 0 else 0

        buy_vol, sell_vol = 0, 0
        v_colors = []
        p_c = prev_c
        for idx, row in df_plot.iterrows():
            c, v = row["Close"], row["Volume"]
            if pd.isna(v): v = 0
            if c >= p_c:
                buy_vol += v
                v_colors.append("rgba(255,59,59,0.8)")
            else:
                sell_vol += v
                v_colors.append("rgba(0,230,118,0.8)")
            p_c = c
            
        total_force = buy_vol + sell_vol
        buy_pct = (buy_vol / total_force * 100) if total_force else 50
        sell_pct = (sell_vol / total_force * 100) if total_force else 50

        df_plot['Vol_MA10'] = df_plot['Volume'].rolling(10).mean().shift(1)
        surges = []
        for dt_idx, r in df_plot.iterrows():
            if r['Volume'] > 0 and not pd.isna(r['Vol_MA10']) and r['Vol_MA10'] > 0:
                if r['Volume'] > r['Vol_MA10'] * 2:
                    surges.append(f"⚠️ {dt_idx.strftime('%H:%M')} 爆量 {r['Volume']/r['Vol_MA10']:.1f} 倍")
        surges = surges[-5:] 

        m1, m2, m3, m4 = st.columns(4)
        c_color = price_color(curr, prev_c)
        m1.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>現價 / 漲跌</div><div style='color:{c_color}; font-size:22px; font-weight:bold;'>{curr:.2f} <span style='font-size:16px;'>({diff:+.2f} {pct:+.2f}%)</span></div></div>", unsafe_allow_html=True)
        m2.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>最高 / 最低</div><div style='color:#fff; font-size:22px; font-weight:bold;'><span style='color:#ff3b3b'>{high_val:.2f}</span> <span style='color:#666;'>/</span> <span style='color:#00e676'>{low_val:.2f}</span></div></div>", unsafe_allow_html=True)
        m3.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>今日振幅</div><div style='color:#ffcc00; font-size:22px; font-weight:bold;'>{amp_pct:.2f}%</div></div>", unsafe_allow_html=True)
        m4.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>即時均價 (VWAP)</div><div style='color:#fff; font-size:22px; font-weight:bold;'>{df_plot['VWAP'].iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)

        st.markdown(f"<div class='card' style='margin-top:10px; margin-bottom:15px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px; font-size:15px;'><span style='color:#ff3b3b; font-weight:bold;'>🔥 主動買盤 {buy_pct:.1f}%</span><span style='color:#00e676; font-weight:bold;'>❄️ 主動賣盤 {sell_pct:.1f}%</span></div><div style='height:12px; background:#1a1a1a; border-radius:6px; display:flex; overflow:hidden;'><div style='width:{buy_pct}%; background:#ff3b3b;'></div><div style='width:{sell_pct}%; background:#00e676;'></div></div></div>", unsafe_allow_html=True)

        if surges:
            surge_html = "".join([f"<span style='background:#332b00; border:1px solid #665500; color:#ffcc00; padding:4px 10px; border-radius:5px; margin-right:10px; font-size:14px; font-weight:bold;'>{s}</span>" for s in surges])
            st.markdown(f"<div style='margin-bottom:15px;'>{surge_html}</div>", unsafe_allow_html=True)

        custom_data = []
        for i, r in df_plot.iterrows():
            chg_p = ((r['Close'] - prev_c) / prev_c * 100) if prev_c else 0
            custom_data.append([r['Volume'], chg_p])

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["Close"], mode="lines", name="即時價格",
            line=dict(color="yellow", width=2.5), customdata=custom_data,
            hovertemplate="<b>時間:</b> %{x|%H:%M}<br><b>價格:</b> %{y:.2f}<br><b>漲跌:</b> %{customdata[1]:+.2f}%<br><b>成交量:</b> %{customdata[0]:,.0f}<extra></extra>"
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot["VWAP"], mode="lines", name="均價線",
            line=dict(color="white", width=1.5, dash="dot"), hoverinfo="skip"
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df_plot.index, y=[prev_c] * len(df_plot), mode="lines", name="昨收線",
            line=dict(color="#777", dash="dash"), hoverinfo="skip"
        ), row=1, col=1)

        fig.add_trace(go.Bar(
            x=df_plot.index, y=df_plot["Volume"], name="分鐘量", marker_color=v_colors,
            customdata=custom_data, hovertemplate="<b>時間:</b> %{x|%H:%M}<br><b>成交量:</b> %{y:,.0f}<extra></extra>"
        ), row=2, col=1)

        today = df_plot.index[-1].date()
        t_start = pd.Timestamp(f"{today} 09:00", tz="Asia/Taipei")
        t_end = pd.Timestamp(f"{today} 13:30", tz="Asia/Taipei")
        fig.update_xaxes(range=[t_start, t_end], tickformat="%H:%M")
        
        fig.update_layout(
            template="plotly_dark", height=650, margin=dict(l=10, r=10, t=20, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hovermode="x unified",
            paper_bgcolor="#000", plot_bgcolor="#000"
        )
        fig.update_xaxes(gridcolor="#111", showspikes=True, spikemode="across", spikesnap="cursor", showline=False, spikedash="solid")
        fig.update_yaxes(side="right", gridcolor="#111")
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
        if len(articles) == 0: st.info("📡 查無近期相關新聞")
        else:
            for i, art in enumerate(articles, start=1):
                title, link, pub = art.title, art.link, art.published if hasattr(art, "published") else ""
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
            st.markdown(f"### 🧠 AI 詳細技術參數\n- **目前股價**：{curr:.2f}\n- **5期均線（{time_unit}）**：{ma5:.2f}\n- **20期均線（{time_unit}）**：{ma20:.2f}\n- **20期高點（{time_unit}）**：{recent_high:.2f}\n- **20期低點（{time_unit}）**：{recent_low:.2f}\n- **最新成交量**：{latest_vol:,.0f}\n- **5期均量（{time_unit}）**：{vol_ma5:,.0f}\n- **AI 綜合分數**：{ai_score}/100")
            st.caption("⚠️ AI 分析與技術指標評分僅供參考，不構成任何投資建議。市場瞬息萬變，投資人應自行謹慎評估風險。")
        else: st.warning("⚠️ 歷史資料不足 20 根 K 棒，無法計算 AI 預測模型。")
    except Exception as e: st.error(f"新聞載入失敗：{e}")

# =====================
# 📑 基本面分析
# =====================
elif page == "📑 基本面分析":
    st.markdown(f"## 📑 {display_name} 基本面分析")
    
    info, fin_data = fetch_fundamentals(symbol, suffix)
    rev_df = fetch_monthly_revenue(symbol)
    
    def safe_get(key, default="N/A"):
        v = info.get(key)
        return v if v is not None else default

    def fmt_pct_ratio(val):
        if val == "N/A" or pd.isna(val): return "N/A"
        try:
            v = float(val)
            if abs(v) > 1: return f"{v:.2f}%"
            return f"{v * 100:.2f}%"
        except: return "N/A"

    def normalize_ratio(val):
        if val == "N/A" or pd.isna(val): return None
        try:
            v = float(val)
            if abs(v) > 1: return v / 100
            return v
        except: return None

    def fmt_flt(val, dec=2):
        if val == "N/A" or pd.isna(val): return "N/A"
        try: return f"{float(val):.{dec}f}"
        except: return "N/A"

    def fmt_curr(val):
        if val == "N/A" or pd.isna(val): return "N/A"
        try:
            v = float(val)
            if abs(v) >= 1e12: return f"{v/1e12:.2f} 兆"
            if abs(v) >= 1e8: return f"{v/1e8:.2f} 億"
            if abs(v) >= 1e4: return f"{v/1e4:.2f} 萬"
            return f"{v:,.0f}"
        except: return "N/A"

    def fmt_date(val):
        if val == "N/A" or pd.isna(val): return "N/A"
        try: return datetime.fromtimestamp(val).strftime('%Y-%m-%d')
        except: return "N/A"

    sector = INDUSTRY_BACKUP.get(symbol, safe_get("sector"))
    marketCap = safe_get("marketCap", 0)
    employees = safe_get("fullTimeEmployees")
    website = safe_get("website")
    country = safe_get("country")
    currency = safe_get("currency")
    
    eps = safe_get("trailingEps", 0)
    pe = safe_get("trailingPE", 0)
    pb = safe_get("priceToBook", 0)
    roe = safe_get("returnOnEquity", 0)
    div_yield = safe_get("dividendYield", 0)
    
    mc_str = fmt_curr(marketCap)
    eps_str = fmt_flt(eps)
    pe_str = fmt_flt(pe)
    pb_str = fmt_flt(pb)
    roe_str = fmt_pct_ratio(roe)
    div_str = fmt_pct_ratio(div_yield)

    roe_norm = normalize_ratio(roe)
    div_yield_norm = normalize_ratio(div_yield)

    st.markdown("### 🏢 公司基本資料")
    i1, i2, i3, i4 = st.columns(4)
    i1.markdown(f"<div class='card'><div style='color:#aaa;'>產業板塊</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{sector}</div></div>", unsafe_allow_html=True)
    i2.markdown(f"<div class='card'><div style='color:#aaa;'>公司市值</div><div style='font-size:20px; font-weight:bold; color:#ffcc00;'>{mc_str}</div></div>", unsafe_allow_html=True)
    i3.markdown(f"<div class='card'><div style='color:#aaa;'>員工總數</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{employees}</div></div>", unsafe_allow_html=True)
    i4.markdown(f"<div class='card'><div style='color:#aaa;'>國家 / 幣別</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{country} / {currency}</div></div>", unsafe_allow_html=True)

    st.markdown("### 📊 核心指標")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>EPS (近四季)</div><div style='font-size:22px; font-weight:bold; color:#ff3b3b;'>{eps_str}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>本益比 (PER)</div><div style='font-size:22px; font-weight:bold; color:#00e676;'>{pe_str}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>股價淨值比 (PBR)</div><div style='font-size:22px; font-weight:bold; color:#00e676;'>{pb_str}</div></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>股東權益報酬 (ROE)</div><div style='font-size:22px; font-weight:bold; color:#ffcc00;'>{roe_str}</div></div>", unsafe_allow_html=True)
    c5.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>殖利率</div><div style='font-size:22px; font-weight:bold; color:#ff3b3b;'>{div_str}</div></div>", unsafe_allow_html=True)
    c6.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>市值規模</div><div style='font-size:22px; font-weight:bold; color:#fff;'>{mc_str}</div></div>", unsafe_allow_html=True)

    score = 0
    if eps != "N/A" and eps > 0:
        if eps > 10: score += 20
        elif eps > 5: score += 10
        
    if roe_norm is not None and roe_norm > 0:
        if roe_norm > 0.15: score += 20
        elif roe_norm > 0.10: score += 10
        
    if div_yield_norm is not None and div_yield_norm > 0:
        if div_yield_norm > 0.05: score += 20
        elif div_yield_norm > 0.03: score += 10
        
    if pe != "N/A" and pe > 0:
        if pe < 15: score += 20
        elif pe < 25: score += 10
        
    if pb != "N/A" and pb > 0:
        if pb < 2: score += 20
        elif pb < 4: score += 10
    
    score = max(0, min(100, score))

    if score >= 90: score_tag, score_color = "🔥 極度優秀", "#ff3b3b"
    elif score >= 75: score_tag, score_color = "✅ 基本面強勁", "#ff9900"
    elif score >= 60: score_tag, score_color = "👍 穩健型公司", "#ffcc00"
    elif score >= 40: score_tag, score_color = "⚠️ 普通", "#aaaaaa"
    else: score_tag, score_color = "❄️ 基本面偏弱", "#00e676"

    ai_summary = ""
    if roe_norm is not None and roe_norm > 0.15: ai_summary += "公司具備優異的獲利能力(ROE高)，"
    elif roe_norm is not None and roe_norm > 0: ai_summary += "公司獲利能力尚可，"
    else: ai_summary += "目前獲利能力偏弱或虧損，"

    if div_yield_norm is not None and div_yield_norm > 0.05: ai_summary += "且具備高殖利率提供防禦性保護。"
    else: ai_summary += "且偏向不發放高股息的資本運用策略。"

    if pe != "N/A" and pe > 0:
        if pe > 25: ai_summary += "<br>惟目前本益比較高，市場給予較高估值或偏向成長型評價。"
        elif pe < 15: ai_summary += "<br>目前本益比偏低，具有潛在的價值投資機會。"
        else: ai_summary += "<br>估值處於合理區間。"
    else: ai_summary += "<br>目前無有效本益比供參考。"

    st.markdown("---")
    s1, s2 = st.columns([3, 7])
    with s1: st.plotly_chart(donut_chart("🤖 AI 基本面評分", score, score_tag, score_color), use_container_width=True)
    with s2:
        st.markdown("### 📋 AI 基本面分析總結")
        st.markdown(f"<div class='card' style='height:260px; display:flex; align-items:center; justify-content:center; padding:30px;'><h3 style='color:#fff; line-height:1.6; font-weight:normal; text-align:left;'>{ai_summary}</h3></div>", unsafe_allow_html=True)

    # ================= 每月營收 =================
    st.markdown("---")
    st.markdown("### 📅 每月營收")
    if rev_df.empty:
        st.info("📡 暫無每月營收資料")
    else:
        c_rev1, c_rev2 = st.columns([4, 6])
        with c_rev1:
            rev_table_html = "<div style='overflow-x:auto; max-height:400px; overflow-y:auto; border-radius:12px; border:1px solid #222;'><table class='fin-table' style='width:100%; border-collapse:collapse;'><thead style='position:sticky; top:0; z-index:999; background:#222;'><tr><th style='padding:10px; color:#fff;'>月份</th><th style='padding:10px; color:#fff; text-align:right;'>營收(億元)</th><th style='padding:10px; color:#fff; text-align:right;'>MoM</th><th style='padding:10px; color:#fff; text-align:right;'>YoY</th></tr></thead><tbody>"
            for _, row in rev_df.iterrows():
                m = row["月份"]
                r = row["營收（億元台幣）"]
                mom = row["月增率 MoM"]
                yoy = row["年增率 YoY"]
                c_mom = "#ff3b3b" if mom > 0 else "#00e676" if mom < 0 else "#fff"
                c_yoy = "#ff3b3b" if yoy > 0 else "#00e676" if yoy < 0 else "#fff"
                rev_table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>{m}</td><td style='padding:10px; border-bottom:1px solid #333; text-align:right;'>{r:.2f}</td><td style='padding:10px; border-bottom:1px solid #333; text-align:right; color:{c_mom};'>{mom:+.2f}%</td><td style='padding:10px; border-bottom:1px solid #333; text-align:right; color:{c_yoy};'>{yoy:+.2f}%</td></tr>"
            rev_table_html += "</tbody></table></div>"
            st.markdown(rev_table_html, unsafe_allow_html=True)
            
        with c_rev2:
            df_chart = rev_df.iloc[::-1].copy()
            fig_rev = make_subplots(specs=[[{"secondary_y": True}]])
            fig_rev.add_trace(go.Bar(
                x=df_chart['月份'], y=df_chart['營收（億元台幣）'],
                name="營收(億元)", marker_color="#00e5ff"
            ), secondary_y=False)
            fig_rev.add_trace(go.Scatter(
                x=df_chart['月份'], y=df_chart['年增率 YoY'],
                name="YoY(%)", mode="lines+markers", line=dict(color="#ff3b3b", width=2)
            ), secondary_y=True)
            
            fig_rev.update_layout(
                template="plotly_dark", height=400, margin=dict(l=10, r=10, t=20, b=10),
                paper_bgcolor="#000", plot_bgcolor="#000",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            fig_rev.update_xaxes(gridcolor="#111", type='category')
            fig_rev.update_yaxes(title_text="營收(億元台幣)", gridcolor="#111", secondary_y=False)
            fig_rev.update_yaxes(title_text="YoY %", showgrid=False, secondary_y=True)
            st.plotly_chart(fig_rev, use_container_width=True)

    # ================= 基本面詳細表格 =================
    st.markdown("---")
    st.markdown("### 📋 基本面詳細表格")
    
    debt_to_equity_str = f"{fmt_flt(safe_get('debtToEquity'))}%" if safe_get('debtToEquity') != "N/A" else "N/A"

    table_html = ""
    table_html += "<div style='overflow-x:auto; max-height:700px; overflow-y:auto; border-radius:12px; border:1px solid #222;'>"
    table_html += "<table class='fin-table' style='width:100%; border-collapse:collapse;'>"
    table_html += "<thead style='position:sticky; top:0; z-index:999; background:#222;'>"
    table_html += "<tr><th style='padding:10px; text-align:left; border-bottom:2px solid #444; color:#fff;'>分類</th><th style='padding:10px; text-align:left; border-bottom:2px solid #444; color:#fff;'>指標</th><th style='padding:10px; text-align:left; border-bottom:2px solid #444; color:#fff;'>數值</th><th style='padding:10px; text-align:left; border-bottom:2px solid #444; color:#fff;'>解讀</th></tr>"
    table_html += "</thead><tbody>"

    table_html += f"<tr><td rowspan='5' style='font-weight:bold; color:#ffcc00; border-right:1px solid #333; padding:10px; border-bottom:1px solid #333;'>💰 獲利能力</td><td style='padding:10px; border-bottom:1px solid #333;'>毛利率 (Gross Margin)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('grossMargins'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>產品附加價值與成本控制能力，越高越好。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>營益率 (Operating Margin)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('operatingMargins'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>本業獲利能力，反映營業費用控制。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>淨利率 (Profit Margin)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('profitMargins'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>稅後最終獲利能力。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>股東權益報酬 (ROE)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('returnOnEquity'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>為股東創造獲利的效率，>15%為佳。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>資產報酬率 (ROA)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('returnOnAssets'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>運用總資產創造獲利的效率。</td></tr>"

    table_html += f"<tr><td rowspan='4' style='font-weight:bold; color:#00e5ff; border-right:1px solid #333; padding:10px; border-bottom:1px solid #333;'>🛡️ 財務安全</td><td style='padding:10px; border-bottom:1px solid #333;'>負債比 (Debt to Equity)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{debt_to_equity_str}</td><td style='padding:10px; border-bottom:1px solid #333;'>負債佔股東權益的比例，衡量財務槓桿。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>流動比率 (Current Ratio)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_flt(safe_get('currentRatio'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>短期償債能力，建議 >1。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>自由現金流 (Free Cashflow)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_curr(safe_get('freeCashflow'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>企業營運後自由可支配的現金。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>現金部位 (Total Cash)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_curr(safe_get('totalCash'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>帳上現金總額，抵禦風險能力。</td></tr>"

    table_html += f"<tr><td rowspan='4' style='font-weight:bold; color:#ff3b3b; border-right:1px solid #333; padding:10px; border-bottom:1px solid #333;'>💸 股利政策</td><td style='padding:10px; border-bottom:1px solid #333;'>殖利率 (Dividend Yield)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('dividendYield'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>股息報酬率，越高代表配息越豐厚。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>現金股息 (Dividend Rate)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_flt(safe_get('dividendRate'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>預計每股發放的現金股利金額。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>配息率 (Payout Ratio)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('payoutRatio'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>企業獲利中發放股息的比例。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>除息日 (Ex-Dividend Date)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_date(safe_get('exDividendDate'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>最近一次除權息的日期。</td></tr>"

    table_html += f"<tr><td rowspan='5' style='font-weight:bold; color:#00e676; border-right:1px solid #333; padding:10px; border-bottom:1px solid #333;'>⚖️ 估值分析</td><td style='padding:10px; border-bottom:1px solid #333;'>本益比 (PER)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_flt(safe_get('trailingPE'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>投資回本年數，越低通常代表越便宜。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>預估本益比 (Forward PE)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_flt(safe_get('forwardPE'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>基於未來獲利預估的本益比。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>股價淨值比 (PBR)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_flt(safe_get('priceToBook'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>股價相對於每股淨值的倍數，<1可能低估。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>本益成長比 (PEG)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_flt(safe_get('pegRatio'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>結合PER與成長率，<1通常視為低估。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>Beta 值</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_flt(safe_get('beta'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>股價波動相對於大盤的敏感度，>1波動較大。</td></tr>"

    table_html += f"<tr><td rowspan='4' style='font-weight:bold; color:#ff9900; border-right:1px solid #333; padding:10px; border-bottom:1px solid #333;'>🚀 成長性</td><td style='padding:10px; border-bottom:1px solid #333;'>營收成長率 (YoY)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('revenueGrowth'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>年營收較去年同期的成長幅度。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>淨利成長率 (YoY)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('earningsGrowth'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>年淨利較去年同期的成長幅度。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>季營收成長 (QoQ)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('quarterlyRevenueGrowth'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>單季營收的短期成長動能。</td></tr>"
    table_html += f"<tr><td style='padding:10px; border-bottom:1px solid #333;'>季淨利成長 (QoQ)</td><td style='font-weight:bold; padding:10px; border-bottom:1px solid #333;'>{fmt_pct_ratio(safe_get('quarterlyEarningsGrowth'))}</td><td style='padding:10px; border-bottom:1px solid #333;'>單季淨利的短期成長動能。</td></tr>"
    
    table_html += "</tbody></table></div>"

    st.markdown(table_html, unsafe_allow_html=True)

    # ================= 財報趨勢圖 =================
    st.markdown("---")
    st.markdown("### 📈 歷年財報趨勢圖")
    
    if not fin_data.empty:
        fig_fin = make_subplots(specs=[[{"secondary_y": True}]])
        has_plot = False
        
        if 'Total Revenue' in fin_data.columns:
            y_rev = fin_data['Total Revenue'] / 1e8
            fig_fin.add_trace(go.Bar(x=fin_data.index, y=y_rev, name="營收 (億元)", marker_color="rgba(255, 204, 0, 0.7)"), secondary_y=False)
            has_plot = True
        elif 'Operating Revenue' in fin_data.columns:
            y_rev = fin_data['Operating Revenue'] / 1e8
            fig_fin.add_trace(go.Bar(x=fin_data.index, y=y_rev, name="營業收入 (億元)", marker_color="rgba(255, 204, 0, 0.7)"), secondary_y=False)
            has_plot = True

        if 'Net Income' in fin_data.columns:
            y_ni = fin_data['Net Income'] / 1e8
            fig_fin.add_trace(go.Scatter(x=fin_data.index, y=y_ni, name="淨利 (億元)", mode="lines+markers", line=dict(color="#ff3b3b", width=3)), secondary_y=False)
            has_plot = True
            
        if 'Basic EPS' in fin_data.columns:
            fig_fin.add_trace(go.Scatter(x=fin_data.index, y=fin_data['Basic EPS'], name="EPS", mode="lines+markers", line=dict(color="#ffffff", width=2, dash="dot")), secondary_y=True)
            has_plot = True

        if has_plot:
            fig_fin.update_layout(
                template="plotly_dark", height=500, margin=dict(l=10, r=10, t=20, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hovermode="x unified",
                paper_bgcolor="#000", plot_bgcolor="#000"
            )
            fig_fin.update_xaxes(gridcolor="#111", type='category') 
            fig_fin.update_yaxes(title_text="金額 (億元台幣)", gridcolor="#111", secondary_y=False)
            fig_fin.update_yaxes(title_text="EPS", showgrid=False, secondary_y=True)
            st.plotly_chart(fig_fin, use_container_width=True)
        else:
            st.info("📡 暫無營收或淨利趨勢資料。")
    else:
        st.info("📡 暫無財報趨勢資料。")

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
    if page != "📑 基本面分析":
        st.markdown("### ⚖️ 即時五檔明細")
        render_order_book(bids, asks, prev_c, curr)
