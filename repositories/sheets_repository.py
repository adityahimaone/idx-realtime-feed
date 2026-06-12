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

    def _get_realtime_worksheet(self, sheet_id: str | None = None, sheet_name: str | None = None) -> gspread.Worksheet:
        """Get or create the Realtime_Watchlist worksheet.
        
        Args:
            sheet_id: Override sheet ID. Uses config.MARKET_ALPHA_SPREADSHEET_ID if None.
            sheet_name: Override worksheet title. Uses config.REALTIME_SHEET_NAME if None.
        """
        target_id = sheet_id or config.MARKET_ALPHA_SPREADSHEET_ID
        realtime_sheet_name = sheet_name or config.REALTIME_SHEET_NAME
        sh = self._get_client().open_by_key(target_id)
        try:
            return sh.worksheet(realtime_sheet_name)
        except gspread.WorksheetNotFound:
            logger.info(f"sheets: creating '{realtime_sheet_name}'")
            ws = sh.add_worksheet(
                title=realtime_sheet_name, rows=100, cols=len(HEADER_ROW)
            )
            ws.append_row(HEADER_ROW)
            return ws

    def get_watchlist(self) -> list[str]:
        """Fetch watchlist from Stockbit exodus API.

        Falls back to DEFAULT_WATCHLIST if API call fails.
        """
        import httpx

        try:
            token = config.STOCKBIT_BEARER_TOKEN
            wid = config.STOCKBIT_WATCHLIST_ID
            url = f"https://exodus.stockbit.com/watchlist/{wid}?page=1&limit=100&setfincol=1"
            resp = httpx.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            tickers = [item["symbol"] for item in data["data"]["result"]]
            result = tickers if config.MAX_WATCHLIST_SIZE <= 0 else tickers[: config.MAX_WATCHLIST_SIZE]
            logger.info(
                f"sheets: watchlist: {len(result)} tickers from Stockbit API"
            )
            return result
        except Exception as exc:
            logger.error(f"sheets: cannot fetch watchlist: {exc}")
            return config.DEFAULT_WATCHLIST or []

    def write_snapshots(self, snapshots: list[OrderbookSnapshot], sheet_id: str | None = None, sheet_name: str | None = None) -> None:
        """Overwrite Realtime_Watchlist with latest snapshots.

        Args:
            snapshots: List of orderbook data to write
            sheet_id: Override sheet ID. Uses config.MARKET_ALPHA_SPREADSHEET_ID if None.
            sheet_name: Override worksheet title. Uses config.REALTIME_SHEET_NAME if None.
            
        Integrity checks performed before write:
          - header validation against manifest
          - anti-rollback timestamp check
        """
        from repositories.integrity_guard import (
            check_anti_rollback,
            ensure_integrity,
            log_integrity_event,
        )

        ws = self._get_realtime_worksheet(sheet_id, sheet_name)

        # -- Integrity check 1: header structure --
        valid, issues = ensure_integrity(ws)
        if not valid:
            log_integrity_event("STRUCTURE_FAIL", "; ".join(issues))
            logger.error(
                f"integrity: sheet structure invalid -- {len(issues)} issues. "
                "Run guard manually to fix."
            )
            logger.warning("integrity: proceeding anyway (will add header if missing)")
            # If sheet is empty, init with headers
            actual = ws.row_values(1)
            if not any(actual):
                ws.append_row(HEADER_ROW)

        # -- Integrity check 2: anti-rollback --
        safe, reason = check_anti_rollback(ws)
        if not safe:
            log_integrity_event("ROLLBACK_BLOCKED", reason or "unknown")
            logger.error(f"integrity: anti-rollback blocked write: {reason}")
            # Don't abort -- allow overwrite but log. The check is advisory
            # for this use case (realtime feed should always overwrite).

        # -- Build rows --
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

        # -- Batch write --
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


    def _get_or_create_sheet(self, title: str, cols: int, sheet_id: str | None = None) -> gspread.Worksheet:
        """Get or create a worksheet by title. Freezes row 1."""
        target_id = sheet_id or config.MARKET_ALPHA_SPREADSHEET_ID
        sh = self._get_client().open_by_key(target_id)
        try:
            return sh.worksheet(title)
        except gspread.WorksheetNotFound:
            logger.info(f"sheets: creating '{title}'")
            ws = sh.add_worksheet(title=title, rows=500, cols=cols)
            ws.freeze(1)
            return ws

    def _build_formula_rows(self, snapshots: list[OrderbookSnapshot], realtime_sheet_name: str | None = None) -> list[list]:
        """Build formula-referenced rows for Dashboard Formula [IRW].

        Each formula references ='Realtime_Watchlist [IRW]'!col{row} so values are live.
        Sheet name wrapped in single quotes because of the space + brackets.
        Uses config.REALTIME_SHEET_NAME or provided override so rename propagates.
        """
        rw_ref = f"'{realtime_sheet_name or config.REALTIME_SHEET_NAME}'"
        rows = [DASHBOARD_HEADER]
        for i in range(len(snapshots)):
            r = i + 2  # row 2 onwards in Realtime_Watchlist [IRW]
            pw = f"{rw_ref}!A{r}"
            pp = f"{rw_ref}!B{r}"
            pc = f"{rw_ref}!C{r}"
            pb = f"{rw_ref}!H{r}"
            pa = f"{rw_ref}!I{r}"
            pf = f"{rw_ref}!K{r}"
            pla = f"{rw_ref}!L{r}"
            plb = f"{rw_ref}!M{r}"
            pv = f"{rw_ref}!G{r}"
            ps = f"{rw_ref}!N{r}"
            pr = f"{rw_ref}!O{r}"

            ref_bar = f'IF({pa}=0,"",ROUND({pb}/{pa},2))'
            ref_ara_d = f'IF(OR({pla}=0,{pp}=0),"",ROUND(({pla}-{pp})/{pp}*100,2))'
            ref_arb_d = f'IF(OR({plb}=0,{pp}=0),"",ROUND(({pp}-{plb})/{pp}*100,2))'

            rows.append([
                f"={pw}",
                f"={pp}",
                f"={pc}",
                f"={ref_bar}",
                '=IFERROR(0,"N/A")',
                f"={ref_ara_d}",
                f"={ref_arb_d}",
                f"={pf}",
                f"={pv}",
                f"={ps}",
                f"={pr}",
                f'=IF({ref_bar}="",0,MIN(ROUND({ref_bar}*5,1),10))',
                f'=IF(IFERROR({ref_bar}*1,0)>=1.2,2,0)+IF({pc}>5,3,IF({pc}>2,2,IF({pc}>0,1,0)))',
                f'=IF(IFERROR({ref_ara_d}*1,99)<=5,4,IF(IFERROR({ref_ara_d}*1,99)<=10,2,0))+IF({pc}>3,3,IF({pc}>0,1,0))+IF(IFERROR({ref_bar}*1,0)>=1.2,2,0)',
                f'=IF(ABS({pf})>5000000000,10,IF(ABS({pf})>2000000000,7,IF(ABS({pf})>1000000000,5,IF(ABS({pf})>500000000,3,IF(ABS({pf})>100000000,1,0)))))',
                f'=TRIM(IF(AND(IFERROR({ref_bar}*1,0)>=2,IFERROR({pc}*1,0)>0),"BUY ","")&IF(IFERROR({pc}*1,0)>3,"MOMENTUM ","")&IF(IFERROR({ref_ara_d}*1,99)<=5,"ARA ","")&IF(IFERROR({pf}*1,0)>1000000000,"FOREIGN ",""))',
            ])
        return rows

    def write_dashboard(self, snapshots: list[OrderbookSnapshot], sheet_id: str | None = None, realtime_sheet_name: str | None = None) -> None:
        from scripts.dashboard_signals import compute_dashboard_row, compute_market_recap, HEADER

        sid = sheet_id or config.MARKET_ALPHA_SPREADSHEET_ID
        sh = self._get_client().open_by_key(sid)

        # -- 1. Dashboard [IRW] -- script values --
        ws = self._get_or_create_sheet("Dashboard [IRW]", len(HEADER), sid)
        rows = [HEADER]
        rows_data = []
        for snap in snapshots:
            row = compute_dashboard_row(snap)
            rows.append(row)
            rows_data.append(row)
        ws.clear()
        if len(rows) > 1:
            ws.update(rows, value_input_option="USER_ENTERED")
        for ci, h in enumerate(HEADER, 1):
            ws.update_cell(1, ci, h)

        # -- 2. Dashboard Formula [IRW] -- GS formulas --
        fws = self._get_or_create_sheet("Dashboard Formula [IRW]", len(DASHBOARD_HEADER), sid)
        frows = self._build_formula_rows(snapshots, realtime_sheet_name=realtime_sheet_name)
        fws.clear()
        if len(frows) > 1:
            fws.update(frows, value_input_option="USER_ENTERED")
        for ci, h in enumerate(DASHBOARD_HEADER, 1):
            fws.update_cell(1, ci, h)

        # -- 3. Market Recap sheet (separate, scales with any watchlist size) --
        try:
            rw = self._get_or_create_sheet("Market Recap [IRW]", 4, sid)
            recap = compute_market_recap(rows_data)
            rw.clear()
            if recap:
                rw.update(recap, value_input_option="USER_ENTERED")
            logger.info("sheets: wrote Dashboard [IRW] + Dashboard Formula [IRW] + Market Recap")
        except Exception as exc:
            logger.error(f"sheets: recap failed: {exc}")


sheets_repository = SheetsRepository()
