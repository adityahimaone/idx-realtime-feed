import streamlit as st
import pandas as pd
import asyncio
from datetime import datetime
from data.fetchers import safe_float, fetch_stockbit_detail
from data.scoring import compute_intraday_score
from data.orderbook_wall import (
    detect_walls, track_delta, OrderbookLevel, WallScore,
    grounded_three_tier_A, grounded_three_tier_B,
    get_sentiment_label,
)
from repositories.sqlite_repository import sqlite_repository
from data.pre_ara import get_ara_price, ara_distance

WIB = __import__("pytz").timezone("Asia/Jakarta")


def _tier_sanity_warning(strategies, current_price, open_price, prev_close, max_pct_from_price=0.08):
    """
    Deteksi entry Moderate/Low Risk yang secara struktural tidak wajar —
    biasanya terjadi saat ARA membuat orderbook menipis/gap besar di bawah harga.
    max_pct_from_price: ambang toleransi jarak dari harga sekarang (default 8%, bisa di-tune).
    """
    floor_price = min(open_price, current_price * (1 - max_pct_from_price)) if open_price > 0 else current_price * (1 - max_pct_from_price)
    
    ara_price = get_ara_price(prev_close) if prev_close else 0.0
    is_near_ara = False
    if ara_price > 0:
        is_near_ara = ara_distance(current_price, ara_price) <= 1.0
        
    warnings = {}
    for tier in ["Moderat", "Low Risk"]:
        entry = strategies[tier]["entry"]
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
                # Force refresh by clearing cache
                cache_key = f"sb_detail_{search_input}"
                if cache_key in st.session_state:
                    del st.session_state[cache_key]
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
                
                import time
                cache_key = f"sb_detail_{selected_detail}"
                time_key = f"sb_time_{selected_detail}"
                snap = None
                now = time.time()
                was_fresh_fetch = False
                
                if cache_key in st.session_state and time_key in st.session_state and (now - st.session_state[time_key] < 10):
                    snap = st.session_state[cache_key]
                else:
                    with st.spinner(f"⚡ Connecting to Exodus API for {selected_detail}..."):
                        snap = asyncio.run(fetch_stockbit_detail(selected_detail))
                        if snap:
                            st.session_state[cache_key] = snap
                            st.session_state[time_key] = now
                            was_fresh_fetch = True
                    
                if snap:
                    # Override to st.session_state.screener_data
                    st.session_state.screener_data[selected_detail] = {
                        "last": snap.last_price,
                        "open": snap.open_price if snap.open_price else snap.last_price,
                        "high": snap.high if snap.high else snap.last_price,
                        "low": snap.low if snap.low else snap.last_price,
                        "volume": snap.volume,
                        "prev_close": snap.prev_close,
                        "source": "stockbit",
                        "source_ts": datetime.now(WIB),
                        "report": "Stockbit Exodus Live Direct (Deep Analysis Override)"
                    }
                    
                    # Refresh raw_data_obj with the overridden values
                    raw_data_obj = st.session_state.screener_data[selected_detail]

                    if was_fresh_fetch:
                        st.toast(f"✅ Price overrides updated for {selected_detail} to {snap.last_price}!")

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

                    # Grounded 3-Tier Strategies — Dual Engine
                    strategies_A = grounded_three_tier_A(snap.last_price, curr_bids, curr_asks)

                    # Engine B needs extra context
                    total_ask_lot = sum(lvl.lot for lvl in snap.ask_levels)
                    open_price_today = snap.open_price if snap.open_price else snap.last_price
                    # Derive avg_price from OHLC (no dedicated avg field available)
                    _high = snap.high if snap.high else snap.last_price
                    _low = snap.low if snap.low else snap.last_price
                    avg_price_est = (open_price_today + _high + _low + snap.last_price) / 4

                    strategies_B = grounded_three_tier_B(
                        last_price=snap.last_price,
                        bid_walls=curr_bids,
                        ask_walls=curr_asks,
                        total_bid_lot=snap.total_bid_lot,
                        total_ask_lot=total_ask_lot,
                        avg_price=avg_price_est,
                        open_price=open_price_today,
                    )

                    score_data = compute_intraday_score(raw_data_obj, hist_row)
                    tier_warnings = _tier_sanity_warning(strategies_A, snap.last_price, open_price_today, snap.prev_close)

                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        st.markdown(f"""
                        <div class="metric-card">
                            <h4>Live Signal</h4>
                            <h2 style="color: {score_data['color']}">{score_data['signal']}</h2>
                            <span>Score: {score_data['score']}/100</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with c2:
                        chg_sign = "+" if snap.change_pct > 0 else ""
                        chg_color = "#00D4AA" if snap.change_pct >= 0 else "#FF6B6B"
                        st.markdown(f"""
                        <div class="metric-card" style="border-left-color: {chg_color}">
                            <h4>Live Price</h4>
                            <h2>IDR {snap.last_price:,.0f}</h2>
                            <span style="color: {chg_color}">{chg_sign}{snap.change_pct:.2f}% Intraday</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with c3:
                        imb_color = "#00D4AA" if (snap.imbalance_ratio and snap.imbalance_ratio >= 1.0) else "#FF6B6B"
                        st.markdown(f"""
                        <div class="metric-card" style="border-left-color: {imb_color}">
                            <h4>Bid/Ask Imbalance</h4>
                            <h2>{snap.imbalance_ratio:.2f}x</h2>
                            <span>Total Bid: {snap.total_bid_lot:,} lot</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with c4:
                        st.markdown(f"""
                        <div class="metric-card" style="border-left-color: #00D4AA">
                            <h4>Source & Freshness</h4>
                            <h2 style="color: #00D4AA;">EXODUS API</h2>
                            <span>TS: {datetime.now(WIB).strftime('%H:%M:%S')} WIB (Live)</span>
                        </div>
                        """, unsafe_allow_html=True)
                         # Calculate position sizes (base values used by _render_strategy_cards)
                    base_portfolio = total_portfolio_value if total_portfolio_value > 0 else 100_000_000.0
                    is_default_port = total_portfolio_value <= 0
                    risk_budget = 0.01  # 1% of portfolio risk
                    risk_amount = base_portfolio * risk_budget


                    # Cross-link from portfolio
                    held_asset = next((a for a in st.session_state.get("portfolio", []) if a["Ticker"] == selected_detail), None)
                    if held_asset:
                        cur_avg = held_asset["Buy Price"]
                        cur_lots = held_asset["Lots"]
                        pl_pct = (snap.last_price - cur_avg) / cur_avg * 100 if cur_avg > 0 else 0.0
                        pl_color = "#10B981" if pl_pct >= 0 else "#EF4444"
                        st.markdown(f"""
                        <div class="notes-section" style="border-left-color:{pl_color};">
                        📌 <b>Posisi aktif:</b> {cur_lots:,} lot @ Rp {cur_avg:,.0f} avg
                        — P/L saat ini: <span style="color:{pl_color};font-weight:700;">{pl_pct:+.2f}%</span>.
                        Mau average down? Buka tab <b>💼 Live Portfolio Tracker</b> → Average Down Calculator,
                        pakai entry Low Risk (Rp {strategies_A['Low Risk']['entry']:,.0f}) sebagai referensi harga
                        kalau memang masih dalam batas wajar (lihat warning gap di atas kalau ada).
                        </div>
                        """, unsafe_allow_html=True)
 
                    # 3-Tier Strategies
                    st.markdown("### 🎯 Grounded 3-Tier Execution Strategies (Orderbook Based)")
                    st.markdown("""
                    <style>
                    .strategy-invalid {
                        opacity: 0.55;
                        border: 1px dashed #FF6B6B !important;
                        filter: grayscale(40%);
                    }
                    .strategy-disabled {
                        opacity: 0.35;
                        border: 1px dashed #888 !important;
                        filter: grayscale(70%);
                    }
                    </style>
                    """, unsafe_allow_html=True)

                    # ── Engine Selector ────────────────────────────────────────
                    imb = snap.imbalance_ratio if snap.imbalance_ratio else 1.0
                    auto_idx = 1 if imb < 0.8 else 0
                    engine_choice = st.radio(
                        "🔧 Engine Mode:",
                        ["Engine A — Wall Gravity (Neutral/Bullish)",
                         "Engine B — Contextual Alpha (Bearish/Volatile)",
                         "Both (Compare)"],
                        horizontal=True,
                        index=auto_idx,
                        key="engine_mode_radio",
                    )
                    use_A = "A" in engine_choice or "Both" in engine_choice
                    use_B = "B" in engine_choice or "Both" in engine_choice
                    is_both = "Both" in engine_choice

                    # Active strategies for sizing (use B if selected, else A)
                    strategies = strategies_B if use_B else strategies_A

                    # ── Sentiment Badge (Engine B) ────────────────────────────
                    if use_B:
                        sent_val = strategies_B.get('sentiment_factor', 1.0)
                        sent_lbl = strategies_B.get('sentiment_label', 'N/A')
                        sent_colors = {
                            "Very Bearish": "#FF4444",
                            "Bearish":      "#FF8C00",
                            "Mild Bearish": "#FFD700",
                            "Neutral":      "#AAAAAA",
                            "Bullish":      "#00D4AA",
                        }
                        sc_color = sent_colors.get(sent_lbl, "#AAAAAA")
                        agg_disabled_msg = "| ⛔ Aggressive tier DISABLED" if not strategies_B.get('aggressive_enabled') else ""
                        depth_cfg = strategies_B.get('depth_config', {})
                        st.markdown(f"""
                        <div style="background:#1a1a2e; border-left:4px solid {sc_color}; padding:10px;
                                    border-radius:6px; margin-bottom:12px;">
                            🎯 <b>Market Sentiment (Engine B):</b>
                            <span style="color:{sc_color}; font-weight:700;">{sent_lbl}</span>
                            — factor <code>{sent_val}</code>
                            {agg_disabled_msg}
                            | Bid/Ask: <code>{imb:.2f}x</code>
                            | Depth: Mod {depth_cfg.get('moderate_depth', 0.08)*100:.0f}% / LR {depth_cfg.get('low_risk_depth', 0.15)*100:.0f}%
                            | TP factor: <code>{depth_cfg.get('tp_factor', 1.0)}</code>
                        </div>
                        """, unsafe_allow_html=True)

                    if is_default_port:
                        st.caption("ℹ️ *Note: Sizing calculates from a default Rp 100 Juta port size because your actual portfolio is empty.*")
                    else:
                        st.caption(f"📊 *Sizing calculates dynamically from your actual active portfolio size: Rp {total_portfolio_value:,.0f}*")
                    st.caption("🛡️ *Sizing uses risk-first allocation: risking 1.0% of portfolio value per trade (max loss), capped at the maximum capital allocation tier.*")
                    st.caption("⚠️ *Penting: Pilih salah satu skenario entry di bawah yang paling sesuai dengan aksi pasar nyata — jangan mengambil kombinasi ketiganya sekaligus (total 45% portofolio).*")
                        
                    # ── Render strategy cards (helper to avoid duplication) ─
                    def _render_strategy_cards(strats, label_suffix=""):
                        """Render 3 strategy columns for a given engine output."""
                        sc1, sc2, sc3 = st.columns(3)

                        # --- Aggressive ---
                        with sc1:
                            agg = strats['Aggressive']
                            agg_disabled = agg.get('entry') is None
                            if agg_disabled:
                                st.markdown(f"""
                                <div class="strategy-card strategy-disabled">
                                <h3 style="color: #888">🔥 Aggressive{label_suffix} — DISABLED</h3>
                                <p style="color:#FF6B6B; padding:12px;">⛔ {agg.get('warning', 'Disabled by sentiment filter.')}</p>
                                </div>
                                """, unsafe_allow_html=True)
                            else:
                                agg_valid_class = '' if agg.get('valid', True) else 'strategy-invalid'
                                agg_rr_badge = '✅' if agg.get('valid', True) else '⚠️ R/R Rendah'
                                # Position sizing
                                _agg_entry = agg['entry']
                                _agg_sl = agg['sl']
                                _agg_rps = _agg_entry - _agg_sl if _agg_entry > _agg_sl else 0
                                _agg_lots_risk = int(risk_amount / (_agg_rps * 100)) if _agg_rps > 0 else 0
                                _agg_lots_cap = int((base_portfolio * 0.10) / (_agg_entry * 100)) if _agg_entry > 0 else 0
                                _agg_lots = min(_agg_lots_risk, _agg_lots_cap) if _agg_rps > 0 else _agg_lots_cap
                                _agg_val = _agg_lots * _agg_entry * 100
                                _agg_risk_val = _agg_lots * _agg_rps * 100
                                _risk_disp_agg = f"Rp {_agg_risk_val:,.0f} ({_agg_risk_val/base_portfolio*100:.2f}%)" if _agg_rps > 0 else "⚠️ SL tidak valid"
                                st.markdown(f"""
                                <div class="strategy-card {agg_valid_class}">
                                <h3 style="color: #FF6B6B">🔥 Aggressive{label_suffix} (Breakout Play)</h3>
                                <ul>
                                    <li><b>Entry:</b> IDR {_agg_entry:,.0f}</li>
                                    <li><b>Target (TP):</b> IDR {agg['tp']:,.0f}</li>
                                    <li><b>Stop Loss (SL):</b> IDR {_agg_sl:,.0f}</li>
                                    <li><b>R/R Ratio:</b> {agg['rr']}x {agg_rr_badge}</li>
                                    <li><b>Suggested Size (10% cap):</b> <b style="color:#FF6B6B;">{_agg_lots:,} Lots</b> (Rp {_agg_val:,.0f})</li>
                                    <li><b>Max Loss at SL:</b> {_risk_disp_agg}</li>
                                </ul>
                                </div>
                                """, unsafe_allow_html=True)
                                if not agg.get('valid', True):
                                    st.warning(f"⚠️ **Aggressive**: {agg['warning']}")

                        # --- Moderate ---
                        with sc2:
                            mod = strats['Moderat']
                            mod_valid_class = '' if mod.get('valid', True) else 'strategy-invalid'
                            mod_rr_badge = '✅' if mod.get('valid', True) else '⚠️ R/R Rendah'
                            wall_info_mod = ""
                            if mod.get('wall_price'):
                                wall_info_mod = f"<li><b>Anchored to Wall:</b> Rp {mod['wall_price']:,.0f} ({mod['wall_lot']:,} lot, score {mod.get('wall_score', 'N/A')})</li>"
                            _mod_entry = mod['entry']
                            _mod_sl = mod['sl']
                            _mod_rps = _mod_entry - _mod_sl if _mod_entry > _mod_sl else 0
                            _mod_lots_risk = int(risk_amount / (_mod_rps * 100)) if _mod_rps > 0 else 0
                            _mod_lots_cap = int((base_portfolio * 0.15) / (_mod_entry * 100)) if _mod_entry > 0 else 0
                            _mod_lots = min(_mod_lots_risk, _mod_lots_cap) if _mod_rps > 0 else _mod_lots_cap
                            _mod_val = _mod_lots * _mod_entry * 100
                            _mod_risk_val = _mod_lots * _mod_rps * 100
                            _risk_disp_mod = f"Rp {_mod_risk_val:,.0f} ({_mod_risk_val/base_portfolio*100:.2f}%)" if _mod_rps > 0 else "⚠️ SL tidak valid"
                            st.markdown(f"""
                            <div class="strategy-card {mod_valid_class}">
                                <h3 style="color: #FFFF00">⚡ Moderate{label_suffix} (Pullback Play)</h3>
                                <ul>
                                    <li><b>Entry:</b> IDR {_mod_entry:,.0f}</li>
                                    <li><b>Target (TP):</b> IDR {mod['tp']:,.0f}</li>
                                    <li><b>Stop Loss (SL):</b> IDR {_mod_sl:,.0f}</li>
                                    <li><b>R/R Ratio:</b> {mod['rr']}x {mod_rr_badge}</li>
                                    {wall_info_mod}
                                    <li><b>Suggested Size (15% cap):</b> <b style="color:#FFFF00;">{_mod_lots:,} Lots</b> (Rp {_mod_val:,.0f})</li>
                                    <li><b>Max Loss at SL:</b> {_risk_disp_mod}</li>
                                </ul>
                            </div>
                            """, unsafe_allow_html=True)
                            if not mod.get('valid', True):
                                st.warning(f"⚠️ **Moderat**: {mod['warning']}")
                            if "Moderat" in tier_warnings:
                                st.caption(f"🚨 {tier_warnings['Moderat']}")

                        # --- Low Risk ---
                        with sc3:
                            low = strats['Low Risk']
                            low_valid_class = '' if low.get('valid', True) else 'strategy-invalid'
                            low_rr_badge = '✅' if low.get('valid', True) else '⚠️ R/R Rendah'
                            wall_info_low = ""
                            if low.get('wall_price'):
                                wall_info_low = f"<li><b>Anchored to Wall:</b> Rp {low['wall_price']:,.0f} ({low['wall_lot']:,} lot, score {low.get('wall_score', 'N/A')})</li>"
                            _low_entry = low['entry']
                            _low_sl = low['sl']
                            _low_rps = _low_entry - _low_sl if _low_entry > _low_sl else 0
                            _low_lots_risk = int(risk_amount / (_low_rps * 100)) if _low_rps > 0 else 0
                            _low_lots_cap = int((base_portfolio * 0.20) / (_low_entry * 100)) if _low_entry > 0 else 0
                            _low_lots = min(_low_lots_risk, _low_lots_cap) if _low_rps > 0 else _low_lots_cap
                            _low_val = _low_lots * _low_entry * 100
                            _low_risk_val = _low_lots * _low_rps * 100
                            _risk_disp_low = f"Rp {_low_risk_val:,.0f} ({_low_risk_val/base_portfolio*100:.2f}%)" if _low_rps > 0 else "⚠️ SL tidak valid"
                            st.markdown(f"""
                            <div class="strategy-card {low_valid_class}">
                                <h3 style="color: #00D4AA">🛡️ Low Risk{label_suffix} (Support Buy)</h3>
                                <ul>
                                    <li><b>Entry:</b> IDR {_low_entry:,.0f}</li>
                                    <li><b>Target (TP):</b> IDR {low['tp']:,.0f}</li>
                                    <li><b>Stop Loss (SL):</b> IDR {_low_sl:,.0f}</li>
                                    <li><b>R/R Ratio:</b> {low['rr']}x {low_rr_badge}</li>
                                    {wall_info_low}
                                    <li><b>Suggested Size (20% cap):</b> <b style="color:#00D4AA;">{_low_lots:,} Lots</b> (Rp {_low_val:,.0f})</li>
                                    <li><b>Max Loss at SL:</b> {_risk_disp_low}</li>
                                </ul>
                            </div>
                            """, unsafe_allow_html=True)
                            if not low.get('valid', True):
                                st.warning(f"⚠️ **Low Risk**: {low['warning']}")
                            if "Low Risk" in tier_warnings:
                                st.caption(f"🚨 {tier_warnings['Low Risk']}")

                    # ── Render based on engine choice ─────────────────────────
                    if is_both:
                        st.markdown("#### 🅰️ Engine A — Wall Gravity")
                        st.caption("Pure structural analysis. No market context.")
                        _render_strategy_cards(strategies_A, " [A]")

                        st.markdown("---")
                        st.markdown("#### 🅱️ Engine B — Contextual Alpha")
                        st.caption(f"Sentiment-adjusted. Factor: {strategies_B.get('sentiment_factor', '?')}x ({strategies_B.get('sentiment_label', '?')})")
                        _render_strategy_cards(strategies_B, " [B]")
                    else:
                        engine_lbl = strategies.get('engine_label', 'Wall Gravity')
                        st.caption(f"🔧 Active Engine: **{engine_lbl}**")
                        _render_strategy_cards(strategies)

                    # Display Walls and Deltas
                    st.markdown("### 🧱 Orderbook Wall & Delta Signals")
                    wc1, wc2 = st.columns(2)
                    with wc1:
                        st.markdown("#### Buy Wall / Bid Deltas")
                        bid_wall_df = pd.DataFrame([{"Price": w.price, "Lot": w.lot, "Strength": f"{w.strength}%"} for w in bid_walls])
                        if not bid_wall_df.empty:
                            st.dataframe(bid_wall_df, use_container_width=True)
                        else:
                            st.caption("No significant bid walls detected.")
                        
                        bid_delta_df = pd.DataFrame([{"Price": d.price, "Delta Lot": d.lot, "Type": d.classification, "Strength": f"{d.strength}%"} for d in bid_deltas])
                        if not bid_delta_df.empty:
                            st.dataframe(bid_delta_df, use_container_width=True)

                    with wc2:
                        st.markdown("#### Sell Wall / Ask Deltas")
                        ask_wall_df = pd.DataFrame([{"Price": w.price, "Lot": w.lot, "Strength": f"{w.strength}%"} for w in ask_walls])
                        if not ask_wall_df.empty:
                            st.dataframe(ask_wall_df, use_container_width=True)
                        else:
                            st.caption("No significant ask walls detected.")

                        ask_delta_df = pd.DataFrame([{"Price": d.price, "Delta Lot": d.lot, "Type": d.classification, "Strength": f"{d.strength}%"} for d in ask_deltas])
                        if not ask_delta_df.empty:
                            st.dataframe(ask_delta_df, use_container_width=True)

                    # Live Orderbook
                    st.markdown("### 📥 Live Orderbook Depth (Exodus API)")
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.markdown("#### Bid Depth (Buy Side)")
                        bids_list = [{"Price": int(lvl.price), "Lot Volume": lvl.lot, "Frequency": lvl.freq} for lvl in snap.bid_levels]
                        if bids_list:
                            st.table(pd.DataFrame(bids_list))
                        else:
                            st.caption("No live bids available.")
                    with dc2:
                        st.markdown("#### Offer Depth (Sell Side)")
                        offers_list = [{"Price": int(lvl.price), "Lot Volume": lvl.lot, "Frequency": lvl.freq} for lvl in snap.ask_levels]
                        if offers_list:
                            st.table(pd.DataFrame(offers_list))
                        else:
                            st.caption("No live offers available.")
                else:
                    st.error("Failed to connect to Exodus API feed. Check auth token or try again.")
            else:
                st.warning(f"Ticker '{selected_detail}' not found in the Google Sheets database.")
    else:
        st.info("Refresh the feed to select tickers for detailed orderbook analysis.")
