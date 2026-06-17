import streamlit as st
import pandas as pd
import time
import calendar
from datetime import datetime, timedelta
from curl_cffi import requests as requests_cf

WIB = __import__("pytz").timezone("Asia/Jakarta")


def fetch_idx_calendar(date_str: str) -> list[dict]:
    """Fetch corporate calendar from IDX website."""
    url = f"https://www.idx.co.id/primary/Home/GetCalendar?range=m&date={date_str}"
    try:
        r = requests_cf.get(url, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            return r.json().get("Results", [])
    except Exception as e:
        st.error(f"Failed to fetch IDX Calendar: {e}")
    return []


def render_tab12():
    st.markdown("""
<style>
    /* Styling Calendar Header weekdays */
    .cal-grid-header {
        text-align: center;
        font-weight: 800;
        color: #94A3B8;
        text-transform: uppercase;
        font-size: 0.8em;
        letter-spacing: 0.1em;
        margin-bottom: 12px;
        padding-bottom: 4px;
        border-bottom: 2px solid rgba(255, 255, 255, 0.05);
    }
    
    /* Sleek card hover transformations for alerts */
    .rec-card {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%) !important;
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        border-radius: 12px !important;
        padding: 16px !important;
        position: relative;
        overflow: hidden;
    }
    .rec-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.04), transparent);
        transform: translateX(-100%);
        transition: transform 0.5s;
    }
    .rec-card:hover::before {
        transform: translateX(100%);
    }
    .rec-card:hover {
        transform: translateY(-4px) scale(1.02) !important;
        box-shadow: 0 12px 20px rgba(0, 0, 0, 0.4) !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
    }
    
    /* Calendar Button Overrides to make them look like professional grid cells */
    .stButton > button {
        border-radius: 8px !important;
        height: 50px !important;
        font-weight: 600 !important;
        font-size: 0.95em !important;
        transition: all 0.2s ease-in-out !important;
        background: rgba(30, 41, 59, 0.3) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        color: #E2E8F0 !important;
    }
    
    /* Secondary (standard day with no events) hover */
    .stButton > button:hover {
        background: rgba(30, 41, 59, 0.8) !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
        color: #FFFFFF !important;
        transform: scale(1.05);
    }
    
    /* Primary buttons (currently selected day) */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%) !important;
        border: 1px solid #60A5FA !important;
        box-shadow: 0 0 12px rgba(59, 130, 246, 0.5) !important;
        color: #FFFFFF !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #60A5FA 0%, #2563EB 100%) !important;
        box-shadow: 0 0 16px rgba(96, 165, 250, 0.7) !important;
        transform: scale(1.05);
    }
</style>
""", unsafe_allow_html=True)

    st.markdown("### 📅 IDX Corporate Calendar & Event Signals")
    st.caption("Interactive monthly calendar and event-driven signals for IDX corporate actions.")

    # Initialize states
    if "selected_cal_day" not in st.session_state:
        st.session_state.selected_cal_day = None

    now_dt = datetime.now(WIB)
    
    # Month/Year selector
    c_sel1, c_sel2 = st.columns(2)
    with c_sel1:
        selected_month = st.selectbox(
            "Month",
            options=list(range(1, 13)),
            index=now_dt.month - 1,
            format_func=lambda m: calendar.month_name[m],
            key="cal_month_select"
        )
    with c_sel2:
        selected_year = st.selectbox(
            "Year",
            options=list(range(now_dt.year - 1, now_dt.year + 2)),
            index=1,  # current year
            key="cal_year_select"
        )

    # Date param format YYYYMMDD (using 1st of the month to get the month calendar)
    date_param = f"{selected_year}{selected_month:02d}01"

    with st.spinner("📅 Syncing corporate events from IDX..."):
        events = fetch_idx_calendar(date_param)

    # Process events
    events_by_day = {}
    all_events = []
    
    tomorrow_dt = (now_dt + timedelta(days=1)).date()
    h1_alerts = []

    for ev in events:
        ticker = ev.get("title", "").strip().upper()
        desc = ev.get("description", "")
        start_raw = ev.get("start", "")
        location = ev.get("location", "-")
        rups_time = ev.get("TglWaktuRups", "-")
        jenis = ev.get("Jenis", "-")
        
        event_date = None
        day_num = None
        if start_raw:
            try:
                dt_obj = datetime.strptime(start_raw[:10], "%Y-%m-%d")
                event_date = dt_obj.date()
                if dt_obj.month == selected_month and dt_obj.year == selected_year:
                    day_num = dt_obj.day
            except Exception:
                pass
                
        # Analyze Signal / Sentiment
        desc_lower = desc.lower()
        if "dividen" in desc_lower or "dividend" in desc_lower or "bagi hasil" in desc_lower:
            signal = "🟢 Speculative Buy (Pre-Dividend Momentum)"
            notes = "Announcements of dividends usually spark buy interest. Best entry window: H-1 before event or cum-date."
        elif "stock split" in desc_lower or "pecah saham" in desc_lower:
            signal = "🟢 Speculative Buy (Liquidity Event)"
            notes = "Stock splits increase retail accessibility. Positive liquidity momentum is expected leading up to split."
        elif "penggabungan nilai" in desc_lower or "reverse split" in desc_lower or "merger" in desc_lower:
            signal = "🔴 Avoid / High Risk (Capital Consolidation)"
            notes = "Reverse splits are usually negatively perceived due to signs of underlying distress."
        elif "rups" in desc_lower or "general meeting" in desc_lower:
            signal = "🟡 Watch (AGMS/EGMS Vote)"
            notes = "AGMS/EGMS events are regulatory. Look out for unexpected corporate actions (e.g. rights issue or change of board)."
        elif "rights issue" in desc_lower or "hmetd" in desc_lower:
            signal = "🟡 Speculative (Capital Expansion)"
            notes = "Rights issue dilutes shares but raises capital. Bullish if funds are for clear expansions."
        else:
            signal = "🟡 Watch (Corporate Event)"
            notes = "Regular event. Keep an eye on direct mentions in stock news channels."

        event_obj = {
            "Date": event_date.strftime("%d %b %Y") if event_date else start_raw[:10],
            "Ticker": ticker,
            "Event Type": jenis,
            "Description": desc,
            "H-1 Signal Analysis": signal,
            "Action Notes": notes,
            "Location": location,
            "RUPS Time": rups_time,
            "_raw_date": event_date
        }

        all_events.append(event_obj)

        # Map to calendar day
        if day_num is not None:
            events_by_day.setdefault(day_num, []).append(event_obj)

        # Check H-1 Notification (if event is tomorrow)
        if event_date == tomorrow_dt:
            h1_alerts.append(event_obj)

    # ============================================================================
    # 🚨 H-1 NOTIFICATION CARD SECTION
    # ============================================================================
    if h1_alerts:
        st.markdown("#### 🔔 Tomorrow's Event Alerts (H-1 Signals)")
        for idx in range(0, len(h1_alerts), 3):
            cols = st.columns(3)
            for col_idx in range(3):
                if idx + col_idx < len(h1_alerts):
                    alert = h1_alerts[idx + col_idx]
                    border_color = (
                        "#10B981" if "🟢" in alert["H-1 Signal Analysis"]
                        else "#EF4444" if "🔴" in alert["H-1 Signal Analysis"]
                        else "#F59E0B"
                    )
                    card_html = (
                        f'<div class="rec-card" style="border-left:5px solid {border_color};margin-bottom:12px;display:flex;flex-direction:column;justify-content:space-between;height:180px;">'
                        f'<div>'
                        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
                        f'<strong style="font-size:1.15em;color:#F8FAFC;letter-spacing:0.02em;">🚀 {alert["Ticker"]}</strong>'
                        f'<span style="background:{border_color}18;color:{border_color};padding:3px 8px;border-radius:6px;font-size:0.75em;font-weight:800;border:1px solid {border_color}33;">'
                        f'{alert["Event Type"]}</span>'
                        f'</div>'
                        f'<div style="font-size:0.85em;color:#94A3B8;line-height:1.4;margin-bottom:10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;text-overflow:ellipsis;">'
                        f'{alert["Description"]}'
                        f'</div>'
                        f'</div>'
                        f'<div style="background:{border_color}08;padding:8px 10px;border-radius:6px;font-size:0.78em;color:#E2E8F0;border:1px solid {border_color}20;display:flex;align-items:center;">'
                        f'{alert["H-1 Signal Analysis"]}'
                        f'</div>'
                        f'</div>'
                    )
                    cols[col_idx].markdown(card_html, unsafe_allow_html=True)
        st.markdown("---")

    # ============================================================================
    # 📅 INTERACTIVE CALENDAR GRID
    # ============================================================================
    st.markdown(f"#### 📅 Calendar Grid — {calendar.month_name[selected_month]} {selected_year}")
    
    # Calculate month ranges
    first_weekday, num_days = calendar.monthrange(selected_year, selected_month)
    
    headers = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    cols = st.columns(7)
    for i, h in enumerate(headers):
        cols[i].markdown(f"<p class='cal-grid-header'>{h}</p>", unsafe_allow_html=True)

    # Render days
    day_counter = 1
    # We pad the calendar grid with empty columns for days before the 1st
    row_cols = st.columns(7)
    for i in range(7):
        if i < first_weekday:
            row_cols[i].write("")
        else:
            _render_day_btn(row_cols[i], day_counter, events_by_day.get(day_counter, []))
            day_counter += 1

    # Render remaining rows
    while day_counter <= num_days:
        row_cols = st.columns(7)
        for i in range(7):
            if day_counter <= num_days:
                _render_day_btn(row_cols[i], day_counter, events_by_day.get(day_counter, []))
                day_counter += 1
            else:
                row_cols[i].write("")

    st.markdown("---")

    # ============================================================================
    # 🔎 SELECTED DAY DETAILS
    # ============================================================================
    sel_day = st.session_state.selected_cal_day
    if sel_day and sel_day in events_by_day:
        st.markdown(f"#### 🔍 Events on {sel_day} {calendar.month_name[selected_month]} {selected_year}")
        day_events = events_by_day[sel_day]
        for ev in day_events:
            border_color = (
                "#10B981" if "🟢" in ev["H-1 Signal Analysis"]
                else "#EF4444" if "🔴" in ev["H-1 Signal Analysis"]
                else "#F59E0B"
            )
            with st.container(border=True):
                st.markdown(f"##### **{ev['Ticker']}** ({ev['Event Type']})")
                st.markdown(f"**Description:** {ev['Description']}")
                st.markdown(f"**Signal Analysis:** <span style='color:{border_color};font-weight:700;'>{ev['H-1 Signal Analysis']}</span>", unsafe_allow_html=True)
                st.markdown(f"**Action Note:** {ev['Action Notes']}")
                if ev['Location'] and ev['Location'] != "-":
                    st.markdown(f"📍 **Location:** {ev['Location']}")
                if ev['RUPS Time'] and ev['RUPS Time'] != "-":
                    st.markdown(f"🕒 **Time:** {ev['RUPS Time']}")
    elif sel_day:
        st.info(f"No events scheduled for {sel_day} {calendar.month_name[selected_month]} {selected_year}.")
    else:
        st.info("💡 Click a calendar day button above to view event details.")


def _render_day_btn(col, day_num, day_events):
    """Helper to render a styled Streamlit button for each day."""
    has_event = len(day_events) > 0
    badge = f" ({len(day_events)})" if has_event else ""
    label = f"{day_num}{badge}"
    
    # Highlight selection
    selected = st.session_state.selected_cal_day == day_num
    btn_type = "primary" if selected else "secondary"
    
    if col.button(label, key=f"cal_day_{day_num}", type=btn_type, use_container_width=True):
        st.session_state.selected_cal_day = day_num
        st.rerun()
