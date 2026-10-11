import math
from core.config import config
from data.fetchers import safe_float


def compute_intraday_score(data, hist_row, imbalance_ratio=None, tradebook=None) -> dict:
    """Unified intraday score (0-100).

    Weights sum to 1.0:
      flow      0.25  (vol tiers 0.6 + foreign-ratio tiers 0.4)
      orderbook 0.20  (Total Bid Lot / Total Ask Lot)
      trend     0.20  (price vs MA20/MA50/MA200 stack, 52W-high proximity bonus)
      momentum  0.15  (change% tiers, RSI discount)
      hist      0.10  (Score v2 baseline, kept until the future column migration)
      risk      0.10  (neutral 50)

    Optional live overrides (backward-compatible — when both are None the
    weights and behaviour are identical to the legacy call):
      imbalance_ratio  replaces the sheet-derived bid/ask ratio.
      tradebook        (tradebook_profile dict) splits the orderbook slot into
                       orderbook 0.10 + trade_flow 0.10, where trade_flow is
                       derived from big-money trend / net-flow momentum and is
                       capped at 40 when big-money selling is dominant.

    Hard caps (most restrictive wins, each adds a warning):
      0 < ARA_Dist_Pct <= ARA_PROXIMITY_WARNING_PCT -> cap 55
      UMA set               -> cap 40
      Corp Action set       -> cap 60
    """
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

    flow_score = round(vol_score * 0.6 + imbalance_score * 0.4, 1)

    last = safe_float(data.get("last", 0))

    # ── Orderbook imbalance (sheet columns the sync daemon already writes) ──
    total_bid = safe_float(hist_row.get("Total Bid Lot", 0)) or safe_float(data.get("total_bid_lot", 0))
    total_ask = safe_float(hist_row.get("Total Ask Lot", 0)) or safe_float(data.get("total_ask_lot", 0))
    ob_ratio = (total_bid / total_ask) if total_ask > 0 else 0.0
    if imbalance_ratio is not None:
        ob_ratio = safe_float(imbalance_ratio)
    if ob_ratio >= 2.5:
        orderbook_score = 100
    elif ob_ratio >= 1.5:
        orderbook_score = 75
    elif ob_ratio >= 0.8:
        orderbook_score = 50
    else:
        orderbook_score = 20

    # ── Trade-flow slot (only when a tradebook profile is supplied) ──
    trade_flow_score = None
    if tradebook:
        bm_trend = tradebook.get("big_money_trend", "neutral")
        base = {"accumulating": 80.0, "neutral": 55.0, "distributing": 30.0}.get(
            bm_trend, 55.0
        )
        net_pos = safe_float(tradebook.get("net_positive_ratio", 0.0))
        momentum = tradebook.get("momentum", "neutral")
        trade_flow_score = base + 20.0 * net_pos
        if momentum == "accelerating":
            trade_flow_score += 10.0
        elif momentum == "decelerating":
            trade_flow_score -= 10.0
        if safe_float(tradebook.get("big_money_sell_pct", 0.0)) >= config.BIG_MONEY_DOMINANCE_PCT:
            trade_flow_score = min(trade_flow_score, 40.0)
        trade_flow_score = max(0.0, min(100.0, trade_flow_score))

    # ── Trend alignment vs MA stack ──
    ma20 = safe_float(hist_row.get("MA20", 0))
    ma50 = safe_float(hist_row.get("MA50", 0))
    ma200 = safe_float(hist_row.get("MA200", 0))
    if ma20 <= 0:
        trend_score = 20
    elif last > ma20:
        if ma50 <= 0:
            trend_score = 40
        elif ma20 > ma50:
            if ma200 <= 0:
                trend_score = 70
            elif ma50 > ma200:
                trend_score = 100
            else:
                trend_score = 70
        else:
            trend_score = 40
    else:
        trend_score = 20

    dist_raw = hist_row.get("Dist to 52W High")
    if dist_raw not in (None, ""):
        dist_52w = safe_float(dist_raw)
        if -10 <= dist_52w <= 0:
            trend_score = min(100, trend_score + 10)

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

    # ── Momentum with RSI discount ──
    rsi = safe_float(hist_row.get("RSI14", 0))
    if rsi >= 75:
        price_score = round(price_score * 0.5)
    elif rsi >= 70:
        price_score = round(price_score * 0.75)
    momentum_score = price_score

    hist_score = safe_float(hist_row.get("Score v2", 50))
    risk_score = 50.0  # neutral risk slot

    if trade_flow_score is not None:
        total = round(
            flow_score * 0.25 +
            orderbook_score * 0.10 +
            trade_flow_score * 0.10 +
            trend_score * 0.20 +
            momentum_score * 0.15 +
            hist_score * 0.10 +
            risk_score * 0.10,
            1,
        )
    else:
        total = round(
            flow_score * 0.25 +
            orderbook_score * 0.20 +
            trend_score * 0.20 +
            momentum_score * 0.15 +
            hist_score * 0.10 +
            risk_score * 0.10,
            1,
        )

    # ── Hard caps ──
    warnings = []
    cap = 101
    ara_raw = hist_row.get("ARA_Dist_Pct")
    if ara_raw not in (None, ""):
        ara_dist = safe_float(ara_raw)
        if 0 < ara_dist <= config.ARA_PROXIMITY_WARNING_PCT:
            cap = min(cap, 55)
            warnings.append(
                f"Near ARA (ARA_Dist_Pct ≤ {config.ARA_PROXIMITY_WARNING_PCT:.0f}%) — cap 55"
            )
    uma_raw = str(hist_row.get("UMA", "") or "").strip()
    if uma_raw and uma_raw.lower() not in ("no", "none", "-", "n/a", "0"):
        cap = min(cap, 40)
        warnings.append("UMA flag set — cap 40")
    corp_raw = str(hist_row.get("Corp Action", "") or "").strip()
    if corp_raw and corp_raw.lower() not in ("no", "none", "-", "n/a", "0"):
        cap = min(cap, 60)
        warnings.append("Corporate Action flag set — cap 60")
    if cap <= 100:
        total = min(total, float(cap))

    total = int(round(total))

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

    result = {
        "score": total,
        "signal": sig,
        "tier": sig,
        "color": col,
        "vol_spike": vol_spike,
        "change_pct": chg,
        "warnings": warnings,
        "breakdown": {
            "flow": flow_score,
            "orderbook": orderbook_score,
            "trend": trend_score,
            "momentum": momentum_score,
            "hist": hist_score,
            "risk": risk_score,
            "Volume Spike": vol_score,
            "Price Intraday Change": price_score,
            "Historical Score Weight": hist_score,
        }
    }
    if trade_flow_score is not None:
        result["breakdown"]["trade_flow"] = trade_flow_score
    return result


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


def sl_tp_levels(price: float, hist_row: dict) -> dict:
    """Stop-loss / take-profit levels (Tab 2 logic).

    SL: SL_Practical, else max(MA20*0.97, price*0.93), floored at price*0.93.
    TP: 52W High, else price*1.15, capped at price*1.15.
    """
    sl_prac = safe_float(hist_row.get("SL_Practical"))
    ma20 = safe_float(hist_row.get("MA20"))
    sl = sl_prac if sl_prac > 0 else round(max(ma20 * 0.97, price * 0.93), 2)
    if sl >= price:
        sl = round(price * 0.93, 2)
    high52 = safe_float(hist_row.get("52W High"))
    tp = round(min(high52, price * 1.15), 2) if high52 > 0 else round(price * 1.15, 2)
    return {"sl": sl, "tp": tp}


def position_size_lots(entry: float, sl: float, base_portfolio: float,
                       allocation_pct: float = 0.10,
                       risk_budget: float = 0.01) -> int:
    """Risk-first position sizing (lifted from Tab 7).

    Lots_risk = (base * risk_budget) / ((entry - sl) * 100)
    Lots_cap  = (base * allocation_pct) / (entry * 100)
    Lots      = min(Lots_risk, Lots_cap)

    Risk-first means the risk budget is a *hard ceiling*: when a single lot
    already risks more than `base * risk_budget` (i.e. Lots_risk == 0), the
    correct size is 0, not the allocation cap. The previous implementation
    returned `lots_cap` in that branch, which silently exceeded the 1% risk
    budget — a risk-control hole (audit fix).
    """
    if entry <= 0 or base_portfolio <= 0:
        return 0
    risk_per_share = entry - sl
    lots_risk = int((base_portfolio * risk_budget) / (risk_per_share * 100)) if risk_per_share > 0 else 0
    lots_cap = int((base_portfolio * allocation_pct) / (entry * 100)) if entry > 0 else 0
    return min(lots_risk, lots_cap)


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
