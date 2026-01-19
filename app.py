import streamlit as st
import pandas as pd
import gspread
import os
import requests
from oauth2client.service_account import ServiceAccountCredentials
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
#      ☁️ Google Sheet 連線 & ImgBB 上傳
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
    """將圖片上傳到 ImgBB 並回傳連結 (取代 Imgur)"""
    if file_obj is None:
        return ""
    
    try:
        api_key = st.secrets["imgbb_api_key"] # 從 Secrets 拿 ID
        
        # 準備上傳
        payload = {
            "key": api_key,
        }
        files = {
            "image": file_obj.getvalue()
        }
        
        response = requests.post("https://api.imgbb.com/1/upload", data=payload, files=files)
        
        # 檢查結果
        if response.status_code == 200:
            return response.json()['data']['url'] # 回傳圖片網址
        else:
            st.error(f"上傳失敗，錯誤代碼：{response.status_code}")
            return ""
            
    except Exception as e:
        st.error(f"連線錯誤：{e}")
        return ""

# --- 讀取資料 ---
def load_data():
    try:
        sheet = get_google_sheet()
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if df.empty: return []
        
        if 'product_img' not in df.columns: df['product_img'] = ""
        if 'warranty_img' not in df.columns: df['warranty_img'] = ""
        
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

# --- 新增區塊 ---
with st.expander("➕ 新增物品 (點我展開)", expanded=True):
    col1, col2 = st.columns([1, 1])
    
    with col1:
        name = st.text_input("物品名稱", placeholder="例如：Dyson 吸塵器")
        buy_date = st.date_input("購買日期", value=date.today())
        warranty_years = st.number_input("保固年限 (年)", min_value=0, max_value=10, value=2)
    
    with col2:
        st.markdown("##### 📸 照片上傳")
        st.caption("照片將存放在 ImgBB 圖床")
        product_file = st.file_uploader("1. 產品外觀照片", type=['png', 'jpg', 'jpeg'])
        warranty_file = st.file_uploader("2. 保固卡/發票照片", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 新增至雲端", type="primary"):
        if name:
            with st.spinner('正在上傳照片並存檔...'):
                expiry_date = pd.to_datetime(buy_date) + relativedelta(years=warranty_years)
                
                # 改用 ImgBB 上傳
                p_link = upload_to_imgbb(product_file) if product_file else ""
                w_link = upload_to_imgbb(warranty_file) if warranty_file else ""
                
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
        else:
            st.error("請輸入名稱！")

st.divider()

# --- 清單顯示區 ---
st.subheader(f"📦 目前共有 {len(st.session_state.products)} 樣物品")

if len(st.session_state.products) > 0:
    for index, item in enumerate(st.session_state.products):
        with st.container():
            try:
                expiry_val = item['expiry_date'].date()
            except:
                expiry_val = pd.to_datetime(item['expiry_date']).date()
            
            days_left = (expiry_val - date.today()).days
            status_color = "green" if days_left >= 30 else "orange" if days_left >= 0 else "red"
            status_text = f"✅ 剩餘 {days_left} 天" if days_left >= 0 else f"❌ 已過期 {abs(days_left)} 天"
            
            st.markdown(f"### {item['name']} <span style='color:{status_color}; font-size:0.8em'>({status_text})</span>", unsafe_allow_html=True)
            
            c1, c2 = st.columns([1, 2])
            with c1:
                st.caption(f"購買日：{pd.to_datetime(item['buy_date']).strftime('%Y-%m-%d')}")
                st.caption(f"到期日：{expiry_val.strftime('%Y-%m-%d')}")
                
                if st.button("🗑️ 刪除", key=f"del_{index}"):
                    st.session_state.products.pop(index)
                    save_to_google(st.session_state.products)
                    st.rerun()
            
            with c2:
                # 檢查是否有連結
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