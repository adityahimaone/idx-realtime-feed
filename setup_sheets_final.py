#!/usr/bin/env python3
"""Create Alpha_Watchlist + Dashboard [stockbit] — batch writes with correct VLOOKUP col indices."""
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

WATCHLIST = ['ADRO', 'ANTM', 'ARCI', 'ASII', 'BBCA', 'BBNI', 'BBRI', 'BMRI', 'BNGA',
             'BREN', 'BRPT', 'BULL', 'CDIA', 'EMAS', 'ESSA', 'FOLK', 'GTSI', 'ITMG',
             'MBMA', 'PGAS', 'PMJS', 'PSAB', 'TLKM', 'TOSK', 'UNTR']

# All Tickers column mapping (A1 notation)
# B=Ticker(1), C=Company(2), D=Sector(3), F=Price(5), G=Change%(6), O=Volume(14),
# Q=Vol_Ratio(16), AF=MA20(31), AG=MA50(32), AH=MA200(33), AN=Trend(39), AO=Score(40),
# AP=Score_v2(41), AR=Final_Signal(43), AS=SL_Practical(44), AW=ATR%(48),
# AX=RSI14(49), AY=RSI_Signal(50), BE=ARA_Dist_Pct(56)

# VLOOKUP col index = sheet_col - 1 (when range starts at B)
def vlookup(ticker_row, sheet_col):
    return f'=IFERROR(VLOOKUP(B{ticker_row},\'All Tickers\'!B:BH,{sheet_col-1},FALSE),"")'

# === 1. Alpha_Watchlist ===
print("=== Alpha_Watchlist ===")
try:
    ws = sh.worksheet('Alpha_Watchlist')
    ws.clear()
except:
    ws = sh.add_worksheet('Alpha_Watchlist', rows=50, cols=8)

alpha_rows = [['Ticker', 'Company Name', 'Sector', 'Last Price', 'Change %', 'Volume', 'MarketCap', 'PE']]
for idx, t in enumerate(WATCHLIST, start=2):
    alpha_rows.append([
        t,
        vlookup(idx, 3),   # Company
        vlookup(idx, 4),   # Sector
        vlookup(idx, 6),   # Price
        vlookup(idx, 7),   # Change%
        vlookup(idx, 15),  # Volume
        vlookup(idx, 21),  # MarketCap
        vlookup(idx, 22),  # PE
    ])

ws.update(range_name='A1', values=alpha_rows, value_input_option='USER_ENTERED')
print(f"  Alpha_Watchlist: {len(alpha_rows)} rows")
time.sleep(2)

# === 2. Dashboard [stockbit] ===
print("\n=== Dashboard [stockbit] ===")
try:
    ws_dash = sh.worksheet('Dashboard [stockbit]')
    ws_dash.clear()
except:
    ws_dash = sh.add_worksheet('Dashboard [stockbit]', rows=60, cols=20)

ws_dash.update_acell('A1', '📊 DASHBOARD [STOCKBIT] — Realtime Watchlist Analysis')
ws_dash.update_acell('A2', f'Generated: {time.strftime("%Y-%m-%d %H:%M")} WIB | Data: Stockbit Feed + Market Alpha Scout')

dash_headers = ['No', 'Ticker', 'Company', 'Sector', 'Trend', 'Last Price', 'Change %',
                'Volume', 'Vol Ratio', 'MA20', 'MA50', 'MA200', 'RSI14', 'RSI Signal',
                'Score v2', 'Final Signal', 'Recommendation', 'ARA Distance %', 'Notes']
ws_dash.update('A4:S4', [dash_headers])

dash_rows = []
for idx, t in enumerate(WATCHLIST, start=5):
    dash_rows.append([
        idx - 4,                    # A: No
        t,                          # B: Ticker
        vlookup(idx, 3),            # C: Company
        vlookup(idx, 4),            # D: Sector
        vlookup(idx, 40),           # E: Trend (AN=40)
        vlookup(idx, 6),            # F: Price
        vlookup(idx, 7),            # G: Change%
        vlookup(idx, 15),           # H: Volume
        vlookup(idx, 17),           # I: Vol Ratio (Q=17)
        vlookup(idx, 32),           # J: MA20 (AF=32)
        vlookup(idx, 33),           # K: MA50 (AG=33)
        vlookup(idx, 34),           # L: MA200 (AH=34)
        vlookup(idx, 50),           # M: RSI14 (AX=50)
        vlookup(idx, 51),           # N: RSI Signal (AY=51)
        vlookup(idx, 42),           # O: Score v2 (AP=42)
        vlookup(idx, 44),           # P: Final_Signal (AR=44)
        # Q: Recommendation
        f'=IF(P{idx}="STRONG_BUY","🔥 STRONG BUY",IF(P{idx}="BUY","✅ BUY",IF(AND(M{idx}>70,P{idx}="SELL"),"⚠️ OVERBOUGHT - JUAL",IF(AND(M{idx}<30,P{idx}="BUY"),"💎 OVERSOLD - BELI",IF(P{idx}="SELL","🔴 SELL",IF(P{idx}="HOLD","⏸️ HOLD","❓ WAIT"))))))',
        vlookup(idx, 57),           # R: ARA Distance % (BE=57)
        # S: Notes
        f'=IF(G{idx}>5,"🔺Gain >5%",IF(G{idx}<-3,"🔻Loss >3%",IF(N{idx}="OVERBOUGHT","⚠️ RSI Overbought",IF(N{idx}="OVERSOLD","💡 RSI Oversold",""))))',
    ])

ws_dash.update(range_name='A5', values=dash_rows, value_input_option='USER_ENTERED')
print(f"  Dashboard: {len(dash_rows)} ticker rows")
time.sleep(1)

# === 3. Summary section ===
sr = len(WATCHLIST) + 7
summary_rows = [
    ['📋 SUMMARY', ''],
    ['STRONG BUY', f'=COUNTIF(P5:P{len(WATCHLIST)+4},"STRONG_BUY")'],
    ['BUY', f'=COUNTIF(P5:P{len(WATCHLIST)+4},"BUY")'],
    ['SELL', f'=COUNTIF(P5:P{len(WATCHLIST)+4},"SELL")'],
    ['HOLD', f'=COUNTIF(P5:P{len(WATCHLIST)+4},"HOLD")'],
    ['Buy/Sell Ratio', f'=IFERROR(B{sr+2}/B{sr+3},"")'],
    ['', ''],
    ['Best Performer', f'=IFERROR(INDEX(B5:B{len(WATCHLIST)+4},MATCH(MAX(G5:G{len(WATCHLIST)+4}),G5:G{len(WATCHLIST)+4},0)),"")'],
    ['Worst Performer', f'=IFERROR(INDEX(B5:B{len(WATCHLIST)+4},MATCH(MIN(G5:G{len(WATCHLIST)+4}),G5:G{len(WATCHLIST)+4},0)),"")'],
    ['', ''],
    ['Avg Score v2', f'=IFERROR(AVERAGE(O5:O{len(WATCHLIST)+4}),"")'],
    ['Avg ARA Distance %', f'=IFERROR(AVERAGE(R5:R{len(WATCHLIST)+4}),"")'],
]

ws_dash.update(range_name=f'A{sr}', values=summary_rows, value_input_option='USER_ENTERED')
print(f"  Summary at row {sr}: {len(summary_rows)} rows")

print("\n✅ Done! Now update .env and run the feed.")
