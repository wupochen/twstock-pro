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
::-webkit-scrollbar {width: 6px; height: 6px;}
::-webkit-scrollbar-track {background: transparent;}
::-webkit-scrollbar-thumb {background: #444; border-radius: 3px;}
::-webkit-scrollbar-thumb:hover {background: #666;}
</style>
""", unsafe_allow_html=True)

# =====================
# 股票字典 (三層備援)
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
    except Exception as e: print(f"上市 OpenAPI 載入失敗: {e}")

    try:
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=headers, timeout=5)
        if r2.status_code == 200:
            for i in r2.json():
                code = i.get("SecuritiesCompanyCode") or i.get("Code")
                name = i.get("CompanyName") or i.get("Name")
                if code and name:
                    market_dict[code] = name
                    market_dict[name] = code
    except Exception as e: print(f"上櫃 OpenAPI 載入失敗: {e}")

    if len(market_dict) < 1000:
        try:
            r_twse = requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", headers=headers, timeout=10)
            dfs = pd.read_html(r_twse.text)
            for _, row in dfs[0].iterrows():
                parts = str(row[0]).strip().replace("　", " ").split(maxsplit=1)
                if len(parts) == 2 and parts[0].isalnum(): 
                    market_dict[parts[0]] = parts[1].strip()
                    market_dict[parts[1].strip()] = parts[0]
        except Exception as e: print(f"上市 ISIN 載入失敗: {e}")

        try:
            r_tpex = requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", headers=headers, timeout=10)
            dfs_tpex = pd.read_html(r_tpex.text)
            for _, row in dfs_tpex[0].iterrows():
                parts = str(row[0]).strip().replace("　", " ").split(maxsplit=1)
                if len(parts) == 2 and parts[0].isalnum():
                    market_dict[parts[0]] = parts[1].strip()
                    market_dict[parts[1].strip()] = parts[0]
        except Exception as e: print(f"上櫃 ISIN 載入失敗: {e}")

    static_backup = {
        "0050":"元大台灣50", "0056":"元大高股息", "006208":"富邦台50",
        "00878":"國泰永續高股息", "00919":"群益台灣精選高息",
        "00929":"復華台灣科技優息", "00940":"元大台灣價值高息",
        "00713":"元大高息低波", "00757":"統一FANG+", "00679B":"元大美債20年",
        "1711":"永光", "2330":"台積電", "2313":"華通",
        "2603":"長榮", "2618":"長榮航", "2454":"聯發科", "2317":"鴻海"
    }
    for k, v in static_backup.items():
        if k not in market_dict:
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
    page = st.radio("📌 頁面切換", ["📊 K線分析", "⚡ 即時趨勢", "🤖 AI綜合預測", "📑 基本面分析"], horizontal=True)

with c2:
    stock_input = st.text_input("🔍 股票代號 / 中文名稱", value="1711")
    stock_input = stock_input.replace(".TW","").replace(".TWO","").replace(".tw","").replace(".two","").strip().upper()
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
        exact_match, fuzzy_match = None, None
        for k, v in MASTER_DICT.items():
            if isinstance(v, str):
                if stock_input == v:
                    exact_match = (k, v)
                    break 
                elif stock_input in v and not fuzzy_match:
                    fuzzy_match = (k, v) 
        if exact_match: symbol, stock_name = exact_match
        elif fuzzy_match: symbol, stock_name = fuzzy_match
        else: symbol, stock_name = stock_input, stock_input

    display_name = f"{symbol} {stock_name}"

with c3:
    tf_label = st.selectbox("📈 K線週期", ["日K", "週K", "月K"])
    tf_map = {"日K":"1d", "週K":"1wk", "月K":"1mo"}
    period_map = {"日K":"6mo", "週K":"2y", "月K":"5y"}
    tf, period = tf_map[tf_label], period_map[tf_label]
    time_unit = {"日K":"日線", "週K":"週線", "月K":"月線"}[tf_label]
    ma1, ma2, ma3 = st.columns(3)
    with ma1: show_ma5 = st.checkbox("5線", True)
    with ma2: show_ma10 = st.checkbox("10線", True)
    with ma3: show_ma20 = st.checkbox("20線", True)

with c4:
    TOKEN_FILE = "fugle_token.txt"
    def get_token():
        try:
            if "FUGLE_API" in st.secrets: return st.secrets["FUGLE_API"]
        except: pass
        if os.path.exists(TOKEN_FILE): return open(TOKEN_FILE, "r").read().strip()
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
        if df_i.index.tz is None: df_i.index = df_i.index.tz_localize("Asia/Taipei")
        else: df_i.index = df_i.index.tz_convert("Asia/Taipei")
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

@st.cache_data(ttl=3600)
def fetch_monthly_revenue(symbol):
    res_df = pd.DataFrame()
    try:
        url = f"https://tw.stock.yahoo.com/quote/{symbol}/revenue"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5)
        dfs = pd.read_html(r.text)
        for df in dfs:
            if len(df.columns) >= 5 and ('單月營收' in str(df.columns) or '月營收' in str(df.columns)):
                df.columns = ["月份", "營收", "MoM", "去年同月", "YoY", "累計營收", "累計YoY"][:len(df.columns)]
                data = []
                for _, row in df.iterrows():
                    m = str(row.get("月份", "")).strip()
                    if "月" not in m: continue 
                    try:
                        rev_val = float(str(row.get("營收", "0")).replace(",", "")) / 100000 
                        mom_val = float(str(row.get("MoM", "0")).replace("%", "").replace(",", ""))
                        yoy_val = float(str(row.get("YoY", "0")).replace("%", "").replace(",", ""))
                        data.append({"月份": m, "營收（億元台幣）": round(rev_val, 2), "月增率 MoM": mom_val, "年增率 YoY": yoy_val})
                    except: pass
                if data:
                    res_df = pd.DataFrame(data).head(12)
                    break
    except: pass
    return res_df

def fetch_fugle_quote(symbol, api_key):
    if not api_key: return {}
    try:
        r = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{symbol}", headers={"X-API-KEY": api_key}, timeout=3)
        if r.status_code == 200: return r.json()
    except: pass
    return {}

def fetch_fugle_trades(symbol, api_key):
    if not api_key: return []
    try:
        r = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/trades/{symbol}", headers={"X-API-KEY": api_key}, timeout=3)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list): return data
            if isinstance(data, dict): return data.get("data", data.get("trades", []))
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
            return datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8))).strftime("%H:%M:%S")
        return raw_str.split("T")[-1].split(".")[0] if "T" in raw_str else raw_str.split(".")[0]
    except: return str(raw_time)[:8]

# =====================
# UI 渲染元件
# =====================
def donut_chart(title, value, label, color):
    value = max(0, min(100, int(value)))
    fig = go.Figure(data=[go.Pie(values=[value, 100 - value], hole=0.72, textinfo="none", sort=False, marker=dict(colors=[color, "#222"]), showlegend=False)])
    fig.update_layout(
        template="plotly_dark", height=260, margin=dict(l=5, r=5, t=40, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        title=dict(text=title, x=0.5, font=dict(size=20, color="#fff")),
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
        b_p = buy5[i].get("price", 0) if i < len(buy5) else 0
        b_s = buy5[i].get("size", 0) if i < len(buy5) else 0
        a_p = sell5[i].get("price", 0) if i < len(sell5) else 0
        a_s = sell5[i].get("size", 0) if i < len(sell5) else 0
        bw, aw = int((b_s / max_v) * 100) if max_v else 0, int((a_s / max_v) * 100) if max_v else 0
        bc = price_color(b_p, prev_c) if b_p > 0 else "#777"
        ac = price_color(a_p, prev_c) if a_p > 0 else "#777"
        bp_t = f"{b_p:.2f}" if b_p > 0 else "--"
        ap_t = f"{a_p:.2f}" if a_p > 0 else "--"
        bs_t = f"{b_s}" if b_s > 0 else ""
        as_t = f"{a_s}" if a_s > 0 else ""
        rows += f"<tr><td style='width:55px; text-align:right; color:#aaa;'>{bs_t}</td><td style='width:170px;'><div class='bar-bg'><div class='buy-bar' style='width:{bw}%;'></div></div></td><td class='order-price' style='width:85px; text-align:right; color:{bc};'>{bp_t}</td><td style='width:55px; text-align:center; color:#555;'>│</td><td class='order-price' style='width:85px; text-align:left; color:{ac};'>{ap_t}</td><td style='width:170px;'><div class='bar-bg'><div class='sell-bar' style='width:{aw}%;'></div></div></td><td style='width:55px; text-align:left; color:#aaa;'>{as_t}</td></tr>"
    st.markdown(f"<div style='background:#050505; padding:12px; border-radius:10px; border:1px solid #222;'><div style='text-align:center; color:#ffcc00; font-size:20px; font-weight:bold; margin-bottom:8px;'>現價 {curr:.2f}</div><table class='order-table'><thead><tr><th>買量</th><th></th><th>買價</th><th></th><th>賣價</th><th></th><th>賣量</th></tr></thead><tbody>{rows}</tbody></table></div>", unsafe_allow_html=True)

def render_trade_details(trades, prev_c):
    st.markdown("### 📜 成交明細")
    if not trades:
        st.info("📡 尚無成交明細資料。")
        return
    rows = ""
    for t in trades[:60]:
        try: p = float(t.get("price", t.get("tradePrice", 0)) or 0)
        except: p = 0
        try: s = int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
        except: s = 0
        time_text = format_trade_time(t.get("time", t.get("at", t.get("date", ""))))
        rows += f"<tr><td style='color:#aaa; border-bottom:1px solid #222; padding:6px;'>{time_text}</td><td style='color:{price_color(p, prev_c)}; font-weight:bold; text-align:right; border-bottom:1px solid #222; padding:6px;'>{p:.2f}</td><td style='color:#ddd; text-align:right; border-bottom:1px solid #222; padding:6px;'>{s}</td></tr>"
    st.markdown(f"<div class='card' style='padding:0;'><div style='max-height:320px; overflow-y:auto; padding:15px;'><table style='width:100%; border-collapse:collapse; font-family:Consolas,\"Courier New\",monospace; font-size:16px;'><thead style='position:sticky; top:-15px; background:#111; z-index:2;'><tr style='color:#aaa;'><th style='text-align:left; padding:8px 6px; background:#111; border-bottom:1px solid #444;'>時間</th><th style='text-align:right; padding:8px 6px; background:#111; border-bottom:1px solid #444;'>成交價</th><th style='text-align:right; padding:8px 6px; background:#111; border-bottom:1px solid #444;'>成交量</th></tr></thead><tbody>{rows}</tbody></table></div></div>", unsafe_allow_html=True)

def render_volume_summary(bids, asks, trades, df_i, prev_c):
    st.markdown("### 📊 委託 / 成交量統計")
    bid_total = sum([x.get("size", 0) for x in bids])
    ask_total = sum([x.get("size", 0) for x in asks])
    total_order = bid_total + ask_total
    price_vol = {}
    for t in trades:
        try:
            p = float(t.get("price", t.get("tradePrice", 0)) or 0)
            s = int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
            if p > 0 and s > 0: price_vol[p] = price_vol.get(p, 0) + s
        except: continue
    trade_total = sum(price_vol.values())
    if trade_total == 0 and df_i is not None and not df_i.empty and "Volume" in df_i.columns:
        try: trade_total = int(df_i["Volume"].sum())
        except: trade_total = 0

    bid_pct = (bid_total / total_order * 100) if total_order else 0
    ask_pct = (ask_total / total_order * 100) if total_order else 0
    st.markdown(f"<div class='card'><div style='display:flex; gap:14px;'><div style='flex:1; text-align:center;'><div style='color:#aaa;'>委託買量</div><div style='font-size:28px; color:#ff3b3b; font-weight:bold;'>{bid_total:,}</div><div style='color:#888; font-size:12px;'>{bid_pct:.1f}%</div></div><div style='flex:1; text-align:center;'><div style='color:#aaa;'>委託賣量</div><div style='font-size:28px; color:#00e676; font-weight:bold;'>{ask_total:,}</div><div style='color:#888; font-size:12px;'>{ask_pct:.1f}%</div></div><div style='flex:1; text-align:center;'><div style='color:#aaa;'>總成交量</div><div style='font-size:28px; color:#ffcc00; font-weight:bold;'>{int(trade_total):,}</div><div style='color:#888; font-size:12px;'>今日累計</div></div></div><div style='margin-top:16px;'><div style='height:14px; background:#1a1a1a; border-radius:4px; display:flex; overflow:hidden;'><div style='width:{bid_pct}%; background:#ff3b3b;'></div><div style='width:{ask_pct}%; background:#00e676;'></div></div><div style='display:flex; justify-content:space-between; color:#aaa; margin-top:6px; font-size:12px;'><span>委買佔比</span><span>委賣佔比</span></div></div></div>", unsafe_allow_html=True)

    st.markdown("### 📈 今日成交價量分布（低 → 高）")
    if not price_vol:
        st.info("📡 尚無逐價成交量資料。")
        return
    max_v = max(price_vol.values()) if price_vol else 1
    rows = ""
    for p in sorted(price_vol.keys()):
        w = int((price_vol[p] / max_v) * 100)
        rows += f"<tr><td style='color:{price_color(p, prev_c)}; font-weight:bold; text-align:right; padding:6px;'>{p:.2f}</td><td style='width:70%; padding:6px;'><div style='height:16px; background:#1a1a1a; border-radius:3px;'><div style='height:16px; width:{w}%; background:#ffcc00; border-radius:3px;'></div></div></td><td style='text-align:right; color:#ddd; padding:6px;'>{price_vol[p]}</td></tr>"
    st.markdown(f"<div class='card' style='padding:0; margin-top:12px;'><div style='max-height:320px; overflow-y:auto; padding:15px;'><table style='width:100%; border-collapse:collapse; font-family:Consolas,\"Courier New\",monospace;'><thead style='position:sticky; top:-15px; background:#111; z-index:2; color:#aaa;'><tr style='border-bottom:1px solid #333;'><th style='text-align:right; padding-bottom:8px; background:#111;'>價格</th><th style='text-align:center; padding-bottom:8px; background:#111;'>量條</th><th style='text-align:right; padding-bottom:8px; background:#111;'>成交量</th></tr></thead><tbody>{rows}</tbody></table></div></div>", unsafe_allow_html=True)

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
curr = float(trade_price) if trade_price not in [None, 0] and not pd.isna(trade_price) else curr_yf

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
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="K線", increasing_line_color="#ff3b3b", decreasing_line_color="#00e676", increasing_fillcolor="#ff3b3b", decreasing_fillcolor="#00e676"), row=1, col=1)
    if cost > 0: fig.add_trace(go.Scatter(x=df.index, y=[cost]*len(df), mode="lines", name="成本線", line=dict(color="cyan", width=2, dash="dash")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=[curr]*len(df), mode="lines", name="現價線", line=dict(color="yellow", width=2, dash="dot")), row=1, col=1)
    
    if show_ma5: fig.add_trace(go.Scatter(x=df.index, y=df["Close"].rolling(5).mean(), mode="lines", line=dict(color="#FFD700", width=1.5), name="MA5"), row=1, col=1)
    if show_ma10: fig.add_trace(go.Scatter(x=df.index, y=df["Close"].rolling(10).mean(), mode="lines", line=dict(color="#00E5FF", width=1.5), name="MA10"), row=1, col=1)
    if show_ma20: fig.add_trace(go.Scatter(x=df.index, y=df["Close"].rolling(20).mean(), mode="lines", line=dict(color="#FF66FF", width=1.5), name="MA20"), row=1, col=1)

    vol_colors = ["rgba(255,59,59,0.5)" if c >= o else "rgba(0,230,118,0.5)" for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="成交量", marker_color=vol_colors), row=2, col=1)

    if tf == "1d":
        dt_obs = df.index.strftime("%Y-%m-%d").tolist()
        dt_all = pd.date_range(start=df.index[0], end=df.index[-1]).strftime("%Y-%m-%d").tolist()
        fig.update_xaxes(rangebreaks=[dict(values=[d for d in dt_all if d not in dt_obs])])

    fig.update_layout(template="plotly_dark", height=700, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h"), hovermode="x unified", paper_bgcolor="#000", plot_bgcolor="#000")
    fig.update_xaxes(gridcolor="#111")
    fig.update_yaxes(side="right", gridcolor="#111")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    dc, vc = st.columns([5, 4])
    with dc: render_trade_details(trades, prev_c)
    with vc: render_volume_summary(bids, asks, trades, df_i_for_summary, prev_c)

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
        
        df_plot = pd.concat([df_i, pd.DataFrame([[df_i["Open"].iloc[-1] if not df_i.empty else curr, curr, curr, curr, 0]], columns=["Open", "High", "Low", "Close", "Volume"], index=[now_ts])]).sort_index()
        df_plot = df_plot[~df_plot.index.duplicated(keep="last")]

        df_plot["VWAP"] = (df_plot["Close"] * df_plot["Volume"]).cumsum() / df_plot["Volume"].cumsum().replace(0, pd.NA)
        df_plot["VWAP"] = df_plot["VWAP"].bfill().fillna(df_plot["Close"])

        high_val, low_val = max(df_plot["High"].max(), curr), min(df_plot["Low"].min(), curr)
        amp_pct = ((high_val - low_val) / low_val) * 100 if low_val > 0 else 0

        buy_vol, sell_vol, v_colors, p_c = 0, 0, [], prev_c
        for _, r in df_plot.iterrows():
            c, v = r["Close"], r["Volume"] if not pd.isna(r["Volume"]) else 0
            if c >= p_c: buy_vol += v; v_colors.append("rgba(255,59,59,0.8)")
            else: sell_vol += v; v_colors.append("rgba(0,230,118,0.8)")
            p_c = c
            
        tot_force = buy_vol + sell_vol
        buy_pct, sell_pct = (buy_vol/tot_force*100) if tot_force else 50, (sell_vol/tot_force*100) if tot_force else 50

        df_plot['VMA'] = df_plot['Volume'].rolling(10).mean().shift(1)
        surges = [f"⚠️ {dt.strftime('%H:%M')} 爆量 {r['Volume']/r['VMA']:.1f} 倍" for dt, r in df_plot.iterrows() if r['Volume'] > 0 and r['VMA'] > 0 and r['Volume'] > r['VMA']*2][-5:]

        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>現價 / 漲跌</div><div style='color:{price_color(curr, prev_c)}; font-size:22px; font-weight:bold;'>{curr:.2f} <span style='font-size:16px;'>({diff:+.2f} {pct:+.2f}%)</span></div></div>", unsafe_allow_html=True)
        m2.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>最高 / 最低</div><div style='color:#fff; font-size:22px; font-weight:bold;'><span style='color:#ff3b3b'>{high_val:.2f}</span> <span style='color:#666;'>/</span> <span style='color:#00e676'>{low_val:.2f}</span></div></div>", unsafe_allow_html=True)
        m3.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>今日振幅</div><div style='color:#ffcc00; font-size:22px; font-weight:bold;'>{amp_pct:.2f}%</div></div>", unsafe_allow_html=True)
        m4.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>即時均價 (VWAP)</div><div style='color:#fff; font-size:22px; font-weight:bold;'>{df_plot['VWAP'].iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='card' style='margin-top:10px; margin-bottom:15px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px; font-size:15px;'><span style='color:#ff3b3b; font-weight:bold;'>🔥 主動買盤 {buy_pct:.1f}%</span><span style='color:#00e676; font-weight:bold;'>❄️ 主動賣盤 {sell_pct:.1f}%</span></div><div style='height:12px; background:#1a1a1a; border-radius:6px; display:flex; overflow:hidden;'><div style='width:{buy_pct}%; background:#ff3b3b;'></div><div style='width:{sell_pct}%; background:#00e676;'></div></div></div>", unsafe_allow_html=True)
        if surges: st.markdown(f"<div style='margin-bottom:15px;'>{''.join([f'<span style=\"background:#332b00; border:1px solid #665500; color:#ffcc00; padding:4px 10px; border-radius:5px; margin-right:10px; font-size:14px; font-weight:bold;\">{s}</span>' for s in surges])}</div>", unsafe_allow_html=True)

        cdata = [[r['Volume'], ((r['Close']-prev_c)/prev_c*100) if prev_c else 0] for _, r in df_plot.iterrows()]
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["Close"], mode="lines", name="即價", line=dict(color="yellow", width=2.5), customdata=cdata, hovertemplate="<b>時間:</b> %{x|%H:%M}<br><b>價格:</b> %{y:.2f}<br><b>漲跌:</b> %{customdata[1]:+.2f}%<br><b>量:</b> %{customdata[0]:,.0f}<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["VWAP"], mode="lines", name="均價", line=dict(color="white", width=1.5, dash="dot"), hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=[prev_c]*len(df_plot), mode="lines", name="昨收", line=dict(color="#777", dash="dash"), hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot["Volume"], name="分量", marker_color=v_colors, customdata=cdata, hovertemplate="<b>時間:</b> %{x|%H:%M}<br><b>量:</b> %{y:,.0f}<extra></extra>"), row=2, col=1)
        
        today = df_plot.index[-1].date()
        fig.update_xaxes(range=[pd.Timestamp(f"{today} 09:00", tz="Asia/Taipei"), pd.Timestamp(f"{today} 13:30", tz="Asia/Taipei")], tickformat="%H:%M")
        fig.update_layout(template="plotly_dark", height=650, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hovermode="x unified", paper_bgcolor="#000", plot_bgcolor="#000")
        fig.update_xaxes(gridcolor="#111", showspikes=True, spikemode="across", spikesnap="cursor", showline=False, spikedash="solid")
        fig.update_yaxes(side="right", gridcolor="#111")
        st.plotly_chart(fig, use_container_width=True)
    else: st.warning("⚠️ 無盤中資料")

# =====================
# 🤖 AI綜合預測 (全新多因子模型)
# =====================
elif page == "🤖 AI綜合預測":
    st.markdown(f"## 🤖 {display_name} AI 綜合預測中心")
    
    # 1. 技術面運算
    ts = 0
    try:
        if len(df) >= 20:
            ma5 = df['Close'].rolling(5).mean().iloc[-1]
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            h20 = df['High'].rolling(20).max().iloc[-1]
            vma20 = df['Volume'].rolling(20).mean().iloc[-1]
            vol_curr = df['Volume'].iloc[-1]
            if curr > ma5: ts += 10
            if curr > ma20: ts += 20
            if curr >= h20 * 0.99: ts += 25
            if vol_curr > vma20: ts += 20
            if curr >= open_p: ts += 10
            if curr > prev_c and vol_curr > df['Volume'].iloc[-2]: ts += 15
        else: ts = 50
    except: ts = 50
    ts = max(0, min(100, ts))

    # 2. 盤中即時運算
    ids = 0
    buy_pct = 0.5 
    sell_pct = 0.5
    try:
        if not df_i_for_summary.empty:
            df_intra = df_i_for_summary.copy()
            vwap = (df_intra['Close'] * df_intra['Volume']).sum() / df_intra['Volume'].sum() if df_intra['Volume'].sum() > 0 else curr
            high_d = max(df_intra['High'].max(), curr)
            low_d = min(df_intra['Low'].min(), curr)
            amp = (high_d - low_d) / low_d if low_d > 0 else 0
            
            buy_v = 0
            p_c = prev_c
            for _, r in df_intra.iterrows():
                if r['Close'] >= p_c: buy_v += r['Volume']
                p_c = r['Close']
            tot_v = df_intra['Volume'].sum()
            buy_pct = buy_v / tot_v if tot_v > 0 else 0.5
            sell_pct = 1 - buy_pct
            
            if curr > vwap: ids += 20
            if buy_pct > 0.6: ids += 25
            if len(df) >= 20 and df_intra['Volume'].max() > df['Volume'].rolling(20).mean().iloc[-1] / 270 * 2: ids += 20
            if high_d > 0 and (high_d - curr)/high_d < 0.01: ids += 15
            if amp > 0.03: ids += 10
        else: ids = 50
    except: ids = 50
    ids = max(0, min(100, ids))

    # 3. 籌碼五檔運算
    cs = 0
    try:
        if bids and asks:
            bid_v = sum(x.get('size', 0) for x in bids)
            ask_v = sum(x.get('size', 0) for x in asks)
            tot_ba = bid_v + ask_v
            if bid_v > ask_v: cs += 20
            if tot_ba > 0 and (bid_v - ask_v)/tot_ba > 0.2: cs += 20
            if len(bids)>0 and bids[0].get('size',0) > 100: cs += 20
            if bid_v > ask_v * 1.5: cs += 20
            cs += 20 
        else: cs = 50
    except: cs = 50
    cs = max(0, min(100, cs))

    # 4. 基本面運算
    fs = 0
    try:
        info, _ = fetch_fundamentals(symbol, suffix)
        if info:
            eps_val = info.get('trailingEps')
            roe_val = info.get('returnOnEquity')
            dy_val = info.get('dividendYield')
            pe_val = info.get('trailingPE')
            rev_g = info.get('revenueGrowth')
            
            if eps_val and eps_val > 10: fs += 20
            if roe_val and roe_val > 0.15: fs += 20
            if dy_val and dy_val > 0.05: fs += 20
            if pe_val and 0 < pe_val < 20: fs += 20
            if rev_g and rev_g > 0: fs += 20
        else: fs = 50
    except: fs = 50
    fs = max(0, min(100, fs))

    total_score = ts * 0.3 + ids * 0.25 + cs * 0.2 + fs * 0.25
    
    if total_score >= 85: t_tag, t_color = "🚀 強勢多方", "#ff3b3b"
    elif total_score >= 70: t_tag, t_color = "📈 偏多", "#ff9900"
    elif total_score >= 55: t_tag, t_color = "🟡 中性偏多", "#ffcc00"
    elif total_score >= 45: t_tag, t_color = "⚖️ 震盪", "#aaaaaa"
    elif total_score >= 30: t_tag, t_color = "📉 偏空", "#00e676"
    else: t_tag, t_color = "❄️ 弱勢", "#009900"

    t1, t2, t3 = st.columns([3, 4, 3])
    with t1:
        st.plotly_chart(donut_chart("🤖 綜合評分", total_score, t_tag, t_color), use_container_width=True)
    with t2:
        fig_r = go.Figure(go.Scatterpolar(
            r=[ts, ids, cs, fs, ts], theta=['技術面', '即時盤中', '籌碼五檔', '基本面', '技術面'],
            fill='toself', line_color='#00e5ff', fillcolor='rgba(0, 229, 255, 0.3)'
        ))
        fig_r.update_layout(
            template="plotly_dark", height=280, margin=dict(l=30, r=30, t=30, b=30),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            polar=dict(radialaxis=dict(visible=True, range=[0, 100], gridcolor="#333"), angularaxis=dict(gridcolor="#333"))
        )
        st.plotly_chart(fig_r, use_container_width=True)
    with t3:
        fig_b = go.Figure(go.Bar(
            x=[ts, ids, cs, fs], y=['技術', '盤中', '籌碼', '基本'], orientation='h',
            marker_color=['#ffcc00', '#00e676', '#ff3b3b', '#aa00ff'],
            text=[f"{ts:.0f}", f"{ids:.0f}", f"{cs:.0f}", f"{fs:.0f}"], textposition='auto'
        ))
        fig_b.update_layout(
            template="plotly_dark", height=280, margin=dict(l=10, r=10, t=30, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(range=[0,100], gridcolor="#333")
        )
        st.plotly_chart(fig_b, use_container_width=True)

    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    def render_mod_card(title, score, color, desc):
        return f"<div class='card' style='height:100%; border-top:4px solid {color};'><h4 style='color:#ccc; margin-bottom:5px;'>{title}</h4><div style='font-size:32px; font-weight:bold; color:{color}; margin-bottom:10px;'>{score:.0f}<span style='font-size:14px; color:#888;'> / 100</span></div><p style='color:#bbb; font-size:14px; line-height:1.5;'>{desc}</p></div>"
    
    m1.markdown(render_mod_card("1️⃣ 技術面", ts, "#ffcc00", "分析長短期均線排列、20日高低點突破狀況以及量價配合結構。"), unsafe_allow_html=True)
    m2.markdown(render_mod_card("2️⃣ 即時盤中", ids, "#00e676", "偵測盤中VWAP均價線防守、主動買盤力道與異常爆量訊號。"), unsafe_allow_html=True)
    m3.markdown(render_mod_card("3️⃣ 籌碼五檔", cs, "#ff3b3b", "觀測最佳五檔買賣壓差、掛單積極度與大戶即時敲單方向。"), unsafe_allow_html=True)
    m4.markdown(render_mod_card("4️⃣ 基本面", fs, "#aa00ff", "評估企業EPS獲利能力、ROE回報率、殖利率防禦及估值高低。"), unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📝 AI 深度解析報告")
    
    t_text = f"從技術線型來看，目前股價表現得分 {ts:.0f} 分。短期與中期均線的排列狀況，決定了目前趨勢的延續性。近期股價相對於20日高低點的位置，反映出市場突破的企圖心。配合近期的量能變化，整體技術結構顯示 {'多方掌控' if ts>=60 else '空方壓制' if ts<40 else '橫盤震盪'}。建議密切觀察關鍵壓力與支撐的攻防。"
    i_text = f"觀察今日即時走勢，盤中綜合評分為 {ids:.0f} 分。股價與分時均價線(VWAP)的相對位置，顯示了當沖客與造市者的成本防線。今日主動買盤達 {buy_pct*100:.1f}%，暗示了資金的真實攻擊方向。若盤中出現急拉爆量，需提防獲利了結賣壓。整體振幅大小亦決定了今日交易的活躍程度。"
    c_text = f"籌碼與五檔掛單分析顯示，目前籌碼健康度達 {cs:.0f} 分。最佳五檔的委買與委賣力道懸殊，反映了造市者與散戶的心理預期。當大單敲進或倒出時，即時成交明細揭露了主力吃貨或出貨的痕跡。買賣報價的滑價空間，顯示流動性是否充足。後續需追蹤主力籌碼是否具備延續性。"
    f_text = f"基本面價值評估獲得 {fs:.0f} 分。公司的獲利數據，直接反映了其長期營運能力與股東資本回報率。配合目前的本益比與股價淨值比區間，可判斷當前股價是否具備估值優勢。近期營收的成長率，是支撐股價上行的最重要催化劑。高股息殖利率亦能為股價提供下檔防禦保護。"
    
    conc_text = f"綜合四大面向的 AI 預測模型，目前標的總評分為 **{total_score:.1f}** 分，系統判定為「**{t_tag}**」。偏多的底氣主要來自於資金動能的匯聚以及技術關卡的突破。然而，偏空風險可能潛藏於短線過熱或基本面估值過高的疑慮之中。短線操作上，建議以 VWAP 均價線作為當沖多空分水嶺。中長線投資人則應緊盯即將公布的營收與財報數據。市場量能的變化將是決定下一波趨勢的靈魂。主力大戶的籌碼堆疊方向，預示著未來的潛在走勢。<br><br><span style='color:#ff3b3b;'>⚠️ 本分析模型基於量化數據自動生成，僅供觀察參考，市場瞬息萬變，投資人應自行審慎評估風險，不構成任何買賣建議。</span>"

    text_html = f"""
    <div style='display:grid; grid-template-columns: 1fr 1fr; gap: 20px;'>
        <div class='card'><h4>📈 技術與盤中動能</h4>
            <p style='color:#ccc; font-size:15px; line-height:1.6;'><b>技術面：</b>{t_text}</p>
            <p style='color:#ccc; font-size:15px; line-height:1.6;'><b>即時盤中：</b>{i_text}</p>
        </div>
        <div class='card'><h4>💼 籌碼與基本面價值</h4>
            <p style='color:#ccc; font-size:15px; line-height:1.6;'><b>籌碼五檔：</b>{c_text}</p>
            <p style='color:#ccc; font-size:15px; line-height:1.6;'><b>基本面：</b>{f_text}</p>
        </div>
    </div>
    <div class='card' style='margin-top:20px; border:1px solid #555; background:#151515;'>
        <h3 style='color:#ffcc00; margin-bottom:10px;'>🎯 AI 綜合總結建議</h3>
        <p style='color:#eee; font-size:16px; line-height:1.8;'>{conc_text}</p>
    </div>
    """
    st.markdown(text_html, unsafe_allow_html=True)

# =====================
# 📑 基本面分析
# =====================
elif page == "📑 基本面分析":
    st.markdown(f"## 📑 {display_name} 基本面分析")
    info, fin_data = fetch_fundamentals(symbol, suffix)
    rev_df = fetch_monthly_revenue(symbol)
    
    def safe_get(key, default="N/A"): return info.get(key, default) if info.get(key) is not None else default
    def fmt_pct_ratio(val):
        if val=="N/A" or pd.isna(val): return "N/A"
        try:
            v=float(val)
            return f"{v:.2f}%" if abs(v)>1 else f"{v*100:.2f}%"
        except: return "N/A"
    def norm_rat(val):
        if val=="N/A" or pd.isna(val): return None
        try:
            v=float(val)
            return v/100 if abs(v)>1 else v
        except: return None
    def fmt_flt(val, dec=2): return f"{float(val):.{dec}f}" if val!="N/A" and not pd.isna(val) else "N/A"
    def fmt_curr(val):
        if val=="N/A" or pd.isna(val): return "N/A"
        try:
            v=float(val)
            return f"{v/1e12:.2f} 兆" if abs(v)>=1e12 else f"{v/1e8:.2f} 億" if abs(v)>=1e8 else f"{v/1e4:.2f} 萬" if abs(v)>=1e4 else f"{v:,.0f}"
        except: return "N/A"
    def fmt_date(val): return datetime.fromtimestamp(val).strftime('%Y-%m-%d') if val!="N/A" and not pd.isna(val) else "N/A"

    sector = INDUSTRY_BACKUP.get(symbol, safe_get("sector"))
    mc, emp, cty, cur = safe_get("marketCap", 0), safe_get("fullTimeEmployees"), safe_get("country"), safe_get("currency")
    eps, pe, pb, roe, dy = safe_get("trailingEps", 0), safe_get("trailingPE", 0), safe_get("priceToBook", 0), safe_get("returnOnEquity", 0), safe_get("dividendYield", 0)
    
    i1, i2, i3, i4 = st.columns(4)
    i1.markdown(f"<div class='card'><div style='color:#aaa;'>產業板塊</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{sector}</div></div>", unsafe_allow_html=True)
    i2.markdown(f"<div class='card'><div style='color:#aaa;'>公司市值</div><div style='font-size:20px; font-weight:bold; color:#ffcc00;'>{fmt_curr(mc)}</div></div>", unsafe_allow_html=True)
    i3.markdown(f"<div class='card'><div style='color:#aaa;'>員工總數</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{emp}</div></div>", unsafe_allow_html=True)
    i4.markdown(f"<div class='card'><div style='color:#aaa;'>國家/幣別</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{cty} / {cur}</div></div>", unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>EPS(近四季)</div><div style='font-size:22px; font-weight:bold; color:#ff3b3b;'>{fmt_flt(eps)}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>PER</div><div style='font-size:22px; font-weight:bold; color:#00e676;'>{fmt_flt(pe)}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>PBR</div><div style='font-size:22px; font-weight:bold; color:#00e676;'>{fmt_flt(pb)}</div></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>ROE</div><div style='font-size:22px; font-weight:bold; color:#ffcc00;'>{fmt_pct_ratio(roe)}</div></div>", unsafe_allow_html=True)
    c5.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>殖利率</div><div style='font-size:22px; font-weight:bold; color:#ff3b3b;'>{fmt_pct_ratio(dy)}</div></div>", unsafe_allow_html=True)
    c6.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>市值規模</div><div style='font-size:22px; font-weight:bold; color:#fff;'>{fmt_curr(mc)}</div></div>", unsafe_allow_html=True)

    rn, dyn, sc = norm_rat(roe), norm_rat(dy), 0
    if eps!="N/A" and eps>0: sc += 20 if eps>10 else 10 if eps>5 else 0
    if rn is not None and rn>0: sc += 20 if rn>0.15 else 10 if rn>0.1 else 0
    if dyn is not None and dyn>0: sc += 20 if dyn>0.05 else 10 if dyn>0.03 else 0
    if pe!="N/A" and pe>0: sc += 20 if pe<15 else 10 if pe<25 else 0
    if pb!="N/A" and pb>0: sc += 20 if pb<2 else 10 if pb<4 else 0
    sc = max(0, min(100, sc))

    stg, scl = ("🔥 極度優秀","#ff3b3b") if sc>=90 else ("✅ 基本面強勁","#ff9900") if sc>=75 else ("👍 穩健型公司","#ffcc00") if sc>=60 else ("⚠️ 普通","#aaaaaa") if sc>=40 else ("❄️ 基本面偏弱","#00e676")
    
    ais = "公司具備優異獲利能力(ROE高)，" if rn and rn>0.15 else "公司獲利尚可，" if rn and rn>0 else "目前獲利偏弱，"
    ais += "具高殖利率防禦保護。" if dyn and dyn>0.05 else "偏向不發高息之資本策略。"
    ais += ("<br>目前本益比偏低，具潛在價值。" if pe!="N/A" and 0<pe<15 else "<br>目前本益比較高，偏向成長型評價。" if pe!="N/A" and pe>25 else "<br>估值處合理區間。" if pe!="N/A" and pe>0 else "<br>無有效PER參考。")

    st.markdown("---")
    s1, s2 = st.columns([3, 7])
    with s1: st.plotly_chart(donut_chart("🤖 AI 評分", sc, stg, scl), use_container_width=True)
    with s2: st.markdown(f"<div class='card' style='height:260px; display:flex; align-items:center; padding:30px;'><h3 style='color:#fff; line-height:1.6;'>{ais}</h3></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📅 每月營收")
    if rev_df.empty: st.info("📡 暫無營收資料")
    else:
        cr1, cr2 = st.columns([4, 6])
        with cr1:
            h = "<div style='overflow-x:auto; max-height:400px; border-radius:12px; border:1px solid #222;'><table class='fin-table'><thead style='position:sticky; top:0; background:#222;'><tr><th>月份</th><th style='text-align:right'>營收(億)</th><th style='text-align:right'>MoM</th><th style='text-align:right'>YoY</th></tr></thead><tbody>"
            for _, r in rev_df.iterrows():
                m, rv, mom, yoy = r["月份"], r["營收（億元台幣）"], r["月增率 MoM"], r["年增率 YoY"]
                h += f"<tr><td>{m}</td><td style='text-align:right'>{rv:.2f}</td><td style='text-align:right; color: {'#ff3b3b' if mom>0 else '#00e676' if mom<0 else '#fff'};'>{mom:+.2f}%</td><td style='text-align:right; color: {'#ff3b3b' if yoy>0 else '#00e676' if yoy<0 else '#fff'};'>{yoy:+.2f}%</td></tr>"
            st.markdown(h+"</tbody></table></div>", unsafe_allow_html=True)
        with cr2:
            d_c = rev_df.iloc[::-1]
            fr = make_subplots(specs=[[{"secondary_y": True}]])
            fr.add_trace(go.Bar(x=d_c['月份'], y=d_c['營收（億元台幣）'], name="營收(億)", marker_color="#00e5ff"), secondary_y=False)
            fr.add_trace(go.Scatter(x=d_c['月份'], y=d_c['年增率 YoY'], name="YoY(%)", line=dict(color="#ff3b3b", width=2)), secondary_y=True)
            fr.update_layout(template="plotly_dark", height=400, margin=dict(l=10, r=10, t=20, b=10), paper_bgcolor="#000", plot_bgcolor="#000", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fr, use_container_width=True)

    st.markdown("---")
    st.markdown("### 📋 基本面詳細表格")
    dte_str = f"{fmt_flt(safe_get('debtToEquity'))}%" if safe_get('debtToEquity')!="N/A" else "N/A"
    th = (
        "<div style='overflow-x:auto; max-height:700px; border-radius:12px; border:1px solid #222;'><table class='fin-table'><thead style='position:sticky; top:0; background:#222;'>"
        "<tr><th>分類</th><th>指標</th><th>數值</th><th>解讀</th></tr></thead><tbody>"
        f"<tr><td rowspan='5' style='color:#ffcc00; font-weight:bold;'>💰 獲利能力</td><td>毛利率</td><td>{fmt_pct_ratio(safe_get('grossMargins'))}</td><td>產品附加價值</td></tr>"
        f"<tr><td>營益率</td><td>{fmt_pct_ratio(safe_get('operatingMargins'))}</td><td>本業獲利能力</td></tr>"
        f"<tr><td>淨利率</td><td>{fmt_pct_ratio(safe_get('profitMargins'))}</td><td>最終獲利能力</td></tr>"
        f"<tr><td>ROE</td><td>{fmt_pct_ratio(safe_get('returnOnEquity'))}</td><td>股東權益報酬</td></tr>"
        f"<tr><td>ROA</td><td>{fmt_pct_ratio(safe_get('returnOnAssets'))}</td><td>資產報酬率</td></tr>"
        f"<tr><td rowspan='4' style='color:#00e5ff; font-weight:bold;'>🛡️ 財務安全</td><td>負債比</td><td>{dte_str}</td><td>財務槓桿</td></tr>"
        f"<tr><td>流動比率</td><td>{fmt_flt(safe_get('currentRatio'))}</td><td>短期償債能力</td></tr>"
        f"<tr><td>自由現金流</td><td>{fmt_curr(safe_get('freeCashflow'))}</td><td>可支配現金</td></tr>"
        f"<tr><td>現金部位</td><td>{fmt_curr(safe_get('totalCash'))}</td><td>帳上現金總額</td></tr>"
        f"<tr><td rowspan='4' style='color:#ff3b3b; font-weight:bold;'>💸 股利政策</td><td>殖利率</td><td>{fmt_pct_ratio(safe_get('dividendYield'))}</td><td>股息報酬率</td></tr>"
        f"<tr><td>現金股息</td><td>{fmt_flt(safe_get('dividendRate'))}</td><td>預計發放金額</td></tr>"
        f"<tr><td>配息率</td><td>{fmt_pct_ratio(safe_get('payoutRatio'))}</td><td>發放股息比例</td></tr>"
        f"<tr><td>除息日</td><td>{fmt_date(safe_get('exDividendDate'))}</td><td>最近除權息日</td></tr>"
        f"<tr><td rowspan='5' style='color:#00e676; font-weight:bold;'>⚖️ 估值分析</td><td>PER</td><td>{fmt_flt(safe_get('trailingPE'))}</td><td>本益比</td></tr>"
        f"<tr><td>預估PER</td><td>{fmt_flt(safe_get('forwardPE'))}</td><td>未來獲利預估</td></tr>"
        f"<tr><td>PBR</td><td>{fmt_flt(safe_get('priceToBook'))}</td><td>股價淨值比</td></tr>"
        f"<tr><td>PEG</td><td>{fmt_flt(safe_get('pegRatio'))}</td><td>本益成長比</td></tr>"
        f"<tr><td>Beta</td><td>{fmt_flt(safe_get('beta'))}</td><td>股價波動度</td></tr>"
        f"<tr><td rowspan='4' style='color:#ff9900; font-weight:bold;'>🚀 成長性</td><td>營收成長(YoY)</td><td>{fmt_pct_ratio(safe_get('revenueGrowth'))}</td><td>年營收成長</td></tr>"
        f"<tr><td>淨利成長(YoY)</td><td>{fmt_pct_ratio(safe_get('earningsGrowth'))}</td><td>年淨利成長</td></tr>"
        f"<tr><td>季營收成長(QoQ)</td><td>{fmt_pct_ratio(safe_get('quarterlyRevenueGrowth'))}</td><td>短期營收動能</td></tr>"
        f"<tr><td>季淨利成長(QoQ)</td><td>{fmt_pct_ratio(safe_get('quarterlyEarningsGrowth'))}</td><td>短期淨利動能</td></tr>"
        "</tbody></table></div>"
    )
    st.markdown(th, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📈 歷年財報趨勢圖")
    if not fin_data.empty:
        ff = make_subplots(specs=[[{"secondary_y": True}]])
        hp = False
        if 'Total Revenue' in fin_data.columns: ff.add_trace(go.Bar(x=fin_data.index, y=fin_data['Total Revenue']/1e8, name="營收(億)", marker_color="rgba(255,204,0,0.7)"), secondary_y=False); hp=True
        elif 'Operating Revenue' in fin_data.columns: ff.add_trace(go.Bar(x=fin_data.index, y=fin_data['Operating Revenue']/1e8, name="營業收入(億)", marker_color="rgba(255,204,0,0.7)"), secondary_y=False); hp=True
        if 'Net Income' in fin_data.columns: ff.add_trace(go.Scatter(x=fin_data.index, y=fin_data['Net Income']/1e8, name="淨利(億)", line=dict(color="#ff3b3b", width=3)), secondary_y=False); hp=True
        if 'Basic EPS' in fin_data.columns: ff.add_trace(go.Scatter(x=fin_data.index, y=fin_data['Basic EPS'], name="EPS", line=dict(color="#fff", width=2, dash="dot")), secondary_y=True); hp=True
        if hp:
            ff.update_layout(template="plotly_dark", height=500, margin=dict(l=10, r=10, t=20, b=10), paper_bgcolor="#000", plot_bgcolor="#000")
            ff.update_xaxes(type='category')
            ff.update_yaxes(title_text="金額(億元台幣)", secondary_y=False)
            st.plotly_chart(ff, use_container_width=True)
        else: st.info("📡 暫無圖表資料")
    else: st.info("📡 暫無財報趨勢資料")

# =====================
# 底部資訊 (全頁共用)
# =====================
st.markdown("---")
b1, b2 = st.columns([4, 6])
with b1:
    pnl_c = "#ff3b3b" if profit > 0 else "#00e676" if profit < 0 else "#fff"
    st.markdown(f"<div style='background:#111; padding:20px; border-radius:10px; border:1px solid #333; height:100%;'><h3>💰 庫存狀態</h3><p style='color:#aaa;'>{display_name}</p><p style='color:#aaa;'>成本：{cost:.2f} ｜ 張數：{qty:.0f}</p><p style='font-size:24px; color:{price_color(curr, prev_c)}; font-weight:bold;'>現價：{curr:.2f} <span style='font-size:18px;'>({diff:+.2f} / {pct:+.2f}%)</span></p><h3>📊 總盈虧</h3><div style='font-size:42px; font-weight:bold; color:{pnl_c};'>{int(profit):,} 元</div></div>", unsafe_allow_html=True)

if page != "📑 基本面分析":
    with b2:
        st.markdown("### ⚖️ 即時五檔明細")
        render_order_book(bids, asks, prev_c, curr)
