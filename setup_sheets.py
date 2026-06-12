#!/usr/bin/env python3
"""Create Alpha_Watchlist + Dashboard [stockbit] in new Market Alpha Scout sheet."""
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

# ── Watchlist tickers from Stockbit API ──
WATCHLIST = ['ADRO', 'ANTM', 'ARCI', 'ASII', 'BBCA', 'BBNI', 'BBRI', 'BMRI', 'BNGA',
             'BREN', 'BRPT', 'BULL', 'CDIA', 'EMAS', 'ESSA', 'FOLK', 'GTSI', 'ITMG',
             'MBMA', 'PGAS', 'PMJS', 'PSAB', 'TLKM', 'TOSK', 'UNTR']

# ── 1. Create Alpha_Watchlist sheet ──
print("=== Creating Alpha_Watchlist ===")
try:
    ws = sh.worksheet('Alpha_Watchlist')
    print("  Already exists, updating...")
except:
    ws = sh.add_worksheet('Alpha_Watchlist', rows=50, cols=8)
    print("  Created new sheet")

# Headers
headers = ['Ticker', 'Company Name', 'Sector', 'Last Price', 'Change %', 'Volume', 'MarketCap', 'PE']

# Clear & write
ws.clear()
ws.append_row(headers)

# Use VLOOKUP formulas referencing All Tickers
# All Tickers columns: A=No(1), B=Ticker(2), C=Company(3), D=Sector(4), E=Sparkline(5),
# F=Price(6), G=Change%(7), H=Change(8), I=PriceOpen(9), J=High(10), K=Low(11),
# L=ClosePrev(12), M=Gap_Pct(13), U=MarketCap(21), V=PE(22)
for i, ticker in enumerate(WATCHLIST, start=2):
    row_num = i
    formula_ticker = f'B{row_num}'
    
    ws.update_acell(f'A{row_num}', ticker)
    
    # Company Name from All Tickers
    ws.update_acell(f'B{row_num}', f'=IFERROR(VLOOKUP(A{row_num},\'All Tickers\'!B:C,2,FALSE),"")')
    # Sector from All Tickers
    ws.update_acell(f'C{row_num}', f'=IFERROR(VLOOKUP(A{row_num},\'All Tickers\'!B:D,3,FALSE),"")')
    # Last Price from All Tickers
    ws.update_acell(f'D{row_num}', f'=IFERROR(VLOOKUP(A{row_num},\'All Tickers\'!B:F,5,FALSE),"")')
    # Change % from All Tickers
    ws.update_acell(f'E{row_num}', f'=IFERROR(VLOOKUP(A{row_num},\'All Tickers\'!B:G,6,FALSE),"")')
    # Volume from All Tickers
    ws.update_acell(f'F{row_num}', f'=IFERROR(VLOOKUP(A{row_num},\'All Tickers\'!B:O,14,FALSE),"")')
    # MarketCap from All Tickers
    ws.update_acell(f'G{row_num}', f'=IFERROR(VLOOKUP(A{row_num},\'All Tickers\'!B:U,20,FALSE),"")')
    # PE from All Tickers
    ws.update_acell(f'H{row_num}', f'=IFERROR(VLOOKUP(A{row_num},\'All Tickers\'!B:V,21,FALSE),"")')

print(f"  Added {len(WATCHLIST)} tickers with formulas")

# ── 2. Create Dashboard [stockbit] sheet ──
print("\n=== Creating Dashboard [stockbit] ===")
try:
    ws_dash = sh.worksheet('Dashboard [stockbit]')
    print("  Already exists, updating...")
    ws_dash.clear()
except:
    ws_dash = sh.add_worksheet('Dashboard [stockbit]', rows=50, cols=20)
    print("  Created new sheet")

# Title row
ws_dash.update_acell('A1', '📊 DASHBOARD [STOCKBIT] — Realtime Watchlist Analysis')
ws_dash.update_acell('A2', f'Generated: {time.strftime("%Y-%m-%d %H:%M")} WIB | Source: Stockbit Feed + Market Alpha Scout')

# Column headers (row 4)
dash_headers = [
    'No',
    'Ticker',
    'Company',
    'Sector',
    'Trend',
    'Last Price',
    'Change %',
    'Volume',
    'Vol Ratio',
    'MA20',
    'MA50',
    'MA200',
    'RSI14',
    'RSI Signal',
    'Score v2',
    'Final Signal',
    'Recommendation',
    'ARA Distance %',
    'Notes'
]
ws_dash.update(f'A4:S4', [dash_headers])

# Row 5 onwards: formulas referencing All Tickers
# All Tickers columns reference:
# B=Ticker(2), C=Company(3), D=Sector(4), F=Price(6), G=Change%(7), O=Volume(15),
# P=Vol_Avg(16), Q=Vol_Ratio(17), AF=MA20(32), AG=MA50(33), AH=MA200(34),
# AM=BSJP(39), AN=Signal(40), AO=Trend(41), AP=Score(42), AQ=Score v2(43),
# AR=Rank(44), AS=Final_Signal(45), AW=RSI14(49), AX=RSI Signal(50),
# BG=ARA_Dist_Pct(59)

for i, ticker in enumerate(WATCHLIST, start=5):
    r = i  # row number
    ws_dash.update_acell(f'A{r}', i-4)  # No
    ws_dash.update_acell(f'B{r}', ticker)  # Ticker
    
    at_range = f"'All Tickers'!B:BG"
    
    formulas = {
        'C': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:C,2,FALSE),"")',       # Company
        'D': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:D,3,FALSE),"")',       # Sector
        'E': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AO,40-1,FALSE),"")',   # Trend
        'F': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:F,5,FALSE),"")',       # Price
        'G': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:G,6,FALSE),"")',       # Change %
        'H': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:O,14,FALSE),"")',      # Volume
        'I': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:Q,16,FALSE),"")',      # Vol Ratio
        'J': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AF,32-1,FALSE),"")',   # MA20
        'K': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AG,33-1,FALSE),"")',   # MA50
        'L': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AH,34-1,FALSE),"")',   # MA200
        'M': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AW,49-1,FALSE),"")',   # RSI14
        'N': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AX,50-1,FALSE),"")',   # RSI Signal
        'O': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AQ,43-1,FALSE),"")',   # Score v2
        'P': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:AS,45-1,FALSE),"")',   # Final Signal
        'R': f'=IFERROR(VLOOKUP(B{r},\'All Tickers\'!B:BG,59-1,FALSE),"")',   # ARA Distance %
    }
    
    for col, formula in formulas.items():
        ws_dash.update_acell(f'{col}{r}', formula)
    
    # Recommendation formula (col Q)
    # Combines Final Signal + RSI + Price vs MA
    rec_formula = (
        f'=IF(P{r}="STRONG_BUY","🔥 STRONG BUY",'
        f'IF(P{r}="BUY","✅ BUY",'
        f'IF(AND(M{r}>70,P{r}="SELL"),"⚠️ OVERBOUGHT - JUAL",'
        f'IF(AND(M{r}<30,P{r}="BUY"),"💎 OVERSOLD - BELI",'
        f'IF(P{r}="SELL","🔴 SELL",'
        f'IF(P{r}="HOLD","⏸️ HOLD","❓ WAIT"))))))'
    )
    ws_dash.update_acell(f'Q{r}', rec_formula)
    
    # Notes col S (sector-based + price action)
    notes_formula = (
        f'=IF(G{r}>5,"🔺Gain >5%",IF(G{r}<-3,"🔻Loss >3%",'
        f'IF(N{r}="OVERBOUGHT","⚠️ RSI Overbought",'
        f'IF(N{r}="OVERSOLD","💡 RSI Oversold",""))))'
    )
    ws_dash.update_acell(f'S{r}', notes_formula)

print(f"  Added {len(WATCHLIST)} tickers with comprehensive formulas")

# ── 3. Summary section ──
print("\n=== Adding Summary Section ===")
summary_start = len(WATCHLIST) + 7
ws_dash.update_acell(f'A{summary_start}', '📋 SUMMARY')
ws_dash.update_acell(f'A{summary_start+1}', 'STRONG BUY Count')
ws_dash.update_acell(f'B{summary_start+1}', f'=COUNTIF(P5:P{summary_start-2},"STRONG_BUY")')
ws_dash.update_acell(f'A{summary_start+2}', 'BUY Count')
ws_dash.update_acell(f'B{summary_start+2}', f'=COUNTIF(P5:P{summary_start-2},"BUY")')
ws_dash.update_acell(f'A{summary_start+3}', 'SELL Count')
ws_dash.update_acell(f'B{summary_start+3}', f'=COUNTIF(P5:P{summary_start-2},"SELL")')
ws_dash.update_acell(f'A{summary_start+4}', 'HOLD Count')
ws_dash.update_acell(f'B{summary_start+4}', f'=COUNTIF(P5:P{summary_start-2},"HOLD")')
ws_dash.update_acell(f'A{summary_start+5}', 'Buy/Sell Ratio')
ws_dash.update_acell(f'B{summary_start+5}', f'=IFERROR(B{summary_start+2}/B{summary_start+3},"")')
ws_dash.update_acell(f'A{summary_start+7}', 'Best Performer')
ws_dash.update_acell(f'B{summary_start+7}', f'=IFERROR(INDEX(B5:B{summary_start-2},MATCH(MAX(G5:G{summary_start-2}),G5:G{summary_start-2},0)),"")')
ws_dash.update_acell(f'A{summary_start+8}', 'Worst Performer')
ws_dash.update_acell(f'B{summary_start+8}', f'=IFERROR(INDEX(B5:B{summary_start-2},MATCH(MIN(G5:G{summary_start-2}),G5:G{summary_start-2},0)),"")')

print("  Summary formulas added")

# ── 4. Formatting hints ──
print("\n=== Setup Complete ===")
print(f"Alpha_Watchlist: {len(WATCHLIST)} tickers")
print(f"Dashboard [stockbit]: {len(WATCHLIST)} tickers with full analysis + summary")
print(f"\nNext step: Update .env → NEW_SHEET, then run feed")
