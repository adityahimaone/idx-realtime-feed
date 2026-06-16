import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from data.elliott_wave import (
    find_zigzag_pivots,
    detect_impulse_waves,
    detect_corrective_waves,
    elliott_score_for_ticker,
)


def _build_pivot_chart(result: dict) -> go.Figure:
    """
    Build candlestick/line chart with pivot markers and Fibonacci levels.
    """
    fig = go.Figure()

    dates  = result.get("dates", [])
    closes = result.get("closes", [])
    if not dates or not closes:
        return fig

    # Price line
    fig.add_trace(go.Scatter(
        x=dates, y=closes, mode="lines",
        name="Close", line=dict(color="#888", width=1.5),
    ))

    # Pivot markers
    pivots = result.get("pivots", [])
    for pv in pivots:
        color = "#1D9E75" if pv["type"] == "low" else "#D85A30"
        fig.add_trace(go.Scatter(
            x=[dates[min(pv["idx"], len(dates) - 1)]],
            y=[pv["price"]],
            mode="markers+text",
            marker=dict(color=color, size=9, symbol="circle"),
            text=[pv["type"][0].upper()],
            textposition="top center",
            textfont=dict(size=10, color=color),
            showlegend=False,
            hovertemplate=f"{pv['type'].upper()}: {pv['price']:,.0f}<extra></extra>",
        ))

    # Fibonacci retracement levels
    fibs = result.get("fib", {})
    for label, price in fibs.items():
        if not label.startswith("ret_"):
            continue
        fig.add_hline(
            y=price, line_dash="dot", line_color="#4A90D9", line_width=0.8,
            annotation_text=f"  {label} {price:,.0f}",
            annotation_position="right",
            annotation_font_size=9,
        )

    fig.update_layout(
        height=480,
        showlegend=False,
        margin=dict(l=10, r=120, t=30, b=10),
        xaxis_rangeslider_visible=False,
        hovermode="x",
    )
    return fig


def render_tab10(scored_list):
    """Render Tab 10: Elliott Wave — 5-Wave Impulse + Fibonacci + A-B-C."""
    st.markdown("### 🌊 Elliott Wave — Impulse + Fibonacci Targets")
    st.caption(
        "Zigzag pivot detection (2% default). 5-wave impulse dengan rule: "
        "W2 < 100% W1, W3 tidak terpendek, W4 tidak overlap W1. "
        "Plus Fibonacci levels, wave targets, dan A-B-C correction detection."
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

    # Deviation slider for zigzag sensitivity
    deviation = st.slider(
        "Zigzag deviation (%)", min_value=1.0, max_value=5.0, value=2.0, step=0.5,
        help="Minimum % move to confirm a new swing pivot. Lower = more pivots detected."
    )

    if st.button("🔍 Detect Elliott Wave", use_container_width=False):
        rows = []
        detailed_results = {}  # ticker -> full result for drill-down
        progress = st.progress(0)

        for i, ticker in enumerate(tickers):
            progress.progress((i + 1) / len(tickers))
            try:
                ticker_yf = f"{ticker}.JK"
                df = yf.Ticker(ticker_yf).history(period="3mo", interval="1d")
                if df is None or df.empty or len(df) < 20:
                    rows.append({
                        "Ticker": ticker,
                        "Status": "⚠️ No data",
                        "Pivots": 0,
                        "Waves": 0,
                        "Detail": "Insufficient data (need ≥ 20 days)",
                    })
                    continue

                result = elliott_score_for_ticker(df)
                # Re-run zigzag with custom deviation
                prices = df["Close"].tolist()
                result["pivots"] = find_zigzag_pivots(prices, deviation_pct=deviation)
                result["waves"] = detect_impulse_waves(result["pivots"])
                result["corrections"] = detect_corrective_waves(result["pivots"])
                valid_waves = [w for w in result["waves"] if w["valid"]]
                result["valid_count"] = len(valid_waves)

                if result["waves"]:
                    w = result["waves"][0]  # most recent match
                    rows.append({
                        "Ticker":     ticker,
                        "Status":     "✅ Valid" if w["valid"] else f"⚠️ {len(w['violations'])} viol",
                        "Pivots":     len(result["pivots"]),
                        "Waves":      len(result["waves"]),
                        "Valid":      len(valid_waves),
                        "W3/W1":      w["w3_ratio"],
                        "Last Price": df["Close"].iloc[-1],
                    })
                    detailed_results[ticker] = {**result, "dates": [str(d)[:10] for d in df.index], "closes": prices}
                else:
                    rows.append({
                        "Ticker": ticker,
                        "Status": "❌ No impulse",
                        "Pivots": len(result["pivots"]),
                        "Waves":  0,
                        "Valid":  0,
                        "Detail": "Zigzag pivots found but no valid 5-wave pattern",
                    })

            except Exception as exc:
                rows.append({
                    "Ticker": ticker,
                    "Status": "❌ Error",
                    "Pivots": 0,
                    "Waves":  0,
                    "Detail": str(exc)[:60],
                })

        progress.empty()

        if rows:
            df_res = pd.DataFrame(rows)
            st.dataframe(
                df_res,
                column_config={
                    "Last Price": st.column_config.NumberColumn("Last", format="IDR %d"),
                    "W3/W1":      st.column_config.NumberColumn("W3/W1 ratio", format="%.2f"),
                    "Pivots":     st.column_config.NumberColumn("Pivots", format="%d"),
                    "Waves":      st.column_config.NumberColumn("Waves", format="%d"),
                    "Valid":      st.column_config.NumberColumn("Valid", format="%d"),
                },
                use_container_width=True,
                hide_index=True,
            )

        # Per-ticker drill-down
        if detailed_results:
            st.markdown("---")
            st.markdown("#### 🔬 Detailed Wave Analysis")

            for ticker, result in detailed_results.items():
                with st.expander(f"📈 {ticker} — {result['valid_count']} valid impulse(s), {len(result['pivots'])} pivots", expanded=False):
                    # Chart
                    fig = _build_pivot_chart(result)
                    st.plotly_chart(fig, use_container_width=True)

                    col_a, col_b = st.columns(2)

                    with col_a:
                        st.markdown("**🌊 Wave Labels**")
                        if result["waves"]:
                            wave_rows = [{
                                "Wave":      f"W{i + 1}",
                                "Start":     f"{w[f'w{i + 1}_start' if i == 0 else f'w{i}_end']:,.0f}",
                                "End":       f"{w[f'w{i + 1}_end']:,.0f}",
                                "Size":      f"{w[f'w{i + 1}']:,.0f}",
                                "Valid":     "✓" if w["valid"] else "❌",
                            } for i, w in enumerate(result["waves"][:5])]
                            st.dataframe(pd.DataFrame(wave_rows), use_container_width=True, hide_index=True)

                    with col_b:
                        st.markdown("**📐 Fibonacci Levels**")
                        fibs = result.get("fib", {})
                        if fibs:
                            fib_df = pd.DataFrame([
                                {"Level": label, "Price": f"{price:,.0f}"}
                                for label, price in fibs.items()
                                if label.startswith("ret_")
                            ])
                            st.dataframe(fib_df, use_container_width=True, hide_index=True)
                        else:
                            st.caption("No fib levels computed.")

                    col_c, col_d = st.columns(2)

                    with col_c:
                        st.markdown("**🎯 Wave Targets (from W1)**")
                        targets = result.get("targets", {})
                        if targets:
                            for k, v in targets.items():
                                if isinstance(v, (int, float)):
                                    st.write(f"  **{k}**: {v:,.0f}")
                                else:
                                    st.caption(f"  _{k}_: {v}")
                        else:
                            st.caption("No valid W1 reference for target projection.")

                    with col_d:
                        st.markdown("**📍 Current Position**")
                        pos = result.get("position", {})
                        if pos:
                            st.info(
                                f"**Position:** {pos.get('position', '?')}\n\n"
                                f"**Next label:** {pos.get('next_label', '?')}\n\n"
                                f"**Next target:** {pos.get('next_target', '?')}"
                            )
                        else:
                            st.caption("Position undetermined.")

                    # Corrective A-B-C if any
                    corrections = result.get("corrections", [])
                    if corrections:
                        st.markdown("**🔄 A-B-C Correction Detected**")
                        corr_df = pd.DataFrame([{
                            "Type":         c["type"],
                            "A size":       c["wa"],
                            "B retrace %":  c["b_retrace_pct"],
                            "C size":       c["wc"],
                            "C ≈ A":        "✓" if c["c_eq_a"] else "—",
                        } for c in corrections])
                        st.dataframe(corr_df, use_container_width=True, hide_index=True)

    with st.expander("📖 Elliott Wave Rules & Methodology", expanded=False):
        st.markdown("""
**Impulse (5-wave) rules:**
- W2 retracement **tidak boleh** ≥ 100% W1
- W3 **tidak boleh** terpendek di antara W1, W3, W5
- W4 **tidak boleh** overlap dengan territory Wave 1

**Corrective (A-B-C):**
- 3-wave counter-trend: A → B (retrace < 100% A) → C (≥ 0.618 × A)
- Equal A=C adalah pola paling umum (0.618–1.0)

**Fibonacci targets (anchored to W1):**
- W2 support: 0.382–0.618 × W1
- W3 normal: 1.618 × W1 (extended: 2.618 ×)
- W5 equal: W3 peak + W1 size

**Limitasi scanner ini:**
- Zigzag deviation configurable (1–5%) — lower = more sensitive
- Daily candle, 3-month window — lebih cocok untuk swing
- yfinance IDX feed bisa delay / rate limit
        """)
