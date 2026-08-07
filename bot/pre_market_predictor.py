"""
🔭 Pre-Market Watch — 08:40 WIB cron job.

Heuristic watch list ranking watchlist tickers by probability of a strong
open: ARA streak + yesterday's BSJP + overnight per-ticker news sentiment +
today's IDX corporate calendar, scaled by the overnight US macro context.

The result is explicitly labeled a heuristic pra-buka watch list (reasons
shown per ticker), not a verdict. Rows are persisted to SQLite
(`pre_market_predictions`) so the Pick of the Day tab can render them
read-only, and a backtest script (`scripts/backtest_premarket.py`) can
recalibrate the weights.

Usage:
    uv run python -m bot.pre_market_predictor
"""
import asyncio
import json
import os
import sys
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.data_pipeline import get_watchlist_tickers, now_wib_str
from bot.morning import get_macro_context
from bot.telegram import escape_md, send_telegram
from data.calendar import events_for_ticker_on
from data.news import ticker_sentiment_map
from data.pre_ara import detect_ara_streak
from repositories.sqlite_repository import sqlite_repository

WIB = pytz.timezone("Asia/Jakarta")

TIER_WATCH = "WATCH CLOSELY"
TIER_RADAR = "ON RADAR"
TIER_BELOW = "BELOW RADAR"

MIN_SCORE = 20  # BELOW RADAR floor — sinyal lemah tetap ditampilkan dengan notes
MAX_TICKERS = 40

# Persistent cache TTLs (per hari) — komponen mahal (yfinance/news) tidak
# di-fetch ulang saat re-run di hari yang sama.
MACRO_CACHE_TTL = 12 * 3600
NEWS_CACHE_TTL = 8 * 3600
STREAK_CACHE_TTL = 12 * 3600


def _bsjp_points(tier: str) -> int:
    """BSJP tier → pre-market points (Prime 25 / Good 15 / Watchlist 0)."""
    if not tier:
        return 0
    if "Prime" in tier:
        return 25
    if "Good" in tier:
        return 15
    if "Watchlist" in tier:
        return 0
    return 0


def _cache_get_json(cache_key: str):
    """Read a JSON value from the persistent TTL cache, or None."""
    try:
        raw = sqlite_repository.cache_get(cache_key)
        return json.loads(raw) if raw is not None else None
    except Exception:
        return None


def _cache_set_json(cache_key: str, value, ttl_sec: int) -> None:
    """Write a JSON value to the persistent TTL cache (best-effort)."""
    try:
        sqlite_repository.cache_set(cache_key, json.dumps(value, ensure_ascii=False), ttl_sec)
    except Exception:
        pass


async def compute_premarket_scores(tickers: list[str], today=None) -> list[dict]:
    """Score each watchlist ticker for a strong open (heuristic).

    Components (each wrapped in try/except — a failure contributes 0 and never
    crashes the run):
      - ARA streak: min(streak * 10, 30) when riding (excludes today's bar)
      - Yesterday BSJP tier: Prime 25 / Good 15 / Watchlist 0 (reason includes
        the actual trade date)
      - Overnight news: min(confidence * 25, 25) when polarity is positive
      - Today's corporate calendar event: +15 (reason = event type)
    Sum is scaled by the macro multiplier: risk-on ×1.1, risk-off ×0.85,
    else ×1.0, then rounded.

    Tiers: ≥60 WATCH CLOSELY, ≥35 ON RADAR, ≥20 BELOW RADAR (sinyal lemah,
    tetap ditampilkan dengan notes); anything below 20 is excluded.
    """
    if today is None:
        today = datetime.now(WIB).date()
    elif isinstance(today, str):
        today = datetime.strptime(today[:10], "%Y-%m-%d").date()
    today_iso = today.isoformat()

    # Macro context — cached per day (persistent, re-run instan)
    macro = _cache_get_json(f"macro:{today_iso}")
    if macro is None:
        macro = get_macro_context()
        _cache_set_json(f"macro:{today_iso}", macro, MACRO_CACHE_TTL)

    # Overnight news sentiment map — cached per day (bagian paling mahal)
    sentiment_map: dict = {}
    cache_key_news = f"news:{today_iso}"
    cached_news = _cache_get_json(cache_key_news)
    if cached_news is not None:
        sentiment_map = cached_news
    else:
        try:
            sentiment_map = ticker_sentiment_map(list(tickers or []))
            _cache_set_json(cache_key_news, sentiment_map, NEWS_CACHE_TTL)
        except Exception:
            sentiment_map = {}

    rows = []
    for ticker in (tickers or [])[:MAX_TICKERS]:
        reasons: list[str] = []
        points = 0.0

        # 1) ARA streak (riding only) — today's in-progress bar excluded.
        #    Persistent per (ticker, hari) — stabil sepanjang hari.
        try:
            cache_key_streak = f"streak:{ticker}:{today_iso}"
            streak_info = _cache_get_json(cache_key_streak)
            if streak_info is None:
                streak_info = detect_ara_streak(ticker, exclude_today=True)
                _cache_set_json(cache_key_streak, streak_info, STREAK_CACHE_TTL)
            if streak_info.get("is_riding"):
                streak = int(streak_info.get("streak", 0) or 0)
                pts = min(streak * 10, 30)
                if pts > 0:
                    points += pts
                    reasons.append(f"ARA streak {streak}d (+{pts})")
        except Exception:
            pass

        # 2) Yesterday's BSJP result (persisted by bot/bsjp.py)
        try:
            bsjp = sqlite_repository.get_last_bsjp_result(ticker)
            if bsjp and bsjp.get("trade_date") != today_iso:
                pts = _bsjp_points(bsjp.get("tier"))
                if pts > 0:
                    points += pts
                    reasons.append(f"BSJP {bsjp.get('tier')} {bsjp['trade_date']} (+{pts})")
        except Exception:
            pass

        # 3) Overnight per-ticker news sentiment
        try:
            sent = sentiment_map.get(ticker, {})
            if sent.get("polarity") == "positif":
                confidence = float(sent.get("confidence", 0) or 0)
                pts = min(confidence * 25, 25)
                points += pts
                headline = (sent.get("headline") or "").strip()
                if len(headline) > 80:
                    headline = headline[:77] + "..."
                reasons.append(f"📰 {headline} (+{pts:.0f})")
        except Exception:
            pass

        # 4) Today's corporate calendar event
        try:
            events = events_for_ticker_on(ticker, today)
            if events:
                ev = events[0]
                ev_type = ev.get("event_type") or ev.get("signal") or "Corporate Event"
                points += 15
                reasons.append(f"📅 {ev_type} (+15)")
        except Exception:
            pass

        if not reasons:
            continue  # no signal today → not a candidate

        # 5) Macro multiplier
        multiplier = 1.0
        if macro.get("risk_on"):
            multiplier = 1.1
            reasons.append("🌐 Risk-on ×1.1")
        elif macro.get("risk_off"):
            multiplier = 0.85
            reasons.append("🌐 Risk-off ×0.85")

        score = round(points * multiplier)
        if score >= 60:
            tier = TIER_WATCH
        elif score >= 35:
            tier = TIER_RADAR
        elif score >= MIN_SCORE:
            tier = TIER_BELOW
        else:
            continue

        rows.append({"ticker": ticker, "score": score, "tier": tier, "reasons": reasons})

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


async def run_and_send() -> str:
    """Cron entry: watchlist → scores → persist → one Telegram message."""
    tickers = get_watchlist_tickers()
    if not tickers:
        msg = "⚠️ Watchlist kosong."
        await send_telegram(msg)
        print(msg)
        return msg

    today = datetime.now(WIB).date()
    rows = await compute_premarket_scores(tickers, today=today)
    sqlite_repository.save_premarket_predictions(today.isoformat(), rows)
    sqlite_repository.save_premarket_run(
        today.isoformat(), len(rows), ran_at=datetime.now(WIB).isoformat()
    )

    watch = [r for r in rows if r["tier"] == TIER_WATCH]
    radar = [r for r in rows if r["tier"] == TIER_RADAR]
    below = [r for r in rows if r["tier"] == TIER_BELOW]

    parts = [
        "🔭 *Pre-Market Watch* — " + escape_md(now_wib_str()),
        "",
        "Heuristic pra-buka, *bukan* prediksi. Skor = ARA streak + BSJP kemarin "
        "+ berita semalam + kalender hari ini, × multiplier pasar.",
        "",
    ]
    if watch:
        parts.append(f"*WATCH CLOSELY* (≥60):")
        for r in watch:
            parts.append(f"• *{escape_md(r['ticker'])}* — {r['score']}")
            parts.append("  " + escape_md(" · ".join(r["reasons"])))
        parts.append("")
    if radar:
        parts.append(f"*ON RADAR* (≥35):")
        for r in radar:
            parts.append(f"• *{escape_md(r['ticker'])}* — {r['score']}")
            parts.append("  " + escape_md(" · ".join(r["reasons"])))
        parts.append("")
    if not watch and not radar and below:
        # Fallback: tidak ada kandidat kuat — tampilkan sinyal lemah + notes
        parts.append(f"⚠️ *BELOW RADAR* (20–34) — sinyal lemah, catatan saja:")
        for r in below[:10]:
            parts.append(f"• *{escape_md(r['ticker'])}* — {r['score']}")
            parts.append("  " + escape_md(" · ".join(r["reasons"])))
        parts.append("")
    if not watch and not radar and not below:
        parts.append("Tidak ada kandidat hari ini.")

    msg = "\n".join(parts) + "\n\n" + escape_md("#PreMarket #IDX")
    print(msg)
    await send_telegram(msg)
    return msg


if __name__ == "__main__":
    asyncio.run(run_and_send())
