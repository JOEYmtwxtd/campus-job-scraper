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
    # 提取数字
    nums = re.findall(r'\d+', date_str)
    if not nums: return None
    try:
        year = datetime.now().year
        month, day = 1, 1
        if len(nums) >= 3:
            year, month, day = int(nums[0]), int(nums[1]), int(nums[2])
            if year < 100: year += 2000
        elif len(nums) == 2:
            # 只有月日，默认为今年
            month, day = int(nums[0]), int(nums[1])
        dt = datetime(year, month, day)
        return int(time.mktime(dt.timetuple()) * 1000)
    except: return None

async def get_qiuzhifangzhou_data(page):
    print("🚀 启动求职方舟抓取 (集成 Graphite 修复)...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle", timeout=120000)
        await asyncio.sleep(15)
        
        page_num = 1
        while True:
            print(f"  📄 正在抓取第 {page_num} 页...")
            try:
                await page.wait_for_selector(".ag-row", timeout=30000)
            except:
                print("  ⚠️ 等待表格超时，尝试继续提取内容...")
            
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
            
            if page_jobs:
                jobs.extend(page_jobs)
                print(f"  ✅ 第 {page_num} 页抓取成功，累计: {len(jobs)} 条")
            
            # 使用 JS 检查下一页按钮状态，防止点击已禁用的按钮导致超时
            has_next = await page.evaluate("""
                () => {
                    const selectors = ['[ref="btNext"]', '.ag-paging-button-next', 'button[aria-label="Next Page"]', '.ag-icon-next'];
                    for (const sel of selectors) {
                        const btn = document.querySelector(sel);
                        if (btn) {
                            const parent = btn.closest('button') || btn.closest('[role="button"]') || btn;
                            const isDisabled = parent.disabled || parent.classList.contains('ag-disabled') || parent.getAttribute('aria-disabled') === 'true';
                            if (!isDisabled) {
                                parent.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }
            """)
            
            if has_next:
                await asyncio.sleep(8)
                page_num += 1
                if page_num > 50: break # 安全限制
            else:
                print(f"  🏁 求职方舟翻页结束，共 {page_num} 页。")
                break
    except Exception as e:
        print(f"  ❌ 求职方舟抓取失败: {e}")
    return jobs

async def get_givemeoc_data(page):
    print("🚀 启动 GiveMeOC 抓取 (集成 Graphite 修复)...")
    jobs = []
    try:
        # 先访问首页获取总页数
        await page.goto("https://www.givemeoc.com/", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(10)
        await page.wait_for_selector('table')
        
        total_pages = await page.evaluate("""
            () => {
                const pageLinks = document.querySelectorAll('a[href*="paged="]');
                let max = 1;
                pageLinks.forEach(link => {
                    const match = link.href.match(/paged=(\\d+)/);
                    if (match && parseInt(match[1]) > max) max = parseInt(match[1]);
                });
                return Math.min(max, 100); // 限制最多抓 100 页
            }
        """)
        print(f"  📑 检测到共 {total_pages} 页，开始循环抓取...")
        
        for p in range(1, total_pages + 1):
            if p > 1:
                await page.goto(f"https://www.givemeoc.com/?paged={p}", wait_until="networkidle")
                await asyncio.sleep(5)
            
            print(f"  📄 正在抓取第 {p} 页...")
            page_jobs = await page.evaluate("""
                () => {
                    const results = [];
                    const rows = document.querySelectorAll('tr');
                    rows.forEach(row => {
                        const cells = Array.from(row.querySelectorAll('td'));
                        // 0:公司, 1:公司类型, 2:行业, 6:岗位, 9:截止时间
                        if (cells.length >= 10) {
                            const company = cells[0].innerText.trim();
                            if (company === "公司" || !company) return;
                            const a = row.querySelector('a');
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
            jobs.extend(page_jobs)
            print(f"  ✅ 第 {p} 页抓取成功，累计: {len(jobs)} 条")
            
    except Exception as e:
        print(f"  ❌ GiveMeOC 抓取失败: {e}")
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
        
        # 去重键：公司+岗位
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
            # 清理旧数据并写入新数据
            existing = fs.get_all_records(table_id)
            if existing:
                ids = [r['record_id'] for r in existing]
                fs.delete_records(table_id, ids)
            fs.add_records(table_id, valid_jobs)
            print(f"🎉 同步完成！{len(valid_jobs)} 条岗位已更新。")
    except Exception as e:
        print(f"  ❌ 飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
