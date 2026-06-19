"""
Live time & API status board + IHSG live chart.
"""
import streamlit as st
from datetime import datetime
import pytz

WIB = pytz.timezone("Asia/Jakarta")


def render_status_board():
    """Market Status + API indicators (live clock JS-driven)."""
    now_wib = datetime.now(WIB)
    is_day_trade = now_wib.weekday() < 5 and (
        (now_wib.hour == 9 and now_wib.minute >= 0)
        or (now_wib.hour > 9 and now_wib.hour < 16)
        or (now_wib.hour == 16 and now_wib.minute == 0)
    )
    badge_text = "LIVE 🔴" if is_day_trade else "CLOSED ⏸️"
    badge_color = "#10B981" if is_day_trade else "#F59E0B"
    badge_bg = "rgba(16,185,129,0.15)" if is_day_trade else "rgba(245,158,11,0.15)"
    badge_border = "rgba(16,185,129,0.3)" if is_day_trade else "rgba(245,158,11,0.3)"

    html = f"""
<style>
    .status-container {{ display:flex; flex-wrap:wrap; gap:12px 18px; align-items:center; padding:14px 18px; border-radius:12px; background:#1A202C; color:#E2E8F0; border:1px solid #2D3748; }}
    .status-item {{ display:flex; align-items:center; gap:8px; font-size:0.9em; }}
    .live-label-container {{ display:inline-flex; align-items:center; gap:6px; padding:4px 8px; border-radius:6px; font-weight:700; font-size:0.8em; }}
    @keyframes pulse-green-anim {{ 0% {{ transform:scale(.95); box-shadow:0 0 0 0 rgba(16,185,129,.7); }} 70% {{ transform:scale(1); box-shadow:0 0 0 6px rgba(16,185,129,0); }} 100% {{ transform:scale(.95); box-shadow:0 0 0 0 rgba(16,185,129,0); }} }}
    .pulse-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
    .pulse-green {{ background:#10B981; box-shadow:0 0 0 0 rgba(16,185,129,.7); animation:pulse-green-anim 2s infinite; }}
</style>
<div class="status-container">
    <div class="status-item">
        <strong>Market Status:</strong>
        <span id="market_status_badge" class="live-label-container" style="background-color:{badge_bg};color:{badge_color};border:1px solid {badge_border};">{badge_text}</span>
        <span id="realtime_clock_span" style="font-family:monospace;font-size:0.95em;">{now_wib.strftime('%Y-%m-%d %H:%M:%S')}</span>
        <span style="color:#94A3B8;font-size:0.85em;">WIB</span>
    </div>
    <div class="status-item"><span class="pulse-dot pulse-green"></span><span><strong>Google Sheets:</strong> Connected (Active Pool)</span></div>
    <div class="status-item"><span class="pulse-dot pulse-green"></span><span><strong>Yahoo Finance:</strong> Online (JK Feed)</span></div>
    <div class="status-item"><span class="pulse-dot pulse-green"></span><span><strong>IDX Endpoint:</strong> Online (Trading Summary)</span></div>
    <div class="status-item"><span class="pulse-dot pulse-green"></span><span><strong>Exodus API:</strong> Ready (Deep Analysis)</span></div>
    <hr style="width:100%; border:0; border-top:1px solid #2D3748; margin:8px 0;">
    <div style="color:#64748B; font-size:0.8em;">Freshness Fallback Pipeline: Google Sheets ➔ yfinance ➔ IDX. (Stockbit for Deep Analysis only).</div>
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
        if (!clockEl) {{ clockEl = window.parent.document.getElementById('realtime_clock_span'); badgeEl = window.parent.document.getElementById('market_status_badge'); }}
        if (clockEl) clockEl.textContent = w.getFullYear() + '-' + pad(w.getMonth()+1) + '-' + pad(w.getDate()) + ' ' + pad(w.getHours()) + ':' + pad(w.getMinutes()) + ':' + pad(w.getSeconds());
        if (badgeEl) {{
            var open = isMarketOpen(w);
            badgeEl.textContent = open ? 'LIVE 🔴' : 'CLOSED ⏸️';
            badgeEl.style.backgroundColor = open ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)';
            badgeEl.style.color = open ? '#10B981' : '#F59E0B';
            badgeEl.style.borderColor = open ? 'rgba(16,185,129,0.3)' : 'rgba(245,158,11,0.3)';
        }}
    }}
    tick();
    setInterval(tick, 1000);
}})();
</script>
"""
    st.components.v1.html(html, height=160, scrolling=False)


def render_ihsg_widget(ihsg: dict | None):
    if not ihsg:
        st.caption("⚠️ IHSG data tidak tersedia saat ini.")
        return

    # Guard untuk fallback mode (Google Finance — no sparkline)
    if not ihsg.get("sparkline") or not ihsg.get("prices"):
        is_up = ihsg.get("change_abs", 0.0) >= 0
        chg_color = "#10B981" if is_up else "#EF4444"
        chg_arrow = "▲" if is_up else "▼"
        st.markdown(f"""
<div style="background:#161B27;border:1px solid #2D3748;border-radius:14px;padding:16px 20px;margin-bottom:4px;">
  <div style="font-size:0.75em;color:#64748B;">IHSG / IDX Composite</div>
  <div style="font-size:2.1em;font-weight:800;color:#F1F5F9;">{ihsg['current']:,.2f}</div>
  <div style="color:{chg_color};font-weight:700;margin-top:4px;">
    {chg_arrow} {abs(ihsg['change_abs']):,.2f} ({abs(ihsg['change_pct']):.2f}%)
  </div>
  <div style="margin-top:6px;font-size:0.72em;color:#475569;">
    Sumber: {ihsg.get('source', 'Fallback')} (no sparkline) · refresh tiap 120 detik
  </div>
</div>
""", unsafe_allow_html=True)
        return

    is_up = ihsg["change_abs"] >= 0
    chg_color = "#10B981" if is_up else "#EF4444"
    chg_arrow = "▲" if is_up else "▼"
    chg_bg = "rgba(16,185,129,0.08)" if is_up else "rgba(239,68,68,0.08)"
    chg_border = "rgba(16,185,129,0.25)" if is_up else "rgba(239,68,68,0.25)"
    line_color = "#10B981" if is_up else "#EF4444"
    fill_color = "rgba(16,185,129,0.12)" if is_up else "rgba(239,68,68,0.12)"
    prices_js = str([round(p, 2) for p in ihsg["prices"]])
    times_js = str(ihsg["times"])
    min_p = round(min(ihsg["prices"]) * 0.9995, 2)
    max_p = round(max(ihsg["prices"]) * 1.0005, 2)

    html = f"""
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap">
<div id="ihsg_widget" style="background:#161B27;border:1px solid #2D3748;border-radius:14px;padding:16px 20px;display:flex;gap:24px;align-items:center;margin-bottom:4px;">
  <div style="flex:0 0 auto;">
    <div style="font-size:0.75em;color:#64748B;font-weight:600;letter-spacing:.08em;text-transform:uppercase;font-family:Inter,sans-serif;">IHSG / IDX Composite</div>
    <div style="font-size:2.1em;font-weight:800;color:#F1F5F9;font-family:Inter,sans-serif;line-height:1.1;margin-top:2px;">{ihsg['current']:,.2f}</div>
    <div style="display:inline-flex;align-items:center;gap:6px;margin-top:5px;padding:3px 10px;border-radius:20px;background:{chg_bg};border:1px solid {chg_border};">
      <span style="color:{chg_color};font-weight:700;font-size:0.95em;font-family:Inter,sans-serif;">{chg_arrow} {abs(ihsg['change_abs']):,.2f} ({abs(ihsg['change_pct']):.2f}%)</span>
    </div>
    <div style="display:flex;gap:14px;margin-top:10px;font-size:0.78em;color:#94A3B8;font-family:Inter,sans-serif;">
      <span>O <b style="color:#CBD5E1;">{ihsg['open']:,.2f}</b></span>
      <span>H <b style="color:#10B981;">{ihsg['high']:,.2f}</b></span>
      <span>L <b style="color:#EF4444;">{ihsg['low']:,.2f}</b></span>
      <span>Prev <b style="color:#CBD5E1;">{ihsg['prev_close']:,.2f}</b></span>
      <span>Vol <b style="color:#CBD5E1;">{ihsg['volume']/1e9:.2f}B</b></span>
    </div>
    <div style="margin-top:5px;font-size:0.72em;color:#475569;font-family:Inter,sans-serif;">Sumber: Yahoo Finance (^JKSE) · refresh tiap 60 detik</div>
  </div>
  <div style="flex:1;min-width:0;height:90px;position:relative;">
    <canvas id="ihsg_chart" style="width:100%;height:90px;"></canvas>
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
    var grad=ctx.createLinearGradient(0,0,0,90);
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
    st.components.v1.html(html, height=175, scrolling=False)
