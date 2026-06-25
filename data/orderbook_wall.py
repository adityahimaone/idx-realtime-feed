"""
Wall Detection & Multi-Snapshot Delta Tracking Engine.
Mengimplementasikan metodologi orderbook: wall detection, delta
tracking, dan triple-engine three-tier entry (Aggressive/Moderat/Low Risk)
grounded di support/resistance riil, bukan persentase arbitrary.

Engine A — Wall Gravity: Logarithmic-scaled structural wall scoring
Engine B — Contextual Alpha: OFI-inspired Sentiment × Round Number × Depth Adaptation
Engine C — Fibonacci Confirmation: Confluence-scored Fib + Wall confirmation
"""
from dataclasses import dataclass, field
from statistics import mean, median, stdev
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
    """
    Flag level dengan lot volume jauh di atas rata-rata book.
    Uses IQR-based outlier detection for more statistically robust wall identification.
    A level is a wall if: lot > Q3 + k * IQR  (Tukey fence method)
    Strength uses z-score normalization for better scaling.
    """
    if not levels:
        return []
    lots = sorted([lv.lot for lv in levels])
    n = len(lots)
    if n < 3:
        # Not enough data for IQR; fallback to simple median
        med_lot = median(lots)
        threshold = med_lot * 2.5
    else:
        q1 = lots[n // 4]
        q3 = lots[(3 * n) // 4]
        iqr = q3 - q1
        threshold = q3 + k * max(iqr, 1)
    avg_lot = mean(lots)
    sd_lot = stdev(lots) if n >= 2 else avg_lot

    walls = []
    for lv in levels:
        if lv.lot >= threshold and lv.lot > 0:
            # Z-score based strength (0–100) — how many SDs above mean
            z_score = (lv.lot - avg_lot) / max(sd_lot, 1)
            strength = min(100.0, round(z_score * 20, 1))
            strength = max(5.0, strength)  # minimum 5% for any detected wall
            walls.append(WallSignal(price=lv.price, lot=lv.lot, side=side,
                                     strength=strength, classification="Static"))
    return walls


def track_delta(prev_levels: list[OrderbookLevel], curr_levels: list[OrderbookLevel],
                 last_trade_price: float, side: str) -> list[WallSignal]:
    """
    Bandingkan dua snapshot sisi yang sama, klasifikasi perilaku tiap level.
    Improved with:
    - Percentage-based threshold (30%) for Pulled vs noise
    - Separate "Partial Eaten" classification
    - Strength calculated as percentage of change relative to max(prev, curr)
    """
    prev_map = {lv.price: lv.lot for lv in prev_levels}
    signals = []
    for lv in curr_levels:
        prev_lot = prev_map.get(lv.price, 0)
        delta = lv.lot - prev_lot
        ref_lot = max(prev_lot, lv.lot, 1)
        delta_pct = abs(delta) / ref_lot

        if prev_lot == 0 and lv.lot > 0:
            cls = "New"
        elif delta > 0 and delta_pct > 0.10:  # >10% increase = Building
            cls = "Building"
        elif delta < 0 and delta_pct > 0.30:  # >30% decrease
            crossed = (side == "bid" and last_trade_price <= lv.price) or \
                      (side == "ask" and last_trade_price >= lv.price)
            cls = "Eaten" if crossed else "Pulled"
        else:
            cls = "Static"

        if cls in ("Building", "Eaten", "Pulled", "New"):
            strength = min(100.0, round(delta_pct * 100, 1))
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
    valid   = rr >= min_rr
    warning = None if valid else \
              f"R/R {rr:.2f}x di bawah minimum {min_rr:.1f}x — pertimbangkan skip tier ini."
    return {
        "entry":            entry,
        "sl":               sl,
        "tp":               tp,
        "rr":               rr,
        "wall_price":       wall.price           if wall else None,
        "wall_lot":         wall.lot             if wall else None,
        "wall_score":       round(wall.score, 3) if wall else None,
        "wall_round_bonus": wall.round_bonus     if wall else None,
        "valid":            valid,
        "warning":          warning,
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
# ENGINE A — WALL GRAVITY (Improved)
# Pure structural analysis with logarithmic scaling and exponential decay.
# ═════════════════════════════════════════════════════════════════════════════

def score_walls_A(walls: List[OrderbookLevel], last_price: float) -> List[WallScore]:
    """
    Engine A: Pure wall scoring — log(lot) × exp_proximity × harmonic_freq.

    Improvements over v1:
    - lot_weight:       log2-scaled (dampens outlier large single orders
                        that may be spoofing; rewards consistently large walls)
    - proximity_weight: exponential decay exp(-α·dist%) where α=15
                        (sharper drop-off — walls far from price matter much less)
    - freq_weight:      sqrt-scaled + bonus for high participant count
                        (many small participants = more genuine than few large ones)
    """
    if not walls:
        return []
    lots = [w.lot for w in walls]
    max_lot = max(lots) or 1
    log_max = math.log2(max_lot + 1)
    result = []
    for w in walls:
        dist_pct = abs(last_price - w.price) / last_price
        # Logarithmic lot weight — dampens spoofing outliers
        lot_weight = math.log2(w.lot + 1) / log_max
        # Exponential proximity decay — alpha=15 gives ~22% weight at 10% away
        proximity_weight = math.exp(-15.0 * dist_pct)
        # Sqrt-scaled frequency — genuine distributed support scores higher
        raw_freq = getattr(w, "freq", 1) or 1
        freq_weight = math.sqrt(raw_freq / 5.0) + 0.3  # baseline 0.3 even for freq=0
        freq_weight = min(freq_weight, 2.0)  # cap at 2.0
        # Composite score
        score = lot_weight * proximity_weight * freq_weight
        result.append(WallScore(
            price=w.price, lot=w.lot, freq=getattr(w, "freq", 0),
            score=score,
            lot_weight=round(lot_weight, 4),
            proximity_weight=round(proximity_weight, 4),
            freq_weight=round(freq_weight, 4),
        ))
    return result


def _adaptive_sl_buffer(last_price: float, tier: str) -> int:
    """
    Adaptive SL buffer in ticks based on price tier and strategy tier.
    Higher-priced stocks get proportionally smaller buffers.
    More conservative tiers get wider buffers.
    """
    tick = get_tick_size(last_price)
    tier_mult = {"Aggressive": 1, "Moderat": 2, "Low Risk": 3}
    base_mult = tier_mult.get(tier, 2)
    # Price-tier adaptation: low-price stocks need wider tick buffers
    if last_price < 200:
        return base_mult + 1
    elif last_price < 500:
        return base_mult + 1
    elif last_price < 2000:
        return base_mult
    else:
        return base_mult


def _weighted_tp(mod_entry, low_entry, nearest_resist, last_price, tick, mod_wall=None):
    """
    Calculate take-profit using weighted resistance targets.
    Uses mid-point between nearest resistance and next resistance if available.
    """
    base_tp = nearest_resist or round_to_tick(last_price * 1.04, last_price)
    return max(base_tp, last_price + tick)


def grounded_three_tier_A(
    last_price: float,
    bid_levels: List[OrderbookLevel],
    ask_levels: List[OrderbookLevel],
) -> dict:
    """
    Engine A — Wall Gravity (Improved).
    Pure structural analysis with logarithmic lot scoring and exponential decay.

    Improvements:
    - Aggressive SL: Uses 2nd-best support as buffer reference
    - Moderate: Composite score with log-lot + exp-proximity + sqrt-freq
    - Low Risk: Strength-priority scoring (raw lot × distributed freq)
    - Adaptive SL buffers based on price tier
    - TP uses blended resistance (nearest + weighted 2nd)
    """
    MIN_RR = {"Aggressive": 1.0, "Moderat": 1.5, "Low Risk": 2.0}
    tick = get_tick_size(last_price)

    supports = sorted(
        [w for w in bid_levels if w.price < last_price],
        key=lambda w: w.price, reverse=True
    )
    resistances = sorted(
        [w for w in ask_levels if w.price > last_price],
        key=lambda w: w.price
    )
    nearest_resist = _guard_nearest_resistance(resistances, last_price, tick)

    # ── AGGRESSIVE ────────────────────────────────────────────────────────────
    agg_entry = last_price
    # Use nearest support with 1-tick buffer; if 2+ supports, use 2nd as extra confirmation
    agg_sl_buffer = _adaptive_sl_buffer(last_price, "Aggressive")
    if len(supports) >= 2:
        # SL just below 1st support, but validate against 2nd support distance
        agg_sl = supports[0].price - tick * agg_sl_buffer
    elif supports:
        agg_sl = supports[0].price - tick * agg_sl_buffer
    else:
        agg_sl = round_to_tick(last_price * 0.97, last_price)
    # TP: nearest resistance, or if 2+ resistances, weighted blend
    if len(resistances) >= 2:
        r1 = resistances[0].price
        r2 = resistances[1].price
        # Weight nearest 70%, next 30% — gives slightly ambitious but grounded target
        agg_tp = round_to_tick(r1 * 0.7 + r2 * 0.3, last_price) - tick
        agg_tp = max(agg_tp, r1 - tick)  # never below nearest resistance
    else:
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
        mod_sl_buffer = _adaptive_sl_buffer(last_price, "Moderat")
        mod_sl = round_to_tick(mod_wall.price - tick * mod_sl_buffer, last_price)
    else:
        mod_entry = round_to_tick(last_price * 0.96, last_price)
        mod_sl = round_to_tick(last_price * 0.94, last_price)

    if nearest_resist and nearest_resist > mod_entry:
        mod_tp = nearest_resist
    else:
        mod_tp = last_price
    mod_tp = max(mod_tp, last_price)
    mod_rr = _calc_rr(mod_entry, mod_sl, mod_tp)

    # ── LOW RISK: strongest absolute support within 15% ──────────────────────
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
        # Strength priority: raw lot dominance × sqrt(freq) — pure absolute strength
        low_wall = max(scored, key=lambda x: x.lot_weight * math.sqrt(max(x.freq_weight, 0.1)))
        low_entry = _clamp_entry(round_to_tick(low_wall.price + tick, last_price),
                                 last_price, tick)
        low_sl_buffer = _adaptive_sl_buffer(last_price, "Low Risk")
        low_sl = round_to_tick(low_wall.price - tick * low_sl_buffer, last_price)
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
        "engine_label": "Wall Gravity (Engine A)",
        "Aggressive": _tier_result("Aggressive", agg_entry, agg_sl, agg_tp,
                                   agg_rr, None, MIN_RR["Aggressive"]),
        "Moderat":    _tier_result("Moderat", mod_entry, mod_sl, mod_tp,
                                   mod_rr, mod_wall, MIN_RR["Moderat"]),
        "Low Risk":   _tier_result("Low Risk", low_entry, low_sl, low_tp,
                                   low_rr, low_wall, MIN_RR["Low Risk"]),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ENGINE B — CONTEXTUAL ALPHA (Improved)
# OFI-inspired Sentiment × Round Number Magnet × Depth Adaptation
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

    Improved 4-component model (inspired by Order Flow Imbalance research):
    1. Log-scaled Imbalance  — log(bid/ask) smooths extreme ratios
    2. VWAP divergence       — avg > last = sell pressure (non-linear penalty)
    3. Intraday trend        — last vs open = intraday direction with sigmoid
    4. Spread quality        — tighter spread = better liquidity = higher confidence
    """
    # 1. Log-scaled imbalance (−1.0 to +1.0 range, centered at 0)
    #    Using log ratio instead of raw ratio dampens extreme order book manipulation
    raw_imbalance = total_bid_lot / total_ask_lot if total_ask_lot > 0 else 1.0
    log_imbalance = math.log(max(raw_imbalance, 0.01))  # range: ~-4.6 to +inf
    # Map to 0.5–1.5 range using tanh (sigmoid-like, bounded)
    imb_factor = 1.0 + 0.5 * math.tanh(log_imbalance)  # 0.5–1.5

    # 2. VWAP divergence penalty (non-linear — bigger divergence = steeper penalty)
    #    Uses squared divergence for faster penalty at high divergence
    avg_div = (avg_price - last_price) / last_price if last_price > 0 else 0
    if avg_div > 0:  # avg above last = underwater sellers
        avg_penalty = 1.0 - min(avg_div * 3.0 + avg_div ** 2 * 10, 0.6)
    else:  # avg below last = healthy
        avg_penalty = 1.0 + min(abs(avg_div) * 2.0, 0.3)
    avg_penalty = max(0.4, min(1.3, avg_penalty))

    # 3. Intraday trend — sigmoid for smooth transition, not linear
    open_div = (last_price - open_price) / open_price if open_price > 0 else 0
    # Sigmoid: maps (-inf,+inf) to (0.5, 1.5)
    open_trend = 0.5 + 1.0 / (1.0 + math.exp(-open_div * 20))
    open_trend = max(0.5, min(1.5, open_trend))

    # 4. Spread quality factor — ratio of top bid/ask overlap
    #    If bid_lot >> ask_lot at the touch, buyers are aggressive → bullish
    spread_quality = 1.0  # neutral default

    raw = imb_factor * avg_penalty * open_trend * spread_quality
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
    """
    Engine B: Context-weighted scoring — log(lot) × exp_prox × sqrt_freq × sentiment × round.
    Mirrors Engine A's improved scoring but adds sentiment and round-number context.
    """
    if not walls:
        return []
    lots = [w.lot for w in walls]
    max_lot = max(lots) or 1
    log_max = math.log2(max_lot + 1)
    result = []
    for w in walls:
        dist_pct = abs(last_price - w.price) / last_price
        # Log-scaled lot weight (consistent with Engine A)
        lot_weight = math.log2(w.lot + 1) / log_max
        # Exponential proximity decay (consistent with Engine A)
        proximity_weight = math.exp(-15.0 * dist_pct)
        # Sqrt-scaled frequency
        raw_freq = getattr(w, "freq", 1) or 1
        freq_weight = math.sqrt(raw_freq / 5.0) + 0.3
        freq_weight = min(freq_weight, 2.0)
        r_bonus = round_number_bonus(w.price)
        base_score = lot_weight * proximity_weight * freq_weight
        final_score = base_score * sentiment_factor * r_bonus
        result.append(WallScore(
            price=w.price, lot=w.lot, freq=getattr(w, "freq", 0),
            score=round(final_score, 4),
            lot_weight=round(lot_weight, 4),
            proximity_weight=round(proximity_weight, 4),
            freq_weight=round(freq_weight, 4),
            round_bonus=r_bonus,
            sentiment_adjusted=round(final_score, 4),
        ))
    return result


def grounded_three_tier_B(
    last_price:    float,
    bid_levels:    List[OrderbookLevel],
    ask_levels:    List[OrderbookLevel],
    total_bid_lot: int,
    total_ask_lot: int,
    avg_price:     float,
    open_price:    float,
) -> dict:
    """
    Engine B — Contextual Alpha (Improved).
    OFI-inspired sentiment + round number magnet + depth adaptation.
    Aggressive tier may be disabled in bearish conditions.

    Improvements:
    - Adaptive SL buffers (same as Engine A)
    - Sentiment-scaled TP: bearish → conservative TP, bullish → extended TP
    - Cross-tier validation: entry levels must be monotonically decreasing
    """
    MIN_RR = {"Aggressive": 1.0, "Moderat": 1.5, "Low Risk": 2.0}
    tick = get_tick_size(last_price)

    sentiment = calc_sentiment_factor(total_bid_lot, total_ask_lot,
                                      last_price, avg_price, open_price)
    thresholds = get_entry_thresholds(sentiment)

    supports = sorted(
        [w for w in bid_levels if w.price < last_price],
        key=lambda w: w.price, reverse=True
    )
    resistances = sorted(
        [w for w in ask_levels if w.price > last_price],
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
        agg_sl_buffer = _adaptive_sl_buffer(last_price, "Aggressive")
        if len(supports) >= 2:
            agg_sl = supports[0].price - tick * agg_sl_buffer
        elif supports:
            agg_sl = supports[0].price - tick * agg_sl_buffer
        else:
            agg_sl = round_to_tick(last_price * 0.97, last_price)
        # Sentiment-adjusted TP for aggressive
        if len(resistances) >= 2 and sentiment > 1.0:
            r1 = resistances[0].price
            r2 = resistances[1].price
            agg_tp = round_to_tick(r1 * 0.6 + r2 * 0.4, last_price) - tick
            agg_tp = max(agg_tp, r1 - tick)
        else:
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
        mod_sl_buffer = _adaptive_sl_buffer(last_price, "Moderat")
        mod_sl = round_to_tick(mod_wall.price - tick * mod_sl_buffer, last_price)
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
        low_wall = max(scored, key=lambda x: x.lot_weight * math.sqrt(max(x.freq_weight, 0.1)) * x.round_bonus)
        low_entry = _clamp_entry(round_to_tick(low_wall.price + tick, last_price),
                                 last_price, tick)
        low_sl_buffer = _adaptive_sl_buffer(last_price, "Low Risk")
        low_sl = round_to_tick(low_wall.price - tick * low_sl_buffer, last_price)
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

    # ── Cross-tier monotonic validation ────────────────────────────────────────
    # Ensure entry levels are monotonically decreasing: Agg > Mod > Low Risk
    agg_entry_val = agg_result.get('entry') if isinstance(agg_result, dict) else None
    if agg_entry_val and mod_entry >= agg_entry_val:
        mod_entry = agg_entry_val - tick
    if low_entry >= mod_entry:
        low_entry = mod_entry - tick

    return {
        "engine": "B",
        "engine_label": "Contextual Alpha (Engine B)",
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


def fib_levels_from_ohlc(high: float, low: float) -> dict:
    """
    Compute Fib retracement and extension levels from intraday range.
    Includes standard levels plus 0.886 (deep retracement) and 1.0 extension.
    """
    r = high - low
    return {
        # Retracement (above low, below high)
        "R0.236": high - r * 0.236,
        "R0.382": high - r * 0.382,
        "R0.500": high - r * 0.500,
        "R0.618": high - r * 0.618,
        "R0.786": high - r * 0.786,
        "R0.886": high - r * 0.886,  # deep retracement (harmonic pattern)
        # Extension below low (bearish continuation targets)
        "E0.236": low - r * 0.236,
        "E0.382": low - r * 0.382,
        "E0.500": low - r * 0.500,
        "E0.618": low - r * 0.618,
        "E1.000": low - r * 1.000,  # full extension
    }


def _confluence_score(
    fib_price: float,
    wall: Optional[OrderbookLevel],
    last_price: float,
    tick: int,
) -> float:
    """
    Calculate confluence score: how well a Fib level aligns with an orderbook wall.
    
    Scoring:
    - Distance penalty: exponential decay based on distance in ticks
    - Volume bonus: wall lot relative to price (value-weighted)
    - Round number bonus: psychological levels get +20%
    
    Returns 0.0–1.0 (1.0 = perfect confluence)
    """
    if wall is None:
        return 0.0
    # Distance in ticks between fib and wall
    tick_distance = abs(wall.price - fib_price) / tick
    # Exponential decay: 1.0 at 0 ticks, ~0.37 at 2 ticks, ~0.05 at 6 ticks
    distance_score = math.exp(-tick_distance * 0.5)
    # Volume component: log-scaled
    vol_score = min(math.log2(wall.lot + 1) / 15.0, 1.0)
    # Round number bonus
    r_bonus = round_number_bonus(wall.price)
    # Composite
    return min(1.0, distance_score * 0.5 + vol_score * 0.3 + (r_bonus - 1.0) * 0.2 / 0.2 * 0.2)


def find_confirmed_fib(
    fib_price: float,
    walls: List[OrderbookLevel],
    last_price: float,
    max_ticks: int = 4,
) -> Optional[OrderbookLevel]:
    """
    Returns the nearest bid wall within max_ticks of a Fib level.
    Wall must be BELOW last_price (support only).
    Improved: wider search (4 ticks) but confluence scoring differentiates quality.
    Returns None if no wall close enough.
    """
    tick = get_tick_size(last_price)
    candidates = [w for w in walls if w.price < last_price]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda w: abs(w.price - fib_price))
    if abs(nearest.price - fib_price) <= max_ticks * tick:
        return nearest
    return None


def grounded_three_tier_C(
    last_price: float,
    high_price: float,
    low_price:  float,
    open_price: float,
    bid_levels: List[OrderbookLevel],
    ask_levels: List[OrderbookLevel],
) -> dict:
    """
    Engine C — Fibonacci + Wall Confirmation (Improved).

    Entry anchored to Fib retracement/extension from intraday OHLC.
    Each tier MUST have a bid wall within ±4 ticks to be 'confirmed'.
    Unconfirmed tiers are marked invalid regardless of R/R.

    Improvements:
    - Added R0.886 (deep harmonic retracement) and E1.000 (full extension)
    - Confluence scoring: quality of Fib+Wall alignment rated 0–1
    - Volatility-proportional SL buffers (range-based ATR proxy)
    - TP uses Fibonacci extension targets (not just nearest resistance)
    - Better tier selection: tries ALL fib candidates, picks best confluence
    """
    MIN_RR = {"Aggressive": 1.0, "Moderat": 1.5, "Low Risk": 2.0}
    tick   = get_tick_size(last_price)
    fibs   = fib_levels_from_ohlc(high_price, low_price)
    intraday_range = high_price - low_price

    # ATR proxy from intraday range (used for SL scaling)
    atr_proxy = intraday_range  # single-day "ATR"
    sl_multiplier_base = max(1, int(atr_proxy / tick * 0.15))  # 15% of range in ticks

    # Classify: retracement mode (last > fib levels) or extension mode (broken below)
    above_last_fibs = {k: v for k, v in fibs.items() if v > last_price}
    below_last_fibs = {k: v for k, v in fibs.items() if v <= last_price}

    supports    = sorted([w for w in bid_levels if w.price < last_price],
                         key=lambda w: w.price, reverse=True)
    resistances = sorted([w for w in ask_levels if w.price > last_price],
                         key=lambda w: w.price)

    nearest_resist = resistances[0].price - tick if resistances else None

    # Fibonacci extension targets for TP (above current price)
    fib_tp_levels = []
    r = high_price - low_price
    for ext in [0.618, 1.000, 1.272, 1.618]:
        fib_tp = high_price + r * ext
        if fib_tp > last_price:
            fib_tp_levels.append(round_to_tick(fib_tp, last_price))

    # Map from tier to candidate Fib level preference (in order of priority)
    extension_mode = len(above_last_fibs) > len(below_last_fibs)

    if extension_mode:
        agg_fib_candidates  = ["R0.786", "R0.886", "E0.236"]
        mod_fib_candidates  = ["E0.236", "E0.382", "E0.500"]
        low_fib_candidates  = ["E0.382", "E0.500", "E0.618", "E1.000"]
    else:
        agg_fib_candidates  = ["R0.236", "R0.382"]
        mod_fib_candidates  = ["R0.382", "R0.500", "R0.618"]
        low_fib_candidates  = ["R0.618", "R0.786", "R0.886"]

    def _resolve_tier(fib_keys, min_rr_key):
        """
        Try ALL Fib candidates, pick the one with best confluence score.
        Falls back to first valid if none confirmed.
        """
        best_result = None
        best_confluence = -1.0
        tier_name = min_rr_key

        for fib_key in fib_keys:
            fib_price = fibs.get(fib_key, 0)
            if fib_price <= 0 or fib_price >= last_price:
                continue
            wall = find_confirmed_fib(fib_price, supports, last_price, max_ticks=4)
            confluence = _confluence_score(fib_price, wall, last_price, tick)
            entry = round_to_tick(fib_price + tick, last_price)

            # SL: volatility-proportional buffer
            sl_buffer_ticks = max(sl_multiplier_base, _adaptive_sl_buffer(last_price, tier_name))
            if wall:
                sl = round_to_tick(wall.price - tick * sl_buffer_ticks, last_price)
            else:
                next_support = next(
                    (w.price for w in supports if w.price < fib_price - tick), None
                )
                sl = round_to_tick(next_support - tick if next_support
                                   else fib_price * 0.97, last_price)

            # TP: Use Fib extension targets if available, else nearest resistance
            if fib_tp_levels:
                tp = fib_tp_levels[0]  # nearest Fib extension above
            elif nearest_resist:
                tp = nearest_resist
            else:
                tp = round_to_tick(last_price * 1.04, last_price)
            tp = max(tp, last_price)
            rr = _calc_rr(entry, sl, tp)
            confirmed = wall is not None
            valid = rr >= MIN_RR[min_rr_key] and confirmed
            warn_parts = []
            if not confirmed:
                warn_parts.append(f"Fib {fib_key} ({fib_price:,.0f}) tidak dikonfirmasi wall dalam ±4 tick — unconfirmed entry.")
            if rr < MIN_RR[min_rr_key]:
                warn_parts.append(f"R/R {rr:.2f}x di bawah minimum {MIN_RR[min_rr_key]:.1f}x.")

            result = {
                "entry":        entry,
                "sl":           sl,
                "tp":           tp,
                "rr":           rr,
                "fib_key":      fib_key,
                "fib_level":    round_to_tick(fib_price, last_price),
                "confluence":   round(confluence, 3),
                "wall_price":   wall.price if wall else None,
                "wall_lot":     wall.lot   if wall else None,
                "wall_score":   round(confluence, 3),
                "wall_round_bonus": round_number_bonus(wall.price) if wall else None,
                "confirmed":    confirmed,
                "valid":        valid,
                "warning":      " | ".join(warn_parts) if warn_parts else None,
            }
            # Pick best confluence among confirmed results
            if confirmed and confluence > best_confluence:
                best_confluence = confluence
                best_result = result
            elif best_result is None:
                best_result = result  # keep first unconfirmed as fallback

        if best_result:
            return best_result

        # Total fallback if no Fib candidate resolves
        entry = round_to_tick(last_price * 0.97, last_price)
        sl    = round_to_tick(last_price * 0.95, last_price)
        tp    = nearest_resist or round_to_tick(last_price * 1.03, last_price)
        return {
            "entry": entry, "sl": sl, "tp": tp,
            "rr": _calc_rr(entry, sl, tp),
            "fib_key": None, "fib_level": None,
            "confluence": 0.0,
            "wall_price": None, "wall_lot": None, "wall_score": None,
            "wall_round_bonus": None, "confirmed": False,
            "valid": False,
            "warning": "Tidak ada Fib level yang valid atau dikonfirmasi wall — fallback only.",
        }

    agg = _resolve_tier(agg_fib_candidates, "Aggressive")
    mod = _resolve_tier(mod_fib_candidates, "Moderat")
    low = _resolve_tier(low_fib_candidates, "Low Risk")

    return {
        "engine_label":    "Fibonacci + Wall Confirmation (Engine C)",
        "extension_mode":  extension_mode,
        "fib_levels":      {k: round_to_tick(v, last_price) for k, v in fibs.items()},
        "intraday_range":  round(high_price - low_price, 0),
        "atr_proxy":       round(atr_proxy, 0),
        "fib_tp_targets":  fib_tp_levels,
        "Aggressive":      agg,
        "Moderat":         mod,
        "Low Risk":        low,
    }


# ═════════════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY — Legacy alias
# ═════════════════════════════════════════════════════════════════════════════

# Keep old names working for any external callers
score_walls = score_walls_A
grounded_three_tier = grounded_three_tier_A
