#!/usr/bin/env python3
"""Create Realtime_Watchlist sheet, reorder next to All Tickers."""
import gspread, json, time
from pathlib import Path
from google.oauth2.credentials import Credentials

NEW_SHEET = '1vOMj5p-X1GAZEAd4Hp_RoSgYtauBiCKF9RW7GRHVxHM'

# Auth
token_data = json.loads(open(Path.home() / '.hermes' / 'google_token.json').read())
creds = Credentials(
    token=token_data['token'],
    refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
    client_id=token_data['client_id'],
    client_secret=token_data['client_secret'],
    scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'],
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(NEW_SHEET)

worksheets = sh.worksheets()
print("=== Current sheet order ===")
for i, ws in enumerate(worksheets):
    print(f"  {i}: {ws.title} [{ws.id}]")

all_idx = next(i for i, ws in enumerate(worksheets) if ws.title == 'All Tickers')
print(f"\nAll Tickers index: {all_idx}")

# Check Realtime_Watchlist
rw = None
for ws in worksheets:
    if ws.title == 'Realtime_Watchlist':
        rw = ws
        break

if rw:
    print(f"Realtime_Watchlist exists [id={rw.id}]")
    ci = next(i for i, ws in enumerate(worksheets) if ws.title == 'Realtime_Watchlist')
    print(f"  at index {ci}, target {all_idx+1}")
    if ci != all_idx + 1:
        body = {"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": rw.id, "index": all_idx + 1},
            "fields": "index"
        }}]}
        sh.batch_update(body)
        print("  Reordered")
else:
    print("Realtime_Watchlist: creating...")
    HEADER = ["Ticker","Last Price","Change %","High","Low","Open","Volume",
              "Total Bid Lot","Total Ask Lot","Imbalance Ratio","Support",
              "Resistance","Source","Last Update (UTC)"]
    rw = sh.add_worksheet(title='Realtime_Watchlist', rows=100, cols=len(HEADER))
    rw.append_row(HEADER)
    time.sleep(2)
    body = {"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": rw.id, "index": 1},
        "fields": "index"
    }}]}
    sh.batch_update(body)
    print("  Created and moved to index 1")

# Also reposition Alpha_Watchlist and Dashboard [stockbit]
# Put them after Realtime_Watchlist
for name, target_idx in [('Alpha_Watchlist', 2), ('Dashboard [stockbit]', 3)]:
    try:
        ws = sh.worksheet(name)
        ci = next(i for i, w in enumerate(sh.worksheets()) if w.title == name)
        if ci != target_idx:
            body = {"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "index": target_idx},
                "fields": "index"
            }}]}
            sh.batch_update(body)
            print(f"{name}: moved to index {target_idx}")
        else:
            print(f"{name}: already at index {target_idx}")
    except:
        print(f"{name}: not found")

# Final order
print("\n=== Final sheet order ===")
for i, ws in enumerate(sh.worksheets()):
    print(f"  {i}: {ws.title}")
