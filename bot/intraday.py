"""
🎯 Intraday Strong Buys + Scalping Picks — ~11:00 WIB
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.data_pipeline import get_watchlist_tickers, scan_all, now_wib_str
from data.fetchers import safe_float
from data.scoring import compute_action_recommendation, calculate_strategies
from bot.telegram import send_telegram

SIGNAL_EMOJI = {
    "STRONG BUY": "🟢",
    "BUY": "🔵",
    "SPECULATIVE": "🟡",
}


async def run_and_send():
    tickers = get_watchlist_tickers()
    if not tickers:
        await send_telegram("⚠️ Watchlist kosong, gak bisa scan intraday.")
        return

    results = await scan_all(tickers[:40])

    # Filter strong buy
    strong = [r for r in results if r["score"] >= 75]
    buys = [r for r in results if 65 <= r["score"] < 75]
    scalp = [r for r in results if r["vol_spike"] >= 2.0 and r["chg_pct"] >= 1.0 and r["score"] >= 60]

    parts = [f"🎯 *Intraday Picks — Mid-Session*"]
    parts.append(f"📅 {now_wib_str()}")
    parts.append(f"📡 {len(results)} tickers scanned")
    parts.append("")

    if strong:
        parts.append(f"*🟢 STRONG BUY* ({len(strong)}):")
        for r in sorted(strong, key=lambda x: x["score"], reverse=True)[:5]:
            price = safe_float(r["live"]["last"])
            hist = r["hist"]
            # Basic TP/SL
            sl = safe_float(hist.get("SL_Practical", 0)) or round(price * 0.93, 0)
            tp = safe_float(hist.get("52W High", 0)) or round(price * 1.12, 0)
            action, max_pos, notes = compute_action_recommendation(price, sl, tp, r["score"], safe_float(hist.get("RSI14", 0)))
            parts.append(f"• *{r['ticker']}* Score {r['score']}")
            parts.append(f"  IDR {price:,.0f} | {r['chg_pct']:+.2f}% | VSR {r['vol_spike']:.1f}x")
            parts.append(f"  🎯 TP: IDR {tp:,.0f}  🛑 SL: IDR {sl:,.0f}")
        parts.append("")

    if buys and not strong:
        parts.append(f"*🔵 BUY* ({len(buys)}):")
        for r in sorted(buys, key=lambda x: x["score"], reverse=True)[:3]:
            parts.append(f"• *{r['ticker']}* Score {r['score']} | {r['chg_pct']:+.2f}% | IDR {r['live']['last']:,.0f}")
        parts.append("")

    if scalp:
        parts.append(f"*⚡ Scalping* ({len(scalp)}):")
        for r in sorted(scalp, key=lambda x: x["vol_spike"], reverse=True)[:4]:
            price = safe_float(r["live"]["last"])
            tp = round(price * 1.025, 0)
            sl = round(price * 0.985, 0)
            parts.append(f"• *{r['ticker']}* IDR {price:,.0f} | VSR {r['vol_spike']:.1f}x")
            parts.append(f"  🎯 TP {tp:,.0f}  🛑 SL {sl:,.0f}  R/R {((tp - price) / max(price - sl, 1)):.1f}x")
        parts.append("")

    if not strong and not scalp:
        parts.append("Tidak ada kandidat strong buy / scalping saat ini. 📉")
    elif not strong:
        parts.append("(Tidak ada Strong Buy, hanya BUY/Scalping)")

    msg = "\n".join(parts) + "\n\n#IntradayPicks #IDX"
    print(msg)
    await send_telegram(msg)
    return msg
