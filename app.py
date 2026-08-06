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
from ui.tabs.tab3_screener import render_tab3
from ui.tabs.tab7_deep_analysis import render_tab7
from ui.tabs.tab8_news_signals import render_tab8
from ui.tabs.tab_pick_of_the_day import render_tab_pick_of_the_day
from ui.tabs.tab_watchlist_portfolio import render_tab_watchlist_portfolio
from ui.components.elliott_wave_view import render_elliott_wave_view
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
    page_title="StockPick IDX",
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
    """Load and cache ticker list from Google Sheets, with local CSV fallback to prevent API rate limits."""
    backup_path = "data/ticker_pool_backup.csv"
    try:
        sh = sheets_repository._get_client().open_by_key(config.MARKET_ALPHA_SPREADSHEET_ID)
        ws = sh.worksheet("All Tickers")
        vals = ws.get_all_values()
        if not vals:
            raise ValueError("All Tickers worksheet is empty")
            
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
        
        # Save local backup on successful fetch
        try:
            os.makedirs("data", exist_ok=True)
            df.to_csv(backup_path, index=False)
            logger.info("Successfully updated local ticker pool registry cache backup.")
        except Exception as cache_err:
            logger.warning(f"Failed to save local ticker pool registry cache: {cache_err}")
            
        return df
    except Exception as e:
        logger.warning(f"Failed to load tickers from Google Sheets (falling back to local cache): {e}")
        # Local Fallback
        if os.path.exists(backup_path):
            try:
                df = pd.read_csv(backup_path)
                # Ensure correct formatting types
                df = df.fillna("")
                for col in df.columns:
                    df[col] = df[col].astype(str)
                df["Clean Ticker"] = df["Ticker"].str.upper().str.replace("IDX:", "", regex=False).str.strip()
                st.warning("⚠️ Google Sheets API Quota exceeded or error. Menggunakan registry offline dari local cache backup.")
                return df
            except Exception as fallback_err:
                st.error(f"Fallback to local cache failed: {fallback_err}")
        
        st.error(f"Failed to load tickers from Google Sheets: {e}")
        return pd.DataFrame()

# ============================================================================
# MULTI-SOURCE FRESHNESS & FALLBACK ENGINE (canonical async version lives in
# data/fetchers.py — see pick_freshest_source / fetch_stockbit_quote_source)
# ============================================================================

async def fetch_screener_batch(tickers: list[str], ticker_df: pd.DataFrame, delay_sec: float, hist_lookup: dict = None):
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
    
    # Ensure hist_lookup is pre-built
    _lookup = hist_lookup or ticker_df.set_index("Clean Ticker").to_dict(orient="index")
    
    async def fetch_single_ticker(ticker, hist_row):
        async with sem:
            winner_data = await pick_freshest_source(ticker, hist_row, idx_summary_dict)
            return ticker, winner_data

    # Create tasks for all tickers
    tasks = []
    for ticker in tickers:
        hist_row = _lookup.get(ticker, {})
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
from data.fetchers import pick_freshest_source
from data.scoring import compute_intraday_score, minify_html


# ============================================================================
# MAIN INTERFACE
# ============================================================================
# The app header (brand + status board + IHSG widget) is assembled further
# down, once the live status flags (gsheet/yf/gf/exodus) are known.

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


# ── APP HEADER (brand + live status board + IHSG) — renders FIRST so the
# ── page is visible while the data pipeline below is still connecting ────
st.markdown("""
<div class="app-brand">
    <div class="app-brand-left">
        <div class="app-brand-logo">📈</div>
        <div>
            <div class="app-brand-title">StockPick IDX</div>
            <div class="app-brand-sub">Realtime IDX Screener — Unified Mega Score + Tier</div>
        </div>
    </div>
    <div class="app-brand-tag">IDX Composite · Jakarta</div>
</div>
""", unsafe_allow_html=True)
status_ph = st.empty()
ihsg_ph = st.empty()
sb_active = bool(config.STOCKBIT_BEARER_TOKEN or (config.STOCKBIT_USERNAME and config.STOCKBIT_PASSWORD))
provisional_statuses = {
    "Google Sheets":  {"active": None, "desc": "Menghubungkan ke registry…"},
    "Yahoo Finance":  {"active": None, "desc": "Menghubungkan ke komposit…"},
    "Google Finance": {"active": None, "desc": "Scraper standby…"},
    "Exodus API":     {"active": sb_active,
                       "desc": "Orderbook queue engine (Authorized)" if sb_active else "Unauthorized (Credentials missing)"},
}
render_status_board(provisional_statuses, container=status_ph)
render_ihsg_widget(None, container=ihsg_ph, loading=True)
st.write("")
st.write("")

# ============================================================================
# IHSG LIVE CARD + DATA PIPELINE HEALTH (loads after the header)
# ============================================================================
ihsg = fetch_ihsg_data()

# Load database
ticker_df = load_ticker_pool()
if ticker_df.empty:
    st.warning("Ticker database is empty or spreadsheet is unreachable.")
    st.stop()

# Determine real-time status dynamically based on connection flags
# 1. Google Sheets
gsheet_active = not ticker_df.empty
gs_desc = "Primary registry active pool" if gsheet_active else "Registry connection error"

# 2. Yahoo Finance
yf_active = ihsg is not None and ihsg.get("source") in ("Yahoo Finance", "Yahoo Finance API")
yf_desc = f"Active Composite source ({ihsg.get('source', 'Offline') if ihsg else 'Offline'})" if yf_active else "Composite source degraded (Fallback active)"

# 3. Google Finance
gf_active = ihsg is not None and ihsg.get("source") == "Google Finance"
gf_desc = "Cascading scraper fallback (Active)" if gf_active else "Scraper idle (Standby)"

# 4. Exodus Stockbit API
sb_desc = "Orderbook queue engine (Authorized)" if sb_active else "Unauthorized (Credentials missing)"

api_statuses = {
    "Google Sheets":   {"active": gsheet_active, "desc": gs_desc},
    "Yahoo Finance":   {"active": yf_active, "desc": yf_desc},
    "Google Finance":  {"active": gf_active, "desc": gf_desc},
    "Exodus API":      {"active": sb_active, "desc": sb_desc},
}

# Replace the provisional header cards with real data.
render_status_board(api_statuses, container=status_ph)
render_ihsg_widget(ihsg, container=ihsg_ph)

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
            "report": f"gsheet ({raw_ts})" if raw_ts else "gsheet"
        }

# ============================================================================
# SIDEBAR FILTERS & TICKERS FILTERING
# ============================================================================
from ui.components.sidebar import render_sidebar
sidebar_data = render_sidebar(ticker_df, fetch_screener_batch)
fetch_delay = sidebar_data["fetch_delay"]
max_scan = sidebar_data["max_scan"]
selected_sectors = sidebar_data["selected_sectors"]
selected_ranks = sidebar_data["selected_ranks"]
min_score = sidebar_data["min_score"]
search_ticker = sidebar_data["search_ticker"]

filtered_df = ticker_df.copy()
if search_ticker:
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

if display_list:
    chips = "".join(
        f'<span class="ticker-chip">{t}</span>' for t in cand_list
    )
    note = ""
    if len(display_list) > len(cand_list):
        note = (
            '<div class="filter-summary-note">Note: Only the top '
            f"<b>{len(cand_list)}</b> tickers will be updated live when "
            "clicking 'Refresh Live Feed' to avoid API rate limits.</div>"
        )
    st.markdown(minify_html(f"""
    <div class="filter-summary">
        <div class="filter-summary-head">
            <span class="filter-summary-title">📊 Displaying <b>{len(display_list)}</b> tickers matching filters</span>
            <span class="filter-summary-pill">Refresh target: top {len(cand_list)}</span>
        </div>
        <div class="ticker-chips">{chips}</div>
        {note}
    </div>
    """), unsafe_allow_html=True)
else:
    st.info("No tickers match the active filters. Adjust your criteria in the sidebar.")
    st.stop()

# ============================================================================
# SYNC / REFRESH TRIGGER
# ============================================================================
col_ref1, col_ref2, col_info = st.columns([1, 1, 2])
with col_ref1:
    if st.button("🔄 Refresh Live Feed (Multi)", use_container_width=True, help="Fetch via Google Sheets ➔ yfinance ➔ IDX Endpoint"):
        live_results = asyncio.run(fetch_screener_batch(cand_list, ticker_df, fetch_delay, hist_lookup))
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
            live_results = asyncio.run(fetch_screener_batch(cand_list, ticker_df, fetch_delay, hist_lookup))
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
            try:
                # Cooldown-deduped: only log when the signal changed, so repeated
                # Streamlit reruns don't bloat scan_history or churn the cache key
                # used by the Pick of the Day track-record forward returns.
                sqlite_repository.save_scan_history_if_changed(
                    ticker, data["last"], score_data["score"], score_data["signal"], data.get("source", "unknown")
                )
            except Exception as exc:
                logger.warning(f"save_scan_history failed for {ticker}: {exc}")
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
# PICK OF THE DAY — PRE-COMPUTED MEGA SCORE (memoized on screener fingerprint)
#
# Streamlit reruns this script on every interaction, so a filter toggle inside
# the Pick of the Day tab used to recompute every signal bundle. The mega rows
# only depend on the fetched screener data, so we gate the build behind a
# fingerprint of that data — filter reruns reuse the cached rows and stay fast.
# ============================================================================
from data.signal_bundle import (
    build_bsjp_rows,
    build_minervini_rows,
    build_pre_ara_rows,
    build_trending_rows,
)
from data.mega_score import compute_mega_score, HORIZON_WEIGHTS


def _mega_fingerprint(screener_data, last_fetch, nonce) -> str:
    """Stable signature of the fetched screener data (cheap, plain Python)."""
    parts = [str(last_fetch), str(nonce)]
    for ticker in sorted(screener_data):
        d = screener_data[ticker]
        parts.append(f"{ticker}:{d.get('last')}:{d.get('source')}:{d.get('source_ts')}")
    return "|".join(parts)


def _build_mega_rows(scored_list) -> dict:
    """Per-horizon Mega Score ranking. News sentiment is intentionally NOT
    fetched here — the News tab owns the (expensive) news pipeline, so loading
    this landing view never pays the 6-source scrape + per-ticker yfinance cost.
    `compute_mega_score` flags the missing news signal as defaulted (50)."""
    bsjp_data = build_bsjp_rows(scored_list)
    minervini_data = build_minervini_rows(scored_list)
    pre_ara_rows = build_pre_ara_rows(scored_list)
    trending_rows = build_trending_rows(scored_list)

    lookup_bsjp = {r["Ticker"]: safe_float(r["Setup Score"]) for r in bsjp_data}
    lookup_min = {
        r["Ticker"]: (100.0 if "PASSED" in r["Passed Template"] else safe_float(r["score_int"]) / 8 * 100)
        for r in minervini_data
    }
    lookup_preara = {r["Ticker"]: safe_float(r["Pre-ARA Score"]) for r in pre_ara_rows}
    lookup_trend = {r["Ticker"]: safe_float(r["Trending Score"]) for r in trending_rows}

    has_bsjp = set(lookup_bsjp)
    has_min = {r["Ticker"] for r in minervini_data if "PASSED" in r["Passed Template"]}
    has_ara = set(lookup_preara)
    has_trend = set(lookup_trend)

    mega_rows = {}
    for horizon in HORIZON_WEIGHTS:
        rows = []
        for s in scored_list:
            t = s["Ticker"]
            signals = {
                "intraday_score": safe_float(s["Intraday Score"]),
                "hist_score": safe_float(s["hist_row_obj"].get("Score v2", 50)),
                "bsjp_score": safe_float(lookup_bsjp.get(t, 50)),
                "minervini_score": safe_float(lookup_min.get(t, 50)),
                "pre_ara_score": safe_float(lookup_preara.get(t, 50)),
                "trending_score": safe_float(lookup_trend.get(t, 50)),
            }
            mega = compute_mega_score(signals, horizon)
            rows.append({
                "Ticker": t,
                "Company": s["Company Name"],
                "Sector": s["Sector"],
                "Price": s["Live Price"],
                "Change %": s["Change %"],
                "Vol Spike": s["Vol Spike"],
                "Source": s["Source Used"],
                "Signal": s["Live Signal"],
                "color": s["color"],
                "Mega Score": mega["score"],
                "Tier": mega["tier"],
                "breakdown": mega["breakdown"],
                "available": mega["available"],
                "defaulted": mega["defaulted"],
                "confidence": mega["confidence"],
                "has_bsjp": t in has_bsjp,
                "has_minervini": t in has_min,
                "has_pre_ara": t in has_ara,
                "has_trending": t in has_trend,
                "hist_row_obj": s["hist_row_obj"],
                "raw_data_obj": s["raw_data_obj"],
            })
        rows.sort(key=lambda r: r["Mega Score"], reverse=True)
        mega_rows[horizon] = rows
    return mega_rows


if "mega_fingerprint" not in st.session_state:
    st.session_state.mega_fingerprint = None
if "mega_recompute" not in st.session_state:
    st.session_state.mega_recompute = 0

mega_fingerprint = _mega_fingerprint(
    st.session_state.screener_data,
    st.session_state.last_fetch,
    st.session_state.mega_recompute,
)


# ============================================================================
# PAGE NAVIGATION — lazy per-page rendering (replaces st.tabs)
#
# st.tabs renders every tab body on every rerun, so the News fetch, the Deep
# Dive API calls, and the signal bundles all paid their network cost even when
# the user was on another tab. Here only the selected page's code runs —
# clicking "📰 News Signals" is what triggers its auto-fetch.
# ============================================================================
PAGES = [
    "🏆 Pick of the Day",
    "📋 Watchlist + Portfolio",
    "🔍 Deep Dive",
    "📊 General Screener",
    "📰 News Signals",
    "📅 Corporate Calendar",
]
selected_page = st.pills(
    "Navigasi",
    options=PAGES,
    default=PAGES[0],
    key="page_select",
    label_visibility="collapsed",
)

# ── PAGE: PICK OF THE DAY (landing) — memoized Mega Score, computed lazily ──
if selected_page == PAGES[0]:
    if st.session_state.screener_data and scored_list_global:
        if mega_fingerprint != st.session_state.get("mega_fingerprint") or not st.session_state.get("mega_rows"):
            with st.status("🏆 Menyusun Pick of the Day — menghitung sinyal...", expanded=False) as status:
                try:
                    st.session_state.mega_rows = _build_mega_rows(scored_list_global)
                    st.session_state.mega_fingerprint = mega_fingerprint
                except Exception as exc:
                    logger.warning(f"signal bundle computation failed: {exc}")
                    st.session_state.mega_rows = {}
                if status is not None:
                    status.update(label="✅ Sinyal Pick of the Day siap", state="complete")
    else:
        st.session_state.mega_rows = {}
    render_tab_pick_of_the_day(total_portfolio_value=total_portfolio_value)

# ── PAGE: WATCHLIST + PORTFOLIO ──────────────────────────────────────────
elif selected_page == PAGES[1]:
    render_tab_watchlist_portfolio(
        ticker_df,
        hist_lookup,
        total_portfolio_value=total_portfolio_value,
    )

# ── PAGE: DEEP DIVE (Deep Analysis + Elliott Wave) ───────────────────────
elif selected_page == PAGES[2]:
    render_tab7(ticker_df, scored_list, total_portfolio_value=total_portfolio_value)
    with st.expander("🌊 Elliott Wave Analysis", expanded=False):
        render_elliott_wave_view(scored_list)

# ── PAGE: GENERAL SCREENER ───────────────────────────────────────────────
elif selected_page == PAGES[3]:
    render_tab3(scored_list)

# ── PAGE: NEWS SIGNALS — auto-fetches when opened (page-gated) ───────────
elif selected_page == PAGES[4]:
    render_tab8(scored_list, ticker_df)

# ── PAGE: CORPORATE CALENDAR ─────────────────────────────────────────────
elif selected_page == PAGES[5]:
    from ui.tabs.tab12_calendar import render_tab12
    render_tab12()
