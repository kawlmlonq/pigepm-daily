from playwright.async_api import async_playwright
import nest_asyncio
import asyncio
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from gspread_formatting import *
import requests
import json
import os

# 確保 asyncio loop 可重複使用（for Colab/local 運行）
nest_asyncio.apply()

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

def write_to_sheet(farm, user):
    # 從 GitHub Secret 中取得 GCP 金鑰字串
    creds_json = os.getenv("GCP_CREDENTIALS")
    if creds_json is None:
        raise RuntimeError("❌ GCP_CREDENTIALS 未設定，請確認 GitHub Secrets 設定")

    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict)
    gc = gspread.authorize(creds)

    SHEET_ID = "1BRfNr84btjJFPH9CXUiTMeojHGb16Y7vRf_D92kHKOU"
    WORKSHEET_NAME = "數據記錄"

    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.worksheet(WORKSHEET_NAME)

    if worksheet.cell(1, 1).value != "日期時間":
        worksheet.insert_row(["日期時間", "牧場數量", "使用者數量", "數據來源"], 1)

    timestamp = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    row = [timestamp, farm, user, "Playwright-GitHubActions"]
    worksheet.append_row(row, value_input_option='USER_ENTERED')

    fmt = cellFormat(numberFormat=numberFormat(type='DATE_TIME', pattern='yyyy/MM/dd HH:mm:ss'))
    format_cell_range(worksheet, 'A:A', fmt)
    print("✅ 資料已寫入 Google Sheet")

def notify_gas(farm, user):
    GAS_URL = "https://script.google.com/macros/s/AKfycbylRiww5xOBR3ElecBOl1Qv5pYGApwVGxXvrbdgWYIid7bQWjdQ_S4Npk29ZBtRNhmL6A/exec"
    payload = {
        "farmCount": farm,
        "userCount": user,
        "source": "Playwright-GitHubActions"
    }
    r = requests.post(GAS_URL, json=payload)
    print("✅ 已通知 GAS，回應：", r.text)

# ✅ 主程序放最後
if __name__ == "__main__":
    print("🐷 Triggered: 程式啟動中...")
    farm, user = asyncio.run(scrape_pigepm())
    print("🐷 牧場數量：", farm)
    print("👥 使用者數量：", user)
    write_to_sheet(farm, user)
    notify_gas(farm, user)
