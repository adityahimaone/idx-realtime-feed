import streamlit as st
import pandas as pd
from data.fetchers import safe_float


def render_tab3(scored_list):
    """Render Tab 3: General Screener Board + Scalping/Swing/Long-term sub-tables."""
    st.markdown("### 📊 General Screener Board")
    st.caption("Intraday health scores across filtered tickers, plus strategy sub-tables.")

    if not scored_list:
        st.info("Refresh the feed to display screener results.")
        return [], [], []

    scored_df = pd.DataFrame(scored_list)
    scored_df = scored_df.sort_values(by="Intraday Score", ascending=False)

    # ─── Main table ──────────────────────────────────────────────────────────
    cols_main = ["Ticker", "Company Name", "Sector", "Live Price", "Change %",
                 "Vol Spike", "Intraday Score", "Live Signal", "Source Used"]
    st.dataframe(
        scored_df[cols_main],
        column_config={
            "Live Price":     st.column_config.NumberColumn("Live Price", format="IDR %d"),
            "Change %":       st.column_config.NumberColumn("Change %", format="%+.2f%%"),
            "Vol Spike":      st.column_config.NumberColumn("Vol Spike", format="%.2f x"),
            "Intraday Score": st.column_config.ProgressColumn(
                "Intraday Score", format="%d", min_value=0, max_value=100),
            "Live Signal":    st.column_config.TextColumn("Live Signal"),
            "Source Used":    st.column_config.TextColumn("Source Used"),
        },
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")

    # ─── SCALPING TABLE ───────────────────────────────────────────────────────
    st.markdown("#### ⚡ SCALPING TABLE — Fast Money (Intraday)")
    st.caption("High Vol Spike ≥ 2×, Change ≥ +1%, Score ≥ 60. Target +2–3%, SL -1.5%.")

    scalp_rows = []
    for s in scored_list:
        raw   = s["raw_data_obj"]
        hist  = s["hist_row_obj"]
        price = safe_float(s["Live Price"])
        chg   = safe_float(s["Change %"])
        vol_spike = safe_float(s["Vol Spike"])
        score = safe_float(s["Intraday Score"])

        if vol_spike < 2.0 or chg < 1.0 or score < 60 or price <= 0:
            continue

        tp   = round(price * 1.025, 0)
        sl   = round(price * 0.985, 0)
        rr   = round((tp - price) / max(price - sl, 1), 2)
        high = safe_float(raw.get("high", price))
        low  = safe_float(raw.get("low", price))
        rng  = high - low
        pos  = round((price - low) / rng * 100, 1) if rng > 0 else 0.0

        scalp_rows.append({
            "Ticker":    s["Ticker"],
            "Price":     price,
            "Change %":  chg,
            "Vol Spike": vol_spike,
            "Score":     score,
            "Pos%":      pos,
            "TP":        tp,
            "SL":        sl,
            "R/R":       rr,
        })

    if scalp_rows:
        scalp_df = pd.DataFrame(scalp_rows).sort_values("Score", ascending=False)
        st.dataframe(
            scalp_df,
            column_config={
                "Price":     st.column_config.NumberColumn("Price", format="IDR %d"),
                "Change %":  st.column_config.NumberColumn("Chg%", format="%+.2f%%"),
                "Vol Spike": st.column_config.NumberColumn("VSR", format="%.2fx"),
                "Score":     st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "Pos%":      st.column_config.NumberColumn("Range Pos%", format="%.1f%%"),
                "TP":        st.column_config.NumberColumn("TP (+2.5%)", format="IDR %d"),
                "SL":        st.column_config.NumberColumn("SL (-1.5%)", format="IDR %d"),
                "R/R":       st.column_config.NumberColumn("R/R", format="%.2fx"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No scalping candidates pass filter right now.")

    st.markdown("---")

    # ─── SWING TABLE ─────────────────────────────────────────────────────────
    st.markdown("#### 🌊 SWING TABLE — Hold 3–10 Hari")
    st.caption("Near support/MA20, Score ≥ 50, Change -2% to +5%. Target: breakout/resistance level.")

    swing_rows = []
    for s in scored_list:
        raw   = s["raw_data_obj"]
        hist  = s["hist_row_obj"]
        price = safe_float(s["Live Price"])
        chg   = safe_float(s["Change %"])
        score = safe_float(s["Intraday Score"])

        if score < 50 or not (-2.0 <= chg <= 5.0) or price <= 0:
            continue

        ma20    = safe_float(hist.get("MA20", 0))
        support = safe_float(hist.get("Support", 0))
        tp_raw  = safe_float(hist.get("Breakout", 0))
        sl_raw  = safe_float(hist.get("SL_Practical", 0))

        if tp_raw <= price:
            tp_raw = round(price * 1.08, 0)
        if sl_raw <= 0 or sl_raw >= price:
            sl_raw = round(max(ma20 * 0.97, price * 0.93), 0) if ma20 > 0 else round(price * 0.93, 0)

        rr = round((tp_raw - price) / max(price - sl_raw, 1), 2)
        if rr < 1.0:
            continue

        near_support = support > 0 and price <= support * 1.05
        near_ma20    = ma20 > 0 and price <= ma20 * 1.03

        swing_rows.append({
            "Ticker":        s["Ticker"],
            "Company":       s["Company Name"],
            "Price":         price,
            "Change %":      chg,
            "Score":         score,
            "MA20":          ma20,
            "Support":       support,
            "TP (Breakout)": tp_raw,
            "SL":            sl_raw,
            "R/R":           rr,
            "Near Support":  "✅" if near_support else "—",
            "Near MA20":     "✅" if near_ma20 else "—",
        })

    if swing_rows:
        swing_df = pd.DataFrame(swing_rows).sort_values("R/R", ascending=False)
        st.dataframe(
            swing_df,
            column_config={
                "Price":         st.column_config.NumberColumn("Price", format="IDR %d"),
                "Change %":      st.column_config.NumberColumn("Chg%", format="%+.2f%%"),
                "Score":         st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "MA20":          st.column_config.NumberColumn("MA20", format="IDR %d"),
                "Support":       st.column_config.NumberColumn("Support", format="IDR %d"),
                "TP (Breakout)": st.column_config.NumberColumn("TP (Breakout)", format="IDR %d"),
                "SL":            st.column_config.NumberColumn("SL", format="IDR %d"),
                "R/R":           st.column_config.NumberColumn("R/R", format="%.2fx"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No swing candidates pass filter right now.")

    st.markdown("---")

    # ─── LONG TERM TABLE ─────────────────────────────────────────────────────
    st.markdown("#### 🏔️ LONG TERM TABLE — Hold Weeks–Months")
    st.caption("Price > MA50 & MA200, Score ≥ 50, within 25% of 52W High. TP: 52W High.")

    lt_rows = []
    for s in scored_list:
        raw   = s["raw_data_obj"]
        hist  = s["hist_row_obj"]
        price = safe_float(s["Live Price"])
        score = safe_float(s["Intraday Score"])

        if score < 50 or price <= 0:
            continue

        ma50   = safe_float(hist.get("MA50", 0))
        ma200  = safe_float(hist.get("MA200", 0))
        high52 = safe_float(hist.get("52W High", 0))
        rsi    = safe_float(hist.get("RSI14", 0))

        if ma50 <= 0 or ma200 <= 0:
            continue
        if price < ma50 or price < ma200:
            continue
        if high52 > 0 and price < high52 * 0.75:
            continue

        tp = high52 if high52 > price else round(price * 1.20, 0)
        sl = round(ma200 * 0.97, 0)
        rr = round((tp - price) / max(price - sl, 1), 2)

        lt_rows.append({
            "Ticker":   s["Ticker"],
            "Company":  s["Company Name"],
            "Sector":   s["Sector"],
            "Price":    price,
            "MA50":     ma50,
            "MA200":    ma200,
            "52W High": high52,
            "RSI14":    rsi,
            "Score":    score,
            "TP":       tp,
            "SL (MA200-3%)": sl,
            "R/R":      rr,
        })

    if lt_rows:
        lt_df = pd.DataFrame(lt_rows).sort_values("Score", ascending=False)
        st.dataframe(
            lt_df,
            column_config={
                "Price":         st.column_config.NumberColumn("Price", format="IDR %d"),
                "MA50":          st.column_config.NumberColumn("MA50", format="IDR %d"),
                "MA200":         st.column_config.NumberColumn("MA200", format="IDR %d"),
                "52W High":      st.column_config.NumberColumn("52W High", format="IDR %d"),
                "RSI14":         st.column_config.NumberColumn("RSI14", format="%.1f"),
                "Score":         st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                "TP":            st.column_config.NumberColumn("TP (52W High)", format="IDR %d"),
                "SL (MA200-3%)": st.column_config.NumberColumn("SL", format="IDR %d"),
                "R/R":           st.column_config.NumberColumn("R/R", format="%.2fx"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No long-term candidates pass filter right now.")

    return scalp_rows, swing_rows, lt_rows
