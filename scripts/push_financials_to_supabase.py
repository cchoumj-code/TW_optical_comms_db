"""
push_financials_to_supabase.py
Reads financial data from the 19 .md files in 
Pilot_Reports/Optical_Communications/ and pushes
the valuation metrics to Supabase stock_data table.
Run once manually or add to GitHub Actions.
"""

import os
import re
import requests
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

def headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

def parse_float(text, label):
    """Extract a numeric value after a label in markdown table."""
    pattern = rf"\|\s*{re.escape(label)}[^|]*\|\s*([\d.,]+|N/A)\s*\|"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        val = match.group(1).replace(",", "").strip()
        if val == "N/A" or val == "":
            return None
        try:
            return float(val)
        except:
            return None
    return None

def parse_md_file(filepath):
    """Parse a company .md file and extract financial metrics."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract ticker from filename e.g. 3081_LiquidCool_聯亞.md
    filename = Path(filepath).stem
    ticker = filename.split("_")[0]

    metrics = {
        "ticker": ticker,
        "pe_ttm":            parse_float(content, "P/E Ratio (TTM) 本益比"),
        "pe_forward":        parse_float(content, "Forward P/E 預估本益比"),
        "ps_ttm":            parse_float(content, "Price-to-Sales (TTM) 股價營收比"),
        "pb":                parse_float(content, "Price-to-Book 股價淨值比"),
        "ev_ebitda":         parse_float(content, "EV/EBITDA 企業價值倍數"),
    }

    # Extract market cap and enterprise value from header
    mc_match = re.search(r"Market Cap 市值:\*\*\s*([\d,]+)", content)
    ev_match = re.search(r"Enterprise Value 企業價值:\*\*\s*([\d,]+)", content)
    if mc_match:
        metrics["market_cap"] = float(mc_match.group(1).replace(",", ""))
    if ev_match:
        metrics["enterprise_value"] = float(ev_match.group(1).replace(",", ""))

    # Extract margins from annual financial table
    metrics["gross_margin"] = parse_float(content, "Gross Margin 毛利率")
    metrics["op_margin"]    = parse_float(content, "Operating Margin 營益率")
    metrics["net_margin"]   = parse_float(content, "Net Margin 淨利率")

    # Extract revenue (most recent year, in millions TWD)
    rev_match = re.search(
        r"Revenue 營收[^|]*\|\s*([\d,]+)\s*\|", content
    )
    if rev_match:
        metrics["revenue"] = float(rev_match.group(1).replace(",", ""))

    return metrics

def update_supabase(metrics):
    """Update stock_data row for this ticker with financial metrics."""
    ticker = metrics.pop("ticker")

    # Remove None values to avoid overwriting good data with null
    clean = {k: v for k, v in metrics.items() if v is not None}

    if not clean:
        print(f"  {ticker}: no metrics found — skipping")
        return

    url = f"{SUPABASE_URL}/rest/v1/stock_data?ticker=eq.{ticker}"
    r = requests.patch(
        url,
        headers={**headers(), "Prefer": "return=minimal"},
        json=clean
    )
    print(f"  {ticker}: updated {len(clean)} metrics → {r.status_code}")

if __name__ == "__main__":
    print("\n=== Push Financials to Supabase ===\n")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set")
        print("Set them as environment variables and run again")
        exit(1)

    # Find all .md files
    reports_dir = Path("Pilot_Reports/Optical_Communications")
    if not reports_dir.exists():
        print(f"ERROR: {reports_dir} not found")
        print("Run this script from the root of your GitHub repo")
        exit(1)

    md_files = list(reports_dir.glob("*.md"))
    print(f"Found {len(md_files)} .md files\n")

    success = 0
    for filepath in sorted(md_files):
        try:
            metrics = parse_md_file(filepath)
            update_supabase(metrics)
            success += 1
        except Exception as e:
            print(f"  {filepath.name}: ERROR — {e}")

    print(f"\nDone. Updated {success}/{len(md_files)} companies.")
