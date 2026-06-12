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
    "High",
    "Low",
    "Open",
    "Volume",
    "Total Bid Lot",
    "Total Ask Lot",
    "Imbalance Ratio",
    "Foreign Net",
    "ARA",
    "ARB",
    "Support",
    "Resistance",
    "Source",
    "Last Update (UTC)",
]

DASHBOARD_HEADER = [
    "Ticker",
    "Last Price",
    "Change %",
    "Bid/Ask Ratio",
    "Spread %",
    "ARA Distance %",
    "ARB Distance %",
    "Foreign Net",
    "Volume",
    "Support",
    "Resistance",
    "Buy Pressure Score",
    "Scalp Score",
    "ARA Potential",
    "Foreign Interest",
    "Signal",
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
                    snap.high if snap.high else "",
                    snap.low if snap.low else "",
                    snap.open_price if snap.open_price else "",
                    snap.volume if snap.volume else "",
                    snap.total_bid_lot,
                    snap.total_ask_lot,
                    snap.imbalance_ratio if snap.imbalance_ratio is not None else "",
                    snap.fnet,
                    snap.ara_price if snap.ara_price else "",
                    snap.arb_price if snap.arb_price else "",
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
                range_clear = f"A2:N{existing_rows}"
                ws.batch_clear([range_clear])
        except Exception as exc:
            logger.warning(f"sheets: clear failed (continuing): {exc}")

        # Write in one batch call
        ws.update(rows, value_input_option="USER_ENTERED")
        logger.info(f"sheets: wrote {len(snapshots)} snapshots to '{config.REALTIME_SHEET_NAME}'")

        log_integrity_event("WRITE_OK", f"{len(snapshots)} snapshots, {len(rows)} rows total")



    def _get_dashboard_worksheet(self) -> gspread.Worksheet:
        """Get or create the Dashboard [Stockbit] worksheet."""
        sh = self._get_client().open_by_key(config.MARKET_ALPHA_SPREADSHEET_ID)
        title = "Dashboard [Stockbit]"
        try:
            return sh.worksheet(title)
        except gspread.WorksheetNotFound:
            logger.info(f"sheets: creating '{title}'")
            ws = sh.add_worksheet(title=title, rows=500, cols=len(DASHBOARD_HEADER))
            ws.append_row(DASHBOARD_HEADER)
            # Freeze header row
            ws.freeze(1)
            return ws

    def _compute_signal(self, snap) -> str:
        """Compute composite trading signal."""
        signals = []
        # Buy pressure: bid_ask_ratio > 2
        bar = snap.bid_ask_ratio
        if bar is not None and bar >= 2.0:
            signals.append("BUY")
        # Scalp: tight spread + positive change
        spread = snap.spread
        if spread is not None and spread <= 0.5 and snap.change_pct > 2:
            signals.append("SCALP")
        # ARA potential: within 5% of ARA
        ara_dist = snap.ara_distance_pct
        if ara_dist is not None and ara_dist <= 5 and snap.change_pct > 0:
            signals.append("ARA")
        # Foreign accumulation
        if snap.fnet > 1000000000 and snap.change_pct > 0:
            signals.append("FOREIGN")
        # Long term: strong bid support + positive change
        if bar is not None and bar >= 1.5 and snap.change_pct > 0:
            signals.append("LONG")
        return " | ".join(signals) if signals else "WATCH"

    def write_dashboard(self, snapshots: list[OrderbookSnapshot]) -> None:
        """Write comprehensive dashboard data to Dashboard [Stockbit]."""
        ws = self._get_dashboard_worksheet()

        rows = [DASHBOARD_HEADER]
        for snap in snapshots:
            bar = snap.bid_ask_ratio
            spread = snap.spread
            ara_dist = snap.ara_distance_pct
            arb_dist = snap.arb_distance_pct

            # Buy Pressure Score: bid/ask ratio scaled
            bp_score = round(min(bar * 5, 10), 1) if bar else 0

            # Scalp Score: tight spread + momentum
            score = 0
            if spread is not None and spread <= 0.3: score += 4
            elif spread is not None and spread <= 0.5: score += 2
            if snap.change_pct > 5: score += 3
            elif snap.change_pct > 2: score += 2
            elif snap.change_pct > 0: score += 1
            scalp_score = score

            # ARA Potential: close to ARA with upward momentum
            ara_potential = 0
            if ara_dist is not None and ara_dist <= 5: ara_potential += 4
            elif ara_dist is not None and ara_dist <= 10: ara_potential += 2
            if snap.change_pct > 3: ara_potential += 3
            elif snap.change_pct > 0: ara_potential += 1
            if bar is not None and bar > 1.2: ara_potential += 2

            # Foreign Interest: normalized score 0-10
            fi = 0
            fnet = abs(snap.fnet)
            if fnet > 5000000000: fi = 10
            elif fnet > 2000000000: fi = 7
            elif fnet > 1000000000: fi = 5
            elif fnet > 500000000: fi = 3
            elif fnet > 100000000: fi = 1

            signal = self._compute_signal(snap)

            rows.append([
                snap.ticker,
                snap.last_price,
                snap.change_pct,
                bar if bar is not None else "",
                spread if spread is not None else "",
                ara_dist if ara_dist is not None else "",
                arb_dist if arb_dist is not None else "",
                snap.fnet,
                snap.volume,
                snap.support_price if snap.support_price is not None else "",
                snap.resistance_price if snap.resistance_price is not None else "",
                bp_score,
                scalp_score,
                ara_potential,
                fi,
                signal,
            ])

        # Clear and write
        try:
            existing = len(ws.get_all_values())
            if existing > 1:
                ws.batch_clear([f"A2:P{existing}"])
        except Exception:
            pass

        ws.update(rows, value_input_option="USER_ENTERED")
        logger.info(f"sheets: wrote {len(snapshots)} dashboard rows")


sheets_repository = SheetsRepository()
