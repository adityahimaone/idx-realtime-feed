"""
Sync service: orchestrator utama untuk idx-realtime-feed.
Updated: supports staging sheet name override for [IRW] suffix.
"""

from __future__ import annotations

import asyncio
import random

from core.config import config
from core.logger import logger
from providers.rti_provider import RTIProvider
from providers.stockbit_provider import StockbitProvider
from repositories.sheets_repository import SheetsRepository, sheets_repository
from repositories.sqlite_repository import sqlite_repository
from schemas.orderbook import OrderbookSnapshot
from services.auth_service import auth_service

MIN_JITTER_SECONDS = 1.0
MAX_JITTER_SECONDS = 4.0

STAGING_SHEET_NAME = "Realtime_Watchlist [IRW]"


class SyncService:
    def __init__(self) -> None:
        self._rti_provider = RTIProvider()
        self._consecutive_failures = 0

    async def run_forever(self) -> None:
        logger.info("sync: starting perpetual loop")
        while True:
            try:
                await self.run_once()
            except KeyboardInterrupt:
                logger.info("sync: received interrupt, shutting down")
                return
            except Exception:
                logger.exception("sync: unexpected error in cycle — continuing")

            logger.info(f"sync: sleeping {config.SYNC_INTERVAL_SECONDS}s")
            await asyncio.sleep(config.SYNC_INTERVAL_SECONDS)

    async def run_once(self) -> None:
        watchlist = sheets_repository.get_watchlist()
        if not watchlist:
            logger.warning("sync: watchlist empty, skipping cycle")
            return

        logger.info(f"sync: cycle start — {len(watchlist)} tickers: {watchlist}")

        token = await auth_service.get_token()
        stockbit_provider = StockbitProvider(token)

        snapshots: list[OrderbookSnapshot] = []
        try:
            for ticker in watchlist:
                snapshot = await self._fetch_with_fallback(stockbit_provider, ticker)
                if snapshot is not None:
                    snapshots.append(snapshot)
                    sqlite_repository.save_snapshot(snapshot)
                    self._consecutive_failures = 0
                else:
                    self._consecutive_failures += 1

                await asyncio.sleep(random.uniform(MIN_JITTER_SECONDS, MAX_JITTER_SECONDS))
        finally:
            await stockbit_provider.close()

        if snapshots:
            # Write to primary sheet (new - Realtime_Watchlist)
            try:
                sheets_repository.write_snapshots(snapshots)
            except Exception as exc:
                logger.error(f"sheets: write failed: {exc}")

            # Write to staging (MAS - Realtime_Watchlist [IRW])
            if config.MAS_STAGING_SPREADSHEET_ID:
                try:
                    staging_repo = SheetsRepository()
                    staging_repo.write_snapshots(snapshots, sheet_id=config.MAS_STAGING_SPREADSHEET_ID, sheet_name=STAGING_SHEET_NAME)
                    logger.info(f"staging: wrote {len(snapshots)} snapshots to '{STAGING_SHEET_NAME}'")
                except Exception as exc:
                    logger.error(f"staging: write failed: {exc}")
            # Also update Dashboard [IRW] + Dashboard Formula [IRW] on staging
            if config.MAS_STAGING_SPREADSHEET_ID:
                try:
                    staging_repo = SheetsRepository()
                    staging_repo.write_dashboard(
                        snapshots,
                        sheet_id=config.MAS_STAGING_SPREADSHEET_ID,
                        realtime_sheet_name=STAGING_SHEET_NAME,
                    )
                    logger.info(f"staging: updated Dashboard [IRW] + Dashboard Formula [IRW]")
                except Exception as exc:
                    logger.error(f"staging: dashboard write failed: {exc}")
        else:
            logger.warning("sync: no snapshots fetched this cycle")
            if self._consecutive_failures >= 3:
                logger.error(f"sync: {self._consecutive_failures} consecutive failures — check providers or auth")

    async def _fetch_with_fallback(self, stockbit_provider: StockbitProvider, ticker: str) -> OrderbookSnapshot | None:
        snapshot = await stockbit_provider.fetch_orderbook(ticker)
        if snapshot is not None:
            return snapshot
        logger.info(f"sync: stockbit failed for {ticker}, trying RTI fallback")
        snapshot = await self._rti_provider.fetch_orderbook(ticker)
        if snapshot is None:
            logger.warning(f"sync: both providers failed for {ticker}")
        return snapshot


sync_service = SyncService()
