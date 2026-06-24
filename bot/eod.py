"""
📊 End of Day Recap — ~16:00 WIB
Summary: best/worst performers, trending, pre-ARA results.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.data_pipeline import get_watchlist_tickers, scan_all, now_wib_str, get_ihsg_status
from data.fetchers import safe_float
from data.scoring import trend_tier, trending_score
from data.pre_ara import get_ara_price, ara_proximity_score
from bot.telegram import send_telegram


async def run_and_send():
    tickers = get_watchlist_tickers()
    if not tickers:
        await send_telegram("⚠️ Watchlist kosong.")
        return

    ihsg = get_ihsg_status()
    results = await scan_all(tickers[:40])

    # Sort
    top_gainers = sorted(results, key=lambda x: x["chg_pct"], reverse=True)
    top_losers = sorted(results, key=lambda x: x["chg_pct"])
    most_active = sorted(results, key=lambda x: x["vol_spike"], reverse=True)

    # Pre-ARA result (who hit ARA?)
    at_ara = []
    approached = []
    for r in results:
        price = safe_float(r["live"]["last"])
        prev = safe_float(r["live"]["prev_close"])
        if price > 0 and prev > 0:
            ara_price = get_ara_price(prev)
            proximity = ara_proximity_score(price, prev, ara_price)
            if proximity >= 95:
                at_ara.append(r["ticker"])
            elif proximity >= 70:
                approached.append(r["ticker"])

    parts = [f"📊 *EOD Recap*"]
    parts.append(f"📅 {now_wib_str()}")
    ihsg_arrow = "🟢" if ihsg["chg_pct"] >= 0 else "🔴"
    parts.append(f"{ihsg_arrow} IHSG: {ihsg['chg_pct']:+.2f}% | Close IDR {ihsg['last']:,.0f} | CPR {ihsg['cpr']:.0f}%")
    parts.append(f"📡 {len(results)}/{len(tickers)} scanned")
    parts.append("")

    if top_gainers:
        parts.append(f"*🔥 Top Gainers*:")
        for r in top_gainers[:5]:
            parts.append(f"• *{r['ticker']}* {r['chg_pct']:+.2f}% | IDR {r['live']['last']:,.0f} | VSR {r['vol_spike']:.1f}x")
        parts.append("")

    if top_losers:
        losers = [r for r in top_losers if r["chg_pct"] < 0]
        if losers:
            parts.append(f"*📉 Top Losers*:")
            for r in losers[:3]:
                parts.append(f"• *{r['ticker']}* {r['chg_pct']:+.2f}% | IDR {r['live']['last']:,.0f}")
            parts.append("")

    if most_active:
        parts.append(f"*⚡ Most Active*:")
        for r in most_active[:3]:
            parts.append(f"• *{r['ticker']}* VSR {r['vol_spike']:.1f}x | {r['chg_pct']:+.2f}%")
        parts.append("")

    if at_ara:
        parts.append(f"*🚨 Hit ARA Today*: {', '.join(at_ara)}")
    if approached:
        parts.append(f"*🎯 Approached ARA*: {', '.join(approached[:5])}")
    parts.append("")

    # Strong buy count
    sb = len([r for r in results if r["score"] >= 75])
    b = len([r for r in results if 65 <= r["score"] < 75])
    parts.append(f"📈 Strong Buy: {sb}  |  Buy: {b}")

    msg = "\n".join(parts) + "\n\n#EOD #IDX"
    print(msg)
    await send_telegram(msg)
    return msg
