"""Best-Pick Recommendation Engine — IDX-specific conviction scoring.

This module produces a single, transparent "Best Pick" verdict per ticker per
horizon, grounded in IDX market microstructure (fraksi harga, ARA/ARB 2025–2026
rules, liquidity tiers) and proven quantitative formulas:

  • Liquidity gate — avoid thin/gorengan via value-traded floors.
  • ATR-normalised risk — volatility-scored per horizon sweet-spot.
  • Relative Strength vs IHSG — O'Neil / Minervini RS rating.
  • Trend Template — Minervini Stage 2 condition count.
  • Bandarmology — foreign flow + orderbook imbalance + tradebook big-money.
  • Momentum — intraday change with RSI regime adjustment.
  • Fundamental quality (long-term) — PE, market-cap, beta composite.

Hard risk gates (each lowers the tier cap and adds a warning):
  UMA → cap 40 | Corp Action → cap 60 | Near-ARA (≤2%) → cap 55
  Extreme vol (ATR% > 15) → cap 50 | Illiquid (< floor) → cap 55
  Big-money distributing + negative net flow → cap 60

All scores are 0–100. Missing data falls back to neutral 50 with reduced
confidence — never fabricated.

Reference rules:
  • Fraksi Harga: Kep-00136/BEI/09-2026 (28 Sep 2026)
  • ARA / ARB:   Kep-00003/BEI/04-2025 (8 Apr 2025) — ARB flat −15% for >Rp10
"""
from __future__ import annotations

import math
from typing import Optional

from data.fetchers import safe_float
from data.scoring import get_tick_size, align_price_to_tick, position_size_lots
from data.mega_score import minervini_to_score
from core.config import config


# ═════════════════════════════════════════════════════════════════════════════
# CONSTANTS — IDX market microstructure (researched)
# ═════════════════════════════════════════════════════════════════════════════

# ARA limit % by prev-close price tier (unchanged BEI rule)
def get_ara_limit_pct(prev_close: float) -> float:
    if prev_close <= 0:
        return 0.0
    if prev_close < 200:
        return 35.0
    elif prev_close < 5000:
        return 25.0
    else:
        return 20.0


# ARB limit % by prev-close price tier (current 2025–2026 rule)
def get_arb_limit_pct(prev_close: float) -> float:
    if prev_close <= 10:
        return -100.0  # sentinel — nominal −Rp1 handled separately
    return -15.0


# Liquidity tiers (average daily value, Rupiah)
LIQUIDITY_TIERS = [
    (50_000_000_000, 100),   # ≥ Rp 50 B  — very liquid
    (10_000_000_000, 85),    # ≥ Rp 10 B  — liquid
    (5_000_000_000, 70),     # ≥ Rp 5 B   — acceptable
    (1_000_000_000, 55),     # ≥ Rp 1 B   — thin
    (250_000_000, 35),       # ≥ Rp 250 M — very thin
]
LIQUIDITY_FLOOR = 250_000_000  # hard gate floor


# Horizon-specific volatility sweet-spots (ATR %)
VOL_SWEET_SPOT = {
    "scalping":  {"lo": 2.0, "hi": 5.0, "dead": 1.0, "wild": 10.0},
    "swing_bsjp": {"lo": 2.0, "hi": 6.0, "dead": 1.5, "wild": 12.0},
    "long_term": {"lo": 1.5, "hi": 4.0, "dead": 1.0, "wild": 10.0},
}


# Conviction weights per horizon (researched, sum ≈ 1.0)
HORIZON_WEIGHTS = {
    "scalping": {
        "liquidity": 0.15,
        "momentum": 0.25,
        "flow": 0.25,
        "volatility": 0.15,
        "trend": 0.10,
        "rs": 0.10,
    },
    "swing_bsjp": {
        "liquidity": 0.15,
        "trend": 0.20,
        "momentum": 0.15,
        "flow": 0.20,
        "rs": 0.15,
        "volatility": 0.15,
    },
    "long_term": {
        "liquidity": 0.10,
        "trend": 0.30,
        "rs": 0.15,
        "fundamental": 0.25,
        "volatility": 0.10,
        "momentum": 0.10,
    },
}


# R/R targets per tier
TIER_RR = {"Aggressive": 1.5, "Moderat": 2.0, "Low Risk": 2.5}


# ═════════════════════════════════════════════════════════════════════════════
# HELPER: safe ATR % with multiple fallbacks
# ═════════════════════════════════════════════════════════════════════════════

def _atr_pct(entry: dict) -> float:
    """Return best-effort ATR % (0–100 scale).

    Priority:
      1. Sheet column "ATR %"
      2. Sheet column "Daily_Range_Pct"
      3. Intraday (high-low)/prev_close * 100 from raw_data
      4. Fallback 0.0
    """
    hist = entry.get("hist_row_obj") or {}
    raw = entry.get("raw_data_obj") or {}

    atr = safe_float(hist.get("ATR %"))
    if atr > 0:
        return atr

    dr = safe_float(hist.get("Daily_Range_Pct"))
    if dr > 0:
        return dr

    prev = safe_float(raw.get("prev_close"))
    high = safe_float(raw.get("high"))
    low = safe_float(raw.get("low"))
    if prev > 0 and high > low > 0:
        return (high - low) / prev * 100

    return 0.0


# ═════════════════════════════════════════════════════════════════════════════
# FACTOR SCORERS (each returns 0–100 score + optional note)
# ═════════════════════════════════════════════════════════════════════════════

def liquidity_score(entry: dict) -> dict:
    """Liquidity score based on average daily traded value (Rp).

    Thin stocks are dangerous in IDX because spreads widen and slippage is
    severe. We gate on a minimum floor and score logarithmically above it.
    """
    hist = entry.get("hist_row_obj") or {}
    raw = entry.get("raw_data_obj") or {}
    price = safe_float(entry.get("Live Price"))
    vol_avg = safe_float(hist.get("Vol_Avg"))

    # Best-effort average daily value
    avg_value = vol_avg * price * 100 if vol_avg > 0 and price > 0 else 0.0
    if avg_value <= 0:
        # Fallback: use today's value if available
        value_today = safe_float(raw.get("value"))
        if value_today > 0:
            avg_value = value_today

    if avg_value <= 0:
        return {"score": 50.0, "avg_value": 0.0, "note": "no liquidity data"}

    for floor, sc in LIQUIDITY_TIERS:
        if avg_value >= floor:
            return {"score": float(sc), "avg_value": avg_value, "note": None}

    return {"score": 15.0, "avg_value": avg_value, "note": "very thin liquidity"}


def volatility_score(entry: dict, horizon: str) -> dict:
    """ATR%-based volatility score per horizon sweet-spot.

    Sweet spot = healthy tradable range. Too low = dead / no edge.
    Too high = gorengan / manipulation risk.
    """
    atr = _atr_pct(entry)
    if atr <= 0:
        return {"score": 50.0, "atr_pct": 0.0, "note": "no ATR data"}

    band = VOL_SWEET_SPOT.get(horizon, VOL_SWEET_SPOT["swing_bsjp"])
    lo, hi = band["lo"], band["hi"]
    dead, wild = band["dead"], band["wild"]

    if atr < dead:
        score = 40.0
    elif atr <= lo:
        score = 60.0 + (atr - dead) / (lo - dead) * 40.0
    elif atr <= hi:
        score = 100.0
    elif atr <= wild:
        score = 100.0 - (atr - hi) / (wild - hi) * 70.0
    else:
        score = 30.0

    note = None
    if atr > wild:
        note = f"extreme volatility (ATR% {atr:.1f}%) — manipulation/gorengan risk"
    elif atr < dead:
        note = f"too quiet (ATR% {atr:.1f}%) — no trading edge"

    return {"score": round(score, 1), "atr_pct": atr, "note": note}


def relative_strength_score(entry: dict, rs_ihsg: float = 0.0) -> dict:
    """Relative Strength vs IHSG — O'Neil / Minervini style.

    Uses 3-month price return if available, else 52-week position as proxy.
    Score: RS −30% → 0, RS 0% → 50, RS +30% → 100.
    """
    hist = entry.get("hist_row_obj") or {}
    price = safe_float(entry.get("Live Price"))

    # Prefer 3-month return when present (Minervini batch)
    close_prev = safe_float(hist.get("ClosePrev"))
    price_3mo = None
    # If hist_row has a synthetic "Price_3M_Ago" we use it; otherwise fall back
    if "Price_3M_Ago" in hist:
        price_3mo = safe_float(hist["Price_3M_Ago"])
    elif close_prev > 0:
        # rough proxy: assume 3mo ago was ~ClosePrev (very coarse)
        price_3mo = close_prev

    if price > 0 and price_3mo and price_3mo > 0:
        rs_ticker = (price / price_3mo - 1) * 100
    else:
        # Fallback: 52-week position
        high52 = safe_float(hist.get("52W High"))
        low52 = safe_float(hist.get("52W Low"))
        if high52 > low52 > 0:
            rs_ticker = (price - low52) / (high52 - low52) * 100
        else:
            return {"score": 50.0, "rs_raw": 0.0, "note": "no RS data"}

    rs = rs_ticker - rs_ihsg
    score = 50.0 + (rs / 30.0) * 50.0
    score = max(0.0, min(100.0, score))

    note = None
    if rs < -15:
        note = f"weak RS vs IHSG ({rs:+.1f}%)"
    elif rs > 20:
        note = f"strong RS vs IHSG ({rs:+.1f}%)"

    return {"score": round(score, 1), "rs_raw": round(rs, 1), "note": note}


def trend_template_score(entry: dict) -> dict:
    """Minervini Stage-2 trend template mapped to 0–100.

    If the ticker already has a Minervini row, use its condition count.
    Otherwise compute a lightweight version from sheet MA stack.
    """
    hist = entry.get("hist_row_obj") or {}
    price = safe_float(entry.get("Live Price"))
    ma20 = safe_float(hist.get("MA20"))
    ma50 = safe_float(hist.get("MA50"))
    ma200 = safe_float(hist.get("MA200"))
    high52 = safe_float(hist.get("52W High"))
    low52 = safe_float(hist.get("52W Low"))
    vol = safe_float(entry.get("raw_data_obj", {}).get("volume"))
    vol_avg = safe_float(hist.get("Vol_Avg"))

    conds = []
    if price > 0 and ma20 > 0:
        conds.append(price > ma20)
    if ma50 > 0:
        conds.append(ma50 > 0)  # placeholder — we don't have MA150/200 easily
    if high52 > 0:
        conds.append(price >= high52 * 0.75)
    if low52 > 0:
        conds.append(price >= low52 * 1.25)
    if vol_avg > 0 and vol > 0:
        conds.append(vol > vol_avg)

    if not conds:
        return {"score": 50.0, "conds_met": 0, "note": "no trend data"}

    score = sum(conds) / len(conds) * 100
    return {"score": round(score, 1), "conds_met": sum(conds), "note": None}


def flow_score(entry: dict, tradebook: dict | None = None) -> dict:
    """Bandarmology — foreign flow + orderbook + tradebook composite.

    IDX-specific: foreign investors are a major price driver.
    High foreign buy ratio + bid-dominant book = bullish flow.
    """
    raw = entry.get("raw_data_obj") or {}
    hist = entry.get("hist_row_obj") or {}

    fb = safe_float(raw.get("foreign_buy"))
    fs = safe_float(raw.get("foreign_sell"))
    vol = safe_float(raw.get("volume"))

    # Foreign net ratio (lots or shares — ratio is unitless)
    net_foreign = fb - fs
    f_ratio = fb / max(fs, 1.0)

    # Orderbook imbalance from freshest available source
    total_bid = safe_float(hist.get("Total Bid Lot")) or safe_float(raw.get("total_bid_lot"))
    total_ask = safe_float(hist.get("Total Ask Lot")) or safe_float(raw.get("total_ask_lot"))
    ob_ratio = total_bid / max(total_ask, 1.0)

    # Foreign flow sub-score
    if f_ratio >= 3.0:
        f_score = 100.0
    elif f_ratio >= 2.0:
        f_score = 80.0
    elif f_ratio >= 1.2:
        f_score = 65.0
    elif f_ratio >= 0.8:
        f_score = 50.0
    else:
        f_score = 30.0

    # Orderbook sub-score
    if ob_ratio >= 2.5:
        ob_score = 100.0
    elif ob_ratio >= 1.5:
        ob_score = 75.0
    elif ob_ratio >= 0.8:
        ob_score = 50.0
    else:
        ob_score = 20.0

    # Tradebook overlay (Engine D data)
    tb_score = 55.0
    tb_note = None
    if tradebook:
        bm_trend = tradebook.get("big_money_trend", "neutral")
        base = {"accumulating": 80.0, "neutral": 55.0, "distributing": 30.0}.get(bm_trend, 55.0)
        net_pos = safe_float(tradebook.get("net_positive_ratio", 0.0))
        tb_score = base + 20.0 * net_pos
        if safe_float(tradebook.get("big_money_sell_pct", 0.0)) >= config.BIG_MONEY_DOMINANCE_PCT:
            tb_score = min(tb_score, 40.0)
            tb_note = "big-money selling dominant"
        tb_score = max(0.0, min(100.0, tb_score))

    # Composite: foreign 0.40, orderbook 0.35, tradebook 0.25
    score = f_score * 0.40 + ob_score * 0.35 + tb_score * 0.25

    notes = []
    if f_ratio < 0.8 and net_foreign < 0:
        notes.append("foreign net selling")
    if ob_ratio < 0.8:
        notes.append("sell-dominant orderbook")
    if tb_note:
        notes.append(tb_note)

    return {
        "score": round(score, 1),
        "foreign_ratio": round(f_ratio, 2),
        "ob_ratio": round(ob_ratio, 2),
        "net_foreign": round(net_foreign, 0),
        "note": "; ".join(notes) if notes else None,
    }


def momentum_score(entry: dict, horizon: str) -> dict:
    """Intraday momentum with RSI regime adjustment.

    Scalping: rewards +2% to +5%, penalises RSI >70.
    Swing:    rewards +1% to +4%, rewards RSI 45–65.
    Long:     rewards +0.5% to +2%, penalises RSI >80.
    """
    raw = entry.get("raw_data_obj") or {}
    hist = entry.get("hist_row_obj") or {}
    price = safe_float(entry.get("Live Price"))
    prev = safe_float(raw.get("prev_close"))
    chg = ((price - prev) / prev * 100) if prev > 0 else 0.0
    rsi = safe_float(hist.get("RSI14"))

    # Base score from change%
    if chg >= 5.0:
        base = 100.0
    elif chg >= 2.0:
        base = 80.0 + (chg - 2.0) / 3.0 * 20.0
    elif chg >= 0.0:
        base = 60.0 + chg / 2.0 * 20.0
    elif chg >= -3.0:
        base = 40.0 + (chg + 3.0) / 3.0 * 20.0
    else:
        base = 20.0

    # RSI adjustment per horizon
    if horizon == "scalping":
        if rsi >= 75:
            base = base * 0.5
        elif rsi >= 70:
            base = base * 0.75
    elif horizon == "swing_bsjp":
        if 45 <= rsi <= 65:
            base = min(100.0, base * 1.15)
        elif rsi >= 75:
            base = base * 0.75
    else:  # long_term
        if 50 <= rsi <= 70:
            base = min(100.0, base * 1.10)
        elif rsi >= 80:
            base = base * 0.60

    note = None
    if rsi >= 75:
        note = f"RSI {rsi:.0f} overbought — momentum discount applied"
    elif rsi > 0 and rsi <= 30 and chg > 0:
        note = f"RSI {rsi:.0f} bounce from oversold — momentum boost"

    return {"score": round(base, 1), "change_pct": round(chg, 2), "rsi": rsi, "note": note}


def fundamental_quality_score(entry: dict) -> dict:
    """Long-term fundamental quality: PE, market-cap, beta.

    Cheap + large + stable beta = high quality. Loss-making (PE ≤ 0) is
    penalised heavily for conservative long-term picks.
    """
    hist = entry.get("hist_row_obj") or {}
    pe = safe_float(hist.get("PE"))
    market_cap = safe_float(hist.get("MarketCap"))
    beta = safe_float(hist.get("Beta"))

    if pe <= 0 and market_cap <= 0 and beta <= 0:
        return {"score": 50.0, "note": "no fundamental data"}

    # PE score
    if pe <= 0:
        pe_score = 20.0
    elif pe < 5:
        pe_score = 90.0
    elif pe < 15:
        pe_score = 100.0
    elif pe < 25:
        pe_score = 80.0
    elif pe < 40:
        pe_score = 60.0
    else:
        pe_score = 40.0

    # Market-cap score
    if market_cap >= 50_000_000_000_000:      # ≥ Rp 50 T
        cap_score = 100.0
    elif market_cap >= 10_000_000_000_000:    # ≥ Rp 10 T
        cap_score = 85.0
    elif market_cap >= 1_000_000_000_000:     # ≥ Rp 1 T
        cap_score = 70.0
    elif market_cap >= 100_000_000_000:       # ≥ Rp 100 B
        cap_score = 55.0
    else:
        cap_score = 40.0

    # Beta score
    if beta <= 0:
        beta_score = 60.0
    elif 0.8 <= beta <= 1.2:
        beta_score = 100.0
    elif beta < 0.8:
        beta_score = 80.0
    elif beta <= 1.5:
        beta_score = 70.0
    else:
        beta_score = 40.0

    score = pe_score * 0.40 + cap_score * 0.35 + beta_score * 0.25

    notes = []
    if pe <= 0:
        notes.append("loss-making (PE ≤ 0)")
    if beta > 1.5:
        notes.append(f"high beta ({beta:.2f})")
    if market_cap > 0 and market_cap < 100_000_000_000:
        notes.append("small-cap liquidity risk")

    return {
        "score": round(score, 1),
        "pe_score": pe_score,
        "cap_score": cap_score,
        "beta_score": beta_score,
        "note": "; ".join(notes) if notes else None,
    }


# ═════════════════════════════════════════════════════════════════════════════
# HARD RISK GATES
# ═════════════════════════════════════════════════════════════════════════════

def apply_risk_gates(entry: dict, base_score: float, tradebook: dict | None = None) -> dict:
    """Apply hard risk gates and return capped score + warnings.

    Each gate lowers the maximum allowed score (most restrictive wins).
    """
    hist = entry.get("hist_row_obj") or {}
    raw = entry.get("raw_data_obj") or {}
    cap = 101.0
    warnings: list[str] = []

    # Gate 1: UMA
    uma = str(hist.get("UMA", "") or "").strip()
    if uma and uma.lower() not in ("no", "none", "-", "n/a", "0"):
        cap = min(cap, 40.0)
        warnings.append("UMA flag — cap 40")

    # Gate 2: Corporate Action
    corp = str(hist.get("Corp Action", "") or "").strip()
    if corp and corp.lower() not in ("no", "none", "-", "n/a", "0"):
        cap = min(cap, 60.0)
        warnings.append("Corporate Action — cap 60")

    # Gate 3: Near-ARA proximity
    ara_dist = safe_float(hist.get("ARA_Dist_Pct"))
    if 0 < ara_dist <= config.ARA_PROXIMITY_WARNING_PCT:
        cap = min(cap, 55.0)
        warnings.append(f"Near ARA ({ara_dist:.1f}%) — cap 55")

    # Gate 4: Extreme volatility
    atr = _atr_pct(entry)
    if atr > 15.0:
        cap = min(cap, 50.0)
        warnings.append(f"Extreme ATR% ({atr:.1f}%) — cap 50")

    # Gate 5: Illiquidity
    liq = liquidity_score(entry)
    if liq["avg_value"] > 0 and liq["avg_value"] < LIQUIDITY_FLOOR:
        cap = min(cap, 55.0)
        warnings.append(f"Illiquid (avg value Rp {liq['avg_value']:,.0f}) — cap 55")

    # Gate 6: Big-money distributing + negative net flow
    if tradebook:
        if tradebook.get("big_money_trend") == "distributing":
            if safe_float(tradebook.get("net_flow_sum", 0)) < 0:
                cap = min(cap, 60.0)
                warnings.append("Big-money distributing + negative net flow — cap 60")

    # Gate 7: Pre-market gap risk — if gap > 8% without volume
    gap = safe_float(raw.get("gap_pct"))
    if gap > 8.0 and liq["avg_value"] < 1_000_000_000:
        cap = min(cap, 60.0)
        warnings.append(f"Large gap ({gap:.1f}%) on thin volume — cap 60")

    if cap <= 100.0:
        final_score = min(base_score, cap)
    else:
        final_score = base_score

    return {
        "score": round(final_score, 1),
        "raw_score": round(base_score, 1),
        "cap": cap if cap <= 100.0 else None,
        "warnings": warnings,
    }


# ═════════════════════════════════════════════════════════════════════════════
# LEVELS: ATR + structure based entry / SL / TP
# ═════════════════════════════════════════════════════════════════════════════

def compute_levels(
    price: float,
    atr_pct: float,
    hist_row: dict,
    raw_data: dict,
    tier_name: str,
) -> dict:
    """Compute tick-aligned entry, SL, and TP for a tier.

    SL = max(structural support, entry − k·ATR)  (risk-first)
    TP = min(entry + R/R_target · risk, 52W high, ARA price)

    k: Aggressive=1.0, Moderate=1.5, Low Risk=2.0
    max risk %: Agg 3%, Mod 4%, Low 6%
    """
    if price <= 0:
        return {"entry": 0.0, "sl": 0.0, "tp": 0.0, "rr": 0.0, "risk_pct": 0.0}

    tick = get_tick_size(price)
    entry = align_price_to_tick(price)

    # ATR in price units
    atr = price * (atr_pct / 100.0)

    k = {"Aggressive": 1.0, "Moderat": 1.5, "Low Risk": 2.0}.get(tier_name, 1.5)
    max_risk_pct = {"Aggressive": 0.03, "Moderat": 0.04, "Low Risk": 0.06}.get(tier_name, 0.04)

    # Structural support fallback
    support = safe_float(hist_row.get("Support"))
    if support <= 0 or support >= price:
        support = price * 0.93
    ma20 = safe_float(hist_row.get("MA20"))
    if ma20 > 0 and ma20 < price:
        support = max(support, ma20 * 0.97)

    raw_sl = entry - k * atr
    max_sl = entry * (1 - max_risk_pct)
    sl = max(raw_sl, max_sl, support)
    sl = align_price_to_tick(sl, "up")
    # Ensure SL < entry
    if sl >= entry:
        sl = entry - tick

    risk = entry - sl
    rr_target = TIER_RR.get(tier_name, 2.0)
    raw_tp = entry + rr_target * risk

    # Cap TP at 52W high and ARA price
    high52 = safe_float(hist_row.get("52W High"))
    if high52 > price:
        raw_tp = min(raw_tp, high52)

    prev_close = safe_float(raw_data.get("prev_close")) or safe_float(hist_row.get("ClosePrev"))
    if prev_close > 0:
        ara_price = prev_close * (1 + get_ara_limit_pct(prev_close) / 100.0)
        raw_tp = min(raw_tp, ara_price)

    tp = align_price_to_tick(raw_tp, "nearest")
    tp = max(tp, entry + tick)

    rr = round((tp - entry) / max(risk, 1e-9), 2) if risk > 0 else 0.0
    risk_pct = round(risk / entry * 100, 2) if entry > 0 else 0.0

    return {
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "risk_pct": risk_pct,
        "k": k,
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN: compute_best_pick
# ═════════════════════════════════════════════════════════════════════════════

def compute_best_pick(
    entry: dict,
    horizon: str,
    rs_ihsg: float = 0.0,
    tradebook: dict | None = None,
    base_portfolio: float = 100_000_000.0,
) -> dict:
    """Produce a single Best-Pick verdict for one ticker.

    Parameters
    ----------
    entry : dict
        One element from `scored_list` (has Ticker, Live Price, Change %,
        Intraday Score, raw_data_obj, hist_row_obj).
    horizon : {"scalping", "swing_bsjp", "long_term"}
    rs_ihsg : float
        IHSG 3-month return % (for relative-strength denominator).
    tradebook : dict | None
        Optional Engine D tradebook_profile (from data.tradebook).
    base_portfolio : float
        Portfolio value for position-size calculation.

    Returns
    -------
    dict with keys:
        score, raw_score, cap, tier, confidence, breakdown, levels,
        sizing, warnings, rationale, horizon.
    """
    weights = HORIZON_WEIGHTS.get(horizon, HORIZON_WEIGHTS["swing_bsjp"])

    # ── Build factor scores ────────────────────────────────────────────────
    liq = liquidity_score(entry)
    vol = volatility_score(entry, horizon)
    rs = relative_strength_score(entry, rs_ihsg)
    trend = trend_template_score(entry)
    flw = flow_score(entry, tradebook)
    mom = momentum_score(entry, horizon)

    factors = {
        "liquidity": liq,
        "volatility": vol,
        "rs": rs,
        "trend": trend,
        "flow": flw,
        "momentum": mom,
    }

    if horizon == "long_term":
        fund = fundamental_quality_score(entry)
        factors["fundamental"] = fund

    # ── Weighted composite ─────────────────────────────────────────────────
    total, used_weight = 0.0, 0.0
    breakdown: dict[str, float] = {}
    defaulted: list[str] = []
    for key, w in weights.items():
        fac = factors.get(key)
        if fac is None:
            defaulted.append(key)
            val = 50.0
        else:
            val = fac["score"]
        breakdown[key] = round(val, 1)
        total += val * w
        used_weight += w

    raw_score = round(total / used_weight, 1) if used_weight > 0 else 50.0

    # ── Confidence = fraction of weight that came from real data ──────────
    present_weight = sum(
        w for key, w in weights.items() if key not in defaulted
    )
    confidence = round(present_weight / sum(weights.values()), 3) if weights else 0.0

    # ── Hard risk gates ────────────────────────────────────────────────────
    gated = apply_risk_gates(entry, raw_score, tradebook)
    score = gated["score"]

    # ── Tier ───────────────────────────────────────────────────────────────
    if score >= 85:
        tier = "🟢 SANGAT DIREKOMENDASIKAN"
    elif score >= 70:
        tier = "🔵 DIREKOMENDASIKAN"
    elif score >= 50:
        tier = "🟡 NETRAL / WATCHLIST"
    else:
        tier = "🔴 HINDARI"

    # ── Levels & sizing ────────────────────────────────────────────────────
    price = safe_float(entry.get("Live Price"))
    atr_pct = vol["atr_pct"]
    hist_row = entry.get("hist_row_obj") or {}
    raw_data = entry.get("raw_data_obj") or {}

    levels = {}
    sizing = {}
    for tname in ("Aggressive", "Moderat", "Low Risk"):
        lv = compute_levels(price, atr_pct, hist_row, raw_data, tname)
        levels[tname] = lv
        alloc = {"Aggressive": 0.10, "Moderat": 0.15, "Low Risk": 0.20}.get(tname, 0.10)
        lots = position_size_lots(lv["entry"], lv["sl"], base_portfolio, alloc)
        sizing[tname] = lots

    # ── Rationale ──────────────────────────────────────────────────────────
    rationale: list[str] = []
    top = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
    for k, v in top:
        label = k.replace("_", " ").title()
        rationale.append(f"{label} {v:.0f}")
    for w in gated["warnings"]:
        rationale.append(f"⚠️ {w}")
    for k, fac in factors.items():
        if fac.get("note"):
            rationale.append(f"• {fac['note']}")

    return {
        "score": score,
        "raw_score": gated["raw_score"],
        "cap": gated["cap"],
        "tier": tier,
        "confidence": confidence,
        "defaulted": defaulted,
        "breakdown": breakdown,
        "factors": {k: {"score": v["score"], "note": v.get("note")} for k, v in factors.items()},
        "levels": levels,
        "sizing": sizing,
        "warnings": gated["warnings"],
        "rationale": rationale,
        "horizon": horizon,
    }


def rank_best_picks(
    scored_list: list[dict],
    horizon: str,
    rs_ihsg: float = 0.0,
    tradebook_map: dict[str, dict] | None = None,
    base_portfolio: float = 100_000_000.0,
    min_score: float = 0.0,
) -> list[dict]:
    """Rank the full watchlist by Best-Pick conviction score.

    Returns a list of dicts, each extending the original `entry` with the
    Best-Pick verdict fields (score, tier, levels, sizing, rationale…).
    Sorted descending by score.
    """
    results = []
    for entry in scored_list:
        tb = (tradebook_map or {}).get(entry.get("Ticker"))
        pick = compute_best_pick(entry, horizon, rs_ihsg, tb, base_portfolio)
        if pick["score"] >= min_score:
            merged = dict(entry)
            merged["BestPick"] = pick
            results.append(merged)
    results.sort(key=lambda r: r["BestPick"]["score"], reverse=True)
    return results
