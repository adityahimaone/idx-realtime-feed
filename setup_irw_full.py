#!/usr/bin/env python3
"""Full Dashboard [IRW] - explicit params."""
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

cols = ['Ticker', 'Last Price', 'Chg %', 'Volume', 'Demand',
        'Trend', 'Rec', 'Risk', 'Entry Zone', 'TP', 'SL', 'Notes']
ws_dash.update(values=[cols], range_name='A1:L1')

ws_rw = sh.worksheet('Realtime_Watchlist [IRW]')
tickers = [t.strip().upper() for t in ws_rw.col_values(1)[1:] if t.strip()]
RW = "'Realtime_Watchlist [IRW]'"

def v(col): return f'IFERROR(VLOOKUP(A$2:A${len(tickers)+1},{RW}!A:Q,{col},FALSE),"")'

rows = []
for idx, t in enumerate(tickers, start=2):
    p = f'IFERROR(VLOOKUP(A{idx},{RW}!A:Q,2,FALSE),"")'
    c = f'IFERROR(VLOOKUP(A{idx},{RW}!A:Q,3,FALSE),"")'
    vol = f'IFERROR(VLOOKUP(A{idx},{RW}!A:Q,7,FALSE),"")'
    bid = f'IFERROR(VLOOKUP(A{idx},{RW}!A:Q,8,FALSE),"")'
    ask = f'IFERROR(VLOOKUP(A{idx},{RW}!A:Q,9,FALSE),"")'
    
    bc = f'IF(OR({bid}="",{ask}="",{ask}=0),"",MIN({bid}/{ask},5))'
    trend = f'IF({c}>2,"Up 🚀",IF({c}>0,"Mild ↗","Down ↘"))'
    dem = f'IF({bc}="","",IF({bc}>1.5,"🔥High",IF({bc}>1,"Medium","Low")))'
    rec_val = f'IF({c}>3,"🔥 BUY",IF({c}>0,"✅ BUY",IF({c}<-3,"🔴 SELL","⏸ HOLD")))'
    risk_val = f'IF({c}>5,"🔥 Aggressive",IF({c}>0,"⚡ Moderate","💧 Low Risk"))'
    entry = f'IF({c}>0,"Market","Wait Pullback")'
    notes = f'IF({c}>5,"High Momentum",IF({c}>0,"Accumulation",IF({c}<-3,"Avoid","Sideways")))'
    tp = f'IF({c}>5,ROUND({p}*1.07,0),IF({c}>0,ROUND({p}*1.05,0),ROUND({p}*1.03,0)))'
    sl = f'IF({c}>5,ROUND({p}*0.97,0),IF({c}>0,ROUND({p}*0.95,0),ROUND({p}*0.93,0)))'
    
    rows.append([t, p, c, vol, dem, trend, rec_val, risk_val, entry, tp, sl, notes])

rng = f'A2:L{len(rows)+1}'
ws_dash.update(values=rows, range_name=rng, params={'valueInputOption': 'USER_ENTERED'})
time.sleep(2)

sr = len(tickers) + 4
summary = [
    ['📊 RECAP'],
    ['🔥 Strong Buy', f'=COUNTIF(G2:G{len(tickers)+1},"🔥 BUY")'],
    ['✅ Buy', f'=COUNTIF(G2:G{len(tickers)+1},"✅ BUY")'],
    ['⏸ Hold/Wait', f'=COUNTIF(G2:G{len(tickers)+1},"⏸*")+COUNTIF(G2:G{len(tickers)+1},"*WAIT*")'],
    ['🔴 Sell', f'=COUNTIF(G2:G{len(tickers)+1},"🔴 SELL")'],
    ['', ''],
    ['🔥 Aggressive (Scalp)', f'=COUNTIF(H2:H{len(tickers)+1},"🔥 Aggressive")'],
    ['⚡ Moderate (Swing)', f'=COUNTIF(H2:H{len(tickers)+1},"⚡ Moderate")'],
    ['💧 Low Risk (Long)', f'=COUNTIF(H2:H{len(tickers)+1},"💧 Low Risk")'],
]
ws_dash.update(values=summary, range_name=f'A{sr}', params={'valueInputOption': 'USER_ENTERED'})
print("Dashboard [IRW] done!")
