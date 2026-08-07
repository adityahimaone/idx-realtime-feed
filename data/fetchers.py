import streamlit as st
import pandas as pd
import asyncio
import logging
import time
from datetime import datetime
import pytz
import yfinance as yf
import math
from curl_cffi import requests as requests_cf
from core.config import config
from core.logger import logger

# Constants
WIB = pytz.timezone("Asia/Jakarta")

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

# ─── Freshness selection ─────────────────────────────────────────────────────

SOURCE_PRIORITY = {"stockbit": 0, "itick": 1, "idx_endpoint": 2, "gsheet": 3, "yfinance": 4}
FRESHNESS_THRESHOLDS_MIN = {
    "stockbit": 2.0,
    "itick": 2.0,
    "idx_endpoint": 5.0,
    "gsheet": 10.0,
    "yfinance": 10.0,
}
TIE_WINDOW_SEC = 5.0

# Stockbit rate-limit guard: ~40 req / 5 min per token. We keep a module-level
# TTL cache (60s per symbol) plus a rolling budget of 8 fetches per 60s window.
STOCKBIT_CACHE_TTL = 60.0
STOCKBIT_BUDGET = 8
STOCKBIT_BUDGET_WINDOW = 60.0
_stockbit_ttl_cache: dict[str, tuple[float, dict]] = {}
_stockbit_budget = {"window_start": 0.0, "count": 0}


def _stockbit_budget_available() -> bool:
    now = time.time()
    if now - _stockbit_budget["window_start"] >= STOCKBIT_BUDGET_WINDOW:
        _stockbit_budget["window_start"] = now
        _stockbit_budget["count"] = 0
    return _stockbit_budget["count"] < STOCKBIT_BUDGET


def _stockbit_budget_consume() -> None:
    _stockbit_budget["count"] += 1


# itick.org backup-source guard: free plan allows ~5 calls / minute. We mirror
# the stockbit pattern with a rolling budget of 5 HTTP calls per 60s window
# plus a 60s TTL cache. A batched quotes pre-fetch consumes 1 call; the Deep
# Analysis fallback (quotes + depth) consumes 2 calls and is skipped when fewer
# than 2 remain.
ITICK_CACHE_TTL = 60.0
ITICK_BUDGET = 5
ITICK_BUDGET_WINDOW = 60.0
_itick_ttl_cache: dict[str, tuple[float, dict]] = {}
_itick_budget = {"window_start": 0.0, "count": 0}


def _itick_budget_available() -> bool:
    now = time.time()
    if now - _itick_budget["window_start"] >= ITICK_BUDGET_WINDOW:
        _itick_budget["window_start"] = now
        _itick_budget["count"] = 0
    return _itick_budget["count"] < ITICK_BUDGET


def _itick_budget_consume() -> None:
    _itick_budget["count"] += 1


def _itick_budget_remaining() -> int:
    now = time.time()
    if now - _itick_budget["window_start"] >= ITICK_BUDGET_WINDOW:
        _itick_budget["window_start"] = now
        _itick_budget["count"] = 0
    return ITICK_BUDGET - _itick_budget["count"]


def fetch_itick_quotes_batch(codes: list[str]) -> dict:
    """Batch quote fetch from itick.org (backup source, ID region).

    One GET /stock/quotes?region=ID&codes=A,B with the `token` header, parsed
    into {CODE: {last, open, high, low, volume, prev_close, value, frequency,
    source_ts, error}}. Max 50 codes per call. Returns {} (silently skipped)
    when no token is configured, on HTTP 401 / request errors, or when the
    5-call/min budget is exhausted.
    """
    if not config.ITICK_TOKEN:
        return {}
    codes = [str(c).upper().strip() for c in codes if str(c).strip()]
    if not codes:
        return {}
    codes = codes[:50]
    key = ",".join(sorted(codes))
    now = time.time()
    cached = _itick_ttl_cache.get(key)
    if cached and now - cached[0] < ITICK_CACHE_TTL:
        return cached[1]
    if not _itick_budget_available():
        logger.warning("itick quotes: budget exhausted, skipping backup batch")
        return {}
    _itick_budget_consume()

    url = "https://api.itick.org/stock/quotes"
    params = {"region": "ID", "codes": ",".join(codes)}
    headers = {"accept": "application/json", "token": config.ITICK_TOKEN}
    try:
        r = requests_cf.get(url, params=params, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 401:
            logger.warning("itick quotes: HTTP 401 (invalid token) — backup source skipped")
            return {}
        if r.status_code != 200:
            logger.warning(f"itick quotes: HTTP {r.status_code} — backup source skipped")
            return {}
        payload = r.json()
        data = payload.get("data") or {}
        out = {}
        for code, q in data.items():
            ts_ms = safe_float(q.get("t"))
            source_ts = None
            if ts_ms > 0:
                source_ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=pytz.utc).astimezone(WIB)
            out[code] = {
                "last": safe_float(q.get("ld")),
                "open": safe_float(q.get("o")),
                "high": safe_float(q.get("h")),
                "low": safe_float(q.get("l")),
                "volume": safe_float(q.get("v")),
                "prev_close": safe_float(q.get("p")),
                "value": safe_float(q.get("tu")),
                "frequency": 0.0,
                "source_ts": source_ts,
                "error": None,
            }
        if out:
            _itick_ttl_cache[key] = (now, out)
        return out
    except Exception as exc:
        logger.warning(f"itick quotes: request error — {exc}")
        return {}


def _stockbit_result_from_snap(snap) -> dict:
    total_bid = sum(l.lot for l in snap.bid_levels)
    total_ask = sum(l.lot for l in snap.ask_levels)
    return {
        "last": snap.last_price,
        "open": snap.open_price or snap.last_price,
        "high": snap.high or snap.last_price,
        "low": snap.low or snap.last_price,
        "volume": snap.volume,
        "prev_close": snap.prev_close,
        "frequency": getattr(snap, "frequency", 0.0),
        "value": getattr(snap, "value", 0.0),
        "foreign_buy": getattr(snap, "fbuy", 0.0),
        "foreign_sell": getattr(snap, "fsell", 0.0),
        "total_bid_lot": total_bid,
        "total_ask_lot": total_ask,
        "imbalance_ratio": total_bid / total_ask if total_ask > 0 else 1.0,
        "source_ts": datetime.now(WIB),
        "error": None,
    }


async def fetch_stockbit_quote_source(symbol: str) -> dict:
    """Fetch a quote-source dict from Stockbit for the freshness engine.

    Guarded by a 60s TTL cache per symbol and a rolling budget of 8 fetches per
    60s window so the ~40 req/5-min token limit is never approached. Uses the
    sync cached token (env/cache only — never triggers an Obscura browser login)
    and falls back to the unauthenticated exodus endpoint. Stockbit exposes no
    exchange timestamp, so source_ts is the fetch time (honest proxy).
    """
    now = time.time()
    cached = _stockbit_ttl_cache.get(symbol)
    if cached and now - cached[0] < STOCKBIT_CACHE_TTL:
        return cached[1]

    if not _stockbit_budget_available():
        return {"source_ts": None, "error": "Stockbit fetch budget exhausted"}
    _stockbit_budget_consume()

    res = None
    try:
        from services.auth_service import auth_service
        from providers.stockbit_provider import StockbitProvider

        token = auth_service.get_cached_token()
        if token:
            provider = StockbitProvider(token)
            try:
                snap = await provider.fetch_orderbook(symbol)
                if snap:
                    res = _stockbit_result_from_snap(snap)
            finally:
                await provider.close()

        if res is None:
            # Unauthenticated exodus fallback (empty token skips the auth path)
            snap = await fetch_stockbit_detail(symbol, token="")
            if snap:
                res = _stockbit_result_from_snap(snap)
    except Exception as exc:
        logger.error(f"fetch_stockbit_quote_source failed for {symbol}: {exc}")

    if res is None:
        res = {"source_ts": None, "error": "Stockbit fetch failed"}
    _stockbit_ttl_cache[symbol] = (now, res)
    return res


def fetch_stockbit_tradebook(symbol: str, date: str | None = None) -> dict | None:
    """Fetch the daily trade-book chart from the public Exodus endpoint.

    GET https://exodus.stockbit.com/order-trade/trade-book/chart
        ?symbol=ARCI&time_interval=1m&date=YYYY-MM-DD

    The payload carries per-minute cumulative buy/sell lots & values, prices,
    net values, a big-money net series, and a `book_total` summary. Returns the
    raw JSON dict (or None). Requires the Stockbit Bearer token — the endpoint
    returns 401 without it. `date` defaults to today WIB (YYYY-MM-DD).
    """
    from datetime import datetime

    import pytz

    if date is None:
        date = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%Y-%m-%d")
    url = "https://exodus.stockbit.com/order-trade/trade-book/chart"
    params = {"symbol": symbol.upper(), "time_interval": "1m", "date": date}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    try:
        from services.auth_service import auth_service
        token = auth_service.get_cached_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass
    try:
        r = requests_cf.get(url, params=params, headers=headers, timeout=12, impersonate="chrome")
        if r.status_code == 200:
            return r.json()
        logger.warning(f"tradebook: HTTP {r.status_code} for {symbol} @ {date}")
    except Exception as exc:
        logger.warning(f"tradebook: request error for {symbol}: {exc}")
    return None


async def pick_freshest_source(symbol: str, hist_row: dict, idx_summary_dict: dict = None,
                               itick_summary_dict: dict = None) -> dict:
    """Compare freshness timestamps of Stockbit, itick (optional), IDX, GSheet,
    and yfinance to select the best winner. Sync source fetchers run in a
    thread pool; Stockbit goes through its own guarded async path. itick joins
    the candidates only when `itick_summary_dict` is provided (a pre-fetched
    batch map — never per-ticker network). The default None keeps legacy
    callers/tests unchanged."""
    gsheet_res, yfinance_res, idx_res, stockbit_res = await asyncio.gather(
        asyncio.to_thread(fetch_gsheet_source, symbol, hist_row),
        asyncio.to_thread(fetch_yfinance_source, symbol),
        asyncio.to_thread(fetch_idx_source, symbol, idx_summary_dict),
        fetch_stockbit_quote_source(symbol),
        return_exceptions=True,
    )

    def _safe(res):
        return {} if isinstance(res, BaseException) else (res or {})

    gsheet_res = _safe(gsheet_res)
    yfinance_res = _safe(yfinance_res)
    idx_res = _safe(idx_res)
    stockbit_res = _safe(stockbit_res)
    itick_res = {}
    if itick_summary_dict is not None:
        itick_res = _safe(itick_summary_dict.get(symbol) or {})

    sources = []

    def is_valid(res):
        return res.get("error") is None and res.get("last") is not None and res.get("last") > 0

    if is_valid(gsheet_res):
        sources.append({"name": "gsheet", "res": gsheet_res, "ts": gsheet_res["source_ts"]})
    if is_valid(yfinance_res):
        sources.append({"name": "yfinance", "res": yfinance_res, "ts": yfinance_res["source_ts"]})
    if is_valid(idx_res):
        sources.append({"name": "idx_endpoint", "res": idx_res, "ts": idx_res["source_ts"]})
    if is_valid(stockbit_res):
        sources.append({"name": "stockbit", "res": stockbit_res, "ts": stockbit_res["source_ts"]})
    if is_valid(itick_res):
        sources.append({"name": "itick", "res": itick_res, "ts": itick_res.get("source_ts")})

    if not sources:
        # Fallback to gsheet row cache (keeps frequency/value enrichment)
        price = safe_float(hist_row.get("Price"))
        value = safe_float(hist_row.get("Value", 0))
        if value <= 0:
            value = price * safe_float(hist_row.get("Volume")) * 100
        return {
            "last": price,
            "open": safe_float(hist_row.get("PriceOpen")),
            "high": safe_float(hist_row.get("High")),
            "low": safe_float(hist_row.get("Low")),
            "volume": safe_float(hist_row.get("Volume")),
            "prev_close": safe_float(hist_row.get("ClosePrev")),
            "frequency": safe_float(hist_row.get("Frequency", 0)),
            "value": value,
            "foreign_buy": 0.0,
            "foreign_sell": 0.0,
            "source": "gsheet_fallback",
            "source_ts": None,
            "report": "All sources failed, fallback to GSheets row values",
        }

    now_wib = datetime.now(WIB)
    fresh_sources = []
    for s in sources:
        ts = s["ts"]
        age_minutes = (now_wib - ts).total_seconds() / 60 if ts else float("inf")
        threshold = FRESHNESS_THRESHOLDS_MIN.get(s["name"], 10.0)
        if age_minutes <= threshold:
            fresh_sources.append(s)

    pool = fresh_sources if fresh_sources else sources

    def ts_seconds(s):
        return s["ts"].timestamp() if s["ts"] else 0.0

    best_ts = max(ts_seconds(s) for s in pool)
    if best_ts > 0:
        tied = [s for s in pool if abs(ts_seconds(s) - best_ts) <= TIE_WINDOW_SEC]
        winner = min(tied, key=lambda s: SOURCE_PRIORITY.get(s["name"], 99))
    else:
        winner = max(pool, key=lambda s: ts_seconds(s))

    res = winner["res"]
    age_str = f"{round((now_wib - winner['ts']).total_seconds() / 60, 1)}m ago" if winner["ts"] else "N/A"
    return {
        "last": res.get("last", 0.0),
        "open": res.get("open", 0.0),
        "high": res.get("high", 0.0),
        "low": res.get("low", 0.0),
        "volume": res.get("volume", 0.0),
        "prev_close": res.get("prev_close", 0.0),
        "frequency": res.get("frequency", 0.0),
        "value": res.get("value", 0.0),
        "foreign_buy": res.get("foreign_buy", 0.0),
        "foreign_sell": res.get("foreign_sell", 0.0),
        "source": winner["name"],
        "source_ts": winner["ts"],
        "report": f"{winner['name']} ({age_str})",
    }


def fetch_news_for_tickers(ticker_list):
    """Fetch yfinance news + rule-based sentiment for a list of IDX tickers.

    The yfinance logger is temporarily silenced around the batch: Yahoo's news
    endpoint frequently returns a faulty (non-JSON) response for IDX tickers,
    and yfinance logs one ERROR line per symbol ("Failed to retrieve the news
    and received faulty response instead."), which would spam the terminal on
    every batched fetch (Pick of the Day, News tab, bots).
    """
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
    yf_logger = logging.getLogger("yfinance")
    prev_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL + 1)
    try:
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
    finally:
        yf_logger.setLevel(prev_level)
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
    def __init__(self, last_price, change_pct, imbalance_ratio, total_bid_lot, bid_levels, ask_levels, open_price=0.0, high=0.0, low=0.0, volume=0.0, prev_close=0.0):
        self.last_price = last_price
        self.change_pct = change_pct
        self.imbalance_ratio = imbalance_ratio
        self.total_bid_lot = total_bid_lot
        self.bid_levels = bid_levels
        self.ask_levels = ask_levels
        self.open_price = open_price
        self.high = high
        self.low = low
        self.volume = volume
        self.prev_close = prev_close


def _parse_orderbook_snap(symbol, payload):
    try:
        data = payload.get("data", payload)
        last_price = safe_float(data.get("lastPrice") or (data.get("last_price") or data.get("lastprice", 0)))
        prev_close = safe_float(data.get("prevClose") or (data.get("prev_close") or (data.get("previous") or last_price)))
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
        open_price = safe_float(data.get("open", last_price))
        high = safe_float(data.get("high", last_price))
        low = safe_float(data.get("low", last_price))
        volume = safe_float(data.get("volume", 0))
        return _OrderbookSnap(
            last_price, change_pct, imbalance, total_bid, bid_levels, ask_levels,
            open_price=open_price, high=high, low=low, volume=volume, prev_close=prev_close
        )
    except Exception:
        return None


async def fetch_stockbit_detail(symbol, token=None):
    """Fetch live orderbook snapshot from Stockbit Exodus API.

    Pass an explicit token to skip auth lookup entirely; otherwise the cached
    token is used (env/cache only, no Obscura browser login). Falls back to the
    unauthenticated exodus endpoint when no token is available or auth fails.
    """
    try:
        from services.auth_service import auth_service
        from providers.stockbit_provider import StockbitProvider

        if token is None:
            token = auth_service.get_cached_token()
        if token:
            provider = StockbitProvider(token)
            try:
                snap = await provider.fetch_orderbook(symbol)
                if snap:
                    total_bid = sum(l.lot for l in snap.bid_levels)
                    total_ask = sum(l.lot for l in snap.ask_levels)
                    imbalance = total_bid / total_ask if total_ask > 0 else 1.0
                    change_pct = ((snap.last_price - snap.prev_close) / snap.prev_close * 100) if snap.prev_close > 0 else 0.0
                    return _OrderbookSnap(
                        snap.last_price,
                        change_pct,
                        imbalance,
                        total_bid,
                        snap.bid_levels,
                        snap.ask_levels,
                        open_price=snap.open_price,
                        high=snap.high,
                        low=snap.low,
                        volume=snap.volume,
                        prev_close=snap.prev_close
                    )
            finally:
                await provider.close()
    except Exception as exc:
        from core.logger import logger
        logger.error(f"fetch_stockbit_detail authenticated fetch failed: {exc}")

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


async def fetch_itick_snapshot(code: str):
    """Deep Analysis fallback orderbook snapshot from itick.org.

    Uses two calls: /stock/quotes (OHLC + last) and /stock/depth (10-level
    bid/ask) with the `token` header, returning an _OrderbookSnap in the same
    shape as the Stockbit Exodus path. Returns None (silently skipped) when no
    token is configured, when fewer than 2 budget calls remain in the current
    60s window, or when either request fails (incl. HTTP 401).
    """
    if not config.ITICK_TOKEN:
        return None
    if _itick_budget_remaining() < 2:
        logger.warning("itick snapshot: budget < 2 calls — skipping backup fallback")
        return None
    _itick_budget_consume()  # quotes call
    _itick_budget_consume()  # depth call

    def _get_json(url: str, params: dict) -> dict | None:
        headers = {"accept": "application/json", "token": config.ITICK_TOKEN}
        r = requests_cf.get(url, params=params, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 401:
            logger.warning("itick snapshot: HTTP 401 (invalid token) — backup skipped")
            return None
        if r.status_code != 200:
            logger.warning(f"itick snapshot: HTTP {r.status_code} — backup skipped")
            return None
        return r.json()

    code = code.upper().strip()
    quotes_res, depth_res = await asyncio.gather(
        asyncio.to_thread(
            _get_json, "https://api.itick.org/stock/quotes",
            {"region": "ID", "codes": code},
        ),
        asyncio.to_thread(
            _get_json, "https://api.itick.org/stock/depth",
            {"region": "ID", "code": code},
        ),
        return_exceptions=True,
    )

    def _safe(payload):
        return {} if isinstance(payload, BaseException) else (payload or {})

    q = (_safe(quotes_res).get("data") or {}).get(code) or {}
    depth = _safe(depth_res).get("data") or {}

    last = safe_float(q.get("ld"))
    if last <= 0:
        return None

    prev_close = safe_float(q.get("p")) or last
    change_pct = ((last - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
    bid_levels = [
        _OrderLevel(safe_float(b.get("p", 0)), int(safe_float(b.get("v", 0))), int(safe_float(b.get("o", 0))))
        for b in (depth.get("b") or [])[:10]
    ]
    ask_levels = [
        _OrderLevel(safe_float(a.get("p", 0)), int(safe_float(a.get("v", 0))), int(safe_float(a.get("o", 0))))
        for a in (depth.get("a") or [])[:10]
    ]
    total_bid = sum(l.lot for l in bid_levels)
    total_ask = sum(l.lot for l in ask_levels)
    imbalance = total_bid / total_ask if total_ask > 0 else 1.0
    return _OrderbookSnap(
        last,
        change_pct,
        imbalance,
        total_bid,
        bid_levels,
        ask_levels,
        open_price=safe_float(q.get("o")) or last,
        high=safe_float(q.get("h")) or last,
        low=safe_float(q.get("l")) or last,
        volume=safe_float(q.get("v")),
        prev_close=prev_close,
    )
