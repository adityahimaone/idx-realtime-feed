import streamlit as st
import pandas as pd
from data.fetchers import safe_float


def render_tab5(scored_list_global, scored_list, exclude_filters_bsjp):
    """Render Tab 5: BSJP (Beli Sore, Jual Pagi) Recommendations"""
    st.markdown("### 🌙 BSJP (Beli Sore, Jual Pagi) Recommendations")
    st.caption("BSJP setups are ideally analyzed between 15:00 - 16:15 WIB before market close.")
    
    bsjp_source_list = scored_list_global if exclude_filters_bsjp else scored_list
    if bsjp_source_list:
        bsjp_data = []
        for s in bsjp_source_list:
            hist_row = s["hist_row_obj"]
            raw_data = s["raw_data_obj"]
            
            price = s["Live Price"]
            high = safe_float(raw_data.get("high", price))
            low = safe_float(raw_data.get("low", price))
            
            chg = s["Change %"]
            
            support = safe_float(hist_row.get("Support", price * 0.95))
            if support <= 0 or support >= price:
                support = price * 0.95
                
            resistance = safe_float(hist_row.get("Breakout", price * 1.05))
            if resistance <= 0 or resistance <= price:
                resistance = price * 1.05
                
            day_range = high - low
            price_pos = (price - low) / day_range if day_range > 0 else 1.0
            
            if chg > 1.0 and price_pos >= 0.7:
                tp = round(resistance, 2)
                sl = round(max(support, price * 0.97), 2)
                rr = (tp - price) / max(1.0, price - sl)
                
                vsr = safe_float(raw_data.get("volume", 0)) / safe_float(hist_row.get("Vol_Avg", 1)) if safe_float(hist_row.get("Vol_Avg", 1)) > 0 else 1.0
                setup_score = int(round(s["Intraday Score"] * 0.7 + min(100, vsr * 20) * 0.3))
                
                if rr >= 1.2 and setup_score >= 60:
                    bsjp_data.append({
                        "Ticker": s["Ticker"],
                        "Company Name": s["Company Name"],
                        "Live Price": price,
                        "Change %": chg,
                        "Price Pos (Day Range)": f"{int(price_pos * 100)}%",
                        "Volume Surge (VSR)": vsr,
                        "Entry (Buy Sore)": price,
                        "Target (Jual Pagi)": tp,
                        "Stop Loss (SL)": sl,
                        "Risk/Reward Ratio": round(rr, 2),
                        "Setup Score": setup_score
                    })
                    
        if bsjp_data:
            st.dataframe(
                pd.DataFrame(bsjp_data).sort_values(by="Setup Score", ascending=False),
                column_config={
                    "Live Price": st.column_config.NumberColumn("Live Price", format="IDR %d"),
                    "Change %": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                    "Volume Surge (VSR)": st.column_config.NumberColumn("Volume Surge (VSR)", format="%.2f x"),
                    "Entry (Buy Sore)": st.column_config.NumberColumn("Entry Price", format="IDR %d"),
                    "Target (Jual Pagi)": st.column_config.NumberColumn("Target TP", format="IDR %d"),
                    "Stop Loss (SL)": st.column_config.NumberColumn("Stop Loss", format="IDR %d"),
                    "Risk/Reward Ratio": st.column_config.NumberColumn("R/R", format="%.2f x"),
                    "Setup Score": st.column_config.ProgressColumn("Setup Score", min_value=0, max_value=100, format="%d")
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No tickers currently match standard BSJP setups (Positive change > 1%, closing in upper 30% of day's range, R/R >= 1.2x).")
    else:
        st.info("Refresh the live feed to display BSJP setups.")
