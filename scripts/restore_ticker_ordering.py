#!/usr/bin/env python3
"""Restore all IDX tickers to staging Realtime_Watchlist after sync overwrite.

Strategy: read existing (may be empty/just header), ensure header, preserve
any data rows, then append all missing tickers from All Tickers for ordering."""

import json, sys
from pathlib import Path
import gspread
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
token_path = Path.home() / ".hermes" / "google_token.json"
with open(token_path) as f:
    td = json.load(f)
creds = Credentials(token=td["token"], refresh_token=td.get("refresh_token"),
    token_uri=td.get("token_uri", "https://oauth2.googleapis.com/token"),
    client_id=td["client_id"], client_secret=td["client_secret"], scopes=SCOPES)
gc = gspread.authorize(creds)

MAS_SID = "1WOPSU6JLoinVUexwJzbB-vpQS-4hoDp8TskP3GcKYaE"
sh = gc.open_by_key(MAS_SID)

# Hardcoded header (20 cols)
HEADER = ["No", "Ticker", "Last Price", "Change %", "Open", "High", "Low",
          "Volume", "Total Bid Lot", "Total Ask Lot", "Imbalance Ratio",
          "Foreign Net", "ARA", "ARB", "Support", "Resistance",
          "ARA Distance %", "ARB Distance %", "Source", "Last Update"]
NCOLS = len(HEADER)

# Read All Tickers
at = sh.worksheet("All Tickers")
all_raw = at.col_values(2)
all_tickers = [t.replace("IDX:", "").strip() for t in all_raw[1:] if t.strip()]
print(f"All Tickers: {len(all_tickers)} unique")

# Read current Realtime_Watchlist
ws = sh.worksheet("Realtime_Watchlist")
current = ws.get_all_values()
print(f"Current: {len(current)} rows")

# Collect data rows (rows after header that have ticker + price)
data_rows = []
data_tickers = set()
start_row = 1  # 0-indexed, skip header
while start_row < len(current):
    row = current[start_row]
    if row and len(row) > 2 and row[1].strip() and row[2].strip():
        t = row[1].strip().upper()
        data_tickers.add(t)
        data_rows.append(row)
    start_row += 1

print(f"Data rows found: {len(data_rows)} ({len(data_tickers)} unique tickers)")

# Build output rows
output = [HEADER]
for row in data_rows:
    # Ensure row has NCOLS columns
    while len(row) < NCOLS:
        row.append("")
    output.append(row)

# Append remaining tickers (not in data) as blank ordering rows
ordered = 0
for t in all_tickers:
    if t.upper() not in data_tickers:
        blank = [""] * NCOLS
        blank[0] = str(len(output))  # running number
        blank[1] = t
        output.append(blank)
        ordered += 1

print(f"Blank ordering rows: {ordered}")
print(f"Total output rows: {len(output)}")

# Resize sheet big enough
ws.resize(rows=len(output) + 50, cols=NCOLS + 5)

# Clear and rewrite
ws.clear()
# Small delay to let clear propagate
import time; time.sleep(1)

# Write everything
ws.update(range_name=f"A1:Z{len(output)}", values=output, value_input_option="USER_ENTERED")
ws.set_basic_filter(f"A1:Z{len(output)}")

print(f"Done! {len(data_tickers)} live + {ordered} ordering = {len(output)} total rows")
