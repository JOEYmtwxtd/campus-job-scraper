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
    """解析日期仅用于过滤过期岗位，不改变原始显示内容"""
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

async def get_qiuzhifangzhou_data(page):
    print("正在从求职方舟原样搬运...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(15)
        
        while True:
            await page.wait_for_selector(".ag-row", timeout=20000)
            page_jobs = await page.evaluate("""
                () => {
                    const results = [];
                    const rows = document.querySelectorAll('.ag-row');
                    rows.forEach(row => {
                        const getT = (id) => row.querySelector(`[col-id="${id}"]`)?.innerText.trim() || "";
                        const company = getT("company").replace("投递公司", "").trim();
                        const link_el = row.querySelector(`[col-id="company"] a`);
                        if (company && company !== "公司") {
                            results.push({
                                '公司名称': company,
                                '公司类型': getT("type"), 
                                '行业类型': getT("industry"),
                                '招聘届别': getT("batch"),
                                '工作地点': getT("locations"),
                                '招聘岗位': getT("positions"),
                                '网申链接': link_el ? link_el.href : '',
                                '招聘公告原文链接': 'https://www.qiuzhifangzhou.com/campus',
                                '截止时间': getT("deadline")
                            });
                        }
                    });
                    return results;
                }
            """)
            if not page_jobs: break
            jobs.extend(page_jobs)
            
            next_btn = await page.query_selector("button:has-text('下一页'), .ag-paging-button:has-text('下一页')")
            if next_btn and await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await asyncio.sleep(5)
            else: break
    except Exception as e: print(f"求职方舟抓取失败: {e}")
    return jobs

async def get_givemeoc_data(page):
    print("正在从 GiveMeOC 原样搬运...")
    jobs = []
    try:
        await page.goto("https://www.givemeoc.com/", wait_until="networkidle", timeout=60000)
        await asyncio.sleep(15)
        page_jobs = await page.evaluate("""
            () => {
                const results = [];
                const rows = document.querySelectorAll('tr');
                rows.forEach(row => {
                    const cells = Array.from(row.querySelectorAll('td'));
                    if (cells.length >= 8) {
                        const company = cells[0].innerText.trim();
                        if (company === "公司" || !company) return;
                        const a = row.querySelector('a');
                        results.push({
                            '公司名称': company,
                            '公司类型': cells[1].innerText.trim(),
                            '行业类型': cells[2].innerText.trim(),
                            '招聘岗位': cells[3].innerText.trim(),
                            '招聘届别': cells[4].innerText.trim(),
                            '工作地点': cells[5].innerText.trim(),
                            '网申链接': a ? a.href : '',
                            '招聘公告原文链接': a ? a.href : '',
                            '截止时间': cells[7].innerText.trim()
                        });
                    }
                });
                return results;
            }
        """)
        jobs.extend(page_jobs)
    except Exception as e: print(f"GiveMeOC 抓取失败: {e}")
    return jobs

async def main():
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
        company = job['公司名称']
        position = job['招聘岗位']
        if not company or not position: continue
        
        # 仅用于过滤，不修改原始截止时间字符串
        deadline_val = parse_date(job.get("截止时间", ""))
        if is_expired(deadline_val): continue
        
        key = f"{company}|{position}"
        if key in seen_keys: continue
        seen_keys.add(key)
        
        # 百分百原样搬运，移除所有 or 默认值
        row = {
            "更新日期": int(time.time() * 1000),
            "公司名称": company,
            "公司类型": job.get('公司类型', ''),
            "行业类型": job.get('行业类型', ''),
            "招聘届别": job.get('招聘届别', ''),
            "工作地点": job.get('工作地点', ''),
            "招聘岗位": position,
            "网申链接": {"link": job["网申链接"], "text": "点击投递"} if job.get("网申链接") else None,
            "招聘公告原文链接": {"link": job["招聘公告原文链接"], "text": "查看公告"} if job.get("招聘公告原文链接") else None,
            "截止时间": int(time.mktime(time.strptime(deadline_val, "%Y-%m-%d"))) * 1000 if deadline_val else None
        }
        valid_jobs.append(row)

    print(f"日志：最终同步 {len(valid_jobs)} 条岗位")
    try:
        fs = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
        table_id = fs.get_table_id()
        if table_id:
            existing = fs.get_all_records(table_id)
            if existing:
                ids = [r['record_id'] for r in existing]
                for i in range(0, len(ids), 500): fs.delete_records(table_id, ids[i:i+500])
            for i in range(0, len(valid_jobs), 100): fs.add_records(table_id, valid_jobs[i:i+100])
            print("🎉 纯净搬运版同步成功！")
    except Exception as e: print(f"飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
