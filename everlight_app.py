# =========================
# 股票名稱資料 (終極防呆混合版)
# =========================
@st.cache_data(ttl=86400)
def load_market_dict():

    market_dict = {}

    # ===== 1. 官方 OpenAPI 快速抓取 (最穩，防雲端擋 IP) =====
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=5)
        if r.status_code == 200:
            for i in r.json():
                market_dict[i["Code"]] = i["Name"]
                market_dict[i["Name"]] = i["Code"]
    except: pass

    try:
        r2 = requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=5)
        if r2.status_code == 200:
            for i in r2.json():
                code = i.get("SecuritiesCompanyCode") or i.get("Code")
                name = i.get("CompanyName") or i.get("Name")
                if code and name:
                    market_dict[code] = name
                    market_dict[name] = code
    except: pass

    # ===== 2. 上市 (ISIN 暴力解析法) =====
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        tables = pd.read_html(url)
        df = tables[0]
        for i in range(len(df)):
            try:
                raw = str(df.iloc[i,0]).strip()
                # 解決地雷：全形轉半形，並強制只切一刀
                parts = raw.replace("　", " ").split(maxsplit=1)
                if len(parts) == 2:
                    code, name = parts[0].strip(), parts[1].strip()
                    if code.isalnum(): # 確保代號是英數字組合
                        market_dict[code] = name
                        market_dict[name] = code
            except: pass
    except Exception as e:
        print("上市ISIN錯誤:", e)

    # ===== 3. 上櫃 (ISIN 暴力解析法) =====
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
    except Exception as e:
        print("上櫃ISIN錯誤:", e)

    # ===== 4. ETF補充保底 =====
    etf_extra = {
        "0050":"元大台灣50", "0056":"元大高股息", "006208":"富邦台50",
        "00878":"國泰永續高股息", "00919":"群益台灣精選高息",
        "00929":"復華台灣科技優息", "00940":"元大台灣價值高息",
        "00713":"元大高息低波", "00757":"統一FANG+", "00679B":"元大美債20年"
    }

    for k, v in etf_extra.items():
        market_dict[k] = v
        market_dict[v] = k

    return market_dict

MASTER_DICT = load_market_dict()
