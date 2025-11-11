# update_readme.py
import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import re

# 目标 URL（你提供的 ip）
URL = "http://31.97.51.107:8500/"
README_FILE = "README.md"
MIN_AMOUNT = 60  # 只提取大于此数的赞助


def fetch_sponsor_data():
    """
    抓取 sponsor 列表并返回 [{'username':..., 'amount':...}, ...]
    需要根据页面实际 DOM 调整选择器（下面尝试了几种常见方案）
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(URL, headers=headers, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"⚠️ 请求失败: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    results = []

    # --- 尝试多种常见结构来提取用户名和金额 ---
    # 优先级：显式 class -> 表格 -> 列表文本
    # 1) 明确的 sponsor-item / username / amount
    for item in soup.select(".sponsor-item"):
        name_el = item.select_one(".username") or item.select_one(".name") or item.select_one("h3")
        amt_el = item.select_one(".amount") or item.select_one(".money") or item.select_one(".price")
        if name_el and amt_el:
            name = name_el.get_text(strip=True)
            amt = extract_number(amt_el.get_text())
            if amt is not None and amt > MIN_AMOUNT:
                results.append({"username": name, "amount": amt})

    # 2) 表格形式：<table><tr><td>name</td><td>amount</td></tr>
    if not results:
        table_rows = soup.select("table tr")
        for tr in table_rows:
            cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cols) >= 2:
                # 假设最后一列是金额，第一列或第二列是名称
                name = cols[0]
                amt = extract_number(cols[-1])
                if amt is not None and amt > MIN_AMOUNT:
                    results.append({"username": name, "amount": amt})

    # 3) 列表或纯文本查找：类似 "用户名 — ￥120"
    if not results:
        text = soup.get_text(separator="\n")
        for line in text.splitlines():
            # 找到有数字的钱金额行
            if re.search(r"\d", line):
                amt = extract_number(line)
                if amt is not None and amt > MIN_AMOUNT:
                    # 尝试把用户名设为数字前的文本（最多 40 chars）
                    name = line.strip()
                    # 去掉金额文本，让名字更干净
                    name = re.sub(r"[\d\.,\s￥$¥USDusd,]+$", "", name).strip()
                    if not name:
                        name = "unknown"
                    results.append({"username": name[:60], "amount": amt})

    # 去重并按金额降序排序（若用户名重复，保留最高的一条）
    dedup = {}
    for r in results:
        key = r["username"]
        if key not in dedup or r["amount"] > dedup[key]:
            dedup[key] = r["amount"]

    final = [{"username": k, "amount": v} for k, v in dedup.items()]
    final.sort(key=lambda x: x["amount"], reverse=True)
    return final


def extract_number(s: str):
    """
    从字符串中提取第一个数字（整数或小数），返回 float 或 None
    例子: "￥120" -> 120.0, "120.5 USD" -> 120.5
    """
    if not s:
        return None
    s = s.replace(",", "")  # 去千分位逗号
    m = re.search(r"(-?\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        val = float(m.group(1))
        return val
    except:
        return None


def format_sponsor_section(sponsors):
    """生成 markdown 段落"""
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    if not sponsors:
        sponsor_md = "_暂无数据_"
    else:
        sponsor_md = "\n".join([f"- **{s['username']}** — 💰 {format_amount(s['amount'])}" for s in sponsors])

    return f"""
---

### 🏆 赞助排行榜（自动更新）

> 数据来源：[{URL}]({URL})  
> 更新时间：{timestamp}

{sponsor_md}

（本段内容由 GitHub Actions 自动更新）
"""


def format_amount(x):
    # 去掉小数位 .0，保留整数或一位小数
    if abs(x - int(x)) < 1e-9:
        return str(int(x))
    else:
        return f"{x:.2f}"


def update_readme(sponsors):
    """保留前 87 行，从第 88 行写入新段落；若无数据则不修改文件"""
    if not os.path.exists(README_FILE):
        print("❌ 未找到 README.md 文件！")
        return

    with open(README_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 确保至少有 87 行
    while len(lines) < 87:
        lines.append("\n")

    if not sponsors:
        print("⚠️ 未获取到新数据，保留原排行榜内容。")
        return

    prefix = "".join(lines[:87])
    new_section = format_sponsor_section(sponsors)

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(prefix + new_section)

    print("✅ README.md 已更新。")


if __name__ == "__main__":
    data = fetch_sponsor_data()
    # 打印 JSON 结果到日志，方便调试
    print(json.dumps(data, ensure_ascii=False, indent=2))
    update_readme(data)
