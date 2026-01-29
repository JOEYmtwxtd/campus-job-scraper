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
    """尝试解析各种格式的日期，返回 YYYY-MM-DD 或 None"""
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
    print("正在从求职方舟全量抓取...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(10)
        page_num = 1
        while True:
            print(f"  - 正在解析第 {page_num} 页...")
            await page.wait_for_selector(".ag-row", timeout=15000)
            
            # 在浏览器内部精准提取
            page_jobs = await page.evaluate("""
                () => {
                    const results = [];
                    const rows = document.querySelectorAll('.ag-row');
                    rows.forEach(row => {
                        const cells = Array.from(row.querySelectorAll('.ag-cell'));
                        // 求职方舟表格列索引：1:公司, 2:岗位, 3:地点, 4:届别, 5:截止时间
                        // 行业类型通常在特定的 col-id 中，我们通过 col-id 匹配更准
                        const getCellText = (id) => row.querySelector(`[col-id="${id}"]`)?.innerText.trim() || "";
                        
                        const company = getCellText("company");
                        const position = getCellText("positions");
                        const location = getCellText("locations");
                        const batch = getCellText("batch");
                        const deadline = getCellText("deadline");
                        const industry = getCellText("industry");
                        
                        const link_el = row.querySelector(`[col-id="company"] a`);
                        
                        if (company && company !== "公司") {
                            results.push({
                                '公司名称': company.replace("投递公司", "").trim(),
                                '招聘岗位': position,
                                '工作地点': location,
                                '招聘届别': batch,
                                '截止时间': deadline,
                                '行业类型': industry,
                                '公司类型': '', // 稍后尝试从行业或名称推测
                                '网申链接': link_el ? link_el.href : '',
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
            
            next_btn = await page.query_selector("button:has-text('下一页'), .ag-paging-button:has-text('下一页')")
            if next_btn and await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await asyncio.sleep(4)
                page_num += 1
            else: break
    except Exception as e: print(f"求职方舟抓取中断: {e}")
    return jobs

async def get_givemeoc_data(page):
    print("正在从 GiveMeOC 抓取...")
    jobs = []
    try:
        await page.goto("https://www.givemeoc.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(10)
        # GiveMeOC 主要是列表形式，解析标题
        items = await page.query_selector_all(".post-item")
        for item in items:
            try:
                title_el = await item.query_selector(".post-title a")
                if not title_el: continue
                title = await title_el.inner_text()
                href = await title_el.get_attribute("href")
                
                # 尝试提取 [公司] 岗位
                match = re.search(r'[\[【](.*?)[\]】](.*)', title)
                company = match.group(1).strip() if match else title.split(' ')[0]
                position = match.group(2).strip() if match else title
                
                jobs.append({
                    "公司名称": company,
                    "招聘岗位": position,
                    "工作地点": "全国",
                    "招聘届别": "2025/2026届",
                    "截止时间": "",
                    "行业类型": "综合",
                    "公司类型": "民企",
                    "网申链接": href,
                    "招聘公告原文链接": href
                })
            except: continue
    except Exception as e: print(f"GiveMeOC 抓取失败: {e}")
    return jobs

def final_guess_info(job):
    """最后的兜底补全"""
    name = job['公司名称'].upper()
    # 简单的外企/国企识别
    if any(x in name for x in ["LVMH", "LV", "DIOR", "CHANEL", "HERMES", "GUCCI", "外企"]):
        job['公司类型'] = "外企"
        job['行业类型'] = "奢侈品"
    elif any(x in name for x in ["中信", "建设银行", "工商银行", "国企", "中铁"]):
        job['公司类型'] = "国企"
    elif not job['公司类型']:
        job['公司类型'] = "民企"
    return job

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
        job = final_guess_info(job)
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
            print("🎉 最终精准抄写版同步成功！")
    except Exception as e: print(f"飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
