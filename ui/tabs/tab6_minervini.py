import streamlit as st
import pandas as pd
from data.fetchers import safe_float


def render_tab6(scored_list_global, scored_list, exclude_filters_minervini):
    """Render Tab 6: Mark Minervini Trend Template"""
    st.markdown("### 📈 Mark Minervini Trend Template")
    st.caption("Validates tickers against Mark Minervini's legendary Stage 2 Uptrend criteria based on historical daily moving averages.")
    
    minervini_source_list = scored_list_global if exclude_filters_minervini else scored_list
    if minervini_source_list:
        minervini_data = []
        for s in minervini_source_list:
            hist_row = s["hist_row_obj"]
            raw_data = s["raw_data_obj"]
            ticker = s["Ticker"]
            
            last = s["Live Price"]
            
            sma50 = safe_float(hist_row.get("MA50", 0))
            sma200 = safe_float(hist_row.get("MA200", 0))
            sma150 = safe_float(hist_row.get("MA150", 0))
            if sma150 <= 0:
                sma150 = round(sma50 * 0.4 + sma200 * 0.6, 2)
                
            high52 = safe_float(hist_row.get("52W High", 0))
            if high52 <= 0:
                high52 = last * 1.10
                
            vol_today = safe_float(raw_data.get("volume", 0))
            vol_avg20 = safe_float(hist_row.get("Vol_Avg", 1))
            if vol_avg20 <= 0:
                vol_avg20 = 1.0
                
            conds = {
                "Price > SMA50": last > sma50,
                "Price > SMA150": last > sma150,
                "Price > SMA200": last > sma200,
                "SMA50 > SMA150": sma50 > sma150,
                "SMA150 > SMA200": sma150 > sma200,
                "SMA50 > SMA200": sma50 > sma200,
                "Within 25% of 52W High": last >= (high52 * 0.75),
                "Volume > Avg20": vol_today > vol_avg20
            }
            
            score_val = sum(conds.values())
            passed = (score_val >= 6)
            
            minervini_data.append({
                "Ticker": ticker,
                "Company Name": s["Company Name"],
                "Live Price": last,
                "SMA 50": sma50,
                "SMA 150 (Est)": sma150,
                "SMA 200": sma200,
                "52W High": high52,
                "Score": f"{score_val}/8",
                "Passed Template": "✅ PASSED" if passed else "❌ FAILED",
                "score_int": score_val
            })
            
        if minervini_data:
            min_df = pd.DataFrame(minervini_data).sort_values(by="score_int", ascending=False)
            st.dataframe(
                min_df,
                column_config={
                    "Live Price": st.column_config.NumberColumn("Live Price", format="IDR %d"),
                    "SMA 50": st.column_config.NumberColumn("SMA 50", format="IDR %d"),
                    "SMA 150 (Est)": st.column_config.NumberColumn("SMA 150", format="IDR %d"),
                    "SMA 200": st.column_config.NumberColumn("SMA 200", format="IDR %d"),
                    "52W High": st.column_config.NumberColumn("52W High", format="IDR %d"),
                    "Score": st.column_config.TextColumn("Condition Score"),
                    "Passed Template": st.column_config.TextColumn("Minervini Setup"),
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No tickers evaluated for Mark Minervini Trend Template.")
    else:
        st.info("Refresh the live feed to calculate Mark Minervini trend template checklists.")
