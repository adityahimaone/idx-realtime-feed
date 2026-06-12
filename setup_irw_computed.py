#!/usr/bin/env python3
"""Dashboard [IRW] — computed in Python, no formulas."""
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

# Read RW data
ws_rw = sh.worksheet('Realtime_Watchlist [IRW]')
rw_vals = ws_rw.get_all_values()

# Build ticker -> row lookup
rw_map = {}
for row in rw_vals[1:]:
    if not row or not row[0].strip():
        continue
    t = row[0].strip().upper()
    try:
        rw_map[t] = {
            'price': float(row[1]) if row[1] else 0,
            'chg': float(row[2]) if row[2] else 0,
            'high': float(row[3]) if row[3] else 0,
            'low': float(row[4]) if row[4] else 0,
            'open': float(row[5]) if row[5] else 0,
            'vol': int(row[6]) if row[6] else 0,
            'bid_lot': int(row[7]) if row[7] else 0,
            'ask_lot': int(row[8]) if row[8] else 0,
            'fnet': int(row[10]) if row[10] else 0,
            'support': float(row[13]) if row[13] else 0,
            'resistance': float(row[14]) if row[14] else 0,
        }
    except (ValueError, IndexError):
        continue

tickers = sorted(rw_map.keys())
print(f"Tickers: {len(tickers)}")

cols = ['Ticker', 'Last Price', 'Chg %', 'Volume', 'Demand', 'Trend',
        'Rec', 'Risk', 'Entry Zone', 'TP', 'SL', 'Notes']
ws_dash.update([cols], 'A1:L1')

rows = []
for t in tickers:
    d = rw_map[t]
    p = d['price']
    c = d['chg']
    v = d['vol']
    bid = d['bid_lot']
    ask = d['ask_lot']
    sup = d['support']
    res = d['resistance']
    
    # Demand
    if ask > 0:
        bar = round(min(bid / ask, 10), 2)
        dem = f"{bar}x" if bar > 0 else "-"
    else:
        bar = 0
        dem = "-"
    
    # Trend
    if c > 2: trend = "Up 🚀"
    elif c > 0: trend = "Mild ↗"
    else: trend = "Down ↘"
    
    # Rec
    if c > 3: rec = "🔥 BUY"
    elif c > 0: rec = "✅ BUY"
    elif c < -3: rec = "🔴 SELL"
    else: rec = "⏸ HOLD"
    
    # Risk
    if c > 5: risk = "🔥 Aggressive"
    elif c > 0: risk = "⚡ Moderate"
    else: risk = "💧 Low Risk"
    
    # Entry
    entry = "Market" if c > 0 else "Wait Pullback"
    
    # TP/SL
    if c > 5:
        tp = round(p * 1.07)
        sl = round(p * 0.97)
    elif c > 0:
        tp = round(p * 1.05)
        sl = round(p * 0.95)
    else:
        tp = round(p * 1.03)
        sl = round(p * 0.93)
    
    # Notes
    if c > 5: notes = "High Momentum"
    elif c > 0: notes = "Accumulation"
    elif c < -3: notes = "Avoid"
    else: notes = "Sideways"
    
    rows.append([t, p, c, v, dem, trend, rec, risk, entry, tp, sl, notes])

# Write in batches
for i in range(0, len(rows), 10):
    batch = rows[i:i+10]
    start = i + 2
    rng = f'A{start}:L{start+len(batch)-1}'
    ws_dash.update(batch, rng, value_input_option='USER_ENTERED')
    time.sleep(0.5)

# Summary
sr = len(tickers) + 4
strong = sum(1 for r in rows if r[6] == "🔥 BUY")
buy = sum(1 for r in rows if r[6] == "✅ BUY")
hold = sum(1 for r in rows if r[6] == "⏸ HOLD")
sell = sum(1 for r in rows if r[6] == "🔴 SELL")
agg = sum(1 for r in rows if "Aggressive" in r[7])
mod = sum(1 for r in rows if "Moderate" in r[7])
low = sum(1 for r in rows if "Low Risk" in r[7])

summary = [
    ['📊 RECAP'], ['', ''],
    ['🔥 Strong Buy', strong],
    ['✅ Buy', buy],
    ['⏸ Hold/Wait', hold],
    ['🔴 Sell', sell],
    ['', ''],
    ['🔥 Aggressive (Scalp)', agg],
    ['⚡ Moderate (Swing)', mod],
    ['💧 Low Risk (Long)', low],
    ['', ''],
    ['Top Scalp', rows[0][0] if rows else '-'],
    ['Watchlist Count', len(tickers)],
]
ws_dash.update(summary, f'A{sr}', value_input_option='USER_ENTERED')

# Verify
ws_dash = sh.worksheet('Dashboard [IRW]')
vals = ws_dash.get_all_values()
print(f"\nDashboard [IRW]: {len(vals)} rows")
for r in vals[1:6]:
    print(f"  {r[0]}: p={r[1]} chg={r[2]} rec={r[6]} risk={r[7]} tp={r[9]} sl={r[10]}")

print("\nDone! All values computed in Python, no formula dependency.")
