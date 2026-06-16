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
    
    def to_float(v) -> float:
        if v is None:
            return 50.0
        if isinstance(v, (list, tuple)):
            if len(v) > 0:
                return to_float(v[0])
            return 50.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 50.0

    for key, w in weights.items():
        val = to_float(signals.get(key, 50.0))
        breakdown[key] = val
        total += val * float(w)
        used_weight += float(w)
    score = round(total / used_weight, 1) if used_weight > 0 else 50.0

    if score >= 85:   tier = "🟢 SANGAT DIREKOMENDASIKAN"
    elif score >= 70: tier = "🔵 DIREKOMENDASIKAN"
    elif score >= 50: tier = "🟡 NETRAL / WATCHLIST"
    else:             tier = "🔴 HINDARI"

    return {"score": score, "tier": tier, "breakdown": breakdown, "horizon": horizon}
