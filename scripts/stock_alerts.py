"""
stock_alerts.py — FREE VERSION (no Anthropic API needed)
Uses yfinance only. Computes TA signals and sends alerts.
Runs daily via GitHub Actions.
"""

import yfinance as yf
import pandas as pd
import requests
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

today = date.today().strftime("%Y-%m-%d")

COMPANIES = [
    ("3081", "3081.TWO", "聯亞",    "LiquidCool",        "Upstream — InP epitaxy"),
    ("2455", "2455.TW",  "全新",    "Global Comm Semi",  "Upstream — GaAs/InP epitaxy"),
    ("4971", "4971.TWO", "IET-KY",  "Innovative Epi",   "Upstream — epi test"),
    ("6451", "6451.TW",  "訊芯-KY", "Applied Opto TW",  "Upstream — laser diode"),
    ("3105", "3105.TWO", "穩懋",    "WIN Semi",          "Upstream — GaAs foundry"),
    ("3363", "3363.TWO", "上詮",    "SENKO Advanced",   "Midstream — FAU/CPO"),
    ("3163", "3163.TWO", "波若威",  "ProLight Opto",    "Midstream — fiber passive"),
    ("4979", "4979.TWO", "華星光",  "HiLight Semi",     "Midstream — CW laser"),
    ("6442", "6442.TW",  "光聖",    "Radiant Opto",     "Midstream — AOC modules"),
    ("4977", "4977.TWO", "眾達-KY", "Luxshare Optical", "Midstream — transceivers"),
    ("6530", "6530.TWO", "創威",    "Coretek",          "Midstream — OSA"),
    ("4903", "4903.TWO", "聯光通",  "Lanto Comm",       "Midstream — fiber cable"),
    ("3450", "3450.TW",  "聯鈞",    "Luxtera TW",       "Midstream — packaging"),
    ("6515", "6515.TW",  "穎崴",    "Ying Wei Tech",    "Test — interfaces"),
    ("6223", "6223.TWO", "旺矽",    "MPI Corporation",  "Test — SiPh probe"),
    ("6510", "6510.TWO", "精測",    "Chroma ATE",       "Test — IC/GPU boards"),
    ("2345", "2345.TW",  "智邦",    "Accton Technology","Downstream — AI switch"),
    ("6426", "6426.TW",  "統新",    "Apogee Optocom",   "Downstream — networking"),
    ("2330", "2330.TW",  "台積電",  "TSMC",             "Platform — COUPE"),
]

# ── TA signal descriptions (plain English, no LLM needed) ─
SIGNAL_INTERPRETATIONS = {
    "GOLDEN CROSS":   "MA20 crossed above MA50 — potential uptrend starting",
    "DEATH CROSS":    "MA20 crossed below MA50 — potential downtrend starting",
    "RSI OVERBOUGHT": "RSI above 70 — stock may be overextended, watch for pullback",
    "RSI OVERSOLD":   "RSI below 30 — stock may be undervalued, watch for bounce",
    "VOLUME SPIKE":   "Unusual volume — likely news-driven, check for announcements",
    "52W HIGH":       "Near 52-week high — strong momentum, monitor for breakout",
    "52W LOW":        "Near 52-week low — significant weakness, review fundamentals",
}

# ── RSI calculation ────────────────────────────────────────
def compute_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))

# ── Analyze one ticker ─────────────────────────────────────
def analyze(ticker_tw, ticker_yf, name_cn, name_en, role):
    try:
        df = yf.download(ticker_yf, period="3mo", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 25:
            return None

        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze()

        ma20 = close.rolling(20).mean()
        ma50 = close.rolling(min(50, len(close))).mean()
        rsi  = compute_rsi(close)

        c     = float(close.iloc[-1])
        m20   = float(ma20.iloc[-1])
        m50   = float(ma50.iloc[-1])
        r     = float(rsi.iloc[-1])
        pm20  = float(ma20.iloc[-2])
        pm50  = float(ma50.iloc[-2])
        vol   = float(volume.iloc[-1])
        avol  = float(volume.rolling(20).mean().iloc[-1])
        h52   = float(close.rolling(min(252, len(close))).max().iloc[-1])
        l52   = float(close.rolling(min(252, len(close))).min().iloc[-1])

        # Compute price change
        pct_1d = (c - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        pct_1w = (c - float(close.iloc[-6])) / float(close.iloc[-6]) * 100 if len(close) > 6 else 0

        signals = []
        if pm20 < pm50 and m20 >= m50:
            signals.append("GOLDEN CROSS")
        elif pm20 > pm50 and m20 <= m50:
            signals.append("DEATH CROSS")
        if r > 72:
            signals.append("RSI OVERBOUGHT")
        elif r < 28:
            signals.append("RSI OVERSOLD")
        if avol > 0 and vol > 2.2 * avol:
            signals.append("VOLUME SPIKE")
        if c >= h52 * 0.97:
            signals.append("52W HIGH")
        elif c <= l52 * 1.03:
            signals.append("52W LOW")

        return {
            "ticker": ticker_tw, "name_cn": name_cn, "name_en": name_en,
            "role": role, "price": c, "rsi": r,
            "ma20": m20, "ma50": m50,
            "pct_1d": pct_1d, "pct_1w": pct_1w,
            "vol_ratio": vol / avol if avol > 0 else 0,
            "signals": signals,
        }
    except Exception as e:
        print(f"  Error {ticker_tw}: {e}")
        return None

# ── Format alert report ────────────────────────────────────
def format_report(results, alerts):
    lines = [f"Taiwan Optical Comms Portfolio — Daily Report {today}",
             "=" * 55, ""]

    # Portfolio snapshot
    lines.append("PORTFOLIO SNAPSHOT (19 companies)")
    lines.append("-" * 40)
    lines.append(f"{'Ticker':<8} {'Name':<14} {'Price':>8} {'1D%':>6} {'1W%':>6} {'RSI':>5}")
    lines.append("-" * 55)
    for r in sorted(results, key=lambda x: x["pct_1d"], reverse=True):
        arrow = "▲" if r["pct_1d"] > 0 else "▼" if r["pct_1d"] < 0 else "—"
        lines.append(
            f"{r['ticker']:<8} {r['name_cn']:<6}{r['name_en'][:7]:<8} "
            f"NT${r['price']:>6.0f} {arrow}{abs(r['pct_1d']):>4.1f}% "
            f"{r['pct_1w']:>+5.1f}% {r['rsi']:>5.0f}"
        )

    lines.append("")
    lines.append(f"TECHNICAL ALERTS ({len(alerts)} triggered)")
    lines.append("-" * 40)

    if not alerts:
        lines.append("No significant signals today. Portfolio stable.")
    else:
        for a in sorted(alerts, key=lambda x: len(x["signals"]), reverse=True):
            lines.append(f"\n{'⚠' * len(a['signals'])} {a['ticker']} {a['name_en']} ({a['name_cn']})")
            lines.append(f"   Role: {a['role']}")
            lines.append(f"   Price: NT${a['price']:.0f} | RSI: {a['rsi']:.0f} | "
                         f"Vol: {a['vol_ratio']:.1f}x avg")
            for sig in a["signals"]:
                interp = SIGNAL_INTERPRETATIONS.get(sig.split(" —")[0], "")
                lines.append(f"   → {sig}: {interp}")

    lines.append("")
    lines.append("Top movers today:")
    top3_up   = sorted(results, key=lambda x: x["pct_1d"], reverse=True)[:3]
    top3_down = sorted(results, key=lambda x: x["pct_1d"])[:3]
    lines.append("  Gainers:  " + " | ".join(
        f"{r['name_cn']} +{r['pct_1d']:.1f}%" for r in top3_up if r["pct_1d"] > 0))
    lines.append("  Decliners:" + " | ".join(
        f"{r['name_cn']} {r['pct_1d']:.1f}%" for r in top3_down if r["pct_1d"] < 0))

    return "\n".join(lines)

# ── Send email ─────────────────────────────────────────────
def send_email(subject, body):
    email    = os.environ.get("ALERT_EMAIL")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not email or not password:
        print("Email not configured — skipping")
        return
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = email
    msg["To"]      = email
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(email, password)
            s.sendmail(email, email, msg.as_string())
        print(f"Email sent to {email}")
    except Exception as e:
        print(f"Email error: {e}")

# ── Push to Notion ─────────────────────────────────────────
def push_to_notion(report, alert_count):
    notion_key = os.environ.get("NOTION_API_KEY")
    page_id    = os.environ.get("NOTION_PAGE_ID")
    if not notion_key or not page_id:
        return

    headers = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    emoji = "🔴" if alert_count >= 3 else "🟡" if alert_count >= 1 else "🟢"
    blocks = [
        {"object": "block", "type": "heading_2", "heading_2": {
            "rich_text": [{"type": "text", "text": {
                "content": f"{emoji} Stock Alerts — {today} ({alert_count} signals)"}}]}},
        {"object": "block", "type": "code", "code": {
            "language": "plain text",
            "rich_text": [{"type": "text", "text": {"content": report}}]}},
        {"object": "block", "type": "divider", "divider": {}},
    ]
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    r = requests.patch(url, headers=headers, json={"children": blocks})
    print(f"Notion updated: {r.status_code}")

# ── Main ───────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n=== Stock Alert Scanner (Free) — {today} ===\n")

    results, alerts = [], []
    for ticker_tw, ticker_yf, name_cn, name_en, role in COMPANIES:
        print(f"  {ticker_tw} {name_cn}...", end=" ")
        r = analyze(ticker_tw, ticker_yf, name_cn, name_en, role)
        if r:
            results.append(r)
            if r["signals"]:
                alerts.append(r)
                print(f"⚠ {r['signals']}")
            else:
                print("ok")
        else:
            print("no data")

    report = format_report(results, alerts)
    print("\n" + report)

    push_to_notion(report, len(alerts))

    if alerts:
        subject = f"[CPO Portfolio] {len(alerts)} alert(s) — {today}"
        send_email(subject, report)

# Add this import at the top of stock_alerts.py:
# from supabase_writer import write_stocks, log_pipeline

# Add this block right before print("\nDone.") at the bottom:

    # Write all stock data to Supabase
    stock_rows = []
    for r in results:
        stock_rows.append({
            "ticker":     r["ticker"],
            "name_cn":    r["name_cn"],
            "name_en":    r["name_en"],
            "tier":       r["role"].split("—")[0].strip() if "—" in r["role"] else r["role"],
            "price":      round(r["price"], 2) if r["price"] else None,
            "change_1d":  round(r["pct_1d"], 2) if r.get("pct_1d") else None,
            "change_1w":  round(r["pct_1w"], 2) if r.get("pct_1w") else None,
            "rsi":        round(r["rsi"], 1) if r.get("rsi") else None,
            "ma20":       round(r["ma20"], 2) if r.get("ma20") else None,
            "ma50":       round(r["ma50"], 2) if r.get("ma50") else None,
            "vol_ratio":  round(r["vol_ratio"], 2) if r.get("vol_ratio") else None,
            "signals":    r["signals"],
            "updated_at": date.today().isoformat(),
        })

    from supabase_writer import write_stocks, log_pipeline
    write_stocks(stock_rows)
    log_pipeline("Stock Alerts", "success", f"{len(alerts)} alerts triggered")
    
    print("\nDone.")
