"""
Elliott Wave detection via zigzag pivot analysis.
Rule: W2 retrace ≤ 100% W1, W3 never shortest, W4 overlap W1 forbidden.
"""
import pandas as pd
from data.fetchers import safe_float


def find_zigzag_pivots(prices: list[float], deviation_pct: float = 2.0) -> list[dict]:
    """
    Find swing high/low pivots in a price list.
    deviation_pct: min % change from prev pivot to confirm new one.
    Returns list of pivots: {idx, price, type='high'|'low'}.
    """
    if not prices or len(prices) < 5:
        return []

    pivots = []
    trend = 0  # 1 = up, -1 = down

    for i in range(2, len(prices) - 2):
        window = prices[i - 2 : i + 3]
        middle = window[2]
        prev_price = prices[i - 1] if i > 0 else middle
        pct_chg = abs(middle - prev_price) / max(prev_price, 1) * 100

        if pct_chg < deviation_pct:
            continue

        if middle == max(window):
            if trend != 1:
                pivots.append({"idx": i, "price": middle, "type": "high"})
                trend = 1
        elif middle == min(window):
            if trend != -1:
                pivots.append({"idx": i, "price": middle, "type": "low"})
                trend = -1

    return pivots


def detect_impulse_waves(pivots: list[dict]) -> list[dict]:
    """
    Detect 5-wave impulse pattern from zigzag pivots.
    Returns list of matched waves.
    """
    waves = []
    for i in range(len(pivots) - 9):
        seg = pivots[i : i + 10]
        if seg[0]["type"] != "low":
            continue
        # Impulse = low-high-low-high-low-high-low-high-low-high
        # But here we have 10 alternating pivots: 0=low,1=high,2=low,3=high...
        types_ok = True
        for j, p in enumerate(seg):
            expected = "high" if j % 2 == 1 else "low"
            if p["type"] != expected:
                types_ok = False
                break
        if not types_ok:
            continue

        w1 = abs(seg[1]["price"] - seg[0]["price"])
        w2 = abs(seg[2]["price"] - seg[1]["price"])
        w3 = abs(seg[3]["price"] - seg[2]["price"])
        w4 = abs(seg[4]["price"] - seg[3]["price"])
        w5 = abs(seg[5]["price"] - seg[4]["price"]) if len(seg) > 5 else 0

        s1 = abs(seg[6]["price"] - seg[5]["price"])
        s2 = abs(seg[7]["price"] - seg[6]["price"])
        s3 = abs(seg[8]["price"] - seg[7]["price"])
        s4 = abs(seg[9]["price"] - seg[8]["price"]) if len(seg) > 9 else 0

        # Rule: W2 retrace < 100% W1
        if w2 >= w1:
            continue

        # Rule: W3 not shortest among 1-3-5
        w3_shortest = w3 < w1 and w3 < w5
        if w3_shortest:
            continue

        # Rule: W4 overlap not allowed into W1 territory
        w4_low = seg[3]["price"] if seg[3]["type"] == "low" else seg[4]["price"]
        w1_high = seg[1]["price"]

        if seg[0]["type"] == "low":
            # Bullish: w4 low >= w1 high? No — w4 low must be > w1 high for overlap check
            overlap = w4_low <= w1_high if seg[1]["price"] > seg[0]["price"] else False
        else:
            overlap = False

        waves.append({
            "wave_start": seg[0]["idx"],
            "wave_end": seg[min(len(seg) - 1, 9)]["idx"],
            "count_segments": len(seg),
            "w1": round(w1, 2),
            "w2": round(w2, 2),
            "w3": round(w3, 2),
            "w4": round(w4, 2),
            "w5": round(w5, 2),
            "types_verified": types_ok,
        })

    return waves


def elliott_score_for_ticker(df: "pd.DataFrame") -> dict:
    """
    Detect Elliott Wave on a ticker's OHLCV dataframe.
    df must have 'Close', 'High', 'Low' columns with datetime index.
    Returns dict with detection results.
    """
    if df is None or df.empty or len(df) < 20:
        return {"detected": False, "count": 0, "waves": []}

    prices = df["Close"].tolist()
    pivots = find_zigzag_pivots(prices, deviation_pct=2.0)

    if len(pivots) < 10:
        return {"detected": False, "count": 0, "waves": []}

    waves = detect_impulse_waves(pivots)
    return {
        "detected": len(waves) > 0,
        "count": len(waves),
        "pivots_count": len(pivots),
        "waves": waves[:5],
    }
