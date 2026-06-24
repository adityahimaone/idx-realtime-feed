"""
Data pipeline: fetch live data for bot's independent analysis.
Reuses app's fetchers/scoring where possible.
"""
import sys
import os
import asyncio
from datetime import datetime
from typing import Optional

import pytz
import yfinance as yf

# Allow imports from app root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetchers import safe_float, fetch_idx_source, fetch_gsheet_source, fetch_yfinance_source
from data.scoring import compute_intraday_score, compute_action_recommendation, get_tick_size
from data.pre_ara import (
    get_ara_limit, get_ara_price, ara_proximity_score,
    pre_ara_score, classify_pre_ara
)
from repositories.sheets_repository import sheets_repository
from core.config import config

WIB = pytz.timezone("Asia/Jakarta")


def _fetch_all_tickers_sheet() -> tuple[list[str], list[list[str]]]:
    """
    Fetch 'All Tickers' sheet once. Returns (headers, rows).
    Single API call — callers must cache result themselves.
    """
    sh = sheets_repository._get_client().open_by_key(config.MARKET_ALPHA_SPREADSHEET_ID)
    ws = sh.worksheet("All Tickers")
    vals = ws.get_all_values()
    if not vals:
        return [], []
    headers = [h.strip() for h in vals[0]]
    return headers, vals[1:]


def get_watchlist_tickers() -> list[str]:
    """
    Load All Tickers from Google Sheets.
    Returns list of clean ticker symbols (e.g. ['BBRI', 'TLKM', ...]).
    Single sheet fetch — no per-ticker calls.
    """
    try:
        headers, rows = _fetch_all_tickers_sheet()
        if not headers:
            return []
        col_idx = {h: i for i, h in enumerate(headers)}
        if "Ticker" not in col_idx:
            return []
        tickers = []
        for r in rows:
            ticker = r[col_idx["Ticker"]].strip().upper().replace("IDX:", "").strip()
            if ticker:
                tickers.append(ticker)
        return tickers
    except Exception as e:
        print(f"get_watchlist_tickers error: {e}")
        return []


def get_all_hist_rows() -> dict[str, dict]:
    """
    Fetch entire 'All Tickers' sheet ONCE and return dict keyed by ticker.
    Use this instead of calling get_hist_row per ticker — saves N-1 API reads.
    """
    try:
        headers, rows = _fetch_all_tickers_sheet()
        if not headers:
            return {}
        col_idx = {h: i for i, h in enumerate(headers)}
        result = {}
        for r in rows:
            ticker = r[col_idx["Ticker"]].strip().upper().replace("IDX:", "").strip() if "Ticker" in col_idx else ""
            if not ticker:
                continue
            row_dict = {}
            for col_i, h in enumerate(headers):
                val = r[col_i].strip() if col_i < len(r) else ""
                row_dict[h] = val
            result[ticker] = row_dict
        return result
    except Exception as e:
        print(f"get_all_hist_rows error: {e}")
        return {}


def get_hist_row(ticker: str) -> dict:
    """
    Get historical row for a ticker from Google Sheets.
    NOTE: Still fetches full sheet each call — use get_all_hist_rows() for bulk scans.
    """
    try:
        headers, rows = _fetch_all_tickers_sheet()
        if not headers:
            return {}
        col_idx = {h: i for i, h in enumerate(headers)}
        ticker_upper = ticker.upper().strip()
        for r in rows:
            existing = r[col_idx["Ticker"]].strip().upper().replace("IDX:", "").strip()
            if existing == ticker_upper:
                row_dict = {}
                for col_i, h in enumerate(headers):
                    val = r[col_i].strip() if col_i < len(r) else ""
                    row_dict[h] = val
                return row_dict
        return {}
    except Exception as e:
        print(f"get_hist_row error for {ticker}: {e}")
        return {}


def get_ihsg_status() -> dict:
    """
    IHSG (^JKSE) status from yfinance.
    """
    try:
        ticker = yf.Ticker("^JKSE")
        info = ticker.info
        last = safe_float(info.get("regularMarketPrice", 0))
        prev = safe_float(info.get("regularMarketPreviousClose", 0))
        open_ = safe_float(info.get("regularMarketOpen", last))
        high = safe_float(info.get("regularMarketDayHigh", last))
        low = safe_float(info.get("regularMarketDayLow", last))
        chg = ((last - prev) / prev * 100) if prev > 0 else 0.0
        cpr = ((last - low) / (high - low) * 100) if high > low else 50.0
        return {
            "last": last, "prev": prev, "open": open_, "high": high, "low": low,
            "chg_pct": chg, "cpr": cpr
        }
    except Exception as e:
        print(f"get_ihsg_status error: {e}")
        return {"last": 0, "prev": 0, "open": 0, "high": 0, "low": 0, "chg_pct": 0, "cpr": 50}


async def fetch_ticker_live(ticker: str) -> Optional[dict]:
    """
    Fetch live price for a ticker. Tries IDX endpoint first, then yfinance.
    Returns dict: {last, open, high, low, prev_close, volume, frequency, value,
                   foreign_buy, foreign_sell, source, source_ts}
    """
    # Run fetch in executor (yfinance is sync)
    loop = asyncio.get_event_loop()

    def _fetch():
        # IDX endpoint
        idx = fetch_idx_source(ticker)
        if idx.get("error") is None and idx.get("last", 0) > 0:
            return {
                "last": idx.get("last", 0),
                "open": idx.get("open", 0),
                "high": idx.get("high", 0),
                "low": idx.get("low", 0),
                "prev_close": idx.get("prev_close", 0),
                "volume": idx.get("volume", 0),
                "frequency": idx.get("frequency", 0),
                "value": idx.get("value", 0),
                "foreign_buy": idx.get("foreign_buy", 0),
                "foreign_sell": idx.get("foreign_sell", 0),
                "source": "idx_endpoint",
                "source_ts": idx.get("source_ts"),
            }
        # yfinance fallback
        yf_res = fetch_yfinance_source(ticker)
        if yf_res.get("error") is None and yf_res.get("last", 0) > 0:
            return {
                "last": yf_res.get("last", 0),
                "open": yf_res.get("open", 0),
                "high": yf_res.get("high", 0),
                "low": yf_res.get("low", 0),
                "prev_close": yf_res.get("prev_close", 0),
                "volume": yf_res.get("volume", 0),
                "frequency": 0,
                "value": 0,
                "foreign_buy": 0,
                "foreign_sell": 0,
                "source": "yfinance",
                "source_ts": yf_res.get("source_ts"),
            }
        return None

    return await loop.run_in_executor(None, _fetch)


async def scan_ticker(ticker: str, hist_cache: Optional[dict] = None) -> Optional[dict]:
    """
    Full scan: live + hist + score. Returns combined dict or None.
    Pass hist_cache (from get_all_hist_rows) to avoid per-ticker sheet reads.
    """
    hist = hist_cache.get(ticker) if hist_cache is not None else None
    if hist is None:
        hist = get_hist_row(ticker)
    if not hist:
        return None
    live = await fetch_ticker_live(ticker)
    if not live:
        return None
    score = compute_intraday_score(live, hist)
    company = hist.get("Company Name", ticker)
    sector = hist.get("Sector", "")
    return {
        "ticker": ticker,
        "company": company,
        "sector": sector,
        "live": live,
        "hist": hist,
        "score": score["score"],
        "signal": score["signal"],
        "vol_spike": score["vol_spike"],
        "chg_pct": score["change_pct"],
    }


async def scan_all(tickers: list[str], concurrency: int = 8) -> list[dict]:
    """
    Scan multiple tickers with bounded concurrency.
    Fetches sheet ONCE, passes cache to each scan_ticker — single API read total.
    Returns list of scan results (filtered for valid ones).
    """
    hist_cache = get_all_hist_rows()
    sem = asyncio.Semaphore(concurrency)

    async def _scan_one(t):
        async with sem:
            return await scan_ticker(t, hist_cache=hist_cache)

    tasks = [_scan_one(t) for t in tickers]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


def now_wib_str() -> str:
    return datetime.now(WIB).strftime("%d %b %Y %H:%M WIB")
