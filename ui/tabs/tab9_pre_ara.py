import streamlit as st
import pandas as pd
from data.fetchers import safe_float
from data.pre_ara import (
    get_ara_limit,
    get_ara_price,
    ara_proximity_score,
    ara_distance,
    pre_ara_score,
    classify_pre_ara,
    detect_ara_streak,
    PRE_ARA_ENTRY,
)
from data.scoring import get_tick_size


def render_tab9(scored_list):
    """Render Tab 9: Pre-ARA Momentum — Early Buy Signal."""
    st.markdown("### 🚨 PRE-ARA MOMENTUM — Early Buy Signal")
    st.caption(
        "Deteksi saham mendekati Auto Rejection Atas (ARA). "
        "IDX 2024: <200 = +35%, 200–4999 = +25%, ≥5000 = +20%. ARB −7% semua tier."
    )

    if not scored_list:
        st.info("Refresh feed dulu untuk lihat Pre-ARA candidates.")
        return []

    rows = []
    for s in scored_list:
        raw = s["raw_data_obj"]
        hist = s["hist_row_obj"]

        price = safe_float(s["Live Price"])
        chg = safe_float(s["Change %"])
        vol_spike = safe_float(s["Vol Spike"])

        if price <= 0:
            continue

        prev_close = safe_float(raw.get("prev_close", 0)) or safe_float(hist.get("ClosePrev", price))
        if prev_close <= 0:
            prev_close = price

        ara_limit_pct = get_ara_limit(prev_close)
        ara_price = get_ara_price(prev_close)

        # Proximity: progress from prev_close toward ARA
        proximity = ara_proximity_score(price, prev_close, ara_price)
        dist_pct = ara_distance(price, ara_price)

        # Pre-filter immediately to optimize performance and prevent slow API queries
        if proximity < 40:
            continue

        # VSR: vol_today / vol_avg
        volume = safe_float(raw.get("volume", 0))
        avg_vol = safe_float(hist.get("Vol_Avg", 1))
        vsr = volume / avg_vol if avg_vol > 0 else 1.0

        # CPR: close position in range
        high = safe_float(raw.get("high", price))
        low = safe_float(raw.get("low", price))
        cpr_val = round((price - low) / (high - low) * 100, 1) if high > low else 50.0

        # ARA Streak (cached via session_state or per-call)
        streak_info = detect_ara_streak(s["Ticker"], days=5)
        streak = streak_info["streak"]
        is_riding = streak_info["is_riding"]

        frequency = safe_float(raw.get("frequency", 0))
        avg_freq = safe_float(hist.get("Freq_Avg", 1))
        value = safe_float(raw.get("value", 0))

        sig = {
            "price": price,
            "prev_close": prev_close,
            "ara_price": ara_price,
            "vsr": vsr,
            "streak": streak,
            "accelerating": chg > 0,  # simplified acceleration proxy
            "cpr": cpr_val,
        }
        score = pre_ara_score(sig)
        label = classify_pre_ara(score, proximity)

        rows.append({
            "Ticker": s["Ticker"],
            "Price": price,
            "PrevClose": prev_close,
            "ΔP%": chg,
            "ARA %": ara_limit_pct,
            "ARA Price": ara_price,
            "Proximity": proximity,
            "Dist%": dist_pct,
            "VSR": round(vsr, 2),
            "Freq": int(frequency),
            "Streak": streak,
            "CPR": cpr_val,
            "Pre-ARA Score": score,
            "Signal": label,
        })

    if not rows:
        st.info("Tidak ada kandidat Pre-ARA saat ini (proximity < 40% atau vsr < 3).")
        return []

    df = pd.DataFrame(rows).sort_values("Pre-ARA Score", ascending=False)

    # Summary metrics
    at_ara = df[df["Signal"] == "🚨 AT ARA"]
    imminent = df[df["Signal"] == "🔴 Imminent ARA"]
    entry = df[df["Signal"] == "🟠 Pre-ARA Entry"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🚨 AT ARA", len(at_ara))
    c2.metric("🔴 Imminent", len(imminent))
    c3.metric("🟠 Entry", len(entry))
    c4.metric("Total", len(df))

    st.dataframe(
        df,
        column_config={
            "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
            "PrevClose": st.column_config.NumberColumn("PrevClose", format="IDR %d"),
            "ΔP%": st.column_config.NumberColumn("Chg%", format="%+.2f%%"),
            "ARA %": st.column_config.NumberColumn("ARA%", format="+%.0f%%"),
            "ARA Price": st.column_config.NumberColumn("ARA Price", format="IDR %d"),
            "Proximity": st.column_config.ProgressColumn(
                "Proximity%", min_value=0, max_value=100, format="%.1f%%"),
            "Dist%": st.column_config.NumberColumn("Dist to ARA%", format="%.2f%%"),
            "VSR": st.column_config.NumberColumn("VSR", format="%.2fx"),
            "Freq": st.column_config.NumberColumn("Freq", format="%d"),
            "Streak": st.column_config.NumberColumn("ARA Streak", format="%d day(s)"),
            "CPR": st.column_config.NumberColumn("CPR", format="%.1f%%"),
            "Pre-ARA Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.1f"),
            "Signal": st.column_config.TextColumn("Signal"),
        },
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("📖 Pre-ARA Score & Entry Strategies", expanded=False):
        st.markdown("""
**Score Formula (Plan v2):**
| Komponen | Bobot | Keterangan |
|---|---|---|
| Proximity | 30% | Progress dari PrevClose ke ARA |
| VSR | 25% | Volume Surge, cap 15x |
| ARA Streak | 20% | Hari berturut-turut ARA, cap 5 |
| Momentum Accel | 15% | Momentum naik (1.0), turun (0.3) |
| CPR | 10% | Close ≥ 50% range (hanya di atas 50) |

**Entry Strategies:**

| Mode | Proximity | Min VSR | Min Streak | Keterangan |
|---|---|---|---|---|
| 🔥 Aggressive | 50–70% | 5x | 0 | High risk, SL -3% |
| ⚡ Moderate | 70–90% | 4x | 1 | Terkonfirmasi, SL -2% |
| 🛡️ Conservative | 95–100% | 3x | 2 | Riding, SL = prev close |
        """)

    return rows
