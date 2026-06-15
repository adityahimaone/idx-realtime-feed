"""
Custom CSS for the IDX Intraday Screener UI.
"""
import streamlit as st


def inject_css():
    st.markdown(
        """
<style>
/* ---- Global Layout ---- */
.main .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 95%; }
h1, h2, h3 { font-family: 'Inter', sans-serif; font-weight: 700; letter-spacing: -0.02em; }
.stButton > button { font-weight: 600; border-radius: 8px; }
.stDataFrame { border-radius: 8px; overflow: hidden; }

/* ---- Custom scrollbar ---- */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #0F1419; }
::-webkit-scrollbar-thumb { background: #2D3748; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #4A5568; }

/* ---- Watchlist/Portfolio card-style containers ---- */
div[data-testid="stMetricValue"] { font-size: 1.4rem; }
</style>
""",
        unsafe_allow_html=True,
    )
