"""Pre-market watch list: persistence, scoring, news map, ARA streak exclusion."""
import asyncio
from datetime import datetime, timedelta

import pandas as pd
import pytest

import bot.pre_market_predictor as pmp
import data.news as news
import data.pre_ara as pre_ara
from repositories.sqlite_repository import SQLiteRepository

WIB = __import__("pytz").timezone("Asia/Jakarta")


@pytest.fixture(autouse=True)
def _clear_ara_cache():
    pre_ara._streak_cache.clear()
    yield
    pre_ara._streak_cache.clear()


# ── Repository round-trips ──────────────────────────────────────────────────

def test_bsjp_repository_latest_date_wins(tmp_path):
    repo = SQLiteRepository(db_path=str(tmp_path / "t.db"))
    repo.save_bsjp_result("BBCA", "2026-08-05", "A — Prime BSJP 🌙", 80.0, 70.0, 40.0, 500, True, 9500.0)
    repo.save_bsjp_result("BBCA", "2026-08-06", "B — Good BSJP ✅", 60.0, 65.0, 30.0, -100, False, 9600.0)
    r = repo.get_last_bsjp_result("BBCA")
    assert r["trade_date"] == "2026-08-06"
    assert r["tier"] == "B — Good BSJP ✅"
    assert r["valid"] is False
    assert r["score"] == 60.0

    # tie-break: same trade_date → newest id wins
    repo.save_bsjp_result("BBCA", "2026-08-06", "B — Good BSJP ✅", 62.0, 65.0, 30.0, -100, True, 9600.0)
    r2 = repo.get_last_bsjp_result("BBCA")
    assert r2["score"] == 62.0

    assert repo.get_last_bsjp_result("ZZZZ") is None


def test_premarket_predictions_reasons_json_roundtrip(tmp_path):
    repo = SQLiteRepository(db_path=str(tmp_path / "t.db"))
    rows = [
        {"ticker": "ARCI", "score": 75, "tier": "WATCH CLOSELY",
         "reasons": ["ARA streak 3d (+30)", "📰 Gold rally (+25)", "🌐 Risk-on ×1.1"]},
        {"ticker": "BBCA", "score": 35, "tier": "ON RADAR",
         "reasons": ["BSJP B — Good BSJP ✅ 2026-08-06 (+15)"]},
    ]
    repo.save_premarket_predictions("2026-08-07", rows)
    preds = repo.get_premarket_predictions("2026-08-07")
    assert [p["ticker"] for p in preds] == ["ARCI", "BBCA"]
    assert preds[0]["reasons"] == rows[0]["reasons"]
    assert preds[1]["reasons"] == ["BSJP B — Good BSJP ✅ 2026-08-06 (+15)"]
    assert preds[1]["score"] == 35 and preds[1]["tier"] == "ON RADAR"

    # delete-then-insert: rerun replaces the date
    repo.save_premarket_predictions("2026-08-07", [rows[1]])
    assert len(repo.get_premarket_predictions("2026-08-07")) == 1
    assert repo.get_premarket_predictions("2026-08-08") == []

    # backtest feed
    all_rows = repo.get_premarket_predictions_all()
    assert len(all_rows) == 1 and all_rows[0]["pred_date"] == "2026-08-07"

    # run log: distinguishes "job belum jalan" from "job jalan, 0 kandidat"
    assert repo.get_premarket_run("2026-08-07") is None
    repo.save_premarket_run("2026-08-07", n_candidates=0, ran_at="2026-08-07T09:22:00+07:00")
    run_info = repo.get_premarket_run("2026-08-07")
    assert run_info["n_candidates"] == 0
    assert run_info["ran_at"].startswith("2026-08-07T09:22")
    repo.save_premarket_run("2026-08-07", n_candidates=2, ran_at="2026-08-07T09:30:00+07:00")
    assert repo.get_premarket_run("2026-08-07")["n_candidates"] == 2  # upsert


def test_eod_snapshot_roundtrip(tmp_path):
    repo = SQLiteRepository(db_path=str(tmp_path / "t.db"))
    repo.save_eod_snapshot("2026-08-06", [
        {"ticker": "ARCI", "chg_pct": 5.2, "vol_spike": 3.0, "score": 80,
         "signal": "STRONG BUY", "at_ara": True, "approached_ara": False},
        {"ticker": "BBCA", "chg_pct": -0.5, "vol_spike": 1.1, "score": 60,
         "signal": "BUY", "at_ara": False, "approached_ara": True},
    ])
    rows = repo.get_eod_snapshot("2026-08-06")
    assert len(rows) == 2
    assert rows[0]["ticker"] == "ARCI" and rows[0]["at_ara"] is True
    assert rows[1]["approached_ara"] is True and rows[1]["chg_pct"] == -0.5
    assert repo.get_eod_snapshot("2026-08-05") == []


# ── ticker_sentiment_map shape ─────────────────────────────────────────────

def test_ticker_sentiment_map_shape(monkeypatch):
    monkeypatch.setattr(news, "fetch_all_news", lambda: {
        "cnbc_indonesia": [{"title": "BBCA laba naik 20 persen", "source": "cnbc_indonesia", "ts": 0}],
    })
    monkeypatch.setattr(
        "data.fetchers.fetch_news_for_tickers",
        lambda tickers: {"BBCA": {"sentiment": 0.2, "latest": "yfinance latest headline", "count": 1}},
    )
    res = news.ticker_sentiment_map(["BBCA", "BBRI"])
    assert "BBCA" in res and "BBRI" in res
    b = res["BBCA"]
    assert set(b) >= {"polarity", "confidence", "headline"}
    assert b["polarity"] == "positif"
    assert b["headline"] == "BBCA laba naik 20 persen"
    assert b["confidence"] == pytest.approx(0.6)  # min(1.0, (0.2 + 1.0) / 2.0)
    r = res["BBRI"]
    assert r["polarity"] == "netral"
    assert r["confidence"] == 0.0
    assert r["headline"] == ""


# ── detect_ara_streak exclude_today ────────────────────────────────────────

def _fake_ticker_with_history(df):
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            return df
    return FakeTicker


def _ara_df():
    today = datetime.now(WIB).date()
    dates = pd.DatetimeIndex([
        pd.Timestamp(today - timedelta(days=2)).tz_localize("Asia/Jakarta"),
        pd.Timestamp(today - timedelta(days=1)).tz_localize("Asia/Jakarta"),
        pd.Timestamp(today).tz_localize("Asia/Jakarta"),
    ])
    return pd.DataFrame({"Open": [1000, 1250, 1562.5], "Close": [1000, 1250, 1562.5]}, index=dates)


def test_detect_ara_streak_exclude_today_drops_in_progress_bar(monkeypatch):
    df = _ara_df()
    monkeypatch.setattr(pre_ara.yf, "Ticker", _fake_ticker_with_history(df))

    # default (backward compatible): counts today's bar → streak 2, riding
    res = pre_ara.detect_ara_streak("ARCI")
    assert res["streak"] == 2 and res["is_riding"] is True

    # exclude_today: today's bar dropped → streak 1, not riding
    res_ex = pre_ara.detect_ara_streak("ARCI", exclude_today=True)
    assert res_ex["streak"] == 1 and res_ex["is_riding"] is False


def test_detect_ara_streak_exclude_today_cache_key(monkeypatch):
    df = _ara_df()
    monkeypatch.setattr(pre_ara.yf, "Ticker", _fake_ticker_with_history(df))
    pre_ara.detect_ara_streak("ARCI")
    pre_ara.detect_ara_streak("ARCI", exclude_today=True)
    # both variants cached independently
    assert (("ARCI", 5, False)) in pre_ara._streak_cache
    assert (("ARCI", 5, True)) in pre_ara._streak_cache


# ── compute_premarket_scores ───────────────────────────────────────────────

def _patch_predictor(monkeypatch, *, macro=None, streak=None, bsjp=None,
                     sentiment=None, calendar=None):
    macro = macro or {"risk_on": False, "risk_off": False, "dji_chg": 0.0, "spx_chg": 0.0}
    monkeypatch.setattr(pmp, "get_macro_context", lambda: macro)
    if callable(streak):
        streak_fn = streak
    elif streak is None:
        streak_fn = lambda symbol, **kw: {"streak": 0, "consecutive_ara": False, "is_riding": False}
    else:
        streak_fn = lambda symbol, **kw: streak
    monkeypatch.setattr(pmp, "detect_ara_streak", streak_fn)

    class FakeRepo:
        def get_last_bsjp_result(self, ticker):
            return bsjp(ticker) if bsjp else None

    monkeypatch.setattr(pmp, "sqlite_repository", FakeRepo())
    monkeypatch.setattr(pmp, "ticker_sentiment_map", (lambda tickers: sentiment) if sentiment is not None else (lambda tickers: {}))
    if callable(calendar):
        cal_fn = calendar
    elif calendar is None:
        cal_fn = lambda ticker, today: []
    else:
        cal_fn = lambda ticker, today: calendar
    monkeypatch.setattr(pmp, "events_for_ticker_on", cal_fn)


def test_compute_premarket_scores_components_and_reasons(monkeypatch):
    def streak_fn(symbol, **kw):
        if symbol == "ARCI":
            return {"streak": 3, "consecutive_ara": True, "is_riding": True}
        return {"streak": 0, "consecutive_ara": False, "is_riding": False}

    _patch_predictor(
        monkeypatch,
        streak=streak_fn,
        bsjp=lambda t: {"ticker": t, "trade_date": "2026-08-06", "tier": "A — Prime BSJP 🌙", "score": 80.0},
        sentiment={"ARCI": {"polarity": "positif", "confidence": 1.0,
                            "headline": "Harga emas melonjak, ARCI diuntungkan", "combined": 2.0}},
        calendar=lambda ticker, today: (
            [{"event_type": "RUPS", "signal": "🟡 Watch (AGMS/EGMS Vote)", "description": "RUPS Tahunan"}]
            if ticker == "ARCI" else []
        ),
    )
    rows = asyncio.run(pmp.compute_premarket_scores(["ARCI", "BBCA"], today="2026-08-07"))
    assert [r["ticker"] for r in rows] == ["ARCI", "BBCA"]
    r = rows[0]
    assert r["score"] == 95 and r["tier"] == "WATCH CLOSELY"  # 30+25+25+15, neutral macro
    assert rows[1]["ticker"] == "BBCA"
    assert rows[1]["score"] == 25 and rows[1]["tier"] == "BELOW RADAR"  # BSJP Prime only
    reasons = r["reasons"]
    assert "ARA streak 3d (+30)" in reasons
    assert any(x.startswith("BSJP") and "2026-08-06" in x and "(+25)" in x for x in reasons)
    assert any(x.startswith("📰 Harga emas melonjak") and "(+25)" in x for x in reasons)
    assert any("📅 RUPS" in x and "(+15)" in x for x in reasons)
    assert not any("Risk" in x for x in reasons)


def test_compute_premarket_scores_tier_thresholds(monkeypatch):
    def streak_fn(symbol, **kw):
        if symbol == "X":
            return {"streak": 3, "consecutive_ara": True, "is_riding": True}  # +30
        return {"streak": 0, "consecutive_ara": False, "is_riding": False}

    def bsjp_fn(t):
        tier = "A — Prime BSJP 🌙" if t != "V" else "B — Good BSJP ✅"
        return {"ticker": t, "trade_date": "2026-08-06", "tier": tier, "score": 80.0}

    _patch_predictor(
        monkeypatch,
        streak=streak_fn,
        bsjp=bsjp_fn,
        sentiment={
            "X": {"polarity": "positif", "confidence": 0.2, "headline": "h", "combined": 0.4},  # 30 + 25 + 5 = 60 → WATCH
            "Y": {"polarity": "positif", "confidence": 0.8, "headline": "h", "combined": 1.6},  # 25 + 20 = 45 → ON RADAR
            "Z": {"polarity": "positif", "confidence": 0.4, "headline": "h", "combined": 0.8},  # 25 + 10 = 35 → ON RADAR
            "W": {"polarity": "positif", "confidence": 0.2, "headline": "h", "combined": 0.4},  # 25 + 5 = 30 → BELOW RADAR
            # V: bsjp Good (+15) only → 15 → excluded (< 20)
        },
    )
    rows = asyncio.run(pmp.compute_premarket_scores(["X", "Y", "Z", "W", "V"], today="2026-08-07"))
    by_ticker = {r["ticker"]: r for r in rows}
    assert set(by_ticker) == {"X", "Y", "Z", "W"}
    assert by_ticker["X"]["score"] == 60 and by_ticker["X"]["tier"] == "WATCH CLOSELY"
    assert by_ticker["Y"]["score"] == 45 and by_ticker["Y"]["tier"] == "ON RADAR"
    assert by_ticker["Z"]["score"] == 35 and by_ticker["Z"]["tier"] == "ON RADAR"
    assert by_ticker["W"]["score"] == 30 and by_ticker["W"]["tier"] == "BELOW RADAR"


def test_compute_premarket_scores_macro_multiplier(monkeypatch):
    streak = {"streak": 3, "consecutive_ara": True, "is_riding": True}
    bsjp = lambda t: {"ticker": t, "trade_date": "2026-08-06", "tier": "A — Prime BSJP 🌙", "score": 80.0}

    _patch_predictor(monkeypatch, macro={"risk_on": True, "risk_off": False, "dji_chg": 1.0, "spx_chg": 0.5},
                     streak=streak, bsjp=bsjp)
    rows = asyncio.run(pmp.compute_premarket_scores(["ARCI"], today="2026-08-07"))
    assert rows[0]["score"] == round(55 * 1.1)  # 30 + 25, risk-on ×1.1
    assert "🌐 Risk-on ×1.1" in rows[0]["reasons"]

    _patch_predictor(monkeypatch, macro={"risk_on": False, "risk_off": True, "dji_chg": -1.0, "spx_chg": -0.5},
                     streak=streak, bsjp=bsjp)
    rows2 = asyncio.run(pmp.compute_premarket_scores(["ARCI"], today="2026-08-07"))
    assert rows2[0]["score"] == round(55 * 0.85)  # risk-off ×0.85
    assert "🌐 Risk-off ×0.85" in rows2[0]["reasons"]


def test_compute_premarket_scores_failures_contribute_zero(monkeypatch):
    _patch_predictor(monkeypatch, streak=None, bsjp=None, sentiment=None, calendar=None)

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(pmp, "detect_ara_streak", boom)
    monkeypatch.setattr(pmp, "ticker_sentiment_map", boom)
    monkeypatch.setattr(pmp, "events_for_ticker_on", boom)

    rows = asyncio.run(pmp.compute_premarket_scores(["ARCI"], today="2026-08-07"))
    assert rows == []  # no signals → no candidates, no crash


def test_compute_premarket_scores_ignores_same_day_bsjp(monkeypatch):
    _patch_predictor(
        monkeypatch,
        bsjp=lambda t: {"ticker": t, "trade_date": "2026-08-07", "tier": "A — Prime BSJP 🌙", "score": 80.0},
    )
    rows = asyncio.run(pmp.compute_premarket_scores(["ARCI"], today="2026-08-07"))
    assert rows == []  # BSJP has not run yet on the pre-market day


def test_premarket_cache_roundtrip_and_expiry(tmp_path):
    import time

    repo = SQLiteRepository(db_path=str(tmp_path / "t.db"))
    assert repo.cache_get("k1") is None
    repo.cache_set("k1", '{"a": 1}', ttl_sec=60)
    assert repo.cache_get("k1") == '{"a": 1}'
    repo.cache_set("k2", "x", ttl_sec=60)
    # expired entries are skipped by cache_get
    assert repo.cache_get("k2", now_ts=time.time() + 120) is None
    # upsert replaces payload
    repo.cache_set("k1", '{"a": 2}', ttl_sec=60)
    assert repo.cache_get("k1") == '{"a": 2}'


def test_compute_premarket_scores_uses_persistent_cache(monkeypatch, tmp_path):
    """Same-day re-run served from SQLite cache — no yfinance/news refetch."""
    repo = SQLiteRepository(db_path=str(tmp_path / "t.db"))
    monkeypatch.setattr(pmp, "sqlite_repository", repo)
    monkeypatch.setattr(
        pmp, "get_macro_context",
        lambda: {"risk_on": False, "risk_off": False, "dji_chg": 0.0, "spx_chg": 0.0},
    )

    today = "2026-08-07"
    pmp._cache_set_json(f"macro:{today}", {"risk_on": False, "risk_off": False, "dji_chg": 0.0, "spx_chg": 0.0}, 60)
    pmp._cache_set_json(f"news:{today}", {"ARCI": {"polarity": "positif", "confidence": 1.0, "headline": "h", "combined": 2.0}}, 60)
    pmp._cache_set_json(f"streak:ARCI:{today}", {"streak": 3, "consecutive_ara": True, "is_riding": True}, 60)

    def boom(*a, **k):
        raise AssertionError("should have been served from persistent cache")

    monkeypatch.setattr(pmp, "detect_ara_streak", boom)
    monkeypatch.setattr(pmp, "ticker_sentiment_map", boom)

    rows = asyncio.run(pmp.compute_premarket_scores(["ARCI"], today=today))
    assert len(rows) == 1 and rows[0]["ticker"] == "ARCI"
    assert rows[0]["score"] == 55 and rows[0]["tier"] == "ON RADAR"  # streak 30 + news 25
    assert "ARA streak 3d (+30)" in rows[0]["reasons"]
    assert any(x.startswith("📰") for x in rows[0]["reasons"])
