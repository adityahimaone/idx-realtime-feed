"""Composite Mega Score — gabungkan semua sinyal jadi satu ranking per horizon."""

HORIZON_WEIGHTS = {
    "scalping": {"intraday_score": 0.30, "orderbook_score": 0.30,
                 "trending_score": 0.20, "pre_ara_score": 0.20},
    "swing_bsjp": {"intraday_score": 0.25, "bsjp_score": 0.35,
                   "news_sentiment_score": 0.20, "trending_score": 0.20},
    "long_term": {"minervini_score": 0.40, "hist_score": 0.30,
                  "news_sentiment_score": 0.15, "macro_score": 0.15},
}


def compute_mega_score(signals: dict, horizon: str) -> dict:
    weights = HORIZON_WEIGHTS.get(horizon, HORIZON_WEIGHTS["scalping"])
    total, used_weight, breakdown = 0.0, 0.0, {}
    available, defaulted = {}, []

    def to_float(v):
        """Return float or None when the signal is genuinely unavailable."""
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            if len(v) > 0:
                return to_float(v[0])
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    for key, w in weights.items():
        val = to_float(signals.get(key))
        if val is None:
            available[key] = False
            defaulted.append(key)
            val = 50.0
        else:
            available[key] = True
        breakdown[key] = val
        total += val * float(w)
        used_weight += float(w)
    score = round(total / used_weight, 1) if used_weight > 0 else 50.0

    present_weight = sum(float(w) for key, w in weights.items() if available.get(key))
    total_weight = sum(float(w) for w in weights.values())
    confidence = round(present_weight / total_weight, 3) if total_weight > 0 else 0.0

    if score >= 85:   tier = "🟢 SANGAT DIREKOMENDASIKAN"
    elif score >= 70: tier = "🔵 DIREKOMENDASIKAN"
    elif score >= 50: tier = "🟡 NETRAL / WATCHLIST"
    else:             tier = "🔴 HINDARI"

    return {
        "score": score,
        "tier": tier,
        "breakdown": breakdown,
        "horizon": horizon,
        "available": available,
        "defaulted": defaulted,
        "confidence": confidence,
    }
