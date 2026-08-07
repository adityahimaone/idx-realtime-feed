import streamlit as st
import pandas as pd
import asyncio
from datetime import datetime
from core.config import config
from data.fetchers import safe_float, fetch_stockbit_detail, fetch_stockbit_tradebook, fetch_itick_snapshot
from data.tradebook import parse_tradebook, tradebook_profile, adjust_tiers_with_tradebook
from data.scoring import compute_intraday_score, position_size_lots, minify_html
from data.orderbook_wall import (
    detect_walls, track_delta, OrderbookLevel,
    grounded_three_tier_A, grounded_three_tier_B, grounded_three_tier_C,
)
from repositories.sqlite_repository import sqlite_repository
from data.pre_ara import get_ara_price, ara_distance

WIB = __import__("pytz").timezone("Asia/Jakarta")

_TIER_META = {
    "Aggressive": {"name": "🔥 Aggressive", "play": "Breakout Play", "cls": "tier-agg", "alloc": 0.10, "alloc_lbl": "10%"},
    "Moderat":    {"name": "⚡ Moderate",    "play": "Pullback Play", "cls": "tier-mod", "alloc": 0.15, "alloc_lbl": "15%"},
    "Low Risk":   {"name": "🛡️ Low Risk",   "play": "Support Buy",   "cls": "tier-low", "alloc": 0.20, "alloc_lbl": "20%"},
}


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_tradebook_cached(symbol: str, date_str: str) -> dict | None:
    """Daily trade-book chart from the public Exodus endpoint (cached 60s)."""
    return fetch_stockbit_tradebook(symbol, date_str)


def _fmt_idr(v: float) -> str:
    """Format Rupiah with sign, e.g. +1.32B / -650.00M."""
    sign = "+" if v > 0 else "-"
    av = abs(v)
    if av >= 1e9:
        return f"{sign}{av / 1e9:.2f}B"
    if av >= 1e6:
        return f"{sign}{av / 1e6:.2f}M"
    return f"{sign}{av:,.0f}"


def _tier_sanity_warning(strategies, current_price, open_price, prev_close, atr_pct=None):
    """
    Deteksi entry Moderate/Low Risk yang secara struktural tidak wajar —
    biasanya terjadi saat ARA membuat orderbook menipis/gap besar di bawah harga.
    Floor dihitung dari kolom `ATR %` (percent) × SANITY_ATR_MULTIPLIER, fallback
    SANITY_FLOOR_FALLBACK_PCT (8%) bila kolom kosong. ARA proximity memakai
    ARA_PROXIMITY_WARNING_PCT (2.0) di semua tempat.
    """
    if not strategies:
        return {}
    if atr_pct:
        floor_pct = config.SANITY_ATR_MULTIPLIER * atr_pct / 100.0
    else:
        floor_pct = config.SANITY_FLOOR_FALLBACK_PCT
    floor_price = (
        min(open_price, current_price * (1 - floor_pct))
        if open_price > 0 else current_price * (1 - floor_pct)
    )

    ara_price = get_ara_price(prev_close) if prev_close else 0.0
    is_near_ara = False
    if ara_price > 0:
        is_near_ara = ara_distance(current_price, ara_price) <= config.ARA_PROXIMITY_WARNING_PCT

    warnings = {}
    for tier in ["Moderat", "Low Risk"]:
        entry = strategies[tier].get("entry")
        if entry is None:
            continue
        if entry < floor_price:
            gap_pct = (current_price - entry) / current_price * 100
            msg = (
                f"Entry Rp {entry:,.0f} berjarak {gap_pct:.1f}% dari harga sekarang dan di bawah "
                f"open hari ini (Rp {open_price:,.0f})."
            )
            if is_near_ara:
                msg += " Saham sedang dekat/at ARA — gap orderbook di bawah adalah hal normal, bukan anomali sistem. Validasi manual dulu, jangan anggap ini level support genuine."
            else:
                msg += " Kemungkinan orderbook menipis/gap — validasi manual dulu, jangan anggap ini level support genuine."
            warnings[tier] = msg
    return warnings


def _engine_tier_rows(strats) -> str:
    """Compact tier rows (Entry/SL/TP/RR) for the A/B/C comparison cards."""
    rows = []
    for key, cls, label in (
        ("Aggressive", "eng-agg", "Agg"),
        ("Moderat", "eng-mod", "Mod"),
        ("Low Risk", "eng-low", "LR"),
    ):
        tier = strats.get(key, {})
        entry = tier.get("entry")
        if entry is None:
            rows.append(
                f"<tr><td class='{cls}'>{label}</td>"
                "<td colspan='4' style='color:#EF4444;'>disabled</td></tr>"
            )
            continue
        sl = tier.get("sl") or 0.0
        tp = tier.get("tp") or 0.0
        rr = tier.get("rr") or 0.0
        rows.append(
            f"<tr><td class='{cls}'>{label}</td><td>{entry:,.0f}</td>"
            f"<td>{sl:,.0f}</td><td>{tp:,.0f}</td><td>{rr}</td></tr>"
        )
    return "".join(rows)


def _engine_card_html(kicker_color, kicker, title, pill, note, rows) -> str:
    """Single compact engine card (`.engine-card`) as minified HTML."""
    return minify_html(f"""
    <div class="engine-card">
        <div class="engine-card-head">
            <span class="engine-card-kicker" style="color:{kicker_color};">{kicker}</span>
            <span class="engine-card-title">{title}</span>
            <span class="engine-card-pill">{pill}</span>
        </div>
        <div class="engine-card-note">{note}</div>
        <table class="engine-table">
            <thead><tr><th>Tier</th><th>Entry</th><th>SL</th><th>TP</th><th>RR</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """)


def _engine_compare_html(strategies_A, strategies_B, strategies_C,
                         fib_range_pct, imb) -> list[str]:
    """Three compact engine cards (A/B/C) below the Engine D verdict.

    Returns one card HTML string per engine — the caller renders each in its
    own st.column so all three always show (single-grid markdown blocks get
    truncated by Streamlit at blank lines; per-column rendering avoids that).
    """
    rows_a = _engine_tier_rows(strategies_A)
    rows_b = _engine_tier_rows(strategies_B)
    rows_c = _engine_tier_rows(strategies_C) if strategies_C else (
        "<tr><td colspan='5' style='color:#64748B;'>Inactive — range &lt; 2.0%</td></tr>"
    )

    sent_lbl = strategies_B.get('sentiment_label', 'N/A')
    sent_val = strategies_B.get('sentiment_factor', 1.0)
    b_note = (
        f"Sentimen <b>{sent_lbl}</b> · factor <code>{sent_val}</code> · "
        f"Bid/Ask {imb:.2f}x"
    )
    if not strategies_B.get('aggressive_enabled', True):
        b_note += " · ⛔ Aggressive disabled"

    if strategies_C and "fib_levels" in strategies_C:
        ext_mode = strategies_C.get('extension_mode', False)
        rng = strategies_C.get('intraday_range', 0)
        mode = "🔻 Extension" if ext_mode else "🔼 Retracement"
        c_note = f"Mode <b>{mode}</b> · range {rng:,.0f} pts ({fib_range_pct:.1f}%)"
    else:
        c_note = f"Inactive — range {fib_range_pct:.2f}% &lt; 2.0%"

    return [
        _engine_card_html("#38BDF8", "Engine A", "Wall Gravity", "Fallback",
                          "Struktural murni — tanpa konteks pasar.", rows_a),
        _engine_card_html("#00D4AA", "Engine B", "Contextual Alpha", "Konfirmasi",
                          b_note, rows_b),
        _engine_card_html("#C9A447", "Engine C", "Fibonacci", "Konfirmasi",
                          c_note, rows_c),
    ]


def _tier_card_html(tier, meta, tag, base_portfolio, risk_budget, warning=None) -> str:
    """Single tier card (`.tier-card`) with Entry/SL/TP/RR/size/max-loss."""
    entry = tier.get("entry")
    if entry is None:
        return f"""
        <div class="tier-card {meta['cls']} tier-disabled">
            <div class="tier-tag">Verdict · Engine {tag}</div>
            <div class="tier-name">{meta['name']} — DISABLED</div>
            <div class="tier-warning">⛔ {tier.get('warning', 'Disabled by engine filter.')}</div>
        </div>
        """

    sl = tier.get("sl") or 0.0
    tp = tier.get("tp") or 0.0
    rr = tier.get("rr") or 0.0
    valid = tier.get("valid", True)
    lots = position_size_lots(entry, sl, base_portfolio, meta["alloc"], risk_budget)
    val = lots * entry * 100
    rps = entry - sl if entry > sl else 0.0
    risk_val = lots * rps * 100
    risk_disp = (
        f"Rp {risk_val:,.0f} ({risk_val / base_portfolio * 100:.2f}%)"
        if rps > 0 else "⚠️ SL tidak valid"
    )
    rr_badge = "✅" if valid else "⚠️ R/R Rendah"

    wall_info = ""
    if tier.get("wall_price"):
        ws = tier.get("wall_score")
        ws_str = f"{ws:.3f}" if isinstance(ws, float) else "N/A"
        wall_info = (
            f"<li><span>Wall Anchor</span><b>Rp {tier['wall_price']:,.0f} "
            f"({tier.get('wall_lot', 0):,} lot, score {ws_str})</b></li>"
        )

    warn_html = ""
    if not valid and tier.get("warning"):
        warn_html = f'<div class="tier-warning">⚠️ {tier["warning"]}</div>'
    elif warning:
        warn_html = f'<div class="tier-warning">🚨 {warning}</div>'

    return f"""
    <div class="tier-card {meta['cls']}">
        <div class="tier-tag">Verdict · Engine {tag}</div>
        <div class="tier-name">{meta['name']} ({meta['play']})</div>
        <ul>
            <li><span>Entry</span><b>IDR {entry:,.0f}</b></li>
            <li><span>Target (TP)</span><b>IDR {tp:,.0f}</b></li>
            <li><span>Stop Loss (SL)</span><b>IDR {sl:,.0f}</b></li>
            <li><span>R/R Ratio</span><b>{rr}x {rr_badge}</b></li>
            {wall_info}
            <li><span>Size ({meta['alloc_lbl']} cap)</span><b>{lots:,} Lots · Rp {val:,.0f}</b></li>
            <li><span>Max Loss at SL</span><b>{risk_disp}</b></li>
        </ul>
        {warn_html}
    </div>
    """


def _render_tier_cards(strats, tag, base_portfolio, risk_budget, tw=None):
    """Render the single 3-tier verdict row (Engine D or fallback Engine A).

    One card per st.column so all three render independently — a single
    markdown HTML grid gets truncated by Streamlit at blank lines (observed:
    only the first card rendered). `.tier-card` uses height:100% + flex so the
    three columns share equal height.
    """
    tier_warnings_local = tw or {}
    cards = [
        _tier_card_html(
            strats["Aggressive"], _TIER_META["Aggressive"], tag,
            base_portfolio, risk_budget,
            warning=tier_warnings_local.get("Aggressive"),
        ),
        _tier_card_html(
            strats["Moderat"], _TIER_META["Moderat"], tag,
            base_portfolio, risk_budget,
            warning=tier_warnings_local.get("Moderat"),
        ),
        _tier_card_html(
            strats["Low Risk"], _TIER_META["Low Risk"], tag,
            base_portfolio, risk_budget,
            warning=tier_warnings_local.get("Low Risk"),
        ),
    ]
    cols = st.columns(3)
    for col, card in zip(cols, cards):
        with col:
            st.markdown(minify_html(card), unsafe_allow_html=True)


def render_tab7(ticker_df, scored_list, total_portfolio_value=0.0):
    """Render Tab 7: Deep Stock Analysis (Exodus API) with Wall Detection & Delta Tracking"""
    st.markdown("### 🔍 Deep Stock Analysis (Exodus API)")
    st.caption("Fetches real-time bid/ask queue details, detects walls, and tracks multi-snapshot deltas using SQLite history.")

    if scored_list:
        if "deep_analyzed_ticker" not in st.session_state:
            st.session_state.deep_analyzed_ticker = ""

        col_input, col_btn = st.columns([3, 1])
        with col_input:
            search_input = st.text_input(
                "Enter Ticker to fetch live orderbook details (e.g. BBCA):",
                value=st.session_state.deep_analyzed_ticker,
                key="deep_search_input"
            ).upper().strip()
        with col_btn:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔍 Search Ticker", use_container_width=True):
                st.session_state.deep_analyzed_ticker = search_input
                # Force refresh by clearing cache (all source-mode variants)
                for _k in [k for k in st.session_state.keys()
                           if k.startswith(f"sb_detail_{search_input}") or k.startswith(f"sb_time_{search_input}")]:
                    del st.session_state[_k]
                st.rerun()

        if search_input and search_input != st.session_state.deep_analyzed_ticker:
            st.session_state.deep_analyzed_ticker = search_input
            st.rerun()

        selected_detail = st.session_state.deep_analyzed_ticker
        if selected_detail:
            matched_rows = ticker_df[ticker_df["Clean Ticker"] == selected_detail]
            if not matched_rows.empty:
                hist_row = matched_rows.iloc[0].to_dict()

                if selected_detail in st.session_state.screener_data:
                    raw_data_obj = st.session_state.screener_data[selected_detail]
                else:
                    raw_data_obj = {
                        "last": safe_float(hist_row.get("Price")),
                        "prev_close": safe_float(hist_row.get("ClosePrev")),
                        "volume": safe_float(hist_row.get("Volume")),
                        "source": "gsheet_fallback",
                        "source_ts": None
                    }

                st.markdown(
                    '<div class="panel-title">🔀 Sumber Data Orderbook</div>',
                    unsafe_allow_html=True,
                )
                source_mode = st.radio(
                    "Pilih sumber orderbook",
                    ["Auto (Stockbit ➔ itick)", "Stockbit Exodus", "itick (Backup)"],
                    index=0,
                    horizontal=True,
                    key=f"deep_source_mode_{selected_detail}",
                )

                import time
                cache_key = f"sb_detail_{selected_detail}_{source_mode}"
                time_key = f"sb_time_{selected_detail}_{source_mode}"
                snap = None
                now = time.time()
                was_fresh_fetch = False

                if cache_key in st.session_state and time_key in st.session_state and (now - st.session_state[time_key] < 10):
                    snap = st.session_state[cache_key]
                else:
                    if source_mode != "itick (Backup)":
                        with st.spinner(f"⚡ Connecting to Exodus API for {selected_detail}..."):
                            snap = asyncio.run(fetch_stockbit_detail(selected_detail))
                    if snap is None and source_mode != "Stockbit Exodus":
                        with st.spinner(f"🔄 itick.org backup untuk {selected_detail}..."):
                            snap = asyncio.run(fetch_itick_snapshot(selected_detail))
                        if snap:
                            snap.source = "itick"
                    if snap:
                        st.session_state[cache_key] = snap
                        st.session_state[time_key] = now
                        was_fresh_fetch = True

                if snap:
                    source_label = "ITICK (Backup)" if getattr(snap, "source", "") == "itick" else "EXODUS API"
                    # Override to st.session_state.screener_data
                    st.session_state.screener_data[selected_detail] = {
                        "last": snap.last_price,
                        "open": snap.open_price if snap.open_price else snap.last_price,
                        "high": snap.high if snap.high else snap.last_price,
                        "low": snap.low if snap.low else snap.last_price,
                        "volume": snap.volume,
                        "prev_close": snap.prev_close,
                        "source": "itick" if source_label == "ITICK (Backup)" else "stockbit",
                        "source_ts": datetime.now(WIB),
                        "report": f"{source_label} Live (Deep Analysis Override)"
                    }

                    # Refresh raw_data_obj with the overridden values
                    raw_data_obj = st.session_state.screener_data[selected_detail]

                    if was_fresh_fetch:
                        st.toast(f"✅ Price overrides updated for {selected_detail} to {snap.last_price}! ({source_label})")

                        # Save snapshot levels to SQLite for delta tracking
                        for lvl in snap.bid_levels:
                            sqlite_repository.save_orderbook_snapshot(selected_detail, "bid", lvl.price, lvl.lot, getattr(lvl, 'freq', 0))
                        for lvl in snap.ask_levels:
                            sqlite_repository.save_orderbook_snapshot(selected_detail, "ask", lvl.price, lvl.lot, getattr(lvl, 'freq', 0))

                    # Fetch previous snapshots from SQLite for delta analysis
                    history = sqlite_repository.get_latest_orderbook_snapshots(selected_detail, limit=40)
                    # Simple reconstruction of previous snapshot levels
                    prev_bids = []
                    prev_asks = []
                    seen_timestamps = sorted(list(set(r["captured_at"] for r in history)), reverse=True)
                    if len(seen_timestamps) > 1:
                        prev_ts = seen_timestamps[1] # the second newest timestamp is the previous refresh
                        for r in history:
                            if r["captured_at"] == prev_ts:
                                lvl = OrderbookLevel(price=r["price"], lot=r["lot"], freq=r["freq"])
                                if r["side"] == "bid":
                                    prev_bids.append(lvl)
                                else:
                                    prev_asks.append(lvl)

                    # Wall Detection
                    curr_bids = [OrderbookLevel(price=lvl.price, lot=lvl.lot, freq=getattr(lvl, 'freq', 0)) for lvl in snap.bid_levels]
                    curr_asks = [OrderbookLevel(price=lvl.price, lot=lvl.lot, freq=getattr(lvl, 'freq', 0)) for lvl in snap.ask_levels]

                    bid_walls = detect_walls(curr_bids, "bid")
                    ask_walls = detect_walls(curr_asks, "ask")

                    # Delta Tracking
                    bid_deltas = track_delta(prev_bids, curr_bids, snap.last_price, "bid")
                    ask_deltas = track_delta(prev_asks, curr_asks, snap.last_price, "ask")

                    # Grounded 3-Tier Strategies — Engine A
                    strategies_A = grounded_three_tier_A(snap.last_price, curr_bids, curr_asks)

                    # ── Trade Book (Engine D) — fetched early so Engine B can use
                    # ── the real VWAP and the score can consume live trade flow ──
                    tb = None
                    profile = None
                    d1, d2 = st.columns([2, 1])
                    with d1:
                        tb_date = st.date_input(
                            "Tanggal Trade Book (Engine D)",
                            value=datetime.now(WIB).date(),
                            key=f"tb_date_{selected_detail}",
                        )
                    with d2:
                        tb_refresh = st.button(
                            "🔄 Muat Ulang",
                            key=f"tb_refresh_{selected_detail}",
                            use_container_width=True,
                        )
                        if tb_refresh:
                            _fetch_tradebook_cached.clear()
                            st.rerun()

                    tb_payload = _fetch_tradebook_cached(
                        selected_detail, tb_date.strftime("%Y-%m-%d")
                    )
                    if tb_payload:
                        tb = parse_tradebook(selected_detail, tb_payload)
                        if tb and tb.series and tb.series.times:
                            profile = tradebook_profile(tb)

                    # Engine B needs extra context
                    total_ask_lot = sum(lvl.lot for lvl in snap.ask_levels)
                    open_price_today = snap.open_price if snap.open_price else snap.last_price
                    # Derive avg_price: prefer real trade-book VWAP when available,
                    # fallback to snap average / OHLC average.
                    _high = snap.high if snap.high else snap.last_price
                    _low = snap.low if snap.low else snap.last_price
                    avg_price_est = (
                        profile.get("vwap") if profile else None
                    ) or (
                        getattr(snap, 'avg', None)
                        or getattr(snap, 'average_price', None)
                        or getattr(snap, 'avg_price', None)
                        or ((open_price_today + _high + _low + snap.last_price) / 4)
                    )

                    strategies_B = grounded_three_tier_B(
                        last_price=snap.last_price,
                        bid_levels=curr_bids,
                        ask_levels=curr_asks,
                        total_bid_lot=snap.total_bid_lot,
                        total_ask_lot=total_ask_lot,
                        avg_price=avg_price_est,
                        open_price=open_price_today,
                    )

                    # Engine C computation (if available).
                    # NOTE (audit #10): the >=2.0% intraday-range gate is kept
                    # intentionally — Fib retracements below 2% range are not
                    # reliable, so Engine C stays inactive there. Documented in
                    # README; do not "fix" without a product decision.
                    fib_range_pct = ((snap.high - snap.low) / snap.last_price * 100) if (snap.high and snap.low) else 0
                    engine_c_available = fib_range_pct >= config.ARA_PROXIMITY_WARNING_PCT

                    strategies_C = None
                    if engine_c_available:
                        strategies_C = grounded_three_tier_C(
                            last_price=snap.last_price,
                            high_price=snap.high,
                            low_price=snap.low,
                            open_price=open_price_today,
                            bid_levels=curr_bids,
                            ask_levels=curr_asks,
                        )

                    # Score memakai data live: imbalance ratio + trade-book flow.
                    atr_pct_raw = safe_float(hist_row.get("ATR %"))
                    score_data = compute_intraday_score(
                        raw_data_obj, hist_row,
                        imbalance_ratio=snap.imbalance_ratio,
                        tradebook=profile if profile else None,
                    )
                    tier_warnings_A = _tier_sanity_warning(
                        strategies_A, snap.last_price, open_price_today,
                        snap.prev_close, atr_pct=atr_pct_raw or None,
                    )
                    tier_warnings_B = _tier_sanity_warning(
                        strategies_B, snap.last_price, open_price_today,
                        snap.prev_close, atr_pct=atr_pct_raw or None,
                    )
                    tier_warnings_C = _tier_sanity_warning(
                        strategies_C, snap.last_price, open_price_today,
                        snap.prev_close, atr_pct=atr_pct_raw or None,
                    ) if strategies_C else {}

                    # Position sizing base
                    base_portfolio = total_portfolio_value if total_portfolio_value > 0 else 100_000_000.0
                    is_default_port = total_portfolio_value <= 0
                    risk_budget = 0.01  # 1% of portfolio risk

                    # ── Metric row (analysis-metric) ──────────────────────────
                    bk = score_data["breakdown"]
                    breakdown_txt = (
                        f"Flow {bk['flow']:.0f} · OB {bk['orderbook']:.0f} · "
                        f"Tr {bk['trend']:.0f} · Mom {bk['momentum']:.0f} · Hist {bk['hist']:.0f}"
                    )
                    if "trade_flow" in bk:
                        breakdown_txt += f" · TF {bk['trade_flow']:.0f}"
                    book_txt = ""
                    if profile:
                        book_txt = (
                            f"<div class='analysis-metric-sub' style='color:#C9A447;'>"
                            f"Book: {profile.get('big_money_trend', 'neutral')} · "
                            f"Imbalance {profile.get('imbalance', 0.0):.2f}×</div>"
                        )
                    chg_sign = "+" if snap.change_pct > 0 else ""
                    chg_color = "#00D4AA" if snap.change_pct >= 0 else "#FF6B6B"
                    imb_color = "#00D4AA" if (snap.imbalance_ratio and snap.imbalance_ratio >= 1.0) else "#FF6B6B"
                    st.markdown(minify_html(f"""
                    <div class="metric-grid">
                        <div class="analysis-metric">
                            <div class="analysis-metric-label">Live Signal</div>
                            <div class="analysis-metric-value" style="color:{score_data['color']};">{score_data['signal']}</div>
                            <div class="analysis-metric-sub">Score {score_data['score']}/100 · {breakdown_txt}</div>
                            {book_txt}
                        </div>
                        <div class="analysis-metric" style="border-top:2px solid {chg_color};">
                            <div class="analysis-metric-label">Live Price</div>
                            <div class="analysis-metric-value">IDR {snap.last_price:,.0f}</div>
                            <div class="analysis-metric-sub" style="color:{chg_color};">{chg_sign}{snap.change_pct:.2f}% Intraday</div>
                        </div>
                        <div class="analysis-metric" style="border-top:2px solid {imb_color};">
                            <div class="analysis-metric-label">Bid/Ask Imbalance</div>
                            <div class="analysis-metric-value">{snap.imbalance_ratio:.2f}x</div>
                            <div class="analysis-metric-sub">Total Bid: {snap.total_bid_lot:,} lot</div>
                        </div>
                        <div class="analysis-metric" style="border-top:2px solid #38BDF8;">
                            <div class="analysis-metric-label">Source & Freshness</div>
                            <div class="analysis-metric-value" style="font-size:1.05em; color:#38BDF8;">{source_label}</div>
                            <div class="analysis-metric-sub">TS: {datetime.now(WIB).strftime('%H:%M:%S')} WIB (Live)</div>
                        </div>
                    </div>
                    """), unsafe_allow_html=True)

                    if source_label == "ITICK (Backup)":
                        if source_mode == "itick (Backup)":
                            st.caption("🛰️ Sumber aktif: itick.org (backup) — quotes + depth (limit 5 calls/menit).")
                        else:
                            st.caption("🔄 Fallback aktif: data dari itick.org (backup) — quotes + depth (limit 5 calls/menit). Stockbit Exodus tidak tersedia.")
                    else:
                        st.caption("📡 Data live dari Stockbit Exodus API — orderbook, walls & delta tracking.")

                    imb = snap.imbalance_ratio if snap.imbalance_ratio else 1.0

                    # Cross-link from portfolio
                    held_asset = next((a for a in st.session_state.get("portfolio", []) if a["Ticker"] == selected_detail), None)
                    if held_asset:
                        cur_avg = held_asset["Buy Price"]
                        cur_lots = held_asset["Lots"]
                        pl_pct = (snap.last_price - cur_avg) / cur_avg * 100 if cur_avg > 0 else 0.0
                        pl_color = "#10B981" if pl_pct >= 0 else "#EF4444"
                        _low_a = strategies_A['Low Risk'].get('entry') or float('inf')
                        _low_b = strategies_B['Low Risk'].get('entry') or float('inf')
                        _low_c = strategies_C['Low Risk'].get('entry') or float('inf') if strategies_C else float('inf')
                        lr_ref_entry = min(_low_a, _low_b, _low_c)
                        st.markdown(f"""
                        <div class="notes-section" style="border-left-color:{pl_color};">
                        📌 <b>Posisi aktif:</b> {cur_lots:,} lot @ Rp {cur_avg:,.0f} avg
                        — P/L saat ini: <span style="color:{pl_color};font-weight:700;">{pl_pct:+.2f}%</span>.
                        Mau average down? Buka tab <b>💼 Live Portfolio Tracker</b> → Average Down Calculator,
                        pakai entry Low Risk (Rp {lr_ref_entry:,.0f}) sebagai referensi harga
                        kalau memang masih dalam batas wajar (lihat warning gap di atas kalau ada).
                        </div>
                        """, unsafe_allow_html=True)

                    # ── Single verdict: Engine D (trade book) atau fallback A ──
                    strategies_D = None
                    if profile:
                        strategies_D = adjust_tiers_with_tradebook(strategies_A, profile)

                    if strategies_D:
                        st.markdown("### 🎯 Verdict — Engine D (Trade Book Momentum)")
                        st.caption(
                            "Engine A di-rekalibrasi trade book (big money, net flow, imbalance). "
                            "Engine A/B/C tampil sebagai perbandingan kompak di bawah."
                        )
                        primary = strategies_D
                        tag = "D"
                        tw = strategies_D.get("tier_warnings", {})
                    else:
                        st.markdown("### 🎯 Verdict — Engine A (Wall Gravity)")
                        st.caption("Trade book tidak tersedia — menampilkan Engine A. Engine B/C tampil sebagai perbandingan kompak di bawah.")
                        primary = strategies_A
                        tag = "A"
                        tw = tier_warnings_A

                    _render_tier_cards(primary, tag, base_portfolio, risk_budget, tw=tw)

                    # ── Compact engine comparison (A/B/C) ────────────────────
                    st.markdown("#### 🅰️🅱️🅲️ Engine A/B/C — Perbandingan Kompak")
                    st.caption(
                        "Verdict utama tetap di atas; kartu ini hanya pembanding "
                        "entry/SL/TP/RR tiap engine."
                    )
                    engine_cards = _engine_compare_html(
                        strategies_A, strategies_B, strategies_C,
                        fib_range_pct, imb,
                    )
                    eng_cols = st.columns(3)
                    for eng_col, eng_card in zip(eng_cols, engine_cards):
                        with eng_col:
                            st.markdown(eng_card, unsafe_allow_html=True)

                    if is_default_port:
                        st.caption("ℹ️ *Note: Sizing calculates from a default Rp 100 Juta port size because your actual portfolio is empty.*")
                    else:
                        st.caption(f"📊 *Sizing calculates dynamically from your actual active portfolio size: Rp {total_portfolio_value:,.0f}*")
                    st.caption("🛡️ *Sizing uses risk-first allocation: risking 1.0% of portfolio value per trade (max loss), capped at the maximum capital allocation tier.*")
                    st.caption("⚠️ *Penting: Pilih salah satu skenario entry di bawah yang paling sesuai dengan aksi pasar nyata — jangan mengambil kombinasi ketiganya sekaligus (total 45% portofolio).*")

                    # ── Trade Book detail (chart + summary + adjustments) ─────
                    if tb and tb.series and tb.series.times:
                        st.markdown("#### 📊 Trade Book — Detail Harian (Engine D)")
                        gap_pct = profile.get("buy_sell_gap_pct", 0.0)
                        mb1, mb2, mb3, mb4 = st.columns(4)
                        with mb1:
                            st.metric(
                                "Book Buy", f"{tb.buy_lot_pct:.0f}%",
                                f"{gap_pct:+.1f}% lot gap",
                            )
                        with mb2:
                            st.metric(
                                "Book Sell", f"{tb.sell_lot_pct:.0f}%",
                                f"big {tb.big_money_sell_pct:.0f}%",
                            )
                        with mb3:
                            st.metric(
                                "Imbalance", f"{tb.imbalance:.2f}x",
                                profile.get("big_money_trend", "neutral"),
                            )
                        with mb4:
                            st.metric(
                                "Net Flow (Hari)", _fmt_idr(profile.get("net_flow_sum", 0.0)),
                                f"{profile.get('net_positive_ratio', 0.0) * 100:.0f}% menit positif",
                            )

                        # ── Chart: price + net flow + big money ────────────────
                        import plotly.graph_objects as go
                        times = tb.series.times
                        net = tb.series.net_values
                        big_net = tb.series.big_money_net_values
                        prices = tb.series.prices
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=times, y=prices, name="Harga",
                            line=dict(color="#38BDF8", width=2), yaxis="y",
                        ))
                        fig.add_trace(go.Bar(
                            x=times, y=net, name="Net Flow (Rp)",
                            marker_color=["#10B981" if v >= 0 else "#EF4444" for v in net],
                            opacity=0.55, yaxis="y2",
                        ))
                        fig.add_trace(go.Scatter(
                            x=times, y=big_net, name="Big Money Net",
                            line=dict(color="#C9A447", width=1.5), yaxis="y2",
                        ))
                        fig.update_layout(
                            height=360,
                            margin=dict(l=10, r=10, t=30, b=10),
                            legend=dict(orientation="h", y=1.08),
                            hovermode="x unified",
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(color="#E2E8F0"),
                            yaxis=dict(title="Harga", gridcolor="rgba(148,163,184,0.15)"),
                            yaxis2=dict(
                                title="Net Value (Rp)", overlaying="y",
                                side="right", showgrid=False,
                            ),
                        )
                        st.plotly_chart(fig, use_container_width=True)

                        if strategies_D and strategies_D.get("notes"):
                            st.caption("🛠️ Penyesuaian Engine D: " + " · ".join(strategies_D["notes"]))
                        if tb.pre_post:
                            pp_lot = tb.pre_post.get("lot", {}).get("formatted", "—")
                            st.caption(f"⏱️ Pre/Post session: {pp_lot} lot")
                    else:
                        st.info(
                            "Trade Book belum tersedia untuk ticker/tanggal ini "
                            "(atau gagal dimuat)."
                        )

                    # Display Walls and Deltas
                    st.markdown("### 🧱 Orderbook Wall & Delta Signals")
                    wc1, wc2 = st.columns(2)
                    with wc1:
                        st.markdown("#### Buy Wall / Bid Deltas")
                        bid_wall_df = pd.DataFrame([{"Price": w.price, "Lot": w.lot, "Strength": f"{w.strength}%"} for w in bid_walls])
                        if not bid_wall_df.empty:
                            st.dataframe(
                                bid_wall_df, use_container_width=True, hide_index=True,
                                column_config={
                                    "Price": st.column_config.NumberColumn("Price", format="%d"),
                                    "Lot": st.column_config.NumberColumn("Lot", format="%d"),
                                },
                            )
                        else:
                            st.caption("No significant bid walls detected.")

                        bid_delta_df = pd.DataFrame([{"Price": d.price, "Delta Lot": d.lot, "Type": d.classification, "Strength": f"{d.strength}%"} for d in bid_deltas])
                        if not bid_delta_df.empty:
                            st.dataframe(bid_delta_df, use_container_width=True, hide_index=True)

                    with wc2:
                        st.markdown("#### Sell Wall / Ask Deltas")
                        ask_wall_df = pd.DataFrame([{"Price": w.price, "Lot": w.lot, "Strength": f"{w.strength}%"} for w in ask_walls])
                        if not ask_wall_df.empty:
                            st.dataframe(
                                ask_wall_df, use_container_width=True, hide_index=True,
                                column_config={
                                    "Price": st.column_config.NumberColumn("Price", format="%d"),
                                    "Lot": st.column_config.NumberColumn("Lot", format="%d"),
                                },
                            )
                        else:
                            st.caption("No significant ask walls detected.")

                        ask_delta_df = pd.DataFrame([{"Price": d.price, "Delta Lot": d.lot, "Type": d.classification, "Strength": f"{d.strength}%"} for d in ask_deltas])
                        if not ask_delta_df.empty:
                            st.dataframe(ask_delta_df, use_container_width=True, hide_index=True)

                    # Live Orderbook
                    st.markdown(f"### 📥 Live Orderbook Depth ({source_label})")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.markdown("#### Bid Depth (Buy Side)")
                        bids_list = [{"Price": int(lvl.price), "Lot Volume": lvl.lot, "Freq": lvl.freq} for lvl in snap.bid_levels]
                        if bids_list:
                            st.dataframe(
                                pd.DataFrame(bids_list), use_container_width=True, hide_index=True,
                                column_config={
                                    "Price": st.column_config.NumberColumn("Price", format="%d"),
                                    "Lot Volume": st.column_config.NumberColumn("Lot Volume", format="%d"),
                                    "Freq": st.column_config.NumberColumn("Freq", format="%d"),
                                },
                            )
                        else:
                            st.caption("No live bids available.")
                    with dc2:
                        st.markdown("#### Offer Depth (Sell Side)")
                        offers_list = [{"Price": int(lvl.price), "Lot Volume": lvl.lot, "Freq": lvl.freq} for lvl in snap.ask_levels]
                        if offers_list:
                            st.dataframe(
                                pd.DataFrame(offers_list), use_container_width=True, hide_index=True,
                                column_config={
                                    "Price": st.column_config.NumberColumn("Price", format="%d"),
                                    "Lot Volume": st.column_config.NumberColumn("Lot Volume", format="%d"),
                                    "Freq": st.column_config.NumberColumn("Freq", format="%d"),
                                },
                            )
                        else:
                            st.caption("No live offers available.")
                else:
                    st.error("Failed to connect to Exodus API & itick.org backup feed. Check auth token or try again.")
            else:
                st.warning(f"Ticker '{selected_detail}' not found in the Google Sheets database.")
    else:
        st.info("Refresh the feed to select tickers for detailed orderbook analysis.")
