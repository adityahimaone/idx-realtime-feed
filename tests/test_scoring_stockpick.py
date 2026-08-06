import pytest
from data.scoring import compute_intraday_score


def _mk_data(volume=1000, last=1000, prev=1000, high=1010, low=990, fb=100, fs=100):
    return {
        "last": last, "prev_close": prev, "high": high, "low": low,
        "volume": volume, "foreign_buy": fb, "foreign_sell": fs,
    }


def _mk_hist(vol_avg=1000, total_bid=0, total_ask=0, ma20=0, ma50=0, ma200=0,
             score_v2=50, rsi=0, dist_52w=None, ara_dist=None, uma="", corp=""):
    h = {
        "Vol_Avg": vol_avg, "Score v2": score_v2, "RSI14": rsi,
        "MA20": ma20, "MA50": ma50, "MA200": ma200,
        "Total Bid Lot": total_bid, "Total Ask Lot": total_ask,
        "UMA": uma, "Corp Action": corp,
    }
    if dist_52w is not None:
        h["Dist to 52W High"] = dist_52w
    if ara_dist is not None:
        h["ARA_Dist_Pct"] = ara_dist
    return h


def test_weights_sum_to_one():
    weights = [0.25, 0.20, 0.20, 0.15, 0.10, 0.10]
    assert sum(weights) == pytest.approx(1.0)


def test_contract_keys_present():
    res = compute_intraday_score(_mk_data(), _mk_hist())
    for key in ["score", "signal", "tier", "color", "vol_spike", "change_pct",
                "warnings", "breakdown"]:
        assert key in res
    for key in ["flow", "orderbook", "trend", "momentum", "hist", "risk"]:
        assert key in res["breakdown"]


def test_orderbook_imbalance_tiers():
    cases = [(3.0, 100), (1.6, 75), (0.9, 50), (0.5, 20)]
    for ratio, expected in cases:
        hist = _mk_hist(total_bid=300, total_ask=int(300 / ratio))
        res = compute_intraday_score(_mk_data(), hist)
        assert res["breakdown"]["orderbook"] == expected, f"ratio {ratio}"


def test_ma_stack_tiers():
    data = _mk_data(last=1000)
    # price > MA20 > MA50 > MA200 -> 100
    assert compute_intraday_score(data, _mk_hist(ma20=900, ma50=800, ma200=700))["breakdown"]["trend"] == 100
    # price > MA20 > MA50, but MA50 <= MA200 -> 70
    assert compute_intraday_score(data, _mk_hist(ma20=900, ma50=800, ma200=850))["breakdown"]["trend"] == 70
    # price > MA20 only -> 40
    assert compute_intraday_score(data, _mk_hist(ma20=900, ma50=950, ma200=700))["breakdown"]["trend"] == 40
    # price < MA20 -> 20
    assert compute_intraday_score(data, _mk_hist(ma20=1100, ma50=900, ma200=700))["breakdown"]["trend"] == 20
    # missing MA20 -> 20 (no false positive)
    assert compute_intraday_score(data, _mk_hist())["breakdown"]["trend"] == 20


def test_52w_proximity_bonus_capped_at_100():
    data = _mk_data(last=1000)
    # Already 100 -> bonus capped
    res = compute_intraday_score(data, _mk_hist(ma20=900, ma50=800, ma200=700, dist_52w=-5))
    assert res["breakdown"]["trend"] == 100
    # 70 -> +10 = 80
    res = compute_intraday_score(data, _mk_hist(ma20=900, ma50=800, ma200=850, dist_52w=-5))
    assert res["breakdown"]["trend"] == 80
    # Outside window -> no bonus
    res = compute_intraday_score(data, _mk_hist(ma20=900, ma50=800, ma200=850, dist_52w=-15))
    assert res["breakdown"]["trend"] == 70


def test_rsi_momentum_discount():
    data = _mk_data(last=1050, prev=1000)  # chg = +5% -> 100
    assert compute_intraday_score(data, _mk_hist(rsi=60))["breakdown"]["momentum"] == 100
    assert compute_intraday_score(data, _mk_hist(rsi=72))["breakdown"]["momentum"] == 75
    assert compute_intraday_score(data, _mk_hist(rsi=76))["breakdown"]["momentum"] == 50


def test_hard_cap_ara():
    data = _mk_data(last=1000)
    hist = _mk_hist(ara_dist=1.5, ma20=900, ma50=800, ma200=700, total_bid=300, total_ask=100)
    res = compute_intraday_score(data, hist)
    assert res["score"] <= 55
    assert any("ARA" in w for w in res["warnings"])


def test_hard_cap_uma():
    data = _mk_data(last=1000)
    hist = _mk_hist(uma="UMA", ma20=900, ma50=800, ma200=700, total_bid=300, total_ask=100)
    res = compute_intraday_score(data, hist)
    assert res["score"] <= 40
    assert any("UMA" in w for w in res["warnings"])


def test_hard_cap_corp_action():
    data = _mk_data(last=1000)
    hist = _mk_hist(corp="Right Issue", ma20=900, ma50=800, ma200=700, total_bid=300, total_ask=100)
    res = compute_intraday_score(data, hist)
    assert res["score"] <= 60
    assert any("Corporate Action" in w for w in res["warnings"])


def test_most_restrictive_cap_wins():
    data = _mk_data(last=1000)
    hist = _mk_hist(ara_dist=1.5, uma="UMA", ma20=900, ma50=800, ma200=700, total_bid=300, total_ask=100)
    res = compute_intraday_score(data, hist)
    assert res["score"] <= 40
    assert len(res["warnings"]) == 2


def test_missing_column_defaults():
    res = compute_intraday_score(_mk_data(), {})
    assert res["warnings"] == []
    # flow(44)*.25 + ob(20)*.2 + trend(20)*.2 + momentum(60)*.15 + hist(50)*.1 + risk(50)*.1 = 38
    assert res["score"] == 38
    assert res["breakdown"]["hist"] == 50
    assert res["breakdown"]["risk"] == 50


# ─── Live-data overrides (imbalance_ratio / tradebook) ───────────────────────

def test_no_new_args_regression():
    """Calling with the new optional args omitted matches legacy output exactly."""
    data = _mk_data(last=1050, prev=1000, volume=2500)  # chg +5%, vol spike 2.5
    hist = _mk_hist(vol_avg=1000, ma20=900, ma50=800, ma200=700,
                    total_bid=300, total_ask=100, rsi=60)
    base = compute_intraday_score(data, hist)
    explicit_none = compute_intraday_score(data, hist, imbalance_ratio=None, tradebook=None)
    assert explicit_none == base
    assert base["breakdown"] == explicit_none["breakdown"]
    assert "trade_flow" not in base["breakdown"]


def test_imbalance_ratio_override():
    """imbalance_ratio replaces the sheet-derived bid/ask ratio."""
    # Sheet has balanced book (ratio 1.0 → 50); live ratio 3.0 → 100.
    hist = _mk_hist(total_bid=100, total_ask=100)
    res = compute_intraday_score(_mk_data(), hist, imbalance_ratio=3.0)
    assert res["breakdown"]["orderbook"] == 100

    res_sheet = compute_intraday_score(_mk_data(), hist)
    assert res_sheet["breakdown"]["orderbook"] == 50


def test_tradebook_splits_orderbook_slot():
    """Supplying a tradebook profile splits orderbook 0.20 → ob 0.10 + flow 0.10."""
    data = _mk_data(last=1050, prev=1000, volume=2500)
    hist = _mk_hist(vol_avg=1000, ma20=900, ma50=800, ma200=700,
                    total_bid=300, total_ask=100, rsi=60)
    tradebook = {
        "big_money_trend": "accumulating",
        "net_positive_ratio": 0.8,
        "momentum": "accelerating",
        "big_money_sell_pct": 45.0,
        "big_money_buy_pct": 55.0,
    }
    res = compute_intraday_score(data, hist, imbalance_ratio=2.0, tradebook=tradebook)
    # 80 (accumulating) + 20*0.8 (net ratio) + 10 (accelerating) = 106 → clamp 100.
    assert res["breakdown"]["trade_flow"] == 100
    assert res["breakdown"]["orderbook"] == 75  # 2.0 ratio tier

    # Total must differ from the legacy call (weights moved 0.10 → trade_flow).
    legacy = compute_intraday_score(data, hist)
    assert res["score"] != legacy["score"]


def test_trade_flow_capped_when_big_money_sell_dominant():
    """trade_flow is capped at 40 when big-money selling is dominant (≥55%)."""
    data = _mk_data(last=1050, prev=1000, volume=2500)
    hist = _mk_hist(vol_avg=1000, ma20=900, ma50=800, ma200=700,
                    total_bid=300, total_ask=100, rsi=60)
    tradebook = {
        "big_money_trend": "neutral",
        "net_positive_ratio": 1.0,
        "momentum": "accelerating",
        "big_money_sell_pct": 60.0,
        "big_money_buy_pct": 40.0,
    }
    res = compute_intraday_score(data, hist, imbalance_ratio=2.0, tradebook=tradebook)
    # Un-capped: 55 + 20*1.0 + 10 = 85 → capped at 40.
    assert res["breakdown"]["trade_flow"] == 40
