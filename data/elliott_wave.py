"""
Elliott Wave detection via zigzag pivot analysis.
Rules:
  W2 retrace < 100% W1
  W3 not shortest among W1/W3/W5
  W4 no overlap into W1 territory

Also provides:
  fib_levels()       - retracement + extension levels from swing
  wave_targets()     - W2/W3/W4/W5 projections from W1 reference
  wave_position()    - current price position relative to detected waves
  corrective_waves() - simple A-B-C detection from zigzag
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional
from data.fetchers import safe_float

# ── Fibonacci ratios ──────────────────────────────────────────────────────────
FIB_RETRACEMENT = [0.236, 0.382, 0.500, 0.618, 0.786, 1.000]
FIB_EXTENSION   = [1.000, 1.272, 1.618, 2.000, 2.618]


def fib_levels(swing_low: float, swing_high: float) -> dict:
    """
    Compute Fibonacci retracement and extension levels from swing_low to swing_high.
    Returns dict keyed by label -> price.
    """
    diff = swing_high - swing_low
    if diff <= 0:
        return {}

    levels = {}
    for r in FIB_RETRACEMENT:
        label = f"ret_{round(r * 100, 1)}%"
        levels[label] = round(swing_high - diff * r, 2)
    for e in FIB_EXTENSION:
        label = f"ext_{round(e * 100, 1)}%"
        levels[label] = round(swing_low + diff * e, 2)
    return levels


def wave_targets(w1_start: float, w1_end: float) -> dict:
    """
    Fibonacci-based wave projections from Wave 1 as anchor.
    w1_start = bottom of W1, w1_end = top of W1 (bullish).
    Returns W2 support zone, W3 targets, W5 equal target.
    """
    w1_size = w1_end - w1_start
    if w1_size <= 0:
        return {}
    return {
        "w2_shallow_support": round(w1_end - w1_size * 0.382, 2),
        "w2_deep_support":    round(w1_end - w1_size * 0.618, 2),
        "w3_min":             round(w1_end + w1_size * 1.000, 2),
        "w3_normal":          round(w1_end + w1_size * 1.618, 2),
        "w3_extended":        round(w1_end + w1_size * 2.618, 2),
        "w5_equal_w1":        "w3_peak + w1_size (pending W3 detection)",
        "w5_truncated":       "w3_peak + w1_size * 0.618 (pending W3 detection)",
    }


# ── Pivot detection ───────────────────────────────────────────────────────────

def find_zigzag_pivots(prices: list[float], deviation_pct: float = 2.0) -> list[dict]:
    """
    Find swing high/low pivots via zigzag algorithm.
    deviation_pct: min % change from last pivot to confirm new one.
    Returns list of {idx, price, type='high'|'low'}.

    Improvement over previous version:
    - Tracks last confirmed pivot price (not just direction)
    - Deduplicates same-direction pivots by keeping best price
    - Uses deviation from last *pivot* price (not prev candle)
    """
    if not prices or len(prices) < 5:
        return []

    pivots = []
    last_pivot_price = prices[0]
    last_pivot_idx = 0
    direction = 0  # 1=up, -1=down

    for i in range(1, len(prices)):
        price = prices[i]
        pct_chg = (price - last_pivot_price) / max(abs(last_pivot_price), 1) * 100

        if direction == 0:
            if pct_chg >= deviation_pct:
                # First move up: mark start as low
                pivots.append({"idx": last_pivot_idx, "price": last_pivot_price, "type": "low"})
                direction = 1
                last_pivot_price = price
                last_pivot_idx = i
            elif pct_chg <= -deviation_pct:
                # First move down: mark start as high
                pivots.append({"idx": last_pivot_idx, "price": last_pivot_price, "type": "high"})
                direction = -1
                last_pivot_price = price
                last_pivot_idx = i

        elif direction == 1:  # trending up
            if price >= last_pivot_price:
                # Extend the high
                last_pivot_price = price
                last_pivot_idx = i
            elif (last_pivot_price - price) / max(last_pivot_price, 1) * 100 >= deviation_pct:
                # Reversal down — confirm high
                pivots.append({"idx": last_pivot_idx, "price": last_pivot_price, "type": "high"})
                direction = -1
                last_pivot_price = price
                last_pivot_idx = i

        elif direction == -1:  # trending down
            if price <= last_pivot_price:
                # Extend the low
                last_pivot_price = price
                last_pivot_idx = i
            elif (price - last_pivot_price) / max(last_pivot_price, 1) * 100 >= deviation_pct:
                # Reversal up — confirm low
                pivots.append({"idx": last_pivot_idx, "price": last_pivot_price, "type": "low"})
                direction = 1
                last_pivot_price = price
                last_pivot_idx = i

    # Append last open segment
    if direction == 1:
        pivots.append({"idx": last_pivot_idx, "price": last_pivot_price, "type": "high"})
    elif direction == -1:
        pivots.append({"idx": last_pivot_idx, "price": last_pivot_price, "type": "low"})

    return pivots


# ── Impulse wave detection ────────────────────────────────────────────────────

def detect_impulse_waves(pivots: list[dict]) -> list[dict]:
    """
    Detect valid 5-wave impulse patterns from zigzag pivots.
    Requires 6 consecutive pivots alternating low-high-low-high-low-high.
    Returns list of matched patterns with rule violations noted.
    """
    waves = []
    n = len(pivots)

    for i in range(n - 5):
        seg = pivots[i:i + 6]

        # Must start with low and alternate
        if seg[0]["type"] != "low":
            continue
        expected_types = ["low", "high", "low", "high", "low", "high"]
        if [p["type"] for p in seg] != expected_types:
            continue

        w1 = abs(seg[1]["price"] - seg[0]["price"])
        w2 = abs(seg[2]["price"] - seg[1]["price"])
        w3 = abs(seg[3]["price"] - seg[2]["price"])
        w4 = abs(seg[4]["price"] - seg[3]["price"])
        w5 = abs(seg[5]["price"] - seg[4]["price"])

        violations = []

        # Rule 1: W2 cannot retrace > 100% of W1
        if w2 >= w1:
            violations.append("W2 retraces ≥ 100% W1")

        # Rule 2: W3 cannot be shortest impulse
        if w3 < w1 and w3 < w5:
            violations.append("W3 is shortest impulse")

        # Rule 3: W4 cannot overlap W1 territory (bullish)
        w1_top = seg[1]["price"]
        w4_low = seg[4]["price"]
        if w4_low <= w1_top:
            violations.append("W4 overlaps W1 territory")

        waves.append({
            "wave_start_idx": seg[0]["idx"],
            "wave_end_idx":   seg[5]["idx"],
            "w1_start":       seg[0]["price"],
            "w1_end":         seg[1]["price"],
            "w2_end":         seg[2]["price"],
            "w3_end":         seg[3]["price"],
            "w4_end":         seg[4]["price"],
            "w5_end":         seg[5]["price"],
            "w1": round(w1, 2),
            "w2": round(w2, 2),
            "w3": round(w3, 2),
            "w4": round(w4, 2),
            "w5": round(w5, 2),
            "valid":      len(violations) == 0,
            "violations": violations,
            "w3_ratio":   round(w3 / w1, 2) if w1 > 0 else 0,  # W3/W1 ratio
        })

    return waves


# ── Corrective A-B-C detection ────────────────────────────────────────────────

def detect_corrective_waves(pivots: list[dict]) -> list[dict]:
    """
    Simple A-B-C corrective pattern detection.
    Requires 4 pivots: high-low-high-low (bearish correction) or low-high-low-high.
    """
    corrections = []
    n = len(pivots)

    for i in range(n - 3):
        seg = pivots[i:i + 4]

        # Bearish correction: high-low-high-low
        if [p["type"] for p in seg] == ["high", "low", "high", "low"]:
            wa = abs(seg[1]["price"] - seg[0]["price"])
            wb = abs(seg[2]["price"] - seg[1]["price"])
            wc = abs(seg[3]["price"] - seg[2]["price"])

            # B retracement < 100% A, C >= A (typical)
            if wb < wa and wc >= wa * 0.618:
                corrections.append({
                    "type":     "bearish_abc",
                    "a_start":  seg[0]["price"],
                    "a_end":    seg[1]["price"],
                    "b_end":    seg[2]["price"],
                    "c_end":    seg[3]["price"],
                    "wa": round(wa, 2),
                    "wb": round(wb, 2),
                    "wc": round(wc, 2),
                    "b_retrace_pct": round(wb / wa * 100, 1),
                    "c_eq_a":   abs(wc - wa) / wa < 0.1,  # C ≈ A
                })

        # Bullish correction: low-high-low-high
        elif [p["type"] for p in seg] == ["low", "high", "low", "high"]:
            wa = abs(seg[1]["price"] - seg[0]["price"])
            wb = abs(seg[2]["price"] - seg[1]["price"])
            wc = abs(seg[3]["price"] - seg[2]["price"])

            if wb < wa and wc >= wa * 0.618:
                corrections.append({
                    "type":     "bullish_abc",
                    "a_start":  seg[0]["price"],
                    "a_end":    seg[1]["price"],
                    "b_end":    seg[2]["price"],
                    "c_end":    seg[3]["price"],
                    "wa": round(wa, 2),
                    "wb": round(wb, 2),
                    "wc": round(wc, 2),
                    "b_retrace_pct": round(wb / wa * 100, 1),
                    "c_eq_a":   abs(wc - wa) / wa < 0.1,
                })

    return corrections


# ── Wave position ─────────────────────────────────────────────────────────────

def current_wave_position(waves: list[dict], current_price: float) -> dict:
    """
    Estimate current wave position based on detected impulse waves.
    Returns current wave label and likely next target.
    """
    if not waves:
        return {"position": "Unknown", "next_target": None, "next_label": "?"}

    # Use most recent valid wave if available, else last
    valid = [w for w in waves if w["valid"]]
    ref = valid[-1] if valid else waves[-1]

    w5_end = ref["w5_end"]
    w3_end = ref["w3_end"]
    w1_start = ref["w1_start"]

    if current_price >= w5_end * 0.98:
        return {
            "position":   "Post-W5 (potential correction)",
            "next_label": "A-B-C Correction",
            "next_target": round(w3_end * 0.618 + w1_start * 0.382, 2),
        }
    elif current_price >= w3_end * 0.98:
        return {
            "position":   "W4–W5 Zone",
            "next_label": "W5",
            "next_target": round(w5_end, 2),
        }
    elif current_price >= ref["w2_end"]:
        return {
            "position":   "W3–W4 Zone",
            "next_label": "W4",
            "next_target": round(ref["w4_end"], 2),
        }
    else:
        return {
            "position":   "W1–W2 Zone (early impulse)",
            "next_label": "W3",
            "next_target": round(w3_end, 2),
        }


# ── Full pipeline ─────────────────────────────────────────────────────────────

def elliott_score_for_ticker(df: "pd.DataFrame") -> dict:
    """
    Full Elliott Wave pipeline for a ticker's OHLCV DataFrame.
    Returns detection results + Fibonacci levels + wave targets.
    """
    if df is None or df.empty or len(df) < 20:
        return {"detected": False, "count": 0, "waves": [], "fib": {}, "targets": {}}

    prices = df["Close"].tolist()
    pivots = find_zigzag_pivots(prices, deviation_pct=2.0)

    if len(pivots) < 6:
        return {
            "detected": False,
            "count": 0,
            "pivots_count": len(pivots),
            "waves": [],
            "fib": {},
            "targets": {},
            "corrections": [],
        }

    waves = detect_impulse_waves(pivots)
    corrections = detect_corrective_waves(pivots)

    # Fibonacci from last 6 pivots swing range
    recent = pivots[-6:]
    swing_low  = min(p["price"] for p in recent)
    swing_high = max(p["price"] for p in recent)
    fibs = fib_levels(swing_low, swing_high)

    # Wave targets from first valid impulse's W1
    targets = {}
    valid_waves = [w for w in waves if w["valid"]]
    if valid_waves:
        w = valid_waves[0]
        targets = wave_targets(w["w1_start"], w["w1_end"])

    # Current wave position
    current_price = prices[-1]
    position = current_wave_position(waves, current_price) if waves else {}

    return {
        "detected":      len(waves) > 0,
        "count":         len(waves),
        "valid_count":   len(valid_waves),
        "pivots_count":  len(pivots),
        "waves":         waves[:5],
        "corrections":   corrections[:3],
        "fib":           fibs,
        "targets":       targets,
        "swing_low":     swing_low,
        "swing_high":    swing_high,
        "current_price": current_price,
        "position":      position,
        "dates":         [str(d)[:10] for d in df.index.tolist()],
        "closes":        prices,
    }
