#!/usr/bin/env python3
"""Rename sheets + create Dashboard [IRW] in MAS staging."""
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

# List current sheets
print("=== Current sheets ===")
sheets = {ws.title: ws for ws in sh.worksheets()}
for i, ws in enumerate(sh.worksheets()):
    print(f"  {i}: {ws.title}")

# 1. Rename Realtime_Watchlist -> Realtime_Watchlist [IRW]
rename_map = {
    'Realtime_Watchlist': 'Realtime_Watchlist [IRW]',
}

for old_name, new_name in rename_map.items():
    if old_name in sheets:
        sheets[old_name].update_title(new_name)
        print(f"  Renamed '{old_name}' -> '{new_name}'")
        time.sleep(1)
    else:
        print(f"  '{old_name}' not found")

# Refresh sheet list
sh = gc.open_by_key(STAGING)
sheets = {ws.title: ws for ws in sh.worksheets()}

# 2. Create Dashboard [IRW]
dash_name = 'Dashboard [IRW]'
try:
    ws_dash = sh.worksheet(dash_name)
    ws_dash.clear()
    print(f"  '{dash_name}' exists, cleared")
except:
    ws_dash = sh.add_worksheet(title=dash_name, rows=150, cols=25)
    print(f"  Created '{dash_name}'")

time.sleep(2)

# Write header
dash_header = [
    'No', 'Ticker',
    'Last Price', 'Change %', 'Volume',
    'Bid Lot', 'Ask Lot', 'Bid/Ask Ratio',
    'Support', 'Resistance',
    'Score v2', 'Final Signal',
    'RSI', 'MA20', 'MA50',
    'Trend', 'ARA Dist %', 'ARB Dist %',
    'Recommendation', 'Risk Level',
    'Entry Zone', 'TP', 'SL',
    'Notes', 'Last Update'
]
ws_dash.update('A1:Y1', [dash_header])

# Read watchlist tickers from Realtime_Watchlist [IRW]
ws_rw = sh.worksheet('Realtime_Watchlist [IRW]')
tickers_raw = ws_rw.col_values(1)[1:]  # skip header
tickers = [t.strip().upper() for t in tickers_raw if t.strip()]
print(f"\nWatchlist tickers: {len(tickers)}")

# Build rows with formulas referencing Realtime_Watchlist [IRW] and All Tickers
# Realtime_Watchlist [IRW] is 17 cols: A=Ticker, B=Price, C=Change%, D=High, E=Low, 
# F=Open, G=Volume, H=BidLot, I=AskLot, J=Imbalance, K=FNet, L=ARA, M=ARB, N=Support, O=Resist, P=Source, Q=Update
# All Tickers: B=Ticker, AF=MA20, AG=MA50, AH=MA200, AO=Score, AP=Score_v2, AR=Final_Signal, AX=RSI, AY=RSI_Signal, BE=ARA_Dist, BF=ARB_Dist

rows = []
for idx, t in enumerate(tickers, start=2):
    rw_ref = f"'Realtime_Watchlist [IRW]'"
    at_ref = "'All Tickers'"
    
    # Formula for price (col B from RW)
    price = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,2,FALSE),"")'
    chg = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,3,FALSE),"")'
    vol = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,7,FALSE),"")'
    bid = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,8,FALSE),"")'
    ask = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,9,FALSE),"")'
    bar = f'=IFERROR(ROUND(VLOOKUP(B{idx},{rw_ref}!A:Q,8,FALSE)/VLOOKUP(B{idx},{rw_ref}!A:Q,9,FALSE),2),"")'
    sup = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,14,FALSE),"")'
    res = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,15,FALSE),"")'
    update = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,17,FALSE),"")'
    
    # From All Tickers (MAS data)
    score = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,42-1,FALSE),"")'  # AP=42->col 41
    signal = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,44-1,FALSE),"")'  # AR=44->col 43
    rsi = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,50-1,FALSE),"")'  # AX=50->col 49
    ma20 = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,32-1,FALSE),"")'  # AF=32->col 31
    ma50 = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,33-1,FALSE),"")'  # AG=33->col 32
    trend = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,40-1,FALSE),"")'  # AN=40->col 39
    ara_d = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,57-1,FALSE),"")'  # BE=57->col 56
    arb_d = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,58-1,FALSE),"")'  # BF=58->col 57

    # Recommendation logic
    rec = (
        f'=IF({signal}="STRONG_BUY","STRONG BUY",'
        f'IF({signal}="BUY",'
        f'IF({rsi}<40,"✅ BUY - OVERSOLD",'
        f'IF(AND({rsi}>=40,{rsi}<70),"✅ BUY","")),'
        f'IF(OR({signal}="SELL",AND({rsi}>70,{signal}="HOLD")),"🔴 SELL",'
        f'IF({signal}="HOLD","⏸ HOLD","❓ WAIT"))))'
    )

    # Risk Level: Aggressive (strong buy + volume + bid/ask), Moderate, Low
    risk = (
        f'=IF({signal}="STRONG_BUY","🔥Aggressive",'
        f'IF(AND({signal}="BUY",IFERROR({rsi}<50,FALSE)),"⚡Moderate",'
        f'IF({signal}="BUY","💧Low Risk","N/A")))'
    )

    # Entry Zone
    entry = (
        f'=IF({signal}="STRONG_BUY",'
        f'IF(AND({price}>0,{sup}>0),"Market - Limit @ {sup}","Market"),'
        f'IF({signal}="BUY",'
        f'IF(AND({price}>0,{sup}>0,{price}>{sup}*1.05),"Wait pullback to {sup}","Market"),'
        f'"Wait"))'
    )

    # TP: 3 levels based on risk
    # Aggressive: TP at Resistance + 2%
    # Moderate: TP at ARA distance/2 or Resistance
    # Low Risk: TP at ARA (auto stop)
    tp = (
        f'=IF({risk}="🔥Aggressive",'
        f'IFERROR(ROUND({res}*1.02,0),"N/A"),'
        f'IF({risk}="⚡Moderate",'
        f'IFERROR(ROUND({res}*1.01,0),"N/A"),'
        f'IF({risk}="💧Low Risk",'
        f'IFERROR(ROUND({price}*1.05,0),"N/A"),"N/A")))'
    )

    # SL: based on risk
    # Aggressive: tight SL 2% below support
    # Moderate: SL at support - 3%
    # Low Risk: WIDE SL - 7%
    sl = (
        f'=IF({risk}="🔥Aggressive",'
        f'IFERROR(ROUND({sup}*0.98,0),"N/A"),'
        f'IF({risk}="⚡Moderate",'
        f'IFERROR(ROUND({price}*0.95,0),"N/A"),'
        f'IF({risk}="💧Low Risk",'
        f'IFERROR(ROUND({price}*0.92,0),"N/A"),"N/A")))'
    )

    # Notes
    notes = (
        f'=IF({rec}="STRONG BUY","🔥 High conviction",'
        f'IF({rec}="✅ BUY - OVERSOLD","💎 Oversold bounce play",'
        f'IF({rec}="🔴 SELL","🔻 Avoid / take profit",'
        f'IF({rsi}>70,"⚠ Overbought",'
        f'IF({bar}>1.2,"📊 Heavy demand",'
        f'IF({vol}>500000000,"💹 High volume",""))))))'
    )

    rows.append([
        idx-1,  # No
        t,       # Ticker
        price, chg, vol, bid, ask, bar, sup, res,
        score, signal,
        rsi, ma20, ma50, trend, ara_d, arb_d,
        rec, risk, entry, tp, sl, notes, update
    ])

# Write in batches of 10 (avoid rate limit)
batch_size = 10
for i in range(0, len(rows), batch_size):
    batch = rows[i:i+batch_size]
    start_row = i + 2
    end_col = chr(64 + len(dash_header))  # Y = 25
    ws_dash.update(f'A{start_row}', batch, value_input_option='USER_ENTERED')
    time.sleep(1.5)
    print(f"  Wrote rows {start_row}-{start_row+len(batch)-1}")

# Summary section
sr = len(tickers) + 4  # Row after data + 3 empty rows
summary = [
    ['📊 SUMMARY [IRW]'],
    ['Total Tickers', f'={len(tickers)}'],
    ['STRONG BUY', f'=COUNTIF(S2:S{len(tickers)+1},"*STRONG BUY*")'],
    ['BUY (Total)', f'=COUNTIF(S2:S{len(tickers)+1},"✅ BUY*")'],
    ['SELL', f'=COUNTIF(S2:S{len(tickers)+1},"🔴 SELL*")'],
    ['HOLD/WAIT', f'=COUNTIF(S2:S{len(tickers)+1},"*HOLD*")+COUNTIF(S2:S{len(tickers)+1},"*WAIT*")'],
    ['Aggressive', f'=COUNTIF(T2:T{len(tickers)+1},"*Aggressive*")'],
    ['Moderate', f'=COUNTIF(T2:T{len(tickers)+1},"*Moderate*")'],
    ['Low Risk', f'=COUNTIF(T2:T{len(tickers)+1},"*Low Risk*")'],
    ['', ''],
    ['Scalp Pick', f'=IFERROR(INDEX(B2:B{len(tickers)+1},MATCH(MAX(K2:K{len(tickers)+1}),K2:K{len(tickers)+1},0)),"")'],
    ['Long Term Pick', f'=IFERROR(INDEX(B2:B{len(tickers)+1},MATCH(MAX(G2:G{len(tickers)+1}),G2:G{len(tickers)+1},0)),"")'],
]
ws_dash.update(f'A{sr}', summary, value_input_option='USER_ENTERED')
print(f"\nSummary at row {sr}")

# Final verify
sh = gc.open_by_key(STAGING)
print("\n=== Final sheets ===")
for i, ws in enumerate(sh.worksheets()):
    print(f"  {i}: {ws.title}")

print("\n✅ Done! Dashboard [IRW] with buy/sell recs, TP/SL created.")
