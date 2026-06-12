#!/usr/bin/env python3
"""Simplified Dashboard [IRW] formulas."""
import gspread, json, time
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

ws_dash = sh.worksheet('Dashboard [IRW]')
ws_dash.clear()

dash_header = ['No', 'Ticker', 'Last Price', 'Chg %', 'Vol', 'Rec', 'TP', 'SL', 'Notes']
ws_dash.update('A1:I1', [dash_header])

# Watchlist data from Realtime_Watchlist [IRW]
ws_rw = sh.worksheet('Realtime_Watchlist [IRW]')
tickers = [t.strip().upper() for t in ws_rw.col_values(1)[1:] if t.strip()]

rows = []
for idx, t in enumerate(tickers, start=2):
    # Formulas reference Realtime_Watchlist [IRW]
    rw = "'Realtime_Watchlist [IRW]'"
    price = f'=IFERROR(VLOOKUP(B{idx},{rw}!A:Q,2,FALSE),"")'
    chg = f'=IFERROR(VLOOKUP(B{idx},{rw}!A:Q,3,FALSE),"")'
    vol = f'=IFERROR(VLOOKUP(B{idx},{rw}!A:Q,7,FALSE),"")'
    
    # Simple logic
    rec = f'=IF({chg}>5,"🔥 BUY",IF({chg}<-3,"🔴 SELL","⏸ HOLD"))'
    tp = f'=IFERROR(ROUND({price}*1.05,0),"")'
    sl = f'=IFERROR(ROUND({price}*0.95,0),"")'
    notes = f'=IF({chg}>5,"Momentum Up","Stable")'
    
    rows.append([idx-1, t, price, chg, vol, rec, tp, sl, notes])

ws_dash.update('A2:I'+str(len(rows)+1), rows, value_input_option='USER_ENTERED')
print("Dashboard [IRW] updated with simple formulas.")
