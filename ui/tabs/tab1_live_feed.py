import streamlit as st
import pandas as pd
from data.fetchers import safe_float

def render_tab1(ticker_df):
    """Render Tab 1: Active Tickers Pool (Google Sheets)"""
    st.markdown("### 📋 Active Tickers Pool (Google Sheets)")
    st.caption("Displays all active tickers currently loaded from the Google Sheets 'All Tickers' database.")
    
    # Filter active tickers (status contains ACTIVE)
    active_ticker_df = ticker_df[ticker_df["Status"].str.contains("ACTIVE", na=False)].copy()
    
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