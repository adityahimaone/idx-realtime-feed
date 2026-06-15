import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import time
from datetime import datetime
from data.fetchers import fetch_news_for_tickers
from data.news import (
    fetch_stockbit_news_headlines,
    fetch_macro_news_yfinance,
    fetch_cnbc_rss,
    fetch_antara_rss,
    fetch_kontan_scrape,
    fetch_bisnis_scrape,
    fetch_idx_disclosure_scrape,
    detect_macro_themes,
    build_ticker_impact_table,
    build_ticker_impact_table_v2,
    build_per_ticker_sentiment,
)

WIB = __import__("pytz").timezone("Asia/Jakarta")

# ---------------------------------------------------------------------------
# Source definitions — one place for all 6 sources
# ---------------------------------------------------------------------------
SOURCE_LABEL = {
    "stockbit":         "📡 Stockbit",
    "cnbc_indonesia":   "📰 CNBC Indonesia",
    "kontan":           "📋 Kontan",
    "antara_ekonomi":   "🌐 Antara Ekonomi",
    "bisnis_indonesia": "📉 Bisnis Indonesia",
    "idx_disclosure":   "🏛️ IDX Disclosure",
}
SOURCE_SORT = {
    "stockbit": 1, "cnbc_indonesia": 2, "antara_ekonomi": 3,
    "kontan": 4, "bisnis_indonesia": 5, "idx_disclosure": 6,
}
# Sources that are known-dead (no public feed) — shown as unavailable in UI
DEAD_SOURCES = {"bisnis_indonesia", "idx_disclosure"}

SOURCES = [
    ("stockbit",         fetch_stockbit_news_headlines),
    ("cnbc_indonesia",   fetch_cnbc_rss),
    ("antara_ekonomi",   fetch_antara_rss),
    ("kontan",           fetch_kontan_scrape),
    ("bisnis_indonesia", fetch_bisnis_scrape),
    ("idx_disclosure",   fetch_idx_disclosure_scrape),
]


def _classify_sentiment(title: str) -> str:
    """Rule-based sentiment from Indonesian/English news headlines."""
    title_l = title.lower()
    pos_kw = ["naik", "tumbuh", "laba", "positif", "dividen", "akuisisi",
              "ekspansi", "profit", "growth", "rise", "gain", "upgrade",
              "bullish", "lunasi", "raih", "rekor", "surplus", "bangkit"]
    neg_kw = ["turun", "rugi", "gagal", "krisis", "utang", "debt", "loss",
              "downgrade", "bearish", "crash", "tunda", "henti", "anjlok",
              "merugi", "default", "sanksi", "protes", "ancam", "pailit"]
    pos_hit = sum(1 for kw in pos_kw if kw in title_l)
    neg_hit = sum(1 for kw in neg_kw if kw in title_l)
    if pos_hit > neg_hit:
        return "🟢 Positif"
    elif neg_hit > pos_hit:
        return "🔴 Negatif"
    return "🟡 Netral"


def _fetch_all_news() -> dict:
    """Fetch all news sources. Return dict of {source_tag: [articles]}."""
    results = {}
    for tag, fetcher_fn in SOURCES:
        try:
            results[tag] = fetcher_fn()
        except Exception as e:
            st.error(f"{SOURCE_LABEL.get(tag, tag)} fetch error: {e}")
            results[tag] = []
    return results


def _build_source_summary_html(all_news: dict, last_fetch_dt: str) -> str:
    """Build HTML for source-availability badges + article counts."""
    parts = []
    for tag in [s[0] for s in SOURCES]:
        articles = all_news.get(tag, []) if all_news else []
        count = len(articles) if articles else 0
        label = SOURCE_LABEL.get(tag, tag)
        if tag in DEAD_SOURCES:
            # Dead source — dimmed badge with warning colour
            parts.append(
                f'<span style="background:rgba(239,68,68,0.10);color:#F87171;'
                f'padding:2px 10px;border-radius:12px;font-size:0.82em;'
                f'font-weight:600;">{label} &times; unavailable</span>'
            )
        elif count > 0:
            parts.append(
                f'<span style="background:rgba(56,189,248,0.12);color:#38BDF8;'
                f'padding:2px 10px;border-radius:12px;font-size:0.82em;'
                f'font-weight:600;">{label}: {count}</span>'
            )
        else:
            # Fetched but empty — dimmer badge
            parts.append(
                f'<span style="background:rgba(100,116,139,0.10);color:#8899A6;'
                f'padding:2px 10px;border-radius:12px;font-size:0.82em;">'
                f'{label}: 0</span>'
            )

    badges = " &nbsp;&middot;&nbsp; ".join(parts)
    return (
        f"<div style='margin:6px 0 12px 0;'>{badges}"
        f" &nbsp;🕐 {last_fetch_dt}</div>"
    )


def _build_combined_df(all_news: dict) -> pd.DataFrame:
    """Build a unified DataFrame across all sources."""
    known_macros = {"IHSG", "BI", "LQ45", "IDX", "COMPOSITE"}
    rows = []
    for source_tag, articles in all_news.items():
        if not articles:
            continue
        for art in articles:
            topics = art.get("topics", []) or []
            emiten = sorted(
                t for t in topics
                if len(t) == 4 and t.isalpha() and t.upper() not in known_macros
            )
            macro = sorted(
                t for t in topics
                if t.upper() in known_macros or len(t) > 4
            )
            sentiment = _classify_sentiment(art["title"])
            rows.append({
                "Sumber": SOURCE_SORT.get(source_tag, 99),
                "Sumber Label": SOURCE_LABEL.get(source_tag, source_tag.upper()),
                "Waktu": art.get("created_display", ""),
                "Judul Berita": art["title"],
                "Emiten": ", ".join(emiten) if emiten else "-",
                "Makro/Topik": ", ".join(macro) if macro else "-",
                "Sentimen": sentiment,
                "_source": source_tag,
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values(["Sumber Label", "Waktu"], ascending=[True, False])
    return df


def render_tab8(scored_list, ticker_df):
    """Render Tab 8: News-Based Signals with multi-source aggregation."""
    st.markdown("### 📰 News-Based Signals")
    st.caption(
        "6 sumber berita: Stockbit, CNBC Indonesia, Kontan, Antara Ekonomi, "
        "Bisnis Indonesia, IDX Disclosure — "
        "diklasifikasikan per sentimen & direlasikan ke emiten "
        "via macro theme detection."
    )

    # ================================================================
    # 1. MULTI-SOURCE NEWS FEED
    # ================================================================
    st.markdown("#### 📡 1. News Feeds")

    # Controls
    cc1, cc2, cc3 = st.columns([1, 1, 1])
    with cc1:
        fetch_btn = st.button("🔄 Fetch All Sources", use_container_width=True, type="primary")
    with cc2:
        auto_interval = st.selectbox(
            "Auto-refresh",
            options=[0, 1, 2, 5, 10],
            format_func=lambda x: "Off" if x == 0 else f"Every {x} min",
            index=0,
            key="news_interval",
        )
    with cc3:
        last_fetch_el = st.empty()

    # Source status badges
    status_row = st.empty()

    # Cache
    if "news_cache" not in st.session_state:
        st.session_state.news_cache = {"data": None, "ts": 0}

    now_ts = time.time()
    cache = st.session_state.news_cache
    stale = (
        fetch_btn
        or cache["data"] is None
        or (auto_interval > 0 and now_ts - cache["ts"] >= auto_interval * 60)
    )

    if stale:
        with st.spinner("📡 Syncing all 6 news sources..."):
            all_news = _fetch_all_news()
            cache["data"] = all_news
            cache["ts"] = now_ts

    all_news = cache["data"]
    last_fetch_dt = (
        datetime.fromtimestamp(cache["ts"], tz=WIB).strftime("%H:%M:%S WIB")
        if cache["ts"] > 0 else "-"
    )

    # Source badges
    if all_news is not None:
        status_row.markdown(
            _build_source_summary_html(all_news, last_fetch_dt),
            unsafe_allow_html=True,
        )

    # --- Source availability note for dead sources ---
    if all_news is not None:
        dead_with_content = [SOURCE_LABEL[t] for t in DEAD_SOURCES
                             if t in all_news and all_news[t]]
        dead_without = [SOURCE_LABEL[t] for t in DEAD_SOURCES
                        if t in all_news and not all_news[t]]
        if dead_without:
            src_list = ", ".join(dead_without)
            st.caption(
                f"⚠️ {src_list} tidak memiliki RSS publik — "
                "menampilkan 0 berita. "
                "Gunakan filter sumber jika ingin menyembunyikannya."
            )

    if auto_interval > 0 and cache["ts"] > 0:
        _inject_news_countdown(int((cache["ts"] + auto_interval * 60) * 1000))

    if all_news and any(len(v) > 0 for v in all_news.values()):
        combined_df = _build_combined_df(all_news)

        # Filters
        all_emiten = sorted(set(
            e for art_list in all_news.values() if art_list
            for art in art_list
            for e in (art.get("topics") or [])
            if len(e) == 4 and e.isalpha() and e.upper() not in {"IHSG", "BI", "LQ45", "IDX", "COMPOSITE"}
        ))
        all_sources = sorted(set(
            SOURCE_LABEL.get(t, t) for t in all_news.keys()
            if len(all_news.get(t, []) or []) > 0
        ))
        f1, f2, f3 = st.columns([1, 1, 1.5])
        with f1:
            filter_source = st.multiselect("Filter Sumber", all_sources, default=list(all_sources), key="ns_source")
        with f2:
            filter_emiten = st.multiselect("Filter Emiten", all_emiten, default=[], key="ns_emiten")
        with f3:
            filter_sent = st.multiselect(
                "Filter Sentimen",
                ["🟢 Positif", "🔴 Negatif", "🟡 Netral"],
                default=[],
                key="ns_sent",
            )

        filtered = combined_df.copy()
        if filter_source:
            filtered = filtered[filtered["Sumber Label"].isin(filter_source)]
        if filter_emiten:
            filtered = filtered[filtered["Emiten"].apply(
                lambda x: any(e in x for e in filter_emiten)
            )]
        if filter_sent:
            filtered = filtered[filtered["Sentimen"].isin(filter_sent)]

        display_cols = ["Sumber Label", "Waktu", "Judul Berita", "Emiten", "Makro/Topik", "Sentimen"]
        col_config = {
            "Sumber Label": st.column_config.TextColumn("Sumber", width="small"),
            "Waktu":        st.column_config.TextColumn("Waktu", width="small"),
            "Judul Berita": st.column_config.TextColumn("Judul Berita", width="large"),
            "Emiten":       st.column_config.TextColumn("Emiten", width="small"),
            "Makro/Topik":  st.column_config.TextColumn("Makro", width="medium"),
            "Sentimen":     st.column_config.TextColumn("Sentimen", width="small"),
        }

        st.dataframe(
            filtered[display_cols],
            column_config=col_config,
            use_container_width=True,
            hide_index=True,
        )
        if len(filtered) == 0:
            st.warning("Filters are empty! Showed nothing.")
            st.write("Raw data sample:", combined_df.head(5))
        st.caption(f"Menampilkan {len(filtered)} dari {len(combined_df)} berita")
    else:
        st.info("Belum ada data. Klik 'Fetch All Sources'.")

    st.markdown("---")

    # ================================================================
    # Aggregate all articles for macro detection
    # ================================================================
    all_articles = []
    if all_news:
        for art_list in all_news.values():
            if art_list:
                all_articles.extend(art_list)

    # ================================================================
    # 2. MACRO NARRATIVE DETECTION
    # ================================================================
    st.markdown("#### 🎯 2. Macro Narrative Detection")
    with st.spinner("📡 Fetching macro news (yfinance)..."):
        macro_articles = fetch_macro_news_yfinance()
    all_articles = all_articles + macro_articles
    triggered = []

    if all_articles:
        with st.expander("📄 Raw macro headlines", expanded=False):
            for art in all_articles[:20]:
                src_map = {
                    "^JKSE": "IHSG", "IDR=X": "USD/IDR",
                    "GC=F": "Gold", "CL=F": "Crude Oil",
                    "stockbit": "Stockbit",
                    "cnbc_indonesia": "CNBC",
                    "antara_ekonomi": "Antara",
                    "kontan": "Kontan",
                    "bisnis_indonesia": "Bisnis",
                    "idx_disclosure": "IDX",
                }
                src_label = src_map.get(art.get("source", ""), art.get("source", "").upper())
                link = art.get("link", "")
                if link:
                    st.markdown(f"- **[{src_label}]** [{art['title']}]({link})")
                else:
                    st.markdown(f"- **[{src_label}]** {art['title']}")

        triggered = detect_macro_themes(all_articles)

    if triggered:
        for theme in triggered:
            impact_color = (
                "#10B981" if theme["impact"] == "positive"
                else "#EF4444" if theme["impact"] == "negative"
                else "#F59E0B"
            )
            impact_label = {
                "positive": "POSITIVE NARRATIVE",
                "negative": "NEGATIVE NARRATIVE",
                "mixed": "MIXED NARRATIVE",
            }.get(theme["impact"], theme["impact"].upper())
            pos_t = ", ".join(theme["positive_tickers"]) or "-"
            neg_t = ", ".join(theme["negative_tickers"]) or "-"
            headlines_li = "".join(
                f'<li><a href="{a.get("link","#")}" target="_blank" '
                f'style="color:#38BDF8;text-decoration:none;">{a["title"]}</a></li>'
                if a.get("link") else
                f"<li>{a['title']}</li>"
                for a in theme["articles"]
            )
            card = (
                f'<div class="rec-card" style="border-left:5px solid {impact_color};margin-bottom:14px;">'
                f'<div class="card-header">'
                f'<span style="font-size:1.3em;font-weight:800;color:#F8FAFC;">{theme["icon"]} {theme["label"]}</span>'
                f'<div class="action-badge" style="background:{impact_color}22;color:{impact_color};border:1px solid {impact_color}66;">{impact_label}</div>'
                f'</div>'
                f'<div class="notes-section" style="border-left-color:{impact_color};"><b>Narasi:</b> {theme["narrative"]}</div>'
                f'<div class="metric-row">'
                f'<div class="metric-box"><div class="metric-label">🟢 Positif</div><div class="metric-value" style="color:#10B981;">{pos_t}</div></div>'
                f'<div class="metric-box"><div class="metric-label">🔴 Negatif</div><div class="metric-value" style="color:#EF4444;">{neg_t}</div></div>'
                f'</div>'
                f'<div style="margin-top:10px;font-size:0.85em;color:#94A3B8;"><b>Headlines pendukung:</b>'
                f'<ul style="margin:4px 0 0 16px;">{headlines_li}</ul></div>'
                f'</div>'
            )
            st.markdown(card, unsafe_allow_html=True)
    else:
        st.info("✅ Tidak ada narasi makro signifikan yang terdeteksi saat ini.")

    st.markdown("---")

    # ================================================================
    # 3. TICKER IMPACT TABLE (v2 — macro + direct mention)
    # ================================================================
    st.markdown("#### 📊 3. Ticker Impact Analysis (Watchlist)")
    st.caption(
        "Dua layer sinyal: (1) macro theme impact dari MACRO_THEMES, "
        "(2) direct ticker mention di headlines semua sumber."
    )
    watchlist = [s["Ticker"] for s in scored_list] if scored_list else []
    impact_rows = build_ticker_impact_table_v2(
        triggered if all_articles else [],
        all_articles,
        watchlist,
    )

    if impact_rows:
        pos = [r for r in impact_rows if r["Net Score"] > 0]
        neg = [r for r in impact_rows if r["Net Score"] < 0]
        mix = [r for r in impact_rows if r["Net Score"] == 0]

        display_cols_pos = ["Ticker", "Signal", "Macro +", "Mention +"]
        display_cols_neg = ["Ticker", "Signal", "Macro -", "Mention -"]
        display_cols_mix = ["Ticker", "Signal", "Macro +", "Macro -", "Mention +", "Mention -"]

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"##### 🟢 Positif ({len(pos)})")
            if pos:
                st.dataframe(
                    pd.DataFrame(pos)[display_cols_pos],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("—")
        with c2:
            st.markdown(f"##### 🔴 Negatif ({len(neg)})")
            if neg:
                st.dataframe(
                    pd.DataFrame(neg)[display_cols_neg],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("—")
        if mix:
            st.markdown(f"##### 🟡 Mixed ({len(mix)})")
            st.dataframe(
                pd.DataFrame(mix)[display_cols_mix],
                use_container_width=True, hide_index=True,
            )

        # Mention detail expander for top tickers
        mention_detail = [r for r in impact_rows if r["_mention_pos_detail"] or r["_mention_neg_detail"]]
        if mention_detail:
            with st.expander("🔍 Detail Direct Mention per Ticker", expanded=False):
                for r in mention_detail[:10]:
                    st.markdown(f"**{r['Ticker']}** {r['Signal']}")
                    if r["_mention_pos_detail"]:
                        for h in r["_mention_pos_detail"][:3]:
                            st.markdown(f"  🟢 {h}")
                    if r["_mention_neg_detail"]:
                        for h in r["_mention_neg_detail"][:3]:
                            st.markdown(f"  🔴 {h}")
    else:
        st.info("Watchlist tidak punya ticker terdampak narasi makro atau direct mention.")

    st.markdown("---")

    # ================================================================
    # 4. PER-TICKER SENTIMENT (yfinance + multi-source)
    # ================================================================
    st.markdown("#### 📋 4. Per-Ticker News Sentiment")
    st.caption(
        "Combined: yFinance sentiment score + multi-source mention score "
        "(Stockbit, CNBC, Antara, Kontan). Sorted by combined score."
    )

    if scored_list:
        tickers = [s["Ticker"] for s in scored_list]
        with st.spinner("Fetching yfinance + multi-source news per ticker..."):
            yf_data = fetch_news_for_tickers(tickers)

        rows = build_per_ticker_sentiment(all_articles, yf_data, tickers)

        if rows:
            display_cols = [
                "Ticker", "Sentimen", "Combined Score",
                "yFinance Headlines", "Multi-Source Mentions",
                "Sumber Berita", "Latest (yFinance)",
            ]
            ndf = pd.DataFrame(rows)[display_cols]
            st.dataframe(
                ndf,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Combined Score":        st.column_config.NumberColumn("Score", format="%+d"),
                    "yFinance Headlines":    st.column_config.NumberColumn("yF News", format="%d"),
                    "Multi-Source Mentions": st.column_config.NumberColumn("Multi-Src", format="%d"),
                    "Sumber Berita":         st.column_config.TextColumn("Sumber", width="small"),
                    "Latest (yFinance)":     st.column_config.TextColumn("Latest Headline", width="large"),
                },
            )

            # Inline multi-source headlines per ticker
            has_mn = [r for r in rows if r["_mn_headlines"]]
            if has_mn:
                with st.expander("📰 Multi-Source Headlines per Ticker", expanded=False):
                    for r in has_mn[:15]:
                        st.markdown(f"**{r['Ticker']}** — {r['Sentimen']}")
                        for h in r["_mn_headlines"]:
                            src = SOURCE_LABEL.get(h["source"], h["source"].upper())
                            link = h.get("link", "")
                            title = h["title"]
                            if link:
                                st.markdown(f"  - [{src}] [{title}]({link})")
                            else:
                                st.markdown(f"  - [{src}] {title}")
        else:
            st.info("No news data found for current watchlist.")
    else:
        st.info("Refresh the live feed to analyze news.")


def _inject_news_countdown(next_ms: int):
    """JS countdown for auto-refresh interval."""
    html = f"""<div style="background:rgba(56,189,248,0.1);border:1px solid rgba(56,189,248,0.25);
padding:6px 12px;border-radius:6px;color:#38BDF8;font-size:0.82em;font-weight:600;display:inline-block;">
⏳ News refresh in: <span id="news_cd_span">--</span>
</div>
<script>
(function(){{var t=setInterval(function(){{
var d=Math.max(0,Math.floor(({next_ms}-Date.now())/1000));
var s=document.getElementById("news_cd_span");
if(s)s.textContent=Math.floor(d/60)+"m "+(d%60)+"s";
if(d<=0){{clearInterval(t);if(s)s.textContent="0m 0s";
var l=window.location;try{{if(window.parent&&window.parent.location)l=window.parent.location;}}catch(e){{}}
l.reload();}}
}},1000);}})();
</script>"""
    components.html(html, height=36)
