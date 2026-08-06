"""
Custom CSS for StockPick IDX — design-engineering pass.

Motion rules (emil-design-eng): fast, interruptible transitions on exact
properties (never `all`), press feedback on buttons, hover only on precise
pointers, and a hard stop for anyone who prefers reduced motion.
"""
import streamlit as st


def inject_css():
    st.markdown(
        """
<style>
/* ---- Design tokens ---- */
:root {
    --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
    --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
    --dur-fast: 150ms;
    --dur-base: 200ms;
    --dur-slow: 300ms;
    --radius-btn: 10px;
    --radius-card: 12px;
}

/* ---- Global layout ---- */
.main .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 95%; }
h1, h2, h3 { font-family: 'Inter', sans-serif; font-weight: 700; letter-spacing: -0.02em; }
.stDataFrame { border-radius: var(--radius-card); overflow: hidden; }

/* ---- Buttons: exact-property transitions + crisp press feedback ---- */
.stButton > button {
    font-weight: 600;
    border-radius: var(--radius-btn);
    transition:
        transform var(--dur-fast) var(--ease-out),
        background-color var(--dur-base) var(--ease-out),
        border-color var(--dur-base) var(--ease-out),
        box-shadow var(--dur-base) var(--ease-out),
        color var(--dur-base) var(--ease-out);
    will-change: transform;
}
.stButton > button:active { transform: scale(0.97); }

/* ---- Hover affordances only on precise pointers ---- */
@media (hover: hover) and (pointer: fine) {
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
}

/* ---- Cards: enter once (see tab_pick_of_the_day), crisp on re-render ---- */
.pick-card {
    background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
    border: 1px solid #334155;
    border-radius: var(--radius-card);
    padding: 14px 16px;
    margin: 8px 0;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.25);
    transition:
        transform var(--dur-base) var(--ease-out),
        border-color var(--dur-base) var(--ease-out),
        box-shadow var(--dur-base) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
    .pick-card:hover {
        transform: translateY(-2px);
        border-color: #4A5568;
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
    }
}

/* ---- Custom scrollbar ---- */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #0F1419; }
::-webkit-scrollbar-thumb { background: #2D3748; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #4A5568; }

/* ---- App brand header ---- */
.app-brand {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 18px;
    border-radius: var(--radius-card);
    background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
    border: 1px solid #334155;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
    margin-bottom: 10px;
}
.app-brand-left { display: flex; align-items: center; gap: 14px; }
.app-brand-logo {
    width: 46px;
    height: 46px;
    border-radius: 12px;
    background: linear-gradient(135deg, #38BDF8 0%, #10B981 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5em;
    box-shadow: 0 4px 12px rgba(56, 189, 248, 0.25);
}
.app-brand-title { font-size: 1.25em; font-weight: 800; letter-spacing: -0.02em; color: #F1F5F9; }
.app-brand-sub { font-size: 0.82em; color: #94A3B8; margin-top: 2px; }
.app-brand-tag {
    font-size: 0.78em;
    font-weight: 600;
    color: #38BDF8;
    background: rgba(56, 189, 248, 0.10);
    border: 1px solid rgba(56, 189, 248, 0.2);
    padding: 4px 10px;
    border-radius: 20px;
    white-space: nowrap;
}

/* ---- Page navigation (st.pills) ---- */
div[data-testid="stPills"] { gap: 6px; }
div[data-testid="stPills"] div[role="option"] {
    background: #0F172A;
    border: 1px solid #2D3748;
    border-radius: 999px;
    padding: 6px 14px;
    color: #94A3B8;
    font-weight: 600;
    font-size: 0.9em;
    transition:
        background-color var(--dur-base) var(--ease-out),
        border-color var(--dur-base) var(--ease-out),
        color var(--dur-base) var(--ease-out),
        transform var(--dur-fast) var(--ease-out);
    will-change: transform;
}
@media (hover: hover) and (pointer: fine) {
    div[data-testid="stPills"] div[role="option"]:hover {
        border-color: #38BDF8;
        color: #E2E8F0;
    }
}
div[data-testid="stPills"] div[role="option"][aria-selected="true"] {
    background: rgba(56, 189, 248, 0.15);
    border-color: rgba(56, 189, 248, 0.5);
    color: #38BDF8;
}

/* ---- Reduced motion: kill all animation/transition ---- */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
}

/* ---- Metrics ---- */
div[data-testid="stMetricValue"] { font-size: 1.4rem; }

/* ---- Market cards (header: status board / IHSG) ---- */
.market-card {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.55) 0%, rgba(15, 23, 42, 0.92) 100%);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    padding: 16px 20px;
    color: #E2E8F0;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    transition:
        border-color var(--dur-base) var(--ease-out),
        box-shadow var(--dur-base) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
    .market-card:hover {
        border-color: rgba(56, 189, 248, 0.35);
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
    }
}
.market-label {
    font-size: 0.72em;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #64748B;
}
.source-chip {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 8px 12px;
    border-radius: 10px;
    background: rgba(15, 23, 42, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.12);
}
.source-chip-name { font-size: 0.8em; font-weight: 700; color: #E2E8F0; display: block; }
.source-chip-desc { font-size: 0.7em; color: #94A3B8; display: block; line-height: 1.3; }
.pulse-dot {
    width: 9px; height: 9px; border-radius: 50%; display: inline-block;
    flex: 0 0 auto;
}
.pulse-green { background: #10B981; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); animation: pulse-anim 2s infinite; }
.pulse-amber { background: #F59E0B; }
.pulse-red   { background: #EF4444; }
@keyframes pulse-anim {
    0%   { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
    70%  { transform: scale(1);    box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
    100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

/* ---- Analysis metric row (Deep Dive) ---- */
.metric-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin: 6px 0 10px;
}
@media (max-width: 900px) {
    .metric-grid { grid-template-columns: repeat(2, 1fr); }
}
.analysis-metric {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.5) 0%, rgba(15, 23, 42, 0.85) 100%);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 12px;
    padding: 12px 14px;
    margin: 6px 0;
    height: 100%;
    transition:
        border-color var(--dur-base) var(--ease-out),
        transform var(--dur-base) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
    .analysis-metric:hover {
        border-color: rgba(56, 189, 248, 0.35);
        transform: translateY(-1px);
    }
}
.analysis-metric-label {
    font-size: 0.72em;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #64748B;
}
.analysis-metric-value {
    font-size: 1.35em;
    font-weight: 800;
    color: #F1F5F9;
    line-height: 1.2;
    margin-top: 2px;
}
.analysis-metric-sub {
    font-size: 0.74em;
    color: #94A3B8;
    margin-top: 3px;
}
.metric-grid .analysis-metric { margin: 0; }

/* ---- Verdict tier cards (Deep Dive) ---- */
.tier-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin: 8px 0;
}
@media (max-width: 900px) {
    .tier-grid { grid-template-columns: 1fr; }
}
.tier-card {
    background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
    border: 1px solid #334155;
    border-radius: 14px;
    padding: 14px 16px;
    margin: 8px 0;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);
    height: 100%;
    transition:
        transform var(--dur-base) var(--ease-out),
        border-color var(--dur-base) var(--ease-out),
        box-shadow var(--dur-base) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
    .tier-card:hover {
        transform: translateY(-2px);
        border-color: #4A5568;
        box-shadow: 0 10px 24px rgba(0, 0, 0, 0.4);
    }
}
.tier-card.tier-agg { border-top: 3px solid #EF4444; }
.tier-card.tier-mod { border-top: 3px solid #FACC15; }
.tier-card.tier-low { border-top: 3px solid #10B981; }
.tier-card.tier-disabled {
    opacity: 0.45;
    filter: grayscale(60%);
    border-style: dashed;
}
.tier-card .tier-name {
    font-weight: 800;
    letter-spacing: -0.01em;
    font-size: 1.02em;
}
.tier-card .tier-tag {
    font-size: 0.72em;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #64748B;
}
.tier-grid .tier-card { margin: 0; }
.tier-card ul { list-style: none; padding: 0; margin: 10px 0 0 0; }
.tier-card li {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    font-size: 0.85em;
    padding: 4px 0;
    border-bottom: 1px solid rgba(148, 163, 184, 0.08);
    color: #94A3B8;
}
.tier-card li:last-child { border-bottom: 0; }
.tier-card li b { color: #E2E8F0; font-weight: 600; }
.tier-card .tier-warning {
    margin-top: 10px;
    font-size: 0.78em;
    color: #FBBF24;
    background: rgba(251, 191, 36, 0.08);
    border: 1px solid rgba(251, 191, 36, 0.2);
    border-radius: 8px;
    padding: 8px 10px;
}

/* ---- Compact engine comparison cards (A/B/C) ---- */
.engine-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
    margin: 8px 0 14px;
}
@media (max-width: 900px) {
    .engine-grid { grid-template-columns: 1fr; }
}
.engine-card {
    background: rgba(15, 23, 42, 0.75);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 12px;
    padding: 10px 12px;
    height: 100%;
    transition:
        border-color var(--dur-base) var(--ease-out),
        transform var(--dur-base) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
    .engine-card:hover {
        border-color: rgba(56, 189, 248, 0.35);
        transform: translateY(-1px);
    }
}
.engine-card-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 6px;
}
.engine-card-kicker {
    font-weight: 800;
    font-size: 0.76em;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}
.engine-card-title {
    font-weight: 700;
    font-size: 0.88em;
    color: #E2E8F0;
}
.engine-card-pill {
    margin-left: auto;
    font-size: 0.68em;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    background: rgba(56, 189, 248, 0.10);
    border: 1px solid rgba(56, 189, 248, 0.25);
    color: #38BDF8;
    white-space: nowrap;
}
.engine-card-note {
    font-size: 0.72em;
    color: #94A3B8;
    margin: 4px 0 6px;
    line-height: 1.35;
}
.engine-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.74em;
}
.engine-table th {
    text-align: left;
    color: #64748B;
    font-weight: 600;
    padding: 3px 4px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.15);
}
.engine-table td {
    padding: 3px 4px;
    color: #CBD5E1;
    border-bottom: 1px solid rgba(148, 163, 184, 0.07);
}
.engine-table tr:last-child td { border-bottom: 0; }
.engine-table td.eng-agg { color: #F87171; font-weight: 600; }
.engine-table td.eng-mod { color: #FACC15; font-weight: 600; }
.engine-table td.eng-low { color: #34D399; font-weight: 600; }

/* ---- Sidebar: Screener Settings panel ---- */
.settings-panel {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.5) 0%, rgba(15, 23, 42, 0.85) 100%);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 6px;
}
.settings-panel-title {
    font-size: 0.95em;
    font-weight: 800;
    letter-spacing: -0.01em;
    color: #F1F5F9;
}
.settings-panel-sub {
    font-size: 0.72em;
    color: #94A3B8;
    margin-top: 2px;
}
.settings-section-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.82em;
    font-weight: 700;
    color: #E2E8F0;
    padding: 8px 10px;
    margin: 10px 0 4px;
    border-radius: 8px;
    background: rgba(56, 189, 248, 0.06);
    border-left: 3px solid #38BDF8;
}

/* ---- Filter summary (screener: "Displaying N tickers") ---- */
.filter-summary {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.5) 0%, rgba(15, 23, 42, 0.85) 100%);
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 12px;
    padding: 12px 14px;
    margin: 8px 0 12px;
}
.filter-summary-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
}
.filter-summary-title { font-size: 0.95em; font-weight: 700; color: #E2E8F0; }
.filter-summary-title b { color: #38BDF8; font-weight: 800; }
.filter-summary-pill {
    font-size: 0.72em;
    font-weight: 700;
    padding: 3px 10px;
    border-radius: 999px;
    background: rgba(56, 189, 248, 0.10);
    border: 1px solid rgba(56, 189, 248, 0.25);
    color: #38BDF8;
    white-space: nowrap;
}
.ticker-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 9px;
    max-height: 128px;
    overflow-y: auto;
    padding-right: 4px;
}
.ticker-chip {
    font-size: 0.76em;
    font-weight: 600;
    color: #CBD5E1;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(148, 163, 184, 0.15);
    padding: 2px 10px;
    border-radius: 999px;
}
.filter-summary-note {
    margin-top: 9px;
    font-size: 0.76em;
    color: #94A3B8;
    line-height: 1.4;
}

/* ---- Panel title (news controls / filters) ---- */
.panel-title {
    font-size: 0.78em;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #64748B;
    margin-bottom: 4px;
}
.panel-title b { color: #38BDF8; }

/* ---- News source summary badges ---- */
.source-summary {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin: 6px 0 12px;
}
.source-summary-time {
    font-size: 0.76em;
    color: #94A3B8;
    margin-left: auto;
}
.src-badge {
    font-size: 0.78em;
    font-weight: 600;
    padding: 3px 11px;
    border-radius: 999px;
    white-space: nowrap;
}
.src-ok   { background: rgba(56, 189, 248, 0.12); color: #38BDF8; }
.src-dead { background: rgba(239, 68, 68, 0.10);  color: #F87171; }
.src-empty{ background: rgba(100, 116, 139, 0.10); color: #8899A6; }

/* ---- News count badge ---- */
.news-count-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 0.8em;
    font-weight: 600;
    color: #E2E8F0;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(148, 163, 184, 0.15);
    padding: 5px 13px;
    border-radius: 999px;
    margin: 8px 0 4px;
}
.news-count-badge b { color: #38BDF8; font-weight: 800; }

/* ---- Bordered containers (news panels) get the glass look ----
   Streamlit 1.58 renders st.container(border=True, key=...) as
   div[data-testid="stVerticalBlock"] with class "st-key-<key>". */
div[data-testid="stVerticalBlock"].st-key-ns_controls,
div[data-testid="stVerticalBlock"].st-key-ns_filters {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.35) 0%, rgba(15, 23, 42, 0.65) 100%);
    border-color: rgba(148, 163, 184, 0.15) !important;
    border-radius: 12px;
}
</style>
""",
        unsafe_allow_html=True,
    )
