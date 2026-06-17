import pytest
import math
from data.scoring import get_tick_size, align_price_to_tick, compute_action_recommendation

def test_get_tick_size():
    # Test boundary conditions for tick sizes
    assert get_tick_size(150) == 1
    assert get_tick_size(199) == 1
    assert get_tick_size(200) == 2
    assert get_tick_size(498) == 2
    assert get_tick_size(500) == 5
    assert get_tick_size(1995) == 5
    assert get_tick_size(2000) == 10
    assert get_tick_size(4990) == 10
    assert get_tick_size(5000) == 25
    assert get_tick_size(10000) == 25

def test_align_price_to_tick():
    # Test align nearest
    assert align_price_to_tick(199.4) == 199.0
    assert align_price_to_tick(199.6) == 200.0
    
    # Test align up
    assert align_price_to_tick(201, round_direction="up") == 202.0
    
    # Test align down
    assert align_price_to_tick(203, round_direction="down") == 202.0

def test_compute_action_recommendation():
    # Test invalid inputs
    rec, size, msg = compute_action_recommendation(0, 50, 60, 80, 50)
    assert "AVOID" in rec
    
    # Test strong buy setup (R/R >= 1.5, score >= 70, rsi < 75)
    # entry 100, target 115, SL 90 -> RR = (15 / 10) = 1.5
    rec, size, msg = compute_action_recommendation(100, 90, 115, 75, 50)
    assert "STRONG BUY" in rec
    assert size == "10%"
    
    # Test avoid setup (R/R too low)
    rec, size, msg = compute_action_recommendation(100, 90, 105, 75, 50)
    assert "AVOID" in rec
