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

def parse_date(date_str):
    if not date_str or any(x in date_str for x in ["不限", "见详情", "截止", "尽快", "长期"]):
        return None
    match = re.search(r'(\d{4})[-\.年/](\d{1,2})[-\.月/](\d{1,2})', date_str)
    if not match:
        match = re.search(r'(\d{1,2})[-\.月/](\d{1,2})', date_str)
        if match:
            year = datetime.now().year
            month, day = match.groups()
        else: return None
    else:
        year, month, day = match.groups()
    try:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    except: return None

def is_expired(date_str):
    if not date_str: return False
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        return date_str < today
    except: return False

def smart_fill(job):
    """强制补全所有空白，确保飞书表格无空行"""
    name = job.get('公司名称', '').upper()
    if not job.get('公司类型'):
        if any(x in name for x in ["LVMH", "LV", "DIOR", "CHANEL", "HERMES", "GUCCI", "外企", "宝洁", "欧莱雅"]):
            job['公司类型'] = "外企"
        elif any(x in name for x in ["中信", "银行", "国企", "中铁", "中建"]):
            job['公司类型'] = "国企"
        else:
            job['公司类型'] = "民企"
    
    if not job.get('行业类型'):
        if "奢侈品" in name or job['公司类型'] == "外企": job['行业类型'] = "奢侈品/快消"
        elif "银行" in name or "证券" in name: job['行业类型'] = "金融"
        else: job['行业类型'] = "综合"
        
    if not job.get('工作地点'): job['工作地点'] = "全国"
    if not job.get('招聘届别'): job['招聘届别'] = "2025/2026届"
    return job

async def get_qiuzhifangzhou_data(page):
    print("正在从求职方舟全量抓取（终极稳健模式）...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(15) # 给足渲染时间
        
        page_num = 1
        while True:
            print(f"  - 正在解析第 {page_num} 页...")
            await page.wait_for_selector(".ag-row", timeout=20000)
            
            # 使用更鲁棒的 JS 提取，即使列顺序变了也能抓到
            page_jobs = await page.evaluate("""
                () => {
                    const results = [];
                    const rows = document.querySelectorAll('.ag-row');
                    rows.forEach(row => {
                        const data = {};
                        const cells = row.querySelectorAll('.ag-cell');
                        cells.forEach(cell => {
                            const colId = cell.getAttribute('col-id');
                            const text = cell.innerText.trim();
                            if (colId) data[colId] = text;
                            if (colId === 'company') {
                                const a = cell.querySelector('a');
                                if (a) data['link'] = a.href;
                            }
                        });
                        
                        if (data.company && data.company !== "公司") {
                            results.push({
                                '公司名称': data.company.replace("投递公司", "").trim(),
                                '招聘岗位': data.positions || "校招岗位",
                                '工作地点': data.locations || "全国",
                                '招聘届别': data.batch || "2025/2026届",
                                '截止时间': data.deadline || "",
                                '行业类型': data.industry || "",
                                '公司类型': '',
                                '网申链接': data.link || '',
                                '招聘公告原文链接': 'https://www.qiuzhifangzhou.com/campus'
                            });
                        }
                    });
                    return results;
                }
            """)
            
            if not page_jobs: break
            for j in page_jobs:
                d = parse_date(j['截止时间'])
                if not is_expired(d): jobs.append(j)
            
            # 翻页
            next_btn = await page.query_selector("button:has-text('下一页'), .ag-paging-button:has-text('下一页')")
            if next_btn and await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await asyncio.sleep(5)
                page_num += 1
            else: break
    except Exception as e: print(f"求职方舟抓取中断: {e}")
    return jobs

async def get_givemeoc_data(page):
    print("正在从 GiveMeOC 抓取...")
    jobs = []
    try:
        await page.goto("https://www.givemeoc.com/", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(10)
        items = await page.query_selector_all(".post-item")
        for item in items:
            try:
                title_el = await item.query_selector(".post-title a")
                if not title_el: continue
                title = await title_el.inner_text()
                href = await title_el.get_attribute("href")
                
                match = re.search(r'[\[【](.*?)[\]】](.*)', title)
                company = match.group(1).strip() if match else title.split(' ')[0]
                position = match.group(2).strip() if match else title
                
                jobs.append({
                    "公司名称": company,
                    "招聘岗位": position,
                    "工作地点": "全国",
                    "招聘届别": "2025/2026届",
                    "截止时间": "",
                    "行业类型": "",
                    "公司类型": "",
                    "网申链接": href,
                    "招聘公告原文链接": href
                })
            except: continue
    except Exception as e: print(f"GiveMeOC 抓取失败: {e}")
    return jobs

async def main():
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN]):
        print("错误: 飞书配置缺失")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        
        all_raw = []
        all_raw.extend(await get_qiuzhifangzhou_data(page))
        all_raw.extend(await get_givemeoc_data(page))
        await browser.close()

    valid_jobs = []
    seen_keys = set()
    for job in all_raw:
        job = smart_fill(job)
        company = job['公司名称'].strip()
        position = job['招聘岗位'].strip()
        if not company or len(company) < 2: continue
        
        deadline = parse_date(job.get("截止时间", ""))
        key = f"{company}|{position}"
        if key in seen_keys: continue
        seen_keys.add(key)
        
        row = {
            "更新日期": int(time.time() * 1000),
            "公司名称": company,
            "公司类型": job['公司类型'],
            "行业类型": job['行业类型'],
            "招聘届别": job['招聘届别'],
            "工作地点": job['工作地点'],
            "招聘岗位": position,
            "网申链接": {"link": job["网申链接"], "text": "点击投递"} if job.get("网申链接") else None,
            "招聘公告原文链接": {"link": job["招聘公告原文链接"], "text": "查看公告"} if job.get("招聘公告原文链接") else None,
            "截止时间": int(time.mktime(time.strptime(deadline, "%Y-%m-%d"))) * 1000 if deadline else None
        }
        valid_jobs.append(row)

    print(f"日志：最终精准同步 {len(valid_jobs)} 条岗位")
    try:
        fs = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
        table_id = fs.get_table_id()
        if table_id:
            existing = fs.get_all_records(table_id)
            if existing:
                ids = [r['record_id'] for r in existing]
                for i in range(0, len(ids), 500): fs.delete_records(table_id, ids[i:i+500])
            for i in range(0, len(valid_jobs), 100): fs.add_records(table_id, valid_jobs[i:i+100])
            print("🎉 终极无敌完美同步成功！")
    except Exception as e: print(f"飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
