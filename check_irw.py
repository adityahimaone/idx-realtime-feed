#!/usr/bin/env python3
"""Check computed values vs formula text on Dashboard [IRW]."""
import gspread, json
from pathlib import Path
from google.oauth2.credentials import Credentials

STAGING = '1WOPSU6JLoinVUexwJzbB-vpQS-4hoDp8TskP3GcKYaE'
token_data = json.loads(open(Path.home() / '.hermes' / 'google_token.json').read())
creds = Credentials(token=token_data['token'], refresh_token=token_data.get('refresh_token'),
    token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
    client_id=token_data['client_id'], client_secret=token_data['client_secret'],
    scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
gc = gspread.authorize(creds)
sh = gc.open_by_key(STAGING)
ws = sh.worksheet('Dashboard [IRW]')

# Get computed values via raw API
req = ws.spreadsheet.values_get(ws.title, params={
    'valueRenderOption': 'FORMATTED_VALUE',
    'majorDimension': 'ROWS'
})
vals = req.get('values', [])

print(f"Total rows: {len(vals)}")
for r in vals[:6]:
    if not r:
        continue
    ticker = r[0] if len(r) > 0 else '?'
    rec = r[6] if len(r) > 6 else '?'
    risk = r[7] if len(r) > 7 else '?'
    tp = r[9] if len(r) > 9 else '?'
    sl = r[10] if len(r) > 10 else '?'
    price = r[1] if len(r) > 1 else '?'
    print(f"  {ticker}: price={price} rec={rec} risk={risk} tp={tp} sl={sl}")

# Summary section
print()
for r in vals[-12:]:
    if r and len(r) > 0 and any(x.strip() for x in r[:2]):
        print(f"  {r[0]}: {r[1] if len(r)>1 else ''}")
