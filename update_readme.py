import requests
from bs4 import BeautifulSoup
import datetime
import json
import re
import os

URL = "https://app.mspa.shop/"
README_FILE = "README.md"

def fetch_sponsor_data():
    """爬取排行榜信息（根据实际HTML结构自行调整选择器）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(URL, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"⚠️ 请求失败: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    sponsors = []
    for item in soup.select(".sponsor-item"):
        username = item.select_one(".username")
        amount = item.select_one(".amount")

        if username and amount:
            num = ''.join(c for c in amount.text if c.isdigit())
            if num and int(num) > 60:
                sponsors.append({
                    "username": username.text.strip(),
                    "amount": int(num)
                })
    return sponsors


def format_sponsor_section(sponsors):
    """格式化输出文本"""
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    sponsor_md = "\n".join(
        [f"- **{s['username']}** — 💰 {s['amount']}" for s in sponsors]
    ) or "_暂无数据_"

    return f"""
---

### 🏆 赞助排行榜（自动更新）

> 数据来源：[MSPA Shop]({URL})  
> 更新时间：{timestamp}

{sponsor_md}

（本段内容由 GitHub Actions 自动更新）
"""


def update_readme(sponsors):
    """更新 README.md，从第 88 行开始替换"""
    if not os.path.exists(README_FILE):
        print("❌ 未找到 README.md 文件！")
        return

    with open(README_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 确保至少有87行
    while len(lines) < 87:
        lines.append("\n")

    # 保留前87行，更新之后的内容
    prefix = "".join(lines[:87])
    new_section = format_sponsor_section(sponsors)

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(prefix + new_section)

    print("✅ README.md 已更新。")


if __name__ == "__main__":
    data = fetch_sponsor_data()
    update_readme(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
