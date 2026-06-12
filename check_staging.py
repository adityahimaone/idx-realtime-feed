#!/usr/bin/env python3
"""Check MAS staging sheet contents and both sheets' Realtime_Watchlist."""
import gspread, json
from pathlib import Path
from google.oauth2.credentials import Credentials

token_data = json.loads(open(Path.home() / '.hermes' / 'google_token.json').read())
creds = Credentials(token=token_data['token'], refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
    client_id=token_data['client_id'], client_secret=token_data['client_secret'],
    scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
gc = gspread.authorize(creds)

# MAS staging sheet
STAGING = '1WOPSU6JLoinVUexwJzbB-vpQS-4hoDp8TskP3GcKYaE'
NEW = '1vOMj5p-X1GAZEAd4Hp_RoSgYtauBiCKF9RW7GRHVxHM'

print("=== MAS STAGING SHEET ===")
sh1 = gc.open_by_key(STAGING)
print("Sheets:", [ws.title for ws in sh1.worksheets()])
try:
    ws = sh1.worksheet('Realtime_Watchlist')
    vals = ws.get_all_values()
    print(f"Realtime_Watchlist: {len(vals)} rows x {len(vals[0]) if vals else 0} cols")
    print(f"  Header: {vals[0]}" if vals else "  Empty")
    # Check last column (date format)
    if vals:
        for r in vals[1:4]:
            print(f"  {r[0]}: date={r[-1] if len(r)>13 else 'N/A'}")
except Exception as e:
    print(f"  Realtime_Watchlist: {e}")

# Check for All Tickers if exists
try:
    at = sh1.worksheet('All Tickers')
    print(f"All Tickers: {len(at.get_all_values())} rows - EXISTS in staging!")
except:
    print("All Tickers: not in staging")

print("\n=== NEW SHEET ===")
sh2 = gc.open_by_key(NEW)
print("Sheets:", [ws.title for ws in sh2.worksheets()])
try:
    ws2 = sh2.worksheet('Realtime_Watchlist')
    vals2 = ws2.get_all_values()
    print(f"Realtime_Watchlist: {len(vals2)} rows x {len(vals2[0]) if vals2 else 0} cols")
    if vals2:
        print(f"  Header: {vals2[0]}")
        for r in vals2[1:4]:
            print(f"  {r[0]}: date={r[-1] if len(r)>13 else 'N/A'}")
except Exception as e:
    print(f"  Realtime_Watchlist: {e}")
