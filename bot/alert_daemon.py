"""
IDX Alert Daemon — PM2 long-running process.
Polls IDX Stock Summary API every 30s, deep-analyzes candidates with Stockbit.
Writes alerts to file; Hermes cron picks up + sends to Telegram.
"""
import sys
import os
import json
import asyncio
import time
from datetime import datetime
from pathlib import Path

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from curl_cffi import requests as requests_cf
from data.fetchers import safe_float
from data.scoring import compute_intraday_score
from data.pre_ara import get_ara_price, ara_proximity_score, pre_ara_score, classify_pre_ara
from bot.data_pipeline import get_watchlist_tickers, get_hist_row, now_wib_str

WIB = pytz.timezone("Asia/Jakarta")
ALERT_FILE = Path("/tmp/idx_alerts.jsonl")
ALERT_COOLDOWN = 300  # 5 min before re-alert same ticker
POLL_INTERVAL = 30    # seconds

# Track sent alerts: ticker -> timestamp
_sent = {}


def fetch_idx_batch(tickers: list[str]) -> list[dict]:
    """
    Fetch stock summary for all tickers in one IDX API call.
    Returns list of raw items.
    """
    try:
        url = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
        headers = {
            "Referer": "https://www.idx.co.id",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }
        r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            items = r.json().get("data", [])
            # Index by ticker
            idx_map = {}
            for item in items:
                code = item.get("StockCode", "").upper().strip()
                idx_map[code] = item
            return [idx_map.get(t) for t in tickers if idx_map.get(t)]
        else:
            print(f"[{datetime.now(WIB).strftime('%H:%M:%S')}] IDX fetch failed: {r.status_code}")
            return []
    except Exception as e:
        print(f"[{datetime.now(WIB).strftime('%H:%M:%S')}] IDX fetch error: {e}")
        return []

# --- STOCKBIT deep analysis (only for candidates) ---

async def fetch_stockbit_orderbook(ticker: str):
    """Fetch orderbook via Stockbit."""
    try:
        url = f"https://exodus.stockbit.com/company-price-feed/v2/orderbook/companies/{ticker}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
        }
        r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


async def deep_analyze(ticker: str, price: float, prev_close: float, vol: float, volume: float) -> dict:
    """Use Stockbit for orderbook imbalance + sentiment."""
    ob = await fetch_stockbit_orderbook(ticker)
    result = {}
    if ob:
        data = ob.get("data", {})
        bids = data.get("Bid", []) or data.get("bid", [])
        asks = data.get("Offer", []) or data.get("ask", []) or data.get("offer", [])
        total_bid = sum(b.get("Lot", 0) for b in bids) if bids else 0
        total_ask = sum(a.get("Lot", 0) for a in asks) if asks else 0
        result["imbalance"] = round(total_bid / max(total_ask, 1), 2)
        result["bid_lot"] = total_bid
        result["ask_lot"] = total_ask
    else:
        result["imbalance"] = 1.0
        result["bid_lot"] = 0
        result["ask_lot"] = 0
    return result


# --- ALERT EVALUATION ---

def evaluate_candidate(ticker: str, live: dict, hist: dict) -> dict | None:
    """Return alert dict if ticker triggers, else None."""
    now_ts = time.time()
    # Cooldown check
    if ticker in _sent and now_ts - _sent[ticker] < ALERT_COOLDOWN:
        return None

    price = safe_float(live.get("last", 0))
    prev_close = safe_float(live.get("prev_close", 0))
    open_price = safe_float(live.get("open", 0))
    high = safe_float(live.get("high", 0))
    low = safe_float(live.get("low", 0))
    volume = safe_float(live.get("volume", 0))

    if price <= 0 or prev_close <= 0:
        return None

    vol_raw = safe_float(live.get("volume", 0))
    avg_vol = safe_float(hist.get("Vol_Avg", 0))
    vsr = round(vol_raw / max(avg_vol, 1), 2) if avg_vol > 0 else 1.0
    chg_pct = round((price - prev_close) / prev_close * 100, 2)

    if chg_pct < 1.0 and vsr < 2:
        return None

    # Score
    hist_for_score = hist.copy()
    live_for_score = {
        "last": price,
        "open": open_price,
        "high": high,
        "low": low,
        "prev_close": prev_close,
        "volume": volume,
        "source": "idx_endpoint",
    }
    score_res = compute_intraday_score(live_for_score, hist_for_score)
    score = score_res["score"]

    # ARA proximity
    ara_price = get_ara_price(prev_close)
    prox = ara_proximity_score(price, prev_close, ara_price)

    reasons = []
    if prox >= 40:
        reasons.append(f"ARA prox {prox:.0f}%")
    if score >= 75:
        reasons.append(f"Score {score}")
    if vsr >= 2.5:
        reasons.append(f"VSR {vsr:.1f}x")
    if chg_pct >= 5:
        reasons.append(f"+{chg_pct:.1f}%")
    elif chg_pct <= -5:
        reasons.append(f"{chg_pct:.1f}%")

    if not reasons:
        return None

    alert = {
        "ticker": ticker,
        "price": price,
        "chg_pct": chg_pct,
        "vsr": vsr,
        "score": score,
        "proximity": prox,
        "reasons": ", ".join(reasons),
        "timestamp": now_ts,
        "time_str": datetime.now(WIB).strftime("%H:%M:%S"),
        "date_str": datetime.now(WIB).strftime("%d %b"),
    }
    return alert


async def run():
    print(f"[{datetime.now(WIB).strftime('%H:%M:%S')}] IDX Alert Daemon started. Polling every {POLL_INTERVAL}s...")
    tickers = get_watchlist_tickers()
    print(f"  Watchlist: {len(tickers)} tickers loaded.")

    while True:
        try:
            loop_start = time.time()

            # 1. Fetch batch from IDX (lightweight)
            items = fetch_idx_batch(tickers)
            if not items:
                # Retry fresh fetch from API
                url = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
                headers = {
                    "Referer": "https://www.idx.co.id",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                }
                r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
                if r.status_code == 200:
                    data_map = {}
                    for item in r.json().get("data", []):
                        code = item.get("StockCode", "").upper().strip()
                        data_map[code] = item
                    items = [data_map.get(t) for t in tickers if data_map.get(t)]

            if not items:
                print(f"[{datetime.now(WIB).strftime('%H:%M:%S')}] No data from IDX, waiting...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # 2. Evaluate each item
            alerts = []
            candidates_for_deep = []

            for item in items:
                if item is None:
                    continue
                ticker = item.get("StockCode", "").upper().strip()
                if not ticker:
                    continue

                live = {
                    "last": safe_float(item.get("LastPrice", 0)),
                    "open": safe_float(item.get("OpenPrice", 0)),
                    "high": safe_float(item.get("HighPrice", 0)),
                    "low": safe_float(item.get("LowPrice", 0)),
                    "prev_close": safe_float(item.get("PreviousPrice", 0)),
                    "volume": safe_float(item.get("Volume", 0)),
                    "frequency": safe_float(item.get("Frequency", 0)),
                    "value": safe_float(item.get("Value", 0)),
                    "foreign_buy": safe_float(item.get("ForeignBuy", 0)),
                    "foreign_sell": safe_float(item.get("ForeignSell", 0)),
                }

                hist = get_hist_row(ticker)
                if not hist:
                    continue

                alert = evaluate_candidate(ticker, live, hist)
                if alert:
                    alerts.append(alert)

            # 3. Deep analyze top candidates with Stockbit
            if alerts:
                top = sorted(alerts, key=lambda a: a["score"] + a["proximity"], reverse=True)[:5]
                for a in top:
                    deep = await deep_analyze(a["ticker"], a["price"], 0, 0, 0)
                    a["imbalance"] = deep["imbalance"]
                    a["bid_lot"] = deep["bid_lot"]
                    a["ask_lot"] = deep["ask_lot"]

                # 4. Write to alert file
                with open(ALERT_FILE, "a") as f:
                    for a in alerts:
                        f.write(json.dumps(a) + "\n")

                # Mark sent
                for a in alerts:
                    _sent[a["ticker"]] = a["timestamp"]

                print(f"[{datetime.now(WIB).strftime('%H:%M:%S')}] {len(alerts)} new alerts")

            # 5. Sleep remaining
            elapsed = time.time() - loop_start
            sleep_for = max(1, POLL_INTERVAL - elapsed)
            await asyncio.sleep(sleep_for)

        except Exception as e:
            print(f"[ERROR] {e}")
            await asyncio.sleep(5)


def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
