# =========================
# 台股戰情室 Pro 完整穩定版
# =========================

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import feedparser
import re
from urllib.parse import quote
from streamlit_autorefresh import st_autorefresh

# =========================
# 頁面設定
# =========================
st.set_page_config(
    layout="wide",
    page_title="台股戰情室 Pro"
)

# =========================
# 黑色主題
# =========================
st.markdown("""
<style>

html, body, [class*="st-"]{
    background-color:#000;
    color:#EEE;
}

.block-container{
    padding-top:1rem;
    max-width:98%;
}

.stTextInput input,
.stNumberInput input{
    background:#111 !important;
    color:white !important;
    border:1px solid #444 !important;
}

.card{
    background:#050505;
    border:1px solid #222;
    border-radius:12px;
    padding:15px;
}

</style>
""", unsafe_allow_html=True)

# =========================
# 股票名稱資料
# =========================
@st.cache_data(ttl=86400)
def load_market_dict():

    market_dict = {}

    # ===== 1. 官方 OpenAPI =====
    try:

        r = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
            headers={"User-Agent":"Mozilla/5.0"},
            timeout=10
        )

        if r.status_code == 200:

            for i in r.json():

                code = str(i.get("Code","")).strip()
                name = str(i.get("Name","")).strip()

                if code and name:

                    market_dict[code] = name
                    market_dict[name] = code

    except:
        pass

    # ===== 上櫃 OpenAPI =====
    try:

        r2 = requests.get(
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
            headers={"User-Agent":"Mozilla/5.0"},
            timeout=10
        )

        if r2.status_code == 200:

            for i in r2.json():

                code = (
                    i.get("SecuritiesCompanyCode")
                    or i.get("Code")
                )

                name = (
                    i.get("CompanyName")
                    or i.get("Name")
                )

                if code and name:

                    code = str(code).strip()
                    name = str(name).strip()

                    market_dict[code] = name
                    market_dict[name] = code

    except:
        pass

    # ===== ISIN 上市 =====
    try:

        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"

        tables = pd.read_html(url)

        df = tables[0]

        for i in range(len(df)):

            try:

                raw = str(df.iloc[i,0]).strip()

                parts = raw.replace("　", " ").split(maxsplit=1)

                if len(parts) == 2:

                    code = parts[0].strip()
                    name = parts[1].strip()

                    if code.isalnum():

                        market_dict[code] = name
                        market_dict[name] = code

            except:
                pass

    except:
        pass

    # ===== ISIN 上櫃 =====
    try:

        url_otc = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"

        tables_otc = pd.read_html(url_otc)

        df_otc = tables_otc[0]

        for i in range(len(df_otc)):

            try:

                raw = str(df_otc.iloc[i,0]).strip()

                parts = raw.replace("　", " ").split(maxsplit=1)

                if len(parts) == 2:

                    code = parts[0].strip()
                    name = parts[1].strip()

                    if code.isalnum():

                        market_dict[code] = name
                        market_dict[name] = code

            except:
                pass

    except:
        pass

    # ===== ETF 補充 =====
    etf_extra = {
        "0050":"元大台灣50",
        "0056":"元大高股息",
        "006208":"富邦台50",
        "00878":"國泰永續高股息",
        "00919":"群益台灣精選高息",
        "00929":"復華台灣科技優息",
        "00940":"元大台灣價值高息",
        "00713":"元大高息低波",
        "00757":"統一FANG+",
        "00679B":"元大美債20年"
    }

    for k, v in etf_extra.items():

        market_dict[k] = v
        market_dict[v] = k

    return market_dict

MASTER_DICT = load_market_dict()

# =========================
# 上方控制
# =========================
c1, c2, c3, c4 = st.columns([2,3,2,2])

# ===== 頁面 =====
with c1:

    page = st.radio(
        "📌 頁面",
        ["📊 K線分析", "⚡ 即時趨勢", "📰 AI新聞預測"],
        horizontal=True
    )

# ===== 股票搜尋 =====
with c2:

    stock_input = st.text_input(
        "🔍 股票代號 / 中文名稱",
        value="1711"
    )

    stock_input = stock_input.strip()

    if stock_input in MASTER_DICT:

        # 輸入代號
        if stock_input.isdigit() or stock_input.endswith("B"):

            symbol = stock_input
            stock_name = MASTER_DICT.get(symbol, symbol)

        # 輸入中文
        else:

            symbol = MASTER_DICT.get(stock_input, stock_input)
            stock_name = stock_input

    else:

        symbol = stock_input
        stock_name = stock_input

    display_name = f"{symbol} {stock_name}"

# ===== K線週期 =====
with c3:

    tf_label = st.selectbox(
        "📈 K線週期",
        ["日K","週K","月K"]
    )

    tf_map = {
        "日K":"1d",
        "週K":"1wk",
        "月K":"1mo"
    }

    period_map = {
        "日K":"6mo",
        "週K":"2y",
        "月K":"5y"
    }

    tf = tf_map[tf_label]
    period = period_map[tf_label]

    ma1, ma2, ma3 = st.columns(3)

    with ma1:
        show_ma5 = st.checkbox("5線", True)

    with ma2:
        show_ma10 = st.checkbox("10線", True)

    with ma3:
        show_ma20 = st.checkbox("20線", True)

# ===== 庫存 =====
with c4:

    qty = st.number_input(
        "📦 持股張數",
        value=1.0
    )

    cost = st.number_input(
        "💰 平均成本",
        value=50.0
    )

# =========================
# 自動刷新
# =========================
st_autorefresh(interval=15000, key="refresh")

# =========================
# 工具
# =========================
def flatten_columns(df):

    if not df.empty and isinstance(df.columns, pd.MultiIndex):

        df.columns = df.columns.get_level_values(0)

    return df

# =========================
# 歷史資料
# =========================
@st.cache_data(ttl=30)
def fetch_history(symbol, period, interval):

    try:

        df = yf.download(
            f"{symbol}.TW",
            period=period,
            interval=interval,
            auto_adjust=False,
            progress=False,
            threads=False
        )

        suffix = ".TW"

    except:

        df = pd.DataFrame()
        suffix = ".TW"

    if df.empty:

        try:

            df = yf.download(
                f"{symbol}.TWO",
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False
            )

            suffix = ".TWO"

        except:

            df = pd.DataFrame()
            suffix = ".TW"

    df = flatten_columns(df)

    return df, suffix

# =========================
# 即時資料
# =========================
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

        if df_i.index.tz is None:
            df_i.index = df_i.index.tz_localize("Asia/Taipei")
        else:
            df_i.index = df_i.index.tz_convert("Asia/Taipei")

        latest_day = df_i.index.date.max()

        df_i = df_i[df_i.index.date == latest_day]

    return df_i

# =========================
# 下載資料
# =========================
df, suffix = fetch_history(symbol, period, tf)

if df.empty:

    st.error(f"❌ 查無股票資料：{symbol}")
    st.stop()

curr = float(df["Close"].iloc[-1])
prev_c = float(df["Close"].iloc[-2])

diff = curr - prev_c
pct = diff / prev_c * 100

profit = (curr - cost) * qty * 1000

# =========================
# 顏色
# =========================
def price_color(price, prev):

    if price > prev:
        return "#ff3b3b"

    elif price < prev:
        return "#00e676"

    return "#fff"

# =========================
# K線分析
# =========================
if page == "📊 K線分析":

    st.markdown(f"## 📊 {display_name}")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.75,0.25],
        vertical_spacing=0.03
    )

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            increasing_line_color="#ff3b3b",
            decreasing_line_color="#00e676",
            increasing_fillcolor="#ff3b3b",
            decreasing_fillcolor="#00e676"
        ),
        row=1,
        col=1
    )

    if show_ma5:

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["Close"].rolling(5).mean(),
                mode="lines",
                name="MA5"
            ),
            row=1,
            col=1
        )

    if show_ma10:

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["Close"].rolling(10).mean(),
                mode="lines",
                name="MA10"
            ),
            row=1,
            col=1
        )

    if show_ma20:

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["Close"].rolling(20).mean(),
                mode="lines",
                name="MA20"
            ),
            row=1,
            col=1
        )

    vol_colors = [
        "#ff3b3b" if c >= o else "#00e676"
        for o, c in zip(df["Open"], df["Close"])
    ]

    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["Volume"],
            marker_color=vol_colors
        ),
        row=2,
        col=1
    )

    fig.update_layout(
        template="plotly_dark",
        height=760,
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#000",
        plot_bgcolor="#000"
    )

    st.plotly_chart(fig, use_container_width=True)

# =========================
# 即時趨勢
# =========================
elif page == "⚡ 即時趨勢":

    st.markdown(f"## ⚡ {display_name}")

    df_i = fetch_intraday(symbol, suffix)

    if not df_i.empty:

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            row_heights=[0.75,0.25]
        )

        fig.add_trace(
            go.Scatter(
                x=df_i.index,
                y=df_i["Close"],
                mode="lines",
                line=dict(color="yellow", width=2)
            ),
            row=1,
            col=1
        )

        vol_colors = []

        prev = None

        for _, row in df_i.iterrows():

            if prev is None:
                vol_colors.append("#ff3b3b")

            else:

                if row["Close"] >= prev:
                    vol_colors.append("#ff3b3b")
                else:
                    vol_colors.append("#00e676")

            prev = row["Close"]

        fig.add_trace(
            go.Bar(
                x=df_i.index,
                y=df_i["Volume"],
                marker_color=vol_colors
            ),
            row=2,
            col=1
        )

        fig.update_layout(
            template="plotly_dark",
            height=760,
            paper_bgcolor="#000",
            plot_bgcolor="#000"
        )

        st.plotly_chart(fig, use_container_width=True)

# =========================
# AI 新聞
# =========================
elif page == "📰 AI新聞預測":

    st.markdown(f"## 📰 {display_name}")

    query = quote(f"{symbol} {stock_name}")

    rss_url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    try:

        rss_res = requests.get(
            rss_url,
            headers={"User-Agent":"Mozilla/5.0"},
            timeout=5
        )

        feed = feedparser.parse(rss_res.content)

        articles = feed.entries[:10]

        for i, art in enumerate(articles, start=1):

            st.markdown(
                f"""
                <div class='card' style='margin-bottom:10px;'>

                <a href="{art.link}"
                   target="_blank"
                   style="color:white;
                          font-size:18px;
                          text-decoration:none;">

                {i}. {art.title}

                </a>

                </div>
                """,
                unsafe_allow_html=True
            )

    except Exception as e:

        st.error(f"新聞載入失敗：{e}")

# =========================
# 底部庫存
# =========================
st.markdown("---")

pnl_color = "#ff3b3b" if profit > 0 else "#00e676"

st.markdown(
    f"""
    <div class='card'>

    <h3>💰 庫存狀態</h3>

    <p>{display_name}</p>

    <p>
    現價：
    <span style='color:{price_color(curr, prev_c)};
                 font-size:24px;
                 font-weight:bold;'>

    {curr:.2f}

    </span>
    </p>

    <p>
    漲跌：
    <span style='color:{price_color(curr, prev_c)}'>
    {diff:+.2f} ({pct:+.2f}%)
    </span>
    </p>

    <h2 style='color:{pnl_color};'>
    損益：{int(profit):,} 元
    </h2>

    </div>
    """,
    unsafe_allow_html=True
)
