import streamlit as st
import pandas as pd
from data.fetchers import safe_float
from data.pre_ara import get_ara_limit, get_ara_price, pre_ara_score, classify_pre_ara


def render_tab9(scored_list):
    """Render Tab 9: Pre-ARA Momentum — Early Buy Signal."""
    st.markdown("### 🚀 Pre-ARA Momentum — Early Buy Signal")
    st.caption(
        "Deteksi saham yang mendekati Auto Rejection Atas (ARA) sebelum hit limit. "
        "IDX ARA tier: <200 = +35%, 200–499 = +25%, 500–1999 = +20%, 2000–4999 = +15%, ≥5000 = +10%."
    )

    if not scored_list:
        st.info("Refresh feed dulu untuk lihat Pre-ARA candidates.")
        return

    rows = []
    for s in scored_list:
        raw  = s["raw_data_obj"]
        hist = s["hist_row_obj"]

        price    = safe_float(s["Live Price"])
        chg      = safe_float(s["Change %"])
        vol_spike = safe_float(s["Vol Spike"])

        if price <= 0:
            continue

        ara_limit_pct = get_ara_limit(price)
        ara_price     = get_ara_price(price)

        # proximity % = how far price is toward ARA limit
        prev_close = safe_float(raw.get("prev_close", 0)) or safe_float(hist.get("ClosePrev", price))
        if prev_close <= 0:
            prev_close = price

        # distance from current price to ARA price
        dist_to_ara_pct = round((ara_price - price) / price * 100, 2)

        # % of ARA limit already consumed
        if prev_close > 0 and chg > 0:
            ara_consumed_pct = round(chg / ara_limit_pct * 100, 1)
        else:
            ara_consumed_pct = 0.0

        frequency = safe_float(raw.get("frequency", 0))
        avg_freq  = safe_float(hist.get("Freq_Avg", 1))
        value     = safe_float(raw.get("value", 0))
        avg_vol   = safe_float(hist.get("Vol_Avg", 1))
        volume    = safe_float(raw.get("volume", 0))

        sig = {
            "price":         price,
            "ara_price":     ara_price,
            "ara_limit_pct": ara_limit_pct,
            "change_pct":    chg,
            "volume":        volume,
            "avg_volume":    avg_vol,
            "frequency":     frequency,
            "avg_frequency": avg_freq,
            "value":         value,
        }
        score  = pre_ara_score(sig)
        label  = classify_pre_ara(score)

        # Only show tickers with meaningful upward move (consumed ≥ 30% of ARA limit)
        if ara_consumed_pct < 30 or chg <= 0:
            continue

        rows.append({
            "Ticker":        s["Ticker"],
            "Company":       s["Company Name"],
            "Sector":        s["Sector"],
            "Price":         price,
            "Change %":      chg,
            "ARA Limit":     ara_limit_pct,
            "ARA Price":     ara_price,
            "Dist to ARA %": dist_to_ara_pct,
            "ARA Used %":    ara_consumed_pct,
            "Vol Spike":     vol_spike,
            "Freq":          int(frequency),
            "Pre-ARA Score": score,
            "Signal":        label,
        })

    if not rows:
        st.info("Tidak ada kandidat Pre-ARA saat ini (ARA consumed < 30% atau harga turun).")
        return

    df = pd.DataFrame(rows).sort_values("Pre-ARA Score", ascending=False)

    # Summary metrics
    prime  = df[df["Signal"] == "⚡ Pre-ARA Watch"]
    momen  = df[df["Signal"] == "🔥 Momentum"]
    c1, c2, c3 = st.columns(3)
    c1.metric("⚡ Pre-ARA Watch", len(prime))
    c2.metric("🔥 Momentum", len(momen))
    c3.metric("Total Candidates", len(df))

    st.dataframe(
        df,
        column_config={
            "Price":         st.column_config.NumberColumn("Price", format="IDR %d"),
            "Change %":      st.column_config.NumberColumn("Change %", format="%+.2f%%"),
            "ARA Limit":     st.column_config.NumberColumn("ARA Limit%", format="+%.0f%%"),
            "ARA Price":     st.column_config.NumberColumn("ARA Price", format="IDR %d"),
            "Dist to ARA %": st.column_config.NumberColumn("Dist to ARA", format="%.2f%%"),
            "ARA Used %":    st.column_config.ProgressColumn(
                "ARA Used %", min_value=0, max_value=100, format="%.1f%%"),
            "Vol Spike":     st.column_config.NumberColumn("VSR", format="%.2fx"),
            "Freq":          st.column_config.NumberColumn("Freq", format="%d"),
            "Pre-ARA Score": st.column_config.ProgressColumn(
                "Pre-ARA Score", min_value=0, max_value=100, format="%.1f"),
            "Signal":        st.column_config.TextColumn("Signal"),
        },
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("📖 Pre-ARA Score legend", expanded=False):
        st.markdown("""
**Score komponen:**
- **Proximity** (35%) — seberapa dekat price ke ARA price
- **Momentum / Change%** (25%) — intraday change pct
- **Volume Surge** (20%) — VSR vs avg
- **Frequency Surge** (15%) — freq transaksi vs avg
- **Value** (5%) — transaction value cap 1B

**Signal Tier:**
- ⚡ Pre-ARA Watch ≥ 80
- 🔥 Momentum ≥ 60
- 👁️ Monitor ≥ 40

**Pre-filter:** ARA consumed ≥ 30% dan harga positif.
        """)
