#!/usr/bin/env python3
"""
Standalone: rebuild Dashboard [IRW] + Dashboard Formula [IRW] + Market Recap [IRW]
from the current Realtime_Watchlist [IRW] data on the staging sheet.

Use this when:
- Sync daemon hasn't run in a while and dashboard is stale
- You manually edited the source sheet and want to refresh dashboard formulas
- You want an out-of-band refresh without waiting for the 45s cycle

Usage:
    python3 scripts/update_dashboard_irw.py
    python3 scripts/update_dashboard_irw.py --dry-run
    python3 scripts/update_dashboard_irw.py --ticker TPIA
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Make project root importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import config
from core.logger import logger
from repositories.sheets_repository import SheetsRepository
from schemas.orderbook import DataSource, OrderbookSnapshot, PriceLevel

STAGING_SHEET_NAME = "Realtime_Watchlist [IRW]"


def _parse_float(v, default: float = 0.0) -> float:
    try:
        if v in ("", None):
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _parse_int(v, default: int = 0) -> int:
    try:
        if v in ("", None):
            return default
        return int(float(v))
    except (ValueError, TypeError):
        return default


def _row_to_snapshot(row: list[str]) -> OrderbookSnapshot | None:
    """Convert a Realtime_Watchlist [IRW] row to an OrderbookSnapshot.

    Column layout (matches HEADER_ROW in sheets_repository.py):
      A: Ticker, B: Last Price, C: Change %, D: High, E: Low, F: Open,
      G: Volume, H: Total Bid Lot, I: Total Ask Lot, J: Imbalance Ratio,
      K: Foreign Net, L: ARA, M: ARB, N: Support, O: Resistance,
      P: Source, Q: Last Update (UTC)
    """
    if not row or not row[0].strip():
        return None

    ticker = row[0].strip().upper()
    last_price = _parse_float(row[1])
    change_pct = _parse_float(row[2])
    high = _parse_float(row[3])
    low = _parse_float(row[4])
    open_ = _parse_float(row[5])
    volume = _parse_float(row[6])
    bid_lot = _parse_int(row[7])
    ask_lot = _parse_int(row[8])
    fnet = _parse_float(row[10])
    ara = _parse_float(row[11])
    arb = _parse_float(row[12])
    support = _parse_float(row[13])
    resistance = _parse_float(row[14])
    source = row[15].strip() if len(row) > 15 and row[15] else "stockbit"
    ts_str = row[16] if len(row) > 16 and row[16] else None

    try:
        ts = datetime.fromisoformat(ts_str) if ts_str else datetime.utcnow()
    except (ValueError, TypeError):
        ts = datetime.utcnow()

    try:
        src = DataSource(source.lower())
    except ValueError:
        src = DataSource.STOCKBIT

    # Derive prev_close from last_price + change_pct so the model's
    # change_pct property stays consistent with what the source sheet shows.
    if change_pct != 0 and last_price > 0:
        prev_close = round(last_price / (1 + change_pct / 100), 2)
    else:
        prev_close = last_price

    # Synthesize a single-level orderbook per side so the model's
    # bid_ask_ratio / support_price / resistance_price / spread
    # properties resolve to the values already on the sheet.
    bid_levels = (
        [PriceLevel(price=support, lot=bid_lot, freq=1)]
        if support > 0 and bid_lot > 0
        else []
    )
    ask_levels = (
        [PriceLevel(price=resistance, lot=ask_lot, freq=1)]
        if resistance > 0 and ask_lot > 0
        else []
    )

    return OrderbookSnapshot(
        ticker=ticker,
        last_price=last_price,
        prev_close=prev_close,
        high=high,
        low=low,
        open_price=open_,
        volume=volume,
        fnet=fnet,
        ara_price=ara,
        arb_price=arb,
        source=src,
        timestamp=ts,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
    )


def fetch_snapshots_from_sheet(repo: SheetsRepository) -> list[OrderbookSnapshot]:
    """Read all rows from Realtime_Watchlist [IRW] and convert to snapshots."""
    sh = repo._get_client().open_by_key(config.MAS_STAGING_SPREADSHEET_ID)
    ws = sh.worksheet(STAGING_SHEET_NAME)
    rows = ws.get_all_values()
    if not rows or len(rows) < 2:
        logger.warning(f"update_dashboard: '{STAGING_SHEET_NAME}' is empty")
        return []

    snapshots: list[OrderbookSnapshot] = []
    for row in rows[1:]:
        snap = _row_to_snapshot(row)
        if snap is not None:
            snapshots.append(snap)
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh Dashboard [IRW] + Dashboard Formula [IRW] from Realtime_Watchlist [IRW]"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        help="Only refresh data for this ticker (filter)",
    )
    args = parser.parse_args()

    if not config.MAS_STAGING_SPREADSHEET_ID:
        logger.error("MAS_STAGING_SPREADSHEET_ID not set in .env")
        return 1

    repo = SheetsRepository()
    snapshots = fetch_snapshots_from_sheet(repo)
    if not snapshots:
        logger.error("No snapshots found in Realtime_Watchlist [IRW]")
        return 1

    if args.ticker:
        ticker = args.ticker.strip().upper()
        snapshots = [s for s in snapshots if s.ticker == ticker]
        if not snapshots:
            logger.error(f"Ticker {ticker} not found in {STAGING_SHEET_NAME}")
            return 1

    logger.info(f"update_dashboard: {len(snapshots)} tickers from '{STAGING_SHEET_NAME}'")
    for s in snapshots:
        logger.info(
            f"  {s.ticker}: p={s.last_price} chg={s.change_pct}% "
            f"bid={s.total_bid_lot} ask={s.total_ask_lot} "
            f"ara_d={s.ara_distance_pct} arb_d={s.arb_distance_pct}"
        )

    if args.dry_run:
        logger.info("DRY RUN — skipping write")
        return 0

    repo.write_dashboard(
        snapshots,
        sheet_id=config.MAS_STAGING_SPREADSHEET_ID,
        realtime_sheet_name=STAGING_SHEET_NAME,
    )
    logger.info(
        "update_dashboard: Dashboard [IRW] + Dashboard Formula [IRW] + Market Recap [IRW] refreshed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
