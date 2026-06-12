#!/usr/bin/env python3
"""
ticker_stream.py

Almost realtime streaming IDX Orderbook Analysis CLI Tool.
Repeatedly fetches orderbook data for a given ticker, performing the 3-Tier Entry
analysis and displaying the results dynamically in-place using rich.live.Live.
"""

from __future__ import annotations

import asyncio
import sys
import os
from datetime import datetime, timezone

# Set PAGER to cat to avoid paged output in subprocesses
os.environ["PAGER"] = "cat"

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.prompt import Prompt

from services.auth_service import auth_service
from providers.stockbit_provider import StockbitProvider
from providers.rti_provider import RTIProvider
from schemas.orderbook import OrderbookSnapshot
from ticker import generate_analysis_panel

console = Console()

async def run_stream(ticker: str):
    # 1. Credentials
    with console.status("[bold yellow]Retrieving credentials...[/bold yellow]", spinner="dots") as status:
        token = await auth_service.get_token()

    # Place an initial placeholder panel
    placeholder_panel = Panel(
        Text(f"Initializing live stream for {ticker.upper()}...", style="bold yellow"),
        title=f"[bold]Streaming: {ticker.upper()}[/bold]",
        border_style="yellow"
    )

    with Live(placeholder_panel, console=console, refresh_per_second=2) as live:
        while True:
            # 2. Fetch Data
            snapshot: OrderbookSnapshot | None = None
            
            # Attempt Stockbit
            if token:
                stockbit_provider = StockbitProvider(token)
                try:
                    snapshot = await stockbit_provider.fetch_orderbook(ticker)
                except Exception:
                    pass
                finally:
                    await stockbit_provider.close()

            # Fallback to RTI
            if snapshot is None:
                try:
                    rti_provider = RTIProvider()
                    snapshot = await rti_provider.fetch_orderbook(ticker)
                except Exception:
                    pass

            if snapshot is not None:
                # 3. Generate Panel
                panel = generate_analysis_panel(ticker, snapshot)
                
                # Dynamic countdown loop
                original_subtitle = panel.subtitle
                for remaining in range(5, 0, -1):
                    stream_status = Text()
                    stream_status.append(original_subtitle)
                    stream_status.append("  •  ", style="dim")
                    stream_status.append(f"Refreshing in {remaining}s...", style="bold yellow")
                    
                    panel.subtitle = stream_status
                    live.update(panel)
                    await asyncio.sleep(1)
            else:
                # Update status to retry on failure
                for remaining in range(5, 0, -1):
                    error_text = Text()
                    error_text.append(f"Failed to fetch orderbook for {ticker.upper()}.\n", style="bold red")
                    error_text.append(f"Retrying in {remaining}s...", style="yellow")
                    
                    live.update(Panel(
                        error_text,
                        title="[bold red]Connection Issue[/bold red]",
                        border_style="red"
                    ))
                    await asyncio.sleep(1)


async def main():
    ticker = ""
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper().strip()
    else:
        # Prompt user
        ticker = Prompt.ask("Enter Ticker Code (e.g. BBCA)").upper().strip()

    if not ticker:
        console.print("[bold red]Error: No ticker code provided.[/bold red]")
        sys.exit(1)

    try:
        await run_stream(ticker)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Streaming halted by user.[/bold yellow]")
    except Exception as e:
        console.print_exception()


if __name__ == "__main__":
    asyncio.run(main())
