import pytest
from data.mega_score import HORIZON_WEIGHTS, compute_mega_score, news_sentiment_to_score


def test_missing_signals_default_to_50_and_are_reported():
    res = compute_mega_score({}, "scalping")
    assert res["score"] == 50.0
    assert res["tier"] == "🟡 NETRAL / WATCHLIST"
    # All 4 scalping signals defaulted
    assert set(res["defaulted"]) == set(HORIZON_WEIGHTS["scalping"].keys())
    assert all(not v for v in res["available"].values())
    assert res["confidence"] == 0.0


def test_available_and_confidence_weighted_share():
    signals = {"intraday_score": 100, "orderbook_score": 100}  # 0.3 + 0.3 of weight
    res = compute_mega_score(signals, "scalping")
    # weighted: (100*0.3 + 100*0.3 + 50*0.2 + 50*0.2) / 1.0
    assert res["score"] == 80.0
    assert res["available"]["intraday_score"] is True
    assert res["available"]["trending_score"] is False
    assert set(res["defaulted"]) == {"trending_score", "pre_ara_score"}
    # present weight = 0.6 of 1.0
    assert res["confidence"] == pytest.approx(0.6)


def test_none_and_unparseable_count_as_defaulted():
    signals = {
        "intraday_score": None,
        "orderbook_score": "not-a-number",
        "trending_score": 80,
        "pre_ara_score": [90],
    }
    res = compute_mega_score(signals, "scalping")
    assert res["defaulted"] == ["intraday_score", "orderbook_score"]
    # 0.2 + 0.2 present weight
    assert res["confidence"] == pytest.approx(0.4)
    assert res["breakdown"]["pre_ara_score"] == 90.0


def test_invalid_horizon_falls_back_to_scalping():
    res = compute_mega_score({"intraday_score": 100}, "bogus_horizon")
    assert res["horizon"] == "bogus_horizon"
    # fallback weights = scalping
    assert set(res["breakdown"].keys()) == set(HORIZON_WEIGHTS["scalping"].keys())
    expected = round((100 * 0.3 + 50 * 0.7) / 1.0, 1)
    assert res["score"] == expected


def test_tier_boundaries():
    signals_85 = {"intraday_score": 100, "orderbook_score": 100,
                  "trending_score": 100, "pre_ara_score": 25}
    res = compute_mega_score(signals_85, "scalping")
    assert res["score"] == 85.0
    assert res["tier"] == "🟢 SANGAT DIREKOMENDASIKAN"

    signals_70 = {"intraday_score": 100, "orderbook_score": 100,
                  "trending_score": 50, "pre_ara_score": 0}
    res = compute_mega_score(signals_70, "scalping")
    assert res["score"] == 70.0
    assert res["tier"] == "🔵 DIREKOMENDASIKAN"

    res = compute_mega_score({"intraday_score": 10, "orderbook_score": 10,
                              "trending_score": 10, "pre_ara_score": 10}, "scalping")
    assert res["score"] == 10.0
    assert res["tier"] == "🔴 HINDARI"


def test_news_sentiment_to_score_boundaries():
    # neutral → 50, positive raises, negative lowers, clamped 0..100
    assert news_sentiment_to_score(0) == 50.0
    assert news_sentiment_to_score(2.5) == 100.0
    assert news_sentiment_to_score(-3) == 0.0
    assert news_sentiment_to_score(0.5) == 60.0
    assert news_sentiment_to_score(10) == 100.0
    assert news_sentiment_to_score(-10) == 0.0


def test_swing_bsjp_uses_news_sentiment_score():
    signals = {
        "intraday_score": 70,
        "bsjp_score": 80,
        "news_sentiment_score": news_sentiment_to_score(2.0),  # 90
        "trending_score": 60,
    }
    res = compute_mega_score(signals, "swing_bsjp")
    assert res["available"]["news_sentiment_score"] is True
    assert res["breakdown"]["news_sentiment_score"] == 90.0
    assert "news_sentiment_score" not in res["defaulted"]
