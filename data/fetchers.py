import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
import yfinance as yf
import math
from curl_cffi import requests as requests_cf
from core.config import config
from core.logger import logger

# Constants
WIB = pytz.timezone("Asia/Jakarta")

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
def load_ticker_pool(sheets_repository):
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
        logger.error(f"Failed to load tickers: {e}")
        return pd.DataFrame()

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
        return {
            "last": safe_float(hist_row.get("Price")),
            "open": safe_float(hist_row.get("PriceOpen")),
            "high": safe_float(hist_row.get("High")),
            "low": safe_float(hist_row.get("Low")),
            "prev_close": safe_float(hist_row.get("ClosePrev")),
            "source": "gsheet_fallback",
            "report": "All sources failed"
        }
        
    now_wib = datetime.now(WIB)
    fresh_sources = []
    for s in sources:
        ts = s["ts"]
        age_minutes = (now_wib - ts).total_seconds() / 60 if ts else float("inf")
        threshold = 5.0 if s["name"] == "idx_endpoint" else 25.0
        if age_minutes <= threshold:
            fresh_sources.append(s)
            
    pool = fresh_sources if fresh_sources else sources
    winner = max(pool, key=lambda x: x["ts"].timestamp() if x["ts"] else 0.0)
    
    res = winner["res"]
    return {
        "last": res["last"],
        "open": res["open"],
        "high": res["high"],
        "low": res["low"],
        "volume": res["volume"],
        "prev_close": res["prev_close"],
        "source": winner["name"],
        "source_ts": winner["ts"],
    }


def fetch_news_for_tickers(ticker_list):
    """Fetch yfinance news + rule-based sentiment for a list of IDX tickers."""
    positive_kw = [
        "naik", "tumbuh", "laba", "positif", "dividen", "akuisisi",
        "ekspansi", "profit", "growth", "rise", "gain", "upgrade",
        "buy", "bullish", "outperform", "surplus", "bangkit",
    ]
    negative_kw = [
        "turun", "rugi", "gagal", "krisis", "kasus", "utang", "debt",
        "loss", "downgrade", "sell", "bearish", "crash", "tunda",
        "henti", "anjlok", "merugi", "default", "pailit",
    ]
    results = {}
    for ticker in ticker_list:
        try:
            stock = yf.Ticker(f"{ticker}.JK")
            news = stock.news or []
            headlines = [a.get("title", "") for a in news[:5] if a.get("title")]
            if not headlines:
                continue
            sentiment = 0
            for title in headlines:
                tl = title.lower()
                sentiment += sum(1 for kw in positive_kw if kw in tl)
                sentiment -= sum(1 for kw in negative_kw if kw in tl)
            
            pub_ts = news[0].get("providerPublishTime", 0)
            latest_time = ""
            if pub_ts:
                try:
                    import pytz
                    import datetime as dt
                    WIB = pytz.timezone("Asia/Jakarta")
                    dt_wib = dt.datetime.fromtimestamp(pub_ts, tz=WIB)
                    latest_time = dt_wib.strftime("%d %b %H:%M WIB")
                except Exception:
                    pass

            results[ticker] = {
                "count": len(headlines),
                "latest": headlines[0],
                "latest_time": latest_time,
                "sentiment": sentiment / len(headlines),
            }
        except Exception:
            pass
    return results


async def fetch_stockbit_trending():
    """Fetch live trending list from Stockbit Exodus API."""
    try:
        url = "https://exodus.stockbit.com/stream/non-login/trending"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
        }
        r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception:
        pass
    return []


class _OrderLevel:
    def __init__(self, price, lot, freq):
        self.price = price
        self.lot = lot
        self.freq = freq


class _OrderbookSnap:
    def __init__(self, last_price, change_pct, imbalance_ratio, total_bid_lot, bid_levels, ask_levels):
        self.last_price = last_price
        self.change_pct = change_pct
        self.imbalance_ratio = imbalance_ratio
        self.total_bid_lot = total_bid_lot
        self.bid_levels = bid_levels
        self.ask_levels = ask_levels


def _parse_orderbook_snap(symbol, payload):
    try:
        data = payload.get("data", payload)
        last_price = safe_float(data.get("lastPrice") or data.get("last_price", 0))
        prev_close = safe_float(data.get("prevClose") or data.get("prev_close", last_price))
        change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
        bids_raw = data.get("bid", data.get("bids", []))
        asks_raw = data.get("offer", data.get("asks", data.get("offers", [])))
        bid_levels = [
            _OrderLevel(safe_float(b.get("price", 0)), int(safe_float(b.get("lot", 0))), int(safe_float(b.get("freq", 0))))
            for b in bids_raw[:10]
        ]
        ask_levels = [
            _OrderLevel(safe_float(a.get("price", 0)), int(safe_float(a.get("lot", 0))), int(safe_float(a.get("freq", 0))))
            for a in asks_raw[:10]
        ]
        total_bid = sum(l.lot for l in bid_levels)
        total_ask = sum(l.lot for l in ask_levels)
        imbalance = total_bid / total_ask if total_ask > 0 else 1.0
        return _OrderbookSnap(last_price, change_pct, imbalance, total_bid, bid_levels, ask_levels)
    except Exception:
        return None


async def fetch_stockbit_detail(symbol):
    """Fetch live orderbook snapshot from Stockbit Exodus API."""
    try:
        url = f"https://exodus.stockbit.com/stock/{symbol}/orderbook"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
        }
        r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            return _parse_orderbook_snap(symbol, r.json())
    except Exception:
        pass
    return None
