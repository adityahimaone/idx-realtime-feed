import streamlit as st
import pandas as pd
import yfinance as yf
from data.elliott_wave import find_zigzag_pivots, detect_impulse_waves


def render_tab10(scored_list):
    """Render Tab 10: Elliott Wave 5-wave impulse detection."""
    st.markdown("### 🌊 Elliott Wave — 5-Wave Impulse Scanner")
    st.caption(
        "Zigzag pivot detection (2% deviation). 5-wave impulse dengan rule: "
        "W2 < 100% W1, W3 tidak terpendek, W4 tidak overlap W1. "
        "Data dari yfinance 60-hari daily."
    )

    if not scored_list:
        st.info("Refresh feed untuk lihat Elliott Wave candidates.")
        return

    ticker_input = st.text_input(
        "Ticker symbols (comma-separated, max 5)",
        value="BBCA,TLKM,BMRI,ASII,BBRI",
        help="Batasi max 5 ticker biar gak hit yfinance rate limit.",
    ).upper().strip()

    if not ticker_input:
        return

    tickers = [t.strip() for t in ticker_input.split(",") if t.strip()][:5]

    if st.button("🔍 Detect Elliott Wave", use_container_width=False):
        rows = []
        progress = st.progress(0)
        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            try:
                ticker_yf = f"{ticker}.JK"
                df = yf.Ticker(ticker_yf).history(period="3mo", interval="1d")
                if df is None or df.empty or len(df) < 20:
                    rows.append({
                        "Ticker":   ticker,
                        "Status":   "⚠️ No data",
                        "Waves":    0,
                        "Detail":   "Insufficient data (need ≥ 20 days)",
                    })
                    continue

                prices = df["Close"].tolist()
                pivots = find_zigzag_pivots(prices, deviation_pct=2.0)
                waves  = detect_impulse_waves(pivots)

                if waves:
                    w = waves[0]
                    rows.append({
                        "Ticker":   ticker,
                        "Status":   "✅ Impulse Detected",
                        "Pivots":   len(pivots),
                        "Waves":    len(waves),
                        "W1":       w["w1"],
                        "W2":       w["w2"],
                        "W3":       w["w3"],
                        "W4":       w["w4"],
                        "W5":       w["w5"],
                    })
                else:
                    rows.append({
                        "Ticker":   ticker,
                        "Status":   "❌ No impulse",
                        "Pivots":   len(pivots),
                        "Waves":    0,
                        "Detail":   "Zigzag pivots found but no valid 5-wave pattern",
                    })
            except Exception as exc:
                rows.append({
                    "Ticker":   ticker,
                    "Status":   "❌ Error",
                    "Waves":    0,
                    "Detail":   str(exc)[:60],
                })

        progress.empty()

        if rows:
            df_res = pd.DataFrame(rows)
            st.dataframe(
                df_res,
                column_config={
                    "W1": st.column_config.NumberColumn("W1", format="%.2f"),
                    "W2": st.column_config.NumberColumn("W2", format="%.2f"),
                    "W3": st.column_config.NumberColumn("W3", format="%.2f"),
                    "W4": st.column_config.NumberColumn("W4", format="%.2f"),
                    "W5": st.column_config.NumberColumn("W5", format="%.2f"),
                },
                use_container_width=True,
                hide_index=True,
            )

    with st.expander("📖 Elliott Wave Rules (Quick Ref)", expanded=False):
        st.markdown("""
**Impulse (5-wave) rules:**
- W2 retracement **tidak boleh** ≥ 100% W1
- W3 **tidak boleh** terpendek di antara W1, W3, W5
- W4 **tidak boleh** overlap dengan territory W1

**Corrective (A-B-C):** pattern 3-wave counter-trend

**Limitasi scanner ini:**
- Zigzag deviation 2% — bisa miss smaller swings
- Hanya 5-wave impulse — belum detect corrective A-B-C
- Daily candle, 3-month window — lebih cocok untuk swing
- yfinance IDX feed bisa delay / rate limit
        """)
