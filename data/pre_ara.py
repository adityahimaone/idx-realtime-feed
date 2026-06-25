"""
Pre-ARA Momentum — Early Buy Signal detection.
IDX 2024 ARA rules:
  < 200      → +35%
  200–5.000  → +25%
  ≥ 5.000    → +20%
ARB: −7% semua tier (Papan Utama & Pengembangan).
"""
import math
import time
import yfinance as yf
from data.fetchers import safe_float

# Cache dictionary to prevent redundant yfinance API calls during live feeds
_streak_cache = {}
CACHE_TTL_SEC = 900  # Cache duration of 15 minutes


def get_tick_size(price: float) -> int:
    """IDX tick size by price tier."""
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


def round_to_tick(price: float) -> float:
    """Round price to nearest IDX tick."""
    tick = get_tick_size(price)
    return round(price / tick) * tick


def get_ara_limit(price: float) -> float:
    """
    IDX 2024 ARA limit % by price (using prev_close tier).
    Papan Utama & Papan Pengembangan.
    """
    if price <= 0:
        return 0.0
    if price < 200:
        return 35.0
    elif price < 5000:
        return 25.0
    else:
        return 20.0


def get_arb_limit(price: float) -> float:
    """ARB limit % — flat 7% across all tiers."""
    if price <= 0:
        return 0.0
    return -7.0


def get_ara_price(prev_close: float) -> float:
    """Calculate ARA price from prev_close, with tick rounding."""
    limit_pct = get_ara_limit(prev_close)
    return round_to_tick(prev_close * (1 + limit_pct / 100.0))


def get_arb_price(prev_close: float) -> float:
    """Calculate ARB price from prev_close."""
    limit_pct = get_arb_limit(prev_close)
    return round_to_tick(prev_close * (1 + limit_pct / 100.0))


def ara_distance(last: float, ara_price: float) -> float:
    """
    % distance from current price to ARA price.
    0% = already at ARA.
    """
    if ara_price <= 0:
        return 0.0
    return round((ara_price - last) / ara_price * 100, 2)


def ara_proximity_score(last: float, prev_close: float, ara_price: float) -> float:
    """
    Score 0–100: how close price is to ARA relative to total ARA range.
    100 = already at ARA, 0 = still at prev_close.

    Formula:
      progress = (Last - PrevClose) / (ARA - PrevClose)
      Score = progress * 100
    """
    total_range = ara_price - prev_close
    if total_range <= 0:
        return 0.0
    progress = (last - prev_close) / total_range
    return round(min(max(progress, 0), 1) * 100, 1)


def detect_ara_streak(symbol: str, days: int = 5) -> dict:
    """
    Check consecutive ARA days using yfinance historical data.
    Returns streak count and riding flag.
    Cached for 15 minutes to maximize live execution speed.
    """
    now = time.time()
    cache_key = (symbol, days)
    if cache_key in _streak_cache:
        cached_res, expiry = _streak_cache[cache_key]
        if now < expiry:
            return cached_res

    try:
        ticker = yf.Ticker(f"{symbol}.JK")
        hist = ticker.history(period=f"{days + 2}d", interval="1d")
    except Exception:
        # Cache errors for a shorter period (5 minutes) to avoid continuous failure loops
        res = {"streak": 0, "consecutive_ara": False, "is_riding": False}
        _streak_cache[cache_key] = (res, now + 300)
        return res

    if hist.empty or len(hist) < 2:
        res = {"streak": 0, "consecutive_ara": False, "is_riding": False}
        _streak_cache[cache_key] = (res, now + 300)
        return res

    streak = 0
    closes = hist["Close"].values

    for i in range(len(closes) - 1, 0, -1):
        current = closes[i]
        prev = closes[i - 1]
        if prev <= 0:
            break
        pct_change = (current - prev) / prev * 100
        ara_pct = get_ara_limit(prev)

        # Within 0.5% of ARA = considered ARA that day
        if pct_change >= ara_pct - 0.5:
            streak += 1
        else:
            break

    res = {
        "streak": streak,
        "consecutive_ara": streak >= 1,
        "is_riding": streak >= 2,
    }
    _streak_cache[cache_key] = (res, now + CACHE_TTL_SEC)
    return res


def momentum_acceleration(df_5m) -> dict:
    """
    Compare momentum 30min ago vs now.
    df_5m: pd.DataFrame with 'Close' column, 5-min candles.
    Returns accelerating flag and delta.
    """
    if df_5m is None:
        return {"accelerating": False, "pcm_now": 0.0, "pcm_prev": 0.0}

    try:
        n = len(df_5m)
        if n < 12:
            return {"accelerating": False, "pcm_now": 0.0, "pcm_prev": 0.0}

        now_window = df_5m.iloc[-6:]   # last 30 min
        prev_window = df_5m.iloc[-12:-6]  # 30 min before that

        def mom(w):
            if len(w) < 2:
                return 0.0
            return (w["Close"].iloc[-1] - w["Close"].iloc[0]) / w["Close"].iloc[0] * 100

        pcm_now = mom(now_window)
        pcm_prev = mom(prev_window)

        return {
            "pcm_now": round(pcm_now, 2),
            "pcm_prev": round(pcm_prev, 2),
            "accelerating": pcm_now > pcm_prev and pcm_now > 0,
            "delta": round(pcm_now - pcm_prev, 2),
        }
    except Exception:
        return {"accelerating": False, "pcm_now": 0.0, "pcm_prev": 0.0}


def pre_ara_score(sig: dict) -> float:
    """
    Pre-ARA Momentum Score 0–100.

    Plan's composite formula:
    - Proximity   (30%): seberapa dekat ke ARA (progress from prev_close)
    - VSR Extreme (25%): volume surge ratio, cap at 15x
    - ARA Streak  (20%): consecutive ARA days, cap at 5
    - Momentum Accel (15%): momentum sedang naik
    - CPR (10%): Close Position in Range — tutup dekat high

    sig keys required:
      price, prev_close, ara_price, vsr, streak, accelerating, cpr
    """
    price = safe_float(sig.get("price", 0))
    prev_close = safe_float(sig.get("prev_close", 0))
    ara_price = safe_float(sig.get("ara_price", 0))
    vsr = safe_float(sig.get("vsr", 0))
    streak = int(sig.get("streak", 0))
    accelerating = bool(sig.get("accelerating", False))
    cpr_val = safe_float(sig.get("cpr", 50))

    if price <= 0 or prev_close <= 0 or ara_price <= 0:
        return 0.0

    proximity = ara_proximity_score(price, prev_close, ara_price)

    # Pre-filter: must be within 40% of ARA range AND VSR ≥ 3
    if proximity < 40:
        return 0.0
    if vsr < 3:
        return 0.0

    # Normalize components
    prox_norm = proximity / 100.0
    vsr_norm = min(vsr / 15.0, 1.0)
    streak_norm = min(streak / 5.0, 1.0)
    accel_norm = 1.0 if accelerating else 0.3
    cpr_norm = min(max(cpr_val - 50, 0) / 50.0, 1.0)  # only value ≥ 50% gets score

    raw = (
        prox_norm * 0.30 +
        vsr_norm * 0.25 +
        streak_norm * 0.20 +
        accel_norm * 0.15 +
        cpr_norm * 0.10
    )
    return round(raw * 100, 1)


def classify_pre_ara(score: float, proximity: float = 0) -> str:
    """
    Tier label based on score + proximity.
    proximity param overrides score if at ARA.
    """
    if proximity >= 95:
        return "🚨 AT ARA"
    if score >= 70:
        return "🔴 Imminent ARA"
    if score >= 50:
        return "🟠 Pre-ARA Entry"
    if score >= 30:
        return "🟡 Approaching"
    return "⚪ Watch"


# Entry strategies lookup
PRE_ARA_ENTRY = {
    "aggressive": {
        "proximity_range": (50, 70),
        "min_vsr": 5,
        "min_streak": 0,
        "note": "Entry awal — high reward, high risk. SL -3% dari entry.",
    },
    "moderate": {
        "proximity_range": (70, 90),
        "min_vsr": 4,
        "min_streak": 1,
        "note": "Entry terkonfirmasi. SL -2%, TP = ARA price.",
    },
    "conservative": {
        "proximity_range": (95, 100),
        "min_vsr": 3,
        "min_streak": 2,
        "note": "Riding ARA streak. Beli H+1 open, SL = yesterday close.",
    },
}
