#!/usr/bin/env python3
"""Canonical Google Sheets setup tool for StockPick IDX.

Consolidates the legacy root-level setup scripts:

  --full       Dashboard [IRW] with formulas (was setup_irw.py)
  --computed   Dashboard [IRW] computed in Python, no formulas (was setup_irw_computed.py)
  --watchlists Alpha_Watchlist + Dashboard [stockbit] (was setup_sheets_final.py)
  --deformula  Scan a worksheet for =GOOGLEFINANCE(...) cells and replace
               them with the last cached value (mutates the live sheet).

Auth uses ~/.hermes/google_token.json (same as the legacy scripts).
"""
import argparse
import json
import sys
import time
from pathlib import Path

import gspread
from google.oauth2.credentials import Credentials

STAGING = "1WOPSU6JLoinVUexwJzbB-vpQS-4hoDp8TskP3GcKYaE"
NEW_SHEET = "1vOMj5p-X1GAZEAd4Hp_RoSgYtauBiCKF9RW7GRHVxHM"

WATCHLIST = [
    "ADRO", "ANTM", "ARCI", "ASII", "BBCA", "BBNI", "BBRI", "BMRI", "BNGA",
    "BREN", "BRPT", "BULL", "CDIA", "EMAS", "ESSA", "FOLK", "GTSI", "ITMG",
    "MBMA", "PGAS", "PMJS", "PSAB", "TLKM", "TOSK", "UNTR",
]


def _auth() -> gspread.Client:
    token_path = Path.home() / ".hermes" / "google_token.json"
    if not token_path.exists():
        sys.exit(f"Auth file not found: {token_path}")
    token_data = json.loads(token_path.read_text())
    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


def vlookup(ticker_row: int, sheet_col: int) -> str:
    """VLOOKUP formula; col index relative to range starting at B."""
    return f'=IFERROR(VLOOKUP(B{ticker_row},\'All Tickers\'!B:BH,{sheet_col - 1},FALSE),"")'


def setup_watchlists(gc: gspread.Client) -> None:
    """Alpha_Watchlist + Dashboard [stockbit] in the Market Alpha Scout sheet."""
    sh = gc.open_by_key(NEW_SHEET)

    print("=== Alpha_Watchlist ===")
    try:
        ws = sh.worksheet("Alpha_Watchlist")
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet("Alpha_Watchlist", rows=50, cols=8)

    alpha_rows = [["Ticker", "Company Name", "Sector", "Last Price", "Change %", "Volume", "MarketCap", "PE"]]
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
    ws.update(range_name="A1", values=alpha_rows, value_input_option="USER_ENTERED")
    print(f"  Alpha_Watchlist: {len(alpha_rows)} rows")
    time.sleep(2)

    print("\n=== Dashboard [stockbit] ===")
    try:
        ws_dash = sh.worksheet("Dashboard [stockbit]")
        ws_dash.clear()
    except gspread.WorksheetNotFound:
        ws_dash = sh.add_worksheet("Dashboard [stockbit]", rows=60, cols=20)

    ws_dash.update_acell("A1", "📊 DASHBOARD [STOCKBIT] — Realtime Watchlist Analysis")
    ws_dash.update_acell("A2", f'Generated: {time.strftime("%Y-%m-%d %H:%M")} WIB | Data: Stockbit Feed + Market Alpha Scout')

    dash_headers = [
        "No", "Ticker", "Company", "Sector", "Trend", "Last Price", "Change %",
        "Volume", "Vol Ratio", "MA20", "MA50", "MA200", "RSI14", "RSI Signal",
        "Score v2", "Final Signal", "Recommendation", "ARA Distance %", "Notes",
    ]
    ws_dash.update("A4:S4", [dash_headers])

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
            f'=IF(P{idx}="STRONG_BUY","🔥 STRONG BUY",IF(P{idx}="BUY","✅ BUY",IF(AND(M{idx}>70,P{idx}="SELL"),"⚠️ OVERBOUGHT - JUAL",IF(AND(M{idx}<30,P{idx}="BUY"),"💎 OVERSOLD - BELI",IF(P{idx}="SELL","🔴 SELL",IF(P{idx}="HOLD","⏸️ HOLD","❓ WAIT"))))))',
            vlookup(idx, 57),           # R: ARA Distance % (BE=57)
            f'=IF(G{idx}>5,"🔺Gain >5%",IF(G{idx}<-3,"🔻Loss >3%",IF(N{idx}="OVERBOUGHT","⚠️ RSI Overbought",IF(N{idx}="OVERSOLD","💡 RSI Oversold",""))))',
        ])
    ws_dash.update(range_name="A5", values=dash_rows, value_input_option="USER_ENTERED")
    print(f"  Dashboard: {len(dash_rows)} ticker rows")
    time.sleep(1)

    sr = len(WATCHLIST) + 7
    summary_rows = [
        ["📋 SUMMARY", ""],
        ["STRONG BUY", f'=COUNTIF(P5:P{len(WATCHLIST) + 4},"STRONG_BUY")'],
        ["BUY", f'=COUNTIF(P5:P{len(WATCHLIST) + 4},"BUY")'],
        ["SELL", f'=COUNTIF(P5:P{len(WATCHLIST) + 4},"SELL")'],
        ["HOLD", f'=COUNTIF(P5:P{len(WATCHLIST) + 4},"HOLD")'],
        ["Buy/Sell Ratio", f'=IFERROR(B{sr + 2}/B{sr + 3},"")'],
        ["", ""],
        ["Best Performer", f'=IFERROR(INDEX(B5:B{len(WATCHLIST) + 4},MATCH(MAX(G5:G{len(WATCHLIST) + 4}),G5:G{len(WATCHLIST) + 4},0)),"")'],
        ["Worst Performer", f'=IFERROR(INDEX(B5:B{len(WATCHLIST) + 4},MATCH(MIN(G5:G{len(WATCHLIST) + 4}),G5:G{len(WATCHLIST) + 4},0)),"")'],
        ["", ""],
        ["Avg Score v2", f'=IFERROR(AVERAGE(O5:O{len(WATCHLIST) + 4}),"")'],
        ["Avg ARA Distance %", f'=IFERROR(AVERAGE(R5:R{len(WATCHLIST) + 4}),"")'],
    ]
    ws_dash.update(range_name=f"A{sr}", values=summary_rows, value_input_option="USER_ENTERED")
    print(f"  Summary at row {sr}: {len(summary_rows)} rows")
    print("\n✅ Done! Now update .env and run the feed.")


def _read_realtime_watchlist(sh) -> tuple[list[str], dict]:
    """Read tickers + values from 'Realtime_Watchlist [IRW]'."""
    ws_rw = sh.worksheet("Realtime_Watchlist [IRW]")
    rw_vals = ws_rw.get_all_values()
    rw_map: dict[str, dict] = {}
    for row in rw_vals[1:]:
        if not row or not row[0].strip():
            continue
        t = row[0].strip().upper()
        try:
            rw_map[t] = {
                "price": float(row[1]) if len(row) > 1 and row[1] else 0,
                "chg": float(row[2]) if len(row) > 2 and row[2] else 0,
                "high": float(row[3]) if len(row) > 3 and row[3] else 0,
                "low": float(row[4]) if len(row) > 4 and row[4] else 0,
                "open": float(row[5]) if len(row) > 5 and row[5] else 0,
                "vol": int(float(row[6])) if len(row) > 6 and row[6] else 0,
                "bid_lot": int(float(row[7])) if len(row) > 7 and row[7] else 0,
                "ask_lot": int(float(row[8])) if len(row) > 8 and row[8] else 0,
                "fnet": int(float(row[10])) if len(row) > 10 and row[10] else 0,
                "support": float(row[13]) if len(row) > 13 and row[13] else 0,
                "resistance": float(row[14]) if len(row) > 14 and row[14] else 0,
            }
        except (ValueError, IndexError):
            continue
    return sorted(rw_map.keys()), rw_map


def setup_irw_full(gc: gspread.Client) -> None:
    """Dashboard [IRW] with formulas referencing Realtime_Watchlist [IRW] + All Tickers."""
    sh = gc.open_by_key(STAGING)
    ws_rw = sh.worksheet("Realtime_Watchlist [IRW]")
    tickers_raw = ws_rw.col_values(1)[1:]
    tickers = [t.strip().upper() for t in tickers_raw if t.strip()]
    print(f"\nWatchlist tickers: {len(tickers)}")

    try:
        ws_dash = sh.worksheet("Dashboard [IRW]")
        ws_dash.clear()
    except gspread.WorksheetNotFound:
        ws_dash = sh.add_worksheet(title="Dashboard [IRW]", rows=150, cols=25)
    print("  Created/cleared 'Dashboard [IRW]'")

    dash_header = [
        "No", "Ticker", "Last Price", "Change %", "Volume", "Bid Lot", "Ask Lot",
        "Bid/Ask Ratio", "Support", "Resistance", "Score v2", "Final Signal",
        "RSI", "MA20", "MA50", "Trend", "ARA Dist %", "ARB Dist %",
        "Recommendation", "Risk Level", "Entry Zone", "TP", "SL", "Notes", "Last Update",
    ]
    ws_dash.update("A1:Y1", [dash_header])

    rows = []
    for idx, t in enumerate(tickers, start=2):
        rw_ref = "'Realtime_Watchlist [IRW]'"
        at_ref = "'All Tickers'"
        price = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,2,FALSE),"")'
        chg = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,3,FALSE),"")'
        vol = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,7,FALSE),"")'
        bid = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,8,FALSE),"")'
        ask = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,9,FALSE),"")'
        bar = f'=IFERROR(ROUND(VLOOKUP(B{idx},{rw_ref}!A:Q,8,FALSE)/VLOOKUP(B{idx},{rw_ref}!A:Q,9,FALSE),2),"")'
        sup = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,14,FALSE),"")'
        res = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,15,FALSE),"")'
        update = f'=IFERROR(VLOOKUP(B{idx},{rw_ref}!A:Q,17,FALSE),"")'
        score = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,42-1,FALSE),"")'
        signal = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,44-1,FALSE),"")'
        rsi = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,50-1,FALSE),"")'
        ma20 = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,32-1,FALSE),"")'
        ma50 = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,33-1,FALSE),"")'
        trend = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,40-1,FALSE),"")'
        ara_d = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,57-1,FALSE),"")'
        arb_d = f'=IFERROR(VLOOKUP(B{idx},{at_ref}!B:BH,58-1,FALSE),"")'

        rec = (
            f'=IF({signal}="STRONG_BUY","STRONG BUY",'
            f'IF({signal}="BUY",'
            f'IF({rsi}<40,"✅ BUY - OVERSOLD",'
            f'IF(AND({rsi}>=40,{rsi}<70),"✅ BUY","")),'
            f'IF(OR({signal}="SELL",AND({rsi}>70,{signal}="HOLD")),"🔴 SELL",'
            f'IF({signal}="HOLD","⏸ HOLD","❓ WAIT"))))'
        )
        risk = (
            f'=IF({signal}="STRONG_BUY","🔥Aggressive",'
            f'IF(AND({signal}="BUY",IFERROR({rsi}<50,FALSE)),"⚡Moderate",'
            f'IF({signal}="BUY","💧Low Risk","N/A")))'
        )
        entry = (
            f'=IF({signal}="STRONG_BUY",'
            f'IF(AND({price}>0,{sup}>0),"Market - Limit @ {sup}","Market"),'
            f'IF({signal}="BUY",'
            f'IF(AND({price}>0,{sup}>0,{price}>{sup}*1.05),"Wait pullback to {sup}","Market"),'
            f'"Wait"))'
        )
        tp = (
            f'=IF({risk}="🔥Aggressive",'
            f'IFERROR(ROUND({res}*1.02,0),"N/A"),'
            f'IF({risk}="⚡Moderate",'
            f'IFERROR(ROUND({res}*1.01,0),"N/A"),'
            f'IF({risk}="💧Low Risk",'
            f'IFERROR(ROUND({price}*1.05,0),"N/A"),"N/A")))'
        )
        sl = (
            f'=IF({risk}="🔥Aggressive",'
            f'IFERROR(ROUND({sup}*0.98,0),"N/A"),'
            f'IF({risk}="⚡Moderate",'
            f'IFERROR(ROUND({price}*0.95,0),"N/A"),'
            f'IF({risk}="💧Low Risk",'
            f'IFERROR(ROUND({price}*0.92,0),"N/A"),"N/A")))'
        )
        notes = (
            f'=IF({rec}="STRONG BUY","🔥 High conviction",'
            f'IF({rec}="✅ BUY - OVERSOLD","💎 Oversold bounce play",'
            f'IF({rec}="🔴 SELL","🔻 Avoid / take profit",'
            f'IF({rsi}>70,"⚠ Overbought",'
            f'IF({bar}>1.2,"📊 Heavy demand",'
            f'IF({vol}>500000000,"💹 High volume",""))))))'
        )
        rows.append([idx - 1, t, price, chg, vol, bid, ask, bar, sup, res,
                     score, signal, rsi, ma20, ma50, trend, ara_d, arb_d,
                     rec, risk, entry, tp, sl, notes, update])

    batch_size = 10
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        start_row = i + 2
        ws_dash.update(f"A{start_row}", batch, value_input_option="USER_ENTERED")
        time.sleep(1.5)
        print(f"  Wrote rows {start_row}-{start_row + len(batch) - 1}")

    sr = len(tickers) + 4
    summary = [
        ["📊 SUMMARY [IRW]"],
        ["Total Tickers", f"={len(tickers)}"],
        ["STRONG BUY", f'=COUNTIF(S2:S{len(tickers) + 1},"*STRONG BUY*")'],
        ["BUY (Total)", f'=COUNTIF(S2:S{len(tickers) + 1},"✅ BUY*")'],
        ["SELL", f'=COUNTIF(S2:S{len(tickers) + 1},"🔴 SELL*")'],
        ["HOLD/WAIT", f'=COUNTIF(S2:S{len(tickers) + 1},"*HOLD*")+COUNTIF(S2:S{len(tickers) + 1},"*WAIT*")'],
        ["Aggressive", f'=COUNTIF(T2:T{len(tickers) + 1},"*Aggressive*")'],
        ["Moderate", f'=COUNTIF(T2:T{len(tickers) + 1},"*Moderate*")'],
        ["Low Risk", f'=COUNTIF(T2:T{len(tickers) + 1},"*Low Risk*")'],
        ["", ""],
        ["Scalp Pick", f'=IFERROR(INDEX(B2:B{len(tickers) + 1},MATCH(MAX(K2:K{len(tickers) + 1}),K2:K{len(tickers) + 1},0)),"")'],
        ["Long Term Pick", f'=IFERROR(INDEX(B2:B{len(tickers) + 1},MATCH(MAX(G2:G{len(tickers) + 1}),G2:G{len(tickers) + 1},0)),"")'],
    ]
    ws_dash.update(f"A{sr}", summary, value_input_option="USER_ENTERED")
    print(f"\nSummary at row {sr}")

    print("\n=== Final sheets ===")
    for i, ws in enumerate(sh.worksheets()):
        print(f"  {i}: {ws.title}")
    print("\n✅ Done! Dashboard [IRW] with buy/sell recs, TP/SL created.")


def setup_irw_computed(gc: gspread.Client) -> None:
    """Dashboard [IRW] computed in Python, no formulas."""
    sh = gc.open_by_key(STAGING)
    tickers, rw_map = _read_realtime_watchlist(sh)
    print(f"Tickers: {len(tickers)}")

    try:
        ws_dash = sh.worksheet("Dashboard [IRW]")
        ws_dash.clear()
    except gspread.WorksheetNotFound:
        ws_dash = sh.add_worksheet("Dashboard [IRW]", rows=150, cols=25)

    cols = ["Ticker", "Last Price", "Chg %", "Volume", "Demand", "Trend",
            "Rec", "Risk", "Entry Zone", "TP", "SL", "Notes"]
    ws_dash.update([cols], "A1:L1")

    rows = []
    for t in tickers:
        d = rw_map[t]
        p, c, v = d["price"], d["chg"], d["vol"]
        bid, ask = d["bid_lot"], d["ask_lot"]
        sup, res = d["support"], d["resistance"]

        dem = f"{round(min(bid / ask, 10), 2)}x" if ask > 0 else "-"
        trend = "Up 🚀" if c > 2 else ("Mild ↗" if c > 0 else "Down ↘")
        rec = "🔥 BUY" if c > 3 else ("✅ BUY" if c > 0 else ("🔴 SELL" if c < -3 else "⏸ HOLD"))
        risk = "🔥 Aggressive" if c > 5 else ("⚡ Moderate" if c > 0 else "💧 Low Risk")
        entry = "Market" if c > 0 else "Wait Pullback"

        if c > 5:
            tp, sl = round(p * 1.07), round(p * 0.97)
            notes = "High Momentum"
        elif c > 0:
            tp, sl = round(p * 1.05), round(p * 0.95)
            notes = "Accumulation"
        elif c < -3:
            tp, sl = round(p * 1.03), round(p * 0.93)
            notes = "Avoid"
        else:
            tp, sl = round(p * 1.03), round(p * 0.93)
            notes = "Sideways"

        rows.append([t, p, c, v, dem, trend, rec, risk, entry, tp, sl, notes])

    for i in range(0, len(rows), 10):
        batch = rows[i:i + 10]
        start = i + 2
        rng = f"A{start}:L{start + len(batch) - 1}"
        ws_dash.update(batch, rng, value_input_option="USER_ENTERED")
        time.sleep(0.5)

    sr = len(tickers) + 4
    summary = [
        ["📊 RECAP"], ["", ""],
        ["🔥 Strong Buy", sum(1 for r in rows if r[6] == "🔥 BUY")],
        ["✅ Buy", sum(1 for r in rows if r[6] == "✅ BUY")],
        ["⏸ Hold/Wait", sum(1 for r in rows if r[6] == "⏸ HOLD")],
        ["🔴 Sell", sum(1 for r in rows if r[6] == "🔴 SELL")],
        ["", ""],
        ["🔥 Aggressive (Scalp)", sum(1 for r in rows if "Aggressive" in r[7])],
        ["⚡ Moderate (Swing)", sum(1 for r in rows if "Moderate" in r[7])],
        ["💧 Low Risk (Long)", sum(1 for r in rows if "Low Risk" in r[7])],
        ["", ""],
        ["Top Scalp", rows[0][0] if rows else "-"],
        ["Watchlist Count", len(tickers)],
    ]
    ws_dash.update(summary, f"A{sr}", value_input_option="USER_ENTERED")

    vals = ws_dash.get_all_values()
    print(f"\nDashboard [IRW]: {len(vals)} rows")
    for r in vals[1:6]:
        print(f"  {r[0]}: p={r[1]} chg={r[2]} rec={r[6]} risk={r[7]} tp={r[9]} sl={r[10]}")
    print("\nDone! All values computed in Python, no formula dependency.")


def deformula(gc: gspread.Client, sheet_id: str, worksheet: str) -> None:
    """Replace =GOOGLEFINANCE(...) cells with their last cached (formatted) value.

    This mutates the live sheet — intended as a one-time manual migration step.
    """
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet(worksheet)
    vals = ws.get_all_values(value_render_option="FORMATTED_VALUE")
    replaced = 0
    ranges = []
    for r_idx, row in enumerate(vals, start=1):
        for c_idx, cell in enumerate(row, start=1):
            if isinstance(cell, str) and cell.lstrip().startswith("=GOOGLEFINANCE("):
                ranges.append((r_idx, c_idx))

    if not ranges:
        print(f"No =GOOGLEFINANCE(...) cells found in '{worksheet}'.")
        return

    print(f"Found {len(ranges)} GOOGLEFINANCE cells in '{worksheet}'.")
    confirm = input("Replace them with the last cached values? Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return

    # Read raw (formula) vs formatted values to map formula -> cached value.
    raw_vals = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    updates = {}
    for r_idx, row in enumerate(raw_vals, start=1):
        for c_idx, cell in enumerate(row, start=1):
            if isinstance(cell, str) and cell.lstrip().startswith("=GOOGLEFINANCE("):
                formatted = vals[r_idx - 1][c_idx - 1] if r_idx - 1 < len(vals) else ""
                updates[(r_idx, c_idx)] = formatted
                replaced += 1

    for (r_idx, c_idx), value in updates.items():
        ws.update_cell(r_idx, c_idx, value)
        time.sleep(0.3)
        print(f"  Replaced {worksheet}!R{r_idx}C{c_idx} -> {value!r}")

    print(f"\n✅ Replaced {replaced} GOOGLEFINANCE formulas with cached values.")


def main() -> None:
    parser = argparse.ArgumentParser(description="StockPick IDX Google Sheets setup tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true", help="Dashboard [IRW] with formulas")
    group.add_argument("--computed", action="store_true", help="Dashboard [IRW] computed in Python")
    group.add_argument("--watchlists", action="store_true", help="Alpha_Watchlist + Dashboard [stockbit]")
    group.add_argument("--deformula", action="store_true",
                       help="Replace =GOOGLEFINANCE cells with cached values (mutates sheet)")
    parser.add_argument("--sheet-id", default=STAGING, help="Spreadsheet ID for --deformula")
    parser.add_argument("--worksheet", default="All Tickers", help="Worksheet name for --deformula")
    args = parser.parse_args()

    gc = _auth()
    if args.full:
        setup_irw_full(gc)
    elif args.computed:
        setup_irw_computed(gc)
    elif args.watchlists:
        setup_watchlists(gc)
    elif args.deformula:
        deformula(gc, args.sheet_id, args.worksheet)


if __name__ == "__main__":
    main()
