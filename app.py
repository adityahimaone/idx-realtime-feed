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

async def fetch_stockbit_trending():
    """Fetch live trending stocks list from unofficial Stockbit Exodus API."""
    token = await auth_service.get_token()
    if not token:
        return []
    url = "https://exodus.stockbit.com/trending/stocks"
    headers = {
        "Authorization": f"Bearer {token}",
        "Referer": "https://stockbit.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    try:
        r = await asyncio.to_thread(
            requests_cf.get, url, headers=headers, timeout=15, impersonate="chrome"
        )
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception as e:
        logger.error(f"Exodus API trending fetch failed: {e}")
    return []

# fetch_ihsg_data() defined below with multi-source fallback


@st.cache_data(ttl=300)
def fetch_news_for_tickers(ticker_list):
    """Fetch yfinance news for a list of IDX tickers."""
    results = {}
    positive_kw = ['naik', 'tumbuh', 'laba', 'positif', 'dividen', 'akuisisi', 'ekspansi', 'profit', 'growth', 'rise', 'gain', 'upgrade', 'buy', 'bullish', 'outperform']
    negative_kw = ['turun', 'rugi', 'gagal', 'krisis', 'kasus', 'utang', 'debt', 'loss', 'downgrade', 'sell', 'bearish', 'crash', 'tunda', 'henti']
    
    for ticker in ticker_list:
        try:
            stock = yf.Ticker(f"{ticker}.JK")
            news = stock.news
            if news and isinstance(news, list):
                headlines = [article.get('title', '') for article in news[:5]]
                sentiment = 0
                for title in headlines:
                    title_l = title.lower()
                    sentiment += sum(1 for kw in positive_kw if kw in title_l)
                    sentiment -= sum(1 for kw in negative_kw if kw in title_l)
                
                results[ticker] = {
                    'count': len(headlines),
                    'latest': headlines[0] if headlines else '',
                    'sentiment': sentiment / len(headlines) if headlines else 0
                }
        except Exception:
            pass
    return results


# ============================================================================
# MACRO THEME DEFINITIONS & TICKER CORRELATION MAP
# ============================================================================
MACRO_THEMES = {
    "fed_rate_hike": {
        "label": "The Fed Naikkan Suku Bunga",
        "icon": "🏦",
        "keywords": ["fed rate", "federal reserve", "rate hike", "suku bunga naik", "interest rate hike", "hawkish fed", "fomc hike"],
        "impact": "negative",
        "narrative": "Kenaikan suku bunga Fed → dollar menguat, capital outflow dari emerging market → tekanan di saham perbankan, properti, dan konsumer.",
        "positive_sectors": ["banking_usd_heavy"],
        "negative_tickers": ["BBCA", "BBRI", "BMRI", "BBNI", "BSDE", "SMRA", "CTRA", "ASRI", "LPKR", "UNVR", "ICBP", "MYOR"],
        "positive_tickers": [],
    },
    "fed_rate_cut": {
        "label": "The Fed Pangkas Suku Bunga",
        "icon": "📉",
        "keywords": ["fed rate cut", "rate cut", "dovish fed", "suku bunga turun", "interest rate cut", "fomc cut", "fed pivot"],
        "impact": "positive",
        "narrative": "Pemotongan suku bunga Fed → dollar melemah, capital inflow ke emerging market → positif untuk perbankan, properti, konsumer.",
        "negative_tickers": [],
        "positive_tickers": ["BBCA", "BBRI", "BMRI", "BBNI", "BSDE", "SMRA", "CTRA", "ASRI", "UNVR", "ICBP", "MYOR"],
    },
    "gold_up": {
        "label": "Harga Emas Naik",
        "icon": "🥇",
        "keywords": ["gold rise", "gold price up", "emas naik", "harga emas melonjak", "gold rally", "xau naik", "emas menguat"],
        "impact": "positive",
        "narrative": "Harga emas naik → emiten tambang emas dan komoditas logam mulia diuntungkan.",
        "negative_tickers": [],
        "positive_tickers": ["ANTM", "EMAS", "ARCI", "MDKA", "BRMS", "PSAB"],
    },
    "gold_down": {
        "label": "Harga Emas Turun",
        "icon": "📉",
        "keywords": ["gold fall", "gold price down", "emas turun", "harga emas anjlok", "gold drops", "xau turun", "emas melemah"],
        "impact": "negative",
        "narrative": "Harga emas turun → emiten tambang emas dan logam mulia tertekan.",
        "negative_tickers": ["ANTM", "EMAS", "ARCI", "MDKA", "BRMS", "PSAB"],
        "positive_tickers": [],
    },
    "coal_up": {
        "label": "Harga Batu Bara Naik",
        "icon": "⚫",
        "keywords": ["coal price up", "batu bara naik", "harga batu bara melonjak", "coal rally", "thermal coal up"],
        "impact": "positive",
        "narrative": "Harga batu bara naik → emiten produsen batu bara diuntungkan secara langsung.",
        "negative_tickers": [],
        "positive_tickers": ["ADRO", "PTBA", "ITMG", "HRUM", "BSSR", "INDY", "PTRO", "DEWA"],
    },
    "coal_down": {
        "label": "Harga Batu Bara Turun",
        "icon": "📉",
        "keywords": ["coal price down", "batu bara turun", "harga batu bara anjlok", "coal drops", "thermal coal down"],
        "impact": "negative",
        "narrative": "Harga batu bara turun → emiten batu bara tertekan, margin ekspor menyusut.",
        "negative_tickers": ["ADRO", "PTBA", "ITMG", "HRUM", "BSSR", "INDY", "PTRO", "DEWA"],
        "positive_tickers": [],
    },
    "cpo_up": {
        "label": "Harga CPO/Sawit Naik",
        "icon": "🌴",
        "keywords": ["cpo price up", "palm oil up", "sawit naik", "harga cpo naik", "crude palm oil rise"],
        "impact": "positive",
        "narrative": "Harga CPO naik → emiten perkebunan sawit dan hilir kelapa sawit diuntungkan.",
        "negative_tickers": [],
        "positive_tickers": ["AALI", "SIMP", "LSIP", "SSMS", "TBLA", "TAPG", "MGRO"],
    },
    "cpo_down": {
        "label": "Harga CPO/Sawit Turun",
        "icon": "📉",
        "keywords": ["cpo price down", "palm oil down", "sawit turun", "harga cpo turun", "crude palm oil falls"],
        "impact": "negative",
        "narrative": "Harga CPO turun → emiten sawit tertekan, revenue ekspor berkurang.",
        "negative_tickers": ["AALI", "SIMP", "LSIP", "SSMS", "TBLA", "TAPG", "MGRO"],
        "positive_tickers": [],
    },
    "rupiah_weak": {
        "label": "Rupiah Melemah",
        "icon": "💸",
        "keywords": ["rupiah melemah", "kurs dolar naik", "idr weakens", "usd/idr naik", "rupiah depreciate", "nilai tukar melemah"],
        "impact": "mixed",
        "narrative": "Rupiah melemah → eksportir (komoditas, manufaktur ekspor) diuntungkan; importir, perbankan, dan saham berbiaya impor tinggi tertekan.",
        "negative_tickers": ["UNVR", "ICBP", "MYOR", "INDF", "KLBF", "SIDO"],
        "positive_tickers": ["ADRO", "PTBA", "ITMG", "ANTM", "AALI", "SIMP"],
    },
    "rupiah_strong": {
        "label": "Rupiah Menguat",
        "icon": "💪",
        "keywords": ["rupiah menguat", "kurs dolar turun", "idr strengthens", "usd/idr turun", "rupiah appreciate"],
        "impact": "mixed",
        "narrative": "Rupiah menguat → importir dan saham berbiaya impor tinggi diuntungkan; eksportir komoditas sedikit tertekan.",
        "negative_tickers": ["ADRO", "PTBA", "ITMG"],
        "positive_tickers": ["UNVR", "ICBP", "MYOR", "INDF", "KLBF", "SIDO", "BBCA", "BBRI"],
    },
    "oil_up": {
        "label": "Harga Minyak Naik",
        "icon": "🛢️",
        "keywords": ["oil price up", "crude oil rise", "minyak naik", "brent naik", "wti naik", "harga minyak melonjak"],
        "impact": "mixed",
        "narrative": "Minyak naik → emiten energi/migas diuntungkan; emiten dengan biaya energi tinggi seperti semen dan kimia tertekan.",
        "negative_tickers": ["SMGR", "INTP", "TPIA"],
        "positive_tickers": ["MEDC", "ENRG", "ELSA", "PGAS", "RUIS"],
    },
    "inflation_high": {
        "label": "Inflasi Tinggi / CPI Melonjak",
        "icon": "🔥",
        "keywords": ["inflasi tinggi", "cpi naik", "inflation high", "inflation surge", "harga barang naik", "cost of living rise"],
        "impact": "negative",
        "narrative": "Inflasi tinggi → daya beli konsumen tertekan, margin konsumer goods menyusut, Bank Indonesia cenderung naikkan suku bunga.",
        "negative_tickers": ["UNVR", "ICBP", "MYOR", "INDF", "SIDO", "KLBF", "BBCA", "BBRI"],
        "positive_tickers": ["ANTM", "ITMG", "ADRO"],
    },
    "bi_rate_hike": {
        "label": "Bank Indonesia Naikkan BI Rate",
        "icon": "🏛️",
        "keywords": ["bi rate naik", "bank indonesia naikkan suku bunga", "bi7drr naik", "bi rate hike", "suku bunga acuan naik"],
        "impact": "negative",
        "narrative": "BI naikkan suku bunga → cost of fund perbankan naik, cicilan meningkat, properti dan konsumer tertekan.",
        "negative_tickers": ["BSDE", "SMRA", "CTRA", "ASRI", "LPKR", "UNVR", "ICBP"],
        "positive_tickers": ["BBCA", "BBRI", "BMRI", "BBNI"],
    },
    "recession_fear": {
        "label": "Ketakutan Resesi Global",
        "icon": "😨",
        "keywords": ["recession fear", "global recession", "resesi global", "economic slowdown", "gdp kontraksi", "perlambatan ekonomi"],
        "impact": "negative",
        "narrative": "Resesi global → permintaan komoditas turun, capital flight ke safe haven, saham cyclical dan komoditas tertekan.",
        "negative_tickers": ["ADRO", "PTBA", "ITMG", "ANTM", "AALI", "INCO", "TINS"],
        "positive_tickers": ["ICBP", "UNVR", "KLBF", "SIDO"],
    },
}


@st.cache_data(ttl=600)
def fetch_macro_news_yfinance() -> list[dict]:
    """Fetch macro-relevant headlines from yfinance general market news."""
    macro_queries = ["^JKSE", "IDR=X", "GC=F", "CL=F"]  # IHSG, USD/IDR, Gold futures, Crude Oil
    articles = []
    for symbol in macro_queries:
        try:
            t = yf.Ticker(symbol)
            news = t.news or []
            for item in news[:5]:
                title = item.get("title", "")
                link = item.get("link", "")
                pub_ts = item.get("providerPublishTime", 0)
                if title:
                    articles.append({
                        "title": title,
                        "link": link,
                        "source": symbol,
                        "ts": pub_ts,
                    })
        except Exception:
            pass
    # Deduplicate by title
    seen = set()
    unique = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    return sorted(unique, key=lambda x: x["ts"], reverse=True)


def fetch_stockbit_news_headlines() -> list[dict]:
    """Fetch Stockbit News feed from Exodus non-login endpoint (no auth needed)."""
    headlines = []
    try:
        url = "https://exodus.stockbit.com/stream/non-login/user/StockbitNews"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            data = r.json()
            items = data.get("data", [])
            for item in items[:30]:
                title = item.get("title", "") or (item.get("content", "") or "")[:120]
                if not title:
                    continue
                headlines.append({
                    "title": title,
                    "link": item.get("titleurl", ""),
                    "source": "stockbit",
                    "ts": item.get("created", 0),
                    "created_display": item.get("created_display", ""),
                    "content_preview": (item.get("content", "") or "")[:200],
                    "topics": item.get("topics", []),
                })
    except Exception:
        pass
    return headlines


def detect_macro_themes(articles: list[dict]) -> list[dict]:
    """Match headlines against MACRO_THEMES, return triggered themes with matched articles."""
    triggered = []
    for theme_key, theme in MACRO_THEMES.items():
        matched_articles = []
        for article in articles:
            title_l = article["title"].lower()
            if any(kw in title_l for kw in theme["keywords"]):
                matched_articles.append(article)
        if matched_articles:
            triggered.append({
                "key": theme_key,
                "label": theme["label"],
                "icon": theme["icon"],
                "impact": theme["impact"],
                "narrative": theme["narrative"],
                "positive_tickers": theme["positive_tickers"],
                "negative_tickers": theme["negative_tickers"],
                "articles": matched_articles[:3],
            })
    return triggered


def build_ticker_impact_table(triggered_themes: list[dict], watchlist_tickers: list[str]) -> list[dict]:
    """Cross-reference triggered macro themes with current watchlist tickers."""
    impact_map = {}  # ticker -> {positive_themes, negative_themes}
    for theme in triggered_themes:
        for t in theme["positive_tickers"]:
            if t in watchlist_tickers or not watchlist_tickers:
                if t not in impact_map:
                    impact_map[t] = {"positive": [], "negative": []}
                impact_map[t]["positive"].append(theme["label"])
        for t in theme["negative_tickers"]:
            if t in watchlist_tickers or not watchlist_tickers:
                if t not in impact_map:
                    impact_map[t] = {"positive": [], "negative": []}
                impact_map[t]["negative"].append(theme["label"])

    rows = []
    for ticker, impacts in impact_map.items():
        pos_count = len(impacts["positive"])
        neg_count = len(impacts["negative"])
        net = pos_count - neg_count
        if net > 0:
            signal = "🟢 Positif"
        elif net < 0:
            signal = "🔴 Negatif"
        else:
            signal = "🟡 Mixed"
        rows.append({
            "Ticker": ticker,
            "Signal": signal,
            "Positif dari": ", ".join(impacts["positive"]) if impacts["positive"] else "-",
            "Negatif dari": ", ".join(impacts["negative"]) if impacts["negative"] else "-",
            "Net Score": net,
        })
    return sorted(rows, key=lambda x: x["Net Score"], reverse=True)

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
    (now_wib.hour > 9 and now_wib.hour < 16) or
    (now_wib.hour == 16 and now_wib.minute == 0)
)

badge_text = "LIVE 🔴" if is_day_trade else "CLOSED ⏸️"
badge_color = "#10B981" if is_day_trade else "#F59E0B"
badge_bg = "rgba(16,185,129,0.15)" if is_day_trade else "rgba(245,158,11,0.15)"
badge_border = "rgba(16,185,129,0.3)" if is_day_trade else "rgba(245,158,11,0.3)"
sb_auth_ok = bool(config.STOCKBIT_BEARER_TOKEN or (config.STOCKBIT_USERNAME and config.STOCKBIT_PASSWORD))
sb_status_dot = "pulse-green" if sb_auth_ok else "pulse-orange"
sb_status_text = "Ready (Deep Analysis)" if sb_auth_ok else "Unavailable (Missing Token)"

status_html = f"""
<style>
    .status-container {{ display:flex; flex-wrap:wrap; gap:12px 18px; align-items:center; padding:14px 18px; border-radius:12px; background:#1A202C; color:#E2E8F0; border:1px solid #2D3748; }}
    .status-item {{ display:flex; align-items:center; gap:8px; font-size:0.9em; }}
    .live-label-container {{ display:inline-flex; align-items:center; gap:6px; padding:4px 8px; border-radius:6px; font-weight:700; font-size:0.8em; }}
    @keyframes pulse-green-anim {{ 0% {{ transform:scale(.95); box-shadow:0 0 0 0 rgba(16,185,129,.7); }} 70% {{ transform:scale(1); box-shadow:0 0 0 6px rgba(16,185,129,0); }} 100% {{ transform:scale(.95); box-shadow:0 0 0 0 rgba(16,185,129,0); }} }}
    @keyframes pulse-orange-anim {{ 0% {{ transform:scale(.95); box-shadow:0 0 0 0 rgba(245,158,11,.7); }} 70% {{ transform:scale(1); box-shadow:0 0 0 6px rgba(245,158,11,0); }} 100% {{ transform:scale(.95); box-shadow:0 0 0 0 rgba(245,158,11,0); }} }}
    .pulse-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
    .pulse-green {{ background:#10B981; box-shadow:0 0 0 0 rgba(16,185,129,.7); animation:pulse-green-anim 2s infinite; }}
    .pulse-orange {{ background:#F59E0B; box-shadow:0 0 0 0 rgba(245,158,11,.7); animation:pulse-orange-anim 2s infinite; }}
</style>
<div class="status-container">
    <div class="status-item">
        <strong>Market Status:</strong>
        <span id="market_status_badge" class="live-label-container" style="background-color:{badge_bg};color:{badge_color};border:1px solid {badge_border};">{badge_text}</span>
        <span id="realtime_clock_span" style="font-family:monospace;font-size:0.95em;">{now_wib.strftime('%Y-%m-%d %H:%M:%S')}</span>
        <span style="color:#94A3B8;font-size:0.85em;">WIB</span>
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
        <span class="pulse-dot {sb_status_dot}"></span>
        <span><strong>Exodus API:</strong> {sb_status_text}</span>
    </div>
    <hr style="width:100%;border:0;border-top:1px solid #2D3748;margin:8px 0;">
    <div style="color:#64748B;font-size:0.8em;">Freshness Fallback Pipeline: Google Sheets ➔ yfinance ➔ IDX. (Stockbit for Deep Analysis only).</div>
</div>

<script>
(function() {{
    function getWIB() {{
        var now = new Date();
        var utc = now.getTime() + (now.getTimezoneOffset() * 60000);
        return new Date(utc + (3600000 * 7));
    }}

    function pad(n) {{ return String(n).padStart(2, '0'); }}

    function isMarketOpen(w) {{
        var day = w.getDay(), h = w.getHours(), m = w.getMinutes();
        if (day < 1 || day > 5) return false;
        return (h === 9) || (h > 9 && h < 16) || (h === 16 && m === 0);
    }}

    function tick() {{
        var w = getWIB();
        var clockEl = document.getElementById('realtime_clock_span');
        var badgeEl = document.getElementById('market_status_badge');

        if (!clockEl) {{
            clockEl = window.parent.document.getElementById('realtime_clock_span');
            badgeEl = window.parent.document.getElementById('market_status_badge');
        }}

        if (clockEl) {{
            clockEl.textContent = w.getFullYear() + '-' + pad(w.getMonth()+1) + '-' + pad(w.getDate()) + ' ' + pad(w.getHours()) + ':' + pad(w.getMinutes()) + ':' + pad(w.getSeconds());
        }}

        if (badgeEl) {{
            var open = isMarketOpen(w);
            badgeEl.textContent = open ? 'LIVE 🔴' : 'CLOSED ⏸️';
            badgeEl.style.backgroundColor = open ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)';
            badgeEl.style.color = open ? '#10B981' : '#F59E0B';
            badgeEl.style.borderColor = open ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.3)';
        }}
    }}

    tick();
    setInterval(tick, 1000);
}})();
</script>
"""
st.components.v1.html(status_html, height=160, scrolling=False)

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

        # Price: div[data-last-price] or the big text element
        price_el = soup.select_one("div.YMlKec.fxKbKc")
        if not price_el:
            return None

        price_text = price_el.get_text(strip=True).replace(",", "").replace(".", "")
        price = float(price_text[:-2] + "." + price_text[-2:])  # handle formatting

        # Change: the span[data-change] nearby
        change_el = soup.select_one("div.P6K39c")
        change_text = change_el.get_text(strip=True) if change_el else "0"

        # Parse change text like "+12.34 (0.56%)"
        change_match = re.search(r"([+-]?\d+[\d,.]*)", change_text.replace(",", ""))
        change_val = float(change_match.group(1)) if change_match else 0.0

        # Pct change from second group in parentheses
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
if ihsg:
    is_up      = ihsg["change_abs"] >= 0
    chg_color  = "#10B981" if is_up else "#EF4444"
    chg_arrow  = "▲" if is_up else "▼"
    chg_bg     = "rgba(16,185,129,0.08)" if is_up else "rgba(239,68,68,0.08)"
    chg_border = "rgba(16,185,129,0.25)" if is_up else "rgba(239,68,68,0.25)"

    if ihsg.get("sparkline") and ihsg["prices"]:
        prices_js  = str([round(p, 2) for p in ihsg["prices"]])
        times_js   = str(ihsg["times"])
        min_p      = round(min(ihsg["prices"]) * 0.9995, 2)
        max_p      = round(max(ihsg["prices"]) * 1.0005, 2)
        line_color = "#10B981" if is_up else "#EF4444"
        fill_color = "rgba(16,185,129,0.12)" if is_up else "rgba(239,68,68,0.12)"
        open_str   = f"O <b style='color:#CBD5E1;'>{ihsg['open']:,.2f}</b>" if ihsg.get("open") else ""
        high_str   = f"H <b style='color:#10B981;'>{ihsg['high']:,.2f}</b>" if ihsg.get("high") else ""
        low_str    = f"L <b style='color:#EF4444;'>{ihsg['low']:,.2f}</b>" if ihsg.get("low") else ""
        prev_str   = f"Prev <b style='color:#CBD5E1;'>{ihsg['prev_close']:,.2f}</b>"
        vol_str    = f"Vol <b style='color:#CBD5E1;'>{ihsg['volume']/1e9:.2f}B</b>" if ihsg.get("volume") else ""

        ihsg_html = f"""
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap">
<div id="ihsg_widget" style="background:#161B27;border:1px solid #2D3748;border-radius:14px;padding:16px 20px;display:flex;gap:24px;align-items:center;margin-bottom:4px;">
  <div style="flex:0 0 auto;">
    <div style="font-size:0.75em;color:#64748B;font-weight:600;letter-spacing:.08em;text-transform:uppercase;font-family:Inter,sans-serif;">IHSG / IDX Composite</div>
    <div style="font-size:2.1em;font-weight:800;color:#F1F5F9;font-family:Inter,sans-serif;line-height:1.1;margin-top:2px;">{ihsg['current']:,.2f}</div>
    <div style="display:inline-flex;align-items:center;gap:6px;margin-top:5px;padding:3px 10px;border-radius:20px;background:{chg_bg};border:1px solid {chg_border};">
      <span style="color:{chg_color};font-weight:700;font-size:0.95em;font-family:Inter,sans-serif;">{chg_arrow} {abs(ihsg['change_abs']):,.2f} ({abs(ihsg['change_pct']):.2f}%)</span>
    </div>
    <div style="display:flex;gap:14px;margin-top:10px;font-size:0.78em;color:#94A3B8;font-family:Inter,sans-serif;">
      {open_str} {high_str} {low_str} {prev_str} {vol_str}
    </div>
    <div style="margin-top:5px;font-size:0.72em;color:#475569;font-family:Inter,sans-serif;">Sumber: {ihsg['source']} · refresh tiap 60 detik</div>
  </div>
  <div style="flex:1;min-width:0;height:90px;position:relative;">
    <canvas id="ihsg_chart" style="width:100%;height:90px;"></canvas>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function(){{
  var prices={prices_js};
  var labels={times_js};
  function init(){{
    var el=document.getElementById('ihsg_chart');
    if(!el){{el=window.parent.document.getElementById('ihsg_chart');}}
    if(!el)return;
    var ctx=el.getContext('2d');
    var grad=ctx.createLinearGradient(0,0,0,90);
    grad.addColorStop(0,'{fill_color}');
    grad.addColorStop(1,'rgba(0,0,0,0)');
    new Chart(ctx,{{
      type:'line',
      data:{{labels:labels,datasets:[{{data:prices,borderColor:'{line_color}',borderWidth:2,backgroundColor:grad,fill:true,pointRadius:0,tension:0.3}}]}},
      options:{{
        responsive:true,maintainAspectRatio:false,
        plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:function(c){{return ' '+c.parsed.y.toLocaleString('id-ID',{{minimumFractionDigits:2}}); }}}}}}}},
        scales:{{x:{{display:false}},y:{{display:false,min:{min_p},max:{max_p}}}}},
        animation:{{duration:400}}
      }}
    }});
  }}
  if(document.readyState==='loading'){{document.addEventListener('DOMContentLoaded',init);}}else{{init();}}
}})();
</script>
"""
        st.components.v1.html(ihsg_html, height=175, scrolling=False)
    else:
        # Fallback: price/change only card (Google Finance scrape — no sparkline)
        st.markdown(f"""
<div style="background:#161B27;border:1px solid #2D3748;border-radius:14px;padding:16px 20px;margin-bottom:4px;">
  <div style="font-size:0.75em;color:#64748B;font-weight:600;letter-spacing:.08em;text-transform:uppercase;">IHSG / IDX Composite</div>
  <div style="font-size:2.1em;font-weight:800;color:#F1F5F9;">{ihsg['current']:,.2f}</div>
  <div style="color:{chg_color};font-weight:700;margin-top:4px;">{chg_arrow} {abs(ihsg['change_abs']):,.2f} ({abs(ihsg['change_pct']):.2f}%)</div>
  <div style="margin-top:6px;font-size:0.72em;color:#475569;">Sumber: {ihsg['source']} (no sparkline) · refresh tiap 120 detik</div>
</div>
""", unsafe_allow_html=True)
else:
    st.caption("⚠️ IHSG data tidak tersedia di semua sumber (Yahoo Finance + Google Finance timeout).")

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
with st.sidebar:
    st.markdown("## 🔍 Screener Settings")
    st.markdown("---")
    
    # Check if query params tells us to scan
    if st.query_params.get("auto_scan", "false") == "true":
        st.session_state["trigger_auto_scan"] = True
        st.query_params["auto_scan"] = "false"

    # Auto refresh configuration
    st.subheader("🔁 Auto Refresh")
    init_auto_refresh = st.query_params.get("auto_refresh", "false") == "true"
    init_interval = int(st.query_params.get("refresh_interval", "10"))
    if init_interval not in [5, 10, 15, 30]:
        init_interval = 10

    auto_refresh_enabled = st.checkbox("Enable Auto Refresh", value=init_auto_refresh, help="Automatically re-trigger scan cycle.")
    if auto_refresh_enabled:
        interval_options = [5, 10, 15, 30]
        interval_index = interval_options.index(init_interval) if init_interval in interval_options else 1
        refresh_interval = st.selectbox(
            "Interval (Minutes)",
            options=interval_options,
            index=interval_index,
            help="Choose refresh period."
        )
        
        # Sync query params if changed
        if st.query_params.get("auto_refresh") != "true" or st.query_params.get("refresh_interval") != str(refresh_interval):
            st.query_params["auto_refresh"] = "true"
            st.query_params["refresh_interval"] = str(refresh_interval)
            
        import time
        if "next_refresh_time" not in st.session_state or st.session_state.get("last_refresh_interval") != refresh_interval:
            st.session_state.next_refresh_time = time.time() + (refresh_interval * 60)
            st.session_state.last_refresh_interval = refresh_interval
            
        time_left = int(st.session_state.next_refresh_time - time.time())
        if time_left <= 0:
            if not st.session_state.get("auto_scan_triggered", False):
                st.session_state.next_refresh_time = time.time() + (refresh_interval * 60)
                st.session_state["trigger_auto_scan"] = True
                st.session_state["auto_scan_triggered"] = True
        else:
            st.session_state["auto_scan_triggered"] = False
            time_display = f"{time_left // 60}m {time_left % 60}s"
            target_time = int(st.session_state.next_refresh_time * 1000)
            countdown_html = f"""<div id="countdown_wrapper" style="background:rgba(56,189,248,0.15);border:1px solid rgba(56,189,248,0.3);padding:10px;border-radius:8px;color:#38BDF8;font-weight:700;font-size:0.9em;margin-bottom:10px;text-align:left;">
⏳ Next auto-scan in: <span id="countdown_timer_span">{time_display}</span>
</div>
<script>
(function(){{
var target={target_time},interval={refresh_interval},t=setInterval(function(){{
var d=Math.max(0,Math.floor((target-Date.now())/1000)),s=document.getElementById("countdown_timer_span");
if(s)s.textContent=Math.floor(d/60)+"m "+(d%60)+"s";
if(d<=0){{clearInterval(t);s.textContent="0m 0s (Scan Complete)";var l=window.location;try{{if(window.parent&&window.parent.location)l=window.parent.location;}}catch(e){{}}l.href=l.pathname+"?auto_refresh=true&auto_scan=true&refresh_interval="+interval;}}
}},1000);
}})();
</script>"""
            st.components.v1.html(countdown_html, height=48)
    else:
        if st.query_params.get("auto_refresh") == "true":
            st.query_params["auto_refresh"] = "false"

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
    st.subheader("⚙️ Tab Scope Options")
    exclude_filters_trending = st.checkbox("Exclude filters for Trending Stocks", value=True, help="Display all matching tickers regardless of Ranks/Sectors.")
    exclude_filters_bsjp = st.checkbox("Exclude filters for BSJP", value=True, help="Display all BSJP setups regardless of Ranks/Sectors.")
    exclude_filters_minervini = st.checkbox("Exclude filters for Minervini Trend", value=True, help="Display all Minervini setups regardless of Ranks/Sectors.")
    
    st.markdown("---")
    
    # Manual Ticker Lookup
    search_ticker = st.text_input("Lookup Specific Ticker (e.g. ADRO)", "").upper().strip()

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
    hist_lookup = {row["Clean Ticker"]: row.to_dict() for _, row in ticker_df.iterrows()}
    
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

# ============================================================================
# TABS SYSTEM SETUP
# ============================================================================
tab11, tab2, tab_wl, tab_port, tab7, tab3, tab4, tab5, tab9, tab6, tab8, tab10, tab1 = st.tabs([
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
    "📋 Active Tickers Pool"
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
        hist_lookup = {row["Clean Ticker"]: row.to_dict() for _, row in ticker_df.iterrows()}
        
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
        hist_lookup = {row["Clean Ticker"]: row.to_dict() for _, row in ticker_df.iterrows()}
        
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
    from ui.tabs.tab7_deep_analysis import render_tab7
    render_tab7(ticker_df, scored_list)

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

