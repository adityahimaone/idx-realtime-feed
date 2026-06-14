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

BASE_URL = "https://exodus.stockbit.com/company-price-feed/v2/orderbook/companies"


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

        Endpoint: /company-price-feed/v2/orderbook/companies/{TICKER}
        Return None kalau request gagal.
        """
        try:
            resp = await self._client.get(f"/{ticker.upper()}")
            
            # If token gets unauthorized, try to refresh and retry
            if resp.status_code == 401:
                logger.warning(f"stockbit: token unauthorized (401) for {ticker}. Attempting to auto-refresh...")
                from services.auth_service import auth_service
                new_token = await auth_service.refresh_token(force=True)
                if new_token:
                    self._token = new_token
                    self._client.headers["Authorization"] = f"Bearer {new_token}"
                    # Retry once
                    logger.info(f"stockbit: retrying fetch for {ticker} with new token...")
                    resp = await self._client.get(f"/{ticker.upper()}")
                    resp.raise_for_status()
                else:
                    logger.error("stockbit: failed to auto-refresh token on 401.")
                    return None
            else:
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(f"stockbit: HTTP {exc.response.status_code} for {ticker}")
            return None
        except httpx.HTTPError as exc:
            logger.warning(f"stockbit: request error for {ticker}: {exc}")
            return None

        return self._parse_response(ticker, resp.json())

    @staticmethod
    def _parse_response(ticker: str, data: dict) -> OrderbookSnapshot:
        """Parse exodus orderbook v2 response.

        Response actual:
        {
          "data": {
            "lastprice": 6075,
            "previous": 5825,
            "open": 6000,
            "high": 6100,
            "low": 5900,
            "change": 250,
            "volume": 235263900,
            "bid": [{"price": "6075", "que_num": "165", "volume": "2264100"}, ...],
            "offer": [{"price": "...", "que_num": "...", "volume": "..."}, ...]
          }
        }

        Note: volume = shares (÷100 = lot), key ask adalah "offer" bukan "ask".
        """
        payload = data.get("data", {})

        def _to_lot(vol_str: str) -> int:
            """Convert volume string (shares) to lot (100 shares = 1 lot)."""
            try:
                return int(vol_str) // 100
            except (ValueError, TypeError):
                return 0

        bid_levels = [
            PriceLevel(
                price=float(lvl["price"]),
                lot=_to_lot(lvl.get("volume", "0")),
                freq=int(lvl.get("que_num", 0)),
            )
            for lvl in payload.get("bid", [])
            if lvl.get("price")
        ]
        # "offer" = ask side
        ask_levels = [
            PriceLevel(
                price=float(lvl["price"]),
                lot=_to_lot(lvl.get("volume", "0")),
                freq=int(lvl.get("que_num", 0)),
            )
            for lvl in payload.get("offer", [])
            if lvl.get("price")
        ]

        return OrderbookSnapshot(
            ticker=ticker.upper(),
            timestamp=datetime.now(timezone.utc),
            source=DataSource.STOCKBIT,
            last_price=float(payload.get("lastprice", 0)),
            prev_close=float(payload.get("previous", 0)),
            high=float(payload.get("high", 0)),
            low=float(payload.get("low", 0)),
            open_price=float(payload.get("open", 0)),
            change=int(payload.get("change", 0)),
            volume=float(payload.get("volume", 0)),
            fbuy=float(payload.get("fbuy", 0)),
            fsell=float(payload.get("fsell", 0)),
            fnet=float(payload.get("fnet", 0)),
            ara_price=float(payload.get("next_ara", {}).get("value", "0").replace(",", "") or 0),
            arb_price=float(payload.get("next_arb", {}).get("value", "0").replace(",", "") or 0),
            frequency=int(payload.get("frequency", 0)),
            value=float(payload.get("value", 0)),
            average_price=float(payload.get("average", 0)),
            bid_levels=bid_levels,
            ask_levels=ask_levels,
        )
