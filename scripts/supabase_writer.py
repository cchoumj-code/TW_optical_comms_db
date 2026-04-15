"""
push_financials_to_supabase.py
Reads financial data from .md files and pushes to Supabase.
Parses both valuation metrics AND financial statements.
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

def clean_num(val):
    """Convert string like '59.9%' or '3,809,054' to float."""
    if not val or val.strip() in ("N/A", "—", "-", ""):
        return None
    val = val.strip().replace(",", "").replace("%", "")
    try:
        return float(val)
    except:
        return None

def parse_table_row(content, row_label):
    """
    Extract all numeric values from a markdown table row.
    Returns list of floats for each column found.
    e.g. "Gross Margin 毛利率 | 59.9% | 56.1% | 54.4%"
    returns [59.9, 56.1, 54.4]
    """
    pattern = rf"\|\s*{re.escape(row_label)}[^|]*\|([^|\n]+(?:\|[^|\n]+)*)\|?"
    match = re.search(pattern, content)
    if not match:
        return []
    cells = match.group(1).split("|")
    return [clean_num(c) for c in cells if c.strip()]

def parse_valuation(content):
    """Parse valuation metrics table."""
    def get_val(label):
        vals = parse_table_row(content, label)
        return vals[0] if vals else None

    return {
        "pe_ttm":     get_val("P/E Ratio (TTM)"),
        "pe_forward": get_val("Forward P/E"),
        "ps_ttm":     get_val("Price-to-Sales (TTM)"),
        "pb":         get_val("Price-to-Book"),
        "ev_ebitda":  get_val("EV/EBITDA"),
    }

def parse_annual(content):
    """Parse annual financials — returns dict with lists of 3 years."""
    # Find year headers
    year_match = re.search(
        r"Annual Financials[^\n]*\n[^\n]*\n[^\n]*\|\s*(\d{4})\s*\|\s*(\d{4})\s*\|\s*(\d{4})",
        content
    )
    years = []
    if year_match:
        years = [year_match.group(1), year_match.group(2), year_match.group(3)]
    else:
        years = ["Y1", "Y2", "Y3"]

    return {
        "years":          years,
        "revenue":        parse_table_row(content, "Revenue 營收 (TWD M)"),
        "gross_profit":   parse_table_row(content, "Gross Profit 毛利 (TWD M)"),
        "op_income":      parse_table_row(content, "Operating Income 營業利益 (TWD M)"),
        "net_income":     parse_table_row(content, "Net Income 淨利 (TWD M)"),
        "gross_margin":   parse_table_row(content, "Gross Margin 毛利率"),
        "op_margin":      parse_table_row(content, "Operating Margin 營益率"),
        "net_margin":     parse_table_row(content, "Net Margin 淨利率"),
    }

def parse_quarterly(content):
    """Parse quarterly financials — returns dict with lists of 4 quarters."""
    # Find quarter headers like 2025-12
    q_match = re.search(
        r"Quarterly Financials[^\n]*\n[^\n]*\n[^\n]*\|\s*(\d{4}-\d{2})\s*\|\s*(\d{4}-\d{2})\s*\|\s*(\d{4}-\d{2})\s*\|\s*(\d{4}-\d{2})",
        content
    )
    quarters = []
    if q_match:
        quarters = [q_match.group(i) for i in range(1, 5)]
    else:
        quarters = ["Q1", "Q2", "Q3", "Q4"]

    # Find quarterly section only (after "Quarterly Financials")
    q_section = content
    q_start = content.find("Quarterly Financials")
    if q_start > 0:
        q_section = content[q_start:]

    return {
        "quarters":     quarters,
        "revenue":      parse_table_row(q_section, "Revenue 營收 (TWD M)"),
        "gross_profit": parse_table_row(q_section, "Gross Profit 毛利 (TWD M)"),
        "op_income":    parse_table_row(q_section, "Operating Income 營業利益 (TWD M)"),
        "net_income":   parse_table_row(q_section, "Net Income 淨利 (TWD M)"),
        "gross_margin": parse_table_row(q_section, "Gross Margin 毛利率"),
        "op_margin":    parse_table_row(q_section, "Operating Margin 營益率"),
        "net_margin":   parse_table_row(q_section, "Net Margin 淨利率"),
    }

def parse_md_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    ticker = Path(filepath).stem.split("_")[0]

    val     = parse_valuation(content)
    annual  = parse_annual(content)
    quarterly = parse_quarterly(content)

    # Most recent year margins for stock_data quick access
    gm = annual["gross_margin"][0] if annual["gross_margin"] else None
    om = annual["op_margin"][0]    if annual["op_margin"]    else None
    nm = annual["net_margin"][0]   if annual["net_margin"]   else None
    rv = annual["revenue"][0]      if annual["revenue"]      else None

    return {
        "ticker":    ticker,
        "valuation": val,
        "annual":    annual,
        "quarterly": quarterly,
        "summary": {
            "gross_margin": gm,
            "op_margin":    om,
            "net_margin":   nm,
            "revenue":      rv,
            **val,
        }
    }

def update_stock_data(ticker, summary):
    """Update stock_data with valuation + latest margin summary."""
    clean = {k: v for k, v in summary.items() if v is not None}
    if not clean:
        print(f"  {ticker}: no summary metrics — skipping")
        return
    url = f"{SUPABASE_URL}/rest/v1/stock_data?ticker=eq.{ticker}"
    r = requests.patch(
        url,
        headers={**headers(), "Prefer": "return=minimal"},
        json=clean
    )
    print(f"  {ticker}: stock_data updated → {r.status_code}")

def upsert_financials(ticker, annual, quarterly):
    """Write full annual + quarterly data to company_financials table."""
    rows = []

    # Annual rows
    for i, year in enumerate(annual["years"]):
        row = {"ticker": ticker, "period": year, "period_type": "annual"}
        for metric in ["revenue","gross_profit","op_income","net_income",
                       "gross_margin","op_margin","net_margin"]:
            vals = annual.get(metric, [])
            row[metric] = vals[i] if i < len(vals) else None
        rows.append(row)

    # Quarterly rows
    for i, quarter in enumerate(quarterly["quarters"]):
        row = {"ticker": ticker, "period": quarter, "period_type": "quarterly"}
        for metric in ["revenue","gross_profit","op_income","net_income",
                       "gross_margin","op_margin","net_margin"]:
            vals = quarterly.get(metric, [])
            row[metric] = vals[i] if i < len(vals) else None
        rows.append(row)

    if not rows:
        return

    # Delete existing rows for this ticker then reinsert
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/company_financials?ticker=eq.{ticker}",
        headers=headers()
    )
    url = f"{SUPABASE_URL}/rest/v1/company_financials"
    r = requests.post(url, headers=headers(), json=rows)
    print(f"  {ticker}: financials upserted ({len(rows)} rows) → {r.status_code}")

if __name__ == "__main__":
    print("\n=== Push Financials to Supabase ===\n")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_ANON_KEY")
        exit(1)

    md_files = list(Path(".").glob("*.md"))
    if not md_files:
        md_files = list(Path("Pilot_Reports/Optical_Communications").glob("*.md"))

    print(f"Found {len(md_files)} .md files\n")

    for filepath in sorted(md_files):
        try:
            data = parse_md_file(filepath)
            ticker = data["ticker"]
            print(f"Processing {ticker}...")
            update_stock_data(ticker, data["summary"])
            upsert_financials(ticker, data["annual"], data["quarterly"])
        except Exception as e:
            print(f"  {filepath.name}: ERROR — {e}")

    print("\nDone.")
