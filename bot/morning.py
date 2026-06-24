"""
📱 Morning Brief — 08:50 WIB & 09:15 WIB

08:50: Pre-market overview (yesterday close, overnight news, IHSG futures, watchlist alert)
09:15: Early bird (first 15m gappers, volume spike, trending from Stockbit)
"""
import sys
import os
import asyncio
from datetime import datetime

import pytz
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.data_pipeline import get_watchlist_tickers, get_hist_row, fetch_ticker_live, scan_all, now_wib_str
from data.fetchers import fetch_news_for_tickers, safe_float
from data.scoring import compute_intraday_score
from bot.telegram import send_telegram

WIB = pytz.timezone("Asia/Jakarta")


async def brief_premarket() -> str:
    """
    08:50 — Before market opens. Focus on:
    - IHSG yesterday close + futures
    - Overnight global (DJI, S&P 500)
    - News macro
    - Watchlist alert: stocks near support/resistance
    """
    # IHSG
    ihsg = yf.Ticker("^JKSE").info
    ihsg_last = safe_float(ihsg.get("regularMarketPreviousClose", 0))
    ihsg_chg = safe_float(ihsg.get("preMarketChangePercent", 0))
    ihsg_open = safe_float(ihsg.get("regularMarketOpen", 0))

    # Global indices (yesterday close)
    dji = yf.Ticker("^DJI").info
    spx = yf.Ticker("^GSPC").info

    dji_chg = safe_float(dji.get("regularMarketChangePercent", 0))
    spx_chg = safe_float(spx.get("regularMarketChangePercent", 0))

    parts = [f"☀️ *Morning Brief — Pre-Market*"]
    parts.append(f"📅 {now_wib_str()}")
    parts.append("")

    # IHSG
    parts.append(f"*IHSG*: IDR {ihsg_last:,.0f}")
    if ihsg_chg != 0:
        arrow = "🟢" if ihsg_chg >= 0 else "🔴"
        parts.append(f"{arrow} Pre-market: {ihsg_chg:+.2f}%")
    parts.append("")

    # Global
    dji_arrow = "🟢" if dji_chg >= 0 else "🔴"
    spx_arrow = "🟢" if spx_chg >= 0 else "🔴"
    parts.append(f"*Global:*")
    parts.append(f"{dji_arrow} DJI: {dji_chg:+.2f}%")
    parts.append(f"{spx_arrow} S&P 500: {spx_chg:+.2f}%")
    parts.append("")

    # News (top 5 macro)
    try:
        from data.news import fetch_macro_news_yfinance
        macro = fetch_macro_news_yfinance()
        if macro:
            parts.append("*📰 Berita:*")
            for item in macro[:3]:
                parts.append(f"• {item.get('title', '')}")
    except Exception:
        pass

    return "\n".join(parts)


async def brief_early() -> str:
    """
    09:15 — First 15 min after open. Focus on:
    - IHSG open vs previous close
    - Gappers (change > 3%)
    - Volume spike (VSR > 2.5x)
    - Trending from Stockbit
    """
    tickers = get_watchlist_tickers()
    if not tickers:
        return "⚠️ Watchlist kosong. Cek koneksi Google Sheets."

    # IHSG
    try:
        ihsg = yf.Ticker("^JKSE").info
        ihsg_last = safe_float(ihsg.get("regularMarketPrice", 0))
        ihsg_prev = safe_float(ihsg.get("regularMarketPreviousClose", 0))
        ihsg_chg = ((ihsg_last - ihsg_prev) / ihsg_prev * 100) if ihsg_prev > 0 else 0.0
        ihsg_minichg = "🟢" if ihsg_chg >= 0 else "🔴"
        ihsg_text = f"{ihsg_minichg} IHSG: {ihsg_chg:+.2f}% di IDR {ihsg_last:,.0f}"
    except Exception:
        ihsg_text = "⚠️ IHSG: Data unavailable"

    # Scan
    results = await scan_all(tickers[:40])  # scan top 40 only (avoid rate limit)
    if not results:
        return "⚠️ Gak ada data live saat ini."

    # Filter sections
    gappers = [r for r in results if abs(r["chg_pct"]) >= 3.0]
    vol_spike = [r for r in results if r["vol_spike"] >= 2.5]
    strong_buy = [r for r in results if r["score"] >= 75]
    mixed = sorted(results, key=lambda x: x["vol_spike"], reverse=True)[:5]

    parts = [f"☀️ *Morning Open — Early Bird*"]
    parts.append(f"📅 {now_wib_str()}")
    parts.append(ihsg_text)
    parts.append(f"📡 {len(results)}/{len(tickers)} tickers scanned")
    parts.append("")

    if gappers:
        parts.append(f"*🔥 Gappers* (≥ ±3%):")
        for r in sorted(gappers, key=lambda x: abs(x["chg_pct"]), reverse=True)[:5]:
            arrow = "🟢" if r["chg_pct"] >= 0 else "🔴"
            parts.append(f"• *{r['ticker']}* {arrow} {r['chg_pct']:+.2f}%  | IDR {r['live']['last']:,.0f}")
        parts.append("")

    if vol_spike:
        parts.append(f"*⚡ Vol Spike* (≥ 2.5x):")
        for r in sorted(vol_spike, key=lambda x: x["vol_spike"], reverse=True)[:5]:
            parts.append(f"• *{r['ticker']}* VSR {r['vol_spike']:.1f}x | {r['chg_pct']:+.2f}%")
        parts.append("")

    if strong_buy:
        parts.append(f"*🎯 Strong Buys* (Score ≥ 75):")
        for r in sorted(strong_buy, key=lambda x: x["score"], reverse=True)[:5]:
            parts.append(f"• *{r['ticker']}* Score {r['score']} | {r['signal']}")
        parts.append("")

    return "\n".join(parts)


async def run_and_send(kind: str):
    """
    kind: "premarket" | "early"
    """
    if kind == "premarket":
        msg = await brief_premarket()
    else:
        msg = await brief_early()

    await send_telegram(msg + "\n\n#IDX #MorningBrief")
    print(f"Morning brief ({kind}) sent.")
