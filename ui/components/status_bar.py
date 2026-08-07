"""
Live time & API status board + IHSG live chart.

Design language: two separate glass cards (`#0F172A`, 14px radius, Inter,
exact-property transitions, reduced-motion respected). Rendered as HTML
components so the JS-driven WIB clock and Chart.js sparkline keep working.
"""
import html as _html_escape
import streamlit as st
from datetime import datetime
import pytz

WIB = pytz.timezone("Asia/Jakarta")

# Sources that must be fully connected for core features; when inactive they
# count as hard-down (red) instead of merely degraded (amber).
_HARD_DOWN = {"Google Sheets", "Exodus API"}

# Short status word shown per chip (dot + name + word). The longer `desc`
# passed by the caller (or the state word) is exposed as the tooltip title.
_STATE_WORD = {"ok": "Online", "degraded": "Standby", "down": "Down", "checking": "Checking…"}

_CARD_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
.market-card {
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.55) 0%, rgba(15, 23, 42, 0.92) 100%);
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    padding: 16px 20px;
    color: #E2E8F0;
    font-family: 'Inter', sans-serif;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    transition:
        border-color 200ms cubic-bezier(0.23, 1, 0.32, 1),
        box-shadow 200ms cubic-bezier(0.23, 1, 0.32, 1);
}
.market-card:hover {
    border-color: rgba(56, 189, 248, 0.35);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
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
    gap: 10px;
    padding: 8px 12px;
    border-radius: 10px;
    background: rgba(15, 23, 42, 0.55);
    border: 1px solid rgba(148, 163, 184, 0.12);
    min-width: 0;
}
.source-chip-body {
    display: flex;
    flex-direction: column;
    min-width: 0;
}
.source-chip-name {
    font-size: 0.8em;
    font-weight: 700;
    color: #E2E8F0;
    white-space: nowrap;
}
.source-chip-desc {
    font-size: 0.7em;
    color: #94A3B8;
    line-height: 1.3;
}
.pulse-dot {
    width: 9px; height: 9px; border-radius: 50%; display: inline-block;
    flex: 0 0 auto;
}
.pulse-green { background: #10B981; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); animation: pulse-anim 2s infinite; }
.pulse-amber { background: #F59E0B; }
.pulse-red   { background: #EF4444; }
.pulse-sky   { background: #38BDF8; box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.6); animation: pulse-anim 1.6s infinite; }
@keyframes pulse-anim {
    0%   { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
    70%  { transform: scale(1);    box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
    100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
</style>
"""


def _dot_html(state: str) -> str:
    """Pulse dot per source state: ok / degraded / down."""
    if state == "ok":
        return '<span class="pulse-dot pulse-green" title="Connected"></span>'
    if state == "degraded":
        return '<span class="pulse-dot pulse-amber" title="Degraded"></span>'
    if state == "checking":
        return '<span class="pulse-dot pulse-sky" title="Connecting"></span>'
    return '<span class="pulse-dot pulse-red" title="Down"></span>'


def render_status_board(api_statuses: dict | None = None, container=None):
    """Market Status + per-source API indicators (live clock JS-driven).

    `api_statuses` maps source name → {"active": bool, "desc": str}. The short
    `desc` is shown on the chip (e.g. "Registry OK", "Authorized"); full detail
    can live in the tooltip. Sources in _HARD_DOWN render red when inactive;
    everything else renders amber (degraded/standby) so fallbacks like Google
    Finance stay visible. `active=None` renders a "checking" (sky) state — used
    for the provisional header while the data pipeline is still connecting.
    `container` (optional st.empty placeholder) routes the component there so
    the header can render instantly and be replaced after fetches finish.
    """
    now_wib = datetime.now(WIB)
    is_day_trade = now_wib.weekday() < 5 and (
        (now_wib.hour == 9 and now_wib.minute >= 0)
        or (now_wib.hour > 9 and now_wib.hour < 16)
        or (now_wib.hour == 16 and now_wib.minute == 0)
    )
    badge_text = "LIVE" if is_day_trade else "CLOSED"
    badge_color = "#10B981" if is_day_trade else "#F59E0B"
    badge_bg = "rgba(16,185,129,0.15)" if is_day_trade else "rgba(245,158,11,0.15)"
    badge_border = "rgba(16,185,129,0.35)" if is_day_trade else "rgba(245,158,11,0.35)"

    chips = ""
    for source, info in (api_statuses or {}).items():
        raw_active = info.get("active") if isinstance(info, dict) else False
        desc = info.get("desc", "") if isinstance(info, dict) else ""
        if raw_active is True:
            state = "ok"
        elif raw_active is None:
            state = "checking"
        elif source in _HARD_DOWN:
            state = "down"
        else:
            state = "degraded"
        word = desc or _STATE_WORD.get(state, state.capitalize())
        tooltip = _html_escape.escape(desc or f"{source} — {_STATE_WORD.get(state, state.capitalize())}")
        chips += (
            f'<div class="source-chip" title="{tooltip}">{_dot_html(state)}'
            f'<div class="source-chip-body">'
            f'<span class="source-chip-name">{source}</span>'
            f'<span class="source-chip-desc">{word}</span>'
            f'</div></div>'
        )

    html = _CARD_CSS + f"""
<div class="market-card">
    <div style="display:flex; flex-wrap:wrap; gap:18px; align-items:center;">
        <div style="flex:0 0 auto; min-width:210px;">
            <div class="market-label">Market Status</div>
            <div style="display:flex; align-items:center; gap:10px; margin-top:6px;">
                <span id="market_status_badge" style="display:inline-flex; align-items:center; gap:6px; padding:4px 12px; border-radius:999px; font-weight:700; font-size:0.82em; background:{badge_bg}; color:{badge_color}; border:1px solid {badge_border};">
                    <span style="width:7px; height:7px; border-radius:50%; background:{badge_color};"></span>{badge_text}
                </span>
                <span id="realtime_clock_span" style="font-family:monospace; font-size:0.95em; color:#E2E8F0;">{now_wib.strftime('%H:%M:%S')}</span>
                <span style="color:#94A3B8; font-size:0.8em;">WIB</span>
            </div>
            <div style="margin-top:8px; font-size:0.78em; color:#64748B;">
                {now_wib.strftime('%A, %d %b %Y')} · Sesi IDX {('09:00–16:00') if is_day_trade else 'ditutup'}
            </div>
        </div>
        <div style="flex:1; min-width:260px; display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:8px 14px;">
            {chips}
        </div>
    </div>
    <div style="margin-top:12px; padding-top:10px; border-top:1px solid rgba(148,163,184,0.15); color:#64748B; font-size:0.76em;">
        Stockbit ➔ itick ➔ IDX ➔ GSheet/yfinance · Deep: Exodus ➔ itick
    </div>
</div>
<script>
(function() {{
    function getWIB() {{
        var now = new Date();
        var utc = now.getTime() + (now.getTimezoneOffset() * 60000);
        return new Date(utc + (3600000 * 7));
    }}
    function pad(n) {{ return String(n).padStart(2, '0'); }}
    function isMarketOpen(w) {{
        var day = w.getDay(), h = w.getHours(), m = w.getMinutes();
        if (day < 1 || day > 5) return false;
        return (h === 9) || (h > 9 && h < 16) || (h === 16 && m === 0);
    }}
    function tick() {{
        var w = getWIB();
        var clockEl = document.getElementById('realtime_clock_span');
        var badgeEl = document.getElementById('market_status_badge');
        if (!clockEl) {{
            clockEl = window.parent.document.getElementById('realtime_clock_span');
            badgeEl = window.parent.document.getElementById('market_status_badge');
        }}
        if (clockEl) clockEl.textContent = pad(w.getHours()) + ':' + pad(w.getMinutes()) + ':' + pad(w.getSeconds());
        if (badgeEl) {{
            var open = isMarketOpen(w);
            badgeEl.textContent = open ? 'LIVE' : 'CLOSED';
            badgeEl.style.color = open ? '#10B981' : '#F59E0B';
            badgeEl.style.background = open ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)';
            badgeEl.style.borderColor = open ? 'rgba(16,185,129,0.35)' : 'rgba(245,158,11,0.35)';
        }}
    }}
    tick();
    setInterval(tick, 1000);
}})();
</script>
"""
    if container is None:
        st.components.v1.html(html, height=190, scrolling=False)
    else:
        with container:
            st.components.v1.html(html, height=190, scrolling=False)


def render_ihsg_widget(ihsg: dict | None, container=None, loading: bool = False):
    def _emit(html: str, height: int) -> None:
        if container is None:
            st.components.v1.html(html, height=height, scrolling=False)
        else:
            with container:
                st.components.v1.html(html, height=height, scrolling=False)

    if not ihsg:
        if loading:
            html = _CARD_CSS + """
<div class="market-card">
    <div class="market-label">IHSG / IDX Composite</div>
    <div style="display:flex; align-items:center; gap:10px; margin-top:6px;">
        <span class="pulse-dot pulse-sky"></span>
        <span style="font-size:0.95em; color:#94A3B8; font-weight:600;">⏳ Memuat data IHSG…</span>
    </div>
    <div style="margin-top:8px; font-size:0.72em; color:#64748B;">
        Menghubungkan ke yfinance ➔ Yahoo API ➔ Google Finance
    </div>
</div>
"""
        else:
            html = _CARD_CSS + """
<div class="market-card">
    <div class="market-label">IHSG / IDX Composite</div>
    <div style="margin-top:6px; font-size:0.95em; color:#F87171; font-weight:600;">
        ⚠️ IHSG data tidak tersedia saat ini.
    </div>
    <div style="margin-top:6px; font-size:0.72em; color:#64748B;">
        Semua sumber gagal: yfinance ➔ Yahoo API ➔ Google Finance
    </div>
</div>
"""
        _emit(html, 116)
        return

    is_up = ihsg.get("change_abs", 0.0) >= 0
    chg_color = "#10B981" if is_up else "#EF4444"
    chg_arrow = "▲" if is_up else "▼"
    chg_bg = "rgba(16,185,129,0.10)" if is_up else "rgba(239,68,68,0.10)"
    chg_border = "rgba(16,185,129,0.30)" if is_up else "rgba(239,68,68,0.30)"
    _vol = ihsg.get("volume") or 0
    volume_fmt = f"{_vol / 1e9:.2f}B" if _vol else "—"
    _open = ihsg.get("open") or 0
    _high = ihsg.get("high") or 0
    _low = ihsg.get("low") or 0
    _prev = ihsg.get("prev_close") or 0

    source_chip = (
        f'<span style="display:inline-flex; align-items:center; gap:6px; padding:2px 10px; '
        f'border-radius:999px; background:rgba(56,189,248,0.10); border:1px solid rgba(56,189,248,0.25); '
        f'color:#38BDF8; font-size:0.72em; font-weight:600;">'
        f'<span style="width:6px; height:6px; border-radius:50%; background:#38BDF8;"></span>'
        f'{ihsg.get("source", "Fallback")}</span>'
    )

    # Fallback mode (Google Finance — no sparkline)
    if not ihsg.get("sparkline") or not ihsg.get("prices"):
        html = _CARD_CSS + f"""
<div class="market-card">
    <div class="market-label">IHSG / IDX Composite</div>
    <div style="display:flex; align-items:baseline; gap:12px; margin-top:4px; flex-wrap:wrap;">
        <span style="font-size:2.2em; font-weight:800; color:#F1F5F9; line-height:1.1;">{ihsg['current']:,.2f}</span>
        <span style="display:inline-flex; align-items:center; gap:6px; padding:3px 12px; border-radius:999px; background:{chg_bg}; border:1px solid {chg_border}; color:{chg_color}; font-weight:700; font-size:0.9em;">
            {chg_arrow} {abs(ihsg['change_abs']):,.2f} ({abs(ihsg['change_pct']):.2f}%)
        </span>
    </div>
    <div style="display:flex; gap:16px; margin-top:10px; font-size:0.8em; color:#94A3B8; flex-wrap:wrap;">
        <span>O <b style="color:#CBD5E1;">{_open:,.2f}</b></span>
        <span>H <b style="color:#10B981;">{_high:,.2f}</b></span>
        <span>L <b style="color:#EF4444;">{_low:,.2f}</b></span>
        <span>Prev <b style="color:#CBD5E1;">{_prev:,.2f}</b></span>
        <span>Vol <b style="color:#CBD5E1;">{volume_fmt}</b></span>
    </div>
    <div style="margin-top:8px; display:flex; align-items:center; gap:10px; font-size:0.72em; color:#64748B;">
        {source_chip} · no sparkline · refresh tiap 120 detik
    </div>
</div>
"""
        _emit(html, 152)
        return

    line_color = "#10B981" if is_up else "#EF4444"
    fill_color = "rgba(16,185,129,0.12)" if is_up else "rgba(239,68,68,0.12)"
    prices_js = str([round(p, 2) for p in ihsg["prices"]])
    times_js = str(ihsg["times"])
    min_p = round(min(ihsg["prices"]) * 0.9995, 2)
    max_p = round(max(ihsg["prices"]) * 1.0005, 2)

    html = _CARD_CSS + f"""
<div class="market-card">
    <div style="display:flex; gap:22px; align-items:center;">
        <div style="flex:0 0 auto;">
            <div class="market-label">IHSG / IDX Composite</div>
            <div style="display:flex; align-items:baseline; gap:12px; margin-top:4px; flex-wrap:wrap;">
                <span style="font-size:2.2em; font-weight:800; color:#F1F5F9; line-height:1.1;">{ihsg['current']:,.2f}</span>
                <span style="display:inline-flex; align-items:center; gap:6px; padding:3px 12px; border-radius:999px; background:{chg_bg}; border:1px solid {chg_border}; color:{chg_color}; font-weight:700; font-size:0.9em;">
                    {chg_arrow} {abs(ihsg['change_abs']):,.2f} ({abs(ihsg['change_pct']):.2f}%)
                </span>
            </div>
            <div style="display:flex; gap:16px; margin-top:10px; font-size:0.8em; color:#94A3B8; flex-wrap:wrap;">
                <span>O <b style="color:#CBD5E1;">{_open:,.2f}</b></span>
                <span>H <b style="color:#10B981;">{_high:,.2f}</b></span>
                <span>L <b style="color:#EF4444;">{_low:,.2f}</b></span>
                <span>Prev <b style="color:#CBD5E1;">{_prev:,.2f}</b></span>
                <span>Vol <b style="color:#CBD5E1;">{volume_fmt}</b></span>
            </div>
            <div style="margin-top:8px; display:flex; align-items:center; gap:10px; font-size:0.72em; color:#64748B;">
                {source_chip} · refresh tiap 60 detik
            </div>
        </div>
        <div style="flex:1; min-width:0; height:92px; position:relative;">
            <canvas id="ihsg_chart" style="width:100%; height:92px;"></canvas>
        </div>
    </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function(){{
  var prices={prices_js};
  var labels={times_js};
  function init(){{
    var el=document.getElementById('ihsg_chart');
    if(!el)el=window.parent.document.getElementById('ihsg_chart');
    if(!el)return;
    var ctx=el.getContext('2d');
    var grad=ctx.createLinearGradient(0,0,0,92);
    grad.addColorStop(0,'{fill_color}');
    grad.addColorStop(1,'rgba(0,0,0,0)');
    new Chart(ctx,{{
      type:'line',
      data:{{
        labels:labels,
        datasets:[{{
          data:prices,
          borderColor:'{line_color}',
          borderWidth:2,
          backgroundColor:grad,
          fill:true,
          pointRadius:0,
          tension:0.3
        }}]
      }},
      options:{{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{{legend:{{display:false}}}},
        scales:{{
          x:{{display:false}},
          y:{{display:false,min:{min_p},max:{max_p}}}
        }},
        animation:{{duration:400}}
      }}
    }});
  }}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
}})( );
</script>
"""
    _emit(html, 182)
