"""Pick of the Day — the landing tab.

Renders the Mega Score ranking computed in app.py before the tabs render
(st.session_state.mega_rows), so a full ranked verdict is visible without
visiting any other tab first.
"""
import datetime

import pandas as pd
import pytz
import streamlit as st

from data.fetchers import safe_float
from data.mega_score import HORIZON_WEIGHTS
from data.scoring import calculate_strategies, sl_tp_levels, position_size_lots

HORIZON_LABEL = {
    "scalping": "⚡ Scalping/Intraday",
    "swing_bsjp": "🌊 Swing/BSJP",
    "long_term": "🏔️ Long Term",
}

_TIER_COLORS = {
    "🟢 SANGAT DIREKOMENDASIKAN": "#10B981",
    "🔵 DIREKOMENDASIKAN": "#3B82F6",
    "🟡 NETRAL / WATCHLIST": "#F59E0B",
    "🔴 HINDARI": "#EF4444",
}

_ALLOC_CAP = {"Aggressive": 0.10, "Moderate": 0.15, "Low Risk": 0.20}


@st.cache_data(ttl=3600)
def compute_track_record(signature, history_rows) -> list[dict]:
    """Forward returns for logged STRONG BUY/BUY signals using yfinance 1y daily
    history: +1/+5/+21 trading-day returns from the first close >= signal date."""
    import pandas as pd
    import yfinance as yf

    rows = []
    for r in history_rows:
        if r.get("signal") not in ("STRONG BUY", "BUY"):
            continue
        price = safe_float(r.get("price"))
        captured_at = r.get("captured_at", "")
        if price <= 0 or not captured_at:
            continue
        try:
            day = pd.Timestamp(captured_at).date()
        except (ValueError, TypeError):
            continue
        rows.append({"ticker": r["ticker"], "day": day, "price": price})

    if not rows:
        return []

    tickers = sorted({r["ticker"] for r in rows})
    history: dict[str, list] = {}
    for t in tickers:
        try:
            df = yf.Ticker(f"{t}.JK").history(period="1y", interval="1d")
            if df.empty:
                continue
            history[t] = [(idx.date(), float(close)) for idx, close in zip(df.index, df["Close"])]
        except Exception:
            continue

    if not history:
        return []

    stats = {1: [], 5: [], 21: []}
    for r in rows:
        closes = history.get(r["ticker"])
        if not closes:
            continue
        entry_idx = None
        for i, (d, _c) in enumerate(closes):
            if d >= r["day"]:
                entry_idx = i
                break
        if entry_idx is None:
            continue
        for offset in (1, 5, 21):
            if entry_idx + offset < len(closes):
                ret = (closes[entry_idx + offset][1] / closes[entry_idx][1] - 1) * 100
                stats[offset].append(ret)

    result = []
    for offset, rets in stats.items():
        if not rets:
            continue
        positive = sum(1 for x in rets if x > 0)
        result.append({
            "Horizon": f"+{offset} trading day(s)",
            "n": len(rets),
            "Hit Rate": f"{positive / len(rets) * 100:.0f}%",
            "Avg Return": f"{sum(rets) / len(rets):+.2f}%",
            "Best": f"{max(rets):+.2f}%",
            "Worst": f"{min(rets):+.2f}%",
        })
    return result


def _why_line(mega: dict, horizon: str) -> str:
    """One-line 'why': top-2 breakdown contributors by weighted contribution.

    Defaulted signals (e.g. news before the News tab fetches) are skipped so the
    line never cites a silent 50 placeholder as a reason."""
    weights = HORIZON_WEIGHTS.get(horizon, HORIZON_WEIGHTS["scalping"])
    defaulted = set(mega.get("defaulted", []))
    contribs = []
    for key, score in mega.get("breakdown", {}).items():
        if key in weights and key not in defaulted:
            contribs.append((key, safe_float(score) * float(weights[key])))
    contribs.sort(key=lambda x: x[1], reverse=True)
    parts = []
    for key, _ in contribs[:2]:
        val = mega["breakdown"][key]
        label = key.replace("_", " ").title()
        parts.append(f"{label} {val:.0f}")
    return " + ".join(parts) if parts else "—"


def _confidence_badge(confidence: float) -> str:
    pct = int(round(confidence * 100))
    if pct >= 80:
        return f"<span class='badge' style='background:rgba(16,185,129,0.15);color:#10B981;'>{pct}% signals</span>"
    if pct >= 50:
        return f"<span class='badge' style='background:rgba(245,158,11,0.15);color:#F59E0B;'>{pct}% signals</span>"
    return f"<span class='badge' style='background:rgba(239,68,68,0.15);color:#EF4444;'>{pct}% signals</span>"


def _filters(rows: list[dict]):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        f_bsjp = st.checkbox("🌙 BSJP only", value=False, key="pick_f_bsjp")
    with c2:
        f_min = st.checkbox("📈 Minervini PASSED only", value=False, key="pick_f_min")
    with c3:
        f_ara = st.checkbox("🚀 Pre-ARA only", value=False, key="pick_f_ara")
    with c4:
        f_trend = st.checkbox("🔥 Trending only", value=False, key="pick_f_trend")

    filtered = []
    for r in rows:
        if f_bsjp and not r.get("has_bsjp"):
            continue
        if f_min and not r.get("has_minervini"):
            continue
        if f_ara and not r.get("has_pre_ara"):
            continue
        if f_trend and not r.get("has_trending"):
            continue
        filtered.append(r)
    return filtered


def _card_view(rows: list[dict], horizon: str, animate: bool = False):
    # Base .pick-card styling lives in ui/components/styles.py (global).
    st.markdown("""
    <style>
    .pick-card-ticker { font-size: 1.15em; font-weight: 800; color: #F8FAFC; }
    .pick-card-meta { font-size: 0.82em; color: #94A3B8; margin-top: 4px; }
    .pick-card-score { font-size: 1.5em; font-weight: 800; }
    </style>
    """, unsafe_allow_html=True)
    if animate:
        # Enter once per session: replaying on every filter rerun would make the
        # list feel sluggish instead of instant (design-eng: repeated interactions
        # stay motionless; first-time views get a light stagger).
        st.markdown("""
        <style>
        .pick-card {
            opacity: 0;
            animation: pickCardIn 300ms cubic-bezier(0.23, 1, 0.32, 1) forwards;
            animation-delay: calc(var(--stagger, 0) * 45ms);
        }
        @keyframes pickCardIn {
            from { opacity: 0; transform: translateY(6px) scale(0.99); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        @media (prefers-reduced-motion: reduce) {
            .pick-card { animation: none; opacity: 1; }
        }
        </style>
        """, unsafe_allow_html=True)
    for i, r in enumerate(rows):
        tier_color = _TIER_COLORS.get(r["Tier"], "#94A3B8")
        st.markdown(f"""
        <div class="pick-card" style="--stagger: {i}">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span class="pick-card-ticker">{r['Ticker']}</span>
                <span class="pick-card-score" style="color:{tier_color}">{r['Mega Score']:.1f}</span>
            </div>
            <div style="color:{tier_color};font-weight:700;font-size:0.9em;">{r['Tier']}</div>
            <div class="pick-card-meta">
                {r['Company']} · IDR {r['Price']:,.0f} · {r['Change %']:+.2f}% · {r['Source']}
            </div>
            <div class="pick-card-meta">Why: {_why_line(r, horizon)} {_confidence_badge(r['confidence'])}</div>
        </div>
        """, unsafe_allow_html=True)


def _strategy_detail(r: dict, total_portfolio_value: float):
    price = safe_float(r["Price"])
    base_portfolio = total_portfolio_value if total_portfolio_value > 0 else 100_000_000.0
    hist_row = r.get("hist_row_obj", {})

    levels = sl_tp_levels(price, hist_row)
    st.markdown(
        f"**SL/TP (Tab 2 logic):** SL `IDR {levels['sl']:,.0f}` · TP `IDR {levels['tp']:,.0f}` · "
        f"R/R `{((levels['tp'] - price) / max(1.0, price - levels['sl'])):.2f}x`"
    )

    strategies = calculate_strategies(price, safe_float(r["Mega Score"]), r.get("Signal", "HOLD"))
    for tier, s in strategies.items():
        lots = position_size_lots(s["entry"], s["sl"], base_portfolio, _ALLOC_CAP.get(tier, 0.10))
        st.markdown(
            f"- **{tier}**: entry `IDR {s['entry']:,.0f}` · TP `IDR {s['target']:,.0f}` · "
            f"SL `IDR {s['sl']:,.0f}` · R/R `{s['rr']}x` · size `{s['size']}` · "
            f"≈ **{lots} lot** @ 1% risk"
        )


def _bestpick_detail(r: dict, total_portfolio_value: float):
    """Render the researched Best-Pick conviction verdict (Engine E)."""
    bp = r.get("BestPick")
    if not bp:
        return
    st.markdown("---")
    st.markdown(
        f"**🎯 Best Pick — {bp['tier']}** `Score {bp['score']:.1f}` "
        f"· Confidence `{bp['confidence']*100:.0f}%`"
    )
    if bp.get("warnings"):
        for w in bp["warnings"]:
            st.caption(f"⚠️ {w}")

    # Breakdown mini-table
    bd = bp.get("breakdown", {})
    if bd:
        parts = [f"{k.replace('_', ' ').title()} {v:.0f}" for k, v in bd.items()]
        st.caption("Factor breakdown: " + " · ".join(parts))

    # Levels per tier
    levels = bp.get("levels", {})
    if levels:
        for tname in ("Aggressive", "Moderat", "Low Risk"):
            lv = levels.get(tname)
            if not lv:
                continue
            lots = bp.get("sizing", {}).get(tname, 0)
            rr = lv.get("rr", 0)
            risk_pct = lv.get("risk_pct", 0)
            st.markdown(
                f"- **{tname}**: entry `IDR {lv['entry']:,.0f}` · TP `IDR {lv['tp']:,.0f}` · "
                f"SL `IDR {lv['sl']:,.0f}` · R/R `{rr}x` · risk `{risk_pct:.1f}%` · "
                f"≈ **{lots} lot**"
            )

    # Rationale
    rationale = bp.get("rationale", [])
    if rationale:
        st.caption("Why: " + " · ".join(rationale[:5]))


def _render_pre_market_watch():
    """🔭 Pre-Market Watch — today's heuristic predictions from SQLite.

    Read-only: the 08:40 WIB cron job (`bot.pre_market_predictor`) computes and
    persists these rows; this expander never recomputes or fetches news.
    """
    from repositories.sqlite_repository import sqlite_repository

    today = datetime.datetime.now(pytz.timezone("Asia/Jakarta")).date().isoformat()
    preds = sqlite_repository.get_premarket_predictions(today)

    with st.expander("🔭 Pre-Market Watch — kandidat gap-up (heuristic)", expanded=False):
        if not preds:
            run_info = sqlite_repository.get_premarket_run(today)
            if run_info:
                try:
                    ran_disp = (
                        datetime.datetime.fromisoformat(run_info["ran_at"]).strftime("%d %b %H:%M")
                        + " WIB"
                    )
                except Exception:
                    ran_disp = str(run_info["ran_at"])
                st.caption(
                    f"✅ Job sudah jalan **{ran_disp}** — tidak ada kandidat hari ini "
                    "(semua skor < 20). Data BSJP/EOD terisi otomatis setelah job 14:30/16:00 jalan."
                )
            else:
                st.caption(
                    "Belum ada prediksi hari ini. Job **08:40 WIB** (`bot.pre_market_predictor`) "
                    "mengisi daftar ini otomatis setiap pagi."
                )
            return
        df = pd.DataFrame([
            {
                "Ticker": p["ticker"],
                "Score": p["score"],
                "Tier": p["tier"],
                "Reasons": " · ".join(p["reasons"]),
            }
            for p in preds
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(
            "Skor heuristic pra-buka: ARA streak + BSJP kemarin + berita semalam + "
            "kalender hari ini, × multiplier pasar. Tier: WATCH CLOSELY ≥60 · "
            "ON RADAR ≥35 · BELOW RADAR ≥20 (sinyal lemah, catatan saja). "
            "Bukan prediksi/verdict final."
        )


def render_tab_pick_of_the_day(total_portfolio_value=0.0):
    _render_pre_market_watch()

    h1, h2 = st.columns([5, 1])
    with h1:
        st.markdown("### 🏆 Pick of the Day — Unified Mega Score")
        st.caption(
            "Satu verdict beli terpadu: Mega Score + Tier menggabungkan intraday, orderbook, "
            "trending, BSJP, Minervini, dan Pre-ARA. "
            "Semua sinyal dihitung otomatis — tidak perlu membuka tab lain dulu."
        )
    with h2:
        if st.button(
            "🔄 Hitung Ulang",
            use_container_width=True,
            help="Paksa hitung ulang Mega Score dari data terbaru.",
            key="pick_recompute",
        ):
            st.session_state.mega_recompute = int(st.session_state.get("mega_recompute", 0)) + 1
            st.rerun()

    st.caption(
        "💡 Sentimen berita ikut dihitung di Mega Score setelah tab **📰 News Signals** "
        "selesai fetch (cache 5 menit) — sebelum itu netral (50), agar landing tetap cepat."
    )

    if "pick_horizon" not in st.session_state:
        st.session_state.pick_horizon = "scalping"

    horizon = st.radio(
        "Horizon",
        list(HORIZON_LABEL.keys()),
        horizontal=True,
        format_func=lambda h: HORIZON_LABEL[h],
        key="pick_horizon",
    )

    mega_rows = st.session_state.get("mega_rows", {})
    rows = mega_rows.get(horizon, []) if isinstance(mega_rows, dict) else []

    if not rows:
        st.info("Belum ada data. Klik **🔄 Refresh Live Feed (Multi)** untuk mengisi Pick of the Day.")
        return

    rows = _filters(rows)
    rows = sorted(rows, key=lambda r: r["Mega Score"], reverse=True)

    st.markdown(f"**{len(rows)} kandidat** · horizon {HORIZON_LABEL[horizon]}")

    card_view = st.checkbox("📱 Card View (Mobile)", value=False, key="pick_card_view")
    if card_view:
        animate = not st.session_state.get("pick_card_animated", False)
        st.session_state.pick_card_animated = True
        _card_view(rows, horizon, animate=animate)
        return

    df = pd.DataFrame([{k: r[k] for k in (
        "Ticker", "Company", "Mega Score", "Tier", "Price", "Change %",
        "Source", "confidence", "Signal"
    )} for r in rows])
    df = df.rename(columns={"confidence": "Signals"})
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Mega Score": st.column_config.ProgressColumn(
                "Mega Score", min_value=0, max_value=100, format="%.1f"),
            "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
            "Change %": st.column_config.NumberColumn("Chg%", format="%+.2f%%"),
            "Source": st.column_config.TextColumn("Source"),
            "Signals": st.column_config.ProgressColumn(
                "Signals", min_value=0, max_value=100, format="%.0f%%"),
        },
    )

    st.markdown("---")
    st.markdown("#### 📋 Detail Entry per Kandidat")
    for r in rows[:10]:
        tier_color = _TIER_COLORS.get(r["Tier"], "#94A3B8")
        with st.expander(
            f"{r['Ticker']} — {r['Mega Score']:.1f} · {r['Tier']} · Why: {_why_line(r, horizon)}",
            expanded=False,
        ):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Price", f"IDR {r['Price']:,.0f}", f"{r['Change %']:+.2f}%")
            with c2:
                st.markdown(
                    f"<div style='color:{tier_color};font-weight:800;font-size:1.1em;'>{r['Tier']}</div>"
                    f"<div style='color:#94A3B8;font-size:0.85em;'>{_why_line(r, horizon)}</div>",
                    unsafe_allow_html=True,
                )
            with c3:
                st.markdown(_confidence_badge(r["confidence"]), unsafe_allow_html=True)
                st.caption(f"Source: {r['Source']} · Signals: {r.get('Signal', '—')}")

            flags = []
            if r.get("has_bsjp"):
                flags.append("🌙 BSJP")
            if r.get("has_minervini"):
                flags.append("📈 Minervini PASSED")
            if r.get("has_pre_ara"):
                flags.append("🚀 Pre-ARA")
            if r.get("has_trending"):
                flags.append("🔥 Trending")
            if r.get("has_news"):
                flags.append("📰 News")
            if flags:
                st.caption("Sub-signal flags: " + " · ".join(flags))
            if r.get("defaulted"):
                st.caption(f"⚠️ Signal defaulted to 50: {', '.join(r['defaulted'])}")

            _strategy_detail(r, total_portfolio_value)
            _bestpick_detail(r, total_portfolio_value)

    # ── Track Record (logged signals → yfinance forward returns) ──────────
    with st.expander("📈 Track Record — logged STRONG BUY/BUY signals", expanded=False):
        from repositories.sqlite_repository import sqlite_repository

        history_rows = sqlite_repository.get_scan_history_all(
            signal_filter=("STRONG BUY", "BUY"), limit=1000
        )
        if not history_rows:
            st.info(
                "⏳ **Collecting data** — sinyal STRONG BUY/BUY dicatat otomatis "
                "setiap refresh feed. Track record forward returns akan muncul "
                "setelah beberapa hari logging."
            )
        else:
            st.caption(
                f"{len(history_rows)} sinyal STRONG BUY/BUY tercatat. "
                "Menghitung forward returns dari yfinance (period 1y)..."
            )
            with st.spinner("Menghitung forward returns..."):
                signature = tuple(sorted(
                    (r["ticker"], r["captured_at"][:10], r["signal"]) for r in history_rows
                ))
                track = compute_track_record(signature, history_rows)
            if track:
                st.dataframe(pd.DataFrame(track), use_container_width=True, hide_index=True)
                st.caption(
                    "Forward returns dihitung dari close entry ke close "
                    "+1/+5/+21 hari trading berikutnya (yfinance, period 1y)."
                )
            else:
                st.info("⏳ Belum cukup data untuk menghitung forward returns.")
