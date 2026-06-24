"""
Wall Detection & Multi-Snapshot Delta Tracking Engine.
Mengimplementasikan metodologi orderbook: wall detection, delta
tracking, dan dual-engine three-tier entry (Aggressive/Moderat/Low Risk)
grounded di support/resistance riil, bukan persentase arbitrary.

Engine A — Wall Gravity: Pure structural wall scoring
Engine B — Contextual Alpha: Sentiment × Round Number × Depth Adaptation
"""
from dataclasses import dataclass, field
from statistics import mean, median
from typing import List, Optional
import math


# ═════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class OrderbookLevel:
    price: float
    lot: int
    freq: int = 0

@dataclass
class WallSignal:
    price: float
    lot: int
    side: str             # "bid" | "ask"
    strength: float        # 0-100
    classification: str    # "Building" | "Pulled" | "Eaten" | "Static" | "New"

@dataclass
class WallScore:
    """Scored bid/ask wall with composite weighting."""
    price: float
    lot: int
    freq: int
    score: float
    lot_weight: float
    proximity_weight: float
    freq_weight: float
    round_bonus: float = 1.0            # Engine B only
    sentiment_adjusted: float = 0.0     # Engine B only


# ═════════════════════════════════════════════════════════════════════════════
# WALL DETECTION & DELTA TRACKING (Unchanged)
# ═════════════════════════════════════════════════════════════════════════════

def detect_walls(levels: list[OrderbookLevel], side: str, k: float = 1.5) -> list[WallSignal]:
    """Flag level dengan lot volume jauh di atas rata-rata book."""
    if not levels:
        return []
    lots = [lv.lot for lv in levels]
    avg_lot = mean(lots)
    med_lot = median(lots)
    threshold = max(avg_lot + k * (max(lots) - avg_lot) * 0.3, med_lot * 3)

    walls = []
    for lv in levels:
        if lv.lot >= threshold and lv.lot > 0:
            strength = min(100.0, round((lv.lot / max(avg_lot, 1)) * 20, 1))
            walls.append(WallSignal(price=lv.price, lot=lv.lot, side=side,
                                     strength=strength, classification="Static"))
    return walls


def track_delta(prev_levels: list[OrderbookLevel], curr_levels: list[OrderbookLevel],
                 last_trade_price: float, side: str) -> list[WallSignal]:
    """Bandingkan dua snapshot sisi yang sama, klasifikasi perilaku tiap level."""
    prev_map = {lv.price: lv.lot for lv in prev_levels}
    signals = []
    for lv in curr_levels:
        prev_lot = prev_map.get(lv.price, 0)
        delta = lv.lot - prev_lot

        if prev_lot == 0 and lv.lot > 0:
            cls = "New"
        elif delta > 0:
            cls = "Building"
        elif delta < -0.5 * max(prev_lot, 1):
            crossed = (side == "bid" and last_trade_price <= lv.price) or \
                      (side == "ask" and last_trade_price >= lv.price)
            cls = "Eaten" if crossed else "Pulled"
        else:
            cls = "Static"

        if cls in ("Building", "Eaten", "Pulled", "New"):
            strength = min(100.0, round(abs(delta) / max(prev_lot, lv.lot, 1) * 100, 1))
            signals.append(WallSignal(price=lv.price, lot=lv.lot, side=side,
                                       strength=strength, classification=cls))
    return signals


# ═════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES (Both Engines)
# ═════════════════════════════════════════════════════════════════════════════

def get_tick_size(price: float) -> int:
    """IDX JATS Fraksi Harga (per bursa rules)."""
    if price < 200:    return 1
    elif price < 500:  return 2
    elif price < 2_000: return 5
    elif price < 5_000: return 25
    else:              return 50


def round_to_tick(price: float, reference: float = None) -> int:
    """Round price to nearest valid IDX tick."""
    ref = reference or price
    tick = get_tick_size(ref)
    return int(round(price / tick) * tick)


def _calc_rr(entry: float, sl: float, tp: float) -> float:
    """Calculate reward-to-risk ratio."""
    risk = entry - sl
    reward = tp - entry
    if risk <= 0 or reward <= 0:
        return 0.0
    return round(reward / risk, 2)


def _tier_result(tier: str, entry, sl, tp, rr, wall: Optional[WallScore], min_rr: float):
    """Build standardized tier result dict."""
    valid = rr >= min_rr
    warning = None if valid else \
        f"R/R {rr:.2f}x di bawah minimum {min_rr:.1f}x — pertimbangkan skip tier ini."
    return {
        "entry":      entry,
        "sl":         sl,
        "tp":         tp,
        "rr":         rr,
        "wall_price": wall.price if wall else None,
        "wall_lot":   wall.lot   if wall else None,
        "wall_score": round(wall.score, 3) if wall else None,
        "wall_round_bonus": round(wall.round_bonus, 2) if wall else None,
        "valid":      valid,
        "warning":    warning,
    }


def _guard_nearest_resistance(resistance_walls, last_price, tick):
    """Ensure nearest resistance is always above last_price."""
    if not resistance_walls:
        return None
    raw = resistance_walls[0].price - tick
    return raw if raw > last_price else last_price + tick


def _clamp_entry(raw_entry, last_price, tick):
    """Clamp entry to never exceed last_price - tick."""
    return min(raw_entry, last_price - tick)


# ═════════════════════════════════════════════════════════════════════════════
# ENGINE A — WALL GRAVITY
# Pure structural analysis. No market context.
# ═════════════════════════════════════════════════════════════════════════════

def score_walls_A(walls: List[OrderbookLevel], last_price: float) -> List[WallScore]:
    """
    Engine A: Pure wall scoring — lot × proximity × freq.

    - lot_weight:       normalized 0–1 relative to largest wall
    - proximity_weight: decay function — closer to last_price = higher score
    - freq_weight:      distributed buyers (high freq) = more genuine support
    """
    if not walls:
        return []
    max_lot = max(w.lot for w in walls) or 1
    result = []
    for w in walls:
        dist_pct = abs(last_price - w.price) / last_price
        lot_weight = w.lot / max_lot
        proximity_weight = 1 / (1 + dist_pct * 10)
        freq_weight = min(getattr(w, "freq", 1) / 20.0, 1.5) + 0.5
        score = lot_weight * proximity_weight * freq_weight
        result.append(WallScore(
            price=w.price, lot=w.lot, freq=getattr(w, "freq", 0),
            score=score,
            lot_weight=lot_weight,
            proximity_weight=proximity_weight,
            freq_weight=freq_weight,
        ))
    return result


def grounded_three_tier_A(
    last_price: float,
    bid_walls:  List[OrderbookLevel],
    ask_walls:  List[OrderbookLevel],
) -> dict:
    """
    Engine A — Wall Gravity.
    Pure structural analysis. No market context.

    Tier philosophy:
    - Aggressive : entry at market, target immediate resistance
    - Moderat    : highest composite score wall (proximity × lot × freq)
    - Low Risk   : strongest absolute support (lot × sqrt(freq))
    """
    MIN_RR = {"Aggressive": 1.0, "Moderat": 1.5, "Low Risk": 2.0}
    tick = get_tick_size(last_price)

    supports = sorted(
        [w for w in bid_walls if w.price < last_price],
        key=lambda w: w.price, reverse=True
    )
    resistances = sorted(
        [w for w in ask_walls if w.price > last_price],
        key=lambda w: w.price
    )
    nearest_resist = _guard_nearest_resistance(resistances, last_price, tick)

    # ── AGGRESSIVE ────────────────────────────────────────────────────────────
    agg_entry = last_price
    agg_sl = (supports[0].price - tick) if supports \
              else round_to_tick(last_price * 0.97, last_price)
    agg_tp = nearest_resist or round_to_tick(last_price * 1.04, last_price)
    agg_rr = _calc_rr(agg_entry, agg_sl, agg_tp)

    # ── MODERATE: highest composite score within 8% ───────────────────────────
    mod_candidates = [w for w in supports
                      if (last_price - w.price) / last_price <= 0.08]
    mod_wall = None
    if mod_candidates:
        scored = score_walls_A(mod_candidates, last_price)
        mod_wall = max(scored, key=lambda x: x.score)
        mod_entry = _clamp_entry(round_to_tick(mod_wall.price + tick, last_price),
                                 last_price, tick)
        mod_sl = round_to_tick(mod_wall.price - tick * 2, last_price)
    else:
        mod_entry = round_to_tick(last_price * 0.96, last_price)
        mod_sl = round_to_tick(last_price * 0.94, last_price)

    if nearest_resist and nearest_resist > mod_entry:
        mod_tp = nearest_resist
    else:
        mod_tp = last_price
    mod_tp = max(mod_tp, last_price)
    mod_rr = _calc_rr(mod_entry, mod_sl, mod_tp)

    # ── LOW RISK: highest lot×sqrt(freq) within 15% ──────────────────────────
    low_candidates = [w for w in supports
                      if (last_price - w.price) / last_price <= 0.15]

    # Exclude Moderate-selected wall to prevent tier overlap
    if mod_wall and low_candidates:
        filtered = [w for w in low_candidates if w.price != mod_wall.price]
        if filtered:
            low_candidates = filtered

    low_wall = None
    if low_candidates:
        scored = score_walls_A(low_candidates, last_price)
        low_wall = max(scored, key=lambda x: x.lot_weight * math.sqrt(x.freq_weight))
        low_entry = _clamp_entry(round_to_tick(low_wall.price + tick, last_price),
                                 last_price, tick)
        low_sl = round_to_tick(low_wall.price - tick * 3, last_price)
    else:
        low_entry = round_to_tick(last_price * 0.93, last_price)
        low_sl = round_to_tick(last_price * 0.91, last_price)

    low_tp = max(mod_entry if mod_wall else last_price, last_price)
    if low_tp <= low_entry:
        low_tp = last_price + tick
    if nearest_resist and nearest_resist > low_tp * 1.03:
        low_tp = nearest_resist
    low_rr = _calc_rr(low_entry, low_sl, low_tp)

    return {
        "engine": "A",
        "engine_label": "Wall Gravity",
        "Aggressive": _tier_result("Aggressive", agg_entry, agg_sl, agg_tp,
                                   agg_rr, None, MIN_RR["Aggressive"]),
        "Moderat":    _tier_result("Moderat", mod_entry, mod_sl, mod_tp,
                                   mod_rr, mod_wall, MIN_RR["Moderat"]),
        "Low Risk":   _tier_result("Low Risk", low_entry, low_sl, low_tp,
                                   low_rr, low_wall, MIN_RR["Low Risk"]),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ENGINE B — CONTEXTUAL ALPHA
# Sentiment × Round Number Magnet × Depth Adaptation
# ═════════════════════════════════════════════════════════════════════════════

def calc_sentiment_factor(
    total_bid_lot: int,
    total_ask_lot: int,
    last_price: float,
    avg_price: float,
    open_price: float,
) -> float:
    """
    Returns sentiment_factor: 0.3 (very bearish) → 2.0 (very bullish).

    Three components:
    1. Imbalance ratio   — ratio bid/ask total lot
    2. Avg divergence    — avg > last = holders underwater = sell pressure
    3. Open trend        — last vs open = intraday direction
    """
    # 1. Imbalance ratio (0.0 – 2.0+)
    imbalance = total_bid_lot / total_ask_lot if total_ask_lot > 0 else 1.0

    # 2. Avg divergence penalty (negative if avg > last)
    avg_div = (avg_price - last_price) / last_price if last_price > 0 else 0
    avg_penalty = 1.0 - max(0.0, avg_div * 5)   # each 1% avg above last → -5% factor
    avg_penalty = max(0.4, avg_penalty)           # floor 0.4x

    # 3. Open trend (negative if dropping from open)
    open_div = (last_price - open_price) / open_price if open_price > 0 else 0
    open_trend = 1.0 + open_div
    open_trend = max(0.5, min(1.5, open_trend))   # clamp 0.5x – 1.5x

    raw = imbalance * avg_penalty * open_trend
    return max(0.3, min(2.0, round(raw, 4)))       # final clamp


def get_sentiment_label(sentiment: float) -> str:
    """Human-readable label for sentiment factor."""
    if sentiment < 0.5:  return "Very Bearish"
    elif sentiment < 0.7: return "Bearish"
    elif sentiment < 1.0: return "Mild Bearish"
    elif sentiment < 1.3: return "Neutral"
    else:                 return "Bullish"


def round_number_bonus(price: float) -> float:
    """
    Multiplier based on proximity to psychological levels.
    100-divisible: 1.20x (strongest) | 50-divisible: 1.10x | 25-divisible: 1.05x
    """
    p = int(price)
    if p % 100 == 0:  return 1.20
    elif p % 50 == 0: return 1.10
    elif p % 25 == 0: return 1.05
    else:             return 1.00


def get_entry_thresholds(sentiment_factor: float) -> dict:
    """
    Sentiment-adaptive entry depth thresholds.
    Bearish = wait deeper for entry. Bullish = entry closer (walls more reliable).
    """
    if sentiment_factor < 0.7:       # BEARISH
        return {
            "aggressive_enabled": False,
            "moderate_depth": 0.10,
            "low_risk_depth": 0.18,
            "tp_factor": 0.85,
        }
    elif sentiment_factor < 1.0:     # MILD BEARISH
        return {
            "aggressive_enabled": True,
            "moderate_depth": 0.08,
            "low_risk_depth": 0.15,
            "tp_factor": 0.92,
        }
    elif sentiment_factor < 1.3:     # NEUTRAL
        return {
            "aggressive_enabled": True,
            "moderate_depth": 0.08,
            "low_risk_depth": 0.15,
            "tp_factor": 1.00,
        }
    else:                            # BULLISH
        return {
            "aggressive_enabled": True,
            "moderate_depth": 0.05,
            "low_risk_depth": 0.10,
            "tp_factor": 1.15,
        }


def score_walls_B(
    walls: List[OrderbookLevel],
    last_price: float,
    sentiment_factor: float,
) -> List[WallScore]:
    """Engine B: Context-weighted scoring — lot × proximity × freq × sentiment × round."""
    if not walls:
        return []
    max_lot = max(w.lot for w in walls) or 1
    result = []
    for w in walls:
        dist_pct = abs(last_price - w.price) / last_price
        lot_weight = w.lot / max_lot
        proximity_weight = 1 / (1 + dist_pct * 10)
        freq_weight = min(getattr(w, "freq", 1) / 20.0, 1.5) + 0.5
        r_bonus = round_number_bonus(w.price)
        base_score = lot_weight * proximity_weight * freq_weight
        final_score = base_score * sentiment_factor * r_bonus
        result.append(WallScore(
            price=w.price, lot=w.lot, freq=getattr(w, "freq", 0),
            score=final_score,
            lot_weight=lot_weight,
            proximity_weight=proximity_weight,
            freq_weight=freq_weight,
            round_bonus=r_bonus,
            sentiment_adjusted=final_score,
        ))
    return result


def grounded_three_tier_B(
    last_price:    float,
    bid_walls:     List[OrderbookLevel],
    ask_walls:     List[OrderbookLevel],
    total_bid_lot: int,
    total_ask_lot: int,
    avg_price:     float,
    open_price:    float,
) -> dict:
    """
    Engine B — Contextual Alpha.
    Sentiment + round number magnet + depth adaptation.
    Aggressive tier may be disabled in bearish conditions.
    """
    MIN_RR = {"Aggressive": 1.0, "Moderat": 1.5, "Low Risk": 2.0}
    tick = get_tick_size(last_price)

    sentiment = calc_sentiment_factor(total_bid_lot, total_ask_lot,
                                      last_price, avg_price, open_price)
    thresholds = get_entry_thresholds(sentiment)

    supports = sorted(
        [w for w in bid_walls if w.price < last_price],
        key=lambda w: w.price, reverse=True
    )
    resistances = sorted(
        [w for w in ask_walls if w.price > last_price],
        key=lambda w: w.price
    )
    nearest_resist = _guard_nearest_resistance(resistances, last_price, tick)

    # ── AGGRESSIVE: disabled if bearish ───────────────────────────────────────
    if not thresholds["aggressive_enabled"]:
        agg_result = {
            "entry": None, "sl": None, "tp": None, "rr": 0.0,
            "wall_price": None, "wall_lot": None, "wall_score": None,
            "valid": False,
            "warning": f"Aggressive DISABLED — sentiment bearish ({sentiment:.2f}x). "
                       f"Tunggu imbalance membaik (>0.8x) sebelum breakout play.",
        }
    else:
        agg_entry = last_price
        agg_sl = (supports[0].price - tick) if supports \
                  else round_to_tick(last_price * 0.97, last_price)
        agg_tp = nearest_resist or round_to_tick(last_price * 1.04, last_price)
        agg_rr = _calc_rr(agg_entry, agg_sl, agg_tp)
        agg_result = _tier_result("Aggressive", agg_entry, agg_sl, agg_tp,
                                  agg_rr, None, MIN_RR["Aggressive"])

    # ── MODERATE: highest B-score in adapted depth ────────────────────────────
    mod_depth = thresholds["moderate_depth"]
    mod_candidates = [w for w in supports
                      if (last_price - w.price) / last_price <= mod_depth]
    mod_wall = None
    if mod_candidates:
        scored = score_walls_B(mod_candidates, last_price, sentiment)
        mod_wall = max(scored, key=lambda x: x.score)
        mod_entry = _clamp_entry(round_to_tick(mod_wall.price + tick, last_price),
                                 last_price, tick)
        mod_sl = round_to_tick(mod_wall.price - tick * 2, last_price)
    else:
        mod_entry = round_to_tick(last_price * (1 - mod_depth * 0.5), last_price)
        mod_sl = round_to_tick(last_price * (1 - mod_depth * 0.7), last_price)

    # Apply TP factor for market context (scale the spread, not absolute price)
    raw_mod_tp = nearest_resist or last_price
    if thresholds["tp_factor"] != 1.0:
        _move = max(tick, raw_mod_tp - mod_entry)
        mod_tp = max(mod_entry + round_to_tick(_move * thresholds["tp_factor"], last_price),
                     last_price + tick)
    else:
        mod_tp = max(raw_mod_tp, last_price + tick)
    mod_rr = _calc_rr(mod_entry, mod_sl, mod_tp)

    # ── LOW RISK: highest lot×freq×round_bonus in adapted depth ───────────────
    low_depth = thresholds["low_risk_depth"]
    low_candidates = [w for w in supports
                      if (last_price - w.price) / last_price <= low_depth]

    # Exclude Moderate-selected wall to prevent tier overlap
    if mod_wall and low_candidates:
        filtered = [w for w in low_candidates if w.price != mod_wall.price]
        if filtered:
            low_candidates = filtered

    low_wall = None
    if low_candidates:
        scored = score_walls_B(low_candidates, last_price, sentiment)
        # Strength priority: lot × sqrt(freq) × round_bonus (not proximity)
        low_wall = max(scored, key=lambda x: x.lot_weight * math.sqrt(x.freq_weight) * x.round_bonus)
        low_entry = _clamp_entry(round_to_tick(low_wall.price + tick, last_price),
                                 last_price, tick)
        low_sl = round_to_tick(low_wall.price - tick * 3, last_price)
    else:
        low_entry = round_to_tick(last_price * (1 - low_depth * 0.6), last_price)
        low_sl = round_to_tick(last_price * (1 - low_depth * 0.8), last_price)

    low_tp_base = max(mod_entry if mod_wall else last_price, last_price)
    if low_tp_base <= low_entry:
        low_tp_base = last_price + tick
    if nearest_resist and nearest_resist > low_tp_base * 1.03:
        low_tp_base = nearest_resist
    if thresholds["tp_factor"] != 1.0:
        _move = max(tick, low_tp_base - low_entry)
        low_tp = max(low_entry + round_to_tick(_move * thresholds["tp_factor"], last_price),
                     last_price + tick)
    else:
        low_tp = max(low_tp_base, last_price + tick)
    low_rr = _calc_rr(low_entry, low_sl, low_tp)

    return {
        "engine": "B",
        "engine_label": "Contextual Alpha",
        "sentiment_factor": round(sentiment, 3),
        "sentiment_label": get_sentiment_label(sentiment),
        "aggressive_enabled": thresholds["aggressive_enabled"],
        "depth_config": thresholds,
        "Aggressive": agg_result,
        "Moderat":    _tier_result("Moderat", mod_entry, mod_sl, mod_tp,
                                   mod_rr, mod_wall, MIN_RR["Moderat"]),
        "Low Risk":   _tier_result("Low Risk", low_entry, low_sl, low_tp,
                                   low_rr, low_wall, MIN_RR["Low Risk"]),
    }


# ═════════════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY — Legacy alias
# ═════════════════════════════════════════════════════════════════════════════

# Keep old names working for any external callers
score_walls = score_walls_A
grounded_three_tier = grounded_three_tier_A
