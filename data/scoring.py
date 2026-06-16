import math
from data.fetchers import safe_float


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

    # --- GANTI hardcoded 60/60 dengan proxy dari data yang sudah ada ---
    fb = safe_float(data.get("foreign_buy", 0))
    fs = safe_float(data.get("foreign_sell", 0))
    net_foreign_ratio = fb / max(fs, 1.0)
    if net_foreign_ratio >= 3.0:
        imbalance_score = 100
    elif net_foreign_ratio >= 2.0:
        imbalance_score = 80
    elif net_foreign_ratio >= 1.2:
        imbalance_score = 65
    elif net_foreign_ratio >= 0.8:
        imbalance_score = 50
    else:
        imbalance_score = 30

    high = safe_float(data.get("high", 0))
    low  = safe_float(data.get("low", 0))
    last = safe_float(data.get("last", 0))
    if high > low:
        price_pos = (last - low) / (high - low)
        spread_score = round(40 + price_pos * 60, 1)   # posisi di range hari ini sbg proxy buying pressure
    else:
        spread_score = 60   # fallback kalau data range tidak tersedia

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

    total = int(round(
        vol_score * 0.25 +
        imbalance_score * 0.25 +
        price_score * 0.20 +
        spread_score * 0.15 +
        hist_score * 0.15
    ))

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
    entry_agg = price
    tp_agg = entry_agg * 1.10
    sl_agg = entry_agg * 0.95

    tick_size = get_tick_size(price)
    entry_mod = price - 2 * tick_size
    tp_mod = entry_mod * 1.06
    sl_mod = entry_mod * 0.97

    entry_low = price - 4 * tick_size
    tp_low = entry_low * 1.08
    sl_low = entry_low * 0.96

    entry_agg = align_price_to_tick(entry_agg)
    tp_agg = align_price_to_tick(tp_agg)
    sl_agg = align_price_to_tick(sl_agg)
    entry_mod = align_price_to_tick(entry_mod)
    tp_mod = align_price_to_tick(tp_mod)
    sl_mod = align_price_to_tick(sl_mod)
    entry_low = align_price_to_tick(entry_low)
    tp_low = align_price_to_tick(tp_low)
    sl_low = align_price_to_tick(sl_low)

    rr_agg = round((tp_agg - entry_agg) / max(1.0, entry_agg - sl_agg), 1)
    rr_mod = round((tp_mod - entry_mod) / max(1.0, entry_mod - sl_mod), 1)
    rr_low = round((tp_low - entry_low) / max(1.0, entry_low - sl_low), 1)

    if "STRONG BUY" in signal:
        alloc_agg, alloc_mod, alloc_low = "10% Port", "15% Port", "20% Port"
    elif "BUY" in signal:
        alloc_agg, alloc_mod, alloc_low = "5% Port", "10% Port", "15% Port"
    else:
        alloc_agg, alloc_mod, alloc_low = "1-2% (Speculative)", "3% Port", "5% Port"

    return {
        "Aggressive": {"entry": entry_agg, "target": tp_agg, "sl": sl_agg, "rr": rr_agg, "size": alloc_agg},
        "Moderate":   {"entry": entry_mod, "target": tp_mod, "sl": sl_mod, "rr": rr_mod, "size": alloc_mod},
        "Low Risk":   {"entry": entry_low, "target": tp_low, "sl": sl_low, "rr": rr_low, "size": alloc_low},
    }


def minify_html(html_str: str) -> str:
    return "".join(line.strip() for line in html_str.split("\n"))


# ─── Trending Scanner ────────────────────────────────────────────────────────

def trending_score(sig: dict) -> float:
    """
    Hitung Trending Score 0–100 dari sinyal intraday IDX.
    Stockbit methodology reconstruction.
    Return 0.0 jika tidak lolos pre-filter.

    sig keys required:
        vsr           : Vol_today / Vol_avg20d
        freq_surge    : Freq_today / Freq_avg20d (IDX endpoint only, 0 if unavail)
        change_pct    : (Last - PrevClose) / PrevClose * 100
        val_surge     : Val_today / Val_avg20d (IDX endpoint only, 0 if unavail)
        net_foreign   : ForeignBuy - ForeignSell (lots)
        freq          : raw frequency count today
        value_rp      : raw transaction value today (Rupiah)

    Weights (Stockbit reconstruction):
        VSR        40%  — volume surge primary signal
        FreqSurge  25%  — frequency surge proxy for social activity
        Change%    20%  — price momentum
        NFR        15%  — net foreign ratio (asing masuk/keluar)
    """
    # Pre-filter (relaxed thresholds)
    if sig.get("vsr", 0) < 1.2:
        return 0.0
    if abs(sig.get("change_pct", 0)) < 0.3:
        return 0.0
    if sig.get("freq", 0) < 50:
        return 0.0
    if sig.get("value_rp", 0) < 25_000_000:
        return 0.0

    def n(val, cap):
        return min(abs(val) / cap, 1.0)

    # NFR = net_foreign / volume_total * 100 — cap at 20%
    volume_total = sig.get("volume_total", 0) or sig.get("freq", 0) * 500 or 1
    raw_nf = sig.get("net_foreign", 0)
    nfr = (raw_nf / volume_total * 100) if volume_total > 0 else 0.0

    score = (
        n(sig.get("vsr", 0),        10) * 0.40 +
        n(sig.get("freq_surge", 0), 10) * 0.25 +
        n(sig.get("change_pct", 0), 10) * 0.20 +
        n(max(nfr, 0),              20) * 0.15
    )
    return round(score * 100, 1)


def trend_tier(score: float) -> str:
    if score >= 65:
        return "Strong Trend 🔥"
    if score >= 45:
        return "Radar ⚡"
    if score >= 25:
        return "Watchlist 👁️"
    return "—"


# ─── BSJP Signals ────────────────────────────────────────────────────────────

def cpr(close: float, high: float, low: float) -> float:
    """Close Position in Range — % posisi close dalam range harian."""
    if high == low:
        return 50.0
    return round((close - low) / (high - low) * 100, 1)


def bsjp_score(sig: dict, ihsg: dict) -> float:
    """
    Hitung BSJP Score 0–100.

    sig keys required:
        cpr                  : Close Position in Range (%)
        change_pct           : ΔP% dari prev close
        vcc                  : Volume Concentration at Close (%)
        net_foreign_lot      : net foreign lots (ForeignBuy - ForeignSell)
        pre_close_momentum   : PCM % (14:30–15:00 window)
        close_vs_vwap        : % close vs VWAP (>0 = above)

    ihsg keys required:
        signal               : "BULLISH" | "NEUTRAL" | "BEARISH"
    """
    # Pre-filter
    if sig.get("cpr", 0) < 50:
        return 0.0
    if abs(sig.get("change_pct", 0)) < 0.3:
        return 0.0
    if ihsg.get("signal") == "BEARISH":
        return 0.0

    def n(val, cap, floor=0.0):
        return min(max((val - floor) / (cap - floor), 0.0), 1.0)

    cpr_norm  = n(sig.get("cpr", 0),                 100, 50)
    vcc_norm  = n(sig.get("vcc", 0),                  50, 15)
    nfc_norm  = n(sig.get("net_foreign_lot", 0), 500_000,  0)
    pcm_norm  = n(sig.get("pre_close_momentum", 0),  2.0,  0)
    vwap_norm = 1.0 if sig.get("close_vs_vwap", 0) > 0 else 0.0

    ihsg_mult = 1.0 if ihsg.get("signal") == "BULLISH" else 0.85

    raw = (
        cpr_norm  * 0.30 +
        vcc_norm  * 0.25 +
        nfc_norm  * 0.20 +
        pcm_norm  * 0.15 +
        vwap_norm * 0.10
    )
    return round(raw * ihsg_mult * 100, 1)


def bsjp_tier(score: float) -> str:
    if score >= 70:
        return "A — Prime BSJP 🌙"
    if score >= 55:
        return "B — Good BSJP ✅"
    if score >= 40:
        return "C — Watchlist 👁️"
    return "X — Skip"


def is_bsjp_entry_valid(sig: dict, score: float) -> dict:
    """
    Cek apakah entry BSJP valid.
    Return dict {valid: bool, checks: dict, score: float}.
    """
    checks = {
        "score_ok":       score >= 40,
        "cpr_ok":         sig.get("cpr", 0) >= 60,
        "vcc_ok":         sig.get("vcc", 0) >= 25,
        "above_vwap":     sig.get("close_vs_vwap", 0) > 0,
        "pcm_positive":   sig.get("pre_close_momentum", 0) > 0,
        "net_foreign_ok": sig.get("net_foreign_lot", 0) >= 0,
    }

    mandatory  = ["score_ok", "cpr_ok", "vcc_ok", "above_vwap"]
    supporting = ["pcm_positive", "net_foreign_ok"]

    mandatory_pass  = all(checks[k] for k in mandatory)
    supporting_pass = sum(1 for k in supporting if checks[k])

    valid = mandatory_pass and supporting_pass >= 1
    return {"valid": valid, "checks": checks, "score": score}


def ihsg_closing_alignment(ihsg_info: dict) -> dict:
    """
    Evaluate IHSG closing alignment dari yfinance info dict.
    ihsg_info: output dari yf.Ticker("^JKSE").info

    Return dict {ihsg_change_pct, ihsg_cpr, bullish, signal}.
    """
    ihsg_chg  = safe_float(ihsg_info.get("regularMarketChangePercent", 0))
    ihsg_last = safe_float(ihsg_info.get("regularMarketPrice", 0))
    ihsg_open = safe_float(ihsg_info.get("regularMarketOpen", ihsg_last)) or ihsg_last
    ihsg_high = safe_float(ihsg_info.get("regularMarketDayHigh", ihsg_last)) or ihsg_last
    ihsg_low  = safe_float(ihsg_info.get("regularMarketDayLow", ihsg_last)) or ihsg_last

    cpr_ihsg = cpr(ihsg_last, ihsg_high, ihsg_low)

    if ihsg_chg > 0.5 and cpr_ihsg >= 60:
        signal = "BULLISH"
    elif abs(ihsg_chg) <= 0.5:
        signal = "NEUTRAL"
    else:
        signal = "BEARISH"

    return {
        "ihsg_change_pct": ihsg_chg,
        "ihsg_cpr":        cpr_ihsg,
        "bullish":         ihsg_chg > 0 and cpr_ihsg >= 50,
        "signal":          signal,
    }
