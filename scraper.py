import os
import json
import base64
import time
import asyncio
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# 配置
GOOGLE_SHEETS_CREDENTIALS_B64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
SHEET_NAME = "校招岗位汇总"  # 请确保您的 Google 表格名字包含这个
TARGET_URLS = [
    "https://www.qiuzhifangzhou.com/campus",
    "https://www.givemeoc.com"
]

async def get_qiuzhifangzhou_data(page):
    print("正在抓取求职方舟数据...")
    await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle")
    # 等待表格加载
    await page.wait_for_selector(".ag-row", timeout=30000)
    
    # 提取数据
    jobs = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('.ag-row');
            const results = [];
            rows.forEach(row => {
                const rowData = {};
                const cells = row.querySelectorAll('.ag-cell');
                cells.forEach(cell => {
                    const colId = cell.getAttribute('col-id');
                    const text = cell.innerText.trim();
                    const linkDiv = cell.querySelector('div[href]');
                    const link = linkDiv ? linkDiv.getAttribute('href') : '';
                    rowData[colId] = {text, link};
                });
                
                if (rowData['company']) {
                    results.append({
                        '公司名称': rowData['company'].text,
                        '岗位名称': rowData['positions'] ? rowData['positions'].text : '',
                        '工作地点': rowData['locations'] ? rowData['locations'].text : '',
                        '面向届别': rowData['batch'] ? rowData['batch'].text : '',
                        '网申链接': rowData['company'].link,
                        '招聘公告原文链接': '',
                        '截止日期': rowData['deadline'] ? rowData['deadline'].text : '见详情',
                        '信息来源': '求职方舟',
                        '抓取日期': new Date().toLocaleDateString()
                    });
                }
            });
            return results;
        }
    """)
    # 修正 evaluate 中的 results.append 为 results.push
    jobs = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('.ag-row');
            const results = [];
            rows.forEach(row => {
                const rowData = {};
                const cells = row.querySelectorAll('.ag-cell');
                cells.forEach(cell => {
                    const colId = cell.getAttribute('col-id');
                    const text = cell.innerText.trim();
                    const linkDiv = cell.querySelector('div[href]');
                    const link = linkDiv ? linkDiv.getAttribute('href') : '';
                    rowData[colId] = {text, link};
                });
                
                if (rowData['company']) {
                    results.push({
                        '公司名称': rowData['company'].text,
                        '岗位名称': rowData['positions'] ? rowData['positions'].text : '',
                        '工作地点': rowData['locations'] ? rowData['locations'].text : '',
                        '面向届别': rowData['batch'] ? rowData['batch'].text : '',
                        '网申链接': rowData['company'].link,
                        '招聘公告原文链接': '',
                        '截止日期': rowData['deadline'] ? rowData['deadline'].text : '见详情',
                        '信息来源': '求职方舟',
                        '抓取日期': new Date().toISOString().split('T')[0]
                    });
                }
            });
            return results;
        }
    """)
    return jobs

async def get_givemeoc_data(page):
    print("正在抓取 GiveMeOC 数据...")
    try:
        await page.goto("https://www.givemeoc.com", wait_until="networkidle", timeout=60000)
        # GiveMeOC 结构通常是 table
        await page.wait_for_selector("table", timeout=20000)
        
        jobs = await page.evaluate("""
            () => {
                const results = [];
                const table = document.querySelector('table');
                if (!table) return results;
                const rows = Array.from(table.querySelectorAll('tr')).slice(1); // 跳过表头
                rows.forEach(row => {
                    const cols = row.querySelectorAll('td');
                    if (cols.length >= 5) {
                        const company = cols[0].innerText.trim();
                        const job_name = cols[3] ? cols[3].innerText.trim() : '';
                        const target = cols[4] ? cols[4].innerText.trim() : '';
                        const location = cols[5] ? cols[5].innerText.trim() : '';
                        const deadline = cols[7] ? cols[7].innerText.trim() : '';
                        const link_a = row.querySelector('a');
                        const link = link_a ? link_a.href : '';
                        
                        results.push({
                            '公司名称': company,
                            '岗位名称': job_name,
                            '工作地点': location,
                            '面向届别': target,
                            '网申链接': link,
                            '招聘公告原文链接': link,
                            '截止日期': deadline,
                            '信息来源': 'GiveMeOC',
                            '抓取日期': new Date().toISOString().split('T')[0]
                        });
                    }
                });
                return results;
            }
        """)
        return jobs
    except Exception as e:
        print(f"抓取 GiveMeOC 失败: {e}")
        return []

async def main():
    if not GOOGLE_SHEETS_CREDENTIALS_B64:
        print("错误: 未设置 GOOGLE_SHEETS_CREDENTIALS 环境变量")
        return

    # 初始化 Google Sheets
    creds_json = json.loads(base64.b64decode(GOOGLE_SHEETS_CREDENTIALS_B64))
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    client = gspread.authorize(creds)
    
    try:
        spreadsheet = client.open(SHEET_NAME)
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"未找到表格 '{SHEET_NAME}'，正在尝试按 ID 打开或请确保表格已分享给 Service Account 邮箱。")
        # 这里的处理可以更友好，建议用户在 README 中查看如何获取邮箱
        return

    sheet = spreadsheet.get_worksheet(0)
    
    # 抓取数据
    all_jobs = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
        page = await context.new_page()
        await stealth_async(page)
        
        all_jobs.extend(await get_qiuzhifangzhou_data(page))
        all_jobs.extend(await get_givemeoc_data(page))
        
        await browser.close()

    if not all_jobs:
        print("没有抓取到任何新数据。")
        return

    # 去重处理（根据公司名称+岗位名称+截止日期）
    existing_data = sheet.get_all_records()
    seen_keys = set()
    for row in existing_data:
        key = f"{row.get('公司名称')}|{row.get('岗位名称')}|{row.get('截止日期')}"
        seen_keys.add(key)

    new_rows = []
    headers = ["公司名称", "岗位名称", "工作地点", "面向届别", "网申链接", "招聘公告原文链接", "截止日期", "信息来源", "抓取日期"]
    
    # 如果表格是空的，写入表头
    if not existing_data:
        sheet.append_row(headers)

    for job in all_jobs:
        key = f"{job['公司名称']}|{job['岗位名称']}|{job['截止日期']}"
        if key not in seen_keys:
            new_rows.append([job[h] for h in headers])
            seen_keys.add(key)

    if new_rows:
        sheet.append_rows(new_rows)
        print(f"成功更新 {len(new_rows)} 条新岗位！")
    else:
        print("没有发现新的岗位。")

if __name__ == "__main__":
    asyncio.run(main())
