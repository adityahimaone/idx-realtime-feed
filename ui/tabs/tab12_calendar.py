import streamlit as st
import pandas as pd
import time
from datetime import datetime
from curl_cffi import requests as requests_cf

WIB = __import__("pytz").timezone("Asia/Jakarta")


def fetch_idx_calendar(date_str: str) -> list[dict]:
    """Fetch corporate calendar from IDX website."""
    url = f"https://www.idx.co.id/primary/Home/GetCalendar?range=m&date={date_str}"
    try:
        r = requests_cf.get(url, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            return r.json().get("Results", [])
    except Exception as e:
        st.error(f"Failed to fetch IDX Calendar: {e}")
    return []


def render_tab12():
    st.markdown("### 📅 IDX Corporate Calendar & Event Signals")
    st.caption("Fetches monthly corporate actions (RUPS, Dividends, etc.) from the official IDX API and analyzes pre-event price momentum signals (H-1).")
    
    # Date Input
    now_dt = datetime.now(WIB)
    
    selected_date = st.date_input("Select Base Date (Fetches Full Month)", value=now_dt)
    date_param = selected_date.strftime("%Y%m%d")
    
    with st.spinner("📅 Syncing corporate events from IDX..."):
        events = fetch_idx_calendar(date_param)
        
    if not events:
        st.info("No corporate calendar events found for the selected month.")
        return
        
    # Process events into display records
    records = []
    for ev in events:
        ticker = ev.get("title", "").strip().upper()
        desc = ev.get("description", "")
        start_raw = ev.get("start", "")
        event_date = "-"
        if start_raw:
            try:
                dt_obj = datetime.strptime(start_raw[:10], "%Y-%m-%d")
                event_date = dt_obj.strftime("%d %b %Y")
            except Exception:
                event_date = start_raw[:10]
                
        jenis = ev.get("Jenis", "-")
        
        # Analyze Signal / Sentiment
        desc_lower = desc.lower()
        if "dividen" in desc_lower or "dividend" in desc_lower or "bagi hasil" in desc_lower:
            signal = "🟢 Speculative Buy (Pre-Dividend Momentum)"
            notes = "Announcements of dividends usually spark buy interest. Best entry window: H-1 before event or cum-date."
        elif "stock split" in desc_lower or "pecah saham" in desc_lower:
            signal = "🟢 Speculative Buy (Liquidity Event)"
            notes = "Stock splits increase retail accessibility. Positive liquidity momentum is expected leading up to split."
        elif "penggabungan nilai" in desc_lower or "reverse split" in desc_lower or "merger" in desc_lower:
            signal = "🔴 Avoid / High Risk (Capital Consolidation)"
            notes = "Reverse splits are usually negatively perceived due to signs of underlying distress."
        elif "rups" in desc_lower or "general meeting" in desc_lower:
            signal = "🟡 Watch (AGMS/EGMS Vote)"
            notes = "AGMS/EGMS events are regulatory. Look out for unexpected corporate actions (e.g. rights issue or change of board)."
        elif "rights issue" in desc_lower or "hmetd" in desc_lower:
            signal = "🟡 Speculative (Capital Expansion)"
            notes = "Rights issue dilutes shares but raises capital. Bullish if funds are for clear expansions."
        else:
            signal = "🟡 Watch (Corporate Event)"
            notes = "Regular event. Keep an eye on direct mentions in stock news channels."
            
        records.append({
            "Date": event_date,
            "Ticker": ticker,
            "Event Type": jenis,
            "Description": desc,
            "H-1 Signal Analysis": signal,
            "Action Notes": notes,
            "_raw_start": start_raw
        })
        
    # Convert to DataFrame
    df = pd.DataFrame(records)
    
    # Sorting by date
    if not df.empty:
        df = df.sort_values("_raw_start", ascending=True)
        
    # Filters
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        f_ticker = st.text_input("Filter Ticker (e.g. MTEL):", "").strip().upper()
    with col2:
        f_type = st.multiselect("Filter Signal", options=[
            "🟢 Speculative Buy (Pre-Dividend Momentum)",
            "🟢 Speculative Buy (Liquidity Event)",
            "🟡 Watch (AGMS/EGMS Vote)",
            "🟡 Speculative (Capital Expansion)",
            "🔴 Avoid / High Risk (Capital Consolidation)",
            "🟡 Watch (Corporate Event)"
        ], default=[])
        
    filtered_df = df.copy()
    if f_ticker:
        filtered_df = filtered_df[filtered_df["Ticker"] == f_ticker]
    if f_type:
        filtered_df = filtered_df[filtered_df["H-1 Signal Analysis"].isin(f_type)]
        
    if filtered_df.empty:
        st.warning("No events match your current filters.")
        return
        
    # Render table
    st.dataframe(
        filtered_df[["Date", "Ticker", "Event Type", "Description", "H-1 Signal Analysis", "Action Notes"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Date": st.column_config.TextColumn("Date", width="medium"),
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Event Type": st.column_config.TextColumn("Event Type", width="small"),
            "Description": st.column_config.TextColumn("Description", width="large"),
            "H-1 Signal Analysis": st.column_config.TextColumn("H-1 Signal Analysis", width="medium"),
            "Action Notes": st.column_config.TextColumn("Action Notes", width="large"),
        }
    )
    
    st.caption(f"Showing {len(filtered_df)} events.")
