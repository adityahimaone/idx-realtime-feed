"""Tests for the Exodus trade-book parser, profile, and Engine D overlay."""
from data.tradebook import (
    TradeBookData,
    TradeBookSeries,
    adjust_tiers_with_tradebook,
    parse_tradebook,
    tradebook_profile,
)


def _val(raw):
    return {"raw": str(raw), "formatted": str(raw)}


def _minute_items(minutes, start_lot=100, start_value=1_000_000):
    """Generate cumulative buy/sell-style minute items."""
    items = []
    lot = start_lot
    value = start_value
    for i, m in enumerate(minutes):
        lot += i + 1
        value += (i + 1) * 100_000
        items.append({
            "time": m,
            "frequency": _val((i + 1) * 10),
            "lot": _val(lot),
            "value": _val(value),
        })
    return items


def _series_payload(minutes):
    times = [f"09:{m:02d}" for m in range(minutes)]
    buy = _minute_items(times, start_lot=1000, start_value=10_000_000)
    sell = _minute_items(times, start_lot=800, start_value=8_000_000)
    net = [{"time": t, "value": _val(200_000 * (i + 1))} for i, t in enumerate(times)]
    big_net = [
        {"time": t, "value": _val(100_000 * (i + 1))}
        for i, t in enumerate(times)
    ]
    return {
        "message": "ok",
        "data": {
            "date": "2026-08-06",
            "buy": buy,
            "sell": sell,
            "prices": [
                {"time": t, "value": _val(1200 + i)} for i, t in enumerate(times)
            ],
            "net_values": net,
            "big_money_net_values": big_net,
            "book_total": {
                "buy_percentage": 58.0,
                "sell_percentage": 42.0,
                "buy_lot": 100000,
                "sell_lot": 80000,
                "big_money_buy_percentage": 55.0,
                "big_money_sell_percentage": 45.0,
            },
        },
    }


def _custom_big_net_payload(big_values):
    """Series payload with a custom big-money net series."""
    times = [f"09:{m:02d}" for m in range(len(big_values))]
    buy = _minute_items(times, start_lot=1000, start_value=10_000_000)
    sell = _minute_items(times, start_lot=800, start_value=8_000_000)
    net = [{"time": t, "value": _val(200_000 * (i + 1))} for i, t in enumerate(times)]
    return {
        "message": "ok",
        "data": {
            "date": "2026-08-06",
            "buy": buy,
            "sell": sell,
            "prices": [
                {"time": t, "value": _val(1200 + i)} for i, t in enumerate(times)
            ],
            "net_values": net,
            "big_money_net_values": [
                {"time": t, "value": _val(v)} for t, v in zip(times, big_values)
            ],
            "book_total": {
                "buy_percentage": 58.0,
                "sell_percentage": 42.0,
                "buy_lot": 100000,
                "sell_lot": 80000,
                "big_money_buy_percentage": 55.0,
                "big_money_sell_percentage": 45.0,
            },
        },
    }


def _tier_strategies():
    return {
        "engine_label": "Wall Gravity (Engine A)",
        "Aggressive": {"entry": 1200.0, "sl": 1170.0, "tp": 1280.0, "rr": 4.0, "valid": True},
        "Moderat": {"entry": 1190.0, "sl": 1165.0, "tp": 1240.0, "rr": 2.5, "valid": True},
        "Low Risk": {"entry": 1180.0, "sl": 1150.0, "tp": 1220.0, "rr": 2.0, "valid": True},
    }


def test_parse_defaults_and_series():
    payload = _series_payload(3)
    tb = parse_tradebook("arci", payload)
    assert tb is not None
    assert tb.symbol == "ARCI"
    assert tb.date == "2026-08-06"
    assert tb.series.times == ["09:00", "09:01", "09:02"]
    assert len(tb.series.buy_lots) == 3
    assert tb.series.prices == [1200.0, 1201.0, 1202.0]
    assert tb.buy_lot_pct == 58.0
    assert tb.sell_lot_pct == 42.0
    assert tb.buy_lot == 100000
    assert tb.sell_lot == 80000
    assert abs(tb.imbalance - 1.25) < 1e-9
    assert tb.big_money_buy_pct == 55.0
    assert tb.big_money_sell_pct == 45.0


def test_parse_aligns_series_by_time():
    payload = _series_payload(3)
    data = payload["data"]
    # Prices missing 09:01; net_values have an extra 09:03 minute.
    data["prices"] = [
        {"time": "09:00", "value": _val(100)},
        {"time": "09:02", "value": _val(102)},
    ]
    data["net_values"] = data["net_values"] + [
        {"time": "09:03", "value": _val(999)}
    ]
    tb = parse_tradebook("ARCI", payload)
    assert tb.series.prices == [100.0, 0.0, 102.0]
    assert tb.series.net_values == [200000.0, 400000.0, 600000.0]
    assert tb.series.big_money_net_values == [100000.0, 200000.0, 300000.0]


def test_parse_rejects_bad_payload():
    assert parse_tradebook("ARCI", None) is None
    assert parse_tradebook("ARCI", {"data": None}) is None
    assert parse_tradebook("ARCI", {"data": {}}) is not None


def test_profile_math():
    tb = parse_tradebook("ARCI", _series_payload(20))
    profile = tradebook_profile(tb)
    assert profile["imbalance"] == 1.25
    assert profile["buy_lot_pct"] == 58.0
    assert profile["net_positive_ratio"] == 1.0
    assert profile["net_flow_sum"] == sum(200_000 * (i + 1) for i in range(20))
    assert profile["big_money_trend"] == "accumulating"
    assert profile["momentum"] == "accelerating"
    assert profile["minutes"] == 20


def test_profile_momentum_windows_disjoint():
    # n=3 → k=1: compare first vs last minute only.
    profile = tradebook_profile(parse_tradebook("ARCI", _series_payload(3)))
    assert profile["k"] == 1
    assert profile["first_k_net_avg"] == 200_000.0
    assert profile["last_k_net_avg"] == 600_000.0
    assert profile["momentum"] == "accelerating"

    # n=20 → k=6: first six vs last six minutes (never overlapping).
    profile = tradebook_profile(parse_tradebook("ARCI", _series_payload(20)))
    assert profile["k"] == 6
    net = [200_000 * (i + 1) for i in range(20)]
    assert profile["first_k_net_avg"] == sum(net[:6]) / 6
    assert profile["last_k_net_avg"] == sum(net[-6:]) / 6


def test_profile_big_money_threshold_ratio_not_sign():
    # Positive but tiny big-money net (< 5% of total value) → neutral, not
    # "accumulating" (previously any positive sign triggered accumulation).
    tb = parse_tradebook("ARCI", _custom_big_net_payload([100_000, 200_000]))
    profile = tradebook_profile(tb)
    assert profile["big_money_net_sum"] > 0
    assert profile["big_money_trend"] == "neutral"
    assert abs(profile["big_money_ratio"]) < 0.05

    # Dominant positive ratio → accumulating.
    tb = parse_tradebook("ARCI", _series_payload(20))
    profile = tradebook_profile(tb)
    assert profile["big_money_ratio"] > 0.05
    assert profile["big_money_trend"] == "accumulating"


def test_profile_vwap_exact_and_zero_guard():
    tb = parse_tradebook("ARCI", _series_payload(20))
    profile = tradebook_profile(tb)
    # Cumulative buy value 31,000,000 / sell 29,000,000; lots 1210 + 1010.
    assert profile["vwap"] is not None
    assert abs(profile["vwap"] - 60_000_000 / (2220 * 100)) < 1e-9

    empty = TradeBookData(
        symbol="ARCI",
        date="2026-08-06",
        series=TradeBookSeries(
            times=["09:00"],
            buy_lots=[0.0],
            sell_lots=[0.0],
            buy_values=[0.0],
            sell_values=[0.0],
            prices=[1200.0],
            net_values=[0.0],
            big_money_net_values=[0.0],
        ),
    )
    assert tradebook_profile(empty)["vwap"] is None


def test_adjust_big_money_sell_disables_aggressive():
    strategies = _tier_strategies()
    profile = {
        "big_money_sell_pct": 60.0,
        "big_money_buy_pct": 40.0,
        "big_money_trend": "distributing",
        "imbalance": 1.0,
        "net_flow_sum": 1_000_000.0,
        "net_flow_latest": 10_000.0,
        "net_positive_ratio": 0.6,
        "momentum": "neutral",
        "minutes": 5,
    }
    out = adjust_tiers_with_tradebook(strategies, profile)
    agg = out["Aggressive"]
    assert agg["entry"] is None
    assert agg["sl"] is None
    assert agg["tp"] is None
    assert agg["valid"] is False
    assert "Aggressive disabled" in agg["warning"]
    assert "Big money sell" in out["tier_warnings"]["Aggressive"]
    # SLs on the remaining tiers are widened.
    assert out["Moderat"]["sl"] < strategies["Moderat"]["sl"]
    assert out["Low Risk"]["sl"] < strategies["Low Risk"]["sl"]
    assert any("SL Moderat dilebarkan" in n for n in out["notes"])
    assert any("SL Low Risk dilebarkan" in n for n in out["notes"])


def test_adjust_big_money_buy_tightens():
    strategies = _tier_strategies()
    profile = {
        "big_money_buy_pct": 60.0,
        "big_money_sell_pct": 40.0,
        "big_money_trend": "accumulating",
        "imbalance": 1.4,
        "net_flow_sum": 2_000_000.0,
        "net_flow_latest": 20_000.0,
        "net_positive_ratio": 0.7,
        "momentum": "neutral",
        "minutes": 5,
    }
    out = adjust_tiers_with_tradebook(strategies, profile)
    assert out["Aggressive"]["entry"] == 1200.0
    assert out["Aggressive"]["sl"] > strategies["Aggressive"]["sl"]
    assert out["Moderat"]["sl"] > strategies["Moderat"]["sl"]
    assert out["Low Risk"]["sl"] > strategies["Low Risk"]["sl"]
    assert any("dirapatkan" in n for n in out["notes"])


def test_adjust_sell_dominant_book_warns():
    strategies = _tier_strategies()
    profile = {
        "big_money_buy_pct": 45.0,
        "big_money_sell_pct": 45.0,
        "big_money_trend": "neutral",
        "imbalance": 0.7,
        "net_flow_sum": -500_000.0,
        "net_flow_latest": -5_000.0,
        "net_positive_ratio": 0.3,
        "momentum": "decelerating",
        "minutes": 5,
    }
    out = adjust_tiers_with_tradebook(strategies, profile)
    assert "Book sell-dominant" in out["tier_warnings"]["Aggressive"]
    assert "Imbalance" in out["Aggressive"]["warning"]
    assert out["Moderat"]["sl"] < strategies["Moderat"]["sl"]
    assert any("sell-dominant" in n for n in out["notes"])
    # Original input dict is not mutated.
    assert strategies["Aggressive"]["entry"] == 1200.0


def test_adjust_cumulative_sl_widen_capped_and_combined_note():
    # Rule 1 (big-money sell ≥55%) + rule 4 (imbalance <0.85) both request SL
    # widening → applied once at min(0.15 + 0.10, MAX_SL_WIDEN_PCT = 0.25),
    # never compound-multiplied (sequential 1.15 × 1.10 → 26.5%).
    strategies = _tier_strategies()
    profile = {
        "big_money_sell_pct": 60.0,
        "big_money_buy_pct": 40.0,
        "big_money_trend": "distributing",
        "imbalance": 0.7,
        "net_flow_sum": -500_000.0,
        "net_flow_latest": -5_000.0,
        "net_positive_ratio": 0.3,
        "momentum": "decelerating",
        "minutes": 5,
    }
    out = adjust_tiers_with_tradebook(strategies, profile)

    combined = next(n for n in out["notes"] if "SL Moderat dilebarkan" in n)
    assert "25%" in combined
    assert "sell pressure" in combined and "thin book" in combined

    # Moderat: entry 1190, sl 1165 (dist 25) → 25% widen = 1160 after tick
    # alignment. Sequential compounding would land at 1155, so this also proves
    # the cumulative cap was applied instead of chained multiplication.
    assert out["Moderat"]["sl"] == 1160
    assert out["Moderat"]["sl"] > 1155
