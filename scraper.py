import os
import json
import time
import asyncio
import re
import schedule  # 新增：用于定时任务
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from feishu_utils import FeishuClient

# 环境变量
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
FEISHU_BASE_TOKEN = os.getenv("FEISHU_BASE_TOKEN")

def parse_date_to_ms(date_str):
    """
    将日期字符串解析为毫秒级时间戳。
    """
    if not date_str or any(x in date_str for x in ["不限", "见详情", "截止", "尽快", "长期"]):
        return None
    nums = re.findall(r'\d+', date_str)
    if not nums:
        return None
    try:
        year = datetime.now().year
        month, day = 1, 1
        if len(nums) >= 3:
            # 假设格式为 年-月-日 或 年/月/日
            year, month, day = int(nums[0]), int(nums[1]), int(nums[2])
            if year < 100:
                year += 2000
        elif len(nums) == 2:
            # 假设格式为 月-日
            month, day = int(nums[0]), int(nums[1])

        # 如果年份已经过去，则认为是下一年的日期
        current_date = datetime.now().date()
        target_date = datetime(year, month, day).date()
        if target_date < current_date:
            year += 1
            target_date = datetime(year, month, day).date()

        dt = datetime.combine(target_date, datetime.min.time())
        return int(time.mktime(dt.timetuple()) * 1000)
    except (ValueError, IndexError):
        return None

async def get_qiuzhifangzhou_data(page):
    """
    抓取求职方舟数据。
    """
    print("🚀 启动求职方舟【暴力翻页】模式...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle", timeout=120000)
        await asyncio.sleep(20)

        for page_num in range(1, 31): # 最多翻 30 页，确保全量
            print(f" 📄 正在全力抓取第 {page_num} 页...")
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
                print(" ⚠️ 本页没抓到数据，尝试再等会儿...")
                await asyncio.sleep(5)
                # 再次尝试获取，以防加载延迟
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
                
            jobs.extend(page_jobs)
            print(f" ✅ 第 {page_num} 页抓取成功，当前累计: {len(jobs)} 条")

            # 暴力寻找下一页按钮并模拟真实点击
            next_btn = await page.query_selector("button:has-text('下一页'), .ag-paging-button:has-text('下一页'), [aria-label='Next Page']")
            if next_btn and await next_btn.is_visible():
                await next_btn.click()
                await asyncio.sleep(8) # 翻页后死等加载
            else:
                print(" 🏁 已翻到最后一页。")
                break

    except Exception as e:
        print(f" ❌ 求职方舟抓取中断: {e}")
    return jobs

async def get_givemeoc_data(page):
    """
    抓取GiveMeOC数据。增加了翻页逻辑以检索所有页面。
    """
    print("🚀 启动 GiveMeOC 抓取...")
    jobs = []
    try:
        await page.goto("https://www.givemeoc.com/", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(15)

        # 确保页面加载完成
        await page.wait_for_selector('table')

        while True: # 循环处理所有页面
            print(" 📄 正在抓取当前 GiveMeOC 页面...")
            
            page_jobs = await page.evaluate("""
             () => {
                 const results = [];
                 const rows = document.querySelectorAll('tr');
                 rows.forEach(row => {
                     const cells = Array.from(row.querySelectorAll('td'));
                     // 根据实际表格结构调整索引
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
            print(f" ✅ 当前 GiveMeOC 页面抓取到 {len(page_jobs)} 条，累计: {len(jobs)} 条")

            # 查找并点击下一页按钮
            next_button_selector = 'button[aria-label="Go to next page"], .pagination-next' # 常见的下一页按钮选择器
            next_btn = await page.query_selector(next_button_selector)
            
            if next_btn and await next_btn.is_enabled() and await next_btn.is_visible():
                print(" 🔄 找到下一页按钮，准备翻页...")
                await next_btn.click()
                await asyncio.sleep(10) # 等待新页面加载
            else:
                print(" 🏁 GiveMeOC 已到达最后一页或找不到下一页按钮。")
                break # 退出循环

    except Exception as e:
        print(f" ❌ GiveMeOC 抓取失败: {e}")
    return jobs

async def get_careercenter_data(page):
    """
    新增函数：抓取careercenter数据。
    这是一个示例框架，您需要根据实际网站结构填充具体的选择器和数据提取逻辑。
    """
    print("🚀 启动 CareerCenter 抓取...")
    jobs = []
    try:
        # 示例网址，请替换为实际网址
        await page.goto("https://www.careercenter.com/jobs", wait_until="networkidle", timeout=90000)
        await asyncio.sleep(15)

        # --- 开始翻页逻辑 ---
        while True:
            print(" 📄 正在抓取当前 CareerCenter 页面...")
            
            # 示例：提取当前页所有职位信息
            # 注意：请根据实际网页结构调整选择器和索引
            page_jobs = await page.evaluate("""
             () => {
                 const results = [];
                 // 假设每个职位在一个特定的元素内，例如 .job-item
                 const jobItems = document.querySelectorAll('.job-item'); 
                 jobItems.forEach(item => {
                     // 假设公司名在 .company 元素中
                     const companyElement = item.querySelector('.company');
                     const company = companyElement ? companyElement.innerText.trim() : '';
                     
                     // 假设岗位名在 .position 元素中
                     const positionElement = item.querySelector('.position');
                     const position = positionElement ? positionElement.innerText.trim() : '';

                     // 假设截止时间在 .deadline 元素中
                     const deadlineElement = item.querySelector('.deadline');
                     const deadline = deadlineElement ? deadlineElement.innerText.trim() : '';

                     // 假设网申链接在 .apply-link 元素中
                     const linkElement = item.querySelector('.apply-link');
                     const link = linkElement ? linkElement.href : '';

                     if (company && position) { // 确保关键字段存在
                         results.push({
                             '公司名称': company,
                             '公司类型': '', // 需要从页面查找或留空
                             '行业类型': '', // 需要从页面查找或留空
                             '招聘届别': '', // 需要从页面查找或留空
                             '工作地点': '', // 需要从页面查找或留空
                             '招聘岗位': position,
                             '网申链接': link,
                             '招聘公告原文链接': link, // 或者指向职位详情页
                             '截止时间': deadline
                         });
                     }
                 });
                 return results;
             }
            """)

            jobs.extend(page_jobs)
            print(f" ✅ 当前 CareerCenter 页面抓取到 {len(page_jobs)} 条，累计: {len(jobs)} 条")

            # --- 寻找下一页按钮 ---
            # 请根据实际网站的分页按钮结构调整选择器
            # 例如: button.next, a[rel='next'], .pagination .next, etc.
            next_btn_selector = "button.next" # 示例选择器，请修改
            next_btn = await page.query_selector(next_btn_selector)
            
            if next_btn and await next_btn.is_enabled() and await next_btn.is_visible():
                print(" 🔄 找到下一页按钮，准备翻页...")
                await next_btn.click()
                await asyncio.sleep(10) # 等待新页面加载
            else:
                print(" 🏁 CareerCenter 已到达最后一页或找不到下一页按钮。")
                break # 退出循环
        # --- 结束翻页逻辑 ---

    except Exception as e:
        print(f" ❌ CareerCenter 抓取失败: {e}")
    return jobs


async def run_single_scrape():
    """
    执行单次抓取任务的核心逻辑。
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        all_raw = []
        all_raw.extend(await get_qiuzhifangzhou_data(page))
        all_raw.extend(await get_givemeoc_data(page))
        # all_raw.extend(await get_careercenter_data(page)) # 启用此行以包含第三个表格

        await browser.close()

        # --- 数据处理与去重 ---
        valid_jobs = []
        seen_companies_positions = set() # 使用集合存储 (公司, 岗位) 元组进行去重
        now_ms = int(time.time() * 1000)

        for job in all_raw:
            company = job['公司名称'].strip()
            position = job['招聘岗位'].strip()
            if not company or not position:
                continue

            # 解析截止时间
            deadline_str = job.get("截止时间", "")
            deadline_ms = parse_date_to_ms(deadline_str)

            # 创建去重键
            key_tuple = (company, position)
            if key_tuple in seen_companies_positions:
                continue # 跳过重复项

            seen_companies_positions.add(key_tuple)

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
                "截止时间": deadline_ms # 确保截止时间被写入
            })

        print(f"📊 任务汇总：总计抓取 {len(valid_jobs)} 条有效岗位。正在同步到飞书...")
        
        try:
            fs = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
            table_id = fs.get_table_id()
            if table_id:
                existing = fs.get_all_records(table_id)
                if existing:
                    ids = [r['record_id'] for r in existing]
                    for i in range(0, len(ids), 500):
                        fs.delete_records(table_id, ids[i:i+500])
                for i in range(0, len(valid_jobs), 100):
                    fs.add_records(table_id, valid_jobs[i:i+100])
            print(f"🎉 大功告成！{len(valid_jobs)} 条岗位已全部同步！")
        except Exception as e:
            print(f" ❌ 飞书同步失败: {e}")

def scheduled_job():
    """
    定时任务调用的函数。
    """
    print(f"\n--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始执行定时抓取任务 ---")
    # 使用 asyncio.run 在同步函数中运行异步代码
    asyncio.run(run_single_scrape())
    print(f"--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 定时抓取任务完成 ---\n")


async def main():
    """
    主函数，设置定时任务并保持程序运行。
    """
    # 设置每天上午10点执行抓取任务
    schedule.every().day.at("10:00").do(scheduled_job)

    print("启动定时任务调度器...")
    print("将按计划在每天 10:00 执行数据抓取。")
    
    # 执行一次（可选）
    # print("执行一次即时抓取...")
    # await run_single_scrape()

    # 保持程序持续运行以监听定时任务
    while True:
        schedule.run_pending()
        await asyncio.sleep(60) # 每分钟检查一次是否有任务需要执行

if __name__ == "__main__":
    # 直接运行脚本时，启动定时任务
    asyncio.run(main())
