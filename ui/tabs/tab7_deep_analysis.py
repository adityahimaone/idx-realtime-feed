import streamlit as st
import pandas as pd
import asyncio
from datetime import datetime
from data.fetchers import safe_float, fetch_stockbit_detail
from data.scoring import compute_intraday_score
from data.orderbook_wall import detect_walls, track_delta, grounded_three_tier, OrderbookLevel
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

                    # Grounded 3-Tier Strategies
                    strategies = grounded_three_tier(snap.last_price, bid_walls, ask_walls)
                    score_data = compute_intraday_score(raw_data_obj, hist_row)
                    
                    open_price_today = snap.open_price if snap.open_price else snap.last_price
                    tier_warnings = _tier_sanity_warning(strategies, snap.last_price, open_price_today, snap.prev_close)

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
                    
                    # Calculate position sizes
                    base_portfolio = total_portfolio_value if total_portfolio_value > 0 else 100_000_000.0
                    is_default_port = total_portfolio_value <= 0
                    
                    risk_budget = 0.01 # 1% of portfolio risk
                    risk_amount = base_portfolio * risk_budget
                    
                    # Aggressive
                    agg_entry = strategies['Aggressive']['entry']
                    agg_sl = strategies['Aggressive']['sl']
                    agg_risk_per_share = agg_entry - agg_sl if agg_entry > agg_sl else 0
                    agg_lots_by_risk = int(risk_amount / (agg_risk_per_share * 100)) if agg_risk_per_share > 0 else 0
                    agg_lots_by_cap = int((base_portfolio * 0.10) / (agg_entry * 100)) if agg_entry > 0 else 0
                    agg_lots = min(agg_lots_by_risk, agg_lots_by_cap) if agg_risk_per_share > 0 else agg_lots_by_cap
                    agg_val = agg_lots * agg_entry * 100
                    agg_risk_val = agg_lots * agg_risk_per_share * 100
                    
                    # Moderate
                    mod_entry = strategies['Moderat']['entry']
                    mod_sl = strategies['Moderat']['sl']
                    mod_risk_per_share = mod_entry - mod_sl if mod_entry > mod_sl else 0
                    mod_lots_by_risk = int(risk_amount / (mod_risk_per_share * 100)) if mod_risk_per_share > 0 else 0
                    mod_lots_by_cap = int((base_portfolio * 0.15) / (mod_entry * 100)) if mod_entry > 0 else 0
                    mod_lots = min(mod_lots_by_risk, mod_lots_by_cap) if mod_risk_per_share > 0 else mod_lots_by_cap
                    mod_val = mod_lots * mod_entry * 100
                    mod_risk_val = mod_lots * mod_risk_per_share * 100
                    
                    # Low Risk
                    low_entry = strategies['Low Risk']['entry']
                    low_sl = strategies['Low Risk']['sl']
                    low_risk_per_share = low_entry - low_sl if low_entry > low_sl else 0
                    low_lots_by_risk = int(risk_amount / (low_risk_per_share * 100)) if low_risk_per_share > 0 else 0
                    low_lots_by_cap = int((base_portfolio * 0.20) / (low_entry * 100)) if low_entry > 0 else 0
                    low_lots = min(low_lots_by_risk, low_lots_by_cap) if low_risk_per_share > 0 else low_lots_by_cap
                    low_val = low_lots * low_entry * 100
                    low_risk_val = low_lots * low_risk_per_share * 100

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
                        pakai entry Low Risk (Rp {strategies['Low Risk']['entry']:,.0f}) sebagai referensi harga
                        kalau memang masih dalam batas wajar (lihat warning gap di atas kalau ada).
                        </div>
                        """, unsafe_allow_html=True)

                    # 3-Tier Strategies
                    st.markdown("### 🎯 Grounded 3-Tier Execution Strategies (Orderbook Based)")
                    if is_default_port:
                        st.caption("ℹ️ *Note: Sizing calculates from a default Rp 100 Juta port size because your actual portfolio is empty.*")
                    else:
                        st.caption(f"📊 *Sizing calculates dynamically from your actual active portfolio size: Rp {total_portfolio_value:,.0f}*")
                    st.caption("🛡️ *Sizing uses risk-first allocation: risking 1.0% of portfolio value per trade (max loss), capped at the maximum capital allocation tier.*")
                    st.caption("⚠️ *Penting: Pilih salah satu skenario entry di bawah yang paling sesuai dengan aksi pasar nyata — jangan mengambil kombinasi ketiganya sekaligus (total 45% portofolio).*")
                        
                    sc1, sc2, sc3 = st.columns(3)
                    with sc1:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #FF6B6B">🔥 Aggressive (Breakout Play)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Aggressive']['entry']:,.0f}</li>
                                <li><b>Target (TP):</b> IDR {strategies['Aggressive']['tp']:,.0f}</li>
                                <li><b>Stop Loss (SL):</b> IDR {strategies['Aggressive']['sl']:,.0f}</li>
                                <li><b>R/R Ratio:</b> {strategies['Aggressive']['rr']}x</li>
                                <li><b>Suggested Size (10% cap):</b> <b style="color:#FF6B6B;">{agg_lots:,} Lots</b> (Rp {agg_val:,.0f})</li>
                                <li><b>Max Loss at SL:</b> Rp {agg_risk_val:,.0f} ({agg_risk_val/base_portfolio*100:.2f}%)</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc2:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #FFFF00">⚡ Moderate (Pullback Play)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Moderat']['entry']:,.0f}</li>
                                <li><b>Target (TP):</b> IDR {strategies['Moderat']['tp']:,.0f}</li>
                                <li><b>Stop Loss (SL):</b> IDR {strategies['Moderat']['sl']:,.0f}</li>
                                <li><b>R/R Ratio:</b> {strategies['Moderat']['rr']}x</li>
                                <li><b>Suggested Size (15% cap):</b> <b style="color:#FFFF00;">{mod_lots:,} Lots</b> (Rp {mod_val:,.0f})</li>
                                <li><b>Max Loss at SL:</b> Rp {mod_risk_val:,.0f} ({mod_risk_val/base_portfolio*100:.2f}%)</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                        if "Moderat" in tier_warnings:
                            st.caption(f"🚨 {tier_warnings['Moderat']}")
                    with sc3:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #00D4AA">🛡️ Low Risk (Support Buy)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Low Risk']['entry']:,.0f}</li>
                                <li><b>Target (TP):</b> IDR {strategies['Low Risk']['tp']:,.0f}</li>
                                <li><b>Stop Loss (SL):</b> IDR {strategies['Low Risk']['sl']:,.0f}</li>
                                <li><b>R/R Ratio:</b> {strategies['Low Risk']['rr']}x</li>
                                <li><b>Suggested Size (20% cap):</b> <b style="color:#00D4AA;">{low_lots:,} Lots</b> (Rp {low_val:,.0f})</li>
                                <li><b>Max Loss at SL:</b> Rp {low_risk_val:,.0f} ({low_risk_val/base_portfolio*100:.2f}%)</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                        if "Low Risk" in tier_warnings:
                            st.caption(f"🚨 {tier_warnings['Low Risk']}")

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
