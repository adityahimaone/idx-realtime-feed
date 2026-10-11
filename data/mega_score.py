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


def news_sentiment_to_score(combined: float) -> float:
    """Map combined news sentiment (roughly -3..+3) to a 0-100 Mega Score input.

    Neutral sentiment maps to 50; each +1.0 of combined sentiment adds +20
    (capped at 100), each -1.0 subtracts 20 (floored at 0).
    """
    return round(min(max(50 + float(combined) * 20, 0), 100), 1)


def minervini_to_score(passed: bool, score_int: float) -> float:
    """Map the Minervini trend-template (0-10 conditions) to a 0-100 input.

    Passing the template (>=8/10) is treated as a full 100 (binary "Stage 2
    confirmed"). Failing stocks map *linearly* from their condition count so a
    7/10 no longer scores 87.5 (the old `score_int / 8 * 100` inflated every
    sub-8 result above its true quality — audit fix).
    """
    if passed:
        return 100.0
    return round(max(0.0, min(float(score_int), 10.0)) / 10.0 * 100.0, 1)


def build_mega_signals(entry: dict, lookups: dict) -> dict:
    """Assemble the per-horizon signal dict for one ticker.

    Signals that are genuinely absent for a ticker are passed as ``None``
    (never a silent 50 placeholder) so ``compute_mega_score`` reports them in
    ``defaulted`` and the confidence badge stays honest. ``compute_mega_score``
    still substitutes 50 for ``None`` internally, so the *score* is unchanged —
    only the availability/confidence reporting is corrected (audit fix).

    `entry` keys: Ticker, Intraday Score, hist_row_obj.
    `lookups` keys -> dict {ticker: value} that contain ONLY tickers with a
    real value: "bsjp", "minervini", "pre_ara", "trending", "news".
    """
    t = entry.get("Ticker")
    hist_row = entry.get("hist_row_obj") or {}

    def _look(key):
        return (lookups.get(key) or {}).get(t)

    hist_raw = hist_row.get("Score v2")
    hist_score = None if hist_raw in (None, "") else hist_raw

    intraday = entry.get("Intraday Score")
    news = _look("news")
    return {
        "intraday_score": intraday if intraday not in (None, "") else None,
        "hist_score": hist_score,
        "bsjp_score": _look("bsjp"),
        "minervini_score": _look("minervini"),
        "pre_ara_score": _look("pre_ara"),
        "trending_score": _look("trending"),
        "news_sentiment_score": news_sentiment_to_score(news) if news is not None else None,
    }
