from data.fetchers import safe_float

def get_ara_limit(price: float) -> float:
    """Return IDX auto-rejection atas % by price tier."""
    if price <= 0:
        return 0.0
    if price < 200:
        return 35.0
    if price < 500:
        return 25.0
    if price < 2000:
        return 20.0
    if price < 5000:
        return 15.0
    return 10.0

def get_ara_price(price: float) -> float:
    """Return ARA price level for a given current price."""
    limit_pct = get_ara_limit(price)
    return round(price * (1 + limit_pct / 100.0), 2)

def pre_ara_score(sig: dict) -> float:
    """
    Pre-ARA Momentum score.
    Inputs:
      price, ara_price, ara_limit_pct, change_pct, volume, avg_volume, frequency, avg_frequency, value
    """
    price = safe_float(sig.get("price", 0))
    ara_price = safe_float(sig.get("ara_price", 0))
    ara_limit_pct = safe_float(sig.get("ara_limit_pct", 0))
    change_pct = safe_float(sig.get("change_pct", 0))
    volume = safe_float(sig.get("volume", 0))
    avg_volume = safe_float(sig.get("avg_volume", 1))
    frequency = safe_float(sig.get("frequency", 0))
    avg_frequency = safe_float(sig.get("avg_frequency", 1))
    value = safe_float(sig.get("value", 0))

    if price <= 0 or ara_price <= 0 or ara_limit_pct <= 0:
        return 0.0

    proximity = min((price / ara_price) * 100, 100)
    momentum = min(max(change_pct, 0.0), 35.0)
    volume_surge = min((volume / avg_volume) if avg_volume > 0 else 1.0, 10.0)
    frequency_surge = min((frequency / avg_frequency) if avg_frequency > 0 else 1.0, 10.0)

    score = (
        proximity * 0.35 +
        momentum * 0.25 +
        volume_surge * 10.0 * 0.20 +
        frequency_surge * 10.0 * 0.15 +
        min(value / 1_000_000_000.0, 1.0) * 5.0
    )
    return round(min(score, 100.0), 1)

def classify_pre_ara(score: float) -> str:
    if score >= 80:
        return "⚡ Pre-ARA Watch"
    if score >= 60:
        return "🔥 Momentum"
    if score >= 40:
        return "👁️ Monitor"
    return "—"
