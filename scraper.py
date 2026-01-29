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
    if not date_str or any(x in date_str for x in ["不限", "见详情", "截止", "尽快", "长期"]):
        return None
    nums = re.findall(r'\d+', date_str)
    if not nums: return None
    try:
        year = datetime.now().year
        month, day = 1, 1
        if len(nums) >= 3:
            year, month, day = int(nums[0]), int(nums[1]), int(nums[2])
            if year < 100: year += 2000
        elif len(nums) == 2:
            month, day = int(nums[0]), int(nums[1])
        dt = datetime(year, month, day)
        return int(time.mktime(dt.timetuple()) * 1000)
    except: return None

async def get_qiuzhifangzhou_data(page):
    print("🚀 启动求职方舟【暴力翻页】模式...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle", timeout=120000)
        await asyncio.sleep(20)

        page_num = 1
        while True:
            print(f"  📄 正在全力抓取第 {page_num} 页...")
            await page.wait_for_selector(".ag-row", timeout=30000)

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

            if not page_jobs:
                print("  ⚠️ 本页没抓到数据，尝试再等会儿...")
                await asyncio.sleep(5)
                page_num += 1
                if page_num > 50:
                    break
                continue

            jobs.extend(page_jobs)
            print(f"  ✅ 第 {page_num} 页抓取成功，当前累计: {len(jobs)} 条")

            # 检查下一页按钮是否存在且可用
            can_go_next = await page.evaluate("""
                () => {
                    const nextBtn = document.querySelector('[ref="btNext"]') ||
                                   document.querySelector('.ag-paging-button[ref="btNext"]') ||
                                   document.querySelector('button[aria-label="Next Page"]');
                    if (!nextBtn) return false;
                    return !nextBtn.disabled && !nextBtn.classList.contains('ag-disabled');
                }
            """)

            if can_go_next:
                await page.click('[ref="btNext"], .ag-paging-button[ref="btNext"], button[aria-label="Next Page"]')
                await asyncio.sleep(8)
                page_num += 1
            else:
                print(f"  🏁 已翻到最后一页，共 {page_num} 页。")
                break
    except Exception as e:
        print(f"  ❌ 抓取中断: {e}")
    return jobs

async def get_givemeoc_data(page):
    print("🚀 启动 GiveMeOC 抓取...")
    jobs = []
    try:
        await page.goto("https://www.givemeoc.com/", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(15)
        await page.wait_for_selector('table')

        # 获取总页数
        total_pages = await page.evaluate("""
            () => {
                const pageLinks = document.querySelectorAll('a[href*="paged="]');
                let max = 1;
                pageLinks.forEach(link => {
                    const match = link.href.match(/paged=(\\d+)/);
                    if (match) max = Math.max(max, parseInt(match[1]));
                });
                return max;
            }
        """)
        print(f"  📊 GiveMeOC 共 {total_pages} 页")

        page_num = 1
        while page_num <= total_pages:
            print(f"  📄 正在抓取 GiveMeOC 第 {page_num}/{total_pages} 页...")

            page_jobs = await page.evaluate("""
                () => {
                    const results = [];
                    const rows = document.querySelectorAll('table tr');
                    rows.forEach(row => {
                        const cells = Array.from(row.querySelectorAll('td'));
                        if (cells.length >= 10) {
                            const company = cells[0].innerText.trim();
                            if (!company || company === '公司名称') return;
                            const linkCell = cells[10] || cells[11];
                            const a = linkCell ? linkCell.querySelector('a') : row.querySelector('a');
                            results.push({
                                '公司名称': company,
                                '公司类型': cells[1].innerText.trim(),
                                '行业类型': cells[2].innerText.trim(),
                                '招聘岗位': cells[6].innerText.trim(),
                                '招聘届别': cells[4].innerText.trim(),
                                '工作地点': cells[5].innerText.trim(),
                                '网申链接': a ? a.href : '',
                                '招聘公告原文链接': a ? a.href : '',
                                '截止时间': cells[9].innerText.trim()
                            });
                        }
                    });
                    return results;
                }
            """)

            if page_jobs:
                jobs.extend(page_jobs)
                print(f"  ✅ GiveMeOC 第 {page_num} 页抓取到 {len(page_jobs)} 条，累计: {len(jobs)} 条")

            page_num += 1
            if page_num <= total_pages:
                # 使用URL直接跳转到下一页
                next_url = f"https://www.givemeoc.com/?paged={page_num}"
                await page.goto(next_url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(5)

        print(f"  🏁 GiveMeOC 抓取完成，共 {total_pages} 页。")
    except Exception as e:
        print(f"  ❌ GiveMeOC 失败: {e}")
    return jobs

async def get_careercenter_data(page):
    print("🚀 启动 CareerCenter 抓取...")
    jobs = []
    try:
        await page.goto("https://www.careercenter.com/jobs", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(15)

        page_num = 1
        while True:
            print(f"  📄 正在抓取 CareerCenter 第 {page_num} 页...")
            page_jobs = await page.evaluate("""
                () => {
                    const results = [];
                    const jobItems = document.querySelectorAll('.job-item');
                    jobItems.forEach(item => {
                        const company = item.querySelector('.company')?.innerText.trim() || '';
                        const position = item.querySelector('.position')?.innerText.trim() || '';
                        const deadline = item.querySelector('.deadline')?.innerText.trim() || '';
                        const link = item.querySelector('.apply-link')?.href || '';
                        if (company && position) {
                            results.push({
                                '公司名称': company,
                                '公司类型': '',
                                '行业类型': '',
                                '招聘届别': '',
                                '工作地点': '',
                                '招聘岗位': position,
                                '网申链接': link,
                                '招聘公告原文链接': link,
                                '截止时间': deadline
                            });
                        }
                    });
                    return results;
                }
            """)

            if page_jobs:
                jobs.extend(page_jobs)
                print(f"  ✅ CareerCenter 第 {page_num} 页抓取到 {len(page_jobs)} 条，累计: {len(jobs)} 条")

            next_btn = await page.query_selector('button.next, a[rel="next"], .pagination .next')
            if next_btn and await next_btn.is_enabled() and await next_btn.is_visible():
                await next_btn.click()
                await asyncio.sleep(8)
                page_num += 1
            else:
                print(f"  🏁 CareerCenter 已到达最后一页，共 {page_num} 页。")
                break
    except Exception as e:
        print(f"  ❌ CareerCenter 失败: {e}")
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
        all_raw.extend(await get_careercenter_data(page))
        await browser.close()

    valid_jobs = []
    seen_keys = set()
    now_ms = int(time.time() * 1000)
    
    for job in all_raw:
        company = job['公司名称'].strip()
        position = job['招聘岗位'].strip()
        if not company or not position: continue
        
        deadline_ms = parse_date_to_ms(job.get("截止时间", ""))
        # 即使没抓到日期也保留，防止漏掉岗位
        key = f"{company}|{position}"
        if key in seen_keys: continue
        seen_keys.add(key)
        
        valid_jobs.append({
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
        })

    print(f"📊 任务汇总：总计抓取 {len(valid_jobs)} 条有效岗位。正在同步到飞书...")
    try:
        fs = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
        table_id = fs.get_table_id()
        if table_id:
            existing = fs.get_all_records(table_id)
            if existing:
                ids = [r['record_id'] for r in existing]
                for i in range(0, len(ids), 500): fs.delete_records(table_id, ids[i:i+500])
            for i in range(0, len(valid_jobs), 100): fs.add_records(table_id, valid_jobs[i:i+100])
            print(f"🎉 大功告成！{len(valid_jobs)} 条岗位已全部同步！")
    except Exception as e:
        print(f"  ❌ 飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
