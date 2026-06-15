import streamlit as st
import pandas as pd
import asyncio
from datetime import datetime
from data.fetchers import safe_float, fetch_stockbit_detail
from data.scoring import compute_intraday_score, calculate_strategies

WIB = __import__("pytz").timezone("Asia/Jakarta")


def render_tab7(ticker_df, scored_list):
    """Render Tab 7: Deep Stock Analysis (Exodus API)"""
    st.markdown("### 🔍 Deep Stock Analysis (Exodus API)")
    st.caption("Fetches real-time bid/ask queue details and company statistics from unofficial Stockbit Exodus API.")
    
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
                    
                with st.spinner(f"⚡ Connecting to Exodus API for {selected_detail}..."):
                    snap = asyncio.run(fetch_stockbit_detail(selected_detail))
                    
                if snap:
                    score_data = compute_intraday_score(raw_data_obj, hist_row)
                    strategies = calculate_strategies(snap.last_price, score_data["score"], score_data["signal"])
                    
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
                    
                    # 3-Tier Strategies
                    st.markdown("### 🎯 3-Tier Execution Strategies")
                    sc1, sc2, sc3 = st.columns(3)
                    with sc1:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #FF6B6B">🔥 Aggressive (Breakout Play)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Aggressive']['entry']:,.0f}</li>
                                <li><b>Target:</b> IDR {strategies['Aggressive']['target']:,.0f} (+10%)</li>
                                <li><b>Stop Loss:</b> IDR {strategies['Aggressive']['sl']:,.0f} (-5%)</li>
                                <li><b>R/R Ratio:</b> {strategies['Aggressive']['rr']}x</li>
                                <li><b>Alloc:</b> {strategies['Aggressive']['size']}</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc2:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #FFFF00">⚡ Moderate (Pullback Play)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Moderate']['entry']:,.0f}</li>
                                <li><b>Target:</b> IDR {strategies['Moderate']['target']:,.0f} (+5%)</li>
                                <li><b>Stop Loss:</b> IDR {strategies['Moderate']['sl']:,.0f} (-7%)</li>
                                <li><b>R/R Ratio:</b> {strategies['Moderate']['rr']}x</li>
                                <li><b>Alloc:</b> {strategies['Moderate']['size']}</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)
                    with sc3:
                        st.markdown(f"""
                        <div class="strategy-card">
                            <h3 style="color: #00D4AA">🛡️ Low Risk (Support Buy)</h3>
                            <ul>
                                <li><b>Entry:</b> IDR {strategies['Low Risk']['entry']:,.0f}</li>
                                <li><b>Target:</b> IDR {strategies['Low Risk']['target']:,.0f} (+3%)</li>
                                <li><b>Stop Loss:</b> IDR {strategies['Low Risk']['sl']:,.0f} (-2%)</li>
                                <li><b>R/R Ratio:</b> {strategies['Low Risk']['rr']}x</li>
                                <li><b>Alloc:</b> {strategies['Low Risk']['size']}</li>
                            </ul>
                        </div>
                        """, unsafe_allow_html=True)

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
