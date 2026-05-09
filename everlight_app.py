# Streamlit Cloud Secrets 設定參考：
# FINMIND_TOKEN = "你的 FinMind Token"
# FUGLE_TOKEN = "你的 Fugle Token"
# ADMIN_PASSWORD = "你自訂的後台密碼"

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import os
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

# =====================
# 頁面設定
# =====================
st.set_page_config(
    page_title="台股戰情室",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

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
.fin-table th{background:#222; color:#fff; padding:10px; border-bottom:2px solid #444; text-align:left;}
.fin-table td{padding:10px; border-bottom:1px solid #333; color:#ddd; vertical-align:middle;}
.fin-table tr:hover td{background:#1a1a1a;}
::-webkit-scrollbar {width: 6px; height: 6px;}
::-webkit-scrollbar-track {background: transparent;}
::-webkit-scrollbar-thumb {background: #444; border-radius: 3px;}
::-webkit-scrollbar-thumb:hover {background: #666;}
</style>
""", unsafe_allow_html=True)

# =====================
# Token 讀取：本機 / Streamlit Cloud 皆可用
# =====================
def read_secret_safe(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return default

def read_file_safe(path):
    try:
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""

def find_local_token(filename):
    """本機測試用：自動搜尋目前資料夾、程式所在資料夾、使用者 Documents。"""
    candidates = [
        Path.cwd() / filename,
        Path(__file__).resolve().parent / filename,
        Path.home() / "Documents" / filename,
        Path.home() / "文件" / filename,
    ]
    for p in candidates:
        token = read_file_safe(p)
        if token:
            return token
    return ""

FINMIND_TOKEN = read_secret_safe("FINMIND_TOKEN", "") or find_local_token("finmind_token.txt")
FUGLE_TOKEN = read_secret_safe("FUGLE_TOKEN", "") or find_local_token("fugle_token.txt")

# 本機測試防呆：如果讀不到 finmind_token.txt，就在網頁上手動貼一次測試
if not FINMIND_TOKEN:
    FINMIND_TOKEN = st.sidebar.text_input(
        "🔑 FinMind Token（本機測試用）",
        value="",
        type="password",
        help="本機讀不到 finmind_token.txt 時，先貼在這裡測試。上雲端後改用 Streamlit Secrets。"
    ).strip()

# =====================
# 股票字典 (三層備援)
# =====================
@st.cache_data(ttl=86400)
def load_market_dict():
    market_dict = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=headers, timeout=5)
        if r.status_code == 200:
            for i in r.json():
                market_dict[i["Code"]] = i["Name"]
                market_dict[i["Name"]] = i["Code"]
    except Exception as e:
        print("TWSE OpenAPI 載入失敗:", e)

    try:
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers=headers, timeout=5)
        if r2.status_code == 200:
            for i in r2.json():
                c = i.get("SecuritiesCompanyCode") or i.get("Code")
                n = i.get("CompanyName") or i.get("Name")
                if c and n:
                    market_dict[c] = n
                    market_dict[n] = c
    except Exception as e:
        print("TPEX OpenAPI 載入失敗:", e)

    if len(market_dict) < 1000:
        try:
            r_twse = requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", headers=headers, timeout=10)
            for _, row in pd.read_html(r_twse.text)[0].iterrows():
                parts = str(row[0]).strip().replace("　", " ").split(maxsplit=1)
                if len(parts) == 2 and parts[0].isalnum():
                    market_dict[parts[0]] = parts[1].strip()
                    market_dict[parts[1].strip()] = parts[0]
        except Exception as e:
            print("上市 ISIN 載入失敗:", e)
        try:
            r_tpex = requests.get("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", headers=headers, timeout=10)
            for _, row in pd.read_html(r_tpex.text)[0].iterrows():
                parts = str(row[0]).strip().replace("　", " ").split(maxsplit=1)
                if len(parts) == 2 and parts[0].isalnum():
                    market_dict[parts[0]] = parts[1].strip()
                    market_dict[parts[1].strip()] = parts[0]
        except Exception as e:
            print("上櫃 ISIN 載入失敗:", e)

    for k, v in {
        "0050":"元大台灣50", "0056":"元大高股息", "006208":"富邦台50",
        "00713":"元大高息低波", "00757":"統一FANG+", "00679B":"元大美債20年",
        "00878":"國泰永續高股息", "00919":"群益台灣精選高息", "00929":"復華台灣科技優息",
        "00940":"元大台灣價值高息", "1711":"永光", "2330":"台積電", "2454":"聯發科",
        "2317":"鴻海", "2313":"華通", "2603":"長榮", "2618":"長榮航"
    }.items():
        market_dict[k] = v
        market_dict[v] = k
    return market_dict

MASTER_DICT = load_market_dict()
INDUSTRY_BACKUP = {
    "2330":"半導體業", "2317":"其他電子業", "2454":"半導體業", "2603":"航運業",
    "2618":"航運業", "1711":"化學工業", "2313":"電子零組件業", "0050":"ETF",
    "0056":"ETF", "00878":"ETF", "00919":"ETF", "00679B":"債券ETF"
}

# =====================
# 頂部控制列
# =====================
c1, c2, c3, c4 = st.columns([3, 2, 1.5, 2.5])

with c1:
    page = st.radio(
        "📌 頁面切換",
        ["📊 K線分析", "⚡ 即時趨勢", "🤖 AI綜合預測", "📑 基本面分析", "🧩 籌碼分析", "🎯 操作策略","🔐 管理後台"],
        horizontal=True
    )

with c2:
    stock_input = st.text_input("🔍 股票代號 / 中文名稱", value="1711").replace(".TW","").replace(".TWO","").replace(".tw","").replace(".two","").strip().upper()
    symbol, stock_name = stock_input, stock_input

    if stock_input in MASTER_DICT:
        if stock_input.isdigit() or stock_input.endswith("B"):
            symbol = stock_input
            stock_name = MASTER_DICT.get(symbol, symbol)
        else:
            symbol = MASTER_DICT.get(stock_input, stock_input)
            stock_name = stock_input
    else:
        exact, fuzzy = None, None
        for k, v in MASTER_DICT.items():
            if isinstance(v, str):
                if stock_input == v:
                    exact = (k, v)
                    break
                elif stock_input in v and not fuzzy:
                    fuzzy = (k, v)
        if exact:
            symbol, stock_name = exact
        elif fuzzy:
            symbol, stock_name = fuzzy

    display_name = f"{symbol} {stock_name}"
    
# =====================
# 使用者查詢紀錄
# =====================
LOG_FILE = "visitor_stock_log.jsonl"

if "visitor_id" not in st.session_state:
    st.session_state["visitor_id"] = str(uuid.uuid4())[:8]

def log_stock_view(page, symbol, stock_name, tf_label=""):
    try:
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "visitor_id": st.session_state.get("visitor_id", "unknown"),
            "page": page,
            "symbol": symbol,
            "stock_name": stock_name,
            "tf_label": tf_label
        }

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    except Exception:
        pass

tf_map = {
    "1分K": "1m",
    "3分K": "3m_custom",
    "5分K": "5m",
    "15分K": "15m",
    "30分K": "30m",
    "60分K": "60m",
    "日K": "1d",
    "週K": "1wk",
    "月K": "1mo",
}

period_map = {
    "1分K": "5d",
    "3分K": "5d",
    "5分K": "60d",
    "15分K": "60d",
    "30分K": "60d",
    "60分K": "730d",
    "日K": "1y",
    "週K": "5y",
    "月K": "10y",
}

time_unit_map = {
    "1分K": "1分線",
    "3分K": "3分線",
    "5分K": "5分線",
    "15分K": "15分線",
    "30分K": "30分線",
    "60分K": "60分線",
    "日K": "日線",
    "週K": "週線",
    "月K": "月線",
}

# 預設值，避免其他頁面報錯
tf_label = "日K"
show_ma5 = show_ma10 = show_ma20 = True
qty = 1.0
cost = 50.0

with c3:
    if page == "📊 K線分析":
        tf_label = st.selectbox(
            "📈 K線週期",
            ["1分K", "3分K", "5分K", "15分K", "30分K", "60分K", "日K", "週K", "月K"],
            index=6
        )

        ma1, ma2, ma3 = st.columns(3)
        with ma1:
            show_ma5 = st.checkbox("5線", True)
        with ma2:
            show_ma10 = st.checkbox("10線", True)
        with ma3:
            show_ma20 = st.checkbox("20線", True)

tf = tf_map[tf_label]
period = period_map[tf_label]
time_unit = time_unit_map[tf_label]

if page != "🔐 管理後台":
    current_log_key = f"{page}|{symbol}|{stock_name}|{tf_label}"

    if st.session_state.get("last_log_key") != current_log_key:
        log_stock_view(
            page=page,
            symbol=symbol,
            stock_name=stock_name,
            tf_label=tf_label
        )
        st.session_state["last_log_key"] = current_log_key

# 隱藏 FUGLE_TOKEN 輸入，直接帶入 Secret
api_key = FUGLE_TOKEN

if page == "📊 K線分析":
    with c4:
        p1, p2 = st.columns(2)
        with p1:
            qty = st.number_input("📦 持股張數", value=1.0, min_value=0.0, step=1.0)
        with p2:
            cost = st.number_input("💰 平均成本", value=50.0, min_value=0.0, step=0.1)

# 關閉自動刷新，避免 Streamlit 前端 removeChild 錯誤
if st.button("🔄 手動刷新"):
    st.rerun()

# =====================
# 資料擷取引擎
# =====================
def flatten_columns(df):
    if not df.empty and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=30)
def fetch_history(symbol, period, interval):
    download_interval = "1m" if interval == "3m_custom" else interval

    df = flatten_columns(
        yf.download(
            f"{symbol}.TW",
            period=period,
            interval=download_interval,
            progress=False,
            threads=False,
            auto_adjust=False
        )
    )
    suffix = ".TW"

    if df.empty:
        df = flatten_columns(
            yf.download(
                f"{symbol}.TWO",
                period=period,
                interval=download_interval,
                progress=False,
                threads=False,
                auto_adjust=False
            )
        )
        suffix = ".TWO"

    if df.empty:
        return df, suffix

    df = df.dropna(subset=["Open", "High", "Low", "Close"])

    # 3分K：用 1分K 重新合成
    if interval == "3m_custom":
        agg = {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }

        if "Adj Close" in df.columns:
            agg["Adj Close"] = "last"

        df = df.resample("3min").agg(agg)
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

    minute_intervals = ["1m", "3m_custom", "5m", "15m", "30m", "60m"]

    if interval in minute_intervals:
        df = df.tail(300)
    else:
        df = df.tail(500)

    return df, suffix

@st.cache_data(ttl=10)
def fetch_intraday(symbol, suffix):
    """
    取得最近一個有 1 分 K 資料的交易日。
    收盤後、晚上、假日也保留最近交易日盤中走勢，不讓即時走勢變空白。
    """
    df_i = flatten_columns(
        yf.download(
            f"{symbol}{suffix}",
            period="5d",
            interval="1m",
            progress=False,
            threads=False,
            auto_adjust=False
        )
    )

    if df_i.empty:
        return df_i

    df_i = df_i.dropna(subset=["Close"])

    if df_i.empty:
        return df_i

    # 轉成台灣時間
    df_i.index = (
        df_i.index.tz_convert("Asia/Taipei")
        if df_i.index.tz
        else df_i.index.tz_localize("Asia/Taipei")
    )

    # 排序，避免資料順序亂掉
    df_i = df_i.sort_index()

    # 只保留最近一個「有資料」的交易日
    latest_trade_date = df_i.index.date.max()
    df_i = df_i[df_i.index.date == latest_trade_date]

    return df_i


def resample_ohlcv(df, rule):
    """
    將 1分K 重新合成 3分K / 5分K / 15分K / 30分K / 60分K。
    會補齊沒有成交的空白K：
    Open / High / Low / Close = 前一根 Close
    Volume = 0
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    # 確保 index 是 datetime
    idx = pd.to_datetime(df.index, errors="coerce")

    # 如果還有時區，轉台灣時間後移除時區
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("Asia/Taipei").tz_localize(None)

    df.index = idx
    df = df[~df.index.isna()].sort_index()

    # 確保 OHLCV 是數字
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace(" ", "", regex=False)
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close"])

    if df.empty:
        return df

    # 只保留台股盤中時間
    df = df.between_time("09:00", "13:30")

    if df.empty:
        return df

    all_sessions = []

    # 逐日處理，避免跨日補出夜盤空白K
    for trade_date, day_df in df.groupby(df.index.date):
        day_df = day_df.sort_index()

        if day_df.empty:
            continue

        # 依指定週期重新合成K棒，從每天 09:00 對齊
        resampled = day_df.resample(
            rule,
            origin="start_day",
            offset="9h"
        ).agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        })

        # 建立該交易日完整時間軸
        start_time = pd.Timestamp(trade_date).replace(hour=9, minute=0)
        end_time = pd.Timestamp(trade_date).replace(hour=13, minute=30)

        full_index = pd.date_range(
            start=start_time,
            end=end_time,
            freq=rule
        )

        resampled = resampled.reindex(full_index)

        # 先用前一根 Close 補 Close
        resampled["Close"] = resampled["Close"].ffill()

        # 沒成交的K棒，用前一根 Close 補 OHLC
        resampled["Open"] = resampled["Open"].fillna(resampled["Close"])
        resampled["High"] = resampled["High"].fillna(resampled["Close"])
        resampled["Low"] = resampled["Low"].fillna(resampled["Close"])
        resampled["Volume"] = resampled["Volume"].fillna(0)

        # 如果當天最前面沒有任何價格，刪掉
        resampled = resampled.dropna(subset=["Open", "High", "Low", "Close"])

        all_sessions.append(resampled)

    if not all_sessions:
        return df

    result = pd.concat(all_sessions).sort_index()

    return result

@st.cache_data(ttl=3600)
def fetch_fundamentals(symbol, suffix):
    try:
        t = yf.Ticker(f"{symbol}{suffix}")
        info = t.info
    except Exception:
        info = {}
        t = None

    try:
        fin = t.financials if t is not None else pd.DataFrame()
        fin = fin.T.sort_index() if fin is not None and not fin.empty else pd.DataFrame()
    except Exception:
        fin = pd.DataFrame()

    return info, fin

@st.cache_data(ttl=3600)
def fetch_monthly_revenue(symbol, finmind_token):
    res_df = pd.DataFrame()
    if not finmind_token:
        return res_df

    try:
        headers = {"Authorization": f"Bearer {finmind_token}"}
        # 為了計算 YoY，至少需要 24 個月資料
        start_date = (datetime.now() - timedelta(days=800)).strftime("%Y-%m-%d")

        params = {
            "dataset": "TaiwanStockMonthRevenue",
            "data_id": str(symbol),
            "start_date": start_date,
            "token": finmind_token,
        }

        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params=params,
            headers=headers,
            timeout=10
        )

        if r.status_code == 200:
            data = r.json().get("data", [])

            if data:
                df = pd.DataFrame(data)

                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")

                df = df.dropna(subset=["date", "revenue"])
                df = df.sort_values("date", ascending=True).reset_index(drop=True)

                df["營收（億元台幣）"] = df["revenue"] / 1e8
                df["月增率 MoM"] = df["revenue"].pct_change(1) * 100
                df["年增率 YoY"] = df["revenue"].pct_change(12) * 100

                df["月增率 MoM"] = df["月增率 MoM"].fillna(0)
                df["年增率 YoY"] = df["年增率 YoY"].fillna(0)

                df["月份"] = df["date"].dt.strftime("%Y/%m")

                res_df = df[
                    ["月份", "營收（億元台幣）", "月增率 MoM", "年增率 YoY"]
                ].tail(12)

                res_df = res_df.iloc[::-1].reset_index(drop=True)

    except Exception as e:
        print("月營收錯誤:", e)

    return res_df


@st.cache_data(ttl=3600)
def fetch_institutional_chips(symbol, finmind_token):
    res_df = pd.DataFrame()

    if not finmind_token:
        return res_df

    try:
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        url = "https://api.finmindtrade.com/api/v4/data"

        params = {
            "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
            "data_id": str(symbol),
            "start_date": start_date,
            "token": finmind_token,
        }

        r = requests.get(url, params=params, timeout=10)

        if r.status_code != 200:
            print(f"三大法人 API 異常! 狀態碼: {r.status_code}, 回傳內容: {r.text}")
            return res_df

        json_data = r.json()
        data = json_data.get("data", [])

        if not data:
            print(f"三大法人 API 回傳無資料! JSON: {json_data}")
            return res_df

        df = pd.DataFrame(data)

        if "date" not in df.columns:
            return res_df

        if "name" not in df.columns:
            return res_df

        if "buy_sell" in df.columns:
            df["net"] = pd.to_numeric(df["buy_sell"], errors="coerce")
        elif "buy" in df.columns and "sell" in df.columns:
            df["net"] = (
                pd.to_numeric(df["buy"], errors="coerce")
                - pd.to_numeric(df["sell"], errors="coerce")
            )
        elif "buy_volume" in df.columns and "sell_volume" in df.columns:
            df["net"] = (
                pd.to_numeric(df["buy_volume"], errors="coerce")
                - pd.to_numeric(df["sell_volume"], errors="coerce")
            )
        else:
            return res_df

        df["net"] = df["net"].fillna(0)

        if not df.empty and df["net"].abs().max() > 500000:
            df["net"] = df["net"] / 1000

        def classify_name(n):
            n_str = str(n).strip()
            n_low = n_str.lower()

            if ("外資" in n_str or "外陸資" in n_str or "foreign" in n_low or "foreign_investor" in n_low or "foreign investor" in n_low):
                return "外資"
            if ("投信" in n_str or "investment_trust" in n_low or "investment trust" in n_low or "trust" in n_low):
                return "投信"
            if ("自營商" in n_str or "dealer" in n_low or "dealer_self" in n_low or "dealer_hedging" in n_low):
                return "自營商"
            return "其他"

        df["type"] = df["name"].apply(classify_name)

        df = df[df["type"] != "其他"]

        if df.empty:
            return res_df

        pivot_df = (
            df.groupby(["date", "type"])["net"]
            .sum()
            .unstack(fill_value=0)
            .reset_index()
        )

        for col in ["外資", "投信", "自營商"]:
            if col not in pivot_df.columns:
                pivot_df[col] = 0

        pivot_df["合計"] = pivot_df["外資"] + pivot_df["投信"] + pivot_df["自營商"]

        res_df = (
            pivot_df[["date", "外資", "投信", "自營商", "合計"]]
            .sort_values("date", ascending=True)
            .tail(20)
            .reset_index(drop=True)
        )

    except Exception as e:
        print("三大法人處理發生錯誤:", e)

    return res_df

@st.cache_data(ttl=3600)
def fetch_margin_chips(symbol, finmind_token):
    res_df = pd.DataFrame()

    if not finmind_token:
        return res_df

    try:
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        url = "https://api.finmindtrade.com/api/v4/data"

        params = {
            "dataset": "TaiwanStockMarginPurchaseShortSale",
            "data_id": str(symbol),
            "start_date": start_date,
            "token": finmind_token,
        }

        r = requests.get(url, params=params, timeout=10)

        if r.status_code != 200:
            print(f"融資融券 API 異常! 狀態碼: {r.status_code}, 回傳內容: {r.text}")
            return res_df

        json_data = r.json()
        data = json_data.get("data", [])

        if not data:
            print(f"融資融券 API 回傳無資料! JSON: {json_data}")
            return res_df

        df = pd.DataFrame(data)

        if "date" not in df.columns:
            return res_df

        df = df.sort_values("date", ascending=True)

        if "MarginPurchaseTodayBalance" not in df.columns or "ShortSaleTodayBalance" not in df.columns:
            return res_df

        df["融資餘額"] = pd.to_numeric(
            df["MarginPurchaseTodayBalance"],
            errors="coerce"
        ).fillna(0)

        df["融券餘額"] = pd.to_numeric(
            df["ShortSaleTodayBalance"],
            errors="coerce"
        ).fillna(0)

        df["融資增減"] = df["融資餘額"].diff().fillna(0)
        df["融券增減"] = df["融券餘額"].diff().fillna(0)

        res_df = (
            df[["date", "融資餘額", "融券餘額", "融資增減", "融券增減"]]
            .tail(20)
            .reset_index(drop=True)
        )

    except Exception as e:
        print("融資融券處理發生錯誤:", e)

    return res_df

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

    except Exception:
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
            d = r.json()
            return d if isinstance(d, list) else d.get("data", d.get("trades", []))

    except Exception:
        pass

    return []


def price_color(price, prev_c):
    if price == 0 or prev_c == 0:
        return "#fff"
    return "#ff3b3b" if price > prev_c else "#00e676" if price < prev_c else "#fff"


def format_trade_time(raw_time):
    try:
        r = str(raw_time).strip()
        if r.isdigit():
            return datetime.fromtimestamp(float(r) / (10 ** (len(r) - 10)) if len(r) > 10 else float(r), tz=timezone(timedelta(hours=8))).strftime("%H:%M:%S")
        return r.split("T")[-1].split(".")[0] if "T" in r else r.split(".")[0]
    except Exception:
        return str(raw_time)[:8]


def donut_chart(title, value, label, color):
    value = max(0, min(100, int(value)))
    fig = go.Figure(data=[go.Pie(values=[value, 100 - value], hole=0.72, textinfo="none", sort=False, marker=dict(colors=[color, "#222"]))])
    fig.update_layout(template="plotly_dark", height=260, margin=dict(l=5, r=5, t=40, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", title=dict(text=title, x=0.5, font=dict(size=20, color="#fff")), annotations=[dict(text=f"<b>{value}%</b><br>{label}", x=0.5, y=0.5, showarrow=False, font=dict(size=24, color="#fff"))])
    return fig

def render_order_book(bids, asks, prev_c, curr, api_key):
    if not api_key:
        st.warning("⚠️ 未設定 FUGLE_TOKEN，無法取得即時五檔資料。")
        return
    if not bids and not asks:
        st.info("📡 五檔尚未連線或非盤中時間")
        return
    all_vols = [x.get("size", 0) for x in bids + asks]
    max_v = max(all_vols) if all_vols else 1
    buy5, sell5 = bids[:5], asks[:5]
    rows = ""
    for i in range(5):
        bp, bs = buy5[i].get("price", 0) if i < len(buy5) else 0, buy5[i].get("size", 0) if i < len(buy5) else 0
        ap, as_ = sell5[i].get("price", 0) if i < len(sell5) else 0, sell5[i].get("size", 0) if i < len(sell5) else 0
        bw, aw = int((bs / max_v) * 100) if max_v else 0, int((as_ / max_v) * 100) if max_v else 0
        bc, ac = price_color(bp, prev_c) if bp > 0 else "#777", price_color(ap, prev_c) if ap > 0 else "#777"
        rows += f"<tr><td style='width:55px; text-align:right; color:#aaa;'>{bs if bs>0 else ''}</td><td style='width:170px;'><div class='bar-bg'><div class='buy-bar' style='width:{bw}%;'></div></div></td><td class='order-price' style='width:85px; text-align:right; color:{bc};'>{f'{bp:.2f}' if bp>0 else '--'}</td><td style='width:55px; text-align:center; color:#555;'>│</td><td class='order-price' style='width:85px; text-align:left; color:{ac};'>{f'{ap:.2f}' if ap>0 else '--'}</td><td style='width:170px;'><div class='bar-bg'><div class='sell-bar' style='width:{aw}%;'></div></div></td><td style='width:55px; text-align:left; color:#aaa;'>{as_ if as_>0 else ''}</td></tr>"
    st.markdown(f"<div style='background:#050505; padding:12px; border-radius:10px; border:1px solid #222;'><div style='text-align:center; color:#ffcc00; font-size:20px; font-weight:bold; margin-bottom:8px;'>現價 {curr:.2f}</div><table class='order-table'><thead><tr><th>買量</th><th></th><th>買價</th><th></th><th>賣價</th><th></th><th>賣量</th></tr></thead><tbody>{rows}</tbody></table></div>", unsafe_allow_html=True)


def render_trade_details(trades, prev_c, api_key):
    if not api_key:
        st.warning("⚠️ 未設定 FUGLE_TOKEN，無法取得成交明細。")
        return
    if not trades:
        st.info("📡 尚無成交明細資料。")
        return
    rows = ""
    for t in trades[:60]:
        try:
            p = float(t.get("price", t.get("tradePrice", 0)) or 0)
        except Exception:
            p = 0
        try:
            s = int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
        except Exception:
            s = 0
        rows += f"<tr><td>{format_trade_time(t.get('time', t.get('at', t.get('date', ''))))}</td><td style='color:{price_color(p, prev_c)}; font-weight:bold; text-align:right;'>{p:.2f}</td><td style='text-align:right;'>{s}</td></tr>"
    st.markdown(f"<div class='card' style='padding:0;'><div style='max-height:320px; overflow-y:auto; padding:15px;'><table class='fin-table'><thead style='position:sticky; top:-15px; z-index:2;'><tr><th>時間</th><th style='text-align:right;'>成交價</th><th style='text-align:right;'>成交量</th></tr></thead><tbody>{rows}</tbody></table></div></div>", unsafe_allow_html=True)


def render_volume_summary(bids, asks, trades, df_i, prev_c):
    st.markdown("### 📊 委託 / 成交量統計")
    bid_total, ask_total = sum(x.get("size", 0) for x in bids), sum(x.get("size", 0) for x in asks)
    price_vol = {}
    for t in trades:
        try:
            p, s = float(t.get("price", t.get("tradePrice", 0)) or 0), int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
            if p > 0 and s > 0:
                price_vol[p] = price_vol.get(p, 0) + s
        except Exception:
            continue
    trade_total = sum(price_vol.values()) or (int(df_i["Volume"].sum()) if not df_i.empty and "Volume" in df_i.columns else 0)
    bid_pct = (bid_total / (bid_total + ask_total) * 100) if (bid_total + ask_total) else 0
    ask_pct = (ask_total / (bid_total + ask_total) * 100) if (bid_total + ask_total) else 0

    st.markdown(f"<div class='card'><div style='display:flex; gap:14px;'><div style='flex:1; text-align:center;'><div style='color:#aaa;'>委託買量</div><div style='font-size:28px; color:#ff3b3b; font-weight:bold;'>{bid_total:,}</div><div style='color:#888; font-size:12px;'>{bid_pct:.1f}%</div></div><div style='flex:1; text-align:center;'><div style='color:#aaa;'>委託賣量</div><div style='font-size:28px; color:#00e676; font-weight:bold;'>{ask_total:,}</div><div style='color:#888; font-size:12px;'>{ask_pct:.1f}%</div></div><div style='flex:1; text-align:center;'><div style='color:#aaa;'>總成交量</div><div style='font-size:28px; color:#ffcc00; font-weight:bold;'>{int(trade_total):,}</div><div style='color:#888; font-size:12px;'>今日累計</div></div></div><div style='margin-top:16px;'><div style='height:14px; background:#1a1a1a; border-radius:4px; display:flex; overflow:hidden;'><div style='width:{bid_pct}%; background:#ff3b3b;'></div><div style='width:{ask_pct}%; background:#00e676;'></div></div><div style='display:flex; justify-content:space-between; color:#aaa; margin-top:6px; font-size:12px;'><span>委買佔比</span><span>委賣佔比</span></div></div></div>", unsafe_allow_html=True)

    st.markdown("### 📈 今日成交價量分布（低 → 高）")
    if not price_vol:
        st.info("📡 尚無逐價成交量資料。")
        return
    max_v, rows = max(price_vol.values()), ""
    for p in sorted(price_vol.keys()):
        rows += f"<tr><td style='color:{price_color(p, prev_c)}; font-weight:bold; text-align:right;'>{p:.2f}</td><td style='width:70%;'><div style='height:16px; background:#1a1a1a; border-radius:3px;'><div style='height:16px; width:{int((price_vol[p]/max_v)*100)}%; background:#ffcc00; border-radius:3px;'></div></div></td><td style='text-align:right;'>{price_vol[p]}</td></tr>"
    st.markdown(f"<div class='card' style='padding:0; margin-top:12px;'><div style='max-height:320px; overflow-y:auto; padding:15px;'><table class='fin-table'><thead style='position:sticky; top:-15px; z-index:2;'><tr><th style='text-align:right;'>價格</th><th style='text-align:center;'>量條</th><th style='text-align:right;'>成交量</th></tr></thead><tbody>{rows}</tbody></table></div></div>", unsafe_allow_html=True)

# =====================
# 主資料處理
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

bids, asks = q.get("bids") or [], q.get("asks") or []
trades = fetch_fugle_trades(symbol, api_key) or []
profit = (curr - cost) * qty * 1000
diff, pct = curr - prev_c, ((curr - prev_c) / prev_c * 100) if prev_c else 0
df_i_for_summary = fetch_intraday(symbol, suffix)

# =====================
# 📊 K線分析
# =====================
if page == "📊 K線分析":

    st.markdown("""
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(0, 229, 255, 0.14), transparent 28%),
            radial-gradient(circle at top right, rgba(168, 85, 247, 0.14), transparent 30%),
            linear-gradient(135deg, #020617 0%, #030712 45%, #050816 100%);
        color: #e5e7eb;
    }

    .block-container {
        max-width: 1680px;
        padding-top: 1.2rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    .stock-hero {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 28px 30px;
        margin: 10px 0 18px 0;
        border-radius: 22px;
        background: linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.98));
        border: 1px solid rgba(56, 189, 248, 0.35);
        box-shadow: 0 0 30px rgba(56, 189, 248, 0.12);
    }

    .stock-title {
        font-size: 38px;
        font-weight: 900;
        color: #f8fafc;
    }

    .stock-subtitle {
        margin-top: 6px;
        font-size: 15px;
        color: #94a3b8;
    }

    .stock-price {
        text-align: right;
    }

    .price-main {
        font-size: 38px;
        font-weight: 900;
        color: #fb7185;
    }

    .price-sub {
        font-size: 13px;
        color: #94a3b8;
    }

    .card {
        padding: 18px 20px;
        border-radius: 18px;
        background: linear-gradient(145deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.96));
        border: 1px solid rgba(148, 163, 184, 0.18);
        box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.06),
            0 0 22px rgba(15, 23, 42, 0.8);
    }

    .card:hover {
        border-color: rgba(56, 189, 248, 0.55);
        box-shadow: 0 0 28px rgba(56, 189, 248, 0.18);
    }

    hr {
        border-color: rgba(148, 163, 184, 0.15);
    }

    /* =====================
       📱 手機版 RWD
    ===================== */
    @media (max-width: 768px) {

        .block-container {
            max-width: 100% !important;
            padding-left: 0.65rem !important;
            padding-right: 0.65rem !important;
            padding-top: 1.2rem !important;
        }

        .stock-hero {
            flex-direction: column;
            align-items: flex-start;
            gap: 12px;
            padding: 16px 16px;
            border-radius: 18px;
            margin: 6px 0 14px 0;
        }

        .stock-title {
            font-size: 25px;
            line-height: 1.25;
        }

        .stock-subtitle {
            font-size: 13px;
            line-height: 1.5;
        }

        .stock-price {
            width: 100%;
            text-align: left;
            padding-top: 10px;
            border-top: 1px solid rgba(148, 163, 184, 0.18);
        }

        .price-main {
            font-size: 32px;
            line-height: 1.1;
        }

        .price-sub {
            font-size: 12px;
        }

        .card {
            padding: 14px 14px;
            border-radius: 16px;
            margin-bottom: 10px;
        }

        div[data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
        }

        div[data-testid="stHorizontalBlock"] {
            gap: 0.5rem !important;
        }

        div[data-testid="stSelectbox"],
        div[data-testid="stMultiSelect"],
        div[data-testid="stNumberInput"] {
            width: 100% !important;
        }

        .js-plotly-plot {
            min-height: 420px !important;
        }

        table {
            font-size: 12px !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)
    
    hero_price = curr if curr is not None and not pd.isna(curr) else df["Close"].iloc[-1]
    
    st.markdown(f"""
    <div class="stock-hero">
        <div>
            <div class="stock-title">📊 {display_name}</div>
            <div class="stock-subtitle">K線分析・技術指標・趨勢判讀</div>
        </div>
        <div class="stock-price">
            <div class="price-main">{hero_price:.2f}</div>
            <div class="price-sub">即時價格</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    # ✅ K線圖操作模式：手機滑動 / 電腦互動
    chart_mode = st.radio(
        "📱 圖表操作模式",
        ["手機滑動優先", "電腦互動模式"],
        index=0,
        horizontal=True,
        help="手機滑動優先：比較好往下滑；電腦互動模式：可拖動K線與畫線。"
    )

    k_col1, k_col2 = st.columns(2)
    with k_col1:
        k_range = st.selectbox(
            "📏 K線顯示範圍",
            [f"還原{time_unit}", "最近50根", "最近100根", "最近150根", "最近200根", "最近300根"],
            index=3
        )
    with k_col2:
        tech_inds = st.multiselect("📈 技術指標", ["KD", "MACD", "RSI", "布林通道"])
   
    if df is None or df.empty:
        st.warning(f"⚠️ 目前 {tf_label} 沒有取得 K線資料，請切換週期或重新整理。")
        st.stop()

    df = df.copy()

    idx = pd.to_datetime(df.index, errors="coerce")

    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("Asia/Taipei").tz_localize(None)

    df.index = idx
    df = df[~df.index.isna()].sort_index()
    
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close"])

    if df.empty:
        st.warning(f"⚠️ {tf_label} 資料格式轉換後沒有可顯示的 K線資料。")
        st.stop()
        
    intraday_resample_map = {
        "3分K": "3min",
        "5分K": "5min",
        "15分K": "15min",
        "30分K": "30min",
        "60分K": "60min",
    }

    if tf_label in intraday_resample_map:
        df = resample_ohlcv(df, intraday_resample_map[tf_label])

    df_calc = df.copy()

    df_calc['MA5'] = df_calc['Close'].rolling(5).mean()
    df_calc['MA10'] = df_calc['Close'].rolling(10).mean()
    df_calc['MA20'] = df_calc['Close'].rolling(20).mean()

    df_calc['9H'] = pd.to_numeric(df_calc['High'], errors="coerce").rolling(9).max()
    df_calc['9L'] = pd.to_numeric(df_calc['Low'], errors="coerce").rolling(9).min()

    rsv_den = (df_calc['9H'] - df_calc['9L']).replace(0, float("nan"))

    df_calc['RSV'] = (
        (pd.to_numeric(df_calc['Close'], errors="coerce") - df_calc['9L']) 
        / rsv_den 
        * 100
    )

    df_calc['RSV'] = pd.to_numeric(df_calc['RSV'], errors="coerce")
    df_calc['K'] = df_calc['RSV'].ewm(com=2, adjust=False).mean()
    df_calc['D'] = df_calc['K'].ewm(com=2, adjust=False).mean()

    df_calc['EMA12'] = df_calc['Close'].ewm(span=12, adjust=False).mean()
    df_calc['EMA26'] = df_calc['Close'].ewm(span=26, adjust=False).mean()
    df_calc['DIF'] = df_calc['EMA12'] - df_calc['EMA26']
    df_calc['MACD'] = df_calc['DIF'].ewm(span=9, adjust=False).mean()
    df_calc['OSC'] = df_calc['DIF'] - df_calc['MACD']

    delta = df_calc['Close'].diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df_calc['RSI'] = 100 - (100 / (1 + rs))

    df_calc['STD20'] = df_calc['Close'].rolling(20).std()
    df_calc['BB_UP'] = df_calc['MA20'] + 2 * df_calc['STD20']
    df_calc['BB_DN'] = df_calc['MA20'] - 2 * df_calc['STD20']

    if k_range.startswith("還原"):
        df_k = df_calc.copy()
    else:
        range_map = {
            "最近50根": 50,
            "最近100根": 100,
            "最近150根": 150,
            "最近200根": 200,
            "最近300根": 300,
        }
        df_k = df_calc.tail(range_map[k_range]).copy()

    st.markdown("---")
    if not df_k.empty:
        high_val = df_k["High"].max()
        low_val = df_k["Low"].min()
        ma5_val = df_k["MA5"].iloc[-1]
        ma10_val = df_k["MA10"].iloc[-1]
        ma20_val = df_k["MA20"].iloc[-1]
    else:
        high_val = low_val = ma5_val = ma10_val = ma20_val = float('nan')

    def fmt_val(v):
        return f"{v:.2f}" if not pd.isna(v) else "N/A"

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(f"<div class='card' style='text-align:center; border-left:4px solid #ff3b3b;'><div style='color:#aaa; font-size:14px;'>最高價</div><div style='font-size:22px; font-weight:bold; color:#ff3b3b;'>{fmt_val(high_val)}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card' style='text-align:center; border-left:4px solid #00e676;'><div style='color:#aaa; font-size:14px;'>最低價</div><div style='font-size:22px; font-weight:bold; color:#00e676;'>{fmt_val(low_val)}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card' style='text-align:center; border-left:4px solid #FFD700;'><div style='color:#aaa; font-size:14px;'>MA5</div><div style='font-size:22px; font-weight:bold; color:#FFD700;'>{fmt_val(ma5_val)}</div></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='card' style='text-align:center; border-left:4px solid #00E5FF;'><div style='color:#aaa; font-size:14px;'>MA10</div><div style='font-size:22px; font-weight:bold; color:#00E5FF;'>{fmt_val(ma10_val)}</div></div>", unsafe_allow_html=True)
    c5.markdown(f"<div class='card' style='text-align:center; border-left:4px solid #FF66FF;'><div style='color:#aaa; font-size:14px;'>MA20</div><div style='font-size:22px; font-weight:bold; color:#FF66FF;'>{fmt_val(ma20_val)}</div></div>", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)

    extra_subplots = [ind for ind in ["KD", "MACD", "RSI"] if ind in tech_inds]
    num_extra = len(extra_subplots)

    row_heights = [5, 2] + [2] * num_extra
    fig = make_subplots(
        rows=2 + num_extra, 
        cols=1, 
        shared_xaxes=True, 
        row_heights=row_heights, 
        vertical_spacing=0.02
    )

    fig.add_trace(go.Candlestick(x=df_k.index, open=df_k["Open"], high=df_k["High"], low=df_k["Low"], close=df_k["Close"], name="K線", increasing_line_color="#ff3b3b", decreasing_line_color="#00e676", increasing_fillcolor="#ff3b3b", decreasing_fillcolor="#00e676"), row=1, col=1)
    if cost > 0 and not df_k.empty:
        price_high = df_k["High"].max()
        price_low = df_k["Low"].min()

        if price_low * 0.8 <= cost <= price_high * 1.2:
            fig.add_trace(
                go.Scatter(
                    x=df_k.index,
                    y=[cost] * len(df_k),
                    mode="lines",
                    name="成本線",
                    line=dict(color="cyan", width=2, dash="dash")
                ),
                row=1,
                col=1
            )
    fig.add_trace(go.Scatter(x=df_k.index, y=[curr] * len(df_k), mode="lines", name="現價線", line=dict(color="yellow", width=2, dash="dot")), row=1, col=1)
    
    if show_ma5:
        fig.add_trace(go.Scatter(x=df_k.index, y=df_k["MA5"], mode="lines", line=dict(color="#FFD700", width=1.5), name="MA5"), row=1, col=1)
    if show_ma10:
        fig.add_trace(go.Scatter(x=df_k.index, y=df_k["MA10"], mode="lines", line=dict(color="#00E5FF", width=1.5), name="MA10"), row=1, col=1)
    if show_ma20:
        fig.add_trace(go.Scatter(x=df_k.index, y=df_k["MA20"], mode="lines", line=dict(color="#FF66FF", width=1.5), name="MA20"), row=1, col=1)

    if "布林通道" in tech_inds:
        fig.add_trace(go.Scatter(x=df_k.index, y=df_k['BB_UP'], name="上軌", line=dict(color='rgba(255,255,255,0.4)', dash='dot')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_k.index, y=df_k['BB_DN'], name="下軌", line=dict(color='rgba(255,255,255,0.4)', dash='dot')), row=1, col=1)

    vol_colors = ["rgba(255,59,59,0.5)" if c >= o else "rgba(0,230,118,0.5)" for o, c in zip(df_k["Open"], df_k["Close"])]
    fig.add_trace(go.Bar(x=df_k.index, y=df_k["Volume"], name="成交量", marker_color=vol_colors), row=2, col=1)

    current_row = 3
    for ind in extra_subplots:
        if ind == "KD":
            fig.add_trace(go.Scatter(x=df_k.index, y=df_k['K'], name="K(9,3)", line=dict(color="yellow", width=1.5)), row=current_row, col=1)
            fig.add_trace(go.Scatter(x=df_k.index, y=df_k['D'], name="D(9,3)", line=dict(color="cyan", width=1.5)), row=current_row, col=1)
            fig.add_hline(y=80, line_dash="dash", line_color="rgba(255,255,255,0.3)", row=current_row, col=1)
            fig.add_hline(y=20, line_dash="dash", line_color="rgba(255,255,255,0.3)", row=current_row, col=1)
        elif ind == "MACD":
            fig.add_trace(go.Scatter(x=df_k.index, y=df_k['DIF'], name="DIF", line=dict(color="yellow", width=1.5)), row=current_row, col=1)
            fig.add_trace(go.Scatter(x=df_k.index, y=df_k['MACD'], name="MACD", line=dict(color="cyan", width=1.5)), row=current_row, col=1)
            osc_colors = ["#ff3b3b" if val >= 0 else "#00e676" for val in df_k['OSC']]
            fig.add_trace(go.Bar(x=df_k.index, y=df_k['OSC'], name="OSC", marker_color=osc_colors), row=current_row, col=1)
        elif ind == "RSI":
            fig.add_trace(go.Scatter(x=df_k.index, y=df_k['RSI'], name="RSI(14)", line=dict(color="yellow", width=1.5)), row=current_row, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="rgba(255,255,255,0.3)", row=current_row, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="rgba(255,255,255,0.3)", row=current_row, col=1)
        current_row += 1

    if tf == "1d":
        dt_obs = df_k.index.strftime("%Y-%m-%d").tolist()
        if len(dt_obs) > 0:
            dt_all = pd.date_range(start=df_k.index[0], end=df_k.index[-1]).strftime("%Y-%m-%d").tolist()
            fig.update_xaxes(rangebreaks=[dict(values=[d for d in dt_all if d not in dt_obs])])

    chart_height = 700 + 150 * num_extra
    
    is_intraday = tf_label in ["1分K", "3分K", "5分K", "15分K", "30分K", "60分K"]
    
    idx_dt = pd.to_datetime(df_k.index, errors="coerce")

    if isinstance(idx_dt, pd.DatetimeIndex):
        has_time = not ((idx_dt.hour == 0) & (idx_dt.minute == 0)).all()
    else:
        has_time = False
        
    if is_intraday and has_time:
        dt_format = "%m/%d<br>%H:%M"
    else:
        dt_format = "%Y/%m/%d"
        
    tickvals = None
    ticktext = None

    if is_intraday and has_time and len(df_k.index) > 0:
        tick_count = 8
        step = max(len(df_k.index) // tick_count, 1)
        tickvals = df_k.index[::step]

        ticktext = [
            t.strftime("%m/%d<br>%H:%M") if hasattr(t, "strftime") else str(t)
            for t in tickvals
        ]
    
    fig.update_layout(
        template="plotly_dark",
        height=chart_height,
        xaxis_rangeslider_visible=False,
        margin=dict(l=6, r=6, t=18, b=8),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(color="#cbd5e1", size=11)
        ),
        hovermode="x unified",
        paper_bgcolor="rgba(2, 6, 23, 0)",
        plot_bgcolor="rgba(2, 6, 23, 0.88)",
        dragmode=False if chart_mode == "手機滑動優先" else "pan",
        font=dict(color="#e5e7eb")
    )

    fig.update_xaxes(
        type="category" if is_intraday else "date",
        gridcolor="rgba(148, 163, 184, 0.10)",
        tickformat=dt_format,
        hoverformat=dt_format,
        zeroline=False,
        linecolor="rgba(148, 163, 184, 0.18)",
        nticks=8,
        tickangle=0,
        tickvals=tickvals,
        ticktext=ticktext,
        fixedrange=True if chart_mode == "手機滑動優先" else False
    )

    fig.update_yaxes(
        side="right",
        gridcolor="rgba(148, 163, 184, 0.10)",
        zeroline=False,
        linecolor="rgba(148, 163, 184, 0.18)",
        fixedrange=True if chart_mode == "手機滑動優先" else False
    )

    if chart_mode == "手機滑動優先":
        plot_config = {
            "scrollZoom": False,
            "displayModeBar": False,
            "displaylogo": False
        }
    else:
        plot_config = {
            "scrollZoom": False,
            "displayModeBar": True,
            "displaylogo": False,
            "modeBarButtonsToAdd": [
                "drawline",
                "eraseshape"
            ],
            "modeBarButtonsToRemove": [
                "select2d",
                "lasso2d",
                "autoScale2d"
            ]
        }

    st.plotly_chart(
        fig,
        use_container_width=True,
        config=plot_config
    )

    
        
# =====================
# ⚡ 即時趨勢
# =====================
elif page == "⚡ 即時趨勢":
    st.markdown(f"## ⚡ {display_name} 即時走勢")
    if not df_i_for_summary.empty:
        df_i = df_i_for_summary.copy()

        show_date = pd.to_datetime(df_i.index[-1]).strftime("%Y-%m-%d")
        st.caption(f"目前顯示最近交易日盤中走勢：{show_date}，收盤後會保留最後盤中線圖。")
        
        now_ts = pd.Timestamp.now(tz="Asia/Taipei").floor("min")
        if "High" not in df_i.columns:
            df_i["High"] = df_i["Close"]
        if "Low" not in df_i.columns:
            df_i["Low"] = df_i["Close"]
        df_plot = pd.concat([df_i, pd.DataFrame([[df_i["Open"].iloc[-1] if not df_i.empty else curr, curr, curr, curr, 0]], columns=["Open", "High", "Low", "Close", "Volume"], index=[now_ts])]).sort_index()
        df_plot = df_plot[~df_plot.index.duplicated(keep="last")]
        df_plot["VWAP"] = (df_plot["Close"] * df_plot["Volume"]).cumsum() / df_plot["Volume"].cumsum().replace(0, pd.NA)
        df_plot["VWAP"] = df_plot["VWAP"].bfill().fillna(df_plot["Close"])

        high_val, low_val = max(df_plot["High"].max(), curr), min(df_plot["Low"].min(), curr)
        amp_pct = ((high_val - low_val) / low_val) * 100 if low_val > 0 else 0

        buy_vol, sell_vol, v_colors, p_c = 0, 0, [], prev_c
        for _, r in df_plot.iterrows():
            c, v = r["Close"], r["Volume"] if not pd.isna(r["Volume"]) else 0
            if c >= p_c:
                buy_vol += v
                v_colors.append("rgba(255,59,59,0.8)")
            else:
                sell_vol += v
                v_colors.append("rgba(0,230,118,0.8)")
            p_c = c
        buy_pct = (buy_vol / (buy_vol + sell_vol) * 100) if (buy_vol + sell_vol) else 50
        sell_pct = 100 - buy_pct

        df_plot["VMA"] = df_plot["Volume"].rolling(10).mean().shift(1)

        surges = []
        buy_surge_streak = 0
        sell_surge_streak = 0
        gold_signal = ""

        prev_price_for_surge = prev_c

        for dt, r in df_plot.iterrows():
            vol = r["Volume"] if not pd.isna(r["Volume"]) else 0
            vma = r["VMA"] if not pd.isna(r["VMA"]) else 0
            close_price = r["Close"] if not pd.isna(r["Close"]) else 0
            vwap_price = r["VWAP"] if "VWAP" in df_plot.columns and not pd.isna(r["VWAP"]) else close_price

            if vol > 0 and vma > 0:
                ratio = vol / vma

                if close_price >= prev_price_for_surge:
                    direction = "buy"
                else:
                    direction = "sell"

                if ratio >= 2 and vol >= 300:
                    if direction == "buy":
                        buy_surge_streak += 1
                        sell_surge_streak = 0
                        surges.append(f"🚀 {dt.strftime('%H:%M')} 爆量買 {ratio:.1f} 倍")
                    else:
                        sell_surge_streak += 1
                        buy_surge_streak = 0
                        surges.append(f"💣 {dt.strftime('%H:%M')} 爆量賣 {ratio:.1f} 倍")

                    if buy_surge_streak >= 3 and close_price >= vwap_price:
                        gold_signal = f"🟡 金探號 {dt.strftime('%H:%M')}：連續 {buy_surge_streak} 根爆量買，價格站上均價"

                    if sell_surge_streak >= 3 and close_price < vwap_price:
                        gold_signal = f"⚫ 風險訊號 {dt.strftime('%H:%M')}：連續 {sell_surge_streak} 根爆量賣，價格跌破均價"
                else:
                    buy_surge_streak = 0
                    sell_surge_streak = 0

            prev_price_for_surge = close_price if close_price > 0 else prev_price_for_surge

        surges = surges[-5:]

        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>現價 / 漲跌</div><div style='color:{price_color(curr, prev_c)}; font-size:22px; font-weight:bold;'>{curr:.2f} <span style='font-size:16px;'>({diff:+.2f} {pct:+.2f}%)</span></div></div>", unsafe_allow_html=True)
        m2.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>最高 / 最低</div><div style='color:#fff; font-size:22px; font-weight:bold;'><span style='color:#ff3b3b'>{high_val:.2f}</span> <span style='color:#666;'>/</span> <span style='color:#00e676'>{low_val:.2f}</span></div></div>", unsafe_allow_html=True)
        m3.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>今日振幅</div><div style='color:#ffcc00; font-size:22px; font-weight:bold;'>{amp_pct:.2f}%</div></div>", unsafe_allow_html=True)
        m4.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>即時均價 (VWAP)</div><div style='color:#fff; font-size:22px; font-weight:bold;'>{df_plot['VWAP'].iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='card' style='margin-top:10px; margin-bottom:15px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px; font-size:15px;'><span style='color:#ff3b3b; font-weight:bold;'>🔥 主動買盤 {buy_pct:.1f}%</span><span style='color:#00e676; font-weight:bold;'>❄️ 主動賣盤 {sell_pct:.1f}%</span></div><div style='height:12px; background:#1a1a1a; border-radius:6px; display:flex; overflow:hidden;'><div style='width:{buy_pct}%; background:#ff3b3b;'></div><div style='width:{sell_pct}%; background:#00e676;'></div></div></div>", unsafe_allow_html=True)
        if gold_signal:
            st.markdown(
                f"""
                <div style="
                    background:linear-gradient(90deg,#3a2f00,#111);
                    border:1px solid #ffcc00;
                    color:#ffcc00;
                    padding:10px 14px;
                    border-radius:8px;
                    margin:10px 0 12px 0;
                    font-size:16px;
                    font-weight:bold;
                ">
                    {gold_signal}
                </div>
                """,
                unsafe_allow_html=True
            )

        if surges:
            st.markdown(
                f"""
                <div style="margin-bottom:15px;">
                    {''.join([
                        f'<span style="background:#332b00; border:1px solid #665500; color:#ffcc00; padding:4px 10px; border-radius:5px; margin-right:10px; font-size:14px; font-weight:bold;">{s}</span>'
                        for s in surges
                    ])}
                </div>
                """,
                unsafe_allow_html=True
            )

        cdata = [
            [
                int(r["Volume"]) if not pd.isna(r["Volume"]) else 0,
                round(((r["Close"] - prev_c) / prev_c * 100), 2) if prev_c else 0
            ]
            for _, r in df_plot.iterrows()
        ]
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["Close"], mode="lines", name="即價", line=dict(color="yellow", width=2.5), customdata=cdata, hovertemplate="<b>時間:</b> %{x|%H:%M}<br><b>價格:</b> %{y:.2f}<br><b>漲跌:</b> %{customdata[1]:+.2f}%<br><b>量:</b> %{customdata[0]:,.0f}<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["VWAP"], mode="lines", name="均價", line=dict(color="white", width=1.5, dash="dot"), hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_plot.index, y=[prev_c] * len(df_plot), mode="lines", name="昨收", line=dict(color="#777", dash="dash"), hoverinfo="skip"), row=1, col=1)
        fig.add_trace(go.Bar(x=df_plot.index, y=df_plot["Volume"], name="分量", marker_color=v_colors, customdata=cdata, hovertemplate="<b>時間:</b> %{x|%H:%M}<br><b>量:</b> %{y:,.0f}<extra></extra>"), row=2, col=1)
        today = df_plot.index[-1].date()
        fig.update_xaxes(range=[pd.Timestamp(f"{today} 09:00", tz="Asia/Taipei"), pd.Timestamp(f"{today} 13:30", tz="Asia/Taipei")], tickformat="%H:%M")
        fig.update_layout(template="plotly_dark", height=650, margin=dict(l=10, r=10, t=20, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), hovermode="x unified", paper_bgcolor="#000", plot_bgcolor="#000", dragmode=False) # 關閉手機拖曳
        
        fig.update_xaxes(gridcolor="#111", showspikes=True, spikemode="across", spikesnap="cursor", showline=False, spikedash="solid", fixedrange=True) # 鎖定 X 軸縮放
        
        # 修正即時走勢基準，強制讓 Y 軸以昨收價為中心對稱置中
        max_deviation = max(abs(df_plot["High"].max() - prev_c), abs(df_plot["Low"].min() - prev_c))
        max_deviation = max_deviation if max_deviation > 0 else prev_c * 0.01
        y_max = prev_c + max_deviation * 1.05
        y_min = prev_c - max_deviation * 1.05
        fig.update_yaxes(range=[y_min, y_max], side="right", gridcolor="#111", fixedrange=True, row=1, col=1) # 鎖定 Y 軸縮放
        
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={
                "scrollZoom": False,
                "displayModeBar": False,
                "displaylogo": False
            }
        )
    else:
        st.warning("⚠️ 無盤中資料")

# =====================
# 🤖 AI綜合預測
# =====================
elif page == "🤖 AI綜合預測":
    st.markdown(f"## 🤖 {display_name} AI 綜合預測中心")
    ts, ids, cs, fs, buy_pct, sell_pct = 0, 0, 0, 0, 0.5, 0.5
    try:
        if len(df) >= 20:
            ma5, ma20, h20, vma20, vc = df["Close"].rolling(5).mean().iloc[-1], df["Close"].rolling(20).mean().iloc[-1], df["High"].rolling(20).max().iloc[-1], df["Volume"].rolling(20).mean().iloc[-1], df["Volume"].iloc[-1]
            if curr > ma5: ts += 10
            if curr > ma20: ts += 20
            if curr >= h20 * 0.99: ts += 25
            if vc > vma20: ts += 20
            if curr >= open_p: ts += 10
            if curr > prev_c and vc > df["Volume"].iloc[-2]: ts += 15
        else: ts = 50
    except Exception: ts = 50
    ts = max(0, min(100, ts))

    try:
        if not df_i_for_summary.empty:
            df_i = df_i_for_summary.copy()
            vwap = (df_i["Close"] * df_i["Volume"]).sum() / df_i["Volume"].sum() if df_i["Volume"].sum() > 0 else curr
            hd, ld = max(df_i["High"].max(), curr), min(df_i["Low"].min(), curr)
            amp = (hd - ld) / ld if ld > 0 else 0
            bv, pc = 0, prev_c
            for _, r in df_i.iterrows():
                if r["Close"] >= pc:
                    bv += r["Volume"]
                pc = r["Close"]
            tv = df_i["Volume"].sum()
            if tv > 0:
                buy_pct = bv / tv
                sell_pct = 1 - buy_pct
            if curr > vwap: ids += 20
            if buy_pct > 0.6: ids += 25
            if len(df) >= 20 and df_i["Volume"].max() > df["Volume"].rolling(20).mean().iloc[-1] / 270 * 2: ids += 20
            if hd > 0 and (hd - curr) / hd < 0.01: ids += 15
            if amp > 0.03: ids += 10
        else: ids = 50
    except Exception: ids = 50
    ids = max(0, min(100, ids))

    try:
        if bids and asks:
            bv, av = sum(x.get("size", 0) for x in bids), sum(x.get("size", 0) for x in asks)
            tba = bv + av
            if bv > av: cs += 20
            if tba > 0 and (bv - av) / tba > 0.2: cs += 20
            if bids and bids[0].get("size", 0) > 100: cs += 20
            if bv > av * 1.5: cs += 20
            cs += 20
        else: cs = 50
    except Exception: cs = 50
    cs = max(0, min(100, cs))

    try:
        info, _ = fetch_fundamentals(symbol, suffix)
        if info:
            e, r, d, p, g = info.get("trailingEps"), info.get("returnOnEquity"), info.get("dividendYield"), info.get("trailingPE"), info.get("revenueGrowth")
            if e and e > 10: fs += 20
            if r and r > 0.15: fs += 20
            if d and d > 0.05: fs += 20
            if p and 0 < p < 20: fs += 20
            if g and g > 0: fs += 20
        else: fs = 50
    except Exception: fs = 50
    fs = max(0, min(100, fs))

    tot = ts * 0.3 + ids * 0.25 + cs * 0.2 + fs * 0.25
    tg, tc = ("🚀 強勢多方", "#ff3b3b") if tot >= 85 else ("📈 偏多", "#ff9900") if tot >= 70 else ("🟡 中性偏多", "#ffcc00") if tot >= 55 else ("⚖️ 震盪", "#aaaaaa") if tot >= 45 else ("📉 偏空", "#00e676") if tot >= 30 else ("❄️ 弱勢", "#009900")

    t1, t2, t3 = st.columns([3, 4, 3])
    with t1:
        st.plotly_chart(donut_chart("🤖 綜合評分", tot, tg, tc), use_container_width=True)
    with t2:
        fig_r = go.Figure(go.Scatterpolar(r=[ts, ids, cs, fs, ts], theta=["技術面", "即時盤中", "籌碼五檔", "基本面", "技術面"], fill="toself", line_color="#00e5ff", fillcolor="rgba(0, 229, 255, 0.3)"))
        fig_r.update_layout(template="plotly_dark", height=280, margin=dict(l=30, r=30, t=30, b=30), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", polar=dict(radialaxis=dict(visible=True, range=[0, 100], gridcolor="#333"), angularaxis=dict(gridcolor="#333")))
        st.plotly_chart(fig_r, use_container_width=True)
    with t3:
        fig_b = go.Figure(go.Bar(x=[ts, ids, cs, fs], y=["技術", "盤中", "籌碼", "基本"], orientation="h", marker_color=["#ffcc00", "#00e676", "#ff3b3b", "#aa00ff"], text=[f"{ts:.0f}", f"{ids:.0f}", f"{cs:.0f}", f"{fs:.0f}"], textposition="auto"))
        fig_b.update_layout(template="plotly_dark", height=280, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(range=[0, 100], gridcolor="#333"))
        st.plotly_chart(fig_b, use_container_width=True)

    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f"<div class='card' style='height:100%; border-top:4px solid #ffcc00;'><h4 style='color:#ccc; margin-bottom:5px;'>1️⃣ 技術面</h4><div style='font-size:32px; font-weight:bold; color:#ffcc00; margin-bottom:10px;'>{ts:.0f}<span style='font-size:14px; color:#888;'> / 100</span></div><p style='color:#bbb; font-size:14px; line-height:1.5;'>分析長短期均線排列、20日高低點突破狀況以及量價配合結構。</p></div>", unsafe_allow_html=True)
    m2.markdown(f"<div class='card' style='height:100%; border-top:4px solid #00e676;'><h4 style='color:#ccc; margin-bottom:5px;'>2️⃣ 即時盤中</h4><div style='font-size:32px; font-weight:bold; color:#00e676; margin-bottom:10px;'>{ids:.0f}<span style='font-size:14px; color:#888;'> / 100</span></div><p style='color:#bbb; font-size:14px; line-height:1.5;'>偵測盤中VWAP均價線防守、主動買盤力道與異常爆量訊號。</p></div>", unsafe_allow_html=True)
    m3.markdown(f"<div class='card' style='height:100%; border-top:4px solid #ff3b3b;'><h4 style='color:#ccc; margin-bottom:5px;'>3️⃣ 籌碼五檔</h4><div style='font-size:32px; font-weight:bold; color:#ff3b3b; margin-bottom:10px;'>{cs:.0f}<span style='font-size:14px; color:#888;'> / 100</span></div><p style='color:#bbb; font-size:14px; line-height:1.5;'>觀測最佳五檔買賣壓差、掛單積極度與大戶即時敲單方向。</p></div>", unsafe_allow_html=True)
    m4.markdown(f"<div class='card' style='height:100%; border-top:4px solid #aa00ff;'><h4 style='color:#ccc; margin-bottom:5px;'>4️⃣ 基本面</h4><div style='font-size:32px; font-weight:bold; color:#aa00ff; margin-bottom:10px;'>{fs:.0f}<span style='font-size:14px; color:#888;'> / 100</span></div><p style='color:#bbb; font-size:14px; line-height:1.5;'>評估企業EPS獲利能力、ROE回報率、殖利率防禦及估值高低。</p></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🧠 籌碼推估：主力 / 外資成本區")

    inst_df = fetch_institutional_chips(symbol, FINMIND_TOKEN)
    
    f_status = "外資觀望"
    f_status_color = "#aaa"
    f_sum_5 = 0
    f_streak_txt = "無"
    f_est_cost = "N/A"
    
    if not inst_df.empty and '外資' in inst_df.columns:
        recent_20 = inst_df.tail(20).copy()
        f_sum_5 = recent_20.tail(5)['外資'].sum()
        
        if f_sum_5 > 0:
            f_status, f_status_color = "外資偏進貨", "#ff3b3b"
        elif f_sum_5 < 0:
            f_status, f_status_color = "外資偏出貨", "#00e676"
            
        f_streak = 0
        is_buy = None
        for val in reversed(recent_20['外資'].tolist()):
            if is_buy is None:
                if val == 0: break
                is_buy = val > 0
            if (val > 0 and is_buy) or (val < 0 and not is_buy):
                f_streak += 1
            else:
                break
        if f_streak > 0:
            f_streak_txt = f"連 {f_streak} 買" if is_buy else f"連 {f_streak} 賣"
            
        try:
            temp_df = df.copy()
            temp_df.index = temp_df.index.strftime('%Y-%m-%d')
            merged = pd.merge(recent_20, temp_df[['Close']], left_on='date', right_index=True, how='left')
            buys = merged[merged['外資'] > 0]
            if not buys.empty and not buys['Close'].isna().all():
                tot_cost = (buys['外資'] * buys['Close']).sum()
                tot_vol = buys['外資'].sum()
                if tot_vol > 0:
                    f_est_cost = f"{tot_cost / tot_vol:.2f}"
        except Exception:
            pass
            
    m_status = "主力觀望"
    m_status_color = "#aaa"
    m_vwap = "N/A"
    m_max_vol_p = "N/A"
    m_max_vol_times = "無" 
    
    vwap_val = curr
    if not df_i_for_summary.empty:
        vol_sum = df_i_for_summary["Volume"].sum()
        if vol_sum > 0:
            vwap_val = (df_i_for_summary["Close"] * df_i_for_summary["Volume"]).sum() / vol_sum
            m_vwap = f"{vwap_val:.2f}"
            
    if trades:
        pv = {}
        for t in trades:
            try:
                p = float(t.get("price", t.get("tradePrice", 0)) or 0)
                s = int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
                if p > 0 and s > 0:
                    pv[p] = pv.get(p, 0) + s
            except Exception:
                pass
        
        if pv:
            max_p = max(pv, key=pv.get)
            m_max_vol_p = f"{max_p:.2f}"
            
            minute_vol = {}
            for t in trades:
                try:
                    p = float(t.get("price", t.get("tradePrice", 0)) or 0)
                    s = int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
                    tm = format_trade_time(t.get("time", t.get("at", t.get("date", ""))))

                    if p == max_p and s > 0 and tm:
                        minute_key = str(tm)[:5]
                        minute_vol[minute_key] = minute_vol.get(minute_key, 0) + s
                except Exception:
                    pass

            if minute_vol:
                top_times = sorted(minute_vol.items(), key=lambda x: x[1], reverse=True)[:3]
                m_max_vol_times = "、".join([x[0] for x in top_times])
            
    if curr > vwap_val and buy_pct > 0.6:
        m_status, m_status_color = "主力疑似進貨", "#ff3b3b"
    elif curr < vwap_val and buy_pct < 0.45:
        m_status, m_status_color = "主力疑似出貨", "#00e676"
        
    c_f1, c_f2, c_m1, c_m2 = st.columns(4)
    c_f1.markdown(f"<div class='card' style='height:100%; border-left:4px solid {f_status_color};'><h4 style='color:#ccc; margin-bottom:5px;'>外資狀態</h4><div style='font-size:24px; font-weight:bold; color:{f_status_color}; margin-bottom:10px;'>{f_status}</div><p style='color:#bbb; font-size:14px; margin:0;'>近5日買賣超：<span style='color:{'#ff3b3b' if f_sum_5>0 else '#00e676' if f_sum_5<0 else '#fff'};'>{f_sum_5:,.0f}</span> 張<br>連買 / 連賣：{f_streak_txt}</p></div>", unsafe_allow_html=True)
    c_f2.markdown(f"<div class='card' style='height:100%; border-left:4px solid #00e5ff;'><h4 style='color:#ccc; margin-bottom:5px;'>外資估算成本</h4><div style='font-size:28px; font-weight:bold; color:#00e5ff; margin-bottom:5px;'>{f_est_cost} <span style='font-size:16px;'>元</span></div><p style='color:#888; font-size:12px; margin:0;'>估算值，非真實成交均價</p></div>", unsafe_allow_html=True)
    c_m1.markdown(f"<div class='card' style='height:100%; border-left:4px solid {m_status_color};'><h4 style='color:#ccc; margin-bottom:5px;'>主力狀態</h4><div style='font-size:24px; font-weight:bold; color:{m_status_color}; margin-bottom:10px;'>{m_status}</div><p style='color:#bbb; font-size:14px; margin:0;'>主動買盤：<span style='color:{'#ff3b3b' if buy_pct>0.5 else '#00e676'};'>{buy_pct*100:.1f}%</span></p></div>", unsafe_allow_html=True)
    c_m2.markdown(f"<div class='card' style='height:100%; border-left:4px solid #ffcc00;'><h4 style='color:#ccc; margin-bottom:5px;'>主力疑似成本區</h4><p style='color:#bbb; font-size:15px; margin:5px 0;'>成交量加權均價 (VWAP)：<span style='font-weight:bold; color:#fff;'>{m_vwap}</span> 元<br>大量成交價：<span style='font-weight:bold; color:#fff;'>{m_max_vol_p}</span> 元<br>集中時間：約 <span style='color:#ddd;'>{m_max_vol_times}</span></p></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🐋 大戶 / 中實戶 / 散戶成交結構")
    st.caption("⚠️ 此為依單筆成交量與成交價變化推估，非交易所真實身分資料。")

    if not trades:
        st.info("📡 成交明細不足，無法估算大戶結構")
    else:
        w_b = w_s = 0
        m_b = m_s = 0
        r_b = r_s = 0
        
        last_p = prev_c
        for t in reversed(trades):
            try:
                p = float(t.get("price", t.get("tradePrice", 0)) or 0)
                v = int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
                if p == 0 or v == 0: continue
                
                is_buy = p >= last_p
                if v >= 50:
                    if is_buy: w_b += v
                    else: w_s += v
                elif v >= 20:
                    if is_buy: m_b += v
                    else: m_s += v
                else:
                    if is_buy: r_b += v
                    else: r_s += v
                
                last_p = p
            except Exception:
                pass
                
        w_net = w_b - w_s
        m_net = m_b - m_s
        r_net = r_b - r_s
        
        def get_grp_stat(b, s, n):
            if b > s: return f"{n}偏進貨", "#ff3b3b"
            elif b < s: return f"{n}偏出貨", "#00e676"
            else: return f"{n}觀望", "#aaa"
            
        w_stat, w_c = get_grp_stat(w_b, w_s, "大戶")
        m_stat, m_c = get_grp_stat(m_b, m_s, "中實戶")
        r_stat, r_c = get_grp_stat(r_b, r_s, "散戶")
        
        c_w, c_m, c_r = st.columns(3)
        c_w.markdown(f"<div class='card' style='border-left:4px solid {w_c};'><h4 style='color:#ccc; margin-bottom:5px;'>大戶 (>=50張)</h4><div style='font-size:24px; font-weight:bold; color:{w_c}; margin-bottom:10px;'>{w_stat}</div><p style='color:#bbb; font-size:15px; margin:0; line-height:1.6;'>買進量：<span style='color:#ff3b3b;'>{w_b:,}</span> 張<br>賣出量：<span style='color:#00e676;'>{w_s:,}</span> 張<br>淨量：<span style='color:{w_c};'>{w_net:+,}</span> 張</p></div>", unsafe_allow_html=True)
        c_m.markdown(f"<div class='card' style='border-left:4px solid {m_c};'><h4 style='color:#ccc; margin-bottom:5px;'>中實戶 (20~49張)</h4><div style='font-size:24px; font-weight:bold; color:{m_c}; margin-bottom:10px;'>{m_stat}</div><p style='color:#bbb; font-size:15px; margin:0; line-height:1.6;'>買進量：<span style='color:#ff3b3b;'>{m_b:,}</span> 張<br>賣出量：<span style='color:#00e676;'>{m_s:,}</span> 張<br>淨量：<span style='color:{m_c};'>{m_net:+,}</span> 張</p></div>", unsafe_allow_html=True)
        c_r.markdown(f"<div class='card' style='border-left:4px solid {r_c};'><h4 style='color:#ccc; margin-bottom:5px;'>散戶 (&lt;20張)</h4><div style='font-size:24px; font-weight:bold; color:{r_c}; margin-bottom:10px;'>{r_stat}</div><p style='color:#bbb; font-size:15px; margin:0; line-height:1.6;'>買進量：<span style='color:#ff3b3b;'>{r_b:,}</span> 張<br>賣出量：<span style='color:#00e676;'>{r_s:,}</span> 張<br>淨量：<span style='color:{r_c};'>{r_net:+,}</span> 張</p></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📝 AI 深度解析報告")
    txt_t = f"從技術線型來看，目前股價得分 {ts:.0f} 分。短中期均線排列決定了趨勢的延續性，而相對於20日高低點的位置，反映出市場突破企圖心。配合近期量能變化，整體技術結構顯示 {'多方掌控' if ts>=60 else '空方壓制' if ts<40 else '橫盤震盪'}。建議密切觀察關鍵壓力與支撐的攻防。"
    txt_i = f"觀察今日走勢，盤中綜合評分為 {ids:.0f} 分。股價與 VWAP 均價線的相對位置，顯示了當沖客與造市者的成本防線。今日主動買盤達 {buy_pct*100:.1f}%，暗示資金的真實攻擊方向。若盤中出現急拉爆量，需提防獲利了結賣壓。整體振幅大小亦決定了今日交易的活躍程度。"
    txt_c = f"籌碼與掛單分析顯示，目前籌碼健康度達 {cs:.0f} 分。最佳五檔的委買委賣力道懸殊，反映了造市者與散戶的預期。當大單敲進或倒出時，即時明細揭露了主力吃貨或出貨的痕跡。買賣報價的滑價空間顯示流動性是否充足。後續需追蹤主力籌碼是否具備延續性。"
    txt_f = f"基本面價值評估獲得 {fs:.0f} 分。公司的獲利數據直接反映其長期營運能力與股東資本回報率。配合目前的本益比與股價淨值比區間，可判斷當前股價是否具備估值優勢。近期營收的成長率是支撐股價上行的重要催化劑。高股息殖利率亦能為股價提供防禦保護。"
    txt_all = f"綜合四大面向模型，目前標的總評分為 **{tot:.1f}** 分，系統判定為「**{tg}**」。偏多底氣主要來自於資金動能的匯聚與技術關卡的突破；偏空風險則潛藏於短線過熱或基本面估值過高的疑慮之中。短線操作建議以 VWAP 作為當沖多空分水嶺，中長線投資人則應緊盯即將公布的營收與財報數據。主力大戶的籌碼堆疊方向，預示著未來的潛在走勢。<br><br><span style='color:#ff3b3b;'>⚠️ 本分析模型基於量化數據自動生成，僅供觀察參考，不構成任何買賣建議。</span>"
    st.markdown(f"<div style='display:grid; grid-template-columns: 1fr 1fr; gap: 20px;'><div class='card'><h4>📈 技術與盤中動能</h4><p style='color:#ccc; font-size:15px; line-height:1.6;'><b>技術面：</b>{txt_t}</p><p style='color:#ccc; font-size:15px; line-height:1.6;'><b>即時盤中：</b>{txt_i}</p></div><div class='card'><h4>💼 籌碼與基本面價值</h4><p style='color:#ccc; font-size:15px; line-height:1.6;'><b>籌碼五檔：</b>{txt_c}</p><p style='color:#ccc; font-size:15px; line-height:1.6;'><b>基本面：</b>{txt_f}</p></div></div><div class='card' style='margin-top:20px; border:1px solid #555; background:#151515;'><h3 style='color:#ffcc00; margin-bottom:10px;'>🎯 AI 綜合總結建議</h3><p style='color:#eee; font-size:16px; line-height:1.8;'>{txt_all}</p></div>", unsafe_allow_html=True)
# =====================
# 📑 基本面分析
# =====================
elif page == "📑 基本面分析":
    st.markdown(f"## 📑 {display_name} 基本面分析")
    info, fin_data = fetch_fundamentals(symbol, suffix)
    rev_df = fetch_monthly_revenue(symbol, FINMIND_TOKEN)

    def safe_get(key, default="N/A"):
        return info.get(key, default) if info.get(key) is not None else default

    def fmt_pct_ratio(val):
        if val == "N/A" or pd.isna(val):
            return "N/A"
        try:
            v = float(val)
            return f"{v:.2f}%" if abs(v) > 1 else f"{v*100:.2f}%"
        except Exception:
            return "N/A"

    def norm_rat(val):
        if val == "N/A" or pd.isna(val):
            return None
        try:
            v = float(val)
            return v/100 if abs(v) > 1 else v
        except Exception:
            return None

    def fmt_flt(val, dec=2):
        return f"{float(val):.{dec}f}" if val != "N/A" and not pd.isna(val) else "N/A"

    def fmt_curr(val):
        if val == "N/A" or pd.isna(val):
            return "N/A"
        try:
            v = float(val)
            return f"{v/1e12:.2f} 兆" if abs(v) >= 1e12 else f"{v/1e8:.2f} 億" if abs(v) >= 1e8 else f"{v/1e4:.2f} 萬" if abs(v) >= 1e4 else f"{v:,.0f}"
        except Exception:
            return "N/A"

    def fmt_date(val):
        return datetime.fromtimestamp(val).strftime("%Y-%m-%d") if val != "N/A" and not pd.isna(val) else "N/A"

    sector = INDUSTRY_BACKUP.get(symbol, safe_get("sector"))
    mc, emp, cty, cur = safe_get("marketCap", 0), safe_get("fullTimeEmployees"), safe_get("country"), safe_get("currency")
    eps, pe, pb, roe, dy = safe_get("trailingEps", 0), safe_get("trailingPE", 0), safe_get("priceToBook", 0), safe_get("returnOnEquity", 0), safe_get("dividendYield", 0)

    eps_str = fmt_flt(eps)
    pe_str = fmt_flt(pe)
    pb_str = fmt_flt(pb)
    roe_str = fmt_pct_ratio(roe)
    div_str = fmt_pct_ratio(dy)
    mc_str = fmt_curr(mc)

    roe_norm = norm_rat(roe)
    div_yield_norm = norm_rat(dy)

    i1, i2, i3, i4 = st.columns(4)
    i1.markdown(f"<div class='card'><div style='color:#aaa;'>產業板塊</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{sector}</div></div>", unsafe_allow_html=True)
    i2.markdown(f"<div class='card'><div style='color:#aaa;'>公司市值</div><div style='font-size:20px; font-weight:bold; color:#ffcc00;'>{mc_str}</div></div>", unsafe_allow_html=True)
    i3.markdown(f"<div class='card'><div style='color:#aaa;'>員工總數</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{emp}</div></div>", unsafe_allow_html=True)
    i4.markdown(f"<div class='card'><div style='color:#aaa;'>國家/幣別</div><div style='font-size:20px; font-weight:bold; color:#fff;'>{cty} / {cur}</div></div>", unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>EPS (近四季)</div><div style='font-size:22px; font-weight:bold; color:#ff3b3b;'>{eps_str}</div></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>本益比 (PER)</div><div style='font-size:22px; font-weight:bold; color:#00e676;'>{pe_str}</div></div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>股價淨值比 (PBR)</div><div style='font-size:22px; font-weight:bold; color:#00e676;'>{pb_str}</div></div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>股東權益報酬 (ROE)</div><div style='font-size:22px; font-weight:bold; color:#ffcc00;'>{roe_str}</div></div>", unsafe_allow_html=True)
    c5.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>殖利率</div><div style='font-size:22px; font-weight:bold; color:#ff3b3b;'>{div_str}</div></div>", unsafe_allow_html=True)
    c6.markdown(f"<div class='card' style='text-align:center;'><div style='color:#aaa; font-size:14px;'>市值規模</div><div style='font-size:22px; font-weight:bold; color:#fff;'>{mc_str}</div></div>", unsafe_allow_html=True)

    score = 0
    if eps != "N/A" and eps > 0:
        score += 20 if eps > 10 else 10 if eps > 5 else 0
    if roe_norm is not None and roe_norm > 0:
        score += 20 if roe_norm > 0.15 else 10 if roe_norm > 0.1 else 0
    if div_yield_norm is not None and div_yield_norm > 0:
        score += 20 if div_yield_norm > 0.05 else 10 if div_yield_norm > 0.03 else 0
    if pe != "N/A" and pe > 0:
        score += 20 if pe < 15 else 10 if pe < 25 else 0
    if pb != "N/A" and pb > 0:
        score += 20 if pb < 2 else 10 if pb < 4 else 0
    score = max(0, min(100, score))

    stg, scl = ("🔥 極度優秀", "#ff3b3b") if score >= 90 else ("✅ 基本面強勁", "#ff9900") if score >= 75 else ("👍 穩健型公司", "#ffcc00") if score >= 60 else ("⚠️ 普通", "#aaaaaa") if score >= 40 else ("❄️ 基本面偏弱", "#00e676")
    ais = "公司具備優異獲利能力(ROE高)，" if roe_norm and roe_norm > 0.15 else "公司獲利尚可，" if roe_norm and roe_norm > 0 else "目前獲利偏弱，"
    ais += "具高殖利率防禦保護。" if div_yield_norm and div_yield_norm > 0.05 else "偏向不發高息之資本策略。"
    ais += ("<br>本益比偏低，具潛在價值。" if pe != "N/A" and 0 < pe < 15 else "<br>本益比較高，偏向成長型評價。" if pe != "N/A" and pe > 25 else "<br>估值處合理區間。" if pe != "N/A" and pe > 0 else "<br>無有效PER參考。")

    st.markdown("---")
    s1, s2 = st.columns([3, 7])
    with s1:
        st.plotly_chart(donut_chart("🤖 AI 評分", score, stg, scl), use_container_width=True)
    with s2:
        st.markdown(f"<div class='card' style='height:260px; display:flex; align-items:center; padding:30px;'><h3 style='color:#fff; line-height:1.6;'>{ais}</h3></div>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📅 每月營收")
    if not FINMIND_TOKEN:
        st.warning("⚠️ 未設定 FINMIND_TOKEN，請設定 Streamlit Secrets 或 finmind_token.txt。")
    elif rev_df.empty:
        st.info("📡 暫無營收資料")
    else:
        cr1, cr2 = st.columns([4, 6])
        with cr1:
            h = "<div style='overflow-x:auto; max-height:400px; border-radius:12px; border:1px solid #222;'><table class='fin-table'><thead style='position:sticky; top:0; z-index:2; background:#222;'><tr><th style='padding:10px; color:#fff;'>月份</th><th style='text-align:right; padding:10px; color:#fff;'>營收(億)</th><th style='text-align:right; padding:10px; color:#fff;'>月增率</th><th style='text-align:right; padding:10px; color:#fff;'>年增率</th></tr></thead><tbody>"
            for _, r in rev_df.iterrows():
                m, rv, mom, yoy = r["月份"], r["營收（億元台幣）"], r["月增率 MoM"], r["年增率 YoY"]
                h += f"<tr><td>{m}</td><td style='text-align:right'>{rv:.2f}</td><td style='text-align:right; color: {'#ff3b3b' if mom > 0 else '#00e676' if mom < 0 else '#fff'};'>{mom:+.2f}%</td><td style='text-align:right; color: {'#ff3b3b' if yoy > 0 else '#00e676' if yoy < 0 else '#fff'};'>{yoy:+.2f}%</td></tr>"
            st.markdown(h + "</tbody></table></div>", unsafe_allow_html=True)
        with cr2:
            d_c = rev_df.iloc[::-1].copy()
            fr = make_subplots(specs=[[{"secondary_y": True}]])
            fr.add_trace(go.Bar(x=d_c["月份"], y=d_c["營收（億元台幣）"], name="營收(億)", marker_color="#00e5ff"), secondary_y=False)
            fr.add_trace(go.Scatter(x=d_c["月份"], y=d_c["年增率 YoY"], name="年增率(%)", line=dict(color="#ff3b3b", width=2)), secondary_y=True)
            fr.update_layout(template="plotly_dark", height=400, margin=dict(l=10, r=10, t=20, b=10), paper_bgcolor="#000", plot_bgcolor="#000", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            fr.update_xaxes(gridcolor="#111", type="category")
            fr.update_yaxes(title_text="營收(億元台幣)", gridcolor="#111", secondary_y=False)
            fr.update_yaxes(title_text="年增率(%)", showgrid=False, secondary_y=True)
            st.plotly_chart(fr, use_container_width=True)

    st.markdown("---")
    st.markdown("### 📋 基本面詳細表格")
    dte_str = f"{fmt_flt(safe_get('debtToEquity'))}%" if safe_get("debtToEquity") != "N/A" else "N/A"
    th = (
        "<div style='overflow-x:auto; max-height:700px; border-radius:12px; border:1px solid #222;'><table class='fin-table'><thead style='position:sticky; top:0; z-index:2; background:#222;'>"
        "<tr><th style='padding:10px; color:#fff;'>分類</th><th style='padding:10px; color:#fff;'>指標</th><th style='padding:10px; color:#fff;'>數值</th><th style='padding:10px; color:#fff;'>解讀</th></tr></thead><tbody>"
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
        if "Total Revenue" in fin_data.columns:
            ff.add_trace(go.Bar(x=fin_data.index, y=fin_data["Total Revenue"] / 1e8, name="營收(億)", marker_color="rgba(255,204,0,0.7)"), secondary_y=False)
            hp = True
        elif "Operating Revenue" in fin_data.columns:
            ff.add_trace(go.Bar(x=fin_data.index, y=fin_data["Operating Revenue"] / 1e8, name="營業收入(億)", marker_color="rgba(255,204,0,0.7)"), secondary_y=False)
            hp = True
        if "Net Income" in fin_data.columns:
            ff.add_trace(go.Scatter(x=fin_data.index, y=fin_data["Net Income"] / 1e8, name="淨利(億)", line=dict(color="#ff3b3b", width=3)), secondary_y=False)
            hp = True
        if "Basic EPS" in fin_data.columns:
            ff.add_trace(go.Scatter(x=fin_data.index, y=fin_data["Basic EPS"], name="EPS", line=dict(color="#fff", width=2, dash="dot")), secondary_y=True)
            hp = True
        if hp:
            ff.update_layout(template="plotly_dark", height=500, margin=dict(l=10, r=10, t=20, b=10), paper_bgcolor="#000", plot_bgcolor="#000")
            ff.update_xaxes(type="category")
            ff.update_yaxes(title_text="金額(億元台幣)", secondary_y=False)
            st.plotly_chart(ff, use_container_width=True)
        else:
            st.info("📡 暫無圖表資料")
    else:
        st.info("📡 暫無財報趨勢資料")
# =====================
# 🧩 籌碼分析
# =====================
elif page == "🧩 籌碼分析":
    st.markdown(f"## 🧩 {display_name} 籌碼分析")

    def fmt_chip_num(v, plus=False, bold=False):
        try:
            v = float(v)
            color = "#ff3b3b" if v > 0 else "#00e676" if v < 0 else "#fff"
            fw = "font-weight:bold;" if bold else ""
            sign = "+" if plus and v > 0 else ""
            text = f"{sign}{v:.0f} 張"
            return f"<span style='color:{color}; {fw}'>{text}</span>"
        except Exception:
            return "<span style='color:#888;'>0 張</span>"

    def fmt_plain_num(v):
        try:
            return f"{float(v):.0f} 張"
        except Exception:
            return "0 張"

    if not FINMIND_TOKEN:
        st.warning("⚠️ 未設定 FINMIND_TOKEN，無法獲取籌碼資料。")
    else:
        inst_df = fetch_institutional_chips(symbol, FINMIND_TOKEN)
        margin_df = fetch_margin_chips(symbol, FINMIND_TOKEN)

        def get_streak(series):
            streak = 0
            is_buy = None

            vals = pd.to_numeric(series, errors="coerce").fillna(0).tolist()

            for val in reversed(vals):
                if is_buy is None:
                    if val == 0:
                        return "無明顯買賣"
                    is_buy = val > 0

                if (val > 0 and is_buy) or (val < 0 and not is_buy):
                    streak += 1
                else:
                    break

            return f"連 {streak} 買" if is_buy else f"連 {streak} 賣"

        if not inst_df.empty:
            for col in ["外資", "投信", "自營商", "合計"]:
                inst_df[col] = pd.to_numeric(inst_df[col], errors="coerce").fillna(0)

            f_streak = get_streak(inst_df["外資"])
            t_streak = get_streak(inst_df["投信"])
            d_streak = get_streak(inst_df["自營商"])
            tot_streak = get_streak(inst_df["合計"])

            st.markdown("### 📊 籌碼連買連賣")
            cs1, cs2, cs3, cs4 = st.columns(4)

            cs1.markdown(
                f"<div class='card' style='text-align:center;'>"
                f"<div style='color:#aaa;'>外資</div>"
                f"<div style='font-size:22px; font-weight:bold; color:{'#ff3b3b' if '買' in f_streak else '#00e676'};'>{f_streak}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            cs2.markdown(
                f"<div class='card' style='text-align:center;'>"
                f"<div style='color:#aaa;'>投信</div>"
                f"<div style='font-size:22px; font-weight:bold; color:{'#ff3b3b' if '買' in t_streak else '#00e676'};'>{t_streak}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            cs3.markdown(
                f"<div class='card' style='text-align:center;'>"
                f"<div style='color:#aaa;'>自營商</div>"
                f"<div style='font-size:22px; font-weight:bold; color:{'#ff3b3b' if '買' in d_streak else '#00e676'};'>{d_streak}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            cs4.markdown(
                f"<div class='card' style='text-align:center;'>"
                f"<div style='color:#aaa;'>三大法人合計</div>"
                f"<div style='font-size:22px; font-weight:bold; color:{'#ff3b3b' if '買' in tot_streak else '#00e676'};'>{tot_streak}</div>"
                f"</div>",
                unsafe_allow_html=True
            )

            st.markdown("---")
            col1, col2 = st.columns([5, 5])

            with col1:
                st.markdown("### 🏦 三大法人買賣超 (張)")
                inst_show = inst_df.iloc[::-1].copy()

                h_inst = (
                    "<div style='overflow-x:auto; max-height:400px; border-radius:12px; border:1px solid #222;'>"
                    "<table class='fin-table'>"
                    "<thead style='position:sticky; top:0; z-index:2; background:#222;'>"
                    "<tr>"
                    "<th style='padding:8px; color:#fff;'>日期</th>"
                    "<th style='text-align:right; padding:8px; color:#fff;'>外資</th>"
                    "<th style='text-align:right; padding:8px; color:#fff;'>投信</th>"
                    "<th style='text-align:right; padding:8px; color:#fff;'>自營商</th>"
                    "<th style='text-align:right; padding:8px; color:#fff;'>合計</th>"
                    "</tr></thead><tbody>"
                )

                for _, r in inst_show.iterrows():
                    h_inst += (
                        f"<tr>"
                        f"<td>{r['date']}</td>"
                        f"<td style='text-align:right;'>{fmt_chip_num(r['外資'])}</td>"
                        f"<td style='text-align:right;'>{fmt_chip_num(r['投信'])}</td>"
                        f"<td style='text-align:right;'>{fmt_chip_num(r['自營商'])}</td>"
                        f"<td style='text-align:right;'>{fmt_chip_num(r['合計'], bold=True)}</td>"
                        f"</tr>"
                    )

                h_inst += "</tbody></table></div>"
                st.markdown(h_inst, unsafe_allow_html=True)

            with col2:
                st.markdown("### 📈 籌碼趨勢圖")

                plot_df = inst_df.copy()
                plot_df["累計"] = plot_df["合計"].cumsum()

                fig_c = make_subplots(specs=[[{"secondary_y": True}]])
                fig_c.add_trace(
                    go.Bar(
                        x=plot_df["date"],
                        y=plot_df["合計"],
                        name="單日買賣(張)",
                        marker_color=["#ff3b3b" if v > 0 else "#00e676" for v in plot_df["合計"]]
                    ),
                    secondary_y=False
                )

                fig_c.add_trace(
                    go.Scatter(
                        x=plot_df["date"],
                        y=plot_df["累計"],
                        name="累計買賣超",
                        line=dict(color="#ffcc00", width=2)
                    ),
                    secondary_y=True
                )

                fig_c.update_layout(
                    template="plotly_dark",
                    height=400,
                    margin=dict(l=10, r=10, t=20, b=10),
                    paper_bgcolor="#000",
                    plot_bgcolor="#000",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                fig_c.update_xaxes(gridcolor="#111", type="category")
                fig_c.update_yaxes(title_text="單日(張)", gridcolor="#111", secondary_y=False)
                fig_c.update_yaxes(title_text="累計(張)", showgrid=False, secondary_y=True)
                st.plotly_chart(fig_c, use_container_width=True)

        else:
            st.info("📡 暫無三大法人買賣超資料")

        st.markdown("---")
        st.markdown("### 🕵️ 主力買賣")
        st.info("💡 主力分點資料需額外資料源，目前先以三大法人買賣超作為籌碼觀察。")

        st.markdown("---")
        st.markdown("### 🚶 散戶指標 (融資融券)")

        if not margin_df.empty:
            for col in ["融資餘額", "融券餘額", "融資增減", "融券增減"]:
                margin_df[col] = pd.to_numeric(margin_df[col], errors="coerce").fillna(0)

            mar_show = margin_df.iloc[::-1].copy()

            h_mar = (
                "<div style='overflow-x:auto; max-height:400px; border-radius:12px; border:1px solid #222;'>"
                "<table class='fin-table'>"
                "<thead style='position:sticky; top:0; z-index:2; background:#222;'>"
                "<tr>"
                "<th style='padding:8px; color:#fff;'>日期</th>"
                "<th style='text-align:right; padding:8px; color:#fff;'>融資餘額(張)</th>"
                "<th style='text-align:right; padding:8px; color:#fff;'>融資增減</th>"
                "<th style='text-align:right; padding:8px; color:#fff;'>融券餘額(張)</th>"
                "<th style='text-align:right; padding:8px; color:#fff;'>融券增減</th>"
                "</tr></thead><tbody>"
            )

            for _, r in mar_show.iterrows():
                h_mar += (
                    f"<tr>"
                    f"<td>{r['date']}</td>"
                    f"<td style='text-align:right'>{fmt_plain_num(r['融資餘額'])}</td>"
                    f"<td style='text-align:right'>{fmt_chip_num(r['融資增減'], plus=True)}</td>"
                    f"<td style='text-align:right'>{fmt_plain_num(r['融券餘額'])}</td>"
                    f"<td style='text-align:right'>{fmt_chip_num(r['融券增減'], plus=True)}</td>"
                    f"</tr>"
                )

            h_mar += "</tbody></table></div>"
            st.markdown(h_mar, unsafe_allow_html=True)

        else:
            st.info("📡 暫無融資融券資料")

# =====================
# 🎯 操作策略
# =====================
elif page == "🎯 操作策略":
    st.markdown(f"## 🎯 {display_name} 操作策略")

    if df.empty:
        st.warning("📡 K線資料不足，無法產生操作策略。")
    else:
        vwap_val = curr
        buy_pct_val = 0.5
        max_vol_p = curr
        whale_net = 0
        
        try:
            if not df_i_for_summary.empty:
                vol_sum = df_i_for_summary["Volume"].sum()
                if vol_sum > 0:
                    vwap_val = (df_i_for_summary["Close"] * df_i_for_summary["Volume"]).sum() / vol_sum
                
                buy_v = 0
                pc = prev_c
                for _, r in df_i_for_summary.iterrows():
                    c_p = r["Close"]
                    if c_p >= pc: buy_v += r["Volume"]
                    pc = c_p
                if vol_sum > 0:
                    buy_pct_val = buy_v / vol_sum
        except Exception: pass
        
        try:
            if trades:
                pv = {}
                w_b, w_s = 0, 0
                last_p = prev_c
                
                for t in reversed(trades):
                    p_t = float(t.get("price", t.get("tradePrice", 0)) or 0)
                    s_t = int(t.get("size", t.get("tradeVolume", t.get("volume", 0))) or 0)
                    if p_t == 0 or s_t == 0: continue
                    
                    pv[p_t] = pv.get(p_t, 0) + s_t
                    
                    is_buy = p_t >= last_p
                    if s_t >= 50:
                        if is_buy: w_b += s_t
                        else: w_s += s_t
                    last_p = p_t
                
                if pv: max_vol_p = max(pv, key=pv.get)
                whale_net = w_b - w_s
        except Exception: pass

        try:
            ma5 = df["Close"].rolling(5).mean().iloc[-1]
            ma10 = df["Close"].rolling(10).mean().iloc[-1]
            ma20 = df["Close"].rolling(20).mean().iloc[-1]
            high20 = df["High"].tail(20).max()
            low20 = df["Low"].tail(20).min()
            
            ema12 = df['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df['Close'].ewm(span=26, adjust=False).mean()
            dif = ema12 - ema26
            macd = dif.ewm(span=9, adjust=False).mean()
            osc = (dif - macd).iloc[-1]
            
            delta = df['Close'].diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            rsi14 = (100 - (100 / (1 + rs))).iloc[-1]
        except Exception:
            ma5 = ma10 = ma20 = high20 = low20 = osc = rsi14 = float('nan')

        f_sum_5 = 0
        has_foreign = False
        try:
            inst_df = fetch_institutional_chips(symbol, FINMIND_TOKEN)
            if not inst_df.empty and '外資' in inst_df.columns:
                f_sum_5 = inst_df.tail(5)['外資'].sum()
                has_foreign = True
        except Exception: pass

        eps, roe, rev_growth = float('nan'), float('nan'), float('nan')
        has_fund = False
        try:
            info, _ = fetch_fundamentals(symbol, suffix)
            if info:
                raw_eps = info.get("trailingEps")
                raw_roe = info.get("returnOnEquity")
                raw_rev = info.get("revenueGrowth")

                eps = float(raw_eps) if raw_eps is not None else float("nan")
                roe = float(raw_roe) if raw_roe is not None else float("nan")
                rev_growth = float(raw_rev) if raw_rev is not None else float("nan")
                has_fund = True
        except Exception: pass

        if curr > vwap_val and buy_pct_val > 0.55 and whale_net > 0 and curr >= max_vol_p:
            short_status, short_color = "短線偏多觀察", "#ff3b3b"
        elif curr < vwap_val and buy_pct_val < 0.45 and whale_net < 0:
            short_status, short_color = "短線偏空保守", "#00e676"
        else:
            short_status, short_color = "短線震盪觀望", "#ffcc00"
            
        if curr > ma20 and ma5 > ma10 and osc > 0 and 50 <= rsi14 <= 75:
            mid_status, mid_color = "波段偏多", "#ff3b3b"
        elif curr < ma20 and ma5 < ma10 and osc < 0:
            mid_status, mid_color = "波段偏空", "#00e676"
        else:
            mid_status, mid_color = "波段整理", "#ffcc00"
            
        long_status, long_color = "長線資料不足", "#aaa"
        if has_fund and not pd.isna(eps) and not pd.isna(roe) and not pd.isna(rev_growth):
            if eps > 0 and roe > 0.1 and rev_growth > 0:
                long_status, long_color = "長線偏多", "#ff3b3b"
            elif eps <= 0 or rev_growth < 0:
                long_status, long_color = "長線保守", "#00e676"
            else:
                long_status, long_color = "長線中性", "#ffcc00"

        reminder = "盤勢震盪，請嚴格控管資金與部位。"
        if "多" in short_status and "多" in mid_status:
            reminder = "偏多觀察，可等待回測 VWAP 或 MA5 附近是否有支撐。"
        elif "空" in short_status and "多" in mid_status:
            reminder = "波段仍可觀察，但短線轉弱，不建議追價。"
        elif "空" in short_status and "空" in mid_status:
            reminder = "偏保守，等待重新站回 VWAP 或 MA20。"
        elif "多" in short_status and "空" in mid_status:
            reminder = "短線有反彈跡象，但波段尚未翻多，淺嚐即止。"
            
        if long_status == "長線資料不足":
            reminder += "<br><span style='color:#aaa; font-size:13px;'>補充：基本面資料不足，長線判斷需保守看待。</span>"

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"<div class='card' style='border-top:4px solid {short_color}; height:100%;'><h4 style='color:#ccc; margin-bottom:5px;'>短線狀態</h4><div style='font-size:24px; font-weight:bold; color:{short_color};'>{short_status}</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='card' style='border-top:4px solid {mid_color}; height:100%;'><h4 style='color:#ccc; margin-bottom:5px;'>波段狀態</h4><div style='font-size:24px; font-weight:bold; color:{mid_color};'>{mid_status}</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='card' style='border-top:4px solid {long_color}; height:100%;'><h4 style='color:#ccc; margin-bottom:5px;'>長線狀態</h4><div style='font-size:24px; font-weight:bold; color:{long_color};'>{long_status}</div></div>", unsafe_allow_html=True)
        c4.markdown(f"<div class='card' style='border-top:4px solid #00E5FF; height:100%;'><h4 style='color:#ccc; margin-bottom:5px;'>操作提醒</h4><div style='font-size:16px; color:#fff;'>{reminder}</div></div>", unsafe_allow_html=True)
        
        st.markdown("---")

        bull_conds = []
        if curr >= vwap_val: bull_conds.append("現價站上 VWAP")
        if buy_pct_val > 0.55: bull_conds.append("主動買盤大於 55%")
        if whale_net > 0: bull_conds.append("大戶成交結構偏進貨")
        if has_foreign and f_sum_5 > 0: bull_conds.append("外資近5日買超")
        if not pd.isna(ma20) and curr >= ma20: bull_conds.append("現價站上 MA20")
        if not pd.isna(ma5) and not pd.isna(ma10) and ma5 > ma10: bull_conds.append("MA5 高於 MA10")
        if not pd.isna(osc) and osc > 0: bull_conds.append("MACD OSC 為正")
        if not pd.isna(rsi14) and 50 <= rsi14 <= 75: bull_conds.append("RSI 位於強勢區")
        if curr >= max_vol_p: bull_conds.append("現價高於大量成交價")
        
        bear_conds = []
        if curr < vwap_val: bear_conds.append("現價跌破 VWAP")
        if buy_pct_val < 0.45: bear_conds.append("主動買盤低於 45%")
        if whale_net < 0: bear_conds.append("大戶成交結構偏出貨")
        if has_foreign and f_sum_5 < 0: bear_conds.append("外資近5日賣超")
        if not pd.isna(ma20) and curr < ma20: bear_conds.append("現價跌破 MA20")
        if not pd.isna(ma5) and not pd.isna(ma10) and ma5 < ma10: bear_conds.append("MA5 低於 MA10")
        if not pd.isna(osc) and osc < 0: bear_conds.append("MACD OSC 為負")
        if not pd.isna(rsi14) and rsi14 > 80: bear_conds.append("RSI 過熱大於 80")
        if curr < max_vol_p: bear_conds.append("現價低於大量成交價")

        b1_col, b2_col = st.columns(2)
        with b1_col:
            st.markdown("<h4 style='color:#ff3b3b;'>✅ 多方條件</h4>", unsafe_allow_html=True)
            if not bull_conds:
                st.info("目前多方條件不足")
            else:
                h = "<div class='card'><ul style='color:#ccc; font-size:16px; line-height:1.8; margin-bottom:0;'>"
                for c in bull_conds[:6]: h += f"<li>{c}</li>"
                h += "</ul></div>"
                st.markdown(h, unsafe_allow_html=True)
        with b2_col:
            st.markdown("<h4 style='color:#00e676;'>⚠️ 空方風險</h4>", unsafe_allow_html=True)
            if not bear_conds:
                st.info("目前空方風險不明顯")
            else:
                h = "<div class='card'><ul style='color:#ccc; font-size:16px; line-height:1.8; margin-bottom:0;'>"
                for c in bear_conds[:6]: h += f"<li>{c}</li>"
                h += "</ul></div>"
                st.markdown(h, unsafe_allow_html=True)

        st.markdown("---")

        active_p = min(curr, vwap_val)
        steady_p = ma5 if not pd.isna(ma5) else vwap_val
        cons_p = ma20 if not pd.isna(ma20) else low20
        
        sl_short = min(vwap_val, max_vol_p) * 0.99
        sl_mid = (ma20 * 0.98) if not pd.isna(ma20) else (low20 * 0.98)
        sl_last = low20 * 0.97
        
        tp_1 = curr + (curr - sl_short)
        tp_2 = high20
        tp_3 = high20 * 1.05

        def safe_p(v): 
            return f"{v:.2f}" if not pd.isna(v) else "N/A"

        p1_col, p2_col = st.columns(2)
        with p1_col:
            st.markdown("<h4 style='color:#FFD700;'>💰 分批進場安全價格 (分批觀察價)</h4>", unsafe_allow_html=True)
            st.markdown(f"""
            <div class='card'>
                <ul style='color:#ccc; font-size:16px; line-height:2.0; list-style:none; padding-left:0; margin-bottom:0;'>
                    <li>⚡ <span style='color:#aaa;'>積極觀察價：</span> <strong style='color:#fff; font-size:18px;'>{safe_p(active_p)}</strong></li>
                    <li>🚶 <span style='color:#aaa;'>穩健觀察價：</span> <strong style='color:#fff; font-size:18px;'>{safe_p(steady_p)}</strong></li>
                    <li>🛡️ <span style='color:#aaa;'>保守觀察價：</span> <strong style='color:#fff; font-size:18px;'>{safe_p(cons_p)}</strong></li>
                    <li>📊 <span style='color:#aaa;'>大量成交價：</span> <strong style='color:#fff; font-size:18px;'>{safe_p(max_vol_p)}</strong></li>
                </ul>
                <div style='color:#888; font-size:13px; margin-top:10px;'>💡 這是依技術與量價推估的分批觀察區，不是保證買點。</div>
            </div>
            """, unsafe_allow_html=True)
            
        with p2_col:
            st.markdown("<h4 style='color:#00E5FF;'>🛡️ 停損停利 (參考)</h4>", unsafe_allow_html=True)
            st.markdown(f"""
            <div class='card'>
                <ul style='color:#ccc; font-size:16px; line-height:2.0; list-style:none; padding-left:0; margin-bottom:0;'>
                    <li>🚨 <span style='color:#aaa;'>短線停損：</span> <strong style='color:#00e676; font-size:18px;'>{safe_p(sl_short)}</strong></li>
                    <li>⚠️ <span style='color:#aaa;'>波段停損：</span> <strong style='color:#00e676; font-size:18px;'>{safe_p(sl_mid)}</strong></li>
                    <li>🛑 <span style='color:#aaa;'>最後防守：</span> <strong style='color:#00e676; font-size:18px;'>{safe_p(sl_last)}</strong></li>
                    <hr style='border-color:#333; margin:8px 0;'>
                    <li>🎯 <span style='color:#aaa;'>第一停利：</span> <strong style='color:#ff3b3b; font-size:18px;'>{safe_p(tp_1)}</strong></li>
                    <li>🚀 <span style='color:#aaa;'>第二停利：</span> <strong style='color:#ff3b3b; font-size:18px;'>{safe_p(tp_2)}</strong></li>
                    <li>🔥 <span style='color:#aaa;'>強勢停利：</span> <strong style='color:#ff3b3b; font-size:18px;'>{safe_p(tp_3)}</strong></li>
                </ul>
                <div style='color:#888; font-size:13px; margin-top:10px;'>💡 停損停利為風險控管參考，不構成買賣建議。</div>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("<br><div style='text-align:center; color:#ff3b3b; font-size:14px; background:#2a0a0a; padding:10px; border-radius:5px;'>⚠️ 本頁為規則型量化整理，僅供觀察參考，不構成任何買賣建議。</div>", unsafe_allow_html=True)

        
# =====================
# 🔐 管理後台
# =====================
elif page == "🔐 管理後台":
    st.markdown("## 🔐 使用紀錄後台")

    ADMIN_PASSWORD = read_secret_safe("ADMIN_PASSWORD", "")

    if not ADMIN_PASSWORD:
        st.warning("⚠️ 系統尚未設定管理員密碼 (ADMIN_PASSWORD)，請先至 Streamlit Secrets 進行設定。為保護資安，目前無法登入。")
    else:
        admin_pwd = st.text_input("請輸入管理密碼", type="password")

        if admin_pwd == ADMIN_PASSWORD:
            try:
                logs = []

                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        logs.append(json.loads(line))

                if not logs:
                    st.info("目前沒有使用紀錄")
                else:
                    log_df = pd.DataFrame(logs)

                    symbol_count = log_df["symbol"].value_counts().to_dict()
                    stock_name_count = log_df["stock_name"].value_counts().to_dict()

                    log_df["股票代號累積次數"] = log_df["symbol"].map(symbol_count)
                    log_df["股票名稱累積次數"] = log_df["stock_name"].map(stock_name_count)

                    display_df = log_df.rename(columns={
                        "time": "時間",
                        "visitor_id": "匿名訪客ID",
                        "page": "頁面",
                        "symbol": "股票代號",
                        "stock_name": "股票名稱",
                        "tf_label": "K線週期"
                    })

                    display_df = display_df[
                        [
                            "時間",
                            "匿名訪客ID",
                            "頁面",
                            "股票代號",
                            "股票代號累積次數",
                            "股票名稱",
                            "股票名稱累積次數",
                            "K線週期"
                        ]
                    ]

                    st.markdown("### 📊 使用概況")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("總紀錄數", len(log_df))
                    c2.metric("匿名訪客數", log_df["visitor_id"].nunique())
                    c3.metric("查詢股票數", log_df["symbol"].nunique())

                    st.markdown("### 🔥 股票代號查詢排行")

                    symbol_rank = (
                        log_df.groupby(["symbol", "stock_name"])
                        .size()
                        .reset_index(name="累積次數")
                        .sort_values("累積次數", ascending=False)
                    )

                    symbol_rank = symbol_rank.rename(columns={
                        "symbol": "股票代號",
                        "stock_name": "股票名稱"
                    })

                    st.dataframe(symbol_rank, use_container_width=True)

                    st.markdown("### 📌 頁面觀看排行")

                    page_rank = log_df["page"].value_counts().reset_index()
                    page_rank.columns = ["頁面", "累積次數"]

                    st.dataframe(page_rank, use_container_width=True)

                    st.markdown("### 🧾 最近使用紀錄")

                    st.dataframe(
                        display_df.sort_values("時間", ascending=False),
                        use_container_width=True
                    )

            except Exception as e:
                st.warning(f"目前沒有紀錄，或讀取失敗：{e}")

        elif admin_pwd:
            st.error("密碼錯誤")
        else:
            st.info("請輸入管理密碼")


# =====================
# 底部資訊 (庫存狀態僅 K線分析顯示)
# =====================
if page == "📊 K線分析":
    st.markdown("---")
    b1, b2 = st.columns([4, 6])

    with b1:
        pnl_c = "#ff3b3b" if profit > 0 else "#00e676" if profit < 0 else "#fff"
        st.markdown(
            f"""
            <div style='background:#111; padding:20px; border-radius:10px; border:1px solid #333; height:100%;'>
                <h3>💰 庫存狀態</h3>
                <p style='color:#aaa;'>{display_name}</p>
                <p style='color:#aaa;'>成本：{cost:.2f} ｜ 張數：{qty:.0f}</p>
                <p style='font-size:24px; color:{price_color(curr, prev_c)}; font-weight:bold;'>
                    現價：{curr:.2f} <span style='font-size:18px;'>({diff:+.2f} / {pct:+.2f}%)</span>
                </p>
                <h3>📊 總盈虧</h3>
                <div style='font-size:42px; font-weight:bold; color:{pnl_c};'>
                    {int(profit):,} 元
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with b2:
        st.markdown("### ⚖️ 即時五檔明細")
        render_order_book(bids, asks, prev_c, curr, api_key)

elif page == "⚡ 即時趨勢":
    st.markdown("---")
    st.markdown("### ⚖️ 即時五檔明細")
    render_order_book(bids, asks, prev_c, curr, api_key)
