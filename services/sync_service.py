"""
Sync service: orchestrator utama untuk idx-realtime-feed.
Updated: supports staging sheet name override for [IRW] suffix.
"""

from __future__ import annotations

import asyncio
import random

from rich.console import Console
from rich.table import Table

from core.config import config
from core.logger import logger
from providers.rti_provider import RTIProvider
from providers.stockbit_provider import StockbitProvider
from repositories.sheets_repository import SheetsRepository, sheets_repository
from repositories.sqlite_repository import sqlite_repository
from schemas.orderbook import DataSource, OrderbookSnapshot
from services.auth_service import auth_service

console = Console()

MIN_JITTER_SECONDS = 1.0
MAX_JITTER_SECONDS = 4.0

STAGING_SHEET_NAME = "Realtime_Watchlist [IRW]"


class SyncService:
    def __init__(self) -> None:
        self._rti_provider = RTIProvider()
        self._consecutive_failures = 0

    async def run_forever(self) -> None:
        logger.info("🔄 [bold cyan]Starting perpetual loop[/bold cyan]...")
        while True:
            try:
                await self.run_once()

                interval = config.SYNC_INTERVAL_SECONDS
                with console.status(
                    f"[bold blue]😴 Sleeping {interval}s before next cycle...[/bold blue]",
                    spinner="clock",
                ) as status:
                    for remaining in range(interval, 0, -1):
                        status.update(
                            f"[bold blue]😴 Sleeping {remaining}s before next cycle...[/bold blue] [dim](press Ctrl+C to exit)[/dim]"
                        )
                        await asyncio.sleep(1)
            except KeyboardInterrupt:
                logger.info("🛑 [bold yellow]Received interrupt, shutting down[/bold yellow]")
                return
            except Exception:
                logger.exception("💥 [bold red]Unexpected error in cycle — continuing[/bold red]")

    async def run_once(self) -> None:
        watchlist = sheets_repository.get_watchlist()
        if not watchlist:
            logger.warning("⚠️ [bold yellow]Watchlist empty, skipping cycle[/bold yellow]")
            return

        logger.info(f"⚡ [bold cyan]Cycle Start[/bold cyan] — fetching [yellow]{len(watchlist)}[/yellow] tickers: [magenta]{watchlist}[/magenta]")

        token = await auth_service.get_token()
        stockbit_provider = StockbitProvider(token)

        snapshots: list[OrderbookSnapshot] = []
        try:
            for ticker in watchlist:
                with console.status(f"[bold yellow]🔍 Fetching {ticker}...[/bold yellow]", spinner="dots") as status:
                    snapshot = await self._fetch_with_fallback(stockbit_provider, ticker)

                if snapshot is not None:
                    snapshots.append(snapshot)
                    sqlite_repository.save_snapshot(snapshot)
                    self._consecutive_failures = 0
                    chg_style = "bold green" if snapshot.change_pct > 0 else ("bold red" if snapshot.change_pct < 0 else "dim")
                    chg_sign = "+" if snapshot.change_pct > 0 else ""
                    logger.info(
                        f"🟢 [bold green]Success[/bold green] | [cyan]{ticker:<5}[/cyan] | "
                        f"Last: [bold]{snapshot.last_price:,.0f}[/bold] | "
                        f"Chg: [{chg_style}]{chg_sign}{snapshot.change_pct:.2f}%[/{chg_style}] | "
                        f"Src: [bold blue]{snapshot.source.value}[/bold blue]"
                    )
                else:
                    self._consecutive_failures += 1
                    logger.warning(f"❌ [bold red]Failed[/bold red] | [cyan]{ticker:<5}[/cyan] | Both providers failed")

                jitter_time = random.uniform(MIN_JITTER_SECONDS, MAX_JITTER_SECONDS)
                with console.status(f"[dim]⏳ Jitter sleep {jitter_time:.1f}s...[/dim]", spinner="bouncingBar") as status:
                    await asyncio.sleep(jitter_time)
        finally:
            await stockbit_provider.close()

        if snapshots:
            # Build and display the cycle summary table
            table = Table(
                title=f"📊 [bold cyan]IDX Watchlist Summary[/bold cyan] (Cycle End)",
                title_justify="left",
                show_header=True,
                header_style="bold magenta",
                border_style="dim",
            )
            table.add_column("Ticker", style="cyan", justify="left")
            table.add_column("Last Price", justify="right")
            table.add_column("Change %", justify="right")
            table.add_column("Bid Lot", justify="right")
            table.add_column("Ask Lot", justify="right")
            table.add_column("Imbalance", justify="right")
            table.add_column("Source", justify="center")

            for snap in snapshots:
                chg_style = "bold green" if snap.change_pct > 0 else ("bold red" if snap.change_pct < 0 else "dim")
                chg_sign = "+" if snap.change_pct > 0 else ""
                imbalance_str = f"{snap.imbalance_ratio:.2f}" if snap.imbalance_ratio is not None else "N/A"
                table.add_row(
                    snap.ticker,
                    f"{snap.last_price:,.0f}",
                    f"[{chg_style}]{chg_sign}{snap.change_pct:.2f}%[/{chg_style}]",
                    f"{snap.total_bid_lot:,.0f}",
                    f"{snap.total_ask_lot:,.0f}",
                    imbalance_str,
                    "[bold blue]Stockbit[/]" if snap.source == DataSource.STOCKBIT else "[bold yellow]RTI[/]",
                )

            console.print(table)

            # Write to primary sheet (new - Realtime_Watchlist)
            try:
                sheets_repository.write_snapshots(snapshots)
                sheets_repository.update_rekomendasi_beli()
            except Exception as exc:
                logger.error(f"📤 [bold red]Sheets[/bold red] | Primary write/RB failed: {exc}")

            # Write to staging (MAS - Realtime_Watchlist [IRW])
            if config.MAS_STAGING_SPREADSHEET_ID:
                try:
                    staging_repo = SheetsRepository()
                    staging_repo.write_snapshots(snapshots, sheet_id=config.MAS_STAGING_SPREADSHEET_ID, sheet_name=STAGING_SHEET_NAME)
                    logger.info(f"📤 [bold green]Staging[/bold green] | Wrote {len(snapshots)} snapshots to '{STAGING_SHEET_NAME}'")
                except Exception as exc:
                    logger.error(f"📤 [bold red]Staging[/bold red] | Write failed: {exc}")
            # Also update Dashboard [IRW] + Dashboard Formula [IRW] on staging
            if config.MAS_STAGING_SPREADSHEET_ID:
                try:
                    staging_repo = SheetsRepository()
                    staging_repo.write_dashboard(
                        snapshots,
                        sheet_id=config.MAS_STAGING_SPREADSHEET_ID,
                        realtime_sheet_name=STAGING_SHEET_NAME,
                    )
                    logger.info("📤 [bold green]Staging[/bold green] | Updated Dashboard [IRW] + Dashboard Formula [IRW]")
                    staging_repo.update_rekomendasi_beli(sheet_id=config.MAS_STAGING_SPREADSHEET_ID)
                    logger.info("📤 [bold green]Staging[/bold green] | Updated Rekomendasi Beli [IRW]")
                except Exception as exc:
                    logger.error(f"📤 [bold red]Staging[/bold red] | Dashboard/RB write failed: {exc}")
        else:
            logger.warning("⚠️ [bold yellow]No snapshots fetched this cycle[/bold yellow]")
            if self._consecutive_failures >= 3:
                logger.error(f"🚨 [bold red]{self._consecutive_failures} consecutive failures[/bold red] — check providers or auth")

    async def _fetch_with_fallback(self, stockbit_provider: StockbitProvider, ticker: str) -> OrderbookSnapshot | None:
        snapshot = await stockbit_provider.fetch_orderbook(ticker)
        if snapshot is not None:
            return snapshot
        logger.info(f"⚠️ [bold yellow]Stockbit failed for {ticker}[/bold yellow], trying RTI fallback...")
        snapshot = await self._rti_provider.fetch_orderbook(ticker)
        if snapshot is None:
            logger.warning(f"🚨 [bold red]Both providers failed for {ticker}[/bold red]")
        return snapshot


sync_service = SyncService()
