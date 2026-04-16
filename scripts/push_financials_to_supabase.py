"""
push_financials_to_supabase.py
Parses .md files with aligned markdown tables and pushes to Supabase.
Writes valuation metrics to stock_data and full financials to company_financials.
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
    Returns (col_headers, data_rows) where data_rows is list of dicts.
    Handles aligned tables with extra spaces.
    """
    pattern = rf"###\s*{re.escape(section_header)}[^\n]*\n"
    match = re.search(pattern, content)
    if not match:
        return [], []

    section_start = match.end()
    remaining = content[section_start:]
    lines = []
    for line in remaining.split("\n"):
        if line.startswith("##"):
            break
        lines.append(line)

    table_lines = [l for l in lines if l.strip().startswith("|")]
    if len(table_lines) < 3:
        return [], []

    header_cells = [c.strip() for c in table_lines[0].split("|") if c.strip()]

    data_rows = []
    for line in table_lines[2:]:
        cells = [c.strip() for c in line.split("|")]
        cells = [c for i, c in enumerate(cells) if not (i == 0 and c == "")]
        if len(cells) < 2:
            continue
        row = {}
        for i, col in enumerate(header_cells):
            if i < len(cells):
                row[col] = cells[i]
        data_rows.append(row)

    return header_cells, data_rows

def get_single(rows, label):
    """Get first numeric value from a row matching label."""
    for row in rows:
        vals = list(row.values())
        if len(vals) >= 2 and label.lower() in vals[0].lower():
            return clean_num(vals[1])
    return None

def get_val(rows, label):
    """Get all numeric values from a row matching label."""
    for row in rows:
        vals = list(row.values())
        if vals and label.lower() in vals[0].lower():
            return [clean_num(v) for v in vals[1:]]
    return []

def parse_md_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    ticker = Path(filepath).stem.split("_")[0]

    # ── Valuation ──────────────────────────────────────────
    _, val_rows = parse_section(content, "Valuation Metrics")
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

    annual = {
        "years":        years,
        "revenue":      get_val(ann_rows, "Revenue"),
        "gross_profit": get_val(ann_rows, "Gross Profit"),
        "op_income":    get_val(ann_rows, "Operating Income"),
        "net_income":   get_val(ann_rows, "Net Income"),
        "gross_margin": get_val(ann_rows, "Gross Margin"),
        "op_margin":    get_val(ann_rows, "Operating Margin"),
        "net_margin":   get_val(ann_rows, "Net Margin"),
    }

    # ── Quarterly Financials ───────────────────────────────
    q_start = content.find("### Quarterly Financials")
    q_content = content[q_start:] if q_start >= 0 else content
    q_cols, q_rows = parse_section(q_content, "Quarterly Financials")
    quarters = [c for c in q_cols[1:] if c] if len(q_cols) > 1 else []

    quarterly = {
        "quarters":     quarters,
        "revenue":      get_val(q_rows, "Revenue"),
        "gross_profit": get_val(q_rows, "Gross Profit"),
        "op_income":    get_val(q_rows, "Operating Income"),
        "net_income":   get_val(q_rows, "Net Income"),
        "gross_margin": get_val(q_rows, "Gross Margin"),
        "op_margin":    get_val(q_rows, "Operating Margin"),
        "net_margin":   get_val(q_rows, "Net Margin"),
    }

    # Latest year summary for stock_data quick access
    summary = {
        **valuation,
        "gross_margin": annual["gross_margin"][0] if annual["gross_margin"] else None,
        "op_margin":    annual["op_margin"][0]    if annual["op_margin"]    else None,
        "net_margin":   annual["net_margin"][0]   if annual["net_margin"]   else None,
        "revenue":      annual["revenue"][0]      if annual["revenue"]      else None,
    }

    return {
        "ticker":    ticker,
        "valuation": valuation,
        "annual":    annual,
        "quarterly": quarterly,
        "summary":   summary,
    }

def update_stock_data(ticker, summary):
    """Update stock_data with valuation + latest margin summary."""
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
    print(f"  {ticker}: stock_data -> {r.status_code} ({len(clean)} fields)")

def upsert_financials(ticker, annual, quarterly):
    """Write full annual + quarterly data to company_financials table."""
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
    print(f"  {ticker}: financials -> {r.status_code} ({len(rows)} rows)")

def push_company_profile(ticker, filepath):
    """Parse business description and supply chain from .md file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    def extract_bullets(section_text):
        items = []
        for line in section_text.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                items.append(line[2:].strip())
        return items[:10]

    # Business description
    overview_match = re.search(
        r"## Business Overview[^\n]*\n(.*?)(?=\n##)",
        content, re.DOTALL
    )
    en_desc, zh_desc = "", ""
    if overview_match:
        paras = [l.strip() for l in overview_match.group(1).split("\n")
                 if l.strip() and not l.startswith("**")]
        en_desc = paras[0] if paras else ""
        zh_desc = paras[1] if len(paras) > 1 else ""

    # Supply chain
    sc_match = re.search(
        r"## Supply Chain Position[^\n]*\n(.*?)(?=\n##)",
        content, re.DOTALL
    )
    upstream, downstream, role = [], [], ""
    if sc_match:
        sc = sc_match.group(1)
        up = re.search(r"\*\*Upstream[^*]*\*\*[^\n]*\n(.*?)(?=\*\*Mid|\*\*Down|\Z)", sc, re.DOTALL)
        dn = re.search(r"\*\*Downstream[^*]*\*\*[^\n]*\n(.*?)(?=\n\n|##|\Z)", sc, re.DOTALL)
        rl = re.search(r"\*\*Midstream[^*]*\*\*[^\n]*\n-[^*]*\*\*[^—]*—\s*([^\n]+)", sc)
        upstream   = extract_bullets(up.group(1)) if up else []
        downstream = extract_bullets(dn.group(1)) if dn else []
        role       = rl.group(1).strip()          if rl else ""

    # Key customers
    cust_match = re.search(
        r"### Key Customers[^\n]*\n(.*?)(?=###|##|\Z)",
        content, re.DOTALL
    )
    key_customers = extract_bullets(cust_match.group(1)) if cust_match else []

    # Key suppliers
    supp_match = re.search(
        r"### Key Suppliers[^\n]*\n(.*?)(?=###|##|\Z)",
        content, re.DOTALL
    )
    key_suppliers = extract_bullets(supp_match.group(1)) if supp_match else []

    # Investment themes
    theme_match = re.search(
        r"### Key Investment Themes[^\n]*\n(.*?)(?=###|##|\Z)",
        content, re.DOTALL
    )
    investment_themes = extract_bullets(theme_match.group(1)) if theme_match else []

    profile = {
        "business_desc":     en_desc[:1000]   if en_desc            else None,
        "business_desc_zh":  zh_desc[:1000]   if zh_desc            else None,
        "upstream":          upstream          if upstream           else None,
        "downstream":        downstream        if downstream         else None,
        "midstream_role":    role[:200]        if role               else None,
        "key_customers":     key_customers     if key_customers      else None,
        "key_suppliers":     key_suppliers     if key_suppliers      else None,
        "investment_themes": investment_themes if investment_themes  else None,
    }

    clean = {k: v for k, v in profile.items() if v is not None}
    if not clean:
        print(f"  {ticker}: no profile data found")
        return

    url = f"{SUPABASE_URL}/rest/v1/stock_data?ticker=eq.{ticker}"
    r = requests.patch(
        url,
        headers={**headers(), "Prefer": "return=minimal"},
        json=clean
    )
    print(f"  {ticker}: profile -> {r.status_code} ({len(clean)} fields)")


if __name__ == "__main__":
    print("\n=== Push Financials to Supabase ===\n")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_ANON_KEY")
        exit(1)

    md_files = list(Path(".").glob("*.md"))
    if not md_files:
        sub = Path("Pilot_Reports/Optical_Communications")
        if sub.exists():
            md_files = list(sub.glob("*.md"))

    print(f"Found {len(md_files)} .md files\n")
    if not md_files:
        print("ERROR: No .md files found")
        exit(1)

    success = 0
    for filepath in sorted(md_files):
        try:
            data = parse_md_file(filepath)
            ticker = data["ticker"]
            print(f"\n{ticker} ({filepath.name})")
            print(f"  Years: {data['annual']['years']}")
            print(f"  Quarters: {data['quarterly']['quarters']}")
            print(f"  Revenue: {data['annual']['revenue']}")
            print(f"  Gross margin: {data['annual']['gross_margin']}")
            update_stock_data(ticker, data["summary"])
            upsert_financials(ticker, data["annual"], data["quarterly"])
            push_company_profile(ticker, filepath)
            success += 1
        except Exception as e:
            import traceback
            print(f"  ERROR: {e}")
            traceback.print_exc()

    print(f"\nDone. Updated {success}/{len(md_files)} companies.")
