"""
Entrypoint: idx-realtime-feed

Jalankan sebagai PM2 process (bukan cron), supaya event loop + token
cache tetap hidup antar-cycle:

    pm2 start main.py --interpreter python3 --name idx-realtime-feed
"""

from __future__ import annotations

import asyncio

from core.logger import logger
from services.sync_service import sync_service


async def print_banner() -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from core.config import config

    console = Console()

    banner_text = Text()
    banner_text.append("📈 IDX REALTIME FEED v0.1.0\n", style="bold green")
    banner_text.append("Perpetual synchronization between Stockbit/RTI and Google Sheets\n\n", style="italic dim")

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
        title="[bold]System Startup[/bold]",
        subtitle="[dim]Press Ctrl+C to exit safely[/dim]"
    )
    console.print(panel)


async def main() -> None:
    try:
        await print_banner()
        logger.info("idx-realtime-feed: starting up")
        await sync_service.run_forever()
    except asyncio.CancelledError:
        logger.info("idx-realtime-feed: shutdown requested")
    except KeyboardInterrupt:
        logger.info("idx-realtime-feed: interrupted")


if __name__ == "__main__":
    asyncio.run(main())
