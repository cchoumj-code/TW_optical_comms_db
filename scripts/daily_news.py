"""
daily_news.py — FREE VERSION (no Anthropic API needed)
Uses Google News RSS + Chinese RSS feeds to pull news.
Runs daily via GitHub Actions. Pushes to Supabase.
"""

import requests
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
    "CPO co-packaged optics Taiwan 2026",
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

CHINESE_RSS_FEEDS = [
    {"name": "經濟日報", "url": "https://money.udn.com/rssfeed/news/1/5607?ch=money"},
    {"name": "中央社",   "url": "https://www.cna.com.tw/RSS/fnc.xml"},
    {"name": "工商時報", "url": "https://ctee.com.tw/feed"},
    {"name": "鉅亨網",   "url": "https://news.cnyes.com/api/v3/news/category/tw_stock/latest?limit=30", "is_json": True},
]

RELEVANCE_KEYWORDS = [
    "光通訊","矽光子","CPO","共封裝","光收發","磊晶",
    "上詮","聯亞","波若威","光聖","穩懋","智邦","台積電",
    "800G","1.6T","InP","光纖","AI伺服器","光引擎",
    "3081","3363","3163","6442","2345","2330",
]

SC_QUERIES = [
    "CPO supply chain win design Taiwan",
    "上詮 SENKO customer order",
    "聯亞 LiquidCool InP capacity",
    "光聖 Radiant Opto Google contract",
    "智邦 Accton NVIDIA switch",
    "TSMC COUPE silicon photonics production",
]

def search_google_news_rss(query, max_results=5, lang="en"):
    encoded = urllib.parse.quote(query)
    if lang == "zh":
        url = f"https://news.google.com/rss/search?q={encoded}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    else:
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        results = []
        for item in root.findall(".//item")[:max_results]:
            title   = item.findtext("title", "").split(" - ")[0].strip()
            source  = item.findtext("title", "").split(" - ")[-1].strip()
            pubdate = item.findtext("pubDate", "")[:16]
            link    = item.findtext("link", "")
            results.append({"title": title, "source": source, "date": pubdate, "link": link})
        return results
    except Exception as e:
        print(f"  RSS error '{query}': {e}")
        return []

def fetch_chinese_rss(feed, max_results=8):
    results = []
    try:
        hdrs = {"User-Agent": "Mozilla/5.0", "Accept": "application/rss+xml, */*"}
        if feed.get("is_json"):
            r = requests.get(feed["url"], timeout=10, headers=hdrs)
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
        r = requests.get(feed["url"], timeout=10, headers=hdrs)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:30]:
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

def push_to_notion(sector_news, earnings, supply_chain):
    notion_key = os.environ.get("NOTION_API_KEY")
    page_id    = os.environ.get("NOTION_PAGE_ID")
    if not notion_key or not page_id:
        print("Notion not configured — skipping")
        return
    hdrs = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    def h2(t):
        return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":t}}]}}
    def para(t):
        return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":t}}]}}
    def divider():
        return {"object":"block","type":"divider","divider":{}}
    blocks = [
        h2(f"Daily Intelligence Digest - {today}"), divider(),
        para("SECTOR NEWS"), para(sector_news), divider(),
        para("EARNINGS"), para(earnings), divider(),
        para("SUPPLY CHAIN"), para(supply_chain), divider(),
    ]
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    r = requests.patch(url, headers=hdrs, json={"children": blocks})
    print(f"Notion: {r.status_code}")

if __name__ == "__main__":
    print(f"\n=== Daily News Pipeline — {today} ===\n")

    all_headlines = []
    seen = set()
    en_news = []
    zh_news = []

    print("Scanning English news...")
    for query in SECTOR_QUERIES_EN:
        for item in search_google_news_rss(query, max_results=3, lang="en"):
            if item["title"] not in seen:
                seen.add(item["title"])
                item["lang"] = "EN"
                item["category"] = "sector"
                en_news.append(item)
                all_headlines.append(item)

    print("Scanning Chinese news...")
    for query in SECTOR_QUERIES_ZH:
        for item in search_google_news_rss(query, max_results=3, lang="zh"):
            if item["title"] not in seen:
                seen.add(item["title"])
                item["lang"] = "ZH"
                item["category"] = "sector"
                zh_news.append(item)
                all_headlines.append(item)

    print("Fetching Chinese RSS feeds...")
    for feed in CHINESE_RSS_FEEDS:
        print(f"  -> {feed['name']}")
        for item in fetch_chinese_rss(feed, max_results=5):
            if item["title"] not in seen:
                seen.add(item["title"])
                item["lang"] = "ZH"
                item["category"] = "sector"
                zh_news.append(item)
                all_headlines.append(item)

    print("Scanning supply chain news...")
    for query in SC_QUERIES:
        for item in search_google_news_rss(query, max_results=3):
            if item["title"] not in seen:
                seen.add(item["title"])
                item["lang"] = "EN"
                item["category"] = "supply_chain"
                all_headlines.append(item)

    print("Scanning earnings news...")
    for ticker, name_cn, name_en in COMPANIES:
        for query in [f"{name_cn} 法說會", f"{name_cn} 營收 {date.today().year}"]:
            for item in search_google_news_rss(query, max_results=2, lang="zh"):
                t = item["title"]
                if any(kw in t for kw in ["法說","營收","獲利","EPS","季報"]):
                    if item["title"] not in seen:
                        seen.add(item["title"])
                        item["lang"] = "ZH"
                        item["category"] = "earnings"
                        all_headlines.append(item)

    # Build digest strings
    lines = [f"Sector News - CPO & Silicon Photonics ({today})"]
    for h in en_news[:8]:
        lines.append(f"- {h['title']} | {h['source']}")
    for h in zh_news[:8]:
        lines.append(f"- {h['title']} | {h['source']}")
    sector_news = "\n".join(lines)
    earnings_str = "See news feed for earnings updates."
    supply_str   = "See news feed for supply chain updates."

    push_to_notion(sector_news, earnings_str, supply_str)

    # Write to Supabase
    from supabase_writer import write_news, log_pipeline

    news_rows = []
    for item in all_headlines:
        news_rows.append({
            "title":        item.get("title", "")[:500],
            "source":       item.get("source", ""),
            "lang":         item.get("lang", "EN"),
            "category":     item.get("category", "sector"),
            "published_at": item.get("date", today),
            "link":         item.get("link", ""),
        })

    write_news(news_rows)
    log_pipeline("Daily News", "success", f"{len(news_rows)} items")

    print(f"\nTotal: {len(news_rows)} news items written to Supabase")
    print("Done.")
