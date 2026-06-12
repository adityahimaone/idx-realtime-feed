#!/usr/bin/env python3
"""
ticker.py

IDX Orderbook Analysis CLI Tool.
Fetches live orderbook data for a given ticker and performs a comprehensive 
3-Tier Entry analysis (Aggressive, Moderat, Low Risk) with rules validation.
"""

from __future__ import annotations

import asyncio
import sys
import os
import json
import math
from datetime import datetime, timezone
from pathlib import Path

# Set PAGER to cat to avoid paged output in subprocesses
os.environ["PAGER"] = "cat"

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.text import Text
from rich.box import ROUNDED, DOUBLE
from rich.align import Align

from core.config import config
from services.auth_service import auth_service
from providers.stockbit_provider import StockbitProvider
from providers.rti_provider import RTIProvider
from schemas.orderbook import OrderbookSnapshot, PriceLevel, DataSource

console = Console()

# --- IDX Tick Size Rules ---

def get_tick_size(price: float) -> int:
    """IDX standard tick rules."""
    if price < 200:
        return 1
    elif price < 500:
        return 2
    elif price < 2000:
        return 5
    elif price < 5000:
        return 10
    else:
        return 25


def align_price_to_tick(price: float, round_direction: str = "nearest") -> float:
    """Align price to IDX tick size depending on requested direction."""
    if price <= 0:
        return 0.0
    tick = get_tick_size(price)
    if round_direction == "up":
        return float(math.ceil(price / tick) * tick)
    elif round_direction == "down":
        return float(math.floor(price / tick) * tick)
    else:
        return float(round(price / tick) * tick)


def calculate_ara_arb_fallbacks(prev_close: float) -> tuple[float, float]:
    """Calculate fallback ARA/ARB prices based on IDX rules."""
    if prev_close <= 0:
        return 0.0, 0.0
    if prev_close <= 200:
        limit = 0.35
    elif prev_close <= 5000:
        limit = 0.25
    else:
        limit = 0.20
    
    raw_ara = prev_close * (1 + limit)
    raw_arb = prev_close * (1 - limit)
    
    ara = align_price_to_tick(raw_ara, "down")
    arb = align_price_to_tick(raw_arb, "up")
    return ara, arb


# --- History / Delta Tracking ---

HISTORY_FILE = Path(".cache/ticker_history.json")

def load_history() -> dict:
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return {}


def save_history(ticker: str, snapshot: OrderbookSnapshot):
    history = load_history()
    # Make sure parent directory exists
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    history[ticker.upper()] = {
        "timestamp": snapshot.timestamp.isoformat(),
        "last_price": snapshot.last_price,
        "bid_levels": [{"price": lvl.price, "lot": lvl.lot, "freq": lvl.freq} for lvl in snapshot.bid_levels],
        "ask_levels": [{"price": lvl.price, "lot": lvl.lot, "freq": lvl.freq} for lvl in snapshot.ask_levels]
    }
    try:
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
    except Exception as e:
        # Silently ignore write error
        pass


# --- Entry Strategy Classes ---

class EntryTier:
    def __init__(self, name: str, entry: float, sl: float, tp: float):
        self.name = name
        self.entry = entry
        self.sl = sl
        self.tp = tp
        self.warnings: list[str] = []
        self.skipped = False
        self.skip_reason = ""


def generate_analysis_panel(ticker: str, snapshot: OrderbookSnapshot) -> Panel:
    """Performs all calculations and generates the Rich visual panel for the orderbook."""
    ticker_upper = ticker.upper()
    
    # Load history for deltas
    history = load_history()
    prev_data = history.get(ticker_upper, {})
    
    prev_bids_dict = {float(lvl["price"]): (lvl["lot"], lvl.get("freq", 0)) for lvl in prev_data.get("bid_levels", [])}
    prev_asks_dict = {float(lvl["price"]): (lvl["lot"], lvl.get("freq", 0)) for lvl in prev_data.get("ask_levels", [])}

    # Handle ARA / ARB calculations
    ara_price = snapshot.ara_price
    arb_price = snapshot.arb_price
    if ara_price == 0 or arb_price == 0:
        f_ara, f_arb = calculate_ara_arb_fallbacks(snapshot.prev_close)
        if ara_price == 0:
            ara_price = f_ara
        if arb_price == 0:
            arb_price = f_arb

    # Support / Resistance Walls
    # Limit to top 10 levels for calculations
    bids = snapshot.bid_levels[:10]
    asks = snapshot.ask_levels[:10]

    avg_bid_vol = sum(lvl.lot for lvl in bids) / len(bids) if bids else 0.0
    avg_ask_vol = sum(lvl.lot for lvl in asks) / len(asks) if asks else 0.0

    support_walls = []
    if bids:
        sorted_bids = sorted(bids, key=lambda lvl: lvl.lot, reverse=True)
        p_lvl = sorted_bids[0]
        p_is_strong = p_lvl.lot >= 2.0 * avg_bid_vol if avg_bid_vol > 0 else False
        support_walls.append({"level": p_lvl, "role": "Primary Support", "strong": p_is_strong})
        if len(sorted_bids) > 1:
            s_lvl = sorted_bids[1]
            s_is_strong = s_lvl.lot >= 2.0 * avg_bid_vol if avg_bid_vol > 0 else False
            support_walls.append({"level": s_lvl, "role": "Secondary Support", "strong": s_is_strong})

    resistance_walls = []
    if asks:
        sorted_asks = sorted(asks, key=lambda lvl: lvl.lot, reverse=True)
        p_lvl = sorted_asks[0]
        p_is_strong = p_lvl.lot >= 2.0 * avg_ask_vol if avg_ask_vol > 0 else False
        resistance_walls.append({"level": p_lvl, "role": "Primary Resistance", "strong": p_is_strong})
        if len(sorted_asks) > 1:
            s_lvl = sorted_asks[1]
            s_is_strong = s_lvl.lot >= 2.0 * avg_ask_vol if avg_ask_vol > 0 else False
            resistance_walls.append({"level": s_lvl, "role": "Secondary Resistance", "strong": s_is_strong})

    best_bid = snapshot.best_bid or snapshot.last_price
    best_ask = snapshot.best_ask or snapshot.last_price
    last_price = snapshot.last_price

    # 3-Tier Strategies
    p_supp_price = support_walls[0]["level"].price if support_walls else best_bid
    p_res_price = resistance_walls[0]["level"].price if resistance_walls else best_ask

    # Tier A: Aggressive (Breakout)
    entry_agg = best_ask
    tp_agg = p_res_price if p_res_price > entry_agg else entry_agg * 1.05
    sl_agg = entry_agg * 0.98

    # Tier B: Moderat (Pullback)
    tick_bb = get_tick_size(best_bid)
    entry_mod = best_bid - 2 * tick_bb
    tp_mod = p_res_price if p_res_price > entry_mod else entry_mod * 1.05
    
    # Check if primary support is lower than mod entry to use as anchor
    if support_walls and support_walls[0]["level"].price < entry_mod:
        sl_mod = support_walls[0]["level"].price - get_tick_size(support_walls[0]["level"].price)
    else:
        sl_mod = entry_mod * 0.97

    # Tier C: Low Risk (Support Buy)
    # Entry 1 tick above support wall if wall is below best_bid
    if support_walls and support_walls[0]["level"].price < best_bid:
        entry_low = support_walls[0]["level"].price + get_tick_size(support_walls[0]["level"].price)
    else:
        entry_low = p_supp_price
    tp_low = p_res_price if p_res_price > entry_low else entry_low * 1.08
    if support_walls:
        sl_low = support_walls[0]["level"].price - get_tick_size(support_walls[0]["level"].price)
    else:
        sl_low = entry_low * 0.96

    tiers = [
        EntryTier("Aggressive (Breakout)", entry_agg, sl_agg, tp_agg),
        EntryTier("Moderat (Pullback)", entry_mod, sl_mod, tp_mod),
        EntryTier("Low Risk (Support Buy)", entry_low, sl_low, tp_low)
    ]

    # Process / Validate Tiers
    for tier in tiers:
        # 1. Align to IDX tick sizes
        tier.entry = align_price_to_tick(tier.entry)
        tier.sl = align_price_to_tick(tier.sl, "up" if tier.name.startswith("Low Risk") else "nearest")
        tier.tp = align_price_to_tick(tier.tp, "nearest")

        # 2. SL clamp to ARB
        if arb_price > 0 and tier.sl < arb_price:
            tier.sl = arb_price
            tier.warnings.append(f"SL clamped to ARB price ({arb_price:,.0f})")

        # 3. TP clamp to ARA
        if ara_price > 0 and tier.tp > ara_price:
            tier.tp = ara_price
            tier.warnings.append(f"TP clamped to ARA price ({ara_price:,.0f})")

        # 4. Low Risk <= 4% max SL validation
        if tier.name.startswith("Low Risk"):
            risk_pct = (tier.entry - tier.sl) / tier.entry if tier.entry > 0 else 0
            if risk_pct > 0.04:
                tier.sl = align_price_to_tick(tier.entry * 0.96, "up")
                # Double check
                if (tier.entry - tier.sl) / tier.entry > 0.04:
                    tier.sl += get_tick_size(tier.sl)
                tier.warnings.append(f"SL adjusted to limit risk to <= 4% (Risk: {((tier.entry - tier.sl)/tier.entry*100):.1f}%)")

        # 5. R/R validation (minimum 2.0 R/R)
        risk = tier.entry - tier.sl
        reward = tier.tp - tier.entry

        if risk <= 0:
            tier.skipped = True
            tier.skip_reason = "Invalid parameters (Stop Loss is at or above Entry Price)"
            continue

        rr = reward / risk
        if rr < 2.0:
            # Try to increase TP to meet 2.0 R/R
            needed_tp = align_price_to_tick(tier.entry + 2.0 * risk, "up")
            if ara_price > 0 and needed_tp > ara_price:
                tier.skipped = True
                tier.skip_reason = f"R/R constraint not met (R/R: {rr:.2f} < 2.0). Needed TP ({needed_tp:,.0f}) exceeds ARA limit ({ara_price:,.0f})."
            else:
                tier.tp = needed_tp
                tier.warnings.append(f"TP adjusted up to {needed_tp:,.0f} to meet min 2.0 R/R")

    # Bias Score Computation
    bias_score = 0
    total_bid_lot = sum(lvl.lot for lvl in bids)
    total_ask_lot = sum(lvl.lot for lvl in asks)
    pressure_ratio = total_bid_lot / total_ask_lot if total_ask_lot > 0 else 1.0

    if pressure_ratio >= 1.5:
        bias_score += 2
    elif pressure_ratio >= 1.1:
        bias_score += 1
    elif pressure_ratio <= 0.5:
        bias_score -= 2
    elif pressure_ratio <= 0.9:
        bias_score -= 1

    # Price position relative to day range (high to low)
    high = snapshot.high
    low = snapshot.low
    if high > low:
        price_pos = (last_price - low) / (high - low)
        if price_pos >= 0.8:
            bias_score += 1
        elif price_pos <= 0.2:
            bias_score -= 1

    # Daily Change %
    chg = snapshot.change_pct
    if chg >= 3.0:
        bias_score += 2
    elif chg > 0:
        bias_score += 1
    elif chg <= -3.0:
        bias_score -= 2
    elif chg < 0:
        bias_score -= 1

    # Foreign Net Ratio
    fbuy = snapshot.fbuy
    fsell = snapshot.fsell
    fnet = snapshot.fnet
    f_total = fbuy + fsell
    if f_total > 0:
        f_ratio = fnet / f_total
        if f_ratio >= 0.20:
            bias_score += 2
        elif f_ratio >= 0.05:
            bias_score += 1
        elif f_ratio <= -0.20:
            bias_score -= 2
        elif f_ratio <= -0.05:
            bias_score -= 1

    # Close to strong support wall
    for w in support_walls:
        if w["strong"]:
            dist_ticks = abs(last_price - w["level"].price) / get_tick_size(last_price)
            if dist_ticks <= 3:
                bias_score += 1
                break
    # Close to strong resistance wall
    for w in resistance_walls:
        if w["strong"]:
            dist_ticks = abs(last_price - w["level"].price) / get_tick_size(last_price)
            if dist_ticks <= 3:
                bias_score -= 1
                break

    if bias_score >= 4:
        bias_label = "STRONG BULLISH"
        bias_style = "bold green"
    elif bias_score >= 1:
        bias_label = "BULLISH"
        bias_style = "bold green"
    elif bias_score <= -4:
        bias_label = "STRONG BEARISH"
        bias_style = "bold red"
    elif bias_score <= -1:
        bias_label = "BEARISH"
        bias_style = "bold red"
    else:
        bias_label = "NEUTRAL"
        bias_style = "bold white"

    # Save to history for next snapshot comparisons
    save_history(ticker, snapshot)

    # --- Render Beautiful Panel ---

    # Title Banner
    change_style = "bold green" if snapshot.change_pct > 0 else ("bold red" if snapshot.change_pct < 0 else "dim")
    change_sign = "+" if snapshot.change_pct > 0 else ""
    
    banner_text = Text()
    banner_text.append(f"📊 {ticker_upper} ORDERBOOK ANALYSIS", style="bold white")
    banner_text.append(" | ", style="dim")
    banner_text.append(f"Last: {snapshot.last_price:,.0f} ({change_sign}{snapshot.change_pct:.2f}%)", style=change_style)
    banner_text.append(" | ", style="dim")
    banner_text.append(f"Open: {snapshot.open_price:,.0f}", style="dim")
    banner_text.append(" | ", style="dim")
    banner_text.append(f"High: {snapshot.high:,.0f}", style="dim")
    banner_text.append(" | ", style="dim")
    banner_text.append(f"Low: {snapshot.low:,.0f}", style="dim")
    
    meta_info = Text()
    meta_info.append(f"Source: {snapshot.source.value.upper()}", style="cyan")
    meta_info.append("  •  ", style="dim")
    meta_info.append(f"Time: {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}", style="magenta")
    if prev_data:
        time_diff = datetime.now(timezone.utc) - datetime.fromisoformat(prev_data["timestamp"])
        diff_sec = int(time_diff.total_seconds())
        if diff_sec < 60:
            time_str = f"{diff_sec}s ago"
        elif diff_sec < 3600:
            time_str = f"{diff_sec // 60}m ago"
        else:
            time_str = f"{diff_sec // 3600}h ago"
        meta_info.append("  •  ", style="dim")
        meta_info.append(f"Prev Snapshot: {time_str}", style="italic yellow")

    # Stacked Layout
    grid = Table.grid(expand=True)

    # LEFT COLUMN: Orderbook Table
    depth_table = Table(
        title="[bold cyan]Orderbook Depth & Deltas[/bold cyan]",
        title_justify="left",
        show_header=True,
        box=ROUNDED,
        header_style="bold"
    )
    depth_table.add_column("Bid Lot", justify="right", no_wrap=True)
    depth_table.add_column("Bid Price", justify="center", no_wrap=True)
    depth_table.add_column("Ask Price", justify="center", no_wrap=True)
    depth_table.add_column("Ask Lot", justify="left", no_wrap=True)

    max_rows = max(len(bids), len(asks))
    for i in range(max_rows):
        bid_str = ""
        bid_price_str = ""
        ask_price_str = ""
        ask_str = ""

        # Bid Level
        if i < len(bids):
            lvl = bids[i]
            p = lvl.price
            
            # Wall detection markers
            wall_marker = ""
            for w in support_walls:
                if w["level"].price == p:
                    wall_marker = " 🧱[bold yellow]SUP[/]" if w["strong"] else " [dim]sup[/]"

            # Delta calculations
            if p in prev_bids_dict:
                p_lot, p_freq = prev_bids_dict[p]
                d_lot = lvl.lot - p_lot
                d_freq = lvl.freq - p_freq
                
                lot_color = "green" if d_lot > 0 else ("red" if d_lot < 0 else "dim")
                freq_color = "green" if d_freq > 0 else ("red" if d_freq < 0 else "dim")
                
                d_lot_str = f"({'+' if d_lot > 0 else ''}{d_lot:,})" if d_lot != 0 else ""
                d_freq_str = f"({'+' if d_freq > 0 else ''}{d_freq})" if d_freq != 0 else ""
                
                lot_part = f"[bold white]{lvl.lot:,}[/][{lot_color}]{d_lot_str}[/]" if d_lot != 0 else f"[bold white]{lvl.lot:,}[/]"
                freq_part = f"[dim]({lvl.freq}[/{freq_color}]{d_freq_str}[dim])[/]" if d_freq != 0 else f"[dim]({lvl.freq})[/]"
                bid_str = f"{lot_part} {freq_part}"
            else:
                is_new = len(prev_bids_dict) > 0
                bid_str = f"[bold white]{lvl.lot:,}[/] {'[italic green](NEW)[/] ' if is_new else ''}[dim]({lvl.freq})[/]"

            bid_price_str = f"[bold green]{p:,.0f}[/]{wall_marker}"

        # Ask Level
        if i < len(asks):
            lvl = asks[i]
            p = lvl.price
            
            # Wall detection markers
            wall_marker = ""
            for w in resistance_walls:
                if w["level"].price == p:
                    wall_marker = " 🧱[bold yellow]RES[/]" if w["strong"] else " [dim]res[/]"

            # Delta calculations
            if p in prev_asks_dict:
                p_lot, p_freq = prev_asks_dict[p]
                d_lot = lvl.lot - p_lot
                d_freq = lvl.freq - p_freq
                
                lot_color = "green" if d_lot > 0 else ("red" if d_lot < 0 else "dim")
                freq_color = "green" if d_freq > 0 else ("red" if d_freq < 0 else "dim")
                
                d_lot_str = f"({'+' if d_lot > 0 else ''}{d_lot:,})" if d_lot != 0 else ""
                d_freq_str = f"({'+' if d_freq > 0 else ''}{d_freq})" if d_freq != 0 else ""
                
                lot_part = f"[bold white]{lvl.lot:,}[/][{lot_color}]{d_lot_str}[/]" if d_lot != 0 else f"[bold white]{lvl.lot:,}[/]"
                freq_part = f"[dim]({lvl.freq}[/{freq_color}]{d_freq_str}[dim])[/]" if d_freq != 0 else f"[dim]({lvl.freq})[/]"
                ask_str = f"{lot_part} {freq_part}"
            else:
                is_new = len(prev_asks_dict) > 0
                ask_str = f"[bold white]{lvl.lot:,}[/] {'[italic green](NEW)[/] ' if is_new else ''}[dim]({lvl.freq})[/]"

            ask_price_str = f"[bold red]{p:,.0f}[/]{wall_marker}"

        depth_table.add_row(bid_str, bid_price_str, ask_price_str, ask_str)

    # RIGHT COLUMN: Metrics & Strategies
    metrics_table = Table(
        title="[bold cyan]Core Metrics[/bold cyan]",
        title_justify="left",
        show_header=False,
        box=None
    )
    metrics_table.add_column("Metric", style="dim", width=20)
    metrics_table.add_column("Value", style="bold")

    # Bid/Offer Pressure format
    pressure_color = "bold green" if pressure_ratio >= 1.2 else ("bold red" if pressure_ratio <= 0.8 else "bold white")
    metrics_table.add_row("Bid/Offer Pressure", f"[{pressure_color}]{pressure_ratio:.2f}[/] (Bid: {total_bid_lot:,} vs Offer: {total_ask_lot:,} lot)")
    
    # Bias Rating
    metrics_table.add_row("Bias Rating Score", f"[{bias_style}]{bias_label} ({bias_score:+d})[/]")

    # Foreign Flow Net
    f_net_formatted = fnet / 1_000_000_000 # convert to Billions (B) IDR
    f_net_color = "green" if fnet > 0 else ("red" if fnet < 0 else "white")
    f_ratio_str = f" (Ratio: {(fnet / (fbuy + fsell) * 100):.1f}%)" if (fbuy + fsell) > 0 else ""
    metrics_table.add_row("Foreign Flow Net", f"[bold {f_net_color}]{f_net_formatted:+.2f}B IDR[/]{f_ratio_str}")

    # Price position
    if high > low:
        price_pos_pct = (last_price - low) / (high - low) * 100
        metrics_table.add_row("Range Price Position", f"{price_pos_pct:.1f}% of Day Range")
    else:
        metrics_table.add_row("Range Price Position", "N/A (Flat)")

    # ARA / ARB limits
    ara_dist = (ara_price - last_price) / last_price * 100 if last_price > 0 else 0
    arb_dist = (last_price - arb_price) / last_price * 100 if last_price > 0 else 0
    metrics_table.add_row("ARA Limit Price", f"[bold red]{ara_price:,.0f}[/] (Dist: {ara_dist:+.2f}%)")
    metrics_table.add_row("ARB Limit Price", f"[bold red]{arb_price:,.0f}[/] (Dist: -{arb_dist:.2f}%)")

    # 3-Tier Strategies Rendering
    strat_text = Text()
    strat_text.append("\n🎯 3-TIER ENTRY STRATEGIES\n", style="bold cyan")
    
    for tier in tiers:
        strat_text.append(f"\n• {tier.name}:\n", style="bold yellow")
        if tier.skipped:
            strat_text.append(f"  ❌ Skipped: {tier.skip_reason}\n", style="bold red")
        else:
            risk = tier.entry - tier.sl
            reward = tier.tp - tier.entry
            rr_val = reward / risk if risk > 0 else 0
            risk_pct = (risk / tier.entry) * 100 if tier.entry > 0 else 0
            
            strat_text.append(f"  Entry  : ", style="dim")
            strat_text.append(f"{tier.entry:,.0f}\n", style="bold green")
            strat_text.append(f"  Target : ", style="dim")
            strat_text.append(f"{tier.tp:,.0f} (+{((tier.tp-tier.entry)/tier.entry*100):.1f}%)\n", style="bold cyan")
            strat_text.append(f"  Stop   : ", style="dim")
            strat_text.append(f"{tier.sl:,.0f} (-{risk_pct:.1f}%)\n", style="bold red")
            strat_text.append(f"  R/R    : ", style="dim")
            strat_text.append(f"{rr_val:.2f}x\n", style="bold magenta")
            
        for w in tier.warnings:
            strat_text.append(f"  ⚠️ {w}\n", style="italic yellow")

    # Add depth table first
    grid.add_row(depth_table)
    grid.add_row("")  # Spacer

    # Metrics and strategies side-by-side at the bottom
    lower_grid = Table.grid(expand=True, padding=(0, 4))
    lower_grid.add_column(ratio=1)
    lower_grid.add_column(ratio=1)
    lower_grid.add_row(metrics_table, strat_text)

    grid.add_row(lower_grid)

    # Master Panel
    master_panel = Panel(
        grid,
        title=banner_text,
        subtitle=meta_info,
        border_style="bold blue",
        box=DOUBLE,
        expand=False
    )
    return master_panel


async def run_analysis(ticker: str):
    # 1. Credentials
    with console.status("[bold yellow]Retrieving credentials...[/bold yellow]", spinner="dots") as status:
        token = await auth_service.get_token()

    # 2. Fetch Data
    snapshot: OrderbookSnapshot | None = None
    with console.status(f"[bold yellow]Fetching live orderbook for {ticker}...[/bold yellow]", spinner="dots") as status:
        if token:
            stockbit_provider = StockbitProvider(token)
            try:
                snapshot = await stockbit_provider.fetch_orderbook(ticker)
            except Exception as e:
                pass
            finally:
                await stockbit_provider.close()

    # Fallback to RTI Provider if stockbit failed
    if snapshot is None:
        with console.status(f"[bold yellow]Stockbit failed. Trying RTI fallback for {ticker}...[/bold yellow]", spinner="dots") as status:
            try:
                rti_provider = RTIProvider()
                snapshot = await rti_provider.fetch_orderbook(ticker)
            except Exception:
                pass

    if snapshot is None:
        console.print(Panel(
            Text(f"Could not retrieve orderbook data for {ticker} from both Stockbit and RTI.", style="bold red"),
            title="[bold red]Error[/bold red]",
            border_style="red"
        ))
        return

    # 3. Calculations & Print
    with console.status("[bold yellow]Executing calculations and rules validation...[/bold yellow]", spinner="dots") as status:
        panel = generate_analysis_panel(ticker, snapshot)

    console.print(panel)


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
        await run_analysis(ticker)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Analysis aborted by user.[/bold yellow]")
    except Exception as e:
        console.print_exception()


if __name__ == "__main__":
    asyncio.run(main())
