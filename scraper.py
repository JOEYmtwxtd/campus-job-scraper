import os
import asyncio
import json
from playwright.async_api import async_playwright
from datetime import datetime

from feishu_utils import FeishuTable

# 飞书配置：从环境变量读取（与 GitHub Secrets 名称完全对应）
FEISHU_APP_ID     = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
FEISHU_BASE_TOKEN = os.environ.get("FEISHU_BASE_TOKEN")
FEISHU_TABLE_ID   = os.environ.get("FEISHU_TABLE_ID")


async def scrape_qiuzhifangzhou(page):
    """求职方舟：解决翻页超时和抓取为空的问题"""
    jobs = []
    print("正在连接: 求职方舟...")
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="networkidle", timeout=60000)

        for i in range(1, 31):  # 限制抓取 30 页
            print(f"  正在处理求职方舟第 {i} 页...")
            await page.wait_for_selector(".ag-row", timeout=10000)

            rows = await page.query_selector_all(".ag-row")
            for row in rows:
                cells = await row.query_selector_all(".ag-cell")
                if len(cells) >= 8:
                    company  = (await cells[1].inner_text()).strip()
                    position = (await cells[2].inner_text()).strip()
                    deadline = (await cells[7].inner_text()).strip()
                    link_elem = await cells[2].query_selector("a")
                    link = await link_elem.get_attribute("href") if link_elem else ""
                    if link and not link.startswith("http"):
                        link = "https://www.qiuzhifangzhou.com" + link

                    if company and position:
                        jobs.append({
                            "更新日期": datetime.now().strftime("%Y/%m/%d"),
                            "公司名称": company,
                            "招聘岗位": position,
                            "网申链接": {"link": link, "text": "点击投递"} if link else "",
                            "截止时间": deadline
                        })

            # 智能翻页
            can_next = await page.evaluate("""() => {
                const btn = document.querySelector('[ref="btNext"]');
                if (btn && !btn.disabled && !btn.classList.contains('ag-disabled')) {
                    btn.click();
                    return true;
                }
                return false;
            }""")
            if not can_next:
                break
            await asyncio.sleep(2)
    except Exception as e:
        print(f"求职方舟出错: {e}")
    print(f"求职方舟抓取完成，共 {len(jobs)} 条")
    return jobs


async def scrape_givemeoc(page):
    """GiveMeOC：解决只抓 30 条和翻页失效的问题"""
    jobs = []
    print("正在连接: GiveMeOC...")
    try:
        for p in range(1, 11):  # 抓取前 10 页
            print(f"  正在处理 GiveMeOC 第 {p} 页...")
            await page.goto(f"https://www.givemeoc.com/?paged={p}", wait_until="domcontentloaded")
            await page.wait_for_selector("table", timeout=10000)

            rows = await page.query_selector_all("tr")
            for row in rows[1:]:  # 跳过表头
                cells = await row.query_selector_all("td")
                if len(cells) >= 10:
                    company  = (await cells[1].inner_text()).strip()
                    position = (await cells[6].inner_text()).strip()
                    deadline = (await cells[9].inner_text()).strip()
                    link_elem = await cells[6].query_selector("a")
                    link = await link_elem.get_attribute("href") if link_elem else ""

                    if company and position:
                        jobs.append({
                            "更新日期": datetime.now().strftime("%Y/%m/%d"),
                            "公司名称": company,
                            "招聘岗位": position,
                            "网申链接": {"link": link, "text": "点击投递"} if link else "",
                            "截止时间": deadline
                        })
            await asyncio.sleep(1)
    except Exception as e:
        print(f"GiveMeOC 出错: {e}")
    print(f"GiveMeOC 抓取完成，共 {len(jobs)} 条")
    return jobs


async def main():
    # 检查必要的环境变量
    missing = [k for k, v in {
        "FEISHU_APP_ID": FEISHU_APP_ID,
        "FEISHU_APP_SECRET": FEISHU_APP_SECRET,
        "FEISHU_BASE_TOKEN": FEISHU_BASE_TOKEN,
        "FEISHU_TABLE_ID": FEISHU_TABLE_ID
    }.items() if not v]

    if missing:
        raise EnvironmentError(f"缺少必要的环境变量: {missing}")

    print(f"[配置] BASE_TOKEN={FEISHU_BASE_TOKEN}, TABLE_ID={FEISHU_TABLE_ID}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        all_jobs = []
        all_jobs.extend(await scrape_qiuzhifangzhou(page))
        all_jobs.extend(await scrape_givemeoc(page))

        print(f"\n抓取完成！总计 {len(all_jobs)} 条记录。")

        if all_jobs:
            feishu = FeishuTable(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
            written = feishu.batch_add_records(FEISHU_TABLE_ID, all_jobs)
            print(f"数据已成功同步至飞书，写入 {written} 条。")
        else:
            print("本次抓取结果为空，跳过飞书写入。")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
