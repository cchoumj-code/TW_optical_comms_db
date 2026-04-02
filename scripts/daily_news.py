"""
daily_news.py — FREE VERSION (no Anthropic API needed)
Uses DuckDuckGo search + RSS feeds to pull news.
Runs daily via GitHub Actions.
Pushes digest to Notion page.
"""

import requests
import json
import os
from datetime import date, timedelta
from xml.etree import ElementTree as ET
import urllib.parse

today     = date.today().strftime("%Y-%m-%d")
yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

COMPANIES = [
    ("3081", "聯亞",    "LiquidCool"),
    ("2455", "全新",    "Global Comm Semi"),
    ("4971", "IET-KY",  "Innovative Epitaxial"),
    ("6451", "訊芯-KY", "Applied Opto TW"),
    ("3105", "穩懋",    "WIN Semiconductors"),
    ("3363", "上詮",    "SENKO Advanced"),
    ("3163", "波若威",  "ProLight Opto"),
    ("4979", "華星光",  "HiLight Semi"),
    ("6442", "光聖",    "Radiant Opto"),
    ("4977", "眾達-KY", "Luxshare Optical"),
    ("6530", "創威",    "Coretek"),
    ("4903", "聯光通",  "Lanto Comm"),
    ("3450", "聯鈞",    "Luxtera TW"),
    ("6515", "穎崴",    "Ying Wei Tech"),
    ("6223", "旺矽",    "MPI Corporation"),
    ("6510", "精測",    "Chroma ATE"),
    ("2345", "智邦",    "Accton Technology"),
    ("6426", "統新",    "Apogee Optocom"),
    ("2330", "台積電",  "TSMC"),
]

SECTOR_QUERIES_EN = [
    "CPO co-packaged optics Taiwan 2025",
    "silicon photonics Taiwan supply chain",
    "TSMC COUPE optical",
    "NVIDIA Rubin optical interconnect",
    "800G 1.6T optical transceiver Taiwan",
]

SECTOR_QUERIES_ZH = [
    "共封裝光學 CPO 台灣",
    "矽光子 台積電 供應鏈",
    "光通訊 台股 法說會",
    "上詮 聯亞 波若威 光聖",
    "光纖 AI伺服器 台灣廠商",
]

# Credible Chinese-language RSS sources
CHINESE_RSS_FEEDS = [
    {
        "name": "經濟日報 (UDN Economy)",
        "url": "https://money.udn.com/rssfeed/news/1/5607?ch=money",  # Tech/stocks
    },
    {
        "name": "中央社 (CNA)",
        "url": "https://www.cna.com.tw/RSS/fnc.xml",  # Finance & economy
    },
    {
        "name": "工商時報 (CTEE)",
        "url": "https://ctee.com.tw/feed",
    },
    {
        "name": "鉅亨網 (Anue)",
        "url": "https://news.cnyes.com/api/v3/news/category/tw_stock/latest?limit=30",
        "is_json": True,  # Anue uses JSON API not XML
    },
]

# Keywords to filter Chinese articles for relevance
RELEVANCE_KEYWORDS = [
    "光通訊", "矽光子", "CPO", "共封裝", "光收發", "磊晶",
    "上詮", "聯亞", "波若威", "光聖", "穩懋", "智邦", "台積電",
    "800G", "1.6T", "InP", "光纖", "AI伺服器", "光引擎",
    "3081", "3363", "3163", "6442", "2345", "2330",
]

# ── Google News RSS (English) ──────────────────────────────
def search_google_news_rss(query, max_results=5, lang="en"):
    """Pull headlines from Google News RSS — completely free."""
    encoded = urllib.parse.quote(query)
    if lang == "zh":
        url = f"https://news.google.com/rss/search?q={encoded}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    else:
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:max_results]
        results = []
        for item in items:
            title   = item.findtext("title", "").split(" - ")[0].strip()
            source  = item.findtext("title", "").split(" - ")[-1].strip()
            pubdate = item.findtext("pubDate", "")[:16]
            link    = item.findtext("link", "")
            results.append({
                "title": title, "source": source,
                "date": pubdate, "link": link,
            })
        return results
    except Exception as e:
        print(f"  RSS error for '{query}': {e}")
        return []

# ── Chinese RSS feed scraper ───────────────────────────────
def fetch_chinese_rss(feed, max_results=8):
    """Fetch and filter articles from Chinese financial news RSS feeds."""
    results = []
    try:
        headers = {"User-Agent": "Mozilla/5.0",
                   "Accept": "application/rss+xml, application/xml, text/xml, */*"}

        # Anue uses JSON API
        if feed.get("is_json"):
            r = requests.get(feed["url"], timeout=10, headers=headers)
            if r.status_code != 200:
                return []
            data = r.json()
            items = data.get("items", data.get("data", {}).get("list", []))[:20]
            for item in items:
                title = item.get("title", "")
                if any(kw in title for kw in RELEVANCE_KEYWORDS):
                    results.append({
                        "title":  title,
                        "source": feed["name"],
                        "date":   item.get("publishAt", today)[:10],
                        "link":   f"https://news.cnyes.com/news/id/{item.get('newsId','')}",
                    })
            return results[:max_results]

        # Standard XML RSS
        r = requests.get(feed["url"], timeout=10, headers=headers)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:30]
        for item in items:
            title = item.findtext("title", "").strip()
            if any(kw in title for kw in RELEVANCE_KEYWORDS):
                results.append({
                    "title":  title,
                    "source": feed["name"],
                    "date":   item.findtext("pubDate", "")[:16],
                    "link":   item.findtext("link", ""),
                })
        return results[:max_results]

    except Exception as e:
        print(f"  Feed error [{feed['name']}]: {e}")
        return []

# ── Build sector news digest ───────────────────────────────
def get_sector_news():
    print("Scanning sector news (English + Chinese sources)...")
    all_headlines = []
    seen = set()

    # English — Google News RSS
    for query in SECTOR_QUERIES_EN:
        for item in search_google_news_rss(query, max_results=3, lang="en"):
            if item["title"] not in seen:
                seen.add(item["title"])
                item["lang"] = "EN"
                all_headlines.append(item)

    # Traditional Chinese — Google News RSS (TW)
    for query in SECTOR_QUERIES_ZH:
        for item in search_google_news_rss(query, max_results=3, lang="zh"):
            if item["title"] not in seen:
                seen.add(item["title"])
                item["lang"] = "ZH"
                all_headlines.append(item)

    # Chinese financial RSS feeds
    print("  Fetching Chinese financial sources...")
    for feed in CHINESE_RSS_FEEDS:
        print(f"    → {feed['name']}")
        for item in fetch_chinese_rss(feed, max_results=5):
            if item["title"] not in seen:
                seen.add(item["title"])
                item["lang"] = "ZH"
                all_headlines.append(item)

    if not all_headlines:
        return "No significant sector news found today."

    # Separate by language for clean formatting
    en_news = [h for h in all_headlines if h.get("lang") == "EN"][:8]
    zh_news = [h for h in all_headlines if h.get("lang") == "ZH"][:10]

    lines = [f"**Sector News — CPO & Silicon Photonics ({today})**\n"]

    if en_news:
        lines.append("── English Sources ──")
        for h in en_news:
            lines.append(f"- {h['title']}\n  {h['source']} | {h['date']}")

    if zh_news:
        lines.append("\n── 中文來源 (Chinese Sources) ──")
        for h in zh_news:
            lines.append(f"- {h['title']}\n  {h['source']} | {h['date']}")

    return "\n".join(lines)

# ── Earnings detection ────────────────────────────────────
def get_earnings_digest():
    print("Checking for earnings calls...")
    results = []
    seen = set()

    for ticker, name_cn, name_en in COMPANIES:
        # English queries
        for query in [f"{name_en} earnings results 2025",
                      f"Taiwan {ticker} quarterly results"]:
            for item in search_google_news_rss(query, max_results=2, lang="en"):
                t = item["title"].lower()
                if any(kw in t for kw in ["earn","revenue","result","quarter","profit"]):
                    if item["title"] not in seen:
                        seen.add(item["title"])
                        results.append({**item, "company": f"{ticker} {name_en} {name_cn}", "lang": "EN"})

        # Chinese queries — 法說會, 營收
        for query in [f"{name_cn} 法說會", f"{name_cn} 營收 {date.today().year}"]:
            for item in search_google_news_rss(query, max_results=2, lang="zh"):
                t = item["title"]
                if any(kw in t for kw in ["法說","營收","獲利","EPS","季報","業績"]):
                    if item["title"] not in seen:
                        seen.add(item["title"])
                        results.append({**item, "company": f"{ticker} {name_en} {name_cn}", "lang": "ZH"})

    # Also check Chinese RSS feeds for earnings
    for feed in CHINESE_RSS_FEEDS:
        for item in fetch_chinese_rss(feed, max_results=10):
            t = item["title"]
            if any(kw in t for kw in ["法說","營收","獲利","EPS","季報"]):
                if item["title"] not in seen:
                    seen.add(item["title"])
                    results.append({**item, "company": "sector", "lang": "ZH"})

    if not results:
        return "No earnings calls or quarterly results detected this week."

    en_r = [r for r in results if r.get("lang") == "EN"][:5]
    zh_r = [r for r in results if r.get("lang") == "ZH"][:8]

    lines = [f"**Earnings & Results Digest ({today})**\n"]
    if en_r:
        lines.append("── English ──")
        for r in en_r:
            lines.append(f"- [{r['company']}] {r['title']}\n  {r['source']} | {r['date']}")
    if zh_r:
        lines.append("\n── 中文 (Chinese) ──")
        for r in zh_r:
            lines.append(f"- [{r['company']}] {r['title']}\n  {r['source']} | {r['date']}")
    return "\n".join(lines)

# ── Supply chain change detection ─────────────────────────
def get_supply_chain_alerts():
    print("Checking supply chain changes...")
    results = []
    seen = set()

    sc_queries = [
        "CPO supply chain win design Taiwan",
        "上詮 SENKO customer order",
        "聯亞 LiquidCool InP capacity",
        "光聖 Radiant Opto Google contract",
        "智邦 Accton NVIDIA switch",
        "TSMC COUPE silicon photonics production",
        "Taiwan optical component supplier change",
    ]

    for query in sc_queries:
        items = search_google_news_rss(query, max_results=3)
        for item in items:
            if item["title"] not in seen:
                seen.add(item["title"])
                results.append(item)

    if not results:
        return "No supply chain changes detected today."

    lines = [f"**Supply Chain Alerts ({today})**\n"]
    for r in results[:8]:
        lines.append(f"- {r['title']}\n  {r['source']} | {r['date']}")
    return "\n".join(lines)

# ── Push to Notion ─────────────────────────────────────────
def push_to_notion(sector_news, earnings, supply_chain):
    notion_key = os.environ.get("NOTION_API_KEY")
    page_id    = os.environ.get("NOTION_PAGE_ID")

    if not notion_key or not page_id:
        print("\n=== DIGEST OUTPUT (Notion not configured) ===\n")
        print(sector_news)
        print("\n" + earnings)
        print("\n" + supply_chain)
        return

    headers = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    def h2(text):
        return {"object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text",
                               "text": {"content": text}}]}}

    def para(text, bold=False):
        return {"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text",
                               "text": {"content": text},
                               "annotations": {"bold": bold}}]}}

    def divider():
        return {"object": "block", "type": "divider", "divider": {}}

    blocks = [
        h2(f"Daily Intelligence Digest — {today}"),
        divider(),
        para("SECTOR NEWS & CPO UPDATES", bold=True),
        para(sector_news),
        divider(),
        para("EARNINGS CALL DIGEST", bold=True),
        para(earnings),
        divider(),
        para("SUPPLY CHAIN CHANGE ALERTS", bold=True),
        para(supply_chain),
        divider(),
    ]

    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    r = requests.patch(url, headers=headers, json={"children": blocks})
    if r.status_code == 200:
        print(f"Notion updated successfully for {today}")
    else:
        print(f"Notion error {r.status_code}: {r.text}")

# ── Main ───────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n=== Daily News Pipeline (Free) — {today} ===\n")
    sector_news  = get_sector_news()
    earnings     = get_earnings_digest()
    supply_chain = get_supply_chain_alerts()
    push_to_notion(sector_news, earnings, supply_chain)
    print("\nDone.")
