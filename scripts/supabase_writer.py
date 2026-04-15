"""
supabase_writer.py
Shared helper used by both daily_news.py and stock_alerts.py
to write data to Supabase. No Anthropic API needed.
"""

import requests
import os
from datetime import date

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

def headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

def clear_today_news():
    """Delete today's news before inserting fresh batch."""
    today = date.today().isoformat()
    url = f"{SUPABASE_URL}/rest/v1/news_items?created_at=gte.{today}T00:00:00"
    requests.delete(url, headers=headers())

def write_news(items):
    """Write news items to Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase not configured — skipping write")
        return
    clear_today_news()
    url = f"{SUPABASE_URL}/rest/v1/news_items"
    r = requests.post(url, headers=headers(), json=items)
    print(f"News written to Supabase: {r.status_code} ({len(items)} items)")
    return r.status_code

def write_stocks(stocks):
    """Write stock data — delete all and reinsert fresh."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase not configured — skipping write")
        return
    # Delete all existing rows first
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/stock_data?id=gte.0",
        headers=headers()
    )
    url = f"{SUPABASE_URL}/rest/v1/stock_data"
    r = requests.post(url, headers=headers(), json=stocks)
    print(f"Stocks written to Supabase: {r.status_code} ({len(stocks)} rows)")
    return r.status_code

def log_pipeline(step, status, message=""):
    """Log pipeline run status."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"Pipeline log (local): {step} — {status} — {message}")
        return
    url = f"{SUPABASE_URL}/rest/v1/pipeline_runs"
    r = requests.post(url, headers=headers(), json=[{
        "run_date": date.today().isoformat(),
        "step":     step,
        "status":   status,
        "message":  message,
    }])
    print(f"Pipeline logged: {step} — {status} ({r.status_code})")
