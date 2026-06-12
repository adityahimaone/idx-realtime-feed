"""Signal computation for IRW Dashboard.
Uses OrderbookSnapshot computed properties."""
from datetime import datetime


HEADER = [
    "Ticker", "Last Price", "Change %", "Bid/Ask Ratio", "Spread %",
    "ARA Distance %", "ARB Distance %", "Foreign Net", "Volume",
    "Support", "Resistance", "Buy Pressure Score", "Scalp Score",
    "ARA Potential", "Foreign Interest", "Signal",
]


def fmt(val, decimals=2) -> str:
    if val is None: return ""
    if isinstance(val, float):
        return f"{val:.{decimals}f}" if abs(val) >= 0.01 else f"{val}"
    return str(val)


def fmt_int(val) -> str:
    return "" if val is None else str(int(val))


def compute_buy_pressure(bar: float | None) -> float:
    """0-10 score: higher bid/ask ratio = more buying pressure."""
    if not bar or bar == 0: return 0
    return max(min(round(bar * 5, 1), 10), 0)


def compute_scalp_score(bar: float | None, chg: float | None) -> int:
    """0-5: bid strength + momentum."""
    s = 0
    if bar and bar >= 1.2: s += 2
    if chg:
        if chg > 5: s += 3
        elif chg > 2: s += 2
        elif chg > 0: s += 1
    return min(s, 5)


def compute_ara_potential(bar: float | None, chg: float | None, ara_d: float | None) -> int:
    """0-9: ARA proximity + momentum + bid strength."""
    s = 0
    if ara_d is not None:
        if ara_d <= 5: s += 4
        elif ara_d <= 10: s += 2
    if chg:
        if chg > 3: s += 3
        elif chg > 0: s += 1
    if bar and bar >= 1.2: s += 2
    return min(s, 9)


def compute_foreign_interest(fnet: float | None) -> int:
    """0-10 based on foreign net magnitude."""
    if not fnet: return 0
    a = abs(fnet)
    if a > 5_000_000_000: return 10
    if a > 2_000_000_000: return 7
    if a > 1_000_000_000: return 5
    if a > 500_000_000: return 3
    if a > 100_000_000: return 1
    return 0


def compute_signal(bar, chg, ara_d, fnet) -> str:
    parts = []
    if bar and bar >= 2 and chg and chg > 0: parts.append("BUY")
    if chg and chg > 3: parts.append("MOMENTUM")
    if ara_d is not None and ara_d <= 5: parts.append("ARA")
    if fnet and fnet > 1_000_000_000: parts.append("FOREIGN")
    return " ".join(parts)


def compute_dashboard_row(snap) -> list[str]:
    """One dashboard row from OrderbookSnapshot. Uses schema computed properties."""
    return [
        snap.ticker,
        fmt(snap.last_price, 0),
        fmt(snap.change_pct, 2),
        fmt(snap.bid_ask_ratio, 2) if snap.bid_ask_ratio is not None else "",
        fmt(snap.spread, 2) if snap.spread is not None else "",
        fmt(snap.ara_distance_pct, 2) if snap.ara_distance_pct is not None else "",
        fmt(snap.arb_distance_pct, 2) if snap.arb_distance_pct is not None else "",
        fmt_int(snap.fnet) if snap.fnet else "",
        fmt_int(snap.volume) if snap.volume else "",
        fmt(snap.support_price, 0) if snap.support_price else "",
        fmt(snap.resistance_price, 0) if snap.resistance_price else "",
        fmt(compute_buy_pressure(snap.bid_ask_ratio), 1),
        str(compute_scalp_score(snap.bid_ask_ratio, snap.change_pct)),
        str(compute_ara_potential(snap.bid_ask_ratio, snap.change_pct, snap.ara_distance_pct)),
        str(compute_foreign_interest(snap.fnet)),
        compute_signal(snap.bid_ask_ratio, snap.change_pct, snap.ara_distance_pct, snap.fnet),
    ]


def compute_market_recap(rows_data: list[list]) -> list[list]:
    """Market recap from dashboard data. Returns rows for separate sheet."""
    if not rows_data:
        return []

    total = len(rows_data)
    buy_sig = sum(1 for r in rows_data if "BUY" in (r[15] if len(r) > 15 else ""))
    mom_sig = sum(1 for r in rows_data if "MOMENTUM" in (r[15] if len(r) > 15 else ""))
    for_sig = sum(1 for r in rows_data if "FOREIGN" in (r[15] if len(r) > 15 else ""))
    ara_sig = sum(1 for r in rows_data if "ARA" in (r[15] if len(r) > 15 else ""))

    bps_list = []
    for r in rows_data:
        try:
            if len(r) > 11 and r[11]:
                bps_list.append(float(r[11]))
        except (ValueError, TypeError):
            pass

    avg_bps = round(sum(bps_list) / len(bps_list), 1) if bps_list else 0
    bullish = sum(1 for v in bps_list if v >= 5)
    bearish = sum(1 for v in bps_list if v < 5)

    fnet_list = []
    for r in rows_data:
        try:
            if len(r) > 7 and r[7]:
                fnet_list.append(float(r[7]))
        except (ValueError, TypeError):
            pass

    total_fnet = sum(fnet_list) if fnet_list else 0
    pos_fnet = sum(v for v in fnet_list if v > 0)
    neg_fnet = sum(v for v in fnet_list if v < 0)
    fnet_count = sum(1 for v in fnet_list if abs(v) > 100_000_000)

    def sig_weight(s):
        w = 0
        if "BUY" in s: w += 3
        if "MOMENTUM" in s: w += 2
        if "FOREIGN" in s: w += 2
        if "ARA" in s: w += 3
        return w

    ranked = []
    for r in rows_data:
        sig = r[15] if len(r) > 15 else ""
        if sig:
            ranked.append((r[0], sig, r[1] if len(r) > 1 else "",
                          r[11] if len(r) > 11 else ""))
    ranked.sort(key=lambda x: sig_weight(x[1]), reverse=True)
    ranked = ranked[:5]

    now_str = datetime.now().strftime("%d %b %H:%M")

    rows = [
        ["Market Recap", "", "", ""],
        ["Generated", now_str, "", ""],
        ["", "", "", ""],
        ["SYNTHESIS", "", "", ""],
        ["Total Watchlist", str(total), "", ""],
        ["Bullish (BPS>=5)", str(bullish), "Bearish (BPS<5)", str(bearish)],
        ["Avg Buy Pressure", str(avg_bps), "", ""],
        ["", "", "", ""],
        ["SIGNALS", "", "", ""],
        ["BUY Signals", str(buy_sig), "Momentum", str(mom_sig)],
        ["ARA Potential", str(ara_sig), "Foreign Interest", str(for_sig)],
        ["", "", "", ""],
        ["FOREIGN FLOW", "", "", ""],
        ["Total FNet", fmt_int(total_fnet), "Tickers w/ Foreign", str(fnet_count)],
        ["Positive Flow", fmt_int(pos_fnet), "Negative Flow", fmt_int(neg_fnet)],
        ["", "", "", ""],
        ["TOP SIGNALS", "", "", "", ""],
    ]

    for item in ranked:
        rows.append([item[0], item[1], "Price", item[2]])

    if not ranked:
        rows.append(["No active signals", "", "", ""])

    return rows
