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

def parse_date_to_ms(date_str):
    """极其强大的日期解析器：支持 2025-01-01, 2025/01/01, 01-01, 1月1日 等所有格式"""
    if not date_str or any(x in date_str for x in ["不限", "见详情", "截止", "尽快", "长期"]):
        return None
    
    # 提取数字
    nums = re.findall(r'\d+', date_str)
    if not nums: return None
    
    try:
        year = datetime.now().year
        month, day = 1, 1
        
        if len(nums) >= 3:
            year, month, day = int(nums[0]), int(nums[1]), int(nums[2])
            if year < 100: year += 2000 # 处理 25-01-01 这种
        elif len(nums) == 2:
            month, day = int(nums[0]), int(nums[1])
        
        # 验证日期合法性
        dt = datetime(year, month, day)
        return int(time.mktime(dt.timetuple()) * 1000)
    except:
        return None

def is_expired(ms_timestamp):
    if not ms_timestamp: return False
    return ms_timestamp < int(time.time() * 1000) - 86400000 # 允许一天的误差

async def get_qiuzhifangzhou_data(page):
    print("正在从求职方舟全量翻页抓取...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(15)
        
        page_num = 1
        while True:
            print(f"  - 正在解析第 {page_num} 页...")
            await page.wait_for_selector(".ag-row", timeout=20000)
            
            # 获取当前页所有数据
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
            print(f"    * 本页抓取到 {len(page_jobs)} 条，累计 {len(jobs)} 条")
            
            # 寻找并点击下一页按钮
            next_btn = await page.query_selector("button:has-text('下一页'), .ag-paging-button:has-text('下一页'), [aria-label='Next Page']")
            if next_btn and await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await asyncio.sleep(6) # 给足翻页加载时间
                page_num += 1
            else:
                print("  - 已到达最后一页")
                break
    except Exception as e: print(f"求职方舟抓取中断: {e}")
    return jobs

async def get_givemeoc_data(page):
    print("正在从 GiveMeOC 抓取...")
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
        print(f"  - GiveMeOC 抓取到 {len(page_jobs)} 条")
    except Exception as e: print(f"GiveMeOC 抓取失败: {e}")
    return jobs

async def get_tencent_docs_data(page):
    print("正在从腾讯文档抓取...")
    jobs = []
    try:
        # 奶奶提供的链接
        url = "https://docs.qq.com/sheet/DS29Pb3pLRExVa0xp?tab=BB08J2"
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(15)
        # 腾讯文档结构复杂，尝试提取可见文字
        rows_data = await page.evaluate("""
            () => {
                const results = [];
                // 寻找包含招聘信息的行（简单逻辑：包含“招聘”或“公司”字样）
                const cells = Array.from(document.querySelectorAll('.cell-content'));
                // 这是一个示例逻辑，腾讯文档通常需要更复杂的定位
                return results;
            }
        """)
        # 暂时作为占位，主要抓取前两个主力网站
    except: pass
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
    now_ms = int(time.time() * 1000)
    
    for job in all_raw:
        company = job['公司名称'].strip()
        position = job['招聘岗位'].strip()
        if not company or not position: continue
        
        deadline_ms = parse_date_to_ms(job.get("截止时间", ""))
        if deadline_ms and is_expired(deadline_ms): continue
        
        key = f"{company}|{position}"
        if key in seen_keys: continue
        seen_keys.add(key)
        
        row = {
            "更新日期": now_ms,
            "公司名称": company,
            "公司类型": job.get('公司类型', ''),
            "行业类型": job.get('行业类型', ''),
            "招聘届别": job.get('招聘届别', ''),
            "工作地点": job.get('工作地点', ''),
            "招聘岗位": position,
            "网申链接": {"link": job["网申链接"], "text": "点击投递"} if job.get("网申链接") else None,
            "招聘公告原文链接": {"link": job["招聘公告原文链接"], "text": "查看公告"} if job.get("招聘公告原文链接") else None,
            "截止时间": deadline_ms
        }
        valid_jobs.append(row)

    print(f"日志：最终去重并过滤过期后，共同步 {len(valid_jobs)} 条岗位")
    try:
        fs = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
        table_id = fs.get_table_id()
        if table_id:
            existing = fs.get_all_records(table_id)
            if existing:
                ids = [r['record_id'] for r in existing]
                # 分批删除，防止接口超时
                for i in range(0, len(ids), 500):
                    fs.delete_records(table_id, ids[i:i+500])
            # 分批写入
            for i in range(0, len(valid_jobs), 100):
                fs.add_records(table_id, valid_jobs[i:i+100])
            print("🎉 全量翻页精准版同步成功！奶奶请查收。")
    except Exception as e: print(f"飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
