import streamlit as st
import pandas as pd
import gspread
import os
import requests
import json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date
from dateutil.relativedelta import relativedelta

# --- 1. 設定頁面 ---
st.set_page_config(page_title="拍立保SnapSure", layout="wide")

# ==========================================
#      🔐 密碼鎖功能
# ==========================================
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    st.title("🔒 請輸入家族密碼")
    st.text_input("Password", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("😕 密碼錯誤，請再試一次")
    return False

if not check_password():
    st.stop()

# ==========================================
#      ☁️ Google Sheet & ImgBB & LINE Bot
# ==========================================
@st.cache_resource
def get_google_sheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if os.path.exists("secrets.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
    else:
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    
    client = gspread.authorize(creds)
    sheet = client.open("warranty_db").sheet1
    return sheet

def upload_to_imgbb(file_obj):
    if file_obj is None: return ""
    try:
        api_key = st.secrets["imgbb_api_key"]
        payload = {"key": api_key}
        files = {"image": file_obj.getvalue()}
        response = requests.post("https://api.imgbb.com/1/upload", data=payload, files=files)
        if response.status_code == 200:
            return response.json()['data']['url']
        return ""
    except Exception as e:
        st.error(f"連線錯誤：{e}")
        return ""

def send_line_message(message_text):
    try:
        token = st.secrets["line_access_token"]
        user_id = st.secrets["line_user_id"]
        url = "https://api.line.me/v2/bot/message/push"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
        data = {"to": user_id, "messages": [{"type": "text", "text": message_text}]}
        r = requests.post(url, headers=headers, data=json.dumps(data))
        return r.status_code == 200
    except Exception as e:
        st.error(f"LINE 發送失敗: {e}")
        return False

# --- 資料存取 ---
def load_data():
    try:
        sheet = get_google_sheet()
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty: return []
        for col in ['product_img', 'warranty_img']:
            if col not in df.columns: df[col] = ""
        for col in ['buy_date', 'expiry_date']:
            if col in df.columns: df[col] = pd.to_datetime(df[col])
        return df.to_dict('records')
    except Exception as e:
        st.error(f"讀取資料失敗：{e}")
        return []

def save_to_google(data_list):
    try:
        sheet = get_google_sheet()
        if len(data_list) > 0:
            df = pd.DataFrame(data_list)
            df_export = df.copy()
            df_export['buy_date'] = df_export['buy_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else "")
            df_export['expiry_date'] = df_export['expiry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else "")
            sheet.clear()
            sheet.update([df_export.columns.values.tolist()] + df_export.values.tolist())
        else:
            sheet.clear()
    except Exception as e:
        st.error(f"儲存失敗：{e}")

# ==========================================
#      ✨ 新功能：編輯視窗 (Dialog)
# ==========================================
@st.dialog("✏️ 編輯物品資料")
def edit_item_dialog(item, index):
    # 1. 顯示輸入框 (預設填入舊資料)
    new_name = st.text_input("物品名稱", value=item['name'])
    
    # 日期處理 (確保是 date 物件)
    try:
        default_date = pd.to_datetime(item['buy_date']).date()
    except:
        default_date = date.today()
        
    new_buy_date = st.date_input("購買日期", value=default_date)
    
    # 簡單計算舊的保固年限當作預設值 (如果不準確沒關係，讓用戶自己改)
    new_warranty_years = st.number_input("保固年限 (重新設定)", min_value=0, max_value=10, value=2)

    st.markdown("---")
    st.caption("👇 如果不想換照片，請留空即可 (會保留舊照片)")
    new_p_file = st.file_uploader("更新：產品照片", type=['png', 'jpg', 'jpeg'], key=f"new_p_{index}")
    new_w_file = st.file_uploader("更新：保固照片", type=['png', 'jpg', 'jpeg'], key=f"new_w_{index}")

    col1, col2 = st.columns(2)
    
    if col1.button("💾 儲存修改", type="primary"):
        with st.spinner("正在更新雲端資料..."):
            # 重新計算到期日
            new_expiry = pd.to_datetime(new_buy_date) + relativedelta(years=new_warranty_years)
            
            # 判斷照片：有新傳就用新的，沒傳就用舊的
            final_p_link = upload_to_imgbb(new_p_file) if new_p_file else item['product_img']
            final_w_link = upload_to_imgbb(new_w_file) if new_w_file else item['warranty_img']

            # 更新 Session State
            st.session_state.products[index] = {
                "name": new_name,
                "buy_date": pd.to_datetime(new_buy_date),
                "expiry_date": new_expiry,
                "product_img": final_p_link,
                "warranty_img": final_w_link
            }
            
            # 存回 Google Sheet
            save_to_google(st.session_state.products)
            st.rerun() # 關閉視窗並重新整理
            
    if col2.button("取消"):
        st.rerun()

# ==========================================
#      主程式 UI
# ==========================================
if 'products' not in st.session_state:
    with st.spinner('正在連線雲端資料庫...'):
        st.session_state.products = load_data()

# --- 側邊欄 (LINE 通知) ---
with st.sidebar:
    st.header("⚙️ 功能選單")
    if st.button("🔔 檢查即將到期物品"):
        msg_list = []
        count = 0
        for item in st.session_state.products:
            try:
                expiry_date = pd.to_datetime(item['expiry_date']).date()
                days_left = (expiry_date - date.today()).days
                if 0 <= days_left <= 30:
                    msg_list.append(f"⚠️ {item['name']} (剩 {days_left} 天)")
                    count += 1
                elif days_left < 0:
                     msg_list.append(f"❌ {item['name']} (已過期 {abs(days_left)} 天)")
                     count += 1
            except: continue
        
        if count > 0:
            full_msg = "【保固管家報告】\n" + "\n".join(msg_list)
            if send_line_message(full_msg): st.success(f"已發送通知！共 {count} 筆。")
            else: st.error("發送失敗")
        else: st.info("目前沒有快過期的物品！")

# --- 新增區塊 ---
with st.expander("➕ 新增物品 (點我展開)", expanded=False): # 預設改為收合，讓介面乾淨點
    c1, c2 = st.columns([1, 1])
    with c1:
        name = st.text_input("物品名稱", placeholder="例如：Dyson 吸塵器")
        buy_date = st.date_input("購買日期", value=date.today())
        warranty_years = st.number_input("保固年限 (年)", min_value=0, max_value=10, value=2)
    with c2:
        st.markdown("##### 📸 照片上傳")
        p_file = st.file_uploader("1. 產品外觀照片", type=['png', 'jpg', 'jpeg'])
        w_file = st.file_uploader("2. 保固卡/發票照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 新增至雲端", type="primary"):
        if name:
            with st.spinner('正在處理...'):
                expiry_date = pd.to_datetime(buy_date) + relativedelta(years=warranty_years)
                p_link = upload_to_imgbb(p_file) if p_file else ""
                w_link = upload_to_imgbb(w_file) if w_file else ""
                
                new_item = {
                    "name": name,
                    "buy_date": pd.to_datetime(buy_date),
                    "expiry_date": expiry_date,
                    "product_img": p_link,
                    "warranty_img": w_link
                }
                st.session_state.products.append(new_item)
                save_to_google(st.session_state.products)
                st.success(f"已儲存：{name}")
                st.rerun()
        else: st.error("請輸入名稱！")

st.divider()

# --- 清單顯示區 (含搜尋 & 篩選) ---
st.subheader("📦 物品清單")

# 1. 搜尋與篩選工具列
if len(st.session_state.products) > 0:
    col_search, col_filter = st.columns([2, 1])
    
    with col_search:
        search_term = st.text_input("🔍 搜尋物品", placeholder="輸入關鍵字...")
    
    with col_filter:
        filter_status = st.selectbox("⚡ 狀態篩選", ["全部顯示", "⚠️ 快過期 (30天內)", "❌ 已過期", "✅ 保固中"])

    # 2. 開始過濾資料
    display_list = []
    current_date = date.today()

    for item in st.session_state.products:
        # 先計算狀態
        try: 
            expiry_val = pd.to_datetime(item['expiry_date']).date()
            days_left = (expiry_val - current_date).days
        except: 
            continue # 日期格式錯誤就跳過

        # A. 關鍵字搜尋 (不分大小寫)
        if search_term:
            if search_term.lower() not in item['name'].lower():
                continue

        # B. 狀態篩選
        if filter_status == "⚠️ 快過期 (30天內)":
            if not (0 <= days_left <= 30): continue
        elif filter_status == "❌ 已過期":
            if days_left >= 0: continue
        elif filter_status == "✅ 保固中":
            if days_left < 0: continue

        # 通過篩選，加入顯示清單
        item['days_left'] = days_left 
        display_list.append(item)

    # 3. 顯示過濾後的結果
    st.caption(f"共找到 {len(display_list)} 筆資料")
    
    if len(display_list) > 0:
        for index, item in enumerate(display_list):
            # 找出原始清單中的位置
            real_index = st.session_state.products.index(item)
            
            # 【關鍵修正】這裡把 index 也加進去 key，確保絕對唯一
            unique_key_suffix = f"{real_index}_{index}"

            with st.container():
                days_left = item['days_left']
                status_color = "green" if days_left >= 30 else "orange" if days_left >= 0 else "red"
                status_text = f"✅ 剩餘 {days_left} 天" if days_left >= 0 else f"❌ 已過期 {abs(days_left)} 天"
                
                st.markdown(f"### {item['name']} <span style='color:{status_color}; font-size:0.8em'>({status_text})</span>", unsafe_allow_html=True)
                
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.caption(f"購買日：{pd.to_datetime(item['buy_date']).strftime('%Y-%m-%d')}")
                    st.caption(f"到期日：{pd.to_datetime(item['expiry_date']).strftime('%Y-%m-%d')}")
                    
                    b_col1, b_col2 = st.columns(2)
                    with b_col1:
                        # 使用新的唯一 Key
                        if st.button("✏️ 編輯", key=f"edit_{unique_key_suffix}"): 
                            edit_item_dialog(item, real_index)
                    with b_col2:
                        # 使用新的唯一 Key
                        if st.button("🗑️ 刪除", key=f"del_{unique_key_suffix}"): 
                            st.session_state.products.pop(real_index)
                            save_to_google(st.session_state.products)
                            st.rerun()

                with c2:
                    has_p = str(item.get('product_img', '')).startswith('http')
                    has_w = str(item.get('warranty_img', '')).startswith('http')
                    if has_p or has_w:
                        tab1, tab2 = st.tabs(["📦 產品照", "🧾 保固卡"])
                        with tab1:
                            if has_p: st.image(item['product_img'], use_container_width=True)
                            else: st.info("無照片")
                        with tab2:
                            if has_w: st.image(item['warranty_img'], use_container_width=True)
                            else: st.info("無照片")
                st.divider()
    else:
        st.info("🔍 找不到符合條件的物品")
else:
    st.info("目前還沒有任何物品，快去新增吧！")