import streamlit as st
import pandas as pd
from data.fetchers import safe_float
from datetime import datetime


def render_tab1(ticker_df):
    """Render Tab 1: Active Tickers Pool (Google Sheets vs live Stockbit source comparison)"""
    st.markdown("### 📋 Active Tickers Pool")
    active_ticker_df = ticker_df[ticker_df["Status"].str.contains("ACTIVE", na=False)].copy()
    
    st.markdown(f"**Total Emiten Aktif:** `{len(active_ticker_df)} emiten`")
    
    # Reconstruct comparison between cached Sheets data vs live updated screener_data
    comparison_rows = []
    
    for _, row in active_ticker_df.iterrows():
        ticker = row["Clean Ticker"]
        
        # Google Sheets timestamp parsing
        sheet_ts = None
        raw_ts = row.get("Last Update", "")
        if raw_ts:
            try:
                sheet_ts = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
                
        # Live Updated timestamp parsing
        live_ts = None
        live_source = "gsheet"
        live_price = safe_float(row.get("Price"))
        
        if "screener_data" in st.session_state and ticker in st.session_state.screener_data:
            live_entry = st.session_state.screener_data[ticker]
            live_price = safe_float(live_entry.get("last", live_price))
            live_source = live_entry.get("source", "gsheet")
            live_ts_obj = live_entry.get("source_ts")
            
            if live_ts_obj:
                if hasattr(live_ts_obj, 'replace'):
                    live_ts = live_ts_obj.replace(tzinfo=None) # Make timezone naive for comparison
                else:
                    live_ts = live_ts_obj

        # Display in Stockbit delta table only if Stockbit is newer than Google Sheets
        is_live_newer = False
        if live_source in ("stockbit", "exodus") and live_ts and sheet_ts:
            is_live_newer = live_ts > sheet_ts
        elif live_source in ("stockbit", "exodus") and live_ts and not sheet_ts:
            is_live_newer = True
            
        if is_live_newer:
            comparison_rows.append({
                "Ticker": ticker,
                "Company Name": row.get("Company Name", ""),
                "Google Sheets Price": safe_float(row.get("Price")),
                "Stockbit Live Price": live_price,
                "Google Sheets Update": raw_ts,
                "Stockbit Live Update": live_ts.strftime("%Y-%m-%d %H:%M:%S") if live_ts else "—",
                "Delta Price": live_price - safe_float(row.get("Price"))
            })

    # Sub-table for Stockbit overrides
    st.markdown("#### ⚡ Live Stockbit Overrides")
    st.caption("Menampilkan emiten yang data feed live-nya (dari Stockbit) lebih update dibanding data cache Google Sheets.")
    
    if comparison_rows:
        comp_df = pd.DataFrame(comparison_rows)
        st.dataframe(
            comp_df,
            column_config={
                "Google Sheets Price": st.column_config.NumberColumn("Sheets Price", format="IDR %d"),
                "Stockbit Live Price": st.column_config.NumberColumn("Stockbit Price", format="IDR %d"),
                "Delta Price": st.column_config.NumberColumn("Price Delta", format="IDR %+d"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Semua feed saat ini sinkron. Tidak ada ticker dengan update Stockbit yang lebih baru dibanding Google Sheets.")

    # General sheets pool view
    st.markdown("#### 📋 Database Pool (Google Sheets)")
    
    # Define clean column order
    col_order = [
        'Ticker', 'Company Name', 'Sector', 'Rank', 'Status', 'Score v2',
        'Price', 'Change%', 'Volume', 'Vol_Avg', 'MA20', 'Support', 'Breakout',
        'RSI14', 'SL_Practical', 'TP_Target', 'RR_Ratio', 'Last Update'
    ]
    # Keep remaining columns
    remaining_cols = [c for c in active_ticker_df.columns if c not in col_order and c != 'Clean Ticker']
    display_cols = col_order + remaining_cols
    
    st.dataframe(
        active_ticker_df[display_cols],
        column_config={
            "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
            "Change%": st.column_config.TextColumn("Change%"),
            "Volume": st.column_config.NumberColumn("Volume", format="%d"),
            "Vol_Avg": st.column_config.NumberColumn("Vol Avg", format="%d"),
            "MA20": st.column_config.NumberColumn("MA20", format="IDR %d"),
            "Support": st.column_config.NumberColumn("Support", format="IDR %d"),
            "Breakout": st.column_config.NumberColumn("Breakout", format="IDR %d"),
            "SL_Practical": st.column_config.NumberColumn("SL Practical", format="IDR %d"),
            "TP_Target": st.column_config.NumberColumn("TP Target", format="IDR %d"),
            "RSI14": st.column_config.NumberColumn("RSI (14)", format="%.1f"),
            "Score v2": st.column_config.NumberColumn("Score v2", format="%d"),
        },
        use_container_width=True,
        hide_index=True
    )