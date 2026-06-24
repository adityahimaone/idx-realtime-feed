import pytest
from data.orderbook_wall import (
    OrderbookLevel,
    grounded_three_tier_A,
    grounded_three_tier_B,
    grounded_three_tier_C,
)

def test_engines():
    # Setup mock orderbook levels
    bid_levels = [
        OrderbookLevel(price=1970, lot=1000, freq=5),
        OrderbookLevel(price=1965, lot=2000, freq=10),
        OrderbookLevel(price=1950, lot=73000, freq=50),  # Strong wall
        OrderbookLevel(price=1940, lot=1500, freq=8),
    ]
    ask_levels = [
        OrderbookLevel(price=1980, lot=1200, freq=6),
        OrderbookLevel(price=1990, lot=2500, freq=12),
        OrderbookLevel(price=2005, lot=3000, freq=15),
    ]

    last_price = 1975.0
    open_price = 2030.0
    high_price = 2060.0
    low_price = 1970.0

    # Test Engine A
    res_a = grounded_three_tier_A(
        last_price=last_price,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
    )
    assert res_a["engine_label"] == "Wall Gravity (Engine A)"
    for tier in ["Aggressive", "Moderat", "Low Risk"]:
        assert tier in res_a
        assert "entry" in res_a[tier]
        assert "sl" in res_a[tier]
        assert "tp" in res_a[tier]

    # Test Engine B
    res_b = grounded_three_tier_B(
        last_price=last_price,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        total_bid_lot=77500,
        total_ask_lot=6700,
        avg_price=2009.0,
        open_price=open_price,
    )
    assert res_b["engine_label"] == "Contextual Alpha (Engine B)"
    assert "sentiment_factor" in res_b
    assert "depth_config" in res_b
    for tier in ["Aggressive", "Moderat", "Low Risk"]:
        assert tier in res_b

    # Test Engine C
    res_c = grounded_three_tier_C(
        last_price=last_price,
        high_price=high_price,
        low_price=low_price,
        open_price=open_price,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
    )
    assert res_c["engine_label"] == "Fibonacci + Wall Confirmation (Engine C)"
    assert "extension_mode" in res_c
    assert "fib_levels" in res_c
    for tier in ["Aggressive", "Moderat", "Low Risk"]:
        assert tier in res_c
