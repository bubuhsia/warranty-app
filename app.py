import streamlit as st
import pandas as pd
import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import date
from dateutil.relativedelta import relativedelta

# --- 1. 設定頁面 ---
st.set_page_config(page_title="雲端保固管家", layout="wide")

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
#      ☁️ Google 服務連線區 (Sheet + Drive)
# ==========================================
@st.cache_resource
def get_creds():
    scope = [
        "https://spreadsheets.google.com/feeds", 
        "https://www.googleapis.com/auth/drive"
    ]
    if os.path.exists("secrets.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
    else:
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    return creds

def get_google_sheet():
    creds = get_creds()
    client = gspread.authorize(creds)
    sheet = client.open("warranty_db").sheet1
    return sheet

def upload_image_to_drive(file_obj, filename):
    """將圖片上傳到 Google Drive 並回傳連結"""
    if file_obj is None:
        return ""
    
    try:
        creds = get_creds()
        drive_service = build('drive', 'v3', credentials=creds)
        folder_id = st.secrets["drive_folder_id"] # 從 Secrets 拿資料夾 ID

        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type)
        
        file = drive_service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webContentLink'
        ).execute()
        
        # 回傳可以直接看的連結
        return file.get('webContentLink')
    except Exception as e:
        st.error(f"圖片上傳失敗：{e}")
        return ""

# --- 讀取資料 ---
def load_data():
    try:
        sheet = get_google_sheet()
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty: return []
        
        # 確保有圖片欄位，沒有就補空字串
        if 'product_img' not in df.columns: df['product_img'] = ""
        if 'warranty_img' not in df.columns: df['warranty_img'] = ""
        
        # 日期轉換
        if 'buy_date' in df.columns:
            df['buy_date'] = pd.to_datetime(df['buy_date'])
        if 'expiry_date' in df.columns:
            df['expiry_date'] = pd.to_datetime(df['expiry_date'])
            
        return df.to_dict('records')
    except Exception as e:
        st.error(f"讀取資料失敗：{e}")
        return []

# --- 存檔 ---
def save_to_google(data_list):
    try:
        sheet = get_google_sheet()
        if len(data_list) > 0:
            df = pd.DataFrame(data_list)
            df_export = df.copy()
            # 轉字串存入 Sheets
            df_export['buy_date'] = df_export['buy_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else "")
            df_export['expiry_date'] = df_export['expiry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else "")
            
            sheet.clear()
            sheet.update([df_export.columns.values.tolist()] + df_export.values.tolist())
        else:
            sheet.clear()
    except Exception as e:
        st.error(f"儲存失敗：{e}")

# ==========================================
#      主程式 UI
# ==========================================
if 'products' not in st.session_state:
    with st.spinner('正在連線雲端資料庫...'):
        st.session_state.products = load_data()

# --- 新增區塊 (放在最上面) ---
with st.expander("➕ 新增物品 (點我展開)", expanded=True):
    col1, col2 = st.columns([1, 1])
    
    with col1:
        name = st.text_input("物品名稱", placeholder="例如：Dyson 吸塵器")
        buy_date = st.date_input("購買日期", value=date.today())
        warranty_years = st.number_input("保固年限 (年)", min_value=0, max_value=10, value=2)
    
    with col2:
        # 分開上傳：產品照 vs 保固卡
        st.markdown("##### 📸 照片上傳")
        product_file = st.file_uploader("1. 產品外觀照片", type=['png', 'jpg', 'jpeg'])
        warranty_file = st.file_uploader("2. 保固卡/發票照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 新增至雲端", type="primary"):
        if name:
            with st.spinner('正在上傳照片並存檔...'):
                # 1. 計算日期
                expiry_date = pd.to_datetime(buy_date) + relativedelta(years=warranty_years)
                
                # 2. 上傳照片 (如果有的話)
                p_link = ""
                w_link = ""
                if product_file:
                    p_link = upload_image_to_drive(product_file, f"{name}_產品_{date.today()}.jpg")
                if warranty_file:
                    w_link = upload_image_to_drive(warranty_file, f"{name}_保固_{date.today()}.jpg")
                
                # 3. 建立資料
                new_item = {
                    "name": name,
                    "buy_date": pd.to_datetime(buy_date),
                    "expiry_date": expiry_date,
                    "product_img": p_link,   # 新增欄位
                    "warranty_img": w_link   # 新增欄位
                }
                
                st.session_state.products.append(new_item)
                save_to_google(st.session_state.products)
                
                st.success(f"已儲存：{name}")
                st.rerun()
        else:
            st.error("請輸入名稱！")

st.divider()

# --- 清單顯示區 ---
st.subheader(f"📦 目前共有 {len(st.session_state.products)} 樣物品")

if len(st.session_state.products) > 0:
    # 把它變成卡片式排列
    for index, item in enumerate(st.session_state.products):
        with st.container():
            # 標題與過期計算
            try:
                expiry_val = item['expiry_date'].date()
            except:
                expiry_val = pd.to_datetime(item['expiry_date']).date()
            
            days_left = (expiry_val - date.today()).days
            
            # 卡片頭部
            status_color = "green" if days_left >= 30 else "orange" if days_left >= 0 else "red"
            status_text = f"✅ 剩餘 {days_left} 天" if days_left >= 0 else f"❌ 已過期 {abs(days_left)} 天"
            
            st.markdown(f"### {item['name']} <span style='color:{status_color}; font-size:0.8em'>({status_text})</span>", unsafe_allow_html=True)
            
            # 內容分兩欄：左邊文字，右邊照片
            c1, c2 = st.columns([1, 2])
            
            with c1:
                st.caption(f"購買日：{pd.to_datetime(item['buy_date']).strftime('%Y-%m-%d')}")
                st.caption(f"到期日：{expiry_val.strftime('%Y-%m-%d')}")
                
                if st.button("🗑️ 刪除", key=f"del_{index}"):
                    st.session_state.products.pop(index)
                    save_to_google(st.session_state.products)
                    st.rerun()
            
            with c2:
                # 顯示照片 (分頁籤顯示，比較整齊)
                # 檢查是否有照片
                has_p = item.get('product_img') and item['product_img'].startswith('http')
                has_w = item.get('warranty_img') and item['warranty_img'].startswith('http')
                
                if has_p or has_w:
                    tab1, tab2 = st.tabs(["📦 產品照", "🧾 保固卡"])
                    with tab1:
                        if has_p:
                            st.image(item['product_img'], use_container_width=True)
                        else:
                            st.info("無照片")
                    with tab2:
                        if has_w:
                            st.image(item['warranty_img'], use_container_width=True)
                        else:
                            st.info("無照片")
            
            st.divider()