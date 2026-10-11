import pytest
import math
from data.recommendation import (
    get_ara_limit_pct,
    get_arb_limit_pct,
    liquidity_score,
    volatility_score,
    relative_strength_score,
    trend_template_score,
    flow_score,
    momentum_score,
    fundamental_quality_score,
    apply_risk_gates,
    compute_levels,
    compute_best_pick,
    rank_best_picks,
    LIQUIDITY_FLOOR,
)


def _entry(price=1000, chg=2.0, **kwargs):
    """Build a minimal scored_list entry dict."""
    raw = {
        "last": price,
        "prev_close": price / (1 + chg / 100),
        "high": price * 1.03,
        "low": price * 0.97,
        "volume": 1_000_000,
        "foreign_buy": 500_000,
        "foreign_sell": 300_000,
        "total_bid_lot": 100_000,
        "total_ask_lot": 50_000,
        "value": 1_000_000_000_000,
    }
    raw.update(kwargs.pop("raw_data", {}))
    hist = {
        "Vol_Avg": 800_000,
        "MA20": price * 0.98,
        "MA50": price * 0.95,
        "MA200": price * 0.90,
        "52W High": price * 1.20,
        "52W Low": price * 0.60,
        "RSI14": 55,
        "ATR %": 3.5,
        "PE": 12,
        "MarketCap": 5_000_000_000_000,
        "Beta": 1.0,
        "Support": price * 0.94,
        "ClosePrev": raw["prev_close"],
    }
    hist.update(kwargs.pop("hist_row", {}))
    return {
        "Ticker": kwargs.get("ticker", "BBCA"),
        "Live Price": price,
        "Change %": chg,
        "Intraday Score": 70,
        "raw_data_obj": raw,
        "hist_row_obj": hist,
        **kwargs,
    }


# ─── Market microstructure ───────────────────────────────────────────────────

def test_ara_limit_tiers():
    assert get_ara_limit_pct(150) == 35.0
    assert get_ara_limit_pct(200) == 25.0
    assert get_ara_limit_pct(4990) == 25.0
    assert get_ara_limit_pct(5000) == 20.0
    assert get_ara_limit_pct(10_000) == 20.0


def test_arb_limit_current_rule():
    # Rp 1–10 sentinel
    assert get_arb_limit_pct(5) == -100.0
    # > Rp 10 flat -15%
    assert get_arb_limit_pct(50) == -15.0
    assert get_arb_limit_pct(500) == -15.0
    assert get_arb_limit_pct(10_000) == -15.0


# ─── Liquidity ───────────────────────────────────────────────────────────────

def test_liquidity_tiers():
    e = _entry(price=1000, hist_row={"Vol_Avg": 10_000_000})
    assert liquidity_score(e)["score"] == 100.0  # ≥ Rp 50 B

    e = _entry(price=500, hist_row={"Vol_Avg": 200_000})
    assert liquidity_score(e)["score"] == 85.0   # ≥ Rp 10 B

    e = _entry(price=500, hist_row={"Vol_Avg": 100_000})
    assert liquidity_score(e)["score"] == 70.0   # ≥ Rp 5 B

    e = _entry(price=500, hist_row={"Vol_Avg": 20_000})
    assert liquidity_score(e)["score"] == 55.0   # ≥ Rp 1 B

    e = _entry(price=500, hist_row={"Vol_Avg": 5_000})
    assert liquidity_score(e)["score"] == 35.0   # ≥ Rp 250 M

    e = _entry(price=500, hist_row={"Vol_Avg": 1_000})
    assert liquidity_score(e)["score"] == 15.0   # < Rp 250 M


def test_liquidity_fallback_to_value():
    e = _entry(price=1000, hist_row={"Vol_Avg": 0}, raw_data={"value": 5_000_000_000_000})
    assert liquidity_score(e)["score"] == 100.0


def test_liquidity_no_data():
    e = _entry(price=1000, hist_row={"Vol_Avg": 0}, raw_data={"value": 0})
    assert liquidity_score(e)["score"] == 50.0


# ─── Volatility ──────────────────────────────────────────────────────────────

def test_volatility_sweet_spot():
    e = _entry(hist_row={"ATR %": 4.0})
    assert volatility_score(e, "scalping")["score"] == 100.0
    assert volatility_score(e, "swing_bsjp")["score"] == 100.0
    assert volatility_score(e, "long_term")["score"] == 100.0


def test_volatility_too_low():
    e = _entry(hist_row={"ATR %": 0.5})
    assert volatility_score(e, "scalping")["score"] == 40.0


def test_volatility_too_high():
    e = _entry(hist_row={"ATR %": 20.0})
    assert volatility_score(e, "scalping")["score"] == 30.0
    assert volatility_score(e, "swing_bsjp")["score"] == 30.0


def test_volatility_fallback_intraday():
    e = _entry(price=1000, raw_data={"high": 1030, "low": 970, "prev_close": 1000}, hist_row={"ATR %": "", "Daily_Range_Pct": ""})
    assert volatility_score(e, "scalping")["atr_pct"] == pytest.approx(6.0, abs=0.1)


# ─── Relative Strength ───────────────────────────────────────────────────────

def test_rs_vs_ihsg():
    e = _entry(price=1200, hist_row={"ClosePrev": 1000})
    # ticker +20% vs IHSG +5% → RS = +15
    res = relative_strength_score(e, rs_ihsg=5.0)
    assert res["score"] == pytest.approx(75.0, abs=1.0)
    assert res["rs_raw"] == pytest.approx(15.0, abs=0.5)


def test_rs_no_data():
    e = _entry(price=1000, hist_row={"ClosePrev": 0, "52W High": 0, "52W Low": 0})
    assert relative_strength_score(e)["score"] == 50.0


# ─── Trend Template ──────────────────────────────────────────────────────────

def test_trend_template_from_ma_stack():
    e = _entry(price=1100, hist_row={"MA20": 1000, "MA50": 950, "52W High": 1500, "52W Low": 600, "Vol_Avg": 1000, "Volume": 2000})
    res = trend_template_score(e)
    assert res["score"] > 70.0
    assert res["conds_met"] >= 3


# ─── Flow ────────────────────────────────────────────────────────────────────

def test_flow_bullish():
    e = _entry(raw_data={"foreign_buy": 900_000, "foreign_sell": 100_000, "total_bid_lot": 200_000, "total_ask_lot": 40_000})
    res = flow_score(e)
    assert res["score"] > 80.0
    assert res["foreign_ratio"] == pytest.approx(9.0, abs=0.1)


def test_flow_bearish():
    e = _entry(raw_data={"foreign_buy": 100_000, "foreign_sell": 900_000, "total_bid_lot": 30_000, "total_ask_lot": 200_000})
    res = flow_score(e)
    assert res["score"] < 40.0
    assert "foreign net selling" in res["note"]


# ─── Momentum ────────────────────────────────────────────────────────────────

def test_momentum_scalping_overbought():
    e = _entry(price=1070, raw_data={"prev_close": 1000}, hist_row={"RSI14": 78})
    res = momentum_score(e, "scalping")
    assert res["score"] < 60.0  # 100 base * 0.5 = 50


def test_momentum_swing_healthy_rsi():
    e = _entry(price=1030, raw_data={"prev_close": 1000}, hist_row={"RSI14": 55})
    res = momentum_score(e, "swing_bsjp")
    assert res["score"] > 70.0


# ─── Fundamental Quality ─────────────────────────────────────────────────────

def test_fundamental_quality_ideal():
    e = _entry(hist_row={"PE": 10, "MarketCap": 20_000_000_000_000, "Beta": 1.0})
    res = fundamental_quality_score(e)
    assert res["score"] > 85.0


def test_fundamental_quality_loss_maker():
    e = _entry(hist_row={"PE": -5, "MarketCap": 50_000_000_000, "Beta": 1.8})
    res = fundamental_quality_score(e)
    assert res["score"] < 50.0
    assert "loss-making" in res["note"]


# ─── Risk Gates ──────────────────────────────────────────────────────────────

def test_gate_uma():
    e = _entry(hist_row={"UMA": "UMA"})
    g = apply_risk_gates(e, 90.0)
    assert g["score"] <= 40.0
    assert any("UMA" in w for w in g["warnings"])


def test_gate_ara_proximity():
    e = _entry(hist_row={"ARA_Dist_Pct": 1.5})
    g = apply_risk_gates(e, 90.0)
    assert g["score"] <= 55.0


def test_gate_extreme_vol():
    e = _entry(hist_row={"ATR %": 20.0})
    g = apply_risk_gates(e, 90.0)
    assert g["score"] <= 50.0


def test_gate_most_restrictive_wins():
    e = _entry(hist_row={"UMA": "UMA", "ARA_Dist_Pct": 1.5, "ATR %": 20.0})
    g = apply_risk_gates(e, 90.0)
    assert g["score"] <= 40.0


# ─── Levels ──────────────────────────────────────────────────────────────────

def test_levels_sanity():
    lv = compute_levels(1000, 3.5, {"Support": 940}, {"prev_close": 980}, "Moderat")
    assert lv["entry"] == 1000
    assert lv["sl"] < lv["entry"]
    assert lv["tp"] > lv["entry"]
    assert lv["rr"] >= 1.5
    assert lv["risk_pct"] <= 6.0


def test_levels_tp_capped_at_52w_high():
    lv = compute_levels(1000, 3.5, {"52W High": 1020, "Support": 940}, {"prev_close": 980}, "Aggressive")
    assert lv["tp"] <= 1020


# ─── Best Pick integration ───────────────────────────────────────────────────

def test_best_pick_scalping():
    e = _entry(price=1050, chg=3.0, raw_data={"prev_close": 1019})
    pick = compute_best_pick(e, "scalping", rs_ihsg=1.0)
    assert "score" in pick
    assert "tier" in pick
    assert "levels" in pick
    assert "rationale" in pick
    assert pick["confidence"] > 0.5


def test_best_pick_long_term_fundamental():
    e = _entry(hist_row={"PE": 50, "MarketCap": 10_000_000_000, "Beta": 1.8})
    pick = compute_best_pick(e, "long_term")
    assert "fundamental" in pick["breakdown"]
    assert pick["breakdown"]["fundamental"] < 60.0


def test_best_pick_gated_by_uma():
    e = _entry(hist_row={"UMA": "UMA"})
    pick = compute_best_pick(e, "swing_bsjp")
    assert pick["score"] <= 40.0
    assert pick["cap"] == 40.0
    assert any("UMA" in w for w in pick["warnings"])


def test_rank_best_picks():
    a = _entry(price=1000, ticker="A")
    b = _entry(price=1000, ticker="B", hist_row={"UMA": "UMA"})
    ranked = rank_best_picks([a, b], "scalping")
    assert ranked[0]["BestPick"]["score"] >= ranked[1]["BestPick"]["score"]


def test_rank_min_score_filter():
    a = _entry(price=1000, ticker="A")
    ranked = rank_best_picks([a], "scalping", min_score=99)
    assert len(ranked) == 0
