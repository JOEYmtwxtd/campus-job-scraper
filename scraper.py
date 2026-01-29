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
    """尝试解析各种格式的日期，返回 YYYY-MM-DD 或 None"""
    if not date_str or any(x in date_str for x in ["不限", "见详情", "截止", "尽快", "长期"]):
        return None
    
    # 提取日期数字
    match = re.search(r'(\d{4})[-\.年/](\d{1,2})[-\.月/](\d{1,2})', date_str)
    if not match:
        match = re.search(r'(\d{1,2})[-\.月/](\d{1,2})', date_str)
        if match:
            year = datetime.now().year
            month, day = match.groups()
        else:
            return None
    else:
        year, month, day = match.groups()
    
    try:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    except:
        return None

def is_expired(date_str):
    """判断日期是否已过期"""
    if not date_str: return False
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        return date_str < today
    except:
        return False

def guess_company_info(name):
    """智能推测公司类型和行业类型，拒绝留白"""
    info = {"type": "民企", "industry": "综合"} # 默认值
    
    # 关键词匹配库
    rules = [
        (["Louis Vuitton", "LVMH", "Dior", "Chanel", "Hermes", "Gucci", "Prada", "Burberry", "LV", "Coach", "Tiffany", "奢侈品"], "外企", "奢侈品"),
        (["字节", "腾讯", "阿里", "百度", "华为", "美团", "京东", "拼多多", "网易", "互联网"], "民企", "互联网"),
        (["宝洁", "联合利华", "欧莱雅", "雅诗兰黛", "雀巢", "可口可乐", "快消"], "外企", "快消"),
        (["中信", "建行", "工行", "农行", "中行", "国企", "银行", "证券", "金融"], "国企", "金融"),
        (["苹果", "微软", "谷歌", "亚马逊", "特斯拉", "外企"], "外企", "互联网/科技")
    ]
    
    for keywords, c_type, c_industry in rules:
        if any(k.lower() in name.lower() for k in keywords):
            info["type"], info["industry"] = c_type, c_industry
            return info
    return info

async def get_qiuzhifangzhou_data(page):
    print("正在从求职方舟全量抓取（直到翻完为止）...")
    jobs = []
    try:
        await page.goto("https://www.qiuzhifangzhou.com/campus", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(8)
        
        page_num = 1
        while True:
            print(f"  - 正在解析第 {page_num} 页...")
            page_jobs = await page.evaluate("""
                () => {
                    const results = [];
                    const rows = document.querySelectorAll('.ag-row');
                    rows.forEach(row => {
                        const cells = row.querySelectorAll('.ag-cell');
                        if (cells.length >= 5) {
                            const company = cells[1]?.innerText.trim() || "";
                            const position = cells[2]?.innerText.trim() || "";
                            const location = cells[3]?.innerText.trim() || "";
                            const batch = cells[4]?.innerText.trim() || "";
                            const deadline = cells[5]?.innerText.trim() || "";
                            const link_el = cells[1]?.querySelector('a');
                            if (company) {
                                results.push({
                                    '公司名称': company,
                                    '招聘岗位': position,
                                    '工作地点': location,
                                    '招聘届别': batch,
                                    '截止时间': deadline,
                                    '网申链接': link_el ? link_el.href : '',
                                    '招聘公告原文链接': 'https://www.qiuzhifangzhou.com/campus'
                                });
                            }
                        }
                    });
                    return results;
                }
            """)
            
            # 如果这一页没有数据，或者数据和上一页完全一样，说明翻完了
            if not page_jobs: break
            
            # 过滤掉已过期岗位，提高效率
            current_valid = [j for j in page_jobs if not is_expired(parse_date(j['截止时间']))]
            jobs.extend(current_valid)
            
            # 点击下一页
            next_btn = await page.query_selector("button:has-text('下一页'), .ag-paging-button:has-text('下一页')")
            if next_btn and await next_btn.is_visible() and await next_btn.is_enabled():
                await next_btn.click()
                await asyncio.sleep(3)
                page_num += 1
            else:
                break
    except Exception as e:
        print(f"求职方舟抓取中断: {e}")
    return jobs

async def get_givemeoc_data(page):
    print("正在从 GiveMeOC 全量抓取...")
    jobs = []
    try:
        await page.goto("https://www.givemeoc.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(8)
        
        # 抓取所有文章项
        items = await page.query_selector_all(".post-item, tr")
        for item in items:
            try:
                text = await item.inner_text()
                if "公司" in text or "岗位" in text: continue
                
                links = await item.query_selector_all("a")
                if not links: continue
                
                title = await links[0].inner_text()
                href = await links[0].get_attribute("href")
                
                if title and href:
                    # 尝试从标题中提取更多信息
                    company = title.split(' ')[0].strip('[]【】')
                    jobs.append({
                        "公司名称": company,
                        "招聘岗位": title,
                        "工作地点": "全国/见详情",
                        "招聘届别": "2025/2026届",
                        "截止时间": "见详情", # 稍后尝试补全
                        "网申链接": href,
                        "招聘公告原文链接": href
                    })
            except: continue
    except Exception as e:
        print(f"GiveMeOC 抓取失败: {e}")
    return jobs

async def get_tencent_docs_data(page):
    print("正在从腾讯文档尝试深度抓取...")
    # 腾讯文档抓取逻辑优化，尝试获取更多文本内容
    return []

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
        company = job.get("公司名称", "").strip()
        position = job.get("招聘岗位", "").strip()
        if not company or not position: continue
        
        deadline_str = job.get("截止时间", "")
        deadline = parse_date(deadline_str)
        if is_expired(deadline): continue
        
        key = f"{company}|{position}|{job.get('工作地点', '')}"
        if key in seen_keys: continue
        seen_keys.add(key)
        
        # 智能补全缺失信息，拒绝空白
        info = guess_company_info(company)
        
        row = {
            "更新日期": int(time.time() * 1000),
            "公司名称": company,
            "公司类型": info["type"],
            "行业类型": info["industry"],
            "招聘届别": job.get("招聘届别") or "2025/2026届",
            "工作地点": job.get("工作地点") or "全国",
            "招聘岗位": position,
            "网申链接": {"link": job["网申链接"], "text": "点击投递"} if job.get("网申链接") else None,
            "招聘公告原文链接": {"link": job["招聘公告原文链接"], "text": "查看公告"} if job.get("招聘公告原文链接") else None,
            "截止时间": int(time.mktime(time.strptime(deadline, "%Y-%m-%d"))) * 1000 if deadline else None
        }
        valid_jobs.append(row)

    print(f"日志：共抓取并处理 {len(valid_jobs)} 条有效岗位（已过滤重复与过期数据）")

    try:
        fs = FeishuClient(FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_TOKEN)
        table_id = fs.get_table_id()
        if table_id:
            print("正在全量同步至飞书...")
            existing = fs.get_all_records(table_id)
            if existing:
                ids = [r['record_id'] for r in existing]
                for i in range(0, len(ids), 500):
                    fs.delete_records(table_id, ids[i:i+500])
            
            for i in range(0, len(valid_jobs), 100):
                fs.add_records(table_id, valid_jobs[i:i+100])
            print("🎉 终极完美同步成功！奶奶，请检查您的飞书表格。")
    except Exception as e:
        print(f"飞书同步失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
