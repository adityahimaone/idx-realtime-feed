"""
Sidebar filters + auto-refresh countdown.
"""
import streamlit as st
import time


def render_sidebar(ticker_df, fetch_screener_batch):
    """Returns dict of sidebar state used downstream."""
    with st.sidebar:
        st.markdown("## 🔍 Screener Settings")
        st.markdown("---")

        if st.query_params.get("auto_scan", "false") == "true":
            st.session_state["trigger_auto_scan"] = True
            st.query_params["auto_scan"] = "false"

        # Auto Refresh
        st.subheader("🔁 Auto Refresh")
        init_auto_refresh = st.query_params.get("auto_refresh", "false") == "true"
        init_interval = int(st.query_params.get("refresh_interval", "10"))
        if init_interval not in [5, 10, 15, 30]:
            init_interval = 10

        auto_refresh_enabled = st.checkbox("Enable Auto Refresh", value=init_auto_refresh)
        refresh_interval = init_interval
        if auto_refresh_enabled:
            interval_options = [5, 10, 15, 30]
            interval_index = interval_options.index(init_interval) if init_interval in interval_options else 1
            refresh_interval = st.selectbox("Interval (Minutes)", options=interval_options, index=interval_index)

            if st.query_params.get("auto_refresh") != "true" or st.query_params.get("refresh_interval") != str(refresh_interval):
                st.query_params["auto_refresh"] = "true"
                st.query_params["refresh_interval"] = str(refresh_interval)

            if "next_refresh_time" not in st.session_state or st.session_state.get("last_refresh_interval") != refresh_interval:
                st.session_state.next_refresh_time = time.time() + (refresh_interval * 60)
                st.session_state.last_refresh_interval = refresh_interval

            time_left = int(st.session_state.next_refresh_time - time.time())
            if time_left <= 0:
                if not st.session_state.get("auto_scan_triggered", False):
                    st.session_state.next_refresh_time = time.time() + (refresh_interval * 60)
                    st.session_state["trigger_auto_scan"] = True
                    st.session_state["auto_scan_triggered"] = True
            else:
                st.session_state["auto_scan_triggered"] = False
                time_display = f"{time_left // 60}m {time_left % 60}s"
                target_time = int(st.session_state.next_refresh_time * 1000)
                countdown_html = f"""<div style="background:rgba(56,189,248,0.15);border:1px solid rgba(56,189,248,0.3);padding:10px;border-radius:8px;color:#38BDF8;font-weight:700;font-size:0.9em;margin-bottom:10px;">⏳ Next auto-scan in: <span id="countdown_timer_span">{time_display}</span></div>
<script>(function(){{var t={target_time},i={refresh_interval};setInterval(function(){{var d=Math.max(0,Math.floor((t-Date.now())/1000)),s=document.getElementById("countdown_timer_span");if(s)s.textContent=Math.floor(d/60)+"m "+(d%60)+"s";if(d<=0){{clearInterval();s.textContent="0m 0s (Scan Complete)";var l=window.location;try{{if(window.parent&&window.parent.location)l=window.parent.location;}}catch(e){{}}l.href=l.pathname+"?auto_refresh=true&auto_scan=true&refresh_interval="+i;}}}},1000);}})();</script>"""
                st.components.v1.html(countdown_html, height=48)
        else:
            if st.query_params.get("auto_refresh") == "true":
                st.query_params["auto_refresh"] = "false"

        st.markdown("---")
        st.subheader("⏱️ Fetch Polling Delay")
        fetch_delay = st.slider("Delay per Ticker (seconds)", min_value=0.1, max_value=3.0, value=0.5, step=0.1)

        st.subheader("📊 Scan Ticker Limit")
        max_scan = st.slider("Max Tickers to Scan", min_value=10, max_value=min(500, len(ticker_df)) if not ticker_df.empty else 100, value=50, step=10)

        st.markdown("---")
        st.subheader("🎯 Watchlist Filter")
        unique_sectors = sorted(list(ticker_df["Sector"].unique())) if "Sector" in ticker_df.columns else []
        selected_sectors = st.multiselect("Sectors", unique_sectors, default=[])

        unique_ranks = sorted(list(ticker_df["Rank"].unique())) if "Rank" in ticker_df.columns else []
        selected_ranks = st.multiselect("Ranks", unique_ranks, default=["⭐ Strong Buy"])

        min_score = st.slider("Minimum Historical Score v2", 0, 100, 50)

        st.markdown("---")
        st.subheader("⚙️ Tab Scope Options")
        exclude_filters_trending = st.checkbox("Exclude filters for Trending Stocks", value=True)
        exclude_filters_bsjp = st.checkbox("Exclude filters for BSJP", value=True)
        exclude_filters_minervini = st.checkbox("Exclude filters for Minervini Trend", value=True)

        st.markdown("---")
        search_ticker = st.text_input("Lookup Specific Ticker (e.g. ADRO)", "").upper().strip()

    return {
        "fetch_delay": fetch_delay,
        "max_scan": max_scan,
        "selected_sectors": selected_sectors,
        "selected_ranks": selected_ranks,
        "min_score": min_score,
        "exclude_filters_trending": exclude_filters_trending,
        "exclude_filters_bsjp": exclude_filters_bsjp,
        "exclude_filters_minervini": exclude_filters_minervini,
        "search_ticker": search_ticker,
    }
