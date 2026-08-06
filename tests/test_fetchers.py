import asyncio
from datetime import datetime, timedelta

import pytest

import data.fetchers as fetchers
from data.fetchers import (
    FRESHNESS_THRESHOLDS_MIN,
    SOURCE_PRIORITY,
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
    yield
    fetchers._stockbit_ttl_cache.clear()
    fetchers._stockbit_budget["window_start"] = 0.0
    fetchers._stockbit_budget["count"] = 0


def test_freshness_thresholds_match_plan():
    assert FRESHNESS_THRESHOLDS_MIN == {
        "stockbit": 2.0,
        "idx_endpoint": 5.0,
        "gsheet": 10.0,
        "yfinance": 10.0,
    }


def test_source_priority_stockbit_first():
    assert SOURCE_PRIORITY["stockbit"] < SOURCE_PRIORITY["idx_endpoint"] < SOURCE_PRIORITY["gsheet"] < SOURCE_PRIORITY["yfinance"]


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
