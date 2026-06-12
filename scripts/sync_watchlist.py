"""
Sync Stockbit watchlist API -> Google Sheets Alpha_Watchlist.
Run once, then sync_service picks it up.

Usage: python scripts/sync_watchlist.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import gspread
from google.oauth2.credentials import Credentials

from core.config import config
from core.logger import logger

WATCHLIST_URL = "https://exodus.stockbit.com/watchlist/2624360?page=1&limit=100&setfincol=1"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_sheets_client() -> gspread.Client:
    token_path = Path.home() / ".hermes" / "google_token.json"
    if token_path.exists():
        with open(token_path) as f:
            td = json.load(f)
        scopes = td.get("scopes") or SCOPES
        if isinstance(scopes, str):
            scopes = scopes.split()
        creds = Credentials(
            token=td["token"],
            refresh_token=td.get("refresh_token"),
            token_uri=td.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=td["client_id"],
            client_secret=td["client_secret"],
            scopes=scopes,
        )
        return gspread.authorize(creds)
    raise RuntimeError("No Google token found")


async def fetch_watchlist() -> list[dict]:
    import httpx
    token = open(".env").read().split("STOCKBIT_BEARER_TOKEN=")[1].split("\n")[0].strip()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            WATCHLIST_URL,
            headers={"Authorization": f"Bearer {token}",
                     "User-Agent": "Stockbit/5.5.0 (Android 14)"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"]["result"]


def write_to_sheet(results: list[dict]) -> None:
    gc = _get_sheets_client()
    sh = gc.open_by_key(config.MARKET_ALPHA_SPREADSHEET_ID)

    try:
        ws = sh.worksheet(config.WATCHLIST_SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=config.WATCHLIST_SHEET_NAME, rows=100, cols=3)
        ws.append_row(["Ticker", "Name", "Last Price"])

    # Build rows
    rows = [["Ticker", "Name", "Last Price", "Change", "Change %"]]
    for item in results:
        rows.append([
            item["symbol"],
            item.get("name", ""),
            item.get("last", ""),
            item.get("change", ""),
            item.get("percent", ""),
        ])

    # Clear and write
    try:
        existing = len(ws.get_all_values())
        if existing > 1:
            ws.batch_clear([f"A2:E{existing}"])
    except Exception:
        pass

    ws.update(rows, value_input_option="USER_ENTERED")
    logger.info(f"watchlist: synced {len(results)} tickers to {config.WATCHLIST_SHEET_NAME}")


async def main():
    print(f"Fetching watchlist from Stockbit...")
    results = await fetch_watchlist()
    print(f"Got {len(results)} tickers:")
    for item in results:
        print(f"  {item['symbol']:6s} {item.get('last', ''):>8s} {item.get('change', ''):>10s} {item.get('percent', ''):>6s}%")
    write_to_sheet(results)
    print("Done - written to Alpha_Watchlist sheet")


if __name__ == "__main__":
    asyncio.run(main())
