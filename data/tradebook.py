"""Trade Book chart (Exodus) — parsing, momentum profile, and tier adjustments.

Feeds on the public chart endpoint:

    GET https://exodus.stockbit.com/order-trade/trade-book/chart
        ?symbol=ARCI&time_interval=1m&date=YYYY-MM-DD

The payload carries per-minute CUMULATIVE buy/sell lots & values, per-minute
prices, per-minute net values (buy − sell), a big-money net series, and a
`book_total` summary (buy/sell %, big-money %, pre/post). This module parses
that into a typed structure, derives a momentum profile, and re-calibrates the
Aggressive / Moderate / Low Risk tiers from the daily flow — the "Engine D"
overlay used by the Deep Dive tab.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.config import config
from data.fetchers import safe_float
from data.orderbook_wall import round_to_tick


# ─── Parsing helpers ─────────────────────────────────────────────────────────

def _num(v) -> float:
    """Accept {raw, formatted} dicts, numeric strings with commas/%, or numbers."""
    if isinstance(v, dict):
        return safe_float(v.get("raw") or v.get("formatted"))
    return safe_float(v)


def _deltas(cumulative: list[float]) -> list[float]:
    """Per-minute deltas from a cumulative series (first point = its own value)."""
    out: list[float] = []
    prev = 0.0
    for val in cumulative:
        out.append(val - prev)
        prev = val
    return out


# ─── Typed structures ────────────────────────────────────────────────────────

@dataclass
class TradeBookSeries:
    times: list[str]
    buy_lots: list[float]            # cumulative lot, per minute
    sell_lots: list[float]
    buy_values: list[float]          # cumulative value (Rp), per minute
    sell_values: list[float]
    prices: list[float]              # per-minute close
    net_values: list[float]          # per-minute net value (buy − sell)
    big_money_net_values: list[float]  # per-minute big-money net value

    def __bool__(self) -> bool:
        return len(self.times) > 0


@dataclass
class TradeBookData:
    symbol: str
    date: str
    series: TradeBookSeries | None
    book_total: dict = field(default_factory=dict)
    pre_post: dict | None = None
    raw: dict = field(default_factory=dict)

    # ── book_total convenience ────────────────────────────────────────────
    @property
    def buy_lot_pct(self) -> float:
        return safe_float(self.book_total.get("buy_percentage"), 50.0)

    @property
    def sell_lot_pct(self) -> float:
        return safe_float(self.book_total.get("sell_percentage"), 50.0)

    @property
    def buy_lot(self) -> float:
        return safe_float(self.book_total.get("buy_lot"))

    @property
    def sell_lot(self) -> float:
        return safe_float(self.book_total.get("sell_lot"))

    @property
    def imbalance(self) -> float:
        """Buy lot ÷ sell lot ratio (1.0 = balanced, >1 = buy-side dominant)."""
        return self.buy_lot / self.sell_lot if self.sell_lot > 0 else 1.0

    @property
    def big_money_buy_pct(self) -> float:
        return safe_float(self.book_total.get("big_money_buy_percentage"), 50.0)

    @property
    def big_money_sell_pct(self) -> float:
        return safe_float(self.book_total.get("big_money_sell_percentage"), 50.0)


def parse_tradebook(symbol: str, payload: dict) -> TradeBookData | None:
    """Parse the chart endpoint payload into a TradeBookData (or None)."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    buy_raw = data.get("buy") or []
    sell_raw = data.get("sell") or []
    times = [it.get("time", "") for it in buy_raw]
    buy_lots = [_num(it.get("lot")) for it in buy_raw]
    sell_lots = [_num(it.get("lot")) for it in sell_raw]
    buy_values = [_num(it.get("value")) for it in buy_raw]
    sell_values = [_num(it.get("value")) for it in sell_raw]

    series = None
    if times:
        # prices/net_values may be missing a leading/trailing minute — align by time
        def _align(key: str) -> list[float]:
            items = data.get(key) or []
            if not items:
                return [0.0] * len(times)
            by_time = {}
            for it in items:
                if isinstance(it, dict):
                    by_time[it.get("time", "")] = _num(it.get("value"))
            return [by_time.get(t, 0.0) for t in times]

        series = TradeBookSeries(
            times=times,
            buy_lots=buy_lots,
            sell_lots=sell_lots,
            buy_values=buy_values,
            sell_values=sell_values,
            prices=_align("prices"),
            net_values=_align("net_values"),
            big_money_net_values=_align("big_money_net_values"),
        )

    return TradeBookData(
        symbol=symbol.upper(),
        date=str(data.get("date") or ""),
        series=series,
        book_total=data.get("book_total") or {},
        pre_post=data.get("pre_post"),
        raw=data,
    )


# ─── Momentum profile ────────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def tradebook_profile(data: TradeBookData) -> dict:
    """Derive a compact momentum profile used by Engine D adjustments."""
    s = data.series
    if not s:
        return {}

    n = len(s.times)
    net = s.net_values
    big_net = s.big_money_net_values
    per_min_buy = _deltas(s.buy_values)
    per_min_sell = _deltas(s.sell_values)

    # Normalized big-money trend: ratio of big-money net to total traded value.
    total_value = (s.buy_values[-1] + s.sell_values[-1]) if s.buy_values else 0.0
    big_sum = sum(big_net)
    big_ratio = big_sum / total_value if total_value > 0 else 0.0
    if big_ratio > config.BIG_MONEY_TREND_RATIO:
        big_trend = "accumulating"
    elif big_ratio < -config.BIG_MONEY_TREND_RATIO:
        big_trend = "distributing"
    else:
        big_trend = "neutral"

    # Disjoint momentum windows: split the series into thirds and compare the
    # first vs last window (always disjoint for n ≥ 3).
    k = max(1, n // 3)
    first_k = _mean(net[:k])
    last_k = _mean(net[-k:])
    momentum = "accelerating" if last_k > first_k else "decelerating"

    total_lot = data.buy_lot + data.sell_lot
    gap_pct = ((data.buy_lot - data.sell_lot) / total_lot * 100) if total_lot > 0 else 0.0

    return {
        "imbalance": data.imbalance,
        "buy_lot_pct": data.buy_lot_pct,
        "sell_lot_pct": data.sell_lot_pct,
        "buy_lot": data.buy_lot,
        "sell_lot": data.sell_lot,
        "buy_sell_gap_pct": gap_pct,
        "big_money_buy_pct": data.big_money_buy_pct,
        "big_money_sell_pct": data.big_money_sell_pct,
        "big_money_trend": big_trend,
        "big_money_ratio": big_ratio,
        "net_flow_sum": sum(net),
        "net_flow_latest": net[-1] if net else 0.0,
        "net_positive_ratio": (sum(1 for v in net if v > 0) / n) if n else 0.0,
        "big_money_net_sum": big_sum,
        "big_money_positive_ratio": (sum(1 for v in big_net if v > 0) / n) if n else 0.0,
        "first_k_net_avg": first_k,
        "last_k_net_avg": last_k,
        "k": k,
        "momentum": momentum,
        "per_min_buy_avg": _mean(per_min_buy),
        "per_min_sell_avg": _mean(per_min_sell),
        "vwap": _vwap(s),
        "minutes": n,
    }


def _vwap(s: TradeBookSeries) -> float | None:
    """Volume-weighted average price from cumulative buy/sell totals (guard 0)."""
    if not s.buy_values or not s.sell_values:
        return None
    total_value = s.buy_values[-1] + s.sell_values[-1]
    total_shares = (s.buy_lots[-1] + s.sell_lots[-1]) * 100
    if total_shares <= 0:
        return None
    return total_value / total_shares


# ─── Engine D: adjust Aggressive / Moderate / Low Risk tiers ────────────────

_MIN_RR = {"Aggressive": 1.0, "Moderat": 1.5, "Low Risk": 2.0}


def _tier_recalc(tier: dict, tier_name: str) -> None:
    """Recompute R/R + validity after entry/sl/tp changes (tick-aligned)."""
    entry, sl, tp = tier.get("entry"), tier.get("sl"), tier.get("tp")
    if entry is None or sl is None or tp is None:
        return
    risk = entry - sl
    tier["rr"] = round((tp - entry) / risk, 2) if risk > 0 else 0.0
    tier["valid"] = tier["rr"] >= _MIN_RR.get(tier_name, 1.5)


def _widen_sl(tier: dict, pct: float) -> None:
    """Move the SL further from entry (more room) and re-validate."""
    entry, sl = tier.get("entry"), tier.get("sl")
    if entry is None or sl is None or entry <= sl:
        return
    new_sl = round_to_tick(entry - (entry - sl) * (1 + pct), entry)
    if new_sl < entry:
        tier["sl"] = new_sl
    _tier_recalc(tier, tier.get("_tier_name", ""))


def _tighten_sl(tier: dict, pct: float) -> None:
    """Move the SL closer to entry (tighter risk) and re-validate."""
    entry, sl = tier.get("entry"), tier.get("sl")
    if entry is None or sl is None or entry <= sl:
        return
    new_sl = round_to_tick(entry - (entry - sl) * (1 - pct), entry)
    if new_sl < entry:
        tier["sl"] = new_sl
    _tier_recalc(tier, tier.get("_tier_name", ""))


def _scale_tp(tier: dict, factor: float) -> None:
    """Pull the TP closer to entry (lower reward) and re-validate."""
    entry, tp = tier.get("entry"), tier.get("tp")
    if entry is None or tp is None or tp <= entry:
        return
    tier["tp"] = round_to_tick(entry + (tp - entry) * factor, entry)
    _tier_recalc(tier, tier.get("_tier_name", ""))


def adjust_tiers_with_tradebook(strategies: dict, profile: dict) -> dict:
    """Engine D overlay: re-calibrate the 3 tiers from the daily trade book.

    Returns a shallow copy of `strategies` with adjusted tier dicts plus
    `tradebook` (profile summary), `tier_warnings`, and `notes`.
    Rules:
      • Big money selling ≥55%  → disable Aggressive, widen SL on the rest.
      • Big money buying  ≥55%  → tighten SL (flow supports entries).
      • Net flow negative + big money sell → pull TPs closer.
      • Imbalance <0.85 (sell-dominant book) → widen SL, caution aggressive.
      • Imbalance ≥1.3 + big money buying → keep/tighten aggressive SL.
    SL widen requests are accumulated per tier and applied once, capped at
    MAX_SL_WIDEN_PCT (cumulative), with a combined reason in `notes`.
    """
    adjusted: dict = {}
    for key, val in strategies.items():
        adjusted[key] = dict(val) if isinstance(val, dict) else val

    for name in ("Aggressive", "Moderat", "Low Risk"):
        if name in adjusted and isinstance(adjusted[name], dict):
            adjusted[name]["_tier_name"] = name

    agg = adjusted.get("Aggressive", {})
    mod = adjusted.get("Moderat", {})
    low = adjusted.get("Low Risk", {})
    warnings: dict = {}
    notes: list[str] = []

    bm_sell = profile.get("big_money_sell_pct", 50.0)
    bm_buy = profile.get("big_money_buy_pct", 50.0)
    imb = profile.get("imbalance", 1.0)
    net_sum = profile.get("net_flow_sum", 0.0)
    bm_trend = profile.get("big_money_trend", "neutral")
    momentum = profile.get("momentum", "neutral")
    widen_requests: dict[str, list[tuple[str, float]]] = {}

    def _req_widen(tier_key: str, reason: str, pct: float) -> None:
        widen_requests.setdefault(tier_key, []).append((reason, pct))

    # 1) Big money distributing → aggressive off, roomier SLs.
    if bm_sell >= config.BIG_MONEY_DOMINANCE_PCT:
        if agg.get("entry") is not None:
            agg["entry"] = None
            agg["sl"] = None
            agg["tp"] = None
            agg["rr"] = 0.0
            agg["valid"] = False
            agg["warning"] = (
                f"⛔ Big money dominan jual ({bm_sell:.0f}% sell) — "
                "Aggressive disabled oleh Engine D."
            )
        warnings["Aggressive"] = (
            f"Big money sell {bm_sell:.0f}% — tunggu akumulasi sebelum entry agresif."
        )
        _req_widen("Moderat", "sell pressure", config.SL_WIDEN_BIG_MONEY)
        _req_widen("Low Risk", "sell pressure", config.SL_WIDEN_BIG_MONEY)
        notes.append(
            f"Big money sell {bm_sell:.0f}% → Aggressive disabled, "
            "SL Moderate/Low Risk diminta dilebarkan"
        )
    # 2) Big money accumulating → tighter risk.
    elif bm_buy >= config.BIG_MONEY_DOMINANCE_PCT:
        _tighten_sl(mod, config.SL_TIGHTEN_MID_LOW)
        _tighten_sl(low, config.SL_TIGHTEN_MID_LOW)
        if agg.get("entry") is not None:
            _tighten_sl(agg, config.SL_TIGHTEN_AGG)
        notes.append(
            f"Big money buy {bm_buy:.0f}% → SL Moderate/Low Risk "
            f"dirapatkan {config.SL_TIGHTEN_MID_LOW * 100:.0f}%"
        )

    # 3) Net flow negative with big money selling → lower targets.
    if net_sum < 0 and bm_sell >= config.NET_FLOW_SELL_PCT:
        _scale_tp(mod, config.TP_SCALE_DOWN)
        _scale_tp(low, config.TP_SCALE_DOWN)
        notes.append(
            "Net flow negatif → TP Moderate/Low Risk diturunkan "
            f"{round((1 - config.TP_SCALE_DOWN) * 100):.0f}%"
        )

    # 4) Sell-dominant book (imbalance < 0.85) → extra caution.
    if imb < config.BOOK_IMBALANCE_SELL:
        if agg.get("entry") is not None:
            agg["warning"] = (
                f"Imbalance bid/ask {imb:.2f}x (sell-dominant book) — "
                "risiko tinggi untuk breakout play."
            )
            warnings["Aggressive"] = warnings.get(
                "Aggressive", ""
            ) + f" Book sell-dominant ({imb:.2f}x)."
        _req_widen("Moderat", "thin book", config.SL_WIDEN_THIN_BOOK)
        _req_widen("Low Risk", "thin book", config.SL_WIDEN_THIN_BOOK)
        notes.append(
            f"Trade book sell-dominant ({imb:.2f}x) → "
            "SL Moderate/Low Risk diminta dilebarkan"
        )
    # 5) Strong buy-side book + accumulation → keep aggressive, tighten SL.
    elif imb >= config.BOOK_IMBALANCE_BUY and bm_buy >= config.NET_FLOW_SELL_PCT:
        if agg.get("entry") is not None:
            _tighten_sl(agg, config.SL_TIGHTEN_AGG)
        notes.append(
            f"Trade book buy-dominant ({imb:.2f}x) + big money buy → "
            f"SL Aggressive dirapatkan {config.SL_TIGHTEN_AGG * 100:.0f}%"
        )

    # Apply accumulated widen requests once per tier, capped at MAX_SL_WIDEN_PCT.
    for tier_key, reqs in widen_requests.items():
        total_pct = min(sum(p for _, p in reqs), config.MAX_SL_WIDEN_PCT)
        _widen_sl(adjusted.get(tier_key, {}), total_pct)
        reasons = " + ".join(dict.fromkeys(r for r, _ in reqs))
        notes.append(
            f"SL {tier_key} dilebarkan {total_pct * 100:.0f}%: {reasons}"
        )

    if bm_trend == "distributing":
        warnings.setdefault(
            "Low Risk",
            "Big money sedang distribusi — hindari average-down agresif.",
        )
    if momentum == "decelerating" and net_sum < 0:
        warnings.setdefault(
            "Moderat",
            "Momentum net flow melambat & negatif — tunggu stabilisasi.",
        )

    adjusted["Aggressive"] = agg
    adjusted["Moderat"] = mod
    adjusted["Low Risk"] = low
    adjusted["tradebook"] = {
        k: profile.get(k) for k in (
            "imbalance", "buy_lot_pct", "sell_lot_pct", "big_money_buy_pct",
            "big_money_sell_pct", "big_money_trend", "net_flow_sum",
            "net_flow_latest", "net_positive_ratio", "momentum", "minutes",
        )
    }
    adjusted["tier_warnings"] = warnings
    adjusted["notes"] = notes
    return adjusted
