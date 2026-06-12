"""
Sync service: orchestrator utama untuk idx-realtime-feed.

Loop per cycle:
 1. Integrity check (structure + anti-rollback)
 2. Ambil watchlist dari sheet Alpha_Watchlist
 3. Untuk tiap ticker (dengan jitter):
      - fetch via StockbitProvider
      - kalau gagal -> fallback ke RTIProvider
 4. Simpan semua snapshot ke SQLite (history)
 5. Batch-write ke sheet Realtime_Watchlist (dengan integrity guard pre-check)
 6. Sleep SYNC_INTERVAL_SECONDS, ulangi
"""

from __future__ import annotations

import asyncio
import random

from core.config import config
from core.logger import logger
from providers.rti_provider import RTIProvider
from providers.stockbit_provider import StockbitProvider
from repositories.sheets_repository import sheets_repository
from repositories.sqlite_repository import sqlite_repository
from schemas.orderbook import OrderbookSnapshot
from services.auth_service import auth_service

MIN_JITTER_SECONDS = 1.0
MAX_JITTER_SECONDS = 4.0


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
        # ── Integrity check ──
        try:
            from repositories.integrity_guard import load_manifest
            manifest = load_manifest()
            logger.debug(f"integrity: manifest v{manifest.get('version')} loaded")
        except Exception as exc:
            logger.error(f"integrity: cannot load manifest — aborting cycle: {exc}")
            return

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

                await asyncio.sleep(
                    random.uniform(MIN_JITTER_SECONDS, MAX_JITTER_SECONDS)
                )
        finally:
            await stockbit_provider.close()

        if snapshots:
            try:
                sheets_repository.write_snapshots(snapshots)
            except Exception as exc:
                logger.error(f"sheets: write failed: {exc}")
            try:
                sheets_repository.write_dashboard(snapshots)
            except Exception as exc:
                logger.error(f"dashboard: write failed: {exc}")
        else:
            logger.warning("sync: no snapshots fetched this cycle")
            if self._consecutive_failures >= 3:
                logger.error(
                    f"sync: {self._consecutive_failures} consecutive failures — "
                    "check providers or auth"
                )

    async def _fetch_with_fallback(
        self, stockbit_provider: StockbitProvider, ticker: str
    ) -> OrderbookSnapshot | None:
        snapshot = await stockbit_provider.fetch_orderbook(ticker)
        if snapshot is not None:
            return snapshot

        # Stockbit gagal -> fallback ke RTI
        logger.info(f"sync: stockbit failed for {ticker}, trying RTI fallback")
        snapshot = await self._rti_provider.fetch_orderbook(ticker)
        if snapshot is None:
            logger.warning(f"sync: both providers failed for {ticker}")
        return snapshot


sync_service = SyncService()
