import streamlit as st
import pandas as pd
from data.fetchers import safe_float
from data.scoring import trending_score, trend_tier
from curl_cffi import requests as requests_cf


@st.cache_data(ttl=300)
def fetch_idx_ranking(ranking_type: str, limit: int = 7) -> list[dict]:
    """Fetch official rankings from IDX.

    ranking_type: 'GetTopGainer', 'GetTopFrequent', 'GetTopVolume', 'GetTopValue'
    """
    url = f"https://www.idx.co.id/primary/Home/{ranking_type}?resultCount={limit}"
    try:
        r = requests_cf.get(url, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


def render_tab4(ticker_df, scored_list):
    """Render Tab 4: Trending Stocks (Stockbit Methodology + Official IDX Leaderboards)."""
    st.markdown("### 🔥 Trending Stocks & Market Leaders")
    st.caption("Custom social-volume momentum trends alongside official IDX real-time exchange rankings.")
    
    tab_sb, tab_idx = st.tabs(["🔥 Stockbit Methodology", "🏛️ Official IDX Rankings"])
    
    processed_trending = []
    
    with tab_sb:
        st.markdown("#### Stockbit Methodology Reconstruction")
        st.caption(
            "Weights: VSR 40%, FreqSurge 25%, ΔP% 20%, NFR 15%. "
            "NFR = NetForeign/Vol × 100. Tier: ≥65 🔥 Hot, ≥45 ⚡ Rising, ≥25 👀 Watch."
        )

        if not scored_list:
            st.info("Refresh feed to see trending scores.")
        else:
            # Calculate trends from scored_list
            for s in scored_list:
                data = s["raw_data_obj"]
                hist_row = s["hist_row_obj"]

                # Formula inputs
                vol_today = safe_float(data.get("volume", 0))
                vol_avg = max(safe_float(hist_row.get("Vol_Avg", 1)), 1.0)
                vsr = vol_today / vol_avg

                freq_today = safe_float(data.get("frequency", 0))
                freq_avg = safe_float(hist_row.get("Freq_Avg", 1))
                freq_surge = (freq_today / freq_avg) if freq_avg > 0 else 0

                change_pct = s["Change %"]

                val_today = safe_float(data.get("value", 0))
                val_avg = safe_float(hist_row.get("Val_Avg", 1))
                val_surge = (val_today / val_avg) if val_avg > 0 else 0

                foreign_buy = safe_float(data.get("foreign_buy", 0))
                foreign_sell = safe_float(data.get("foreign_sell", 0))
                net_foreign = foreign_buy - foreign_sell

                # NFR% = Net Foreign / Volume * 100
                nfr = (net_foreign / vol_today * 100) if vol_today > 0 else 0.0

                sig = {
                    "vsr": vsr,
                    "freq_surge": freq_surge,
                    "change_pct": change_pct,
                    "val_surge": val_surge,
                    "net_foreign": net_foreign,
                    "freq": freq_today,
                    "value_rp": val_today,
                    "volume_total": vol_today,
                }

                score = trending_score(sig)
                if score > 0:
                    processed_trending.append({
                        "Ticker": s["Ticker"],
                        "Trending Score": score,
                        "Tier": trend_tier(score),
                        "Price": s["Live Price"],
                        "Change %": change_pct,
                        "VSR": round(vsr, 2),
                        "Freq": int(freq_today),
                        "NFR %": round(nfr, 2),
                        "Value (Rp M)": round(val_today / 1_000_000, 1),
                    })

            if not processed_trending:
                st.info("No tickers pass trending pre-filter (VSR≥1.2, |ΔP%|≥0.3%, Freq≥50, Value≥25jt).")
            else:
                df = pd.DataFrame(processed_trending).sort_values("Trending Score", ascending=False)

                st.dataframe(
                    df,
                    column_config={
                        "Trending Score": st.column_config.ProgressColumn(
                            "Score", min_value=0, max_value=100, format="%.1f"),
                        "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                        "Change %": st.column_config.NumberColumn("Chg%", format="%+.2f%%"),
                        "VSR": st.column_config.NumberColumn("VSR", format="%.2fx"),
                        "Freq": st.column_config.NumberColumn("Freq", format="%d"),
                        "NFR %": st.column_config.NumberColumn("NFR%", format="%+.2f%%"),
                        "Value (Rp M)": st.column_config.NumberColumn("Value (Rp M)", format="%.0f"),
                        "Tier": st.column_config.TextColumn("Tier"),
                    },
                    use_container_width=True, hide_index=True
                )

                # Summary metrics row
                hot = df[df["Tier"] == "Strong Trend 🔥"]
                rising = df[df["Tier"] == "Radar ⚡"]
                watch = df[df["Tier"] == "Watchlist 👁️"]
                c1, c2, c3 = st.columns(3)
                c1.metric("🔥 Strong Trend", len(hot))
                c2.metric("⚡ Radar", len(rising))
                c3.metric("👁️ Watchlist", len(watch))

                with st.expander("📖 Score Formula (Stockbit Reconstruction)", expanded=False):
                    st.markdown("""
**Components & Weights:**
- **VSR** (40%) — Volume Surge Ratio, cap at 10x
- **FreqSurge** (25%) — Frequency Surge, cap at 10x (proxy for social activity)
- **ΔP%** (20%) — Price momentum, cap at ±10%
- **NFR** (15%) — Net Foreign Ratio (positive only), cap at 20%

**Pre-filter:** VSR ≥ 1.2, |ΔP%| ≥ 0.3%, Frequency ≥ 50, Value ≥ Rp 25jt

**Tiers:** ≥65 🔥 Hot, ≥45 ⚡ Rising, ≥25 👀 Watch
                    """)

    with tab_idx:
        st.markdown("#### Official IDX Real-Time Leaderboards")
        st.caption("Live tables fetched directly from the Indonesia Stock Exchange (IDX) official API.")
        
        idx_gainer_tab, idx_freq_tab, idx_vol_tab, idx_val_tab = st.tabs([
            "📈 Top Gainers", 
            "🔄 Top Frequent", 
            "📊 Top Volume", 
            "💰 Top Value"
        ])
        
        with idx_gainer_tab:
            st.markdown("##### 📈 Top 7 Gainers")
            with st.spinner("Fetching Top Gainers..."):
                gainers = fetch_idx_ranking("GetTopGainer")
            if gainers:
                gdf = pd.DataFrame(gainers)
                st.dataframe(
                    gdf[["Code", "Price", "Change", "Percent", "Volume", "Value", "Frequency"]],
                    column_config={
                        "Code": st.column_config.TextColumn("Code"),
                        "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                        "Change": st.column_config.NumberColumn("Change", format="%+d"),
                        "Percent": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                        "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                        "Value": st.column_config.NumberColumn("Value (Rp)", format="IDR %d"),
                        "Frequency": st.column_config.NumberColumn("Freq", format="%d"),
                    },
                    use_container_width=True, hide_index=True
                )
            else:
                st.info("No data fetched from IDX Top Gainer API.")

        with idx_freq_tab:
            st.markdown("##### 🔄 Top 7 Most Frequent")
            with st.spinner("Fetching Top Frequent..."):
                freqs = fetch_idx_ranking("GetTopFrequent")
            if freqs:
                fdf = pd.DataFrame(freqs)
                st.dataframe(
                    fdf[["Code", "Price", "Change", "Percent", "Volume", "Value", "Frequency"]],
                    column_config={
                        "Code": st.column_config.TextColumn("Code"),
                        "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                        "Change": st.column_config.NumberColumn("Change", format="%+d"),
                        "Percent": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                        "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                        "Value": st.column_config.NumberColumn("Value (Rp)", format="IDR %d"),
                        "Frequency": st.column_config.NumberColumn("Freq", format="%d"),
                    },
                    use_container_width=True, hide_index=True
                )
            else:
                st.info("No data fetched from IDX Top Frequent API.")

        with idx_vol_tab:
            st.markdown("##### 📊 Top 7 Volume")
            with st.spinner("Fetching Top Volume..."):
                vols = fetch_idx_ranking("GetTopVolume")
            if vols:
                vdf = pd.DataFrame(vols)
                st.dataframe(
                    vdf[["Code", "Price", "Change", "Percent", "Volume", "Value", "Frequency"]],
                    column_config={
                        "Code": st.column_config.TextColumn("Code"),
                        "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                        "Change": st.column_config.NumberColumn("Change", format="%+d"),
                        "Percent": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                        "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                        "Value": st.column_config.NumberColumn("Value (Rp)", format="IDR %d"),
                        "Frequency": st.column_config.NumberColumn("Freq", format="%d"),
                    },
                    use_container_width=True, hide_index=True
                )
            else:
                st.info("No data fetched from IDX Top Volume API.")

        with idx_val_tab:
            st.markdown("##### 💰 Top 7 Value")
            with st.spinner("Fetching Top Value..."):
                vals = fetch_idx_ranking("GetTopValue")
            if vals:
                vadf = pd.DataFrame(vals)
                st.dataframe(
                    vadf[["Code", "Price", "Change", "Percent", "Volume", "Value", "Frequency"]],
                    column_config={
                        "Code": st.column_config.TextColumn("Code"),
                        "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                        "Change": st.column_config.NumberColumn("Change", format="%+d"),
                        "Percent": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                        "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                        "Value": st.column_config.NumberColumn("Value (Rp)", format="IDR %d"),
                        "Frequency": st.column_config.NumberColumn("Freq", format="%d"),
                    },
                    use_container_width=True, hide_index=True
                )
            else:
                st.info("No data fetched from IDX Top Value API.")

    return processed_trending
