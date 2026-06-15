import streamlit as st
import pandas as pd
from data.fetchers import safe_float
from data.scoring import trending_score, trend_tier

def render_tab4(ticker_df, scored_list):
    """Render Tab 4: Trending Stocks — Self-Calculated Composite Score."""
    st.markdown("### 🔥 Trending Stocks")
    st.caption("Self-calculated Trending Score (VSR 35%, Freq 25%, ΔP% 20%, Val 15%, NetForeign 10%).")

    if not scored_list:
        st.info("Refresh feed to see trending scores.")
        return

    # Calculate trends from scored_list
    processed_trending = []
    for s in scored_list:
        data = s["raw_data_obj"]
        hist_row = s["hist_row_obj"]
        
        # Formula inputs
        vsr = safe_float(data.get("volume", 0)) / max(safe_float(hist_row.get("Vol_Avg", 1)), 1.0)
        freq_today = safe_float(data.get("frequency", 0))
        freq_avg = safe_float(hist_row.get("Freq_Avg", 1))
        freq_surge = (freq_today / freq_avg) if freq_avg > 0 else 0
        
        change_pct = s["Change %"]
        
        val_today = safe_float(data.get("value", 0))
        val_avg = safe_float(hist_row.get("Val_Avg", 1))
        val_surge = (val_today / val_avg) if val_avg > 0 else 0
        
        net_foreign = safe_float(data.get("foreign_buy", 0)) - safe_float(data.get("foreign_sell", 0))
        
        sig = {
            "vsr": vsr,
            "freq_surge": freq_surge,
            "change_pct": change_pct,
            "val_surge": val_surge,
            "net_foreign": net_foreign,
            "freq": freq_today,
            "value_rp": val_today
        }
        
        score = trending_score(sig)
        if score > 0:
            processed_trending.append({
                "Ticker": s["Ticker"],
                "Trending Score": score,
                "Tier": trend_tier(score),
                "Price": s["Live Price"],
                "Change %": change_pct,
                "VSR": vsr,
                "Value": val_today
            })
            
    if not processed_trending:
        st.info("No tickers pass trending pre-filter.")
        return

    df = pd.DataFrame(processed_trending).sort_values("Trending Score", ascending=False)
    st.dataframe(
        df,
        column_config={
            "Trending Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.1f"),
            "Value": st.column_config.NumberColumn("Value", format="Rp %d"),
            "Change %": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
        },
        use_container_width=True, hide_index=True
    )
