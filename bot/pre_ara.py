"""
🚨 Pre-ARA Alert — every 30m, 09:00–14:30 WIB
Detect saham mendekati ARA:
🟠 Pre-ARA Entry (prox 50-70%)
🔴 Imminent (prox 70-95%)
🚨 AT ARA (prox ≥ 95%)
"""
import sys
import os
import asyncio
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.data_pipeline import get_watchlist_tickers, get_hist_row, fetch_ticker_live, now_wib_str, scan_all
from data.pre_ara import (
    get_ara_limit, get_ara_price, ara_proximity_score,
    ara_distance, pre_ara_score, classify_pre_ara, detect_ara_streak
)
from data.fetchers import safe_float
from bot.telegram import send_telegram

WIB = pytz.timezone("Asia/Jakarta")


async def scan_pre_ara() -> str:
    """
    Scan watchlist for pre-ARA candidates.
    Returns formatted message.
    """
    tickers = get_watchlist_tickers()
    if not tickers:
        return "⚠️ Watchlist kosong."

    results = await scan_all(tickers[:50])

    candidates = []
    for r in results:
        price = safe_float(r["live"]["last"])
        prev_close = safe_float(r["live"]["prev_close"])
        if price <= 0 or prev_close <= 0:
            continue

        ara_limit_pct = get_ara_limit(prev_close)
        ara_price = get_ara_price(prev_close)
        proximity = ara_proximity_score(price, prev_close, ara_price)
        vsr = r["vol_spike"]
        chg = r["chg_pct"]
        streak_info = detect_ara_streak(r["ticker"], days=5)
        streak = streak_info["streak"]

        # Pre-filter
        if proximity < 40 or vsr < 3:
            continue

        score = pre_ara_score({
            "price": price,
            "prev_close": prev_close,
            "ara_price": ara_price,
            "vsr": vsr,
            "streak": streak,
            "accelerating": chg > 0,
            "cpr": 50.0,  # simplified
        })
        label = classify_pre_ara(score, proximity)

        candidates.append({
            "ticker": r["ticker"],
            "price": price,
            "chg": chg,
            "proximity": proximity,
            "vsr": vsr,
            "streak": streak,
            "score": score,
            "label": label,
        })

    if not candidates:
        return "🚫 Tidak ada kandidat Pre-ARA saat ini."

    # Group by label
    at_ara = [c for c in candidates if "AT ARA" in c["label"]]
    imminent = [c for c in candidates if "Imminent" in c["label"]]
    entry = [c for c in candidates if "Pre-ARA Entry" in c["label"]]
    watch = [c for c in candidates if c not in at_ara + imminent + entry]

    parts = [f"🚨 *Pre-ARA Momentum*"]
    parts.append(f"📅 {now_wib_str()}")
    parts.append(f"📡 Total: {len(candidates)} kandidat")
    parts.append("")

    if at_ara:
        parts.append(f"*🚨 AT ARA* ({len(at_ara)}):")
        for c in at_ara[:5]:
            parts.append(f"• *{c['ticker']}* IDR {c['price']:,.0f} | {c['chg']:+.2f}% | streak {c['streak']}d")
        parts.append("")

    if imminent:
        parts.append(f"*🔴 Imminent ARA* ({len(imminent)}):")
        for c in sorted(imminent, key=lambda x: x["score"], reverse=True)[:5]:
            parts.append(f"• *{c['ticker']}* prox {c['proximity']:.0f}% | VSR {c['vsr']:.1f}x | +{c['chg']:.1f}%")
        parts.append("")

    if entry:
        parts.append(f"*🟠 Pre-ARA Entry* ({len(entry)}):")
        for c in sorted(entry, key=lambda x: x["score"], reverse=True)[:5]:
            parts.append(f"• *{c['ticker']}* prox {c['proximity']:.0f}% | VSR {c['vsr']:.1f}x | +{c['chg']:.1f}%")
        parts.append("")

    if watch:
        parts.append(f"*🟡 Approaching*: {', '.join(c['ticker'] for c in watch[:8])}")

    return "\n".join(parts)


async def run_and_send():
    msg = await scan_pre_ara()
    await send_telegram(msg + "\n\n#PreARA #IDX")
    print("Pre-ARA alert sent.")
