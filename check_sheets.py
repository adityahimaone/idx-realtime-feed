import gspread, json
from pathlib import Path
from google.oauth2.credentials import Credentials

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

# NEW spreadsheet
NEW_SHEET = '1vOMj5p-X1GAZEAd4Hp_RoSgYtauBiCKF9RW7GRHVxHM'
OLD_SHEET = '1wr2f6drQBqBUxikdJqSp1YVPaHF13qX0V3c7p4hkw5U'

sh = gc.open_by_key(NEW_SHEET)
old_sh = gc.open_by_key(OLD_SHEET)

print("=== NEW SHEET ===")
print("Current sheets:", [ws.title for ws in sh.worksheets()])

print("\n=== OLD SHEET (staging) ===")
print("Sheets:", [ws.title for ws in old_sh.worksheets()])

# Check what's in old sheet's Alpha_Watchlist / Realtime_Watchlist
for name in ['Alpha_Watchlist', 'Realtime_Watchlist']:
    try:
        ws = old_sh.worksheet(name)
        vals = ws.get_all_values()
        print(f"  {name}: {len(vals)} rows")
        if vals:
            print(f"    Header: {vals[0][:5]}")
            if len(vals) > 1:
                print(f"    Row 2: {vals[1][:5]}")
    except:
        print(f"  {name}: not found")

# Check All Tickers structure in new sheet
ws_at = sh.worksheet('All Tickers')
header = ws_at.row_values(1)
print(f"\nAll Tickers columns ({len(header)}): {header}")
