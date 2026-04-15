"""
supabase_writer.py
Shared helper used by daily_news.py, stock_alerts.py,
and push_financials_to_supabase.py to write data to Supabase.
"""

import requests
import os
from datetime import date

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

def _headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

def write_news(items):
    """Delete today's news and insert fresh batch."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase not configured — skipping write_news")
        return
    today = date.today().isoformat()
    # Delete today's existing news
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/news_items?created_at=gte.{today}T00:00:00",
        headers=_headers()
    )
    if not items:
        print("No news items to write")
        return
    url = f"{SUPABASE_URL}/rest/v1/news_items"
    r = requests.post(url, headers=_headers(), json=items)
    print(f"News written to Supabase: {r.status_code} ({len(items)} items)")
    return r.status_code

def write_stocks(stocks):
    """Delete all existing stock rows and insert fresh."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Supabase not configured — skipping write_stocks")
        return
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/stock_data?id=gte.0",
        headers=_headers()
    )
    if not stocks:
        print("No stock data to write")
        return
    url = f"{SUPABASE_URL}/rest/v1/stock_data"
    r = requests.post(url, headers=_headers(), json=stocks)
    print(f"Stocks written to Supabase: {r.status_code} ({len(stocks)} rows)")
    return r.status_code

def log_pipeline(step, status, message=""):
    """Log a pipeline run step to Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"Pipeline log (local): {step} — {status} — {message}")
        return
    url = f"{SUPABASE_URL}/rest/v1/pipeline_runs"
    r = requests.post(url, headers=_headers(), json=[{
        "run_date": date.today().isoformat(),
        "step":     step,
        "status":   status,
        "message":  message,
    }])
    print(f"Pipeline logged: {step} — {status} ({r.status_code})")
