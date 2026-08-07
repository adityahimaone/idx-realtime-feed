import asyncio
from datetime import datetime, timedelta

import pytest

import data.fetchers as fetchers
from data.fetchers import (
    FRESHNESS_THRESHOLDS_MIN,
    SOURCE_PRIORITY,
    fetch_itick_quotes_batch,
    fetch_itick_snapshot,
    fetch_stockbit_quote_source,
    pick_freshest_source,
)

WIB = __import__("pytz").timezone("Asia/Jakarta")


def _fresh_ts(minutes_ago: float = 0.0):
    return datetime.now(WIB) - timedelta(minutes=minutes_ago)


def _mk(last, minutes_ago=None, **extra):
    res = {
        "last": last, "error": None,
        "source_ts": _fresh_ts(minutes_ago) if minutes_ago is not None else None,
        "open": 0.0, "high": 0.0, "low": 0.0, "volume": 0.0, "prev_close": 0.0,
    }
    res.update(extra)
    return res


async def _run(coro):
    return await coro


@pytest.fixture(autouse=True)
def _reset_stockbit_guards():
    fetchers._stockbit_ttl_cache.clear()
    fetchers._stockbit_budget["window_start"] = 0.0
    fetchers._stockbit_budget["count"] = 0
    fetchers._itick_ttl_cache.clear()
    fetchers._itick_budget["window_start"] = 0.0
    fetchers._itick_budget["count"] = 0
    yield
    fetchers._stockbit_ttl_cache.clear()
    fetchers._stockbit_budget["window_start"] = 0.0
    fetchers._stockbit_budget["count"] = 0
    fetchers._itick_ttl_cache.clear()
    fetchers._itick_budget["window_start"] = 0.0
    fetchers._itick_budget["count"] = 0


def test_freshness_thresholds_match_plan():
    assert FRESHNESS_THRESHOLDS_MIN == {
        "stockbit": 2.0,
        "itick": 2.0,
        "idx_endpoint": 5.0,
        "gsheet": 10.0,
        "yfinance": 10.0,
    }


def test_source_priority_stockbit_first():
    assert SOURCE_PRIORITY["stockbit"] < SOURCE_PRIORITY["itick"] < SOURCE_PRIORITY["idx_endpoint"] < SOURCE_PRIORITY["gsheet"] < SOURCE_PRIORITY["yfinance"]


@pytest.mark.asyncio
async def test_stockbit_wins_when_valid_and_fresh(monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_gsheet_source", lambda *a, **k: _mk(100.0, minutes_ago=1, error=None))
    monkeypatch.setattr(fetchers, "fetch_yfinance_source", lambda *a, **k: _mk(101.0, minutes_ago=1, error=None))
    monkeypatch.setattr(fetchers, "fetch_idx_source", lambda *a, **k: _mk(102.0, minutes_ago=1, error=None))

    async def fake_stockbit(symbol):
        return _mk(103.0, minutes_ago=0.0, frequency=9, value=9e9,
                   foreign_buy=10, foreign_sell=2, total_bid_lot=500, total_ask_lot=100,
                   imbalance_ratio=5.0)

    monkeypatch.setattr(fetchers, "fetch_stockbit_quote_source", fake_stockbit)
    res = await pick_freshest_source("BBRI", {})
    assert res["source"] == "stockbit"
    assert res["last"] == 103.0


@pytest.mark.asyncio
async def test_stale_30min_gsheet_rejected(monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_gsheet_source", lambda *a, **k: _mk(90.0, minutes_ago=30))
    monkeypatch.setattr(fetchers, "fetch_yfinance_source", lambda *a, **k: _mk(0, error="nope"))
    monkeypatch.setattr(fetchers, "fetch_idx_source", lambda *a, **k: _mk(95.0, minutes_ago=1, frequency=3, value=1e9))
    monkeypatch.setattr(fetchers, "fetch_stockbit_quote_source", lambda s: asyncio.sleep(0) or _mk(0, error="nope"))
    res = await pick_freshest_source("BBRI", {})
    assert res["source"] == "idx_endpoint"
    assert res["last"] == 95.0


@pytest.mark.asyncio
async def test_stale_good_quality_beats_stockbit_failure(monkeypatch):
    # Stockbit unavailable -> IDX wins even if gsheet is 12 min stale
    monkeypatch.setattr(fetchers, "fetch_gsheet_source", lambda *a, **k: _mk(90.0, minutes_ago=12))
    monkeypatch.setattr(fetchers, "fetch_yfinance_source", lambda *a, **k: _mk(0, error="nope"))
    monkeypatch.setattr(fetchers, "fetch_idx_source", lambda *a, **k: _mk(95.0, minutes_ago=1, frequency=3, value=1e9))
    monkeypatch.setattr(fetchers, "fetch_stockbit_quote_source", lambda s: asyncio.sleep(0) or _mk(0, error="nope"))
    res = await pick_freshest_source("BBRI", {})
    assert res["source"] == "idx_endpoint"


@pytest.mark.asyncio
async def test_all_fail_falls_back_to_gsheet_row(monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_gsheet_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_yfinance_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_idx_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_stockbit_quote_source", lambda s: asyncio.sleep(0) or _mk(0, error="x"))
    hist_row = {
        "Price": "1234", "PriceOpen": "1200", "High": "1250", "Low": "1190",
        "Volume": "100000", "ClosePrev": "1200", "Frequency": "55", "Value": "500000000",
    }
    res = await pick_freshest_source("BBRI", hist_row)
    assert res["source"] == "gsheet_fallback"
    assert res["last"] == 1234.0
    assert res["value"] == 500000000.0


@pytest.mark.asyncio
async def test_budget_exhaustion_falls_through_to_idx(monkeypatch):
    fetchers._stockbit_budget["window_start"] = datetime.now().timestamp()
    fetchers._stockbit_budget["count"] = fetchers.STOCKBIT_BUDGET

    monkeypatch.setattr(fetchers, "fetch_gsheet_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_yfinance_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_idx_source", lambda *a, **k: _mk(95.0, minutes_ago=1, frequency=3, value=1e9))
    # Real fetch_stockbit_quote_source: budget exhausted -> falls through to IDX
    stockbit_res = await fetch_stockbit_quote_source("BBRI")
    assert stockbit_res.get("error") == "Stockbit fetch budget exhausted"

    res = await pick_freshest_source("BBRI", {})
    assert res["source"] == "idx_endpoint"
    assert res["last"] == 95.0


@pytest.mark.asyncio
async def test_stockbit_quote_source_respects_ttl_and_budget(monkeypatch):
    hits = {"n": 0}

    async def fake_fetch_orderbook(symbol):
        hits["n"] += 1
        class _Snap:
            last_price = 1000.0
            open_price = 990.0
            high = 1010.0
            low = 985.0
            volume = 500000.0
            prev_close = 980.0
            frequency = 77
            value = 1e9
            fbuy = 100
            fsell = 50
            bid_levels = [fetchers._OrderLevel(1000, 500, 3), fetchers._OrderLevel(995, 300, 2)]
            ask_levels = [fetchers._OrderLevel(1005, 200, 2), fetchers._OrderLevel(1010, 100, 1)]
        return _Snap()

    class _FakeProvider:
        def __init__(self, token):
            self.closed = False
        async def fetch_orderbook(self, symbol):
            return await fake_fetch_orderbook(symbol)
        async def close(self):
            self.closed = True

    class _FakeAuth:
        def get_cached_token(self):
            return "tok"

    import types
    fake_module = types.SimpleNamespace(StockbitProvider=_FakeProvider, auth_service=_FakeAuth())
    monkeypatch.setitem(__import__("sys").modules, "providers.stockbit_provider", fake_module)
    monkeypatch.setitem(__import__("sys").modules, "services.auth_service", fake_module)

    res1 = await fetch_stockbit_quote_source("BBRI")
    res2 = await fetch_stockbit_quote_source("BBRI")
    assert res1["last"] == 1000.0
    assert res2["last"] == 1000.0
    # Second call served from TTL cache -> no extra provider hit
    assert hits["n"] == 1
    assert res1["imbalance_ratio"] == 800 / 300
    assert res1["source_ts"] is not None


# ─── itick.org backup source ────────────────────────────────────────────────


def test_fetch_itick_quotes_batch_parses(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "tok-itick")

    def fake_get(url, params=None, headers=None, timeout=None, impersonate=None):
        assert url == "https://api.itick.org/stock/quotes"
        assert params == {"region": "ID", "codes": "ARCI,BBCA"}
        assert headers["token"] == "tok-itick"

        class _R:
            status_code = 200

            def json(self):
                return {
                    "code": 0,
                    "msg": None,
                    "data": {
                        "ARCI": {"s": "ARCI", "ld": 1000, "o": 990, "p": 980,
                                 "h": 1010, "l": 975, "t": 1765526889000,
                                 "v": 500000, "tu": 1000000000.0, "ts": 0,
                                 "ch": 20, "chp": 2.04},
                        "BBCA": {"s": "BBCA", "ld": 9000, "o": 8950, "p": 8900,
                                 "h": 9050, "l": 8930, "t": 0,
                                 "v": 100000, "tu": 900000000.0, "ts": 0,
                                 "ch": 100, "chp": 1.12},
                    },
                }

        return _R()

    monkeypatch.setattr(fetchers.requests_cf, "get", fake_get)
    out = fetch_itick_quotes_batch(["ARCI", "bbca"])
    assert set(out) == {"ARCI", "BBCA"}
    assert out["ARCI"]["last"] == 1000.0
    assert out["ARCI"]["open"] == 990.0
    assert out["ARCI"]["prev_close"] == 980.0
    assert out["ARCI"]["high"] == 1010.0
    assert out["ARCI"]["low"] == 975.0
    assert out["ARCI"]["volume"] == 500000.0
    assert out["ARCI"]["value"] == 1000000000.0
    assert out["ARCI"]["source_ts"] is not None
    assert out["ARCI"]["error"] is None
    # No exchange timestamp -> parsed anyway with source_ts None
    assert out["BBCA"]["source_ts"] is None
    assert out["BBCA"]["last"] == 9000.0


def test_fetch_itick_quotes_batch_skips_without_token(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "")
    called = {"n": 0}

    def fake_get(*a, **k):
        called["n"] += 1

    monkeypatch.setattr(fetchers.requests_cf, "get", fake_get)
    assert fetch_itick_quotes_batch(["ARCI"]) == {}
    assert called["n"] == 0


def test_fetch_itick_quotes_batch_skips_on_401(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "bad")

    class _R:
        status_code = 401

    monkeypatch.setattr(fetchers.requests_cf, "get", lambda *a, **k: _R())
    assert fetch_itick_quotes_batch(["ARCI"]) == {}


def test_fetch_itick_quotes_batch_caps_at_50_codes(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "tok")
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None, impersonate=None):
        seen["codes"] = params["codes"]

        class _R:
            status_code = 200

            def json(self):
                return {"code": 0, "data": {}}

        return _R()

    monkeypatch.setattr(fetchers.requests_cf, "get", fake_get)
    codes = [f"T{i:03d}" for i in range(60)]
    assert fetch_itick_quotes_batch(codes) == {}
    assert len(seen["codes"].split(",")) == 50


def test_fetch_itick_quotes_batch_skips_when_budget_exhausted(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "tok")
    fetchers._itick_budget["window_start"] = datetime.now().timestamp()
    fetchers._itick_budget["count"] = fetchers.ITICK_BUDGET
    called = {"n": 0}
    monkeypatch.setattr(fetchers.requests_cf, "get", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert fetch_itick_quotes_batch(["ARCI"]) == {}
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_pick_freshest_source_prefers_itick_when_stockbit_fails(monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_gsheet_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_yfinance_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_idx_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_stockbit_quote_source", lambda s: asyncio.sleep(0) or _mk(0, error="nope"))
    itick_dict = {"BBRI": _mk(5050.0, minutes_ago=0.5, frequency=9, value=5e9)}
    res = await pick_freshest_source("BBRI", {}, itick_summary_dict=itick_dict)
    assert res["source"] == "itick"
    assert res["last"] == 5050.0


@pytest.mark.asyncio
async def test_pick_freshest_source_rejects_stale_itick(monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_gsheet_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_yfinance_source", lambda *a, **k: _mk(0, error="x"))
    monkeypatch.setattr(fetchers, "fetch_idx_source", lambda *a, **k: _mk(95.0, minutes_ago=1, frequency=3, value=1e9))
    monkeypatch.setattr(fetchers, "fetch_stockbit_quote_source", lambda s: asyncio.sleep(0) or _mk(0, error="nope"))
    itick_dict = {"BBRI": _mk(5050.0, minutes_ago=30)}
    res = await pick_freshest_source("BBRI", {}, itick_summary_dict=itick_dict)
    assert res["source"] == "idx_endpoint"
    assert res["last"] == 95.0


@pytest.mark.asyncio
async def test_fetch_itick_snapshot_builds_orderbook_snap(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "tok")

    def fake_get(url, params=None, headers=None, timeout=None, impersonate=None):
        class _R:
            status_code = 200

            def json(self):
                if "depth" in url:
                    return {"code": 0, "data": {"s": "ARCI", "a": [
                        {"po": 1, "p": 1005, "v": 200, "o": 2},
                        {"po": 2, "p": 1010, "v": 100, "o": 1},
                    ], "b": [
                        {"po": 1, "p": 1000, "v": 500, "o": 3},
                        {"po": 2, "p": 995, "v": 300, "o": 2},
                    ]}}
                return {"code": 0, "data": {"ARCI": {
                    "s": "ARCI", "ld": 1000, "o": 990, "p": 980,
                    "h": 1010, "l": 975, "t": 1765526889000,
                    "v": 500000, "tu": 1000000000.0, "ts": 0,
                    "ch": 20, "chp": 2.04,
                }}}

        return _R()

    monkeypatch.setattr(fetchers.requests_cf, "get", fake_get)
    snap = await fetch_itick_snapshot("ARCI")
    assert snap is not None
    assert snap.last_price == 1000.0
    assert snap.open_price == 990.0
    assert snap.high == 1010.0
    assert snap.low == 975.0
    assert snap.volume == 500000.0
    assert snap.prev_close == 980.0
    assert len(snap.bid_levels) == 2
    assert len(snap.ask_levels) == 2
    assert snap.total_bid_lot == 800
    assert sum(l.lot for l in snap.ask_levels) == 300
    assert snap.imbalance_ratio == 800 / 300
    assert snap.bid_levels[0].price == 1000.0
    assert snap.bid_levels[0].lot == 500
    assert snap.bid_levels[0].freq == 3
    assert snap.ask_levels[0].price == 1005.0
    assert snap.ask_levels[0].lot == 200


@pytest.mark.asyncio
async def test_fetch_itick_snapshot_skips_when_budget_low(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "tok")
    fetchers._itick_budget["window_start"] = datetime.now().timestamp()
    fetchers._itick_budget["count"] = fetchers.ITICK_BUDGET - 1  # only 1 call left
    called = {"n": 0}
    monkeypatch.setattr(fetchers.requests_cf, "get", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert await fetch_itick_snapshot("ARCI") is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_fetch_itick_snapshot_skips_without_token(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "")
    called = {"n": 0}
    monkeypatch.setattr(fetchers.requests_cf, "get", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    assert await fetch_itick_snapshot("ARCI") is None
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_fetch_itick_snapshot_returns_none_on_401(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "bad")

    class _R:
        status_code = 401

    monkeypatch.setattr(fetchers.requests_cf, "get", lambda *a, **k: _R())
    assert await fetch_itick_snapshot("ARCI") is None


def test_fetch_itick_quotes_batch_respects_ttl_cache(monkeypatch):
    monkeypatch.setattr(fetchers.config, "ITICK_TOKEN", "tok")
    hits = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None, impersonate=None):
        hits["n"] += 1

        class _R:
            status_code = 200

            def json(self):
                return {"code": 0, "data": {"ARCI": {
                    "s": "ARCI", "ld": 1000, "o": 990, "p": 980,
                    "h": 1010, "l": 975, "t": 1765526889000,
                    "v": 500000, "tu": 1000000000.0, "ts": 0,
                    "ch": 20, "chp": 2.04,
                }}}

        return _R()

    monkeypatch.setattr(fetchers.requests_cf, "get", fake_get)
    out1 = fetch_itick_quotes_batch(["ARCI"])
    out2 = fetch_itick_quotes_batch(["ARCI"])
    assert out1["ARCI"]["last"] == 1000.0
    assert out2 == out1
    assert hits["n"] == 1  # second call served from 60s TTL cache


def test_fetch_news_for_tickers_silences_yfinance_noise(caplog, monkeypatch):
    """Faulty Yahoo news responses must not spam the yfinance logger."""
    import logging

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def news(self):
            logging.getLogger("yfinance").error(
                f"{self.symbol}: Failed to retrieve the news and received faulty response instead."
            )
            return []

    monkeypatch.setattr(fetchers.yf, "Ticker", FakeTicker)

    yf_logger = logging.getLogger("yfinance")
    prev_level = yf_logger.level
    try:
        with caplog.at_level(logging.ERROR, logger="yfinance"):
            res = fetchers.fetch_news_for_tickers(["MMLP", "MNCN"])
    finally:
        yf_logger.setLevel(prev_level)

    assert res == {}
    assert "Failed to retrieve the news" not in caplog.text
    assert yf_logger.level == prev_level  # level restored after the batch


def test_fetch_news_for_tickers_still_parses_valid_news(monkeypatch):
    """The logger-suppression wrapper must not change normal news parsing."""

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def news(self):
            return [
                {"title": "BBCA laba naik tajam", "providerPublishTime": 1700000000},
                {"title": "BBCA umumkan dividen", "providerPublishTime": 1700000100},
            ]

    monkeypatch.setattr(fetchers.yf, "Ticker", FakeTicker)
    res = fetchers.fetch_news_for_tickers(["BBCA"])
    assert res["BBCA"]["count"] == 2
    assert res["BBCA"]["latest"] == "BBCA laba naik tajam"
    assert res["BBCA"]["sentiment"] > 0
