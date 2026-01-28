import os
import json
import time
import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from feishu_utils import FeishuClient

# 环境变量
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
FEISHU_BASE_TOKEN = os.getenv("FEISHU_BASE_TOKEN")

# 严格表头定义
HEADERS = [
    "更新日期", "公司名称", "公司类型", "行业类型", "招聘届别", 
    "工作地点", "招聘岗位", "网申链接", "招聘公告原文链接", "截止时间"
]

def parse_date(date_str):
    if not date_str or "不限" in date_str or "见详情" in date_str:
        return None
    date_str = re.sub(r'[^\d\-]', '', date_str.replace('/', '-'))
    try:
        if len(date_str) <= 5 and '-' in date_str:
            year = datetime.now().year
            date_str = f"{year}-{date_str}"
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except:
        return None

def is_expired(date_str):
    parsed = parse_date(date_str)
    if not parsed: return False
    return parsed < datetime.now().strftime("%Y-%m-%d")

def guess_company_info(company_name):
    name = company_name.upper()
    info = {"type": "", "industry": ""}
    luxury = ["LOUIS VUITTON", "LV", "GUCCI", "PRADA", "CHANEL", "HERMES", "DIOR", "ROLEX", "LVMH", "KERING"]
    if any(b in name for b in luxury): info["type"], info["industry"] = "外企", "奢侈品"
    tech = ["腾讯", "TENCENT", "阿里巴巴", "ALIBABA", "字节跳动", "BYTEDANCE", "美团", "百度", "BAIDU", "拼多多", "PDD"]
    if any(b in name for b in tech): info["type"], info["industry"] = "民企", "互联网"
    return info

async def get_qiuzhifangzhou_data(page):
    print("正在从求职方舟抓取...")
    try:
        # 增加超时时间到 60 秒，并使用 domcontentloaded
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="domcontentloaded", timeout=60000 )
        await page.wait_for_selector(".ag-row", timeout=30000)
        return await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('.ag-row');
                const results = [];
                rows.forEach(row => {
                    const rowData = {};
                    const cells = row.querySelectorAll('.ag-cell');
                    cells.forEach(cell => {
                        const colId = cell.getAttribute('col-id');
                        rowData[colId] = {text: cell.innerText.trim(), link: cell.querySelector('div[href]') ? cell.querySelector('div[href]').getAttribute('href') : ''};
                    });
                    if (rowData['company']) {
                        results.push({
                            '更新日期': new Date().toISOString().split('T')[0],
                            '公司名称': rowData['company'].text,
                            '公司类型': '',
                            '行业类型': rowData['industry'] ? rowData['industry'].text : '',
                            '招聘届别': rowData['batch'] ? rowData['batch'].text : '',
                            '工作地点': rowData['locations'] ? rowData['locations'].text : '',
                            '招聘岗位': rowData['positions'] ? rowData['positions'].text : '',
                            '网申链接': rowData['company'].link,
                            '招聘公告原文链接': '',
                            '截止时间': rowData['deadline'] ? rowData['deadline'].text : ''
                        });
                    }
                });
                return results;
            }
        """)
    except Exception as e:
        print(f"求职方舟抓取失败: {e}")
        return []

async def get_givemeoc_data(page):
    print("正在从 GiveMeOC 抓取...")
    try:
        await page.goto("https://www.givemeoc.com", wait_until="domcontentloaded", timeout=60000 )
        await page.wait_for_selector("table", timeout=30000)
        return await page.evaluate("""
            () => {
                const results = [];
                const table = document.querySelector('table');
                if (!table) return results;
                const rows = Array.from(table.querySelectorAll('tr')).slice(1);
                rows.forEach(row => {
                    const cols = row.querySelectorAll('td');
                    if (cols.length >= 5) {
                        const link_a = row.querySelector('a');
                        results.push({
                            '更新日期': new Date().toISOString().split('T')[0],
                            '公司名称': cols[0].innerText.trim(),
                            '公司类型': '',
                            '行业类型': cols[2] ? cols[2].innerText.trim() : '',
                            '招聘届别': cols[4] ? cols[4].innerText.trim() : '',
                            '工作地点': cols[5] ? cols[5].innerText.trim() : '',
                            '招聘岗位': cols[3] ? cols[3].innerText.trim() : '',
                            '网申链接': link_a ? link_a.href : '',
                            '招聘公告原文链接': link_a ? link_a.href : '',
                            '截止时间': cols[7] ? cols[7].innerText.trim() : ''
                        });
                    }
                });
                return results;
            }
        """)
    except Exception as e:
        print(f"GiveMeOC 抓取失败: {e}")
        return []

async def get_tencent_docs_data(page):
    print("正在从腾讯文档抓取...")
    try:
        await page.goto("https://docs.qq.com/sheet/DS29Pb3pLRExVa0xp?tab=BB08J2", wait_until="domcontentloaded", timeout=60000 )
        await asyncio.sleep(5)
        return [] # 腾讯文档逻辑较复杂，先保持结构稳定
    except Exception as e:
        print(f"腾讯文档抓取跳过: {e}")
        return []

async def main():
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN]):
        print("错误: 飞书配置缺失")
        return
    all_jobs_raw = []
    stats = {"givemeoc": 0, "qiuzhifangzhou": 0, "tencent": 0}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        q_data = await get_qiuzhifangzhou_data(page)
        stats["qiuzhifangzhou"] = len(q_data)
        all_jobs_raw.extend(q_data)
        g_data = await get_givemeoc_data(page)
        stats["givemeoc"] = len(g_data)
        all_jobs_raw.extend(g_data)
        t_data = await get_tencent_docs_data(page)
        stats["tencent"] = len(t_data)
        all_jobs_raw.extend(t_data)
        await browser.close()
    valid_jobs = []
    seen_keys = set()
    for job in all_jobs_raw:
        guessed = guess_company_info(job['公司名称'])
        if not job['公司类型']: job['公司类型'] = guessed['type']
        if not job['行业类型']: job['行业类型'] = guessed['industry']
        job['截止时间'] = parse_date(job['截止时间']) or ""
        key = f"{job['公司名称']}|{job['网申链接']}|{job['招聘公告原文链接']}"
        if not is_expired(job['截止时间']) and key not in seen_keys:
            if job['网申链接']: job['网申链接'] = {"link": job['网申链接'], "text": "点击投递"}
            if job['招聘公告原文链接']: job['招聘公告原文链接'] = {"link": job['招聘公告原文链接'], "text": "查看公告"}
            if job['更新日期']: job['更新日期'] = int(time.mktime(time.strptime(job['更新日期'], "%Y-%m-%d"))) * 1000
            if job['截止时间']: job['截止时间'] = int(time.mktime(time.strptime(job['截止时间'], "%Y-%m-%d"))) * 1000
            else: job['截止时间'] = None
            valid_jobs.append(job)
            seen_keys.add(key)
    print(f"日志：共抓取 {len(all_jobs_raw)} 条，{len(valid_jobs)} 条有效")
    try:
        fs = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
        table_id = fs.get_table_id()
        if table_id:
            existing = fs.get_all_records(table_id)
            if existing: fs.delete_records(table_id, [r['record_id'] for r in existing])
            fs.add_records(table_id, valid_jobs)
            print("同步成功！")
    except Exception as e: print(f"飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
