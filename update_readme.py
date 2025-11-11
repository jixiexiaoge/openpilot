import os
import ssl
import requests
from bs4 import BeautifulSoup
import datetime
import json
import urllib3

# 🚫 全局禁用 SSL 验证
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://app.mspa.shop/"
README_FILE = "README.md"



def fetch_sponsor_data():
    """爬取排行榜信息（根据实际HTML结构调整选择器）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # ✅ 关闭 SSL 验证以避免证书错误
        r = requests.get(URL, headers=headers, timeout=20, verify=False)
        r.raise_for_status()
    except Exception as e:
        print(f"⚠️ 请求失败: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    sponsors = []
    # ⚙️ 根据实际网页结构修改以下选择器
    for item in soup.select(".sponsor-item"):
        username = item.select_one(".username")
        amount = item.select_one(".amount")

        if username and amount:
            # 提取数字部分，例如 "￥120" → 120
            num = ''.join(c for c in amount.text if c.isdigit())
            if num and int(num) > 60:
                sponsors.append({
                    "username": username.text.strip(),
                    "amount": int(num)
                })

    return sponsors


def format_sponsor_section(sponsors):
    """格式化输出 Markdown 段落"""
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
    """更新 README.md 从第 88 行开始"""
    if not os.path.exists(README_FILE):
        print("❌ 未找到 README.md 文件！")
        return

    with open(README_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 确保文件至少87行
    while len(lines) < 87:
        lines.append("\n")

    prefix = "".join(lines[:87])

    # 如果没抓到新数据，则保留旧内容
    if not sponsors:
        print("⚠️ 未获取到新数据，保留原排行榜内容。")
        return

    new_section = format_sponsor_section(sponsors)

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(prefix + new_section)

    print("✅ README.md 已更新。")


if __name__ == "__main__":
    data = fetch_sponsor_data()
    update_readme(data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
