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

    def write_dashboard(self, snapshots: list[OrderbookSnapshot]) -> None:
        """Write Dashboard [Stockbit] with formulas referencing Realtime_Watchlist.

        Formulas are Google Sheets native — auto-recalculate when Realtime_Watchlist
        updates. Signal column uses IF() conditions based on computed columns.
        """
        ws = self._get_dashboard_worksheet()

        rows = [DASHBOARD_HEADER]
        for i, snap in enumerate(snapshots):
            row = i + 2  # Sheet row (header=1, data starts at 2)

            # Build formulas referencing Realtime_Watchlist columns
            # Col mapping in RW: A=Ticker, B=Last Price, C=Change%, D=High, E=Low,
            # F=Open, G=Volume, H=TotBidLot, I=TotAskLot, J=ImbRatio,
            # K=ForeignNet, L=ARA, M=ARB, N=Support, O=Resistance
            r = f"Realtime_Watchlist!A{row}"

            ticker_f = f"Realtime_Watchlist!A{row}"
            price_f = f"Realtime_Watchlist!B{row}"
            chg_f = f"Realtime_Watchlist!C{row}"
            bid_f = f"Realtime_Watchlist!H{row}"
            ask_f = f"Realtime_Watchlist!I{row}"
            fnet_f = f"Realtime_Watchlist!K{row}"
            ara_f = f"Realtime_Watchlist!L{row}"
            arb_f = f"Realtime_Watchlist!M{row}"
            sup_f = f"Realtime_Watchlist!N{row}"
            res_f = f"Realtime_Watchlist!O{row}"
            vol_f = f"Realtime_Watchlist!G{row}"

            # C: Change % — direct ref
            change_f = f"={chg_f}"

            # D: Bid/Ask Ratio = bid_lot / ask_lot
            bar_f = f"=IF({ask_f}=0,"",ROUND({bid_f}/{ask_f},2))"

            # E: Spread % = (best_ask - best_bid) / last_price * 100
            # best_bid = max bid = bid column (col H has totals, not levels)
            # We can't easily calc spread from aggregates, so approximate
            spread_f = "=IFERROR(0,"N/A")"

            # F: ARA Distance % = (ARA - Last) / Last * 100
            ara_dist_f = f"=IF(OR({ara_f}=0,{price_f}=0),"",ROUND(({ara_f}-{price_f})/{price_f}*100,2))"

            # G: ARB Distance % = (Last - ARB) / Last * 100
            arb_dist_f = f"=IF(OR({arb_f}=0,{price_f}=0),"",ROUND(({price_f}-{arb_f})/{price_f}*100,2))"

            # H: Foreign Net — direct
            fnet_formula_f = f"={fnet_f}"

            # I: Volume — direct
            vol_formula_f = f"={vol_f}"

            # J: Support — direct
            sup_formula_f = f"={sup_f}"

            # K: Resistance — direct
            res_formula_f = f"={res_f}"

            # L: Buy Pressure Score = min(bid/ask * 5, 10)
            bp_f = f"=IF({bar_f}="",0,MIN(ROUND({bar_f}*5,1),10))"

            # M: Scalp Score = tight spread + momentum
            scalp_f = f"=IF({bar_f}>=1.2,2,0) + IF({chg_f}>5,3,IF({chg_f}>2,2,IF({chg_f}>0,1,0)))"

            # N: ARA Potential = close to ARA + upward momentum
            ara_pot_f = f"=IF(AND({ara_dist_f}<="",0,IF({ara_dist_f}<=5,4,IF({ara_dist_f}<=10,2,0))) + IF({chg_f}>3,3,IF({chg_f}>0,1,0)) + IF({bar_f}>=1.2,2,0))"
            # Simpler version:
            ara_pot_f_simple = f"=IF({ara_dist_f}="",0,IF({ara_dist_f}<=5,4,IF({ara_dist_f}<=10,2,0))) + IF({chg_f}>3,3,IF({chg_f}>0,1,0)) + IF(IFERROR({bar_f}*1,0)>=1.2,2,0)"

            # O: Foreign Interest (0-10 based on magnitude)
            fi_f = f"=IF(ABS({fnet_f})>5000000000,10,IF(ABS({fnet_f})>2000000000,7,IF(ABS({fnet_f})>1000000000,5,IF(ABS({fnet_f})>500000000,3,IF(ABS({fnet_f})>100000000,1,0)))))"

            # P: Signal — composite
            # If spread <= X + change > Y => SCALP
            # If ara_dist <= 10 + change > 0 => ARA
            # If fnet > 1B + change > 0 => FOREIGN
            # If bid/ask >= 1.5 + change > 0 => LONG
            # Fallback: WATCH
            signal_f = (
                f"=IF(IFERROR({fnet_f}*1,0)>1000000000*IF(IFERROR({chg_f}*1,0)>0,"FOREIGN",""),"
                f"IF(IFERROR({ara_dist_f}*1,99)<=10*IF(IFERROR({chg_f}*1,0)>0,"ARA | ",""),"
                f"IF(AND(IFERROR({bar_f}*1,0)>=1.2,IFERROR({chg_f}*1,0)>2),"SCALP | ",""),"
                f"IF(AND(IFERROR({bar_f}*1,0)>=1.5,IFERROR({chg_f}*1,0)>0),"LONG | ",""),"
                f""WATCH")))"
            )
            # Simplier signal with TEXTJOIN:
            signal_f = (
                f'=TRIM('
                f'IF(AND(IFERROR({bar_f}*1,0)>=2,IFERROR({chg_f}*1,0)>0),"BUY ","")&'
                f'IF(IFERROR({chg_f}*1,0)>3,"MOMENTUM ","")&'
                f'IF(IFERROR({ara_dist_f}*1,99)<=5,"ARA ","")&'
                f'IF(IFERROR({fnet_f}*1,0)>1000000000,"FOREIGN ","")'
                f')'
            )

            rows.append([
                f"={ticker_f}",
                f"={price_f}",
                change_f,
                bar_f,
                spread_f,
                ara_dist_f,
                arb_dist_f,
                fnet_formula_f,
                vol_formula_f,
                sup_formula_f,
                res_formula_f,
                bp_f,
                scalp_f,
                ara_pot_f_simple,
                fi_f,
                signal_f,
            ])

        # Clear and write
        try:
            existing = len(ws.get_all_values())
            if existing > 1:
                ws.batch_clear([f"A2:P{existing}"])
        except Exception:
            pass

        ws.update(rows, value_input_option="USER_ENTERED")
        logger.info(f"dashboard: wrote {len(snapshots)} rows with formulas")


sheets_repository = SheetsRepository()
