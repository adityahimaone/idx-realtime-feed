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
    "No",
    "Ticker",
    "Company Name",
    "Sector",
    "Sparkline",
    "Price",
    "Change%",
    "Change",
    "PriceOpen",
    "High",
    "Low",
    "ClosePrev",
    "Gap_Pct",
    "Gap_Flag",
    "Volume",
    "Vol_Avg",
    "Vol_Ratio",
    "Vol_Flag",
    "Daily_Range_Pct",
    "Vol_Level",
    "MarketCap",
    "PE",
    "PE_Grade",
    "EPS",
    "Beta",
    "52W High",
    "52W Low",
    "Dist to 52W High",
    "Dist_52W_Low",
    "52W_Range_Pct",
    "Range_Signal",
    "MA20",
    "MA50",
    "MA200",
    "Support",
    "Breakout",
    "Reversal",
    "BSJP",
    "Signal",
    "Trend",
    "Score",
    "Score v2",
    "Rank",
    "Final_Signal",
    "SL_Practical",
    "TP_Target",
    "RR_Ratio",
    "ATR14",
    "ATR %",
    "RSI14",
    "RSI Signal",
    "Status",
    "Volume_Flag",
    "Liquidity_Score",
    "Momentum_Score",
    "ARA_Score",
    "ARA_Dist_Pct",
    "ARA_Stage",
    "Gap_Score",
    "Last Update",
    "Total Bid Lot",
    "Total Ask Lot",
    "Imbalance Ratio",
    "Foreign Net",
    "ARA",
    "ARB",
    "Source",
    "UMA",
    "Corp Action",
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
    "ARA Candidate",
    "Scalp Suitability",
    "Long Term Pick",
    "Final Recommendation",
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
        # -- Build rows --
        rows = [HEADER_ROW]
        for idx, snap in enumerate(snapshots, start=2):
            row = []
            for col_i, col in enumerate(HEADER_ROW):
                if col == "No":
                    row.append(idx - 1)
                elif col == "Ticker":
                    row.append(snap.ticker)
                elif col == "Company Name":
                    row.append(snap.name if snap.name else f"=IFERROR(VLOOKUP(B{idx},'All Tickers'!B:BH,{col_i},FALSE),\"\")")
                elif col == "Sparkline":
                    if snap.prices:
                        prices_str = ",".join(str(p) for p in snap.prices)
                        row.append(f"=SPARKLINE({{{prices_str}}})")
                    else:
                        row.append(f"=IFERROR(VLOOKUP(B{idx},'All Tickers'!B:BH,{col_i},FALSE),\"\")")
                elif col == "Price":
                    row.append(snap.last_price)
                elif col == "Change%":
                    row.append(f'=IF(L{idx}>0, ROUND((F{idx}-L{idx})/L{idx}*100, 2), 0)')
                elif col == "Change":
                    row.append(f'=F{idx}-L{idx}')
                elif col == "PriceOpen":
                    row.append(snap.open_price if snap.open_price else "")
                elif col == "High":
                    row.append(snap.high if snap.high else "")
                elif col == "Low":
                    row.append(snap.low if snap.low else "")
                elif col == "ClosePrev":
                    row.append(snap.prev_close if snap.prev_close else "")
                elif col == "Gap_Pct":
                    row.append(f'=IF(L{idx}>0, ROUND((I{idx}-L{idx})/L{idx}*100, 2), 0)')
                elif col == "Gap_Flag":
                    row.append(f'=IF(M{idx}>0, "UP", IF(M{idx}<0, "DOWN", ""))')
                elif col == "Volume":
                    row.append(snap.volume if snap.volume else "")
                elif col == "Daily_Range_Pct":
                    row.append(f'=IF(K{idx}>0, ROUND((J{idx}-K{idx})/K{idx}*100, 2), 0)')
                elif col == "Dist to 52W High":
                    row.append(f'=IF(Z{idx}>0, ROUND((Z{idx}-F{idx})/Z{idx}*100, 2), "")')
                elif col == "Dist_52W_Low":
                    row.append(f'=IF(AA{idx}>0, ROUND((F{idx}-AA{idx})/AA{idx}*100, 2), "")')
                elif col == "52W_Range_Pct":
                    row.append(f'=IF(AA{idx}>0, ROUND((Z{idx}-AA{idx})/AA{idx}*100, 2), "")')
                elif col == "Support" and snap.support_price is not None:
                    row.append(snap.support_price)
                elif col == "ARA_Dist_Pct":
                    row.append(f'=IF(AND(BM{idx}>0, F{idx}>0), ROUND((BM{idx}-F{idx})/F{idx}*100, 2), "")')
                elif col == "Last Update":
                    row.append(snap.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
                elif col == "Total Bid Lot":
                    row.append(snap.total_bid_lot)
                elif col == "Total Ask Lot":
                    row.append(snap.total_ask_lot)
                elif col == "Imbalance Ratio":
                    row.append(snap.imbalance_ratio if snap.imbalance_ratio is not None else "")
                elif col == "Foreign Net":
                    row.append(snap.fnet)
                elif col == "ARA":
                    row.append(snap.ara_price if snap.ara_price else "")
                elif col == "ARB":
                    row.append(snap.arb_price if snap.arb_price else "")
                elif col == "Source":
                    row.append(snap.source.value)
                elif col == "UMA":
                    row.append("UMA" if snap.uma else "")
                elif col == "Corp Action":
                    row.append(snap.corp_action_text if snap.corp_action_active else "")
                else:
                    # Formula index in range B:BH is exactly col_i
                    row.append(f"=IFERROR(VLOOKUP(B{idx},'All Tickers'!B:BH,{col_i},FALSE),\"\")")
            rows.append(row)

        # -- Batch write --
        # Clear existing content first (leave header) then write
        try:
            existing_rows = len(ws.get_all_values())
            if existing_rows > 1:
                # Clear all data rows (leaving header at row 1)
                range_clear = f"A2:BQ{existing_rows}"
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
        """Build formula-referenced rows for Dashboard Formula.

        Each formula references ='Realtime_Watchlist [IRW]'!col{row} so values are live.
        Sheet name wrapped in single quotes because of the space + brackets.
        Uses config.REALTIME_SHEET_NAME or provided override so rename propagates.
        """
        rw_ref = f"'{realtime_sheet_name or config.REALTIME_SHEET_NAME}'"
        rows = [DASHBOARD_HEADER]
        for i in range(len(snapshots)):
            r = i + 2  # row 2 onwards in Realtime_Watchlist [IRW]
            pw = f"{rw_ref}!B{r}"
            pp = f"{rw_ref}!F{r}"
            pc = f"{rw_ref}!G{r}"
            pb = f"{rw_ref}!BI{r}"
            pa = f"{rw_ref}!BJ{r}"
            pf = f"{rw_ref}!BL{r}"
            pla = f"{rw_ref}!BM{r}"
            plb = f"{rw_ref}!BN{r}"
            pv = f"{rw_ref}!O{r}"
            ps = f"{rw_ref}!AI{r}"
            pr = f"{rw_ref}!AJ{r}"

            ref_bar = f'IF({pa}=0,"",ROUND({pb}/{pa},2))'
            ref_ara_d = f'IF(OR({pla}=0,{pp}=0),"",ROUND(({pla}-{pp})/{pp}*100,2))'
            ref_arb_d = f'IF(OR({plb}=0,{pp}=0),"",ROUND(({pp}-{plb})/{pp}*100,2))'

            # Excel row references inside Dashboard / Dashboard Formula sheet
            # Ticker=A, Last=B, Chg%=C, B/A=D, Spread=E, ARA_d=F, ARB_d=G, FNet=H, Vol=I, Support=J, Res=K, BPS=L, ScalpS=M, ARA_pot=N, FInt=O, Sig=P
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
                f'=IF(AND(F{r}<=5,C{r}>3,D{r}>=1.5),"HIGH",IF(AND(F{r}<=10,C{r}>0),"MEDIUM","LOW"))',
                f'=IF(AND(C{r}>3,D{r}>=1.5),"STRONG SCALP",IF(AND(C{r}>1,D{r}>=1.1),"MODERATE","NOT SUITABLE"))',
                f'=IF(AND(H{r}>100000000,C{r}>=-2,C{r}<=2),"ACCUMULATION","HOLD/WATCH")',
                f'=IF(AND(L{r}>=7,O{r}>=5),"STRONG BUY",IF(L{r}>=5,"BUY",IF(L{r}<=3,"SELL","HOLD")))'
            ])
        return rows

    def write_dashboard(self, snapshots: list[OrderbookSnapshot], sheet_id: str | None = None, realtime_sheet_name: str | None = None) -> None:
        from scripts.dashboard_signals import compute_dashboard_row, compute_market_recap, HEADER

        sid = sheet_id or config.MARKET_ALPHA_SPREADSHEET_ID
        sh = self._get_client().open_by_key(sid)

        # Route dynamically for Light Mode target sheet naming separation
        if realtime_sheet_name == "Light Watchlist [IRW]":
            dashboard_sheet_name = "Dashboard Lighthouse [IRW]"
            formula_sheet_name = "Dashboard Formula Lighthouse [IRW]"
            recap_sheet_name = "Market Recap Lighthouse [IRW]"
        else:
            dashboard_sheet_name = "Dashboard [IRW]"
            formula_sheet_name = "Dashboard Formula [IRW]"
            recap_sheet_name = "Market Recap [IRW]"

        # -- 1. Dashboard -- script values --
        ws = self._get_or_create_sheet(dashboard_sheet_name, len(HEADER), sid)
        rows = [HEADER]
        rows_data = []
        for snap in snapshots:
            row = compute_dashboard_row(snap)
            rows.append(row)
            rows_data.append(row)
        ws.clear()
        if len(rows) > 1:
            ws.update(rows, value_input_option="USER_ENTERED")

        # -- 2. Dashboard Formula -- GS formulas --
        fws = self._get_or_create_sheet(formula_sheet_name, len(DASHBOARD_HEADER), sid)
        frows = self._build_formula_rows(snapshots, realtime_sheet_name=realtime_sheet_name)
        fws.clear()
        if len(frows) > 1:
            fws.update(frows, value_input_option="USER_ENTERED")

        # -- 3. Market Recap sheet --
        try:
            rw = self._get_or_create_sheet(recap_sheet_name, 4, sid)
            recap = compute_market_recap(rows_data)
            rw.clear()
            if recap:
                rw.update(recap, value_input_option="USER_ENTERED")
            logger.info(f"sheets: wrote {dashboard_sheet_name} + {formula_sheet_name} + {recap_sheet_name}")
        except Exception as exc:
            logger.error(f"sheets: recap failed: {exc}")

    def update_rekomendasi_beli(self, sheet_id: str | None = None) -> None:
        """Read tickers and metrics from Realtime_Watchlist [IRW] and Light Watchlist [IRW],
        compute recommendations, and write to 'Rekomendasi Beli [IRW]'."""
        import math
        from zoneinfo import ZoneInfo
        from datetime import datetime
        
        WIB = ZoneInfo("Asia/Jakarta")
        sid = sheet_id or config.MARKET_ALPHA_SPREADSHEET_ID
        sh = self._get_client().open_by_key(sid)

        def safe_float(v):
            if v is None or v == "":
                return None
            try:
                if isinstance(v, str):
                    v = v.replace(",", "").replace("%", "").strip()
                f = float(v)
                if math.isnan(f) or math.isinf(f):
                    return None
                return f
            except (ValueError, TypeError):
                return None

        def compute_action(rr, score_v2, rsi):
            if rr is None or score_v2 is None:
                return "❌ AVOID", "0%", ""
            if rr >= 1.5 and score_v2 >= 20 and (rsi is None or rsi < 75):
                return "✅ BUY", "5%", "R/R ≥1.5, Score ≥20, confirmed"
            if rr >= 1.0 and score_v2 >= 10 and (rsi is None or rsi < 70):
                return "⚡ SPECULATIVE", "2-3%", "R/R ≥1.0, Score ≥10"
            return "❌ AVOID", "0%", f"R/R {rr:.2f}, Score {score_v2:.1f} — below threshold"

        # 1. Read tickers and data from watchlists
        watchlist_tickers = {}  # ticker -> dict of values
        
        # Columns we need
        need = ["Ticker", "Company Name", "Sector", "Price", "Change%", "Score v2",
                "Rank", "RSI14", "Vol_Ratio", "SL_Practical", "52W High", "52W Low",
                "MA20", "MA50", "ATR14", "UMA", "Corp Action"]
                
        watchlists = ["Realtime_Watchlist [IRW]", "Light Watchlist [IRW]"]
        for ws_name in watchlists:
            try:
                ws = sh.worksheet(ws_name)
                vals = ws.get_all_values()
                if len(vals) > 1:
                    headers = [h.strip() for h in vals[0]]
                    col_idx = {h: i for i, h in enumerate(headers)}
                    
                    if "Ticker" not in col_idx:
                        continue
                        
                    added = 0
                    for row in vals[1:]:
                        ticker = row[col_idx["Ticker"]].strip().upper().replace("IDX:", "")
                        if not ticker:
                            continue
                            
                        data = {}
                        for n in need:
                            if n in col_idx and col_idx[n] < len(row):
                                data[n] = row[col_idx[n]].strip()
                            else:
                                data[n] = ""
                                
                        price = safe_float(data.get("Price"))
                        if ticker not in watchlist_tickers or price is not None:
                            watchlist_tickers[ticker] = data
                            added += 1
                    logger.info(f"sheets: read {added} tickers from '{ws_name}' for Rekomendasi Beli [IRW]")
            except Exception as e:
                logger.warning(f"sheets: could not read '{ws_name}' for Rekomendasi Beli: {e}")

        if not watchlist_tickers:
            # Fallback to All Tickers
            try:
                ws_all = sh.worksheet("All Tickers")
                vals = ws_all.get_all_values()
                if len(vals) > 1:
                    headers = [h.strip() for h in vals[0]]
                    col_idx = {h: i for i, h in enumerate(headers)}
                    for row in vals[1:]:
                        ticker = row[col_idx["Ticker"]].strip().upper().replace("IDX:", "")
                        if not ticker:
                            continue
                        data = {}
                        for n in need:
                            if n in col_idx and col_idx[n] < len(row):
                                data[n] = row[col_idx[n]].strip()
                            else:
                                data[n] = ""
                        rank = data.get("Rank", "")
                        score_v2 = safe_float(data.get("Score v2"))
                        if rank in ("⭐ Strong Buy", "🔥 Watchlist") or (score_v2 and score_v2 >= 50):
                            watchlist_tickers[ticker] = data
            except Exception as e:
                logger.error(f"sheets: fallback to All Tickers failed: {e}")
                return

        # Sort by Score v2 desc
        candidates = list(watchlist_tickers.values())
        candidates.sort(key=lambda x: safe_float(x.get("Score v2")) or 0.0, reverse=True)
        candidates = candidates[:30]

        rb_name = "Rekomendasi Beli [IRW]"
        try:
            ws_rb = sh.worksheet(rb_name)
        except gspread.WorksheetNotFound:
            logger.info(f"sheets: creating '{rb_name}'")
            ws_rb = sh.add_worksheet(title=rb_name, rows=100, cols=16)

        rb_rows = []
        rb_rows.append([
            "🎯 REKOMENDASI BELI [IRW] — MARKET ALPHA SCOUT v2.7.1", "", "", "", "", "",
            "", "", "", "", "", "", "", "", "", ""
        ])
        rb_rows.append([
            f"Last updated: {datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')} WIB", "", "", "", "", "",
            "", "", "", "", "", "", "", "", "", ""
        ])
        rb_rows.append([""] * 16)
        rb_rows.append([
            "Ticker", "Company", "Sector", "Price", "Change%", "Score v2",
            "Rank", "RSI14", "Vol_Ratio", "Buy Price", "SL_Practical",
            "TP", "R/R Ratio", "Max Pos", "Action", "Notes"
        ])

        for data in candidates:
            ticker = data["Ticker"].upper().replace("IDX:", "")
            company = data["Company Name"]
            sector = data["Sector"]
            price = safe_float(data["Price"])
            change_pct = safe_float(data["Change%"])
            score_v2 = safe_float(data["Score v2"])
            rank = data["Rank"]
            rsi = safe_float(data["RSI14"])
            vol_ratio = safe_float(data["Vol_Ratio"])
            sl_prac = safe_float(data["SL_Practical"])
            high52 = safe_float(data["52W High"])
            ma20 = safe_float(data["MA20"])
            atr = safe_float(data["ATR14"])

            if price is None or price <= 0:
                continue

            buy_price = price
            sl = sl_prac if sl_prac else round(max((ma20 or 0) * 0.97, price * 0.93), 2)
            if sl >= buy_price:
                sl = round(buy_price * 0.93, 2)

            if high52:
                tp = round(min(high52, buy_price * 1.15), 2)
            else:
                tp = round(buy_price * 1.15, 2)

            rr = None
            if buy_price > sl:
                rr = round((tp - buy_price) / (buy_price - sl), 2)

            action, max_pos, notes = compute_action(rr, score_v2, rsi)

            if atr and atr > 0:
                sl_atr = round(buy_price - 1.5 * atr, 2)
                notes += f" | SL_ATR={sl_atr}"

            uma_str = data.get("UMA", "")
            corp_act_str = data.get("Corp Action", "")
            if uma_str:
                notes += f" | {uma_str}"
            if corp_act_str:
                notes += f" | CorpAct: {corp_act_str}"

            rb_rows.append([
                ticker, company, sector,
                price, change_pct if change_pct is not None else "",
                score_v2 if score_v2 is not None else "",
                rank, rsi if rsi is not None else "",
                vol_ratio if vol_ratio is not None else "",
                buy_price, sl, tp,
                rr if rr is not None else "",
                max_pos, action, notes
            ])

        try:
            ws_rb.clear()
            if ws_rb.row_count < len(rb_rows) + 5:
                ws_rb.resize(rows=len(rb_rows) + 10, cols=16)
            ws_rb.append_rows(rb_rows, value_input_option="USER_ENTERED")
            logger.info(f"sheets: updated '{rb_name}' with {len(candidates)} candidates")
        except Exception as exc:
            logger.error(f"sheets: Rekomendasi Beli [IRW] update failed: {exc}")


sheets_repository = SheetsRepository()
