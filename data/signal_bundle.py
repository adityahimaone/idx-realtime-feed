"""Signal-row builders extracted from the legacy sub-signal tabs.

Each builder converts a `scored_list` (the per-ticker dicts produced by
app.py) into the same row structures the old tabs returned, so the Pick of the
Day tab can compute Mega Score inputs without requiring other tabs to be
visited first. All builders are cached with st.cache_data(ttl=300).
"""
import streamlit as st
import yfinance as yf

from data.fetchers import safe_float, fetch_news_for_tickers
from data.scoring import trending_score, trend_tier
from data.pre_ara import (
    get_ara_limit,
    get_ara_price,
    ara_proximity_score,
    ara_distance,
    pre_ara_score,
    classify_pre_ara,
    detect_ara_streak,
)
from data.news import build_per_ticker_sentiment


# ─── Trending ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def build_trending_rows(scored_list) -> list[dict]:
    """Stockbit-methodology trending rows (was Tab 4)."""
    processed_trending = []
    for s in scored_list:
        data = s["raw_data_obj"]
        hist_row = s["hist_row_obj"]

        vol_today = safe_float(data.get("volume", 0))
        vol_avg = max(safe_float(hist_row.get("Vol_Avg", 1)), 1.0)
        vsr = vol_today / vol_avg

        freq_today = safe_float(data.get("frequency", 0))
        freq_avg = safe_float(hist_row.get("Freq_Avg", 1))
        freq_surge = (freq_today / freq_avg) if freq_avg > 0 else 0

        change_pct = s["Change %"]

        val_today = safe_float(data.get("value", 0))
        val_avg = safe_float(hist_row.get("Val_Avg", 1))
        val_surge = (val_today / val_avg) if val_avg > 0 else 0

        foreign_buy = safe_float(data.get("foreign_buy", 0))
        foreign_sell = safe_float(data.get("foreign_sell", 0))
        net_foreign = foreign_buy - foreign_sell
        nfr = (net_foreign / vol_today * 100) if vol_today > 0 else 0.0

        sig = {
            "vsr": vsr,
            "freq_surge": freq_surge,
            "change_pct": change_pct,
            "val_surge": val_surge,
            "net_foreign": net_foreign,
            "freq": freq_today,
            "value_rp": val_today,
            "volume_total": vol_today,
        }
        score = trending_score(sig)
        if score > 0:
            processed_trending.append({
                "Ticker": s["Ticker"],
                "Trending Score": score,
                "Tier": trend_tier(score),
                "Price": s["Live Price"],
                "Change %": change_pct,
                "VSR": round(vsr, 2),
                "Freq": int(freq_today),
                "NFR %": round(nfr, 2),
                "Value (Rp M)": round(val_today / 1_000_000, 1),
            })
    return processed_trending


# ─── BSJP ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def build_bsjp_rows(scored_list) -> list[dict]:
    """BSJP setup rows (was Tab 5)."""
    bsjp_data = []
    for s in scored_list:
        hist_row = s["hist_row_obj"]
        raw_data = s["raw_data_obj"]

        price = s["Live Price"]
        high = safe_float(raw_data.get("high", price))
        low = safe_float(raw_data.get("low", price))
        chg = s["Change %"]

        support = safe_float(hist_row.get("Support", price * 0.95))
        if support <= 0 or support >= price:
            support = price * 0.95
        resistance = safe_float(hist_row.get("Breakout", price * 1.05))
        if resistance <= 0 or resistance <= price:
            resistance = price * 1.05

        day_range = high - low
        price_pos = (price - low) / day_range if day_range > 0 else 1.0

        prev_close = safe_float(raw_data.get("prev_close", 0)) or safe_float(hist_row.get("ClosePrev", price))
        ara_limit_pct = get_ara_limit(prev_close)
        ara_used_pct = (chg / ara_limit_pct * 100) if ara_limit_pct > 0 else 0.0

        if chg > 1.0 and price_pos >= 0.70 and ara_used_pct < 85:
            tp = round(resistance, 2)
            sl = round(max(support, price * 0.97), 2)
            rr = (tp - price) / max(1.0, price - sl)

            vol_avg = safe_float(hist_row.get("Vol_Avg", 1))
            vsr = safe_float(raw_data.get("volume", 0)) / vol_avg if vol_avg > 0 else 1.0

            fb = safe_float(raw_data.get("foreign_buy", 0))
            fs = safe_float(raw_data.get("foreign_sell", 0))
            net_foreign_ratio = fb / max(fs, 1.0)
            if net_foreign_ratio >= 3.0:
                foreign_flow_score = 100
            elif net_foreign_ratio >= 2.0:
                foreign_flow_score = 80
            elif net_foreign_ratio >= 1.2:
                foreign_flow_score = 65
            elif net_foreign_ratio >= 0.8:
                foreign_flow_score = 50
            else:
                foreign_flow_score = 30

            setup_score = int(round(
                0.45 * s["Intraday Score"]
                + 0.20 * min(100, vsr * 20)
                + 0.20 * foreign_flow_score
                + 0.15 * (price_pos * 100)
            ))

            if rr >= 1.2 and setup_score >= 60:
                bsjp_data.append({
                    "Ticker": s["Ticker"],
                    "Company Name": s["Company Name"],
                    "Live Price": price,
                    "Change %": chg,
                    "Price Pos (Day Range)": f"{int(price_pos * 100)}%",
                    "Volume Surge (VSR)": vsr,
                    "Entry (Buy Sore)": price,
                    "Target (Jual Pagi)": tp,
                    "Stop Loss (SL)": sl,
                    "Risk/Reward Ratio": round(rr, 2),
                    "Setup Score": setup_score,
                })
    return bsjp_data


# ─── Minervini ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400)
def _fetch_long_smas(ticker: str) -> dict:
    """SMA150/200 + 52W high/low + 3M-ago price from yfinance (cached 24h)."""
    try:
        df = yf.Ticker(f"{ticker}.JK").history(period="2y", interval="1d")
        if df.empty or len(df) < 200:
            return {}
        lookback_252 = min(len(df), 252)
        lookback_63 = min(len(df), 63)
        return {
            "sma150": round(df["Close"].rolling(150).mean().iloc[-1], 2),
            "sma200": round(df["Close"].rolling(200).mean().iloc[-1], 2),
            "low52": round(df["Low"].iloc[-lookback_252:].min(), 2),
            "high52": round(df["High"].iloc[-lookback_252:].max(), 2),
            "price_3mo_ago": round(df["Close"].iloc[-lookback_63], 2),
        }
    except Exception:
        return {}


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_long_smas_batch(tickers: tuple) -> dict:
    """SMA150/200 + 52W + 3M-ago price via ONE yfinance batch download (24h cache).

    The per-ticker alternative costs ~1 request per symbol; a 40+ ticker
    watchlist made the first Minervini pass the slowest part of app startup.
    Callers keep sheet values as the primary source and use this as a fill-in.
    """
    import pandas as pd

    results: dict = {}
    try:
        df = yf.download(
            [f"{t}.JK" for t in tickers],
            period="2y", interval="1d", auto_adjust=True,
            group_by="ticker", threads=False, progress=False,
        )
    except Exception:
        return results
    if df is None or df.empty:
        return results
    for t in tickers:
        try:
            sub = df[t + ".JK"] if isinstance(df.columns, pd.MultiIndex) else df
            close = sub["Close"].dropna()
            if close.empty or len(close) < 200:
                continue
            lookback_252 = min(len(close), 252)
            lookback_63 = min(len(close), 63)
            results[t] = {
                "sma150": round(close.rolling(150).mean().iloc[-1], 2),
                "sma200": round(close.rolling(200).mean().iloc[-1], 2),
                "low52": round(sub["Low"].dropna().iloc[-lookback_252:].min(), 2),
                "high52": round(sub["High"].dropna().iloc[-lookback_252:].max(), 2),
                "price_3mo_ago": round(close.iloc[-lookback_63], 2),
            }
        except Exception:
            continue
    return results


@st.cache_data(ttl=86400)
def _fetch_ihsg_3mo_return() -> float:
    try:
        df = yf.Ticker("^JKSE").history(period="3mo", interval="1d")
        if df.empty or len(df) < 5:
            return 0.0
        return (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
    except Exception:
        return 0.0


@st.cache_data(ttl=300)
def build_minervini_rows(scored_list) -> list[dict]:
    """Mark Minervini Trend Template rows (was Tab 6).

    Sheet values (MA50/MA200/52W High/Low) are preferred — the sync daemon
    keeps them fresh and reading them costs nothing. yfinance (one batched,
    24h-cached download) only fills MA150 and the 3-month-ago price.
    """
    if not scored_list:
        return []
    rs_ihsg = _fetch_ihsg_3mo_return()
    tickers = tuple(sorted({s["Ticker"] for s in scored_list}))
    long_smas_batch = _fetch_long_smas_batch(tickers)
    minervini_data = []
    for s in scored_list:
        hist_row = s["hist_row_obj"]
        raw_data = s["raw_data_obj"]
        ticker = s["Ticker"]
        last = s["Live Price"]

        cached_vals = long_smas_batch.get(ticker)
        if cached_vals is None:
            cached_vals = _fetch_long_smas(ticker)  # per-ticker fallback
        sma50 = safe_float(hist_row.get("MA50", 0))
        sma200 = cached_vals.get("sma200") or safe_float(hist_row.get("MA200", 0))
        sma150 = cached_vals.get("sma150") or safe_float(hist_row.get("MA150", 0))
        if sma150 <= 0:
            sma150 = round(sma50 * 0.4 + sma200 * 0.6, 2)

        high52 = cached_vals.get("high52") or safe_float(hist_row.get("52W High", 0))
        if high52 <= 0:
            high52 = last * 1.10
        low52 = cached_vals.get("low52") or safe_float(hist_row.get("52W Low", 0))
        if low52 <= 0:
            low52 = last * 0.70

        vol_today = safe_float(raw_data.get("volume", 0))
        vol_avg20 = safe_float(hist_row.get("Vol_Avg", 1))
        if vol_avg20 <= 0:
            vol_avg20 = 1.0

        price_3mo_ago = cached_vals.get("price_3mo_ago") or (safe_float(hist_row.get("ClosePrev", last)) * 0.90)
        rs_ticker = (last / price_3mo_ago - 1) * 100 if price_3mo_ago > 0 else 0.0
        rs_positive = rs_ticker > rs_ihsg

        conds = {
            "Price > SMA50": last > sma50,
            "Price > SMA150": last > sma150,
            "Price > SMA200": last > sma200,
            "SMA50 > SMA150": sma50 > sma150,
            "SMA150 > SMA200": sma150 > sma200,
            "SMA50 > SMA200": sma50 > sma200,
            "Within 25% of 52W High": last >= (high52 * 0.75),
            "Volume > Avg20": vol_today > vol_avg20,
            "Price > 52W Low + 25%": last >= (low52 * 1.25) if low52 > 0 else False,
            "RS vs IHSG positive": rs_positive,
        }
        score_val = sum(conds.values())
        passed = score_val >= 8
        minervini_data.append({
            "Ticker": ticker,
            "Company Name": s["Company Name"],
            "Live Price": last,
            "SMA 50": sma50,
            "SMA 150 (Est)": sma150,
            "SMA 200": sma200,
            "52W High": high52,
            "52W Low": low52,
            "Score": f"{score_val}/10",
            "Passed Template": "✅ PASSED" if passed else "❌ FAILED",
            "score_int": score_val,
        })
    return minervini_data


# ─── Pre-ARA ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def build_pre_ara_rows(scored_list) -> list[dict]:
    """Pre-ARA momentum rows (was Tab 9)."""
    rows = []
    for s in scored_list:
        raw = s["raw_data_obj"]
        hist = s["hist_row_obj"]

        price = safe_float(s["Live Price"])
        chg = safe_float(s["Change %"])
        if price <= 0:
            continue

        prev_close = safe_float(raw.get("prev_close", 0)) or safe_float(hist.get("ClosePrev", price))
        if prev_close <= 0:
            prev_close = price

        ara_limit_pct = get_ara_limit(prev_close)
        ara_price = get_ara_price(prev_close)
        proximity = ara_proximity_score(price, prev_close, ara_price)
        dist_pct = ara_distance(price, ara_price)

        if proximity < 40:
            continue

        volume = safe_float(raw.get("volume", 0))
        avg_vol = safe_float(hist.get("Vol_Avg", 1))
        vsr = volume / avg_vol if avg_vol > 0 else 1.0

        high = safe_float(raw.get("high", price))
        low = safe_float(raw.get("low", price))
        cpr_val = round((price - low) / (high - low) * 100, 1) if high > low else 50.0

        streak_info = detect_ara_streak(s["Ticker"], days=5)
        streak = streak_info["streak"]

        frequency = safe_float(raw.get("frequency", 0))

        sig = {
            "price": price,
            "prev_close": prev_close,
            "ara_price": ara_price,
            "vsr": vsr,
            "streak": streak,
            "accelerating": chg > 0,
            "cpr": cpr_val,
        }
        score = pre_ara_score(sig)
        label = classify_pre_ara(score, proximity)

        rows.append({
            "Ticker": s["Ticker"],
            "Price": price,
            "PrevClose": prev_close,
            "ΔP%": chg,
            "ARA %": ara_limit_pct,
            "ARA Price": ara_price,
            "Proximity": proximity,
            "Dist%": dist_pct,
            "VSR": round(vsr, 2),
            "Freq": int(frequency),
            "Streak": streak,
            "CPR": cpr_val,
            "Pre-ARA Score": score,
            "Signal": label,
        })
    return rows


# ─── News sentiment ──────────────────────────────────────────────────────────
# Note: the Pick of the Day build deliberately skips news (see app.py) — the
# News tab owns the news pipeline. build_news_rows remains as the reusable
# per-ticker sentiment builder for anything that needs the news signal.

@st.cache_data(ttl=300)
def _fetch_all_news_cached() -> dict:
    """Fetch all 6 news sources once per 5 minutes."""
    from data.news import fetch_all_news
    return fetch_all_news()


@st.cache_data(ttl=300)
def build_news_rows(scored_list) -> list[dict]:
    """Per-ticker news sentiment rows (was Tab 8 section 4)."""
    if not scored_list:
        return []
    all_articles = []
    all_news = _fetch_all_news_cached()
    for src, art_list in all_news.items():
        if art_list:
            for art in art_list:
                art["source"] = src
            all_articles.extend(art_list)

    tickers = [s["Ticker"] for s in scored_list]
    yf_data = fetch_news_for_tickers(tickers)
    return build_per_ticker_sentiment(all_articles, yf_data, tickers)
