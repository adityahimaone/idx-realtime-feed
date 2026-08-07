"""
IDX corporate calendar — plain functions shared by the Streamlit calendar tab
and the pre-market predictor. No streamlit dependency here so bots can use it.
"""
import time
from datetime import datetime

from curl_cffi import requests as requests_cf

# Month → (expiry, events). The pre-market predictor calls events_for_ticker_on
# per ticker, so cache the shared month payload to avoid hammering IDX.
_calendar_cache: dict[str, tuple[float, list[dict]]] = {}
CALENDAR_CACHE_TTL_SEC = 600


def fetch_calendar_events(date_str: str) -> list[dict]:
    """Fetch corporate calendar from IDX website.

    date_str is the IDX month parameter (YYYYMMDD of the 1st of the month).
    Returns the raw "Results" list; never raises (failure → []). Cached 10 min.
    """
    now = time.time()
    cached = _calendar_cache.get(date_str)
    if cached and now < cached[0]:
        return cached[1]

    events: list[dict] = []
    url = f"https://www.idx.co.id/primary/Home/GetCalendar?range=m&date={date_str}"
    try:
        r = requests_cf.get(url, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            events = r.json().get("Results", [])
    except Exception:
        pass
    _calendar_cache[date_str] = (now + CALENDAR_CACHE_TTL_SEC, events)
    return events


def classify_event(desc: str) -> dict:
    """Classify a calendar event description into signal + notes.

    Labels are identical to the legacy tab12 classifier (unchanged behavior).
    Returns {"signal": ..., "notes": ...}.
    """
    desc_lower = (desc or "").lower()
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
    return {"signal": signal, "notes": notes}


def events_for_ticker_on(ticker: str, date) -> list[dict]:
    """Calendar events for `ticker` on `date` (datetime.date or "YYYY-MM-DD").

    Fetches the event's month, filters by ticker (title field) and exact date.
    Returns list of dicts: {ticker, date, event_type, description, signal, notes}.
    """
    if isinstance(date, str):
        date = datetime.strptime(date[:10], "%Y-%m-%d").date()
    date_param = f"{date.year}{date.month:02d}01"

    events = []
    for ev in fetch_calendar_events(date_param):
        ev_ticker = (ev.get("title") or "").strip().upper()
        if ev_ticker != ticker.upper().strip():
            continue
        start_raw = ev.get("start", "")
        if not start_raw:
            continue
        try:
            ev_date = datetime.strptime(start_raw[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if ev_date != date:
            continue
        cls = classify_event(ev.get("description", ""))
        events.append({
            "ticker": ev_ticker,
            "date": ev_date.isoformat(),
            "event_type": ev.get("Jenis", "-"),
            "description": ev.get("description", ""),
            "signal": cls["signal"],
            "notes": cls["notes"],
        })
    return events
