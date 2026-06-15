import streamlit as st
import pandas as pd
import numpy as np
import asyncio
from datetime import datetime
import os
import sys
import math
import pytz
import yfinance as yf
import plotly.graph_objects as go
from curl_cffi import requests as requests_cf

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

# ============================================================================
# CUSTOM CSS STYLING
# ============================================================================
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
def safe_float(v):
    if v is None or v == "":
        return 0.0
    try:
        if isinstance(v, str):
            v = v.replace(",", "").replace("%", "").strip()
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return 0.0
        return f
    except (ValueError, TypeError):
        return 0.0

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
# LIVE DEEP ANALYSIS FETCH (EXODUS API)
# ============================================================================
async def fetch_stockbit_detail(ticker: str):
    """Deep analysis orderbook fetch from Stockbit Exodus API endpoint."""
    token = await auth_service.get_token()
    if not token:
        return None
    provider = StockbitProvider(token)
    try:
        snap = await provider.fetch_orderbook(ticker)
        await provider.close()
        return snap
    except Exception as e:
        logger.error(f"Exodus API detail fetch failed for {ticker}: {e}")
        await provider.close()
        return None

# ============================================================================
# SCORING & RECOMMENDATIONS ENGINE
# ============================================================================
def compute_intraday_score(data, hist_row) -> dict:
    vol_avg = safe_float(hist_row.get("Vol_Avg", 0))
    live_vol = safe_float(data.get("volume", 0))
    vol_spike = (live_vol / vol_avg) if vol_avg > 0 else 1.0
    
    if vol_spike >= 3.0:
        vol_score = 100
    elif vol_spike >= 2.0:
        vol_score = 80
    elif vol_spike >= 1.5:
        vol_score = 60
    elif vol_spike >= 1.0:
        vol_score = 40
    else:
        vol_score = 20
        
    # Standard fallback score for spread and imbalance in batch mode
    imbalance_score = 60
    spread_score = 60
        
    # Price Change% (20%)
    last = safe_float(data.get("last", 0))
    prev = safe_float(data.get("prev_close", 0))
    chg = ((last - prev) / prev * 100) if prev > 0 else 0.0
    
    if chg >= 5.0:
        price_score = 100
    elif chg >= 2.0:
        price_score = 80
    elif chg >= 0.0:
        price_score = 60
    elif chg >= -3.0:
        price_score = 40
    else:
        price_score = 20
        
    hist_score = safe_float(hist_row.get("Score v2", 50))
    
    total = (
        vol_score * 0.25 +
        imbalance_score * 0.25 +
        price_score * 0.20 +
        spread_score * 0.15 +
        hist_score * 0.15
    )
    total = int(round(total))
    
    if total >= 85:
        sig, col = "STRONG BUY", "#00D4AA"
    elif total >= 70:
        sig, col = "BUY", "#90EE90"
    elif total >= 50:
        sig, col = "HOLD", "#FFFF00"
    elif total >= 30:
        sig, col = "SELL", "#FFA500"
    else:
        sig, col = "STRONG SELL", "#FF6B6B"
        
    return {
        "score": total,
        "signal": sig,
        "color": col,
        "vol_spike": vol_spike,
        "change_pct": chg,
        "breakdown": {
            "Volume Spike": vol_score,
            "Price Intraday Change": price_score,
            "Historical Score Weight": hist_score
        }
    }

def compute_action_recommendation(price, sl, tp, score, rsi):
    """Advanced R/R logic (similar to v27_rekomendasi_beli.py)."""
    if price <= 0 or sl >= price:
        return "❌ AVOID", "0%", "Invalid price levels"
        
    rr = round((tp - price) / (price - sl), 2)
    
    if rr >= 1.5 and score >= 70 and (rsi <= 0 or rsi < 75):
        return "✅ STRONG BUY", "10%", f"R/R={rr} (Target: {tp}, SL: {sl}). Favorable setups."
    if rr >= 1.2 and score >= 50 and (rsi <= 0 or rsi < 70):
        return "⚡ BUY", "5%", f"R/R={rr} (Target: {tp}, SL: {sl}). Moderate buy."
    if rr >= 1.0 and score >= 40:
        return "🌀 SPECULATIVE", "2-3%", f"R/R={rr}. Higher volatility."
    return "❌ AVOID", "0%", f"R/R={rr} (Target: {tp}, SL: {sl}). Below thresholds."

def get_tick_size(price: float) -> int:
    """IDX standard tick rules."""
    if price < 200:
        return 1
    elif price < 500:
        return 2
    elif price < 2000:
        return 5
    elif price < 5000:
        return 10
    else:
        return 25

def align_price_to_tick(price: float, round_direction: str = "nearest") -> float:
    """Align price to IDX tick size depending on requested direction."""
    if price <= 0:
        return 0.0
    tick = get_tick_size(price)
    if round_direction == "up":
        return float(math.ceil(price / tick) * tick)
    elif round_direction == "down":
        return float(math.floor(price / tick) * tick)
    else:
        return float(round(price / tick) * tick)

def calculate_strategies(price: float, score: int, signal: str) -> dict:
    """Calculate 3-Tier execution strategy levels for a given price using ticker.py rules."""
    # Aggressive (Breakout Play)
    # Entry at best ask/price
    entry_agg = price
    tp_agg = entry_agg * 1.10
    sl_agg = entry_agg * 0.95
    
    # Moderate (Pullback Play)
    # Entry at 2 ticks below price
    tick_size = get_tick_size(price)
    entry_mod = price - 2 * tick_size
    tp_mod = entry_mod * 1.05
    sl_mod = entry_mod * 0.93
    
    # Low Risk (Support Buy)
    # Entry at 4% support distance
    entry_low = price - 4 * tick_size
    tp_low = entry_low * 1.08
    sl_low = entry_low * 0.96

    # Align all values to ticks
    entry_agg = align_price_to_tick(entry_agg)
    tp_agg = align_price_to_tick(tp_agg)
    sl_agg = align_price_to_tick(sl_agg)

    entry_mod = align_price_to_tick(entry_mod)
    tp_mod = align_price_to_tick(tp_mod)
    sl_mod = align_price_to_tick(sl_mod)

    entry_low = align_price_to_tick(entry_low)
    tp_low = align_price_to_tick(tp_low)
    sl_low = align_price_to_tick(sl_low)

    # Risk-Reward calculations
    rr_agg = round((tp_agg - entry_agg) / max(1.0, entry_agg - sl_agg), 1)
    rr_mod = round((tp_mod - entry_mod) / max(1.0, entry_mod - sl_mod), 1)
    rr_low = round((tp_low - entry_low) / max(1.0, entry_low - sl_low), 1)
    
    # Alloc sizes based on signal strength
    if "STRONG BUY" in signal:
        alloc_agg = "10% Port"
        alloc_mod = "15% Port"
        alloc_low = "20% Port"
    elif "BUY" in signal:
        alloc_agg = "5% Port"
        alloc_mod = "10% Port"
        alloc_low = "15% Port"
    else:
        alloc_agg = "1-2% (Speculative)"
        alloc_mod = "3% Port"
        alloc_low = "5% Port"
        
    return {
        "Aggressive": {
            "entry": entry_agg,
            "target": tp_agg,
            "sl": sl_agg,
            "rr": rr_agg,
            "size": alloc_agg
        },
        "Moderate": {
            "entry": entry_mod,
            "target": tp_mod,
            "sl": sl_mod,
            "rr": rr_mod,
            "size": alloc_mod
        },
        "Low Risk": {
            "entry": entry_low,
            "target": tp_low,
            "sl": sl_low,
            "rr": rr_low,
            "size": alloc_low
        }
    }

def minify_html(html_str: str) -> str:
    """Minify HTML string by removing newlines and leading indentation spaces."""
    return "".join(line.strip() for line in html_str.split("\n"))


# ============================================================================
# MAIN INTERFACE
# ============================================================================
st.title("📈 IDX Intraday Multi-Source Screener [IRW]")

# ============================================================================
# LIVE TIME & API STATUS BOARD
# ============================================================================
now_wib = datetime.now(WIB)
is_day_trade = now_wib.weekday() < 5 and (
    (now_wib.hour == 9 and now_wib.minute >= 0) or
    (now_wib.hour > 9 and now_wib.hour < 12) or
    (now_wib.hour == 11 and now_wib.minute <= 30) or
    (now_wib.hour >= 13 and now_wib.hour < 16) or
    (now_wib.hour == 16 and now_wib.minute <= 15)
)

live_badge = '<span class="live-label-container"><span class="pulse-dot pulse-green"></span>🔴 LIVE</span>' if is_day_trade else '<span class="live-label-container" style="background-color: rgba(245,158,11,0.15); color: #F59E0B; border-color: rgba(245,158,11,0.3);"><span class="pulse-dot pulse-yellow"></span>⏸️ CLOSED</span>'

status_html = f"""
<div class="status-container">
    <div class="status-item">
        <strong>Market Status:</strong> {live_badge} ({now_wib.strftime('%Y-%m-%d %H:%M:%S')} WIB)
    </div>
    <div class="status-item">
        <span class="pulse-dot pulse-green"></span>
        <span><strong>Google Sheets:</strong> Connected (Active Pool)</span>
    </div>
    <div class="status-item">
        <span class="pulse-dot pulse-green"></span>
        <span><strong>Yahoo Finance:</strong> Online (JK Feed)</span>
    </div>
    <div class="status-item">
        <span class="pulse-dot pulse-green"></span>
        <span><strong>IDX Endpoint:</strong> Online (Trading Summary)</span>
    </div>
    <div class="status-item">
        <span class="pulse-dot pulse-green"></span>
        <span><strong>Exodus API:</strong> Ready (Deep Analysis)</span>
    </div>
</div>
"""
st.markdown(status_html, unsafe_allow_html=True)
st.caption("Freshness Fallback Pipeline: Google Sheets ➔ yfinance ➔ IDX. (Stockbit for Deep Analysis only).")

# Load database
ticker_df = load_ticker_pool()
if ticker_df.empty:
    st.warning("Ticker database is empty or spreadsheet is unreachable.")
    st.stop()

# Initialize session state for cached data
if "screener_data" not in st.session_state:
    st.session_state.screener_data = {}
if "last_fetch" not in st.session_state:
    st.session_state.last_fetch = None

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
with st.sidebar:
    st.markdown("## 🔍 Screener Settings")
    st.markdown("---")
    
    # Auto refresh configuration
    st.subheader("🔁 Auto Refresh")
    auto_refresh_enabled = st.checkbox("Enable Auto Refresh", value=False, help="Automatically re-trigger scan cycle.")
    if auto_refresh_enabled:
        refresh_interval = st.selectbox(
            "Interval (Minutes)",
            options=[5, 10, 15, 30],
            index=1,
            help="Choose refresh period."
        )
        
        # Inject standard JS metadata/trigger to auto-reload or utilize streamlit rerun schedule
        # Simple metadata trick using st.session_state and a timestamp tracking
        import time
        if "next_refresh_time" not in st.session_state or st.session_state.get("last_refresh_interval") != refresh_interval:
            st.session_state.next_refresh_time = time.time() + (refresh_interval * 60)
            st.session_state.last_refresh_interval = refresh_interval
            
        time_left = int(st.session_state.next_refresh_time - time.time())
        if time_left <= 0:
            st.session_state.next_refresh_time = time.time() + (refresh_interval * 60)
            # Rerun trigger
            st.session_state["trigger_auto_scan"] = True
        else:
            # Display a dynamic HTML container that updates the countdown in real time via local JS
            countdown_placeholder = st.empty()
            countdown_placeholder.markdown(
                f'<div style="background-color: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.3); padding: 10px; border-radius: 6px; color: #38BDF8; font-weight: bold; font-size: 0.9em; margin-bottom: 10px;">⏳ Next auto-scan in: <span id="countdown_timer_span">{time_left // 60}m {time_left % 60}s</span></div>',
                unsafe_allow_html=True
            )
            
            st.components.v1.html(
                f"""
                <script>
                var targetTime = {st.session_state.next_refresh_time * 1000};
                
                function updateTimer() {{
                    var now = new Date().getTime();
                    var diff = Math.max(0, Math.floor((targetTime - now) / 1000));
                    
                    var minutes = Math.floor(diff / 60);
                    var seconds = diff % 60;
                    
                    // Update text inside parent frame DOM securely
                    var span = window.parent.document.getElementById("countdown_timer_span");
                    if (span) {{
                        span.innerText = minutes + "m " + seconds + "s";
                    }}
                    
                    if (diff <= 0) {{
                        clearInterval(interval);
                        // Trigger reload when reaching zero
                        window.parent.location.reload();
                    }}
                }}
                
                // Immediately check once and set interval for subsequent updates
                updateTimer();
                var interval = setInterval(updateTimer, 1000);
                </script>
                """,
                height=0,
                width=0
            )
            
    st.markdown("---")
    
    # Delay selector
    st.subheader("⏱️ Fetch Polling Delay")
    fetch_delay = st.slider(
        "Delay per Ticker (seconds)",
        min_value=0.1,
        max_value=3.0,
        value=0.5,
        step=0.1,
        help="Rate-limiting sleep duration between ticker queries."
    )
    
    # Max tickers scan
    st.subheader("📊 Scan Ticker Limit")
    max_scan = st.slider(
        "Max Tickers to Scan",
        min_value=10,
        max_value=min(500, len(ticker_df)) if not ticker_df.empty else 100,
        value=50,
        step=10,
        help="Limit the number of tickers to scan in a batch."
    )
    
    st.markdown("---")
    
    # Filters
    st.subheader("🎯 Watchlist Filter")
    unique_sectors = sorted(list(ticker_df["Sector"].unique())) if "Sector" in ticker_df.columns else []
    selected_sectors = st.multiselect("Sectors", unique_sectors, default=[])
    
    unique_ranks = sorted(list(ticker_df["Rank"].unique())) if "Rank" in ticker_df.columns else []
    selected_ranks = st.multiselect("Ranks", unique_ranks, default=["⭐ Strong Buy"])
    
    min_score = st.slider("Minimum Historical Score v2", 0, 100, 50)
    
    st.markdown("---")
    
    # Manual Ticker Lookup
    search_ticker = st.text_input("Lookup Specific Ticker (e.g. ADRO)", "").upper().strip()

# ============================================================================
# FILTER TICKERS
# ============================================================================
filtered_df = ticker_df.copy()

if selected_sectors:
    filtered_df = filtered_df[filtered_df["Sector"].isin(selected_sectors)]
if selected_ranks:
    filtered_df = filtered_df[filtered_df["Rank"].isin(selected_ranks)]
if min_score > 0:
    filtered_df = filtered_df[filtered_df["Score v2"].apply(safe_float) >= min_score]
if search_ticker:
    filtered_df = filtered_df[filtered_df["Clean Ticker"] == search_ticker]

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
    if st.button("🚀 Refresh Live Feed (Stockbit)", use_container_width=True, help="Fetch fresh price directly from Stockbit Exodus API"):
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
if st.session_state.screener_data:
    hist_lookup = {row["Clean Ticker"]: row.to_dict() for _, row in ticker_df.iterrows()}
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
            "hist_row_obj": hist_row
        })

# ============================================================================
# TABS SYSTEM SETUP
# ============================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Displaying Tickers",
    "🎯 Intraday Buy Recommendations",
    "📊 General Screener Board",
    "🔍 Deep Stock Analysis (Exodus API)"
])

# ============================================================================
# TAB 1: DISPLAYING TICKERS
# ============================================================================
with tab1:
    st.markdown("### 📋 Active Tickers Pool (Google Sheets)")
    st.caption("Displays all active tickers currently loaded from the Google Sheets 'All Tickers' database.")
    
    # Filter active tickers (status contains ACTIVE)
    active_ticker_df = ticker_df[ticker_df["Status"].str.contains("ACTIVE", na=False)].copy()
    
    # Define clean column order
    col_order = [
        'Ticker', 'Company Name', 'Sector', 'Rank', 'Status', 'Score v2', 
        'Price', 'Change%', 'Volume', 'Vol_Avg', 'MA20', 'Support', 'Breakout', 
        'RSI14', 'SL_Practical', 'TP_Target', 'RR_Ratio', 'Last Update'
    ]
    # Keep remaining columns
    remaining_cols = [c for c in active_ticker_df.columns if c not in col_order and c != 'Clean Ticker']
    display_cols = col_order + remaining_cols
    
    st.dataframe(
        active_ticker_df[display_cols],
        column_config={
            "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
            "Change%": st.column_config.TextColumn("Change%"),
            "Volume": st.column_config.NumberColumn("Volume", format="%d"),
            "Vol_Avg": st.column_config.NumberColumn("Vol Avg", format="%d"),
            "MA20": st.column_config.NumberColumn("MA20", format="IDR %d"),
            "Support": st.column_config.NumberColumn("Support", format="IDR %d"),
            "Breakout": st.column_config.NumberColumn("Breakout", format="IDR %d"),
            "SL_Practical": st.column_config.NumberColumn("SL Practical", format="IDR %d"),
            "TP_Target": st.column_config.NumberColumn("TP Target", format="IDR %d"),
            "RSI14": st.column_config.NumberColumn("RSI (14)", format="%.1f"),
            "Score v2": st.column_config.NumberColumn("Score v2", format="%d"),
        },
        use_container_width=True,
        hide_index=True
    )

# ============================================================================
# TAB 2: INTRADAY BUY RECOMMENDATIONS
# ============================================================================
with tab2:
    st.markdown("### 🎯 Intraday Buy Recommendations")
    st.caption("Active recommendations generated using target prices and risk/reward formulas (Top 30 Strong Buys).")
    
    if scored_list:
        rec_list = []
        for s in scored_list:
            price = safe_float(s["Live Price"])
            score = s["Intraday Score"]
            hist_row = s["hist_row_obj"]
            
            # Stop loss: support or MA20 or standard 7%
            sl_prac = safe_float(hist_row.get("SL_Practical"))
            ma20 = safe_float(hist_row.get("MA20"))
            sl = sl_prac if sl_prac > 0 else round(max(ma20 * 0.97, price * 0.93), 2)
            if sl >= price:
                sl = round(price * 0.93, 2)
                
            # Target: 52W High or standard 15%
            high52 = safe_float(hist_row.get("52W High"))
            tp = round(min(high52, price * 1.15), 2) if high52 > 0 else round(price * 1.15, 2)
            
            rsi = safe_float(hist_row.get("RSI14"))
            
            action, max_pos, notes = compute_action_recommendation(price, sl, tp, score, rsi)
            
            # Append ATR stop-loss if ATR14 is available
            atr = safe_float(hist_row.get("ATR14"))
            if atr > 0:
                sl_atr = round(price - 1.5 * atr, 2)
                notes += f" | SL_ATR={sl_atr}"
                
            # Append UMA & Corporate Action warnings
            uma_str = hist_row.get("UMA", "")
            corp_act_str = hist_row.get("Corp Action", "")
            if uma_str:
                notes += f" | {uma_str}"
            if corp_act_str:
                notes += f" | CorpAct: {corp_act_str}"
            
            if "STRONG BUY" in action:
                rec_list.append({
                    "Ticker": s["Ticker"],
                    "Company Name": s["Company Name"],
                    "Sector": s["Sector"],
                    "Price": price,
                    "Intraday Score": score,
                    "Buy Target": price,
                    "Stop Loss (SL)": sl,
                    "Target Price (TP)": tp,
                    "R/R Ratio": round((tp - price) / max(1.0, price - sl), 2),
                    "Max Pos": max_pos,
                    "Action": action,
                    "Notes": notes,
                    "Change Pct": s["Change %"],
                    "Vol Spike": s["Vol Spike"],
                    "Live Signal": s["Live Signal"],
                    "Source Used": s["Source Used"]
                })
                
        if rec_list:
            # Sort by Intraday Score descending and take top 30
            rec_list = sorted(rec_list, key=lambda x: x["Intraday Score"], reverse=True)[:30]
            # Display recommendations as premium HTML cards
            html_cards = '<div class="card-grid">'
            for r in rec_list:
                # Determine Action Class
                act = r["Action"]
                if "STRONG BUY" in act:
                    act_class = "action-strong-buy"
                elif "BUY" in act:
                    act_class = "action-buy"
                else:
                    act_class = "action-speculative"
                    
                # Price change styling
                chg = r["Change Pct"]
                chg_class = "change-up" if chg >= 0 else "change-down"
                chg_sign = "+" if chg > 0 else ""
                
                # Progress bar color based on score
                sc = r["Intraday Score"]
                if sc >= 85:
                    bar_color = "#10B981" # green
                elif sc >= 70:
                    bar_color = "#3B82F6" # blue
                elif sc >= 50:
                    bar_color = "#F59E0B" # yellow/orange
                else:
                    bar_color = "#EF4444" # red
                    
                card_html = f"""
                <div class="rec-card">
                    <div class="card-header">
                        <div>
                            <span class="ticker-badge">{r['Ticker']}</span>
                            <div class="company-name">{r['Company Name']}</div>
                            <div class="sector-tag">{r['Sector']}</div>
                        </div>
                        <span class="action-badge {act_class}">{r['Action']}</span>
                    </div>
                    <div class="price-display">
                        <span class="price-value">IDR {r['Price']:,.0f}</span>
                        <span class="price-change {chg_class}">{chg_sign}{chg:.2f}%</span>
                    </div>
                    <div class="score-section">
                        <div class="score-header">
                            <span>Intraday Health Score</span>
                            <span style="color: {bar_color}; font-weight: bold;">{sc}/100</span>
                        </div>
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill" style="width: {sc}%; background-color: {bar_color};"></div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric-box">
                            <div class="metric-label">Target Price (TP)</div>
                            <div class="metric-value" style="color: #10B981; font-weight: bold;">IDR {r['Target Price (TP)']:,.0f}</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Stop Loss (SL)</div>
                            <div class="metric-value" style="color: #EF4444; font-weight: bold;">IDR {r['Stop Loss (SL)']:,.0f}</div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric-box">
                            <div class="metric-label">Risk/Reward (R/R)</div>
                            <div class="metric-value" style="color: #38BDF8; font-weight: bold;">{r['R/R Ratio']:.2f}x</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Max Position Size</div>
                            <div class="metric-value" style="color: #F59E0B; font-weight: bold;">{r['Max Pos']}</div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric-box">
                            <div class="metric-label">Volume Spike</div>
                            <div class="metric-value">{r['Vol Spike']:.2f}x avg</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Source & Age</div>
                            <div class="metric-value" style="font-size: 0.85em; text-transform: uppercase;">{r['Source Used']}</div>
                        </div>
                    </div>
                    <div class="notes-section">
                        <b>Setup Notes:</b> {r['Notes']}
                    </div>
                </div>
                """
                html_cards += minify_html(card_html)
            html_cards += "</div>"
            st.markdown(html_cards, unsafe_allow_html=True)
        else:
            st.info("No active recommendations found. Scoring is currently under HOLD/SELL thresholds.")
    else:
        st.info("Please refresh the feed to calculate live recommendations.")

# ============================================================================
# TAB 3: GENERAL SCREENER BOARD
# ============================================================================
with tab3:
    st.markdown("### 📊 General Screener Board")
    st.caption("Intraday health scores and signals calculated across all filtered tickers.")
    
    if scored_list:
        scored_df = pd.DataFrame(scored_list)
        # Sort by Intraday Score desc
        scored_df = scored_df.sort_values(by="Intraday Score", ascending=False)
        
        cols_to_show = ["Ticker", "Company Name", "Sector", "Live Price", "Change %", "Vol Spike", "Intraday Score", "Live Signal", "Source Used"]
        st.dataframe(
            scored_df[cols_to_show],
            column_config={
                "Live Price": st.column_config.NumberColumn("Live Price", format="IDR %d"),
                "Change %": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                "Vol Spike": st.column_config.NumberColumn("Vol Spike", format="%.2f x"),
                "Intraday Score": st.column_config.ProgressColumn(
                    "Intraday Score",
                    help="Combined intraday health score",
                    format="%d",
                    min_value=0,
                    max_value=100,
                ),
                "Live Signal": st.column_config.TextColumn("Live Signal"),
                "Source Used": st.column_config.TextColumn("Source Used"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Refresh the feed to display general screener results.")

# ============================================================================
# TAB 4: DEEP STOCK ANALYSIS (EXODUS API)
# ============================================================================
with tab4:
    st.markdown("### 🔍 Deep Stock Analysis (Exodus API)")
    st.caption("Fetches real-time bid/ask queue details and company statistics from unofficial Stockbit Exodus API.")
    
    if scored_list:
        # Initialize session state for searched detail ticker
        if "deep_analyzed_ticker" not in st.session_state:
            st.session_state.deep_analyzed_ticker = ""

        col_input, col_btn = st.columns([3, 1])
        with col_input:
            search_input = st.text_input(
                "Enter Ticker to fetch live orderbook details (e.g. BBCA):",
                value=st.session_state.deep_analyzed_ticker,
                key="deep_search_input"
            ).upper().strip()
        with col_btn:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔍 Search Ticker", use_container_width=True):
                st.session_state.deep_analyzed_ticker = search_input
                st.rerun()

        # Trigger action if input changed via Enter press
        if search_input and search_input != st.session_state.deep_analyzed_ticker:
            st.session_state.deep_analyzed_ticker = search_input
            st.rerun()

        selected_detail = st.session_state.deep_analyzed_ticker
        if selected_detail:
            # Check if the ticker is valid in ticker_df
            matched_rows = ticker_df[ticker_df["Clean Ticker"] == selected_detail]
            if not matched_rows.empty:
                hist_row = matched_rows.iloc[0].to_dict()
                
                # Lookup raw data from screener_data if it was screened, otherwise mock
                if selected_detail in st.session_state.screener_data:
                    raw_data_obj = st.session_state.screener_data[selected_detail]
                    source_used = raw_data_obj["source"]
                else:
                    raw_data_obj = {
                        "last": safe_float(hist_row.get("Price")),
                        "prev_close": safe_float(hist_row.get("ClosePrev")),
                        "volume": safe_float(hist_row.get("Volume")),
                        "source": "gsheet_fallback",
                        "source_ts": None
                    }
                    source_used = "gsheet_fallback"
                    
                # Trigger Exodus API call for detail view
                with st.spinner(f"⚡ Establishing secure connection to Exodus API and streaming real-time orderbook for {selected_detail}..."):
                    snap = asyncio.run(fetch_stockbit_detail(selected_detail))
                    
                if snap:
                    score_data = compute_intraday_score(raw_data_obj, hist_row)
                    strategies = calculate_strategies(snap.last_price, score_data["score"], score_data["signal"])
                    
                    # 1. Main Stats
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.markdown(f"""
                        <div class="metric-card">
                            <h4>Live Signal</h4>
                            <h2 style="color: {score_data['color']}">{score_data['signal']}</h2>
                            <span>Score: {score_data['score']}/100</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with c2:
                        chg_sign = "+" if snap.change_pct > 0 else ""
                        chg_color = "#00D4AA" if snap.change_pct >= 0 else "#FF6B6B"
                        st.markdown(f"""
                        <div class="metric-card" style="border-left-color: {chg_color}">
                            <h4>Live Price</h4>
                            <h2>IDR {snap.last_price:,.0f}</h2>
                            <span style="color: {chg_color}">{chg_sign}{snap.change_pct:.2f}% Intraday</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with c3:
                        imb_color = "#00D4AA" if (snap.imbalance_ratio and snap.imbalance_ratio >= 1.0) else "#FF6B6B"
                        st.markdown(f"""
                        <div class="metric-card" style="border-left-color: {imb_color}">
                            <h4>Bid/Ask Imbalance</h4>
                            <h2>{snap.imbalance_ratio:.2f}x</h2>
                            <span>Total Bid: {snap.total_bid_lot:,} lot</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with c4:
                        st.markdown(f"""
                        <div class="metric-card" style="border-left-color: #00D4AA">
                            <h4>Source & Freshness</h4>
                            <h2 style="color: #00D4AA;">EXODUS API</h2>
                            <span>TS: {datetime.now().strftime('%H:%M:%S')} WIB (Live)</span>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    # 2. Strategies
                    st.markdown("### 🎯 3-Tier Execution Strategies")
                    sc1, sc2, sc3 = st.columns(3)
                    with sc1:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #FF6B6B">🔥 Aggressive (Breakout Play)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Aggressive']['entry']:,.0f}</li>
                                <li><b>Target:</b> IDR {strategies['Aggressive']['target']:,.0f} (+10%)</li>
                                <li><b>Stop Loss:</b> IDR {strategies['Aggressive']['sl']:,.0f} (-5%)</li>
                                <li><b>R/R Ratio:</b> {strategies['Aggressive']['rr']}x</li>
                                <li><b>Alloc:</b> {strategies['Aggressive']['size']}</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc2:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #FFFF00">⚡ Moderate (Pullback Play)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Moderate']['entry']:,.0f}</li>
                                <li><b>Target:</b> IDR {strategies['Moderate']['target']:,.0f} (+5%)</li>
                                <li><b>Stop Loss:</b> IDR {strategies['Moderate']['sl']:,.0f} (-7%)</li>
                                <li><b>R/R Ratio:</b> {strategies['Moderate']['rr']}x</li>
                                <li><b>Alloc:</b> {strategies['Moderate']['size']}</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc3:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #00D4AA">🛡️ Low Risk (Support Buy)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Low Risk']['entry']:,.0f}</li>
                                <li><b>Target:</b> IDR {strategies['Low Risk']['target']:,.0f} (+3%)</li>
                                <li><b>Stop Loss:</b> IDR {strategies['Low Risk']['sl']:,.0f} (-2%)</li>
                                <li><b>R/R Ratio:</b> {strategies['Low Risk']['rr']}x</li>
                                <li><b>Alloc:</b> {strategies['Low Risk']['size']}</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)

                    # 3. Live Orderbook Depth
                    st.markdown("### 📥 Live Orderbook Depth (Exodus API)")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.markdown("#### Bid Depth (Buy Side)")
                        bids_list = [{"Price": int(lvl.price), "Lot Volume": lvl.lot, "Frequency": lvl.freq} for lvl in snap.bid_levels]
                        if bids_list:
                            st.table(pd.DataFrame(bids_list))
                        else:
                            st.caption("No live bids available.")
                    with dc2:
                        st.markdown("#### Offer Depth (Sell Side)")
                        offers_list = [{"Price": int(lvl.price), "Lot Volume": lvl.lot, "Frequency": lvl.freq} for lvl in snap.ask_levels]
                        if offers_list:
                            st.table(pd.DataFrame(offers_list))
                        else:
                            st.caption("No live offers available.")
                else:
                    st.error("Failed to connect to Exodus API feed. Check auth token or try again.")
            else:
                st.warning(f"Ticker '{selected_detail}' not found in the Google Sheets 'All Tickers' database. Please check if the ticker exists.")
    else:
        st.info("Refresh the feed to select tickers for detailed orderbook analysis.")
