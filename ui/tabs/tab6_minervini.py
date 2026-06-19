import streamlit as st
import pandas as pd
import yfinance as yf
from data.fetchers import safe_float


@st.cache_data(ttl=86400)
def fetch_long_smas(ticker: str) -> dict:
    """Fetch SMA150, SMA200, 52W Low, 52W High, and 3-Month Ago Price from yfinance (cached for 24h)"""
    try:
        df = yf.Ticker(f"{ticker}.JK").history(period="2y", interval="1d")
        if df.empty or len(df) < 200:
            return {}
        
        lookback_252 = min(len(df), 252)
        lookback_63 = min(len(df), 63)
        
        return {
            "sma150": round(df["Close"].rolling(150).mean().iloc[-1], 2),
            "sma200": round(df["Close"].rolling(200).mean().iloc[-1], 2),
            "low52":  round(df["Low"].iloc[-lookback_252:].min(), 2),
            "high52": round(df["High"].iloc[-lookback_252:].max(), 2),
            "price_3mo_ago": round(df["Close"].iloc[-lookback_63], 2),
        }
    except Exception:
        return {}


@st.cache_data(ttl=86400)
def fetch_ihsg_3mo_return() -> float:
    try:
        df = yf.Ticker("^JKSE").history(period="3mo", interval="1d")
        if df.empty or len(df) < 5:
            return 0.0
        return (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
    except Exception:
        return 0.0


def render_tab6(scored_list_global, scored_list, exclude_filters_minervini, ihsg_info=None):
    """Render Tab 6: Mark Minervini Trend Template with 52W Low and Relative Strength (RS) to IHSG"""
    st.markdown("### 📈 Mark Minervini Trend Template")
    st.caption("Validates tickers against Mark Minervini's Stage 2 Uptrend criteria. Requires at least 8/10 conditions passed.")
    
    minervini_source_list = scored_list_global if exclude_filters_minervini else scored_list
    if minervini_source_list:
        # RS computation: Ticker performance vs IHSG performance over last 3 months
        rs_ihsg = fetch_ihsg_3mo_return()

        minervini_data = []
        for s in minervini_source_list:
            hist_row = s["hist_row_obj"]
            raw_data = s["raw_data_obj"]
            ticker = s["Ticker"]
            
            last = s["Live Price"]
            
            # Use cached yfinance SMAs if available, otherwise fallback to sheet
            cached_vals = fetch_long_smas(ticker)
            
            sma50 = safe_float(hist_row.get("MA50", 0))
            sma200 = cached_vals.get("sma200") or safe_float(hist_row.get("MA200", 0))
            sma150 = cached_vals.get("sma150") or safe_float(hist_row.get("MA150", 0))
            if sma150 <= 0:
                sma150 = round(sma50 * 0.4 + sma200 * 0.6, 2)
                
            high52 = cached_vals.get("high52") or safe_float(hist_row.get("52W High", 0))
            if high52 <= 0:
                high52 = last * 1.10
                
            low52 = cached_vals.get("low52") or safe_float(hist_row.get("52W Low", 0))
            if low52 <= 0:
                low52 = last * 0.70
                
            vol_today = safe_float(raw_data.get("volume", 0))
            vol_avg20 = safe_float(hist_row.get("Vol_Avg", 1))
            if vol_avg20 <= 0:
                vol_avg20 = 1.0

            # RS computation: Ticker performance vs IHSG performance
            price_3mo_ago = cached_vals.get("price_3mo_ago") or (safe_float(hist_row.get("ClosePrev", last)) * 0.90)
            rs_ticker = (last / price_3mo_ago - 1) * 100 if price_3mo_ago > 0 else 0.0
            rs_positive = rs_ticker > rs_ihsg
                
            conds = {
                "Price > SMA50": last > sma50,
                "Price > SMA150": last > sma150,
                "Price > SMA200": last > sma200,
                "SMA50 > SMA150": sma50 > sma150,
                "SMA150 > SMA200": sma150 > sma200,
                "SMA50 > SMA200": sma50 > sma200,
                "Within 25% of 52W High": last >= (high52 * 0.75),
                "Volume > Avg20": vol_today > vol_avg20,
                "Price > 52W Low + 25%": last >= (low52 * 1.25) if low52 > 0 else False,
                "RS vs IHSG positive": rs_positive
            }
            
            score_val = sum(conds.values())
            passed = (score_val >= 8)
            
            minervini_data.append({
                "Ticker": ticker,
                "Company Name": s["Company Name"],
                "Live Price": last,
                "SMA 50": sma50,
                "SMA 150 (Est)": sma150,
                "SMA 200": sma200,
                "52W High": high52,
                "52W Low": low52,
                "Score": f"{score_val}/10",
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
                    "52W Low": st.column_config.NumberColumn("52W Low", format="IDR %d"),
                    "Score": st.column_config.TextColumn("Condition Score"),
                    "Passed Template": st.column_config.TextColumn("Minervini Setup"),
                },
                use_container_width=True,
                hide_index=True
            )
            return minervini_data
        else:
            st.info("No tickers evaluated for Mark Minervini Trend Template.")
    else:
        st.info("Refresh the live feed to calculate Mark Minervini trend template checklists.")
    return []
