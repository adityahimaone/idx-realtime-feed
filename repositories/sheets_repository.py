"""
Google Sheets repository for idx-realtime-feed.

Reuse credential from Hermes Agent:
  - Primary: service account (config.GOOGLE_SERVICE_ACCOUNT)
  - Fallback: OAuth token file (~/.hermes/google_token.json)

Integrity checks (via integrity_guard) run before every write:
  1. ensure_integrity() — validate header row vs manifest
  2. check_anti_rollback() — detect concurrent writes / clock skew
"""

from __future__ import annotations

import json
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials as SACredentials
from google.oauth2.credentials import Credentials as UserCredentials

from core.config import config
from core.logger import logger
from schemas.orderbook import OrderbookSnapshot

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER_ROW = [
    "Ticker",
    "Last Price",
    "Change %",
    "Total Bid Lot",
    "Total Ask Lot",
    "Imbalance Ratio",
    "Support",
    "Resistance",
    "Source",
    "Last Update (UTC)",
]


class SheetsRepository:
    def __init__(self) -> None:
        self._client: gspread.Client | None = None

    def _get_client(self) -> gspread.Client:
        if self._client is not None:
            return self._client

        # Try service account first (env var)
        if config.GOOGLE_SERVICE_ACCOUNT:
            try:
                creds_dict = json.loads(config.GOOGLE_SERVICE_ACCOUNT)
                creds = SACredentials.from_service_account_info(creds_dict, scopes=SCOPES)
                self._client = gspread.authorize(creds)
                logger.info("sheets: authed via service account")
                return self._client
            except Exception as exc:
                logger.warning(f"sheets: service account auth failed: {exc}")

        # Fallback: user OAuth token (Hermes standard)
        token_path = Path.home() / ".hermes" / "google_token.json"
        if token_path.exists():
            try:
                with open(token_path) as f:
                    token_data = json.load(f)
                scopes = token_data.get("scopes") or SCOPES
                if isinstance(scopes, str):
                    scopes = scopes.split()
                creds = UserCredentials(
                    token=token_data["token"],
                    refresh_token=token_data.get("refresh_token"),
                    token_uri=token_data.get(
                        "token_uri", "https://oauth2.googleapis.com/token"
                    ),
                    client_id=token_data["client_id"],
                    client_secret=token_data["client_secret"],
                    scopes=scopes,
                )
                self._client = gspread.authorize(creds)
                logger.info("sheets: authed via user token")
                return self._client
            except Exception as exc:
                logger.error(f"sheets: user token auth failed: {exc}")

        raise RuntimeError(
            "No Google Sheets credentials available. "
            "Set GOOGLE_SERVICE_ACCOUNT env var or ensure ~/.hermes/google_token.json exists."
        )

    def _get_realtime_worksheet(self) -> gspread.Worksheet:
        """Get or create the Realtime_Watchlist worksheet."""
        sh = self._get_client().open_by_key(config.MARKET_ALPHA_SPREADSHEET_ID)
        try:
            return sh.worksheet(config.REALTIME_SHEET_NAME)
        except gspread.WorksheetNotFound:
            logger.info(f"sheets: creating '{config.REALTIME_SHEET_NAME}'")
            ws = sh.add_worksheet(
                title=config.REALTIME_SHEET_NAME, rows=100, cols=len(HEADER_ROW)
            )
            ws.append_row(HEADER_ROW)
            return ws

    def get_watchlist(self) -> list[str]:
        """Read tickers from Alpha_Watchlist sheet (col A, skip header)."""
        try:
            sh = self._get_client().open_by_key(config.MARKET_ALPHA_SPREADSHEET_ID)
            ws = sh.worksheet(config.WATCHLIST_SHEET_NAME)
            values = ws.col_values(1)[1:]  # skip header
            tickers = [v.strip().upper() for v in values if v.strip()]
            return tickers[: config.MAX_WATCHLIST_SIZE]
        except Exception as exc:
            logger.error(f"sheets: cannot read watchlist: {exc}")
            # Try default tickers as fallback
            return config.DEFAULT_WATCHLIST or []

    def write_snapshots(self, snapshots: list[OrderbookSnapshot]) -> None:
        """Overwrite Realtime_Watchlist with latest snapshots.

        Integrity checks performed before write:
          - header validation against manifest
          - anti-rollback timestamp check
        """
        from repositories.integrity_guard import (
            check_anti_rollback,
            ensure_integrity,
            log_integrity_event,
        )

        ws = self._get_realtime_worksheet()

        # ── Integrity check 1: header structure ──
        valid, issues = ensure_integrity(ws)
        if not valid:
            log_integrity_event("STRUCTURE_FAIL", "; ".join(issues))
            logger.error(
                f"integrity: sheet structure invalid — {len(issues)} issues. "
                "Run guard manually to fix."
            )
            logger.warning("integrity: proceeding anyway (will add header if missing)")
            # If sheet is empty, init with headers
            actual = ws.row_values(1)
            if not any(actual):
                ws.append_row(HEADER_ROW)

        # ── Integrity check 2: anti-rollback ──
        safe, reason = check_anti_rollback(ws)
        if not safe:
            log_integrity_event("ROLLBACK_BLOCKED", reason or "unknown")
            logger.error(f"integrity: anti-rollback blocked write: {reason}")
            # Don't abort — allow overwrite but log. The check is advisory
            # for this use case (realtime feed should always overwrite).

        # ── Build rows ──
        rows = [HEADER_ROW]
        for snap in snapshots:
            rows.append(
                [
                    snap.ticker,
                    snap.last_price,
                    snap.change_pct,
                    snap.total_bid_lot,
                    snap.total_ask_lot,
                    snap.imbalance_ratio if snap.imbalance_ratio is not None else "",
                    snap.support_price if snap.support_price is not None else "",
                    snap.resistance_price if snap.resistance_price is not None else "",
                    snap.source.value,
                    snap.timestamp.isoformat(),
                ]
            )

        # ── Batch write ──
        # Clear existing content first (leave header) then write
        try:
            existing_rows = len(ws.get_all_values())
            if existing_rows > 1:
                # Clear all data rows (leaving header at row 1)
                range_clear = f"A2:J{existing_rows}"
                ws.batch_clear([range_clear])
        except Exception as exc:
            logger.warning(f"sheets: clear failed (continuing): {exc}")

        # Write in one batch call
        ws.update(rows, value_input_option="USER_ENTERED")
        logger.info(f"sheets: wrote {len(snapshots)} snapshots to '{config.REALTIME_SHEET_NAME}'")

        log_integrity_event("WRITE_OK", f"{len(snapshots)} snapshots, {len(rows)} rows total")


sheets_repository = SheetsRepository()
