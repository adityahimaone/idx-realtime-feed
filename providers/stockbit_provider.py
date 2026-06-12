"""
Provider: Stockbit exodus API (unofficial).

Endpoint yang dipakai (hasil reverse-engineering komunitas, lihat
SorataBaka/New-Composite-API):

    GET https://exodus.stockbit.com/stream/v3/symbol/{TICKER}

Butuh header Authorization: Bearer {token} dari hasil login
(lihat services/auth_service.py).

Rate limit observasi: ~40 request / 5 menit per token. Untuk watchlist
10-30 ticker dengan interval 30-60s, pastikan ada jitter antar-request
(lihat services/sync_service.py) supaya tidak burst.

NOTE: struktur response di bawah adalah PLACEHOLDER. Sebelum implementasi
penuh, jalankan Phase 0 (spike) dari plan.md: hit endpoint ini manual pakai
token dari browser devtools, lalu sesuaikan `_parse_response()` dengan
struktur JSON asli (terutama: apakah orderbook dikirim 5 level atau cuma
best bid/ask).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from core.logger import logger
from schemas.orderbook import DataSource, OrderbookSnapshot, PriceLevel

BASE_URL = "https://exodus.stockbit.com/stream/v3/symbol"


class StockbitProvider:
    def __init__(self, token: str) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_orderbook(self, ticker: str) -> OrderbookSnapshot | None:
        """Fetch snapshot orderbook untuk satu ticker.

        Return None kalau request gagal (caller harus fallback ke
        RTI provider / trigger re-auth kalau 401).
        """
        try:
            resp = await self._client.get(f"/{ticker.upper()}")
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                logger.warning(f"stockbit: token expired/invalid for {ticker}")
            else:
                logger.warning(f"stockbit: HTTP {exc.response.status_code} for {ticker}")
            return None
        except httpx.HTTPError as exc:
            logger.warning(f"stockbit: request error for {ticker}: {exc}")
            return None

        return self._parse_response(ticker, resp.json())

    @staticmethod
    def _parse_response(ticker: str, data: dict) -> OrderbookSnapshot:
        """PLACEHOLDER parser — sesuaikan key sesuai struktur asli exodus API.

        Asumsi sementara struktur (TODO Phase 0, verify):
        {
          "data": {
            "lastprice": 8550,
            "prevclose": 8400,
            "bid": [{"price": 8550, "lot": 1200, "freq": 34}, ...],
            "ask": [{"price": 8575, "lot": 800, "freq": 21}, ...]
          }
        }
        """
        payload = data.get("data", {})

        bid_levels = [
            PriceLevel(price=lvl["price"], lot=lvl["lot"], freq=lvl.get("freq", 0))
            for lvl in payload.get("bid", [])
        ]
        ask_levels = [
            PriceLevel(price=lvl["price"], lot=lvl["lot"], freq=lvl.get("freq", 0))
            for lvl in payload.get("ask", [])
        ]

        return OrderbookSnapshot(
            ticker=ticker.upper(),
            timestamp=datetime.now(timezone.utc),
            source=DataSource.STOCKBIT,
            last_price=payload.get("lastprice", 0.0),
            prev_close=payload.get("prevclose", 0.0),
            bid_levels=bid_levels,
            ask_levels=ask_levels,
        )
