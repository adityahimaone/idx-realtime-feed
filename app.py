import streamlit as st
import pandas as pd
import numpy as np
import asyncio
from datetime import datetime
import os
import sys
import math
import time
import pytz
import yfinance as yf
import plotly.graph_objects as go
from curl_cffi import requests as requests_cf
from ui.tabs.tab8_news_signals import render_tab8
from ui.tabs.tab3_screener import render_tab3
from ui.tabs.tab4_trending import render_tab4
from ui.tabs.tab9_pre_ara import render_tab9
from ui.tabs.tab10_elliott_wave import render_tab10
from ui.tabs.tab7_deep_analysis import render_tab7
from ui.components.status_bar import render_status_board, render_ihsg_widget

# Mitigate yfinance cache locking issues in parallel execution
try:
    os.makedirs("/tmp/yfinance_tz", exist_ok=True)
    yf.set_tz_cache_location("/tmp/yfinance_tz")
except Exception as e:
    pass


# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import config
from core.logger import logger
from services.auth_service import auth_service
from providers.stockbit_provider import StockbitProvider
from repositories.sheets_repository import sheets_repository
from repositories.sqlite_repository import sqlite_repository

# Timezone normalization
WIB = pytz.timezone("Asia/Jakarta")

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================
st.set_page_config(
    page_title="IDX Intraday Multi-Source Screener [IRW]",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

from ui.components.styles import inject_css
inject_css()

st.markdown("""
<style>
    .stApp {
        background-color: #0E1117;
        color: #E2E8F0;
    }
    .metric-card {
        background-color: #1A202C;
        border-radius: 10px;
        padding: 20px;
        margin: 10px 0;
        border-left: 5px solid #00D4AA;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .strategy-card {
        background-color: #2D3748;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        border: 1px solid #4A5568;
    }
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: bold;
        text-align: center;
        font-size: 0.85em;
    }
    
    /* Upgraded Buy Recommendations Card Grid */
    .card-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
        gap: 20px;
        margin-top: 15px;
    }
    .rec-card {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -4px rgba(0, 0, 0, 0.3);
        transition: transform 0.2s, border-color 0.2s;
        position: relative;
        overflow: hidden;
    }
    .rec-card:hover {
        transform: translateY(-4px);
        border-color: #38BDF8;
    }
    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 12px;
    }
    .ticker-badge {
        font-size: 1.3em;
        font-weight: 800;
        color: #F8FAFC;
        background-color: #334155;
        padding: 4px 10px;
        border-radius: 8px;
        letter-spacing: 0.5px;
        display: inline-block;
    }
    .action-badge {
        padding: 6px 12px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 0.85em;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        display: inline-block;
    }
    .action-strong-buy {
        background-color: rgba(16, 185, 129, 0.2);
        color: #10B981;
        border: 1px solid rgba(16, 185, 129, 0.4);
        box-shadow: 0 0 10px rgba(16, 185, 129, 0.2);
    }
    .action-buy {
        background-color: rgba(59, 130, 246, 0.2);
        color: #3B82F6;
        border: 1px solid rgba(59, 130, 246, 0.4);
        box-shadow: 0 0 10px rgba(59, 130, 246, 0.1);
    }
    .action-speculative {
        background-color: rgba(245, 158, 11, 0.2);
        color: #F59E0B;
        border: 1px solid rgba(245, 158, 11, 0.4);
        box-shadow: 0 0 10px rgba(245, 158, 11, 0.1);
    }
    .company-name {
        font-size: 0.9em;
        color: #94A3B8;
        margin-top: 6px;
        font-weight: 500;
    }
    .sector-tag {
        font-size: 0.75em;
        color: #38BDF8;
        background-color: #1E293B;
        padding: 2px 6px;
        border-radius: 4px;
        display: inline-block;
        margin-top: 4px;
        font-weight: 600;
    }
    .price-display {
        display: flex;
        align-items: baseline;
        margin: 15px 0 10px 0;
    }
    .price-value {
        font-size: 1.8em;
        font-weight: 700;
        color: #F8FAFC;
    }
    .price-change {
        margin-left: 8px;
        font-size: 0.95em;
        font-weight: 600;
    }
    .change-up { color: #10B981; }
    .change-down { color: #EF4444; }
    
    .metric-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
        margin: 8px 0;
        font-size: 0.85em;
    }
    .metric-box {
        background-color: #0F172A;
        padding: 8px;
        border-radius: 6px;
        border: 1px solid #1E293B;
    }
    .metric-label {
        color: #64748B;
        font-size: 0.8em;
        margin-bottom: 2px;
    }
    .metric-value {
        color: #E2E8F0;
        font-weight: 600;
    }
    .score-section {
        margin: 12px 0;
    }
    .score-header {
        display: flex;
        justify-content: space-between;
        font-size: 0.85em;
        margin-bottom: 4px;
        color: #94A3B8;
    }
    .progress-bar-bg {
        background-color: #334155;
        height: 6px;
        border-radius: 3px;
        overflow: hidden;
    }
    .progress-bar-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.5s ease-out;
    }
    .notes-section {
        font-size: 0.8em;
        color: #E2E8F0;
        background-color: #0F172A;
        padding: 8px 12px;
        border-radius: 6px;
        border-left: 3px solid #38BDF8;
        margin-top: 10px;
        line-height: 1.4;
    }
    
    /* API Status & Pulse Animations */
    .status-container {
        display: flex;
        flex-wrap: wrap;
        gap: 15px;
        background-color: #1A202C;
        padding: 15px 20px;
        border-radius: 10px;
        margin-bottom: 20px;
        border: 1px solid #2D3748;
        align-items: center;
    }
    .status-item {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.9em;
        font-weight: 500;
    }
    .pulse-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        display: inline-block;
    }
    .pulse-green {
        background-color: #10B981;
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        animation: pulse-green-anim 2s infinite;
    }
    .pulse-yellow {
        background-color: #F59E0B;
        box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.7);
        animation: pulse-yellow-anim 2s infinite;
    }
    .live-label-container {
        display: flex;
        align-items: center;
        gap: 6px;
        background-color: rgba(16, 185, 129, 0.15);
        color: #10B981;
        padding: 4px 8px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.8em;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    
    @keyframes pulse-green-anim {
        0% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        }
        70% {
            transform: scale(1);
            box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
        }
        100% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
        }
    }
    @keyframes pulse-yellow-anim {
        0% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.7);
        }
        70% {
            transform: scale(1);
            box-shadow: 0 0 0 6px rgba(245, 158, 11, 0);
        }
        100% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(245, 158, 11, 0);
        }
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def safe_float(v, default=0.0):
    if v is None or v == "":
        return default
    try:
        if isinstance(v, str):
            v = v.replace(",", "").replace("%", "").strip()
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

@st.cache_data(ttl=300)
def load_ticker_pool():
    """Load and cache ticker list from the All Tickers worksheet on MAS Staging."""
    try:
        sh = sheets_repository._get_client().open_by_key(config.MARKET_ALPHA_SPREADSHEET_ID)
        ws = sh.worksheet("All Tickers")
        vals = ws.get_all_values()
        if not vals:
            return pd.DataFrame()
            
        headers = [h.strip() for h in vals[0]]
        col_idx = {h: i for i, h in enumerate(headers)}
        
        if "Ticker" not in col_idx:
            st.error("Column 'Ticker' not found in All Tickers worksheet.")
            return pd.DataFrame()
            
        records = []
        for r in vals[1:]:
            ticker = r[col_idx["Ticker"]].strip()
            if not ticker:
                continue
                
            row_dict = {}
            for col_i, h in enumerate(headers):
                val = r[col_i].strip() if col_i < len(r) else ""
                row_dict[h] = val
            records.append(row_dict)
            
        df = pd.DataFrame(records)
        df["Clean Ticker"] = df["Ticker"].str.upper().str.replace("IDX:", "", regex=False).str.strip()
        return df
    except Exception as e:
        st.error(f"Failed to load tickers from Google Sheets: {e}")
        return pd.DataFrame()

# ============================================================================
# MULTI-SOURCE FRESHNESS & FALLBACK ENGINE
# ============================================================================
def fetch_gsheet_source(symbol: str, hist_row: dict) -> dict:
    try:
        raw_ts = hist_row.get("Last Update", "")
        source_ts = None
        if raw_ts:
            try:
                dt = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
                source_ts = WIB.localize(dt)
            except ValueError:
                pass
                
        return {
            "last": safe_float(hist_row.get("Price")),
            "open": safe_float(hist_row.get("PriceOpen")),
            "high": safe_float(hist_row.get("High")),
            "low": safe_float(hist_row.get("Low")),
            "volume": safe_float(hist_row.get("Volume")),
            "prev_close": safe_float(hist_row.get("ClosePrev")),
            "source_ts": source_ts,
            "error": None
        }
    except Exception as e:
        return {"source_ts": None, "error": str(e)}

def fetch_yfinance_source(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(f"{symbol}.JK")
        info = ticker.info
        
        reg_ts = info.get("regularMarketTime")
        source_ts = datetime.fromtimestamp(reg_ts, tz=pytz.utc).astimezone(WIB) if reg_ts else None
        
        return {
            "last": info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose"),
            "open": info.get("regularMarketOpen"),
            "high": info.get("regularMarketDayHigh"),
            "low": info.get("regularMarketDayLow"),
            "volume": info.get("regularMarketVolume"),
            "prev_close": info.get("regularMarketPreviousClose"),
            "source_ts": source_ts,
            "error": None
        }
    except Exception as e:
        return {"source_ts": None, "error": str(e)}

def fetch_idx_source(symbol: str, idx_summary_dict: dict = None) -> dict:
    try:
        item = None
        if idx_summary_dict is not None:
            item = idx_summary_dict.get(symbol)
        else:
            # Fallback to single fetch if not provided in batch
            url = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
            headers = {
                "Referer": "https://www.idx.co.id",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            }
            r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
            if r.status_code == 200:
                data = r.json()
                for x in data.get("data", []):
                    if x.get("StockCode", "").upper().strip() == symbol:
                        item = x
                        break
        
        if not item:
            return {"source_ts": None, "error": "Symbol not found in IDX trading summary"}
            
        raw_ts = item.get("Date") or item.get("LastUpdateTime", "")
        source_ts = None
        if raw_ts:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(raw_ts, fmt)
                    source_ts = WIB.localize(dt)
                    break
                except ValueError:
                    continue
                    
        return {
            "last": safe_float(item.get("Close")) or safe_float(item.get("Previous")),
            "open": safe_float(item.get("OpenPrice")),
            "high": safe_float(item.get("High")),
            "low": safe_float(item.get("Low")),
            "volume": safe_float(item.get("Volume")),
            "prev_close": safe_float(item.get("Previous")),
            "frequency": safe_float(item.get("Frequency")),
            "value": safe_float(item.get("Value")),
            "foreign_buy": safe_float(item.get("ForeignBuy")),
            "foreign_sell": safe_float(item.get("ForeignSell")),
            "source_ts": source_ts,
            "error": None
        }
    except Exception as e:
        return {"source_ts": None, "error": str(e)}

def pick_freshest_source(symbol: str, hist_row: dict, idx_summary_dict: dict = None) -> dict:
    """Compare freshness timestamps of GSheet, yfinance, and IDX endpoint to select the best winner."""
    gsheet_res = fetch_gsheet_source(symbol, hist_row)
    yfinance_res = fetch_yfinance_source(symbol)
    idx_res = fetch_idx_source(symbol, idx_summary_dict)
    
    sources = []
    def is_valid(res):
        return res.get("error") is None and res.get("last") is not None and res.get("last") > 0
        
    if is_valid(gsheet_res):
        sources.append({"name": "gsheet", "res": gsheet_res, "ts": gsheet_res["source_ts"]})
    if is_valid(yfinance_res):
        sources.append({"name": "yfinance", "res": yfinance_res, "ts": yfinance_res["source_ts"]})
    if is_valid(idx_res):
        sources.append({"name": "idx_endpoint", "res": idx_res, "ts": idx_res["source_ts"]})
        
    if not sources:
        # Fallback to gsheet row cache
        return {
            "last": safe_float(hist_row.get("Price")),
            "open": safe_float(hist_row.get("PriceOpen")),
            "high": safe_float(hist_row.get("High")),
            "low": safe_float(hist_row.get("Low")),
            "volume": safe_float(hist_row.get("Volume")),
            "prev_close": safe_float(hist_row.get("ClosePrev")),
            "frequency": safe_float(hist_row.get("Frequency", 0)),
            "value": safe_float(hist_row.get("Value", 0)) if safe_float(hist_row.get("Value", 0)) > 0 else (safe_float(hist_row.get("Price")) * safe_float(hist_row.get("Volume")) * 100),
            "foreign_buy": 0.0,
            "foreign_sell": 0.0,
            "source": "gsheet_fallback",
            "source_ts": None,
            "report": "All sources failed, fallback to GSheets row values"
        }
        
    now_wib = datetime.now(WIB)
    fresh_sources = []
    
    for s in sources:
        ts = s["ts"]
        if ts:
            age_minutes = (now_wib - ts).total_seconds() / 60
        else:
            age_minutes = float("inf")
            
        threshold = 5.0 if s["name"] == "idx_endpoint" else 25.0
        if age_minutes <= threshold:
            fresh_sources.append(s)
            
    pool = fresh_sources if fresh_sources else sources
    winner = max(pool, key=lambda x: x["ts"].timestamp() if x["ts"] else 0.0)
    
    res = winner["res"]
    age_str = f"{round((now_wib - winner['ts']).total_seconds()/60, 1)}m ago" if winner["ts"] else "N/A"
    return {
        "last": res["last"],
        "open": res["open"],
        "high": res["high"],
        "low": res["low"],
        "volume": res["volume"],
        "prev_close": res["prev_close"],
        "frequency": res.get("frequency", 0.0),
        "value": res.get("value", 0.0),
        "foreign_buy": res.get("foreign_buy", 0.0),
        "foreign_sell": res.get("foreign_sell", 0.0),
        "source": winner["name"],
        "source_ts": winner["ts"],
        "report": f"{winner['name']} ({age_str})"
    }

async def fetch_screener_batch(tickers: list[str], ticker_df: pd.DataFrame, delay_sec: float):
    """Fetch data for multiple tickers concurrently using our freshness logic."""
    results = {}
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 1. Pre-fetch IDX summaries in a single batch request
    idx_summary_dict = {}
    status_text.text("Pre-fetching IDX trading summaries in batch...")
    try:
        url = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
        headers = {
            "Referer": "https://www.idx.co.id",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        r = await asyncio.to_thread(
            requests_cf.get, url, headers=headers, timeout=15, impersonate="chrome"
        )
        if r.status_code == 200:
            raw_data = r.json()
            for item in raw_data.get("data", []):
                code = item.get("StockCode", "").upper().strip()
                if code:
                    idx_summary_dict[code] = item
            logger.info(f"Successfully pre-fetched {len(idx_summary_dict)} IDX stock summaries in batch.")
        else:
            logger.warning(f"Failed to pre-fetch IDX summaries: status {r.status_code}")
    except Exception as e:
        logger.warning(f"Failed to pre-fetch IDX summaries: {e}")
        
    total = len(tickers)
    sem = asyncio.Semaphore(5)  # Limit concurrency to 5 tickers at a time
    
    async def fetch_single_ticker(ticker, hist_row):
        async with sem:
            # yfinance fetching is blocking so we run it in a thread pool
            winner_data = await asyncio.to_thread(pick_freshest_source, ticker, hist_row, idx_summary_dict)
            return ticker, winner_data

    # Create tasks for all tickers
    tasks = []
    for ticker in tickers:
        hist_rows_matched = ticker_df[ticker_df["Clean Ticker"] == ticker]
        if not hist_rows_matched.empty:
            hist_row = hist_rows_matched.iloc[0].to_dict()
        else:
            hist_row = {}
        tasks.append(fetch_single_ticker(ticker, hist_row))
        
    completed = 0
    # As each task completes, update results and progress
    for future in asyncio.as_completed(tasks):
        ticker, winner_data = await future
        if winner_data:
            results[ticker] = winner_data
        completed += 1
        progress_bar.progress(completed / total)
        status_text.text(f"Scanning tickers: {completed}/{total} completed...")
        # Tiny delay to spread out API requests
        await asyncio.sleep(delay_sec)
        
    progress_bar.empty()
    status_text.empty()
    return results

# ============================================================================
# MODULAR IMPORTS: SCORING & NARRATIVES
# ============================================================================
from data.scoring import compute_intraday_score


# ============================================================================
# MAIN INTERFACE
# ============================================================================
st.title("📈 IDX Intraday Multi-Source Screener [IRW]")
render_status_board()

# ============================================================================
# IHSG DATA FETCH WITH FALLBACKS
# ============================================================================

@st.cache_data(ttl=60)
def fetch_ihsg_yfinance() -> dict | None:
    """Primary: yfinance IHSG with 5m intraday sparkline."""
    try:
        idx = yf.Ticker("^JKSE")
        hist_intraday = idx.history(period="1d", interval="5m")
        hist_daily    = idx.history(period="2d", interval="1d")
        if hist_intraday.empty or hist_daily.empty or len(hist_daily) < 2:
            return None
        curr  = float(hist_intraday["Close"].iloc[-1])
        prev  = float(hist_daily["Close"].iloc[-2])
        return _build_ihsg_result(hist_intraday, curr, prev, "Yahoo Finance")
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_ihsg_yahoo_api() -> dict | None:
    """Fallback 1: direct Yahoo Finance REST API (bypasses yfinance library)."""
    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE?"
            "interval=5m&range=1d&includePrePost=false"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests_cf.get(url, headers=headers, timeout=15, impersonate="chrome")

        if r.status_code != 200:
            return None
        data = r.json()
        result = data.get("chart", {}).get("result", [{}])[0]
        meta   = result.get("meta", {})
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        closes = quotes.get("close", [])
        opens  = quotes.get("open", [])

        if not closes or not timestamps:
            return None

        # Filter out None closes
        valid = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
        if not valid:
            return None

        times, prices = zip(*valid)
        curr = prices[-1]
        prev = meta.get("previousClose", 0) or prices[0]

        # Build a pseudo-DataFrame for _build_ihsg_result compatibility
        import pandas as pd
        df = pd.DataFrame({
            "Close": list(prices),
            "Open":  [o or 0 for o in opens[:len(prices)]],
            "High":  [max(prices[i:i+5]) if i+5 < len(prices) else prices[-1] for i in range(len(prices))],
            "Low":   [min(prices[i:i+5]) if i+5 < len(prices) else prices[-1] for i in range(len(prices))],
            "Volume": [0] * len(prices),
        })
        df.index = pd.to_datetime([t for t in times], unit="s")
        return _build_ihsg_result(df, curr, prev, "Yahoo Finance API")
    except Exception:
        return None


@st.cache_data(ttl=120)
def fetch_ihsg_google_finance() -> dict | None:
    """
    Fallback 2: Google Finance scrape for IHSG.
    Only returns current price/change — no sparkline.
    """
    try:
        url = "https://www.google.com/finance/quote/IDX_COMPOSITE:IDX?hl=en"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
        }
        r = requests_cf.get(url, headers=headers, timeout=15, impersonate="chrome")
        if r.status_code != 200:
            return None

        import re, bs4
        soup = bs4.BeautifulSoup(r.text, "html.parser")

        # Robust selector: data-last-price attribute or standard YMlKec class
        price_el = soup.select_one("[data-last-price]") or soup.select_one(".YMlKec")
        if not price_el:
            return None

        if price_el.has_attr("data-last-price"):
            price = float(price_el["data-last-price"])
        else:
            price_text = price_el.get_text(strip=True).replace(",", "")
            price_match = re.search(r"(\d+[\d.]*)", price_text)
            if not price_match:
                return None
            price = float(price_match.group(1))

        # Change element parsing
        change_el = soup.select_one("[data-last-normal-market-change]") or soup.select_one(".P6K39c")
        if change_el and change_el.has_attr("data-last-normal-market-change"):
            change_val = float(change_el["data-last-normal-market-change"])
            # Pct change
            change_pct = 0.0
            pct_el = soup.select_one("[data-last-normal-market-change-percent]")
            if pct_el and pct_el.has_attr("data-last-normal-market-change-percent"):
                change_pct = float(pct_el["data-last-normal-market-change-percent"])
        else:
            change_text = change_el.get_text(strip=True) if change_el else "0"
            change_match = re.search(r"([+-]?\d+[\d,.]*)", change_text.replace(",", ""))
            change_val = float(change_match.group(1)) if change_match else 0.0
            
            pct_match = re.search(r"\(([+-]?\d+[\d,.]*)%\)", change_text)
            change_pct = float(pct_match.group(1)) if pct_match else 0.0

        prev_close = price - change_val

        return {
            "current":     price,
            "prev_close":  prev_close,
            "open":        None,
            "high":        None,
            "low":         None,
            "volume":      None,
            "change_abs":  change_val,
            "change_pct":  change_pct,
            "prices":      [],   # no sparkline data
            "times":       [],
            "source":      "Google Finance",
            "sparkline":   False,
        }
    except Exception:
        return None


def _build_ihsg_result(df, curr, prev, source: str) -> dict:
    """Build unified IHSG result dict from DataFrame."""
    opens = float(df["Open"].iloc[0]) if "Open" in df and not df["Open"].empty else curr
    highs = float(df["High"].max())
    lows  = float(df["Low"].min())
    vols  = float(df["Volume"].sum()) if "Volume" in df else 0
    prices = df["Close"].dropna().tolist()
    times  = [t.strftime("%H:%M") for t in df.index]
    return {
        "current":    curr,
        "prev_close": prev,
        "open":       opens,
        "high":       highs,
        "low":        lows,
        "volume":     vols,
        "change_abs": curr - prev,
        "change_pct": ((curr - prev) / prev) * 100,
        "prices":     prices,
        "times":      times,
        "source":     source,
        "sparkline":  True,
    }


def fetch_ihsg_data() -> dict | None:
    """
    Fetch IHSG data with cascading fallbacks.
    1. yfinance (full 5m sparkline)
    2. Yahoo Finance REST API (full 5m sparkline)
    3. Google Finance scrape (price/change only, no sparkline)
    """
    data = fetch_ihsg_yfinance()
    if data:
        return data

    data = fetch_ihsg_yahoo_api()
    if data:
        return data

    data = fetch_ihsg_google_finance()
    if data:
        return data

    return None


# ============================================================================
# IHSG LIVE CARD
# ============================================================================
ihsg = fetch_ihsg_data()
render_ihsg_widget(ihsg)

# ============================================================================
# ============================================================================
# DATA PIPELINE HEALTH MONITOR
# ============================================================================
st.markdown("##### 🛠️ Data Pipeline fallback health status")

# Determine real-time status dynamically based on connection flags
# 1. Google Sheets
gsheet_active = "load_ticker_pool" in globals() and bool(config.MARKET_ALPHA_SPREADSHEET_ID)
gs_bg = "rgba(16, 185, 129, 0.08)" if gsheet_active else "rgba(239, 68, 68, 0.08)"
gs_border = "rgba(16, 185, 129, 0.2)" if gsheet_active else "rgba(239, 68, 68, 0.2)"
gs_dot = "#10B981" if gsheet_active else "#EF4444"
gs_desc = "Primary registry active pool" if gsheet_active else "Registry connection error"

# 2. Yahoo Finance
yf_active = ihsg is not None and ihsg.get("source") in ("Yahoo Finance", "Yahoo Finance API")
yf_bg = "rgba(16, 185, 129, 0.08)" if yf_active else "rgba(245, 158, 11, 0.08)"
yf_border = "rgba(16, 185, 129, 0.2)" if yf_active else "rgba(245, 158, 11, 0.2)"
yf_dot = "#10B981" if yf_active else "#F59E0B"
yf_desc = f"Active Composite source ({ihsg.get('source', 'Offline') if ihsg else 'Offline'})" if yf_active else "Composite source degraded (Fallback active)"

# 3. Google Finance
gf_active = ihsg is not None and ihsg.get("source") == "Google Finance"
gf_bg = "rgba(16, 185, 129, 0.08)" if gf_active else "rgba(100, 116, 139, 0.08)"
gf_border = "rgba(16, 185, 129, 0.2)" if gf_active else "rgba(100, 116, 139, 0.2)"
gf_dot = "#10B981" if gf_active else "#64748B"
gf_desc = "Cascading scraper fallback (Active)" if gf_active else "Scraper idle (Standby)"

# 4. Exodus Stockbit API
sb_active = bool(config.STOCKBIT_BEARER_TOKEN or (config.STOCKBIT_USERNAME and config.STOCKBIT_PASSWORD))
sb_bg = "rgba(16, 185, 129, 0.08)" if sb_active else "rgba(239, 68, 68, 0.08)"
sb_border = "rgba(16, 185, 129, 0.2)" if sb_active else "rgba(239, 68, 68, 0.2)"
sb_dot = "#10B981" if sb_active else "#EF4444"
sb_desc = "Orderbook queue engine (Authorized)" if sb_active else "Unauthorized (Credentials missing)"

hc1, hc2, hc3, hc4 = st.columns(4)
with hc1:
    st.markdown(f"""
    <div style="background: {gs_bg}; border: 1px solid {gs_border}; padding: 8px 12px; border-radius: 8px;">
        <span style="color:{gs_dot}; font-weight:700; font-size:0.85em;">● Google Sheets</span>
        <div style="font-size:0.75em; color:#94A3B8;">{gs_desc}</div>
    </div>
    """, unsafe_allow_html=True)
with hc2:
    st.markdown(f"""
    <div style="background: {yf_bg}; border: 1px solid {yf_border}; padding: 8px 12px; border-radius: 8px;">
        <span style="color:{yf_dot}; font-weight:700; font-size:0.85em;">● Yahoo Finance</span>
        <div style="font-size:0.75em; color:#94A3B8;">{yf_desc}</div>
    </div>
    """, unsafe_allow_html=True)
with hc3:
    st.markdown(f"""
    <div style="background: {gf_bg}; border: 1px solid {gf_border}; padding: 8px 12px; border-radius: 8px;">
        <span style="color:{gf_dot}; font-weight:700; font-size:0.85em;">● Google Finance</span>
        <div style="font-size:0.75em; color:#94A3B8;">{gf_desc}</div>
    </div>
    """, unsafe_allow_html=True)
with hc4:
    st.markdown(f"""
    <div style="background: {sb_bg}; border: 1px solid {sb_border}; padding: 8px 12px; border-radius: 8px;">
        <span style="color:{sb_dot}; font-weight:700; font-size:0.85em;">● Exodus Stockbit API</span>
        <div style="font-size:0.75em; color:#94A3B8;">{sb_desc}</div>
    </div>
    """, unsafe_allow_html=True)
st.write("")

# Load database
ticker_df = load_ticker_pool()
if ticker_df.empty:
    st.warning("Ticker database is empty or spreadsheet is unreachable.")
    st.stop()

# Single source of truth for hist_lookup (O(N) vectorized map)
hist_lookup = ticker_df.set_index("Clean Ticker").to_dict(orient="index")

# Initialize session state for cached data
if "screener_data" not in st.session_state:
    st.session_state.screener_data = {}
if "last_fetch" not in st.session_state:
    st.session_state.last_fetch = None
if "custom_watchlist" not in st.session_state:
    st.session_state.custom_watchlist = sqlite_repository.get_watchlist()
if "portfolio" not in st.session_state:
    st.session_state.portfolio = sqlite_repository.get_portfolio()

# Populate screener_data with Google Sheets cached prices for all tickers
for _, row in ticker_df.iterrows():
    ticker = row["Clean Ticker"]
    if ticker not in st.session_state.screener_data:
        raw_ts = row.get("Last Update", "")
        source_ts = None
        if raw_ts:
            try:
                dt = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
                source_ts = WIB.localize(dt)
            except ValueError:
                pass
        st.session_state.screener_data[ticker] = {
            "last": safe_float(row.get("Price")),
            "open": safe_float(row.get("PriceOpen")),
            "high": safe_float(row.get("High")),
            "low": safe_float(row.get("Low")),
            "volume": safe_float(row.get("Volume")),
            "prev_close": safe_float(row.get("ClosePrev")),
            "source": "gsheet",
            "source_ts": source_ts,
            "report": "Initial load from Google Sheets"
        }

# ============================================================================
# SIDEBAR FILTERS
# ============================================================================
from ui.components.sidebar import render_sidebar
sidebar_data = render_sidebar(ticker_df, fetch_screener_batch)
fetch_delay = sidebar_data["fetch_delay"]
max_scan = sidebar_data["max_scan"]
selected_sectors = sidebar_data["selected_sectors"]
selected_ranks = sidebar_data["selected_ranks"]
min_score = sidebar_data["min_score"]
exclude_filters_trending = sidebar_data["exclude_filters_trending"]
exclude_filters_bsjp = sidebar_data["exclude_filters_bsjp"]
exclude_filters_minervini = sidebar_data["exclude_filters_minervini"]
search_ticker = sidebar_data["search_ticker"]

# ============================================================================
# FILTER TICKERS
# ============================================================================
filtered_df = ticker_df.copy()

if search_ticker:
    # pencarian eksplisit selalu menang, bypass semua filter lain
    filtered_df = filtered_df[filtered_df["Clean Ticker"] == search_ticker]
else:
    if selected_sectors:
        filtered_df = filtered_df[filtered_df["Sector"].isin(selected_sectors)]
    if selected_ranks:
        filtered_df = filtered_df[filtered_df["Rank"].isin(selected_ranks)]
    if min_score > 0:
        filtered_df = filtered_df[filtered_df["Score v2"].apply(safe_float) >= min_score]

display_list = filtered_df["Clean Ticker"].tolist()
cand_list = display_list[:max_scan]

st.subheader(f"📊 Displaying {len(display_list)} Tickers matching filters")
if display_list:
    st.write(f"Refresh Target (Top {len(cand_list)}):", ", ".join(cand_list))
    if len(display_list) > len(cand_list):
        st.caption(f"Note: Only the top {len(cand_list)} tickers will be updated live when clicking 'Refresh Live Feed' to avoid API rate limits.")
else:
    st.info("No tickers match the active filters. Adjust your criteria in the sidebar.")
    st.stop()

# ============================================================================
# SYNC / REFRESH TRIGGER
# ============================================================================
col_ref1, col_ref2, col_info = st.columns([1, 1, 2])
with col_ref1:
    if st.button("🔄 Refresh Live Feed (Multi)", use_container_width=True, help="Fetch via Google Sheets ➔ yfinance ➔ IDX Endpoint"):
        live_results = asyncio.run(fetch_screener_batch(cand_list, ticker_df, fetch_delay))
        st.session_state.screener_data.update(live_results)
        st.session_state.last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (Multi-Source)"
        st.rerun()

with col_ref2:
    sb_auth_ok = bool(config.STOCKBIT_BEARER_TOKEN or (config.STOCKBIT_USERNAME and config.STOCKBIT_PASSWORD))
    sb_help_text = "Fetch fresh price directly from Stockbit Exodus API" if sb_auth_ok else "Stockbit unavailable (Requires token or credentials in .env)"
    if st.button("🚀 Refresh Live Feed (Stockbit)", use_container_width=True, help=sb_help_text, disabled=not sb_auth_ok):
        # Helper batch fetcher for Stockbit prices specifically
        async def fetch_stockbit_screener_batch(tickers, df, delay):
            token = await auth_service.get_token()
            if not token:
                st.error("Failed to acquire Stockbit Exodus Auth Token!")
                return {}
            results = {}
            progress_bar = st.progress(0)
            status_text = st.empty()
            total = len(tickers)
            completed = 0
            
            for ticker in tickers:
                status_text.text(f"Fetching {ticker} directly from Stockbit...")
                provider = StockbitProvider(token)
                try:
                    snap = await provider.fetch_orderbook(ticker)
                    if snap:
                        results[ticker] = {
                            "last": snap.last_price,
                            "open": snap.open_price if snap.open_price else snap.last_price,
                            "high": snap.high if snap.high else snap.last_price,
                            "low": snap.low if snap.low else snap.last_price,
                            "volume": snap.volume,
                            "prev_close": snap.prev_close,
                            "source": "stockbit",
                            "source_ts": datetime.now(WIB),
                            "report": "Stockbit Exodus Live Direct"
                        }
                except Exception as exc:
                    logger.error(f"Stockbit batch scan error for {ticker}: {exc}")
                finally:
                    await provider.close()
                completed += 1
                progress_bar.progress(completed / total)
                await asyncio.sleep(delay)
            progress_bar.empty()
            status_text.empty()
            return results

        live_results = asyncio.run(fetch_stockbit_screener_batch(cand_list, ticker_df, fetch_delay))
        if live_results:
            st.session_state.screener_data.update(live_results)
            st.session_state.last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (Stockbit API)"
        st.rerun()

with col_info:
    # Trigger auto refresh if scheduled
    if st.session_state.get("trigger_auto_scan", False):
        st.session_state["trigger_auto_scan"] = False
        with st.spinner("⏳ Auto Refresh Triggered: Scanning multi-source feed..."):
            live_results = asyncio.run(fetch_screener_batch(cand_list, ticker_df, fetch_delay))
            st.session_state.screener_data.update(live_results)
            st.session_state.last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (Auto Multi-Source)"
        st.rerun()

    if st.session_state.last_fetch:
        st.caption(f"Last updated: {st.session_state.last_fetch} WIB.")
    else:
        st.info("Click a button to fetch price freshness tables.")

# ============================================================================
# SCREENER PROCESS & DATA EXTRACTION
# ============================================================================
scored_list = []
scored_list_global = []
if st.session_state.screener_data:
    
    # Global population for unfiltered tabs
    for ticker, data in st.session_state.screener_data.items():
        hist_row = hist_lookup.get(ticker)
        if hist_row:
            score_data = compute_intraday_score(data, hist_row)
            scored_list_global.append({
                "Ticker": ticker,
                "Company Name": hist_row.get("Company Name", ""),
                "Sector": hist_row.get("Sector", ""),
                "Live Price": data["last"],
                "Change %": score_data["change_pct"],
                "Vol Spike": score_data["vol_spike"],
                "Intraday Score": score_data["score"],
                "Live Signal": score_data["signal"],
                "Source Used": data["source"],
                "color": score_data["color"],
                "raw_data_obj": data,
                "hist_row_obj": hist_row,
                "frequency": data.get("frequency", 0.0),
                "value": data.get("value", 0.0),
                "foreign_buy": data.get("foreign_buy", 0.0),
                "foreign_sell": data.get("foreign_sell", 0.0)
            })

    # Sidebar Filtered population for general tabs
    for ticker in display_list:
        if ticker not in st.session_state.screener_data:
            continue
        data = st.session_state.screener_data[ticker]
        hist_row = hist_lookup.get(ticker)
        if not hist_row:
            continue
        
        score_data = compute_intraday_score(data, hist_row)
        scored_list.append({
            "Ticker": ticker,
            "Company Name": hist_row.get("Company Name", ""),
            "Sector": hist_row.get("Sector", ""),
            "Live Price": data["last"],
            "Change %": score_data["change_pct"],
            "Vol Spike": score_data["vol_spike"],
            "Intraday Score": score_data["score"],
            "Live Signal": score_data["signal"],
            "Source Used": data["source"],
            "color": score_data["color"],
            "raw_data_obj": data,
            "hist_row_obj": hist_row,
            "frequency": data.get("frequency", 0.0),
            "value": data.get("value", 0.0),
            "foreign_buy": data.get("foreign_buy", 0.0),
            "foreign_sell": data.get("foreign_sell", 0.0)
        })

# Calculate active total portfolio value dynamically
total_portfolio_value = 0.0
if st.session_state.portfolio:
    for asset in st.session_state.portfolio:
        ticker = asset["Ticker"]
        buy_price = asset["Buy Price"]
        lots = asset["Lots"]
        live_price = buy_price
        if ticker in hist_lookup:
            hist_row = hist_lookup[ticker]
            if ticker in st.session_state.screener_data:
                live_price = st.session_state.screener_data[ticker]["last"]
            else:
                live_price = safe_float(hist_row.get("Price"), buy_price)
        total_portfolio_value += live_price * lots * 100

# ============================================================================
# TABS SYSTEM SETUP
# ============================================================================
tab11, tab2, tab_wl, tab_port, tab7, tab3, tab4, tab5, tab9, tab6, tab8, tab10, tab1, tab_cal = st.tabs([
    "🏆 Top Picks",
    "🎯 Intraday Buy Recommendations",
    "⭐ Custom Watchlist",
    "💼 Live Portfolio Tracker",
    "🔍 Deep Stock Analysis (Exodus API)",
    "📊 General Screener Board",
    "🔥 Trending Stocks",
    "🌙 BSJP Recommendations",
    "🚀 Pre-ARA Momentum",
    "📈 Minervini Trend",
    "📰 News-Based Signals",
    "🌊 Elliott Wave",
    "📋 Active Tickers Pool",
    "📅 Corporate Calendar"
])

# ============================================================================
# TAB: CUSTOM WATCHLIST
# ============================================================================
with tab_wl:
    st.markdown("### ⭐ Custom Watchlist")
    st.caption("Search, add, and monitor custom tickers with live/cached metrics.")

    # Search and Add
    all_tickers = sorted(ticker_df["Clean Ticker"].unique().tolist())
    
    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        add_ticker_select = st.selectbox(
            "Search Emiten to Add",
            options=all_tickers,
            key="wl_add_select",
            help="Select ticker to add to watchlist."
        )
    with col_add2:
        st.write("") # Spacer
        st.write("") # Spacer
        if st.button("➕ Add to Watchlist", use_container_width=True):
            if add_ticker_select not in st.session_state.custom_watchlist:
                sqlite_repository.add_watchlist(add_ticker_select)
                st.session_state.custom_watchlist = sqlite_repository.get_watchlist()
                st.toast(f"Added {add_ticker_select} to watchlist! 🚀")
                st.rerun()
            else:
                st.warning(f"{add_ticker_select} is already in watchlist.")

    # Watchlist Table
    if st.session_state.custom_watchlist:
        wl_data = []
        
        for ticker in st.session_state.custom_watchlist:
            if ticker in hist_lookup:
                hist_row = hist_lookup[ticker]
                # Get live details if refreshed
                if ticker in st.session_state.screener_data:
                    raw_data = st.session_state.screener_data[ticker]
                    price = raw_data["last"]
                    prev_close = safe_float(hist_row.get("ClosePrev", price))
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
                    volume = raw_data.get("volume", 0)
                else:
                    price = safe_float(hist_row.get("Price"))
                    change_pct = safe_float(hist_row.get("Change%"))
                    volume = safe_float(hist_row.get("Volume"))
                
                wl_data.append({
                    "Ticker": ticker,
                    "Company Name": hist_row.get("Company Name", ""),
                    "Sector": hist_row.get("Sector", ""),
                    "Price": price,
                    "Change %": change_pct,
                    "Volume": volume,
                    "RSI14": safe_float(hist_row.get("RSI14")),
                    "Support": safe_float(hist_row.get("Support")),
                    "Breakout": safe_float(hist_row.get("Breakout"))
                })
        
        if wl_data:
            wl_df = pd.DataFrame(wl_data)
            st.dataframe(
                wl_df,
                column_config={
                    "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                    "Change %": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                    "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                    "RSI14": st.column_config.NumberColumn("RSI14", format="%.2f"),
                    "Support": st.column_config.NumberColumn("Support", format="IDR %d"),
                    "Breakout": st.column_config.NumberColumn("Resistance", format="IDR %d"),
                },
                use_container_width=True,
                hide_index=True
            )
            
            # Management (Remove individual or Clear All)
            col_rem1, col_rem2, col_rem3 = st.columns([2, 1, 1])
            with col_rem1:
                rem_ticker_select = st.selectbox(
                    "Select Ticker to Remove",
                    options=st.session_state.custom_watchlist,
                    key="wl_rem_select"
                )
            with col_rem2:
                st.write("") # Spacer
                st.write("") # Spacer
                if st.button("❌ Remove Selected", use_container_width=True):
                    sqlite_repository.remove_watchlist(rem_ticker_select)
                    st.session_state.custom_watchlist = sqlite_repository.get_watchlist()
                    st.toast(f"Removed {rem_ticker_select} from watchlist.")
                    st.rerun()
            with col_rem3:
                st.write("") # Spacer
                st.write("") # Spacer
                if st.button("🗑️ Clear Watchlist", use_container_width=True):
                    sqlite_repository.clear_watchlist()
                    st.session_state.custom_watchlist = []
                    st.toast("Watchlist cleared.")
                    st.rerun()
    else:
        st.info("Watchlist is currently empty. Use the search box above to add stocks.")

# ============================================================================
# TAB: LIVE PORTFOLIO TRACKER
# ============================================================================
with tab_port:
    st.markdown("### 💼 Live Portfolio Tracker")
    st.caption("Track your holding value, average buy price, and lots, compared against real-time feed.")

    # Search, Buy Price, and Lot inputs
    col_p1, col_p2, col_p3, col_p4 = st.columns([2, 1.2, 1.2, 1])
    with col_p1:
        port_ticker_select = st.selectbox(
            "Search Emiten",
            options=all_tickers,
            key="port_add_select",
            help="Select ticker to add to portfolio."
        )
    with col_p2:
        buy_price_input = st.number_input(
            "Buy Price (IDR)",
            min_value=1.0,
            value=100.0,
            step=10.0,
            key="port_buy_price"
        )
    with col_p3:
        lots_input = st.number_input(
            "Lots Size",
            min_value=1,
            value=10,
            step=1,
            key="port_lots"
        )
    with col_p4:
        st.write("") # Spacer
        st.write("") # Spacer
        if st.button("➕ Add Asset", use_container_width=True):
            # Check and clear old entry for this ticker before adding new
            sqlite_repository.remove_portfolio_by_ticker(port_ticker_select)
            sqlite_repository.add_portfolio(port_ticker_select, buy_price_input, lots_input)
            st.session_state.portfolio = sqlite_repository.get_portfolio()
            st.toast(f"Added {port_ticker_select} to portfolio!")
            st.rerun()

    # Portfolio table & computations
    if st.session_state.portfolio:
        port_rows = []
        total_invested = 0.0
        total_current_val = 0.0
        
        for asset in st.session_state.portfolio:
            ticker = asset["Ticker"]
            buy_price = asset["Buy Price"]
            lots = asset["Lots"]
            
            # Fetch live price
            live_price = buy_price
            if ticker in hist_lookup:
                hist_row = hist_lookup[ticker]
                if ticker in st.session_state.screener_data:
                    live_price = st.session_state.screener_data[ticker]["last"]
                else:
                    live_price = safe_float(hist_row.get("Price"), buy_price)
            
            invested_val = buy_price * lots * 100
            current_val = live_price * lots * 100
            gain_loss = current_val - invested_val
            gain_loss_pct = (live_price - buy_price) / buy_price * 100 if buy_price > 0 else 0.0
            
            total_invested += invested_val
            total_current_val += current_val
            
            port_rows.append({
                "Ticker": ticker,
                "Buy Price": buy_price,
                "Lots": lots,
                "Live Price": live_price,
                "Invested Value": invested_val,
                "Current Value": current_val,
                "Gain / Loss": gain_loss,
                "Gain / Loss %": gain_loss_pct
            })
            
        total_gain_loss = total_current_val - total_invested
        total_gain_loss_pct = total_gain_loss / total_invested * 100 if total_invested > 0 else 0.0
        
        # Summary widgets
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("Total Invested", f"Rp {total_invested:,.0f}")
        col_s2.metric("Total Value", f"Rp {total_current_val:,.0f}")
        
        # Color coding metrics for gain loss
        gl_label = f"Rp {total_gain_loss:+,.0f}"
        gl_pct_label = f"{total_gain_loss_pct:+.2f}%"
        col_s3.metric("Total Profit/Loss", gl_label, gl_pct_label)
        
        st.markdown("---")
        
        # Dataframe
        port_df = pd.DataFrame(port_rows)
        st.dataframe(
            port_df,
            column_config={
                "Buy Price": st.column_config.NumberColumn("Avg Buy Price", format="IDR %d"),
                "Lots": st.column_config.NumberColumn("Lots", format="%d"),
                "Live Price": st.column_config.NumberColumn("Live Price", format="IDR %d"),
                "Invested Value": st.column_config.NumberColumn("Invested Val", format="Rp %d"),
                "Current Value": st.column_config.NumberColumn("Current Val", format="Rp %d"),
                "Gain / Loss": st.column_config.NumberColumn("Profit / Loss", format="Rp %+d"),
                "Gain / Loss %": st.column_config.NumberColumn("P/L %", format="%+.2f%%"),
            },
            use_container_width=True,
            hide_index=True
        )
        
        # Portfolio Asset management
        col_prem1, col_prem2, col_prem3 = st.columns([2, 1, 1])
        with col_prem1:
            rem_asset_select = st.selectbox(
                "Select Asset to Remove",
                options=[a["Ticker"] for a in st.session_state.portfolio],
                key="port_rem_select"
            )
        with col_prem2:
            st.write("")
            st.write("")
            if st.button("❌ Remove Asset", use_container_width=True):
                sqlite_repository.remove_portfolio_by_ticker(rem_asset_select)
                st.session_state.portfolio = sqlite_repository.get_portfolio()
                st.toast(f"Removed {rem_asset_select} from portfolio.")
                st.rerun()
        with col_prem3:
            st.write("")
            st.write("")
            if st.button("🗑️ Reset Portfolio", use_container_width=True):
                sqlite_repository.clear_portfolio()
                st.session_state.portfolio = []
                st.toast("Portfolio cleared.")
                st.rerun()
    else:
        st.info("Portfolio is empty. Add assets using the fields above.")

    # ========================================================================
    # AVERAGE DOWN / DCA CALCULATOR
    # ========================================================================
    st.markdown("---")
    st.markdown("### 🔄 Average Down Calculator")
    st.caption(
        "Simulasikan dampak average down terhadap harga rata-rata, jarak breakeven, "
        "dan konsentrasi risiko sebelum eksekusi. Average down memperbesar eksposur "
        "di satu saham — gunakan dengan disiplin, bukan reaksi otomatis saat posisi rugi."
    )

    if st.session_state.portfolio:
        dca_ticker = st.selectbox(
            "Pilih posisi yang ingin di-average down",
            options=[a["Ticker"] for a in st.session_state.portfolio],
            key="dca_ticker_select"
        )
        asset = next(a for a in st.session_state.portfolio if a["Ticker"] == dca_ticker)
        old_avg = asset["Buy Price"]
        old_lots = asset["Lots"]
        live_price = st.session_state.screener_data.get(dca_ticker, {}).get("last", old_avg)

        dca_col1, dca_col2 = st.columns(2)
        with dca_col1:
            dca_price_mode = st.radio(
                "Harga beli tambahan", ["Live Price", "Custom"],
                horizontal=True, key="dca_price_mode"
            )
            dca_price = live_price if dca_price_mode == "Live Price" else st.number_input(
                "Harga custom (IDR)", min_value=1.0, value=float(live_price), step=1.0, key="dca_custom_price"
            )
        with dca_col2:
            dca_lots = st.number_input("Lot tambahan", min_value=1, value=old_lots, step=1, key="dca_lots_input")

        new_lots = old_lots + dca_lots
        new_invested = (old_avg * old_lots * 100) + (dca_price * dca_lots * 100)
        new_avg = new_invested / (new_lots * 100)
        breakeven_gap_pct = ((new_avg - live_price) / live_price * 100) if live_price > 0 else 0.0
        ticker_concentration = (new_invested / total_portfolio_value * 100) if total_portfolio_value > 0 else 0.0

        st.markdown("##### 📊 Hasil Simulasi")
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Avg Lama → Baru", f"Rp {old_avg:,.0f} → Rp {new_avg:,.0f}")
        rc2.metric("Total Lot Baru", f"{new_lots:,} lot")
        rc3.metric(
            "Jarak ke Breakeven", f"{breakeven_gap_pct:+.2f}%",
            help="Positif = live price masih perlu naik sekian % untuk balik modal dari avg baru."
        )
        rc4.metric("Konsentrasi di Ticker Ini", f"{ticker_concentration:.1f}%")

        if ticker_concentration > 25:
            st.warning(
                f"⚠️ Setelah average down, **{dca_ticker}** akan menyumbang "
                f"**{ticker_concentration:.1f}%** dari total portofolio — di atas batas "
                f"konsentrasi umum 25% per saham. Pertimbangkan ulang ukurannya."
            )

        if st.button("✅ Terapkan Average Down ke Portfolio", key="dca_apply_btn"):
            sqlite_repository.remove_portfolio_by_ticker(dca_ticker)
            sqlite_repository.add_portfolio(dca_ticker, round(new_avg, 2), new_lots)
            st.session_state.portfolio = sqlite_repository.get_portfolio()
            st.toast(f"Average down {dca_ticker} diterapkan! Avg baru: Rp {new_avg:,.0f}")
            st.rerun()
    else:
        st.info("Portfolio masih kosong — tambah posisi dulu di atas untuk pakai kalkulator ini.")

# ============================================================================
# TAB RENDERING PORTING
# ============================================================================
with tab1:
    from ui.tabs.tab1_live_feed import render_tab1
    render_tab1(ticker_df)

with tab2:
    from ui.tabs.tab2_recommendations import render_tab2
    render_tab2(scored_list)

with tab3:
    scalp_data, swing_data, lt_data = render_tab3(scored_list)

with tab4:
    trending_source_list = scored_list_global if exclude_filters_trending else scored_list
    trending_data = render_tab4(ticker_df, trending_source_list)

with tab5:
    from ui.tabs.tab5_bsjp import render_tab5
    bsjp_data = render_tab5(scored_list_global, scored_list, exclude_filters_bsjp)

with tab6:
    from ui.tabs.tab6_minervini import render_tab6
    minervini_data = render_tab6(scored_list_global, scored_list, exclude_filters_minervini, ihsg)

with tab7:
    render_tab7(ticker_df, scored_list, total_portfolio_value=total_portfolio_value)

with tab8:
    news_data = render_tab8(scored_list, ticker_df)

with tab9:
    pre_ara_data = render_tab9(scored_list)

with tab10:
    render_tab10(scored_list)

with tab11:
    from ui.tabs.tab11_top_picks import render_tab11
    render_tab11(
        scored_list,
        bsjp_data=bsjp_data,
        minervini_data=minervini_data,
        pre_ara_rows=pre_ara_data,
        trending_rows=trending_data,
        news_sentiment_rows=news_data
    )

with tab_cal:
    from ui.tabs.tab12_calendar import render_tab12
    render_tab12()

