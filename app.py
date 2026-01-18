import streamlit as st
import pandas as pd
import gspread
import os  # <--- 這就是剛剛說要補上的，用來檢查檔案是否存在
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date
from dateutil.relativedelta import relativedelta

# --- 1. 設定與連線函數 (兩棲版：支援本機與雲端) ---
@st.cache_resource
def get_google_sheet():
    # 設定權限範圍
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 策略 A：先試試看有沒有本機的 secrets.json 檔案
    # (os.path.exists 就是在問電腦：這個檔案在不在？)
    if os.path.exists("secrets.json"):
        creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
    
    # 策略 B：如果沒有檔案，就試試看讀取 Streamlit 雲端的 Secrets
    else:
        # 這裡的 "gcp_service_account" 是我們等一下要在雲端設定的名字
        key_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
        
    client = gspread.authorize(creds)
    sheet = client.open("warranty_db").sheet1
    return sheet

# --- 2. 讀取資料函數 ---
def load_data():
    try:
        sheet = get_google_sheet()
        # 抓取所有資料
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # 如果試算表是空的，回傳空清單
        if df.empty:
            return []
            
        # 處理日期格式 (因為從 Google 抓下來是文字，要轉回日期物件)
        # 檢查欄位是否存在，避免新表格報錯
        if 'buy_date' in df.columns:
            df['buy_date'] = pd.to_datetime(df['buy_date'])
        if 'expiry_date' in df.columns:
            df['expiry_date'] = pd.to_datetime(df['expiry_date'])
            
        return df.to_dict('records')
    except Exception as e:
        st.error(f"讀取資料失敗：{e}")
        return []

# --- 3. 儲存資料函數 (直接寫回 Google Sheets) ---
def save_to_google(data_list):
    try:
        sheet = get_google_sheet()
        
        if len(data_list) > 0:
            df = pd.DataFrame(data_list)
            
            # Google Sheets 看不懂 Python 的日期物件，要轉成字串 (YYYY-MM-DD)
            # 我們建立一個副本來轉換，不要影響原本的資料
            df_export = df.copy()
            df_export['buy_date'] = df_export['buy_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else "")
            df_export['expiry_date'] = df_export['expiry_date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notnull(x) else "")
            
            # 清空試算表，重新寫入 (這是最簡單的更新方法)
            sheet.clear()
            # 寫入標題和內容 ([df.columns.values.tolist()] 是標題, df.values.tolist() 是內容)
            sheet.update([df_export.columns.values.tolist()] + df_export.values.tolist())
        else:
            # 如果資料被刪光了，就只清空試算表
            sheet.clear()
            
    except Exception as e:
        st.error(f"儲存失敗：{e}")

# ==========================================
#      主程式開始
# ==========================================
st.set_page_config(page_title="雲端保固管家", layout="wide")
🔒 密碼鎖功能 (新增這一段)
# ==========================================
def check_password():
    """檢查密碼是否正確，不正確則停止執行"""
    
    # 驗證密碼的內部函數
    def password_entered():
        if st.session_state["password"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 驗證成功後刪除密碼，不留痕跡
        else:
            st.session_state["password_correct"] = False

    # 初始化狀態
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    # 如果已經驗證通過，就回傳 True，讓程式繼續跑
    if st.session_state["password_correct"]:
        return True

    # 如果還沒通過，顯示輸入框
    st.title("🔒 請輸入家族密碼")
    st.text_input(
        "Password", 
        type="password", 
        on_change=password_entered, 
        key="password"
    )
    
    # 如果密碼打錯了，顯示錯誤訊息
    if "password_correct" in st.session_state and st.session_state["password_correct"] == False:
        st.error("😕 密碼錯誤，請再試一次")

    return False

# --- 呼叫檢查站 ---
# 如果 check_password() 回傳 False (代表沒過)，就執行 st.stop() 停在這裡
if not check_password():
    st.stop()
# 初始化
if 'products' not in st.session_state:
    with st.spinner('正在從 Google 雲端下載資料...'):
        st.session_state.products = load_data()

if 'edit_index' not in st.session_state:
    st.session_state.edit_index = None

# --- 側邊欄 ---
with st.sidebar:
    # 編輯模式
    if st.session_state.edit_index is not None:
        st.header("✏️ 編輯物品")
        st.info("資料將直接同步至 Google 雲端 ☁️")
        
        idx = st.session_state.edit_index
        # 確保索引沒有超出範圍
        if idx < len(st.session_state.products):
            item_to_edit = st.session_state.products[idx]
            
            # 處理日期 (如果是 Timestamp 要轉 date)
            try:
                old_buy_date = item_to_edit['buy_date'].date()
            except:
                old_buy_date = pd.to_datetime(item_to_edit['buy_date']).date()

            new_name = st.text_input("物品名稱", value=item_to_edit['name'])
            new_buy_date = st.date_input("購買日期", value=old_buy_date)
            
            # 推算舊年限
            try:
                old_expiry = item_to_edit['expiry_date'].date()
            except:
                old_expiry = pd.to_datetime(item_to_edit['expiry_date']).date()
                
            years_diff = old_expiry.year - old_buy_date.year
            new_warranty_years = st.number_input("保固年限 (年)", min_value=0, max_value=10, value=years_diff)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("💾 雲端存檔", type="primary"):
                    with st.spinner('正在寫入 Google Sheets...'):
                        new_expiry = pd.to_datetime(new_buy_date) + relativedelta(years=new_warranty_years)
                        
                        updated_item = {
                            "name": new_name,
                            "buy_date": pd.to_datetime(new_buy_date),
                            "expiry_date": new_expiry
                        }
                        
                        st.session_state.products[idx] = updated_item
                        save_to_google(st.session_state.products)
                        
                        st.session_state.edit_index = None
                        st.success("更新成功！")
                        st.rerun()
                    
            with col2:
                if st.button("❌ 取消"):
                    st.session_state.edit_index = None
                    st.rerun()

    # 新增模式
    else:
        st.header("☁️ 新增至雲端資料庫")
        
        name = st.text_input("物品名稱", placeholder="例如：Dyson 吸塵器")
        buy_date = st.date_input("購買日期", value=date.today())
        warranty_years = st.number_input("保固年限 (年)", min_value=0, max_value=10, value=2)
        
        if st.button("➕ 新增", type="primary"):
            if name:
                with st.spinner('正在上傳到 Google...'):
                    expiry_date = pd.to_datetime(buy_date) + relativedelta(years=warranty_years)
                    
                    new_item = {
                        "name": name,
                        "buy_date": pd.to_datetime(buy_date),
                        "expiry_date": expiry_date
                    }
                    
                    st.session_state.products.append(new_item)
                    save_to_google(st.session_state.products)
                    
                    st.success(f"已儲存：{name}")
                    st.rerun()
            else:
                st.error("請輸入物品名稱喔！")

# --- 主畫面 ---
st.title("☁️ 雲端保固管家")
st.caption("資料來源：Google Sheets (warranty_db)")

if len(st.session_state.products) == 0:
    st.info("👈 目前雲端資料庫是空的，試著新增一筆看看！")

else:
    cols = st.columns(3)
    for index, item in enumerate(st.session_state.products):
        col = cols[index % 3]
        with col:
            st.markdown(f"### {item['name']}")
            
            # 日期計算
            try:
                expiry_date_val = item['expiry_date'].date()
            except: # 如果已經是 date 物件
                expiry_date_val = pd.to_datetime(item['expiry_date']).date()

            days_left = (expiry_date_val - date.today()).days
            
            if days_left < 0:
                st.markdown(f":red[**❌ 已過期 {abs(days_left)} 天**]")
            elif days_left < 30:
                st.markdown(f":orange[**⚠️ 剩餘 {days_left} 天**]")
            else:
                st.markdown(f":green[**✅ 剩餘 {days_left} 天**]")
            
            try:
                buy_date_str = item['buy_date'].strftime('%Y-%m-%d')
            except:
                buy_date_str = pd.to_datetime(item['buy_date']).strftime('%Y-%m-%d')
                
            st.text(f"購買日：{buy_date_str}")
            st.text(f"到期日：{expiry_date_val.strftime('%Y-%m-%d')}")
            
            b_col1, b_col2 = st.columns([1, 1])
            with b_col1:
                if st.button("✏️ 編輯", key=f"edit_{index}"):
                    st.session_state.edit_index = index
                    st.rerun()
            
            with b_col2:
                if st.button("🗑️ 刪除", key=f"del_{index}"):
                    with st.spinner('正在從 Google 刪除...'):
                        st.session_state.products.pop(index)
                        save_to_google(st.session_state.products)
                        if st.session_state.edit_index == index:
                            st.session_state.edit_index = None
                        st.rerun()
            
            st.divider()