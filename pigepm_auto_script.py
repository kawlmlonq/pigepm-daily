from playwright.async_api import async_playwright
import nest_asyncio
import asyncio
import gspread
import os
import json
import time
from datetime import datetime, timezone, timedelta
from gspread_formatting import *
import requests
from google.oauth2.service_account import Credentials

# 確保 asyncio loop 可重複使用（for GitHub Actions / Colab）
nest_asyncio.apply()

# Playwright 擷取資料
async def scrape_pigepm():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto("https://pigepm.moa.gov.tw/", wait_until="networkidle")

        items = await page.query_selector_all('.number-name-item')
        farm_count = user_count = None

        for item in items:
            label = (await item.inner_text()).strip()
            value = (await item.evaluate("el => el.previousElementSibling.textContent")).strip()
            if '牧場數量' in label:
                farm_count = int(value)
            elif '使用者數量' in label:
                user_count = int(value)

        await browser.close()
        return farm_count, user_count

# 寫入 Google Sheet（加入重試機制）
def write_to_sheet(farm, user, max_retries=5):
    print("📄 取得 Google Sheet 金鑰")
    creds_json = os.environ.get("GCP_CREDENTIALS")

    if not creds_json:
        raise ValueError("❌ 未偵測到 GCP_CREDENTIALS，請確認 GitHub Secrets 設定正確")

    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

    gc = gspread.authorize(creds)

    SHEET_ID = "1BRfNr84btjJFPH9CXUiTMeojHGb16Y7vRf_D92kHKOU"
    WORKSHEET_NAME = "數據記錄"

    # 重試邏輯
    for attempt in range(max_retries):
        try:
            print(f"🔄 嘗試連接 Google Sheet（第 {attempt + 1} 次）")
            
            sh = gc.open_by_key(SHEET_ID)
            worksheet = sh.worksheet(WORKSHEET_NAME)

            # 檢查並添加標題行
            if worksheet.cell(1, 1).value != "日期時間":
                worksheet.insert_row(["日期時間", "牧場數量", "使用者數量", "數據來源"], 1)

            # 準備資料
            taipei_time = datetime.now(timezone.utc) + timedelta(hours=8)
            timestamp = taipei_time.strftime("%Y/%m/%d %H:%M:%S")
            row = [timestamp, farm, user, "Playwright-GitHubActions"]

            # 寫入資料
            worksheet.append_row(row, value_input_option='USER_ENTERED')

            # 格式化日期欄位
            fmt = cellFormat(numberFormat=numberFormat(type='DATE_TIME', pattern='yyyy/MM/dd HH:mm:ss'))
            format_cell_range(worksheet, 'A:A', fmt)

            print("✅ 資料已成功寫入 Google Sheet")
            return  # 成功則退出函數

        except gspread.exceptions.APIError as e:
            if "503" in str(e) or "temporarily unavailable" in str(e).lower():
                wait_time = (2 ** attempt) + 1  # 指數退避：2, 5, 9, 17, 33 秒
                print(f"⚠️  Google Sheets API 暫時不可用，{wait_time} 秒後重試...")
                time.sleep(wait_time)
                
                if attempt == max_retries - 1:
                    print("❌ 已達最大重試次數，寫入失敗")
                    raise e
            else:
                print(f"❌ 其他 API 錯誤：{e}")
                raise e
        except Exception as e:
            print(f"❌ 未預期的錯誤：{e}")
            if attempt == max_retries - 1:
                raise e
            else:
                time.sleep(2)

# 通知 GAS webhook（也加入重試）
def notify_gas(farm, user, max_retries=3):
    GAS_URL = "https://script.google.com/macros/s/AKfycbylRiww5xOBR3ElecBOl1Qv5pYGApwVGxXvrbdgWYIid7bQWjdQ_S4Npk29ZBtRNhmL6A/exec"
    payload = {
        "farmCount": farm,
        "userCount": user,
        "source": "Playwright-GitHubActions"
    }
    
    for attempt in range(max_retries):
        try:
            print(f"📡 發送通知到 GAS（第 {attempt + 1} 次）")
            r = requests.post(GAS_URL, json=payload, timeout=30)
            
            if r.status_code == 200:
                print("✅ 已通知 GAS，回應：", r.text)
                return
            else:
                print(f"⚠️  GAS 回應狀態碼：{r.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"⚠️  GAS 通知失敗：{e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1, 2, 4 秒
            else:
                print("❌ GAS 通知最終失敗，但程式將繼續執行")

# 主程序
if __name__ == "__main__":
    try:
        print("🚀 程式啟動中")
        farm, user = asyncio.run(scrape_pigepm())
        print("🐷 牧場數量：", farm)
        print("👥 使用者數量：", user)
        
        # 先嘗試寫入 Google Sheet
        write_to_sheet(farm, user)
        
        # 再發送 GAS 通知
        notify_gas(farm, user)
        
        print("🎉 所有任務完成！")
        
    except Exception as e:
        print(f"💥 程式執行失敗：{e}")
        exit(1)  # 讓 GitHub Actions 知道執行失敗