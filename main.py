import streamlit as st
import pandas as pd
import requests
import os
import altair as alt
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# --- 0. Streamlit 頁面設定 (必須在最前面) ---
st.set_page_config(page_title="工廠生產管理系統 V4.2.1", layout="wide")

# --- 1. 系統常數與時區設定 ---
TAIWAN_TZ = ZoneInfo("Asia/Taipei")
DB_FILE = 'factory_db.csv'
SETTING_FILE = 'settings.csv'
DEFAULT_EMPS = ["劉信佑", "詹聰實", "李昱緯", "陳思豪"]
PROD_TYPES = ["正常生產", "插件", "NG重修", "重製"]

# STANDARD_COLS 標準欄位定義
STANDARD_COLS = [
    '工單ID', '日期', '填寫人', '生產類型', '圖號', '預估工時',
    '實際工時', '開始時間', '結束時間', '工作區間工時',
    '累積工作區間工時', '最後恢復時間', '暫停時間', '暫停原因',
    '時間差異', '狀態', '備註'
]

# 讀取 LINE Messaging API Secrets
try:
    LINE_CHANNEL_ACCESS_TOKEN = st.secrets.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    LINE_TO_ID = st.secrets.get("LINE_TO_ID", "")
except Exception:
    LINE_CHANNEL_ACCESS_TOKEN = ""
    LINE_TO_ID = ""

# --- 2. 核心功能函式 ---

def normalize_db_df(df):
    """資料表型態保護，避免時間字串被判定為 float 報錯"""
    num_cols = ['預估工時', '實際工時', '工作區間工時', '累積工作區間工時', '時間差異']
    for c in df.columns:
        if c in num_cols:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
        else:
            df[c] = df[c].fillna("").astype(str)
    return df

def parse_taiwan_time(value):
    """時間解析核心邏輯：支援多種格式並穩定轉換為台灣時區"""
    try:
        if pd.isna(value) or str(value).strip() == "":
            return pd.NaT
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return pd.NaT
        if dt.tzinfo is None:
            return dt.tz_localize(TAIWAN_TZ)
        else:
            return dt.tz_convert(TAIWAN_TZ)
    except Exception:
        return pd.NaT

def init_files():
    """初始化並整理舊資料欄位遷移與新欄位補齊"""
    if not os.path.exists(SETTING_FILE):
        pd.DataFrame({"員工名字": DEFAULT_EMPS}).to_csv(SETTING_FILE, index=False)
    
    if not os.path.exists(DB_FILE):
        pd.DataFrame(columns=STANDARD_COLS).to_csv(DB_FILE, index=False)
    else:
        try:
            df = normalize_db_df(pd.read_csv(DB_FILE))
            if '生產類型' in df.columns:
                df['生產類型'] = df['生產類型'].replace({'NG修復': 'NG重修'})
            
            if '在公司工時' in df.columns:
                if '工作區間工時' not in df.columns:
                    df = df.rename(columns={'在公司工時': '工作區間工時'})
                else:
                    df['工作區間工時'] = pd.to_numeric(df['工作區間工時'].replace('', 0), errors='coerce').fillna(0)
                    old_hours = pd.to_numeric(df['在公司工時'], errors='coerce').fillna(0)
                    df.loc[(df['工作區間工時'] == 0) & (old_hours > 0), '工作區間工時'] = old_hours
                    df = df.drop(columns=['在公司工時'])

            for c in STANDARD_COLS:
                if c not in df.columns:
                    if c in ['預估工時', '實際工時', '工作區間工時', '累積工作區間工時', '時間差異']: 
                        df[c] = 0.0
                    elif c == '狀態': 
                        df[c] = '已完成'
                    elif c == '工單ID': 
                        df[c] = df.index.map(lambda x: f"WO-OLD-{x}")
                    else: 
                        df[c] = ""
            
            df = df[STANDARD_COLS]
            df.to_csv(DB_FILE, index=False)
        except Exception as e:
            st.error(f"初始化資料庫失敗: {e}")

def load_employees():
    if os.path.exists(SETTING_FILE):
        try:
            df = pd.read_csv(SETTING_FILE)
            emps = df["員工名字"].dropna().astype(str).str.strip().tolist()
            return list(dict.fromkeys([e for e in emps if e]))
        except: return DEFAULT_EMPS
    return DEFAULT_EMPS

def get_diff_color(x):
    if x > 0: return "red"
    elif x < 0: return "green"
    else: return "gray"

def send_line_message(msg):
    """使用 LINE Messaging API 發送通知，並回傳詳細結果"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return False, "LINE_CHANNEL_ACCESS_TOKEN 尚未設定"
    if not LINE_TO_ID:
        return False, "LINE_TO_ID 尚未設定"
    try:
        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "to": LINE_TO_ID,
            "messages": [{"type": "text", "text": msg}]
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=5)
        
        if resp.status_code == 200:
            return True, ""
        else:
            return False, f"LINE API 回傳錯誤：HTTP {resp.status_code}，內容：{resp.text}"
    except Exception as e:
        return False, f"LINE 發送例外錯誤：{e}"

def send_unfinished_work_orders_reminder(trigger_label="定時檢查"):
    """定時檢查與推播未結案工單"""
    try:
        if not os.path.exists(DB_FILE):
            return

        df = normalize_db_df(pd.read_csv(DB_FILE))
        unfinished_df = df[df['狀態'].isin(['進行中', '暫停中'])]
        
        now_dt = datetime.now(TAIWAN_TZ)
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        if unfinished_df.empty:
            msg = (f"✅ 工單檢查通知\n"
                   f"提醒類型：{trigger_label}\n"
                   f"目前沒有未結案工單。\n"
                   f"時間：台灣時間 {now_str}")
        else:
            msg = (f"🔔 未結案工單提醒\n"
                   f"提醒類型：{trigger_label}\n"
                   f"時間：台灣時間 {now_str}\n\n"
                   f"目前仍有以下工單尚未完成：")
            
            count = 1
            for _, row in unfinished_df.iterrows():
                status = row['狀態']
                
                if status == '進行中':
                    resume_dt = parse_taiwan_time(row.get('最後恢復時間', ''))
                    if pd.isna(resume_dt):
                        resume_dt = parse_taiwan_time(row['開始時間'])
                    
                    if pd.isna(resume_dt):
                        segment_h = 0.0
                    else:
                        segment_h = round((now_dt - resume_dt).total_seconds() / 3600, 2)
                        segment_h = max(0.0, segment_h)
                        
                    old_acc = pd.to_numeric(row.get('累積工作區間工時', 0), errors='coerce')
                    if pd.isna(old_acc): old_acc = 0.0
                    current_total_h = round(old_acc + segment_h, 2)
                    
                    msg += (f"\n\n{count}. 人員：{row['填寫人']}\n"
                            f"   狀態：{status}\n"
                            f"   類型：{row['生產類型']}\n"
                            f"   圖號：{row['圖號']}\n"
                            f"   開始時間：{row['開始時間']}\n"
                            f"   累積工作區間：{current_total_h}h")
                            
                elif status == '暫停中':
                    old_acc = pd.to_numeric(row.get('累積工作區間工時', 0), errors='coerce')
                    if pd.isna(old_acc): old_acc = 0.0
                    current_total_h = round(old_acc, 2)
                    pause_reason = row.get('暫停原因', '未填寫')
                    
                    msg += (f"\n\n{count}. 人員：{row['填寫人']}\n"
                            f"   狀態：{status}\n"
                            f"   類型：{row['生產類型']}\n"
                            f"   圖號：{row['圖號']}\n"
                            f"   開始時間：{row['開始時間']}\n"
                            f"   暫停原因：{pause_reason}\n"
                            f"   累積工作區間：{current_total_h}h")
                count += 1

        line_ok, line_error = send_line_message(msg)
        if not line_ok:
            print(f"未結案提醒推播失敗 ({trigger_label})：{line_error}")
        else:
            print(f"未結案提醒推播成功 ({trigger_label})")

    except Exception as e:
        print(f"未結案提醒發生例外錯誤：{e}")

# --- 背景排程初始化 (確保只啟動一次) ---
@st.cache_resource
def init_scheduler():
    scheduler = BackgroundScheduler(timezone=TAIWAN_TZ)
    scheduler.add_job(send_unfinished_work_orders_reminder, CronTrigger(hour=16, minute=55), args=["下班前 16:55 檢查"])
    scheduler.add_job(send_unfinished_work_orders_reminder, CronTrigger(hour=18, minute=0), args=["下班後 18:00 檢查"])
    scheduler.add_job(send_unfinished_work_orders_reminder, CronTrigger(hour=21, minute=0), args=["晚上 21:00 加班檢查"])
    scheduler.start()
    return scheduler

# 初始化檔案與排程
init_files()
init_scheduler()

# --- 3. 網頁 UI 介面 ---
with st.sidebar:
    st.title("⚙️ 系統設定")
    is_print_mode = st.checkbox("🖨️ 開啟列印月報模式", value=False)
    
    if not is_print_mode:
        st.divider()
        with st.expander("👤 人員名單維護"):
            current_list = load_employees()
            new_emp = st.text_input("新增員工姓名").strip()
            if st.button("確認新增"):
                if not new_emp: st.warning("請輸入姓名。")
                elif new_emp in current_list: st.error("姓名已在名單中。")
                else:
                    pd.DataFrame({"員工名字": current_list + [new_emp]}).to_csv(SETTING_FILE, index=False)
                    st.success(f"已新增：{new_emp}"); st.rerun()
        
        st.divider()
        st.subheader("💬 LINE 通知設定狀態")
        if LINE_CHANNEL_ACCESS_TOKEN: st.write("✅ LINE Token 已設定")
        else: st.write("❌ LINE_CHANNEL_ACCESS_TOKEN 尚未設定")

        if LINE_TO_ID: st.write("✅ LINE_TO_ID 已設定")
        else: st.write("❌ LINE_TO_ID 尚未設定")

        st.write("🕓 未結案提醒：每日 16:55、18:00、21:00 自動推播")

        st.caption("""
        **LINE_TO_ID 可以是：**
        1. 主管個人的 userId
        2. 公司 LINE 群組的 groupId
        3. 多人聊天室的 roomId
        """)

        if st.button("📩 測試 LINE 通知"):
            now_str = datetime.now(TAIWAN_TZ).strftime('%Y-%m-%d %H:%M:%S')
            test_msg = f"\n測試通知：\n工廠生產管理系統 LINE Messaging API 已連線成功。\n時間：台灣時間 {now_str}"
            
            line_ok, line_error = send_line_message(test_msg)
            if line_ok:
                st.success("✅ LINE 測試通知已送出")
            else:
                st.error("❌ LINE 測試通知失敗")
                st.caption(line_error)
                
        # 手動未結案提醒按鈕
        if st.button("🔔 測試未結案工單提醒"):
            send_unfinished_work_orders_reminder("手動測試")
            st.success("✅ 未結案工單提醒指令已送出！(請檢查 LINE 或終端機)")

if not is_print_mode:
    tab1, tab2 = st.tabs(["🏗️ 現場報工填寫", "📊 主管數據看板"])
else:
    tab1, tab2 = st.empty(), st.container()

# --- 頁籤 1：現場報工填寫 ---
if not is_print_mode:
    with tab1:
        st.header("現場即時加工報工")
        emps = load_employees()
        db_df = normalize_db_df(pd.read_csv(DB_FILE))
        
        st.subheader("🆕 開始新工單")
        with st.container(border=True):
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                s_name = st.selectbox("填寫人", emps, key="s_name")
                s_type = st.selectbox("生產類型", PROD_TYPES, key="s_type")
            with col_s2:
                s_drawing = st.text_input("圖號 / 工單", key="s_drawing").strip()
                s_est = st.number_input("預估工時 (hrs)", min_value=0.0, step=0.1, key="s_est")
            
            if st.button("▶️ 開始加工", type="primary"):
                if not s_drawing: st.error("❌ 請輸入圖號！")
                elif s_est <= 0: st.error("❌ 預估工時不可為 0！")
                else:
                    now = datetime.now(TAIWAN_TZ)
                    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
                    wo_id = f"WO-{now.strftime('%Y%m%d%H%M%S%f')}"
                    new_entry = {
                        '工單ID': wo_id, '日期': now.strftime("%Y-%m-%d"), '填寫人': s_name,
                        '生產類型': s_type, '圖號': s_drawing, '預估工時': s_est,
                        '實際工時': 0.0, '開始時間': now_str,
                        '結束時間': "", '工作區間工時': 0.0,
                        '累積工作區間工時': 0.0, '最後恢復時間': now_str, '暫停時間': "", '暫停原因': "",
                        '時間差異': 0.0, '狀態': '進行中', '備註': ""
                    }
                    pd.DataFrame([new_entry], columns=STANDARD_COLS).to_csv(DB_FILE, mode='a', index=False, header=False)
                    st.success(f"✅ 工單已啟動！ID: {wo_id}"); st.rerun()

        st.divider()

        st.subheader("⏳ 進行中的工單查詢")
        filter_ongoing = st.selectbox("查看進行中工單", ["全部"] + emps, index=0)
        ongoing_df = db_df[db_df['狀態'] == '進行中'].copy()
        if filter_ongoing != "全部": ongoing_df = ongoing_df[ongoing_df['填寫人'] == filter_ongoing]
            
        if ongoing_df.empty:
            st.info(f"目前沒有 {filter_ongoing if filter_ongoing != '全部' else ''} 正在進行的工單。")
        else:
            for index, row in ongoing_df.iterrows():
                with st.expander(f"🛠️ {row['填寫人']} | {row['圖號']} ({row['生產類型']}) - 開始於 {row['開始時間']}"):
                    
                    resume_dt = parse_taiwan_time(row.get('最後恢復時間', ''))
                    if pd.isna(resume_dt):
                        resume_dt = parse_taiwan_time(row['開始時間'])
                    if pd.isna(resume_dt):
                        st.error("❌ 此工單時間格式異常，無法計算，請主管檢查。")
                        continue
                    
                    now_dt = datetime.now(TAIWAN_TZ)
                    segment_h = round((now_dt - resume_dt).total_seconds() / 3600, 2)
                    segment_h = max(0.0, segment_h)
                    
                    old_acc = pd.to_numeric(row.get('累積工作區間工時', 0), errors='coerce')
                    if pd.isna(old_acc): old_acc = 0.0
                    
                    current_total_h = round(old_acc + segment_h, 2)
                    
                    st.write(f"**工單ID:** `{row['工單ID']}`")
                    st.info(f"⏱️ 系統累積工作區間工時: {current_total_h} 小時")
                    
                    st.divider()
                    
                    st.markdown("### ⏸️ 暫停加工")
                    p_reason = st.selectbox("暫停原因", ["下班未完成", "臨時插件", "等料", "等主管確認", "機台異常", "其他"], key=f"pr_{row['工單ID']}")
                    if st.button("⏸️ 暫停加工", key=f"pb_{row['工單ID']}"):
                        current_db = normalize_db_df(pd.read_csv(DB_FILE))
                        mask = (current_db['工單ID'] == row['工單ID']) & (current_db['狀態'] == '進行中')
                        if not current_db[mask].empty:
                            pause_now = datetime.now(TAIWAN_TZ)
                            current_db.loc[mask, '累積工作區間工時'] = current_total_h
                            current_db.loc[mask, '狀態'] = '暫停中'
                            current_db.loc[mask, '暫停時間'] = pause_now.strftime("%Y-%m-%d %H:%M:%S")
                            current_db.loc[mask, '暫停原因'] = p_reason
                            
                            for c in STANDARD_COLS:
                                if c not in current_db.columns: current_db[c] = ""
                            current_db = current_db[STANDARD_COLS]
                            current_db.to_csv(DB_FILE, index=False)
                            st.success(f"⏸️ 工單已暫停，累積區間：{current_total_h}h"); st.rerun()
                        else: st.error("❌ 此工單可能已被修改。")
                    
                    st.divider()

                    st.markdown("### ✅ 加工完成 / 結束結案")
                    e_act = st.number_input(
                        "實際加工工時 (hrs)", min_value=0.1, 
                        value=max(0.1, float(current_total_h)), 
                        step=0.1, key=f"act_{row['工單ID']}"
                    )
                    if e_act > current_total_h:
                        st.warning("⚠️ 實際加工工時大於系統累積工作區間工時，請確認是否填寫正確。")
                    
                    e_note = st.text_area(f"備註 / 異常原因", key=f"note_{row['工單ID']}")
                    
                    if st.button(f"✅ 加工完成並結案", key=f"btn_{row['工單ID']}", type="primary"):
                        if row['生產類型'] != "正常生產" and not e_note.strip():
                            st.error("❌ 異常件請務必填寫備註原因！")
                        else:
                            current_db = normalize_db_df(pd.read_csv(DB_FILE))
                            mask = (current_db['工單ID'] == row['工單ID']) & (current_db['狀態'] == '進行中')
                            if not current_db[mask].empty:
                                end_now = datetime.now(TAIWAN_TZ)
                                diff_time = round(current_total_h - e_act, 2)
                                
                                current_db.loc[mask, '結束時間'] = end_now.strftime("%Y-%m-%d %H:%M:%S")
                                current_db.loc[mask, '實際工時'] = e_act
                                current_db.loc[mask, '工作區間工時'] = current_total_h
                                current_db.loc[mask, '累積工作區間工時'] = current_total_h
                                current_db.loc[mask, '時間差異'] = diff_time
                                current_db.loc[mask, '狀態'] = '已完成'
                                current_db.loc[mask, '備註'] = e_note.strip()
                                
                                for c in STANDARD_COLS:
                                    if c not in current_db.columns: current_db[c] = ""
                                current_db = current_db[STANDARD_COLS]
                                current_db.to_csv(DB_FILE, index=False)
                                
                                line_ok = True
                                line_error = ""
                                if row['生產類型'] != "正常生產":
                                    line_ok, line_error = send_line_message(
                                        f"\n⚠️異常結案通知\n"
                                        f"類型：{row['生產類型']}\n"
                                        f"人員：{row['填寫人']}\n"
                                        f"圖號：{row['圖號']}\n"
                                        f"實際加工：{e_act}h\n"
                                        f"工作區間：{current_total_h}h\n"
                                        f"區間未加工：{diff_time}h\n"
                                        f"備註：{e_note.strip()}"
                                    )

                                if row['生產類型'] != "正常生產" and not line_ok:
                                    st.warning("⚠️ 工單已結案，但 LINE Messaging API 通知可能未成功送出。")
                                    st.caption(line_error)

                                st.success(f"✅ 已結案！區間：{current_total_h}h")
                                st.rerun()
                            else: st.error("❌ 此工單可能已被他人結束或暫停。")

        st.divider()
        st.subheader("⏸️ 暫停中的工單查詢")
        filter_paused = st.selectbox("查看暫停中工單", ["全部"] + emps, index=0, key="f_pause")
        pause_df = db_df[db_df['狀態'] == '暫停中'].copy()
        if filter_paused != "全部": pause_df = pause_df[pause_df['填寫人'] == filter_paused]
            
        if pause_df.empty:
            st.info(f"目前沒有 {filter_paused if filter_paused != '全部' else ''} 暫停中的工單。")
        else:
            for index, row in pause_df.iterrows():
                with st.container(border=True):
                    col_p1, col_p2 = st.columns([3, 1])
                    with col_p1:
                        st.write(f"**工單ID:** `{row['工單ID']}` | **人員:** {row['填寫人']}")
                        st.write(f"**圖號:** {row['圖號']} ({row['生產類型']}) | **開始於:** {row['開始時間']}")
                        st.error(f"⏸️ 暫停原因: {row.get('暫停原因', '未填寫')} (於 {row.get('暫停時間', '')})")
                        st.info(f"⏱️ 累積工作區間工時: {row.get('累積工作區間工時', 0.0)} 小時")
                    with col_p2:
                        st.write("") 
                        if st.button("▶️ 繼續加工", key=f"r_btn_{row['工單ID']}", type="primary", use_container_width=True):
                            current_db = normalize_db_df(pd.read_csv(DB_FILE))
                            mask = (current_db['工單ID'] == row['工單ID']) & (current_db['狀態'] == '暫停中')
                            if not current_db[mask].empty:
                                resume_now = datetime.now(TAIWAN_TZ)
                                current_db.loc[mask, '狀態'] = '進行中'
                                current_db.loc[mask, '最後恢復時間'] = resume_now.strftime("%Y-%m-%d %H:%M:%S")
                                
                                for c in STANDARD_COLS:
                                    if c not in current_db.columns: current_db[c] = ""
                                current_db = current_db[STANDARD_COLS]
                                current_db.to_csv(DB_FILE, index=False)
                                st.success("▶️ 已恢復加工！"); st.rerun()
                            else: st.error("❌ 狀態錯誤，無法繼續。")

# --- 頁籤 2：主管數據看板 ---
with tab2:
    if is_print_mode:
        st.markdown(f"<h1 style='text-align: center;'>工廠生產管理月報表 (V4.2.1) - {datetime.now(TAIWAN_TZ).strftime('%Y-%m-%d')}</h1>", unsafe_allow_html=True)
    else:
        st.title("📊 生產數據看板 (V4.2.1)")

    if os.path.exists(DB_FILE):
        full_df = normalize_db_df(pd.read_csv(DB_FILE))
        if '生產類型' in full_df.columns:
            full_df['生產類型'] = full_df['生產類型'].replace({'NG修復': 'NG重修'})
        
        full_df['開始時間'] = full_df['開始時間'].fillna("")
        full_df['開始時間_dt'] = full_df['開始時間'].apply(parse_taiwan_time)
        full_df = full_df.dropna(subset=['開始時間_dt'])
        
        full_df['日期_date'] = full_df['開始時間_dt'].dt.date
        full_df['年月'] = full_df['開始時間_dt'].dt.strftime('%Y-%m')
        full_df['月日'] = full_df['開始時間_dt'].dt.strftime('%m-%d')
        
        if full_df.empty:
            st.info("尚未有有效數據。"); st.stop()

        with st.container(border=not is_print_mode):
            c1, c2, c3, c4, c5 = st.columns([1.5, 2, 2, 2, 2])
            with c1: v_mode = st.radio("檢視模式", ["整體", "個人"], horizontal=True)
            with c2: s_emp = st.selectbox("員工篩選", load_employees(), disabled=(v_mode=="整體"))
            with c3: d_range = st.date_input("日期區間", [full_df['日期_date'].min(), full_df['日期_date'].max()])
            with c4: s_status = st.selectbox("工單狀態", ["已完成", "進行中", "暫停中", "全部"])
            with c5: s_type = st.selectbox("生產類型篩選", ["全部"] + PROD_TYPES)
        
        f_df = full_df.copy()
        if v_mode == "個人": f_df = f_df[f_df['填寫人'] == s_emp]
        if isinstance(d_range, (list, tuple)) and len(d_range) == 2:
            f_df = f_df[(f_df['日期_date'] >= d_range[0]) & (f_df['日期_date'] <= d_range[1])]
        if s_status != "全部": f_df = f_df[f_df['狀態'] == s_status]
        if s_type != "全部": f_df = f_df[f_df['生產類型'] == s_type]

        if f_df.empty: st.warning("目前篩選條件下沒有資料。"); st.stop()

        done_df = f_df[f_df['狀態'] == '已完成']
        ing_df = f_df[f_df['狀態'] == '進行中']
        pause_df = f_df[f_df['狀態'] == '暫停中']
        
        st.markdown("### 📌 關鍵指標彙總")
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("總工作區間", f"{round(done_df['工作區間工時'].sum(), 1)} h")
        k2.metric("總實際加工", f"{round(done_df['實際工時'].sum(), 1)} h")
        k3.metric("區間未加工時間", f"{round(done_df['時間差異'].sum(), 1)} h", delta_color="inverse")
        k4.metric("進行中工單", f"{len(ing_df)} 筆")
        k5.metric("暫停中工單", f"{len(pause_df)} 筆")
        k6.metric("已完成工單", f"{len(done_df)} 筆")

        if not pause_df.empty and not is_print_mode:
            st.warning("⏸️ 目前有暫停中工單，請確認是否為下班未完成、臨時插件、等料或其他原因。")
            show_cols = ['工單ID', '填寫人', '生產類型', '圖號', '開始時間', '暫停時間', '暫停原因', '累積工作區間工時']
            st.dataframe(pause_df[[c for c in show_cols if c in pause_df.columns]], use_container_width=True)

        with st.container(border=True):
            st.markdown("### 📈 數據分析戰情室")
            if s_status in ["進行中", "暫停中"]:
                st.warning(f"ℹ️ 狀態為「{s_status}」的工單尚未結案，暫不納入統計。")
            elif done_df.empty:
                st.info("目前沒有已完成工單，暫無正式圖表。")
            else:
                t_level = st.radio("分析層級", ["月統計", "日統計", "工單明細"], horizontal=True)
                if t_level == "月統計": x_field = "年月"
                elif t_level == "日統計": x_field = "月日"
                else: x_field = "工單ID"

                chart_df = done_df.groupby([x_field, '生產類型']).agg({'實際工時':'sum', '預估工時':'sum'}).reset_index()
                time_agg = done_df.groupby(x_field).agg({'實際工時':'sum', '預估工時':'sum'}).reset_index()
                time_agg['偏差'] = time_agg['實際工時'] - time_agg['預估工時']
                time_agg['標籤'] = time_agg['偏差'].apply(lambda x: f"{'+' if x>0 else ''}{round(x,1)}h")
                time_agg['偏差顏色'] = time_agg['偏差'].apply(get_diff_color)

                c_range = ['#1f77b4', '#ff7f0e', '#d62728', '#9467bd'] if not is_print_mode else ['#333', '#666', '#999', '#CCC']

                bars = alt.Chart(chart_df).mark_bar().encode(
                    x=alt.X(f'{x_field}:N', title='時間維度', axis=alt.Axis(labelAngle=-20)),
                    y=alt.Y('實際工時:Q', title='工時 (h)'),
                    xOffset=alt.XOffset('生產類型:N'),
                    color=alt.Color('生產類型:N', scale=alt.Scale(domain=PROD_TYPES, range=c_range))
                )
                
                line = alt.Chart(time_agg).mark_line(point=True, color='black').encode(
                    x=alt.X(f'{x_field}:N'),
                    y=alt.Y('預估工時:Q')
                )
                
                text = alt.Chart(time_agg).mark_text(dy=-15, fontWeight='bold').encode(
                    x=alt.X(f'{x_field}:N'), y='實際工時:Q', text='標籤:N',
                    color=alt.Color('偏差顏色:N', scale=None)
                )
                st.altair_chart((bars + line + text).properties(height=350), use_container_width=True)

        st.write("### 📅 每月彙總數據表")
        if not done_df.empty:
            pivot_df = done_df.pivot_table(index='年月', columns='生產類型', values='實際工時', aggfunc='sum').fillna(0)
            for col in PROD_TYPES:
                if col not in pivot_df.columns: pivot_df[col] = 0
            sum_df = done_df.groupby('年月').agg({'預估工時':'sum', '實際工時':'sum', '工作區間工時':'sum', '時間差異':'sum'})
            
            format_dict = {
                '預估工時': '{:.1f}', '實際工時': '{:.1f}', '工作區間工時': '{:.1f}',
                '時間差異': '{:.1f}', '正常生產': '{:.1f}', '插件': '{:.1f}',
                'NG重修': '{:.1f}', '重製': '{:.1f}'
            }
            st.dataframe(pd.concat([sum_df, pivot_df], axis=1).style.format(format_dict), use_container_width=True)

        st.write("### 🔍 詳細生產紀錄清單")
        show_df = f_df[[c for c in STANDARD_COLS if c in f_df.columns]]
        st.dataframe(show_df, use_container_width=True)
        
        if not is_print_mode:
            csv_data = show_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📥 下載篩選後 CSV 報表", 
                csv_data, 
                f"Report_{datetime.now(TAIWAN_TZ).strftime('%Y%m%d')}.csv", 
                "text/csv"
            )