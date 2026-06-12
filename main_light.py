#!/usr/bin/env python3
"""
Entrypoint: idx-realtime-feed (Light Version)

Jalankan sebagai PM2 process (bukan cron), supaya event loop + token
cache tetap hidup antar-cycle:

    pm2 start main_light.py --interpreter python3 --name idx-realtime-feed-light
"""

from __future__ import annotations

import asyncio
import sys
import os
from datetime import datetime, timezone
import httpx

# Set PAGER to cat to avoid paged output in subprocesses
os.environ["PAGER"] = "cat"

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED

from core.config import config
from core.logger import logger
from services.auth_service import auth_service
from repositories.sheets_repository import sheets_repository
from repositories.sqlite_repository import sqlite_repository
from schemas.orderbook import DataSource, OrderbookSnapshot
from ticker import calculate_ara_arb_fallbacks

console = Console()

LIGHT_SHEET_NAME = "Light Watchlist [IRW]"


async def print_banner() -> None:
    banner_text = Text()
    banner_text.append("📈 IDX REALTIME FEED (LIGHT MODE) v0.1.0\n", style="bold green")
    banner_text.append("Batch synchronization between Stockbit Watchlist and Google Sheets\n\n", style="italic dim")

    banner_text.append("Configuration Details:\n", style="bold cyan")
    banner_text.append("  • Interval      : ", style="dim")
    banner_text.append(f"{config.SYNC_INTERVAL_SECONDS} seconds\n", style="bold yellow")

    banner_text.append("  • Primary Sheet : ", style="dim")
    banner_text.append(f"{config.MARKET_ALPHA_SPREADSHEET_ID or 'Not Set'}\n", style="bold magenta")

    banner_text.append("  • Staging Sheet : ", style="dim")
    banner_text.append(f"{config.MAS_STAGING_SPREADSHEET_ID or 'Not Set'}\n", style="bold magenta")

    banner_text.append("  • SQLite DB     : ", style="dim")
    banner_text.append(f"{config.SQLITE_PATH}\n", style="blue")

    banner_text.append("  • Watchlist ID  : ", style="dim")
    banner_text.append(f"{config.STOCKBIT_WATCHLIST_ID}\n", style="green")

    panel = Panel(
        banner_text,
        border_style="bold green",
        expand=False,
        title="[bold]System Startup (Light Mode)[/bold]",
        subtitle="[dim]Press Ctrl+C to exit safely[/dim]"
    )
    console.print(panel)


async def run_once() -> None:
    logger.info("⚡ [bold cyan]Batch Cycle Start (Light Mode)[/bold cyan]...")

    token = await auth_service.get_token()
    if not token:
        logger.error("❌ Auth token unavailable. Skipping cycle.")
        return

    wid = config.STOCKBIT_WATCHLIST_ID
    url = f"https://exodus.stockbit.com/watchlist/{wid}?page=1&limit=100&setfincol=1"

    snapshots: list[OrderbookSnapshot] = []

    with console.status("[bold yellow]Fetching batch watchlist data...[/bold yellow]", spinner="dots") as status:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error(f"❌ Failed to fetch watchlist batch: {exc}")
            return

    results = data.get("data", {}).get("result", [])
    if not results:
        logger.warning("⚠️ Watchlist batch returned empty results. Skipping write.")
        return

    logger.info(f"🟢 [bold green]Success[/bold green] | Retrieved {len(results)} watchlist items in a single call")

    for item in results:
        symbol = item.get("symbol", "").upper()
        if not symbol:
            continue

        last_price = float(item.get("last", 0.0) or 0.0)
        prev_close = float(item.get("previous", 0.0) or 0.0)
        
        # Calculate fallback ARA/ARB from IDX rules
        ara, arb = calculate_ara_arb_fallbacks(prev_close)

        # Estimate High/Low from the intraday price tick array if available
        prices = [float(x) for x in item.get("prices", []) if x]
        high_val = max(prices) if prices else last_price
        low_val = min(prices) if prices else last_price
        open_val = prices[0] if prices else last_price
        
        change_pct = float(item.get("percent", 0.0) or 0.0)
        change_val = int(float(item.get("change", 0.0) or 0.0))
        volume = float(item.get("volume", 0.0) or 0.0)

        snap = OrderbookSnapshot(
            ticker=symbol,
            timestamp=datetime.now(timezone.utc),
            source=DataSource.STOCKBIT,
            last_price=last_price,
            prev_close=prev_close,
            high=high_val,
            low=low_val,
            open_price=open_val,
            change=change_val,
            volume=volume,
            fbuy=0.0,
            fsell=0.0,
            fnet=0.0,
            ara_price=ara,
            arb_price=arb,
            frequency=0,
            value=0.0,
            average_price=0.0,
            bid_levels=[],
            ask_levels=[]
        )
        snapshots.append(snap)
        
        # Save history locally for backtesting / audit logs
        try:
            sqlite_repository.save_snapshot(snap)
        except Exception as e:
            logger.warning(f"Failed to save {symbol} to SQLite history: {e}")

    if snapshots:
        # Build and display the cycle summary table
        table = Table(
            title=f"📊 [bold cyan]IDX Watchlist Batch Summary[/bold cyan] (Cycle End)",
            title_justify="left",
            show_header=True,
            header_style="bold magenta",
            border_style="dim",
        )
        table.add_column("Ticker", style="cyan", justify="left")
        table.add_column("Last Price", justify="right")
        table.add_column("Change %", justify="right")
        table.add_column("Volume (Shares)", justify="right")
        table.add_column("Estimated High", justify="right")
        table.add_column("Estimated Low", justify="right")

        for snap in snapshots:
            chg_style = "bold green" if snap.change_pct > 0 else ("bold red" if snap.change_pct < 0 else "dim")
            chg_sign = "+" if snap.change_pct > 0 else ""
            table.add_row(
                snap.ticker,
                f"{snap.last_price:,.0f}",
                f"[{chg_style}]{chg_sign}{snap.change_pct:.2f}%[/{chg_style}]",
                f"{snap.volume:,.0f}",
                f"{snap.high:,.0f}",
                f"{snap.low:,.0f}",
            )

        console.print(table)

        # Write to primary sheet (Light Watchlist [IRW])
        try:
            sheets_repository.write_snapshots(snapshots, sheet_name=LIGHT_SHEET_NAME)
        except Exception as exc:
            logger.error(f"📤 [bold red]Sheets[/bold red] | Primary write failed: {exc}")

        # Write to staging (MAS - Light Watchlist [IRW] + Dashboard calculations)
        if config.MAS_STAGING_SPREADSHEET_ID:
            try:
                sheets_repository.write_snapshots(snapshots, sheet_id=config.MAS_STAGING_SPREADSHEET_ID, sheet_name=LIGHT_SHEET_NAME)
                logger.info(f"📤 [bold green]Staging[/bold green] | Wrote {len(snapshots)} snapshots to '{LIGHT_SHEET_NAME}'")
            except Exception as exc:
                logger.error(f"📤 [bold red]Staging[/bold red] | Write failed: {exc}")

            try:
                sheets_repository.write_dashboard(
                    snapshots,
                    sheet_id=config.MAS_STAGING_SPREADSHEET_ID,
                    realtime_sheet_name=LIGHT_SHEET_NAME,
                )
                logger.info("📤 [bold green]Staging[/bold green] | Updated Dashboard [IRW] + Dashboard Formula [IRW]")
            except Exception as exc:
                logger.error(f"📤 [bold red]Staging[/bold red] | Dashboard write failed: {exc}")


async def run_forever() -> None:
    await print_banner()
    logger.info("🔄 [bold cyan]Starting perpetual batch sync loop[/bold cyan]...")
    while True:
        try:
            await run_once()

            interval = config.SYNC_INTERVAL_SECONDS
            with console.status(
                f"[bold blue]😴 Sleeping {interval}s before next batch cycle...[/bold blue]",
                spinner="clock",
            ) as status:
                for remaining in range(interval, 0, -1):
                    status.update(
                        f"[bold blue]😴 Sleeping {remaining}s before next batch cycle...[/bold blue] [dim](press Ctrl+C to exit)[/dim]"
                    )
                    await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 [bold yellow]Received interrupt, shutting down[/bold yellow]")
            return
        except Exception:
            logger.exception("💥 [bold red]Unexpected error in batch cycle — continuing[/bold red]")


async def main() -> None:
    try:
        await run_forever()
    except asyncio.CancelledError:
        logger.info("idx-realtime-feed-light: shutdown requested")
    except KeyboardInterrupt:
        logger.info("idx-realtime-feed-light: interrupted")


if __name__ == "__main__":
    asyncio.run(main())
