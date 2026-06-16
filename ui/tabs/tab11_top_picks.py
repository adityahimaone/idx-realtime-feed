import streamlit as st
import pandas as pd
from data.mega_score import compute_mega_score

HORIZON_LABEL = {"scalping": "⚡ Scalping/Intraday",
                  "swing_bsjp": "🌊 Swing/BSJP",
                  "long_term": "🏔️ Long Term"}


def render_tab11(scored_list, bsjp_data, minervini_data, pre_ara_rows,
                  trending_rows, news_sentiment_rows):
    st.markdown("### 🏆 Top Picks — Composite Mega Score")
    st.caption("Cross-reference semua sinyal jadi satu ranking per horizon.")

    horizon = st.radio("Horizon", list(HORIZON_LABEL.keys()),
                        horizontal=True, format_func=lambda h: HORIZON_LABEL[h])

    from data.fetchers import safe_float
    lookup_bsjp   = {r["Ticker"]: safe_float(r["Setup Score"]) for r in bsjp_data}
    lookup_min    = {r["Ticker"]: (100.0 if "PASSED" in r["Passed Template"] else safe_float(r["score_int"]) / 8 * 100)
                      for r in minervini_data}
    lookup_preara = {r["Ticker"]: safe_float(r["Pre-ARA Score"]) for r in pre_ara_rows}
    lookup_trend  = {r["Ticker"]: safe_float(r["Trending Score"]) for r in trending_rows}
    lookup_news   = {r["Ticker"]: safe_float(r.get("Combined Score", 0)) + 50.0 for r in news_sentiment_rows}

    rows = []
    for s in scored_list:
        t = s["Ticker"]
        signals = {
            "intraday_score": safe_float(s["Intraday Score"]),
            "hist_score": safe_float(s["hist_row_obj"].get("Score v2", 50)),
            "bsjp_score": safe_float(lookup_bsjp.get(t, 50)),
            "minervini_score": safe_float(lookup_min.get(t, 50)),
            "pre_ara_score": safe_float(lookup_preara.get(t, 50)),
            "trending_score": safe_float(lookup_trend.get(t, 50)),
            "news_sentiment_score": safe_float(lookup_news.get(t, 50)),
            # orderbook_score & macro_score baru terisi kalau sudah ada Deep Analysis run
        }
        mega = compute_mega_score(signals, horizon)
        rows.append({"Ticker": t, "Company": s["Company Name"],
                      "Mega Score": mega["score"], "Tier": mega["tier"], **mega["breakdown"]})

    if rows:
        df = pd.DataFrame(rows).sort_values("Mega Score", ascending=False)
        st.dataframe(df, use_container_width=True, hide_index=True,
                      column_config={"Mega Score": st.column_config.ProgressColumn(
                          "Mega Score", min_value=0, max_value=100, format="%.1f")})
    else:
        st.info("Refresh feed & jalankan tab terkait dulu untuk mengisi data.")
