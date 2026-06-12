"""
Provider: RTI Business (fallback).

Dipakai kalau Stockbit provider gagal (token expired, rate limit, dst).
RTI Business render data via JS, jadi kita pakai ObscuraClient untuk
ambil DOM setelah render.

NOTE: selector di bawah PLACEHOLDER — sesuaikan dengan struktur HTML
RTI Business yang sebenarnya saat implementasi (Phase 5 di plan.md).
"""

from __future__ import annotations

from datetime import datetime, timezone

from providers.obscura_client import obscura_client
from core.logger import logger
from schemas.orderbook import DataSource, OrderbookSnapshot, PriceLevel

RTI_STOCK_URL = "https://www.rti.co.id/stock/{ticker}"


class RTIProvider:
    async def fetch_orderbook(self, ticker: str) -> OrderbookSnapshot | None:
        url = RTI_STOCK_URL.format(ticker=ticker.upper())

        try:
            async with obscura_client.page() as page:
                await page.goto(url, wait_until="networkidle")

                # PLACEHOLDER selectors — cek struktur asli halaman RTI.
                last_price = await page.locator(".price-last").text_content()
                prev_close = await page.locator(".price-prevclose").text_content()

                bid_rows = await page.locator(".orderbook-bid-row").all()
                ask_rows = await page.locator(".orderbook-ask-row").all()

                bid_levels = [await self._parse_row(row) for row in bid_rows]
                ask_levels = [await self._parse_row(row) for row in ask_rows]

        except Exception as exc:  # noqa: BLE001 - fallback provider, log & return None
            logger.warning(f"rti: failed to fetch {ticker}: {exc}")
            return None

        return OrderbookSnapshot(
            ticker=ticker.upper(),
            timestamp=datetime.now(timezone.utc),
            source=DataSource.RTI,
            last_price=self._to_float(last_price),
            prev_close=self._to_float(prev_close),
            bid_levels=bid_levels,
            ask_levels=ask_levels,
        )

    @staticmethod
    async def _parse_row(row) -> PriceLevel:
        price = await row.locator(".price").text_content()
        lot = await row.locator(".lot").text_content()
        return PriceLevel(price=RTIProvider._to_float(price), lot=RTIProvider._to_int(lot))

    @staticmethod
    def _to_float(value: str | None) -> float:
        if not value:
            return 0.0
        return float(value.replace(",", "").strip())

    @staticmethod
    def _to_int(value: str | None) -> int:
        if not value:
            return 0
        return int(value.replace(",", "").strip())
