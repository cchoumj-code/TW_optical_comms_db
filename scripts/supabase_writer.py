"""
push_financials_to_supabase.py
Parses .md files with aligned markdown tables and pushes to Supabase.
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
    """Convert '59.9%' or '3,809,054' or '1855' to float."""
    if not val:
        return None
    val = val.strip().replace(",", "").replace("%", "").replace(" ", "")
    if val in ("N/A", "—", "-", ""):
        return None
    try:
        return float(val)
    except:
        return None

def parse_section(content, section_header):
    """
    Extract a markdown table section by header name.
    Returns list of {col_header: value} dicts, one per data row.
    Handles aligned tables with extra spaces.
    """
    # Find the section
    pattern = rf"###\s*{re.escape(section_header)}[^\n]*\n"
    match = re.search(pattern, content)
    if not match:
        return [], []

    section_start = match.end()
    # Get lines until next ### or ##
    remaining = content[section_start:]
    lines = []
    for line in remaining.split("\n"):
        if line.startswith("##"):
            break
        lines.append(line)

    # Parse table
    table_lines = [l for l in lines if l.strip().startswith("|")]
    if len(table_lines) < 3:
        return [], []

    # Header row — extract column names
    header_cells = [c.strip() for c in table_lines[0].split("|") if c.strip()]
    # Skip separator row (table_lines[1])
    # Data rows
    data_rows = []
    for line in table_lines[2:]:
        cells = [c.strip() for c in line.split("|")]
        # Remove empty first/last from leading/trailing |
        cells = [c for i, c in enumerate(cells) if not (i == 0 and c == "")]
        if len(cells) < 2:
            continue
        row = {}
        for i, col in enumerate(header_cells):
            if i < len(cells):
                row[col] = cells[i]
        data_rows.append(row)

    return header_cells, data_rows

def get_val(rows, label_contains):
    """Find first row whose first column contains label, return all numeric values."""
    for row in rows:
        first_col = list(row.keys())[0] if row else ""
        first_val = list(row.values())[0] if row else ""
        if label_contains.lower() in first_val.lower():
            return [clean_num(v) for k, v in list(row.items())[1:]]
    return []

def parse_md_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    ticker = Path(filepath).stem.split("_")[0]

    # ── Valuation ──────────────────────────────────────────
    _, val_rows = parse_section(content, "Valuation Metrics")

    def get_single(rows, label):
        for row in rows:
            vals = list(row.values())
            if len(vals) >= 2 and label.lower() in vals[0].lower():
                return clean_num(vals[1])
        return None

    valuation = {
        "pe_ttm":     get_single(val_rows, "P/E Ratio (TTM)"),
        "pe_forward": get_single(val_rows, "Forward P/E"),
        "ps_ttm":     get_single(val_rows, "Price-to-Sales"),
        "pb":         get_single(val_rows, "Price-to-Book"),
        "ev_ebitda":  get_single(val_rows, "EV/EBITDA"),
    }

    # ── Annual Financials ──────────────────────────────────
    ann_cols, ann_rows = parse_section(content, "Annual Financials")
    years = [c for c in ann_cols[1:] if c] if len(ann_cols) > 1 else []

    def get_annual(label):
        return get_val(ann_rows, label)

    annual = {
        "years":        years,
        "revenue":      get_annual("Revenue"),
        "gross_profit": get_annual("Gross Profit"),
        "op_income":    get_annual("Operating Income"),
        "net_income":   get_annual("Net Income"),
        "gross_margin": get_annual("Gross Margin"),
        "op_margin":    get_annual("Operating Margin"),
        "net_margin":   get_annual("Net Margin"),
    }

    # ── Quarterly Financials ───────────────────────────────
    # Find quarterly section specifically
    q_start = content.find("### Quarterly Financials")
    q_content = content[q_start:] if q_start >= 0 else content

    q_cols, q_rows = parse_section(q_content, "Quarterly Financials")
    quarters = [c for c in q_cols[1:] if c] if len(q_cols) > 1 else []

    def get_quarterly(label):
        return get_val(q_rows, label)

    quarterly = {
        "quarters":     quarters,
        "revenue":      get_quarterly("Revenue"),
        "gross_profit": get_quarterly("Gross Profit"),
        "op_income":    get_quarterly("Operating Income"),
        "net_income":   get_quarterly("Net Income"),
        "gross_margin": get_quarterly("Gross Margin"),
        "op_margin":    get_quarterly("Operating Margin"),
        "net_margin":   get_quarterly("Net Margin"),
    }

    # Latest year summary for stock_data
    summary = {
        **valuation,
        "gross_margin": annual["gross_margin"][0] if annual["gross_margin"] else None,
        "op_margin":    annual["op_margin"][0]    if annual["op_margin"]    else None,
        "net_margin":   annual["net_margin"][0]   if annual["net_margin"]   else None,
        "revenue":      annual["revenue"][0]      if annual["revenue"]      else None,
    }

    return {
        "ticker":     ticker,
        "valuation":  valuation,
        "annual":     annual,
        "quarterly":  quarterly,
        "summary":    summary,
    }

def update_stock_data(ticker, summary):
    clean = {k: v for k, v in summary.items() if v is not None}
    if not clean:
        print(f"  {ticker}: no summary metrics")
        return
    url = f"{SUPABASE_URL}/rest/v1/stock_data?ticker=eq.{ticker}"
    r = requests.patch(
        url,
        headers={**headers(), "Prefer": "return=minimal"},
        json=clean
    )
    print(f"  {ticker}: stock_data → {r.status_code} ({len(clean)} fields)")

def upsert_financials(ticker, annual, quarterly):
    rows = []

    for i, year in enumerate(annual["years"]):
        row = {"ticker": ticker, "period": year, "period_type": "annual"}
        for m in ["revenue","gross_profit","op_income","net_income",
                  "gross_margin","op_margin","net_margin"]:
            vals = annual.get(m, [])
            row[m] = vals[i] if i < len(vals) else None
        rows.append(row)

    for i, quarter in enumerate(quarterly["quarters"]):
        row = {"ticker": ticker, "period": quarter, "period_type": "quarterly"}
        for m in ["revenue","gross_profit","op_income","net_income",
                  "gross_margin","op_margin","net_margin"]:
            vals = quarterly.get(m, [])
            row[m] = vals[i] if i < len(vals) else None
        rows.append(row)

    if not rows:
        print(f"  {ticker}: no financial rows to insert")
        return

    requests.delete(
        f"{SUPABASE_URL}/rest/v1/company_financials?ticker=eq.{ticker}",
        headers=headers()
    )
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/company_financials",
        headers=headers(),
        json=rows
    )
    print(f"  {ticker}: financials → {r.status_code} ({len(rows)} rows)")

if __name__ == "__main__":
    print("\n=== Push Financials to Supabase ===\n")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_ANON_KEY")
        exit(1)

    # Find .md files — check root first, then subfolder
    md_files = list(Path(".").glob("*.md"))
    if not md_files:
        sub = Path("Pilot_Reports/Optical_Communications")
        if sub.exists():
            md_files = list(sub.glob("*.md"))

    print(f"Found {len(md_files)} .md files\n")
    if not md_files:
        print("ERROR: No .md files found")
        exit(1)

    for filepath in sorted(md_files):
        try:
            data = parse_md_file(filepath)
            ticker = data["ticker"]
            print(f"\n{ticker} ({filepath.name})")
            update_stock_data(ticker, data["summary"])
            upsert_financials(ticker, data["annual"], data["quarterly"])
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}")
            traceback.print_exc()

    print("\n=== Done ===")
