import gspread, json
from pathlib import Path
from google.oauth2.credentials import Credentials

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

# OLD sheet - check Dashboard [Stockbit]
old = gc.open_by_key('1wr2f6drQBqBUxikdJqSp1YVPaHF13qX0V3c7p4hkw5U')
ws = old.worksheet('Dashboard [Stockbit]')
vals = ws.get_all_values()
print(f"Dashboard [Stockbit]: {len(vals)} rows x {len(vals[0]) if vals else 0} cols")
for i, row in enumerate(vals[:30]):
    print(f"  Row {i+1}: {row[:8]}")

# Also check Alpha_Watchlist in old sheet for full data
ws2 = old.worksheet('Alpha_Watchlist')
vals2 = ws2.get_all_values()
print(f"\nAlpha_Watchlist: {len(vals2)} rows")
for row in vals2[:5]:
    print(f"  {row[:5]}")

# Check the formulas in All Tickers for a sample row
new = gc.open_by_key('1vOMj5p-X1GAZEAd4Hp_RoSgYtauBiCKF9RW7GRHVxHM')
at = new.worksheet('All Tickers')
# Get formulas for row 2 (AADI)
formulas = [at.cell(2, c).value for c in range(1, 61)]
print(f"\nAll Tickers Row 2 formulas (first 30):")
for i, f in enumerate(formulas[:30]):
    print(f"  Col {i+1}: {str(f)[:80]}")
