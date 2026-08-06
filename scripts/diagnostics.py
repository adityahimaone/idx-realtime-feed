#!/usr/bin/env python3
"""Canonical diagnostics tool — consolidated from the legacy root check_*.py scripts.

Subcommands:
  --dashboard  Check old Dashboard [Stockbit] + All Tickers formulas (was check_dashboard.py)
  --irw        Check computed values vs formulas on Dashboard [IRW] (was check_irw.py)
  --sheets     Compare new vs old spreadsheets (was check_sheets.py)
  --staging    Check MAS staging + new sheet Realtime_Watchlist (was check_staging.py)
"""
import argparse
import json
import sys
from pathlib import Path

import gspread
from google.oauth2.credentials import Credentials

STAGING = "1WOPSU6JLoinVUexwJzbB-vpQS-4hoDp8TskP3GcKYaE"
NEW_SHEET = "1vOMj5p-X1GAZEAd4Hp_RoSgYtauBiCKF9RW7GRHVxHM"
OLD_SHEET = "1wr2f6drQBqBUxikdJqSp1YVPaHF13qX0V3c7p4hkw5U"


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


def diag_dashboard(gc: gspread.Client) -> None:
    old = gc.open_by_key(OLD_SHEET)
    ws = old.worksheet("Dashboard [Stockbit]")
    vals = ws.get_all_values()
    print(f"Dashboard [Stockbit]: {len(vals)} rows x {len(vals[0]) if vals else 0} cols")
    for i, row in enumerate(vals[:30]):
        print(f"  Row {i + 1}: {row[:8]}")

    ws2 = old.worksheet("Alpha_Watchlist")
    vals2 = ws2.get_all_values()
    print(f"\nAlpha_Watchlist: {len(vals2)} rows")
    for row in vals2[:5]:
        print(f"  {row[:5]}")

    new = gc.open_by_key(NEW_SHEET)
    at = new.worksheet("All Tickers")
    formulas = [at.cell(2, c).value for c in range(1, 61)]
    print(f"\nAll Tickers Row 2 formulas (first 30):")
    for i, f in enumerate(formulas[:30]):
        print(f"  Col {i + 1}: {str(f)[:80]}")


def diag_irw(gc: gspread.Client) -> None:
    sh = gc.open_by_key(STAGING)
    ws = sh.worksheet("Dashboard [IRW]")
    req = ws.spreadsheet.values_get(ws.title, params={
        "valueRenderOption": "FORMATTED_VALUE",
        "majorDimension": "ROWS",
    })
    vals = req.get("values", [])
    print(f"Total rows: {len(vals)}")
    for r in vals[:6]:
        if not r:
            continue
        ticker = r[0] if len(r) > 0 else "?"
        rec = r[6] if len(r) > 6 else "?"
        risk = r[7] if len(r) > 7 else "?"
        tp = r[9] if len(r) > 9 else "?"
        sl = r[10] if len(r) > 10 else "?"
        price = r[1] if len(r) > 1 else "?"
        print(f"  {ticker}: price={price} rec={rec} risk={risk} tp={tp} sl={sl}")
    print()
    for r in vals[-12:]:
        if r and len(r) > 0 and any(x.strip() for x in r[:2]):
            print(f"  {r[0]}: {r[1] if len(r) > 1 else ''}")


def diag_sheets(gc: gspread.Client) -> None:
    sh = gc.open_by_key(NEW_SHEET)
    old_sh = gc.open_by_key(OLD_SHEET)
    print("=== NEW SHEET ===")
    print("Current sheets:", [ws.title for ws in sh.worksheets()])
    print("\n=== OLD SHEET (staging) ===")
    print("Sheets:", [ws.title for ws in old_sh.worksheets()])
    for name in ["Alpha_Watchlist", "Realtime_Watchlist"]:
        try:
            ws = old_sh.worksheet(name)
            vals = ws.get_all_values()
            print(f"  {name}: {len(vals)} rows")
            if vals:
                print(f"    Header: {vals[0][:5]}")
                if len(vals) > 1:
                    print(f"    Row 2: {vals[1][:5]}")
        except gspread.WorksheetNotFound:
            print(f"  {name}: not found")
    ws_at = sh.worksheet("All Tickers")
    header = ws_at.row_values(1)
    print(f"\nAll Tickers columns ({len(header)}): {header}")


def diag_staging(gc: gspread.Client) -> None:
    print("=== MAS STAGING SHEET ===")
    sh1 = gc.open_by_key(STAGING)
    print("Sheets:", [ws.title for ws in sh1.worksheets()])
    for name in ["Realtime_Watchlist", "Realtime_Watchlist [IRW]"]:
        try:
            ws = sh1.worksheet(name)
            vals = ws.get_all_values()
            print(f"{name}: {len(vals)} rows x {len(vals[0]) if vals else 0} cols")
            if vals:
                print(f"  Header: {vals[0]}")
                for r in vals[1:4]:
                    print(f"  {r[0]}: date={r[-1] if len(r) > 13 else 'N/A'}")
        except gspread.WorksheetNotFound:
            print(f"{name}: not found")

    print("\n=== NEW SHEET ===")
    sh2 = gc.open_by_key(NEW_SHEET)
    print("Sheets:", [ws.title for ws in sh2.worksheets()])
    try:
        ws2 = sh2.worksheet("Realtime_Watchlist")
        vals2 = ws2.get_all_values()
        print(f"Realtime_Watchlist: {len(vals2)} rows x {len(vals2[0]) if vals2 else 0} cols")
        if vals2:
            print(f"  Header: {vals2[0]}")
            for r in vals2[1:4]:
                print(f"  {r[0]}: date={r[-1] if len(r) > 13 else 'N/A'}")
    except gspread.WorksheetNotFound:
        print("Realtime_Watchlist: not found")


def main() -> None:
    parser = argparse.ArgumentParser(description="StockPick IDX diagnostics")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dashboard", action="store_true", help="Check Dashboard [Stockbit] + All Tickers formulas")
    group.add_argument("--irw", action="store_true", help="Check Dashboard [IRW] computed values")
    group.add_argument("--sheets", action="store_true", help="Compare new vs old spreadsheets")
    group.add_argument("--staging", action="store_true", help="Check MAS staging + new sheet Realtime_Watchlist")
    args = parser.parse_args()

    gc = _auth()
    if args.dashboard:
        diag_dashboard(gc)
    elif args.irw:
        diag_irw(gc)
    elif args.sheets:
        diag_sheets(gc)
    elif args.staging:
        diag_staging(gc)


if __name__ == "__main__":
    main()
