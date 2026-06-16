import streamlit as st
import yfinance as yf
from curl_cffi import requests as requests_cf
from core.logger import logger

# ---------------------------------------------------------------------------
# MACRO THEME DEFINITIONS & TICKER CORRELATION MAP
# ---------------------------------------------------------------------------
MACRO_THEMES = {
    "fed_rate_hike": {
        "label": "The Fed Naikkan Suku Bunga",
        "icon": "🏦",
        "keywords": ["fed rate", "federal reserve", "rate hike", "suku bunga naik", "interest rate hike", "hawkish fed", "fomc hike"],
        "impact": "negative",
        "narrative": "Kenaikan suku bunga Fed → dollar menguat, capital outflow dari emerging market → tekanan di saham perbankan, properti, dan konsumer.",
        "positive_tickers": [],
        "negative_tickers": ["BBCA", "BBRI", "BMRI", "BBNI", "BSDE", "SMRA", "CTRA", "ASRI", "LPKR", "UNVR", "ICBP", "MYOR"],
    },
    "fed_rate_cut": {
        "label": "The Fed Pangkas Suku Bunga",
        "icon": "📉",
        "keywords": ["fed rate cut", "rate cut", "dovish fed", "suku bunga turun", "interest rate cut", "fomc cut", "fed pivot"],
        "impact": "positive",
        "narrative": "Pemotongan suku bunga Fed → dollar melemah, capital inflow ke emerging market → positif untuk perbankan, properti, konsumer.",
        "negative_tickers": [],
        "positive_tickers": ["BBCA", "BBRI", "BMRI", "BBNI", "BSDE", "SMRA", "CTRA", "ASRI", "UNVR", "ICBP", "MYOR"],
    },
    "gold_up": {
        "label": "Harga Emas Naik",
        "icon": "🥇",
        "keywords": ["gold rise", "gold price up", "emas naik", "harga emas melonjak", "gold rally", "xau naik", "emas menguat"],
        "impact": "positive",
        "narrative": "Harga emas naik → emiten tambang emas dan komoditas logam mulia diuntungkan.",
        "negative_tickers": [],
        "positive_tickers": ["ANTM", "EMAS", "ARCI", "MDKA", "BRMS", "PSAB"],
    },
    "gold_down": {
        "label": "Harga Emas Turun",
        "icon": "📉",
        "keywords": ["gold fall", "gold price down", "emas turun", "harga emas anjlok", "gold drops", "xau turun", "emas melemah"],
        "impact": "negative",
        "narrative": "Harga emas turun → emiten tambang emas dan logam mulia tertekan.",
        "negative_tickers": ["ANTM", "EMAS", "ARCI", "MDKA", "BRMS", "PSAB"],
        "positive_tickers": [],
    },
    "coal_up": {
        "label": "Harga Batu Bara Naik",
        "icon": "⚫",
        "keywords": ["coal price up", "batu bara naik", "harga batu bara melonjak", "coal rally", "thermal coal up"],
        "impact": "positive",
        "narrative": "Harga batu bara naik → emiten produsen batu bara diuntungkan secara langsung.",
        "negative_tickers": [],
        "positive_tickers": ["ADRO", "PTBA", "ITMG", "HRUM", "BSSR", "INDY", "PTRO", "DEWA"],
    },
    "coal_down": {
        "label": "Harga Batu Bara Turun",
        "icon": "📉",
        "keywords": ["coal price down", "batu bara turun", "harga batu bara anjlok", "coal drops", "thermal coal down"],
        "impact": "negative",
        "narrative": "Harga batu bara turun → emiten batu bara tertekan, margin ekspor menyusut.",
        "negative_tickers": ["ADRO", "PTBA", "ITMG", "HRUM", "BSSR", "INDY", "PTRO", "DEWA"],
        "positive_tickers": [],
    },
    "cpo_up": {
        "label": "Harga CPO/Sawit Naik",
        "icon": "🌴",
        "keywords": ["cpo price up", "palm oil up", "sawit naik", "harga cpo naik", "crude palm oil rise"],
        "impact": "positive",
        "narrative": "Harga CPO naik → emiten perkebunan sawit dan hilir kelapa sawit diuntungkan.",
        "negative_tickers": [],
        "positive_tickers": ["AALI", "SIMP", "LSIP", "SSMS", "TBLA", "TAPG", "MGRO"],
    },
    "cpo_down": {
        "label": "Harga CPO/Sawit Turun",
        "icon": "📉",
        "keywords": ["cpo price down", "palm oil down", "sawit turun", "harga cpo turun", "crude palm oil falls"],
        "impact": "negative",
        "narrative": "Harga CPO turun → emiten sawit tertekan, revenue ekspor berkurang.",
        "negative_tickers": ["AALI", "SIMP", "LSIP", "SSMS", "TBLA", "TAPG", "MGRO"],
        "positive_tickers": [],
    },
    "rupiah_weak": {
        "label": "Rupiah Melemah",
        "icon": "💸",
        "keywords": ["rupiah melemah", "kurs dolar naik", "idr weakens", "usd/idr naik", "rupiah depreciate", "nilai tukar melemah"],
        "impact": "mixed",
        "narrative": "Rupiah melemah → eksportir diuntungkan; importir dan saham berbiaya impor tinggi tertekan.",
        "negative_tickers": ["UNVR", "ICBP", "MYOR", "INDF", "KLBF", "SIDO"],
        "positive_tickers": ["ADRO", "PTBA", "ITMG", "ANTM", "AALI", "SIMP"],
    },
    "rupiah_strong": {
        "label": "Rupiah Menguat",
        "icon": "💪",
        "keywords": ["rupiah menguat", "kurs dolar turun", "idr strengthens", "usd/idr turun", "rupiah appreciate"],
        "impact": "mixed",
        "narrative": "Rupiah menguat → importir diuntungkan; eksportir komoditas sedikit tertekan.",
        "negative_tickers": ["ADRO", "PTBA", "ITMG"],
        "positive_tickers": ["UNVR", "ICBP", "MYOR", "INDF", "KLBF", "SIDO", "BBCA", "BBRI"],
    },
    "oil_up": {
        "label": "Harga Minyak Naik",
        "icon": "🛢️",
        "keywords": ["oil price up", "crude oil rise", "minyak naik", "brent naik", "wti naik", "harga minyak melonjak"],
        "impact": "mixed",
        "narrative": "Minyak naik → emiten energi/migas diuntungkan; semen dan kimia tertekan.",
        "negative_tickers": ["SMGR", "INTP", "TPIA"],
        "positive_tickers": ["MEDC", "ENRG", "ELSA", "PGAS", "RUIS"],
    },
    "inflation_high": {
        "label": "Inflasi Tinggi / CPI Melonjak",
        "icon": "🔥",
        "keywords": ["inflasi tinggi", "cpi naik", "inflation high", "inflation surge", "harga barang naik", "cost of living rise"],
        "impact": "negative",
        "narrative": "Inflasi tinggi → daya beli tertekan, Bank Indonesia cenderung naikkan suku bunga.",
        "negative_tickers": ["UNVR", "ICBP", "MYOR", "INDF", "SIDO", "KLBF", "BBCA", "BBRI"],
        "positive_tickers": ["ANTM", "ITMG", "ADRO"],
    },
    "bi_rate_hike": {
        "label": "Bank Indonesia Naikkan BI Rate",
        "icon": "🏛️",
        "keywords": ["bi rate naik", "bank indonesia naikkan suku bunga", "bi7drr naik", "bi rate hike", "suku bunga acuan naik"],
        "impact": "negative",
        "narrative": "BI naikkan suku bunga → cost of fund perbankan naik, properti dan konsumer tertekan.",
        "negative_tickers": ["BSDE", "SMRA", "CTRA", "ASRI", "LPKR", "UNVR", "ICBP"],
        "positive_tickers": ["BBCA", "BBRI", "BMRI", "BBNI"],
    },
    "recession_fear": {
        "label": "Ketakutan Resesi Global",
        "icon": "😨",
        "keywords": ["recession fear", "global recession", "resesi global", "economic slowdown", "gdp kontraksi", "perlambatan ekonomi"],
        "impact": "negative",
        "narrative": "Resesi global → permintaan komoditas turun, saham cyclical tertekan.",
        "negative_tickers": ["ADRO", "PTBA", "ITMG", "ANTM", "AALI", "INCO", "TINS"],
        "positive_tickers": ["ICBP", "UNVR", "KLBF", "SIDO"],
    },
}


@st.cache_data(ttl=600)
def fetch_macro_news_yfinance() -> list:
    """Fetch macro-relevant headlines from yfinance."""
    macro_queries = ["^JKSE", "IDR=X", "GC=F", "CL=F"]
    articles = []
    import pytz
    import datetime as dt
    WIB = pytz.timezone("Asia/Jakarta")
    for symbol in macro_queries:
        try:
            t = yf.Ticker(symbol)
            news = t.news or []
            for item in news[:5]:
                title = item.get("title", "")
                link = item.get("link", "")
                pub_ts = item.get("providerPublishTime", 0)
                if title:
                    try:
                        dt_wib = dt.datetime.fromtimestamp(pub_ts, tz=WIB)
                        created_display = dt_wib.strftime("%d %b %H:%M WIB")
                    except Exception:
                        created_display = ""
                    articles.append({
                        "title": title,
                        "link": link,
                        "source": symbol,
                        "ts": pub_ts,
                        "created_display": created_display
                    })
        except Exception:
            pass
    seen = set()
    unique = []
    for a in articles:
        if a["title"] not in seen:
            seen.add(a["title"])
            unique.append(a)
    return sorted(unique, key=lambda x: x["ts"], reverse=True)


def fetch_stockbit_news_headlines() -> list:
    """Fetch Stockbit News feed from Exodus non-login endpoint."""
    headlines = []
    try:
        url = "https://exodus.stockbit.com/stream/non-login/user/StockbitNews"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            items = r.json().get("data", [])
            for item in items[:30]:
                title = item.get("title", "") or (item.get("content", "") or "")[:120]
                if not title:
                    continue
                headlines.append({
                    "title": title,
                    "link": item.get("titleurl", ""),
                    "source": "stockbit",
                    "ts": item.get("created", 0),
                    "created_display": item.get("created_display", ""),
                    "content_preview": (item.get("content", "") or "")[:200],
                    "topics": item.get("topics", []),
                })
    except Exception:
        pass
    return headlines


import re
TICKER_RE = re.compile(r'\b([A-Z]{4})\b')

def _extract_tickers(text: str) -> list:
    """Extract 4-char uppercase tickers, exclude common non-ticker noise."""
    matches = TICKER_RE.findall(text.upper())
    return [
        m for m in matches
        if m not in {"IHSG", "FROM", "WITH", "THAT", "THIS", "YEAR", "DATA", "NEWS"}
    ]

def _parse_rss(url: str, source_tag: str, max_items: int = 30) -> list:
    """Generic RSS parser for Indonesian news feeds."""
    import xml.etree.ElementTree as ET
    headlines = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r = requests_cf.get(url, headers=headers, timeout=10, impersonate="chrome")
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            for item in root.findall('.//item')[:max_items]:
                title = item.findtext('title', '').strip()
                link = item.findtext('link', '')
                pub_date = item.findtext('pubDate', '')
                description = item.findtext('description', '')
                if not title:
                    continue
                # Extract topics from RSS + auto-extract tickers from title
                topics = [c.text.strip() for c in item.findall('category') if c.text]
                topics.extend(_extract_tickers(title))
                
                headlines.append({
                    "title": title,
                    "link": link,
                    "source": source_tag,
                    "ts": 0,
                    "created_display": pub_date,
                    "content_preview": description[:200] if description else "",
                    "topics": list(set(topics)),
                })
    except Exception:
        pass
    return headlines


def fetch_cnbc_rss() -> list:
    """Fetch CNBC Indonesia RSS feed."""
    return _parse_rss("https://www.cnbcindonesia.com/rss", "cnbc_indonesia")


def fetch_antara_rss() -> list:
    """Fetch Antara Ekonomi RSS feed."""
    return _parse_rss("https://www.antaranews.com/rss/ekonomi", "antara_ekonomi")


def fetch_kontan_scrape() -> list:
    """Scrape Kontan.co.id homepage for latest financial news headlines.

    Kontan's RSS endpoints (`rss.kontan.co.id`) are all 403 / TLS failure
    as of 2026-06. The main site renders headlines inline, so we extract
    (title, link) pairs from the homepage HTML.
    """
    import re
    headlines: list[dict] = []
    seen_links: set[str] = set()
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests_cf.get(
            "https://www.kontan.co.id",
            headers=headers,
            timeout=10,
            impersonate="chrome",
        )
        if r.status_code != 200:
            return headlines
        html = r.text

        # Pattern A: headline cards with <img alt="Title"> inside a link
        for m in re.finditer(
            r'<a\s+href="((?:https?:)?//[a-z0-9.\-]*kontan\.co\.id/news/[^"]+)"[^>]*>'
            r'\s*<img[^>]*alt="([^"]+)"[^>]*/>\s*</a>',
            html, re.IGNORECASE,
        ):
            link = m.group(1)
            if link.startswith("//"):
                link = "https:" + link
            link = link.split("?")[0]
            title = m.group(2).strip()
            if title and link not in seen_links and len(title) >= 15:
                seen_links.add(link)
                headlines.append({
                    "title": title,
                    "link": link,
                    "source": "kontan",
                    "ts": 0,
                    "created_display": "",
                    "content_preview": "",
                    "topics": _extract_tickers(title),
                    })

        # Pattern B: <h1>/<h2>/<h3> with a direct <a> child (article title)
        if len(headlines) < 10:
            for m in re.finditer(
                r'<h[1-3][^>]*>\s*<a\s+href="((?:https?:)?//[a-z0-9.\-]*kontan\.co\.id/news/[^"]+)"[^>]*>'
                r'([^<]{20,})</a>',
                html, re.IGNORECASE,
            ):
                link = m.group(1)
                if link.startswith("//"):
                    link = "https:" + link
                link = link.split("?")[0]
                title = re.sub(r"\s+", " ", m.group(2)).strip()
                if title and link not in seen_links:
                    seen_links.add(link)
                    headlines.append({
                        "title": title,
                        "link": link,
                        "source": "kontan",
                        "ts": 0,
                        "created_display": "",
                        "content_preview": "",
                        "topics": _extract_tickers(title),
                    })
    except Exception as e:
        logger.debug(f"Kontan scrape error: {e}")
    return headlines[:30]


def fetch_bisnis_scrape() -> list:
    """Bisnis Indonesia news source.

    As of 2026-06, Bisnis Indonesia has no public RSS feed and the
    main site (www.bisnis.com) returns 404 for /rss, /feed, and all
    category indexes. The site requires JavaScript-rendered
    navigation to load article lists. We return an empty list and
    surface a clear "unavailable" state in the UI rather than fake data.
    """
    logger.debug("Bisnis Indonesia: no public feed available, skipping")
    return []


def fetch_idx_disclosure_scrape() -> list:
    """IDX (Bursa Efek Indonesia) corporate disclosure / news announcements.

    IDX official endpoints are all 403 Forbidden without auth:
    - /primary/NewsAnnouncement/GetAllNews
    - /primary/TradingData/GetNewsCompany
    - /api/v1/news
    Returning empty list and letting the UI mark this source as
    unavailable.
    """
    logger.debug("IDX Disclosure: endpoints 403, no public feed")
    return []


def detect_macro_themes(articles: list) -> list:
    triggered = []
    for theme_key, theme in MACRO_THEMES.items():
        matched = [a for a in articles if any(kw in a["title"].lower() for kw in theme["keywords"])]
        if matched:
            triggered.append({
                "key": theme_key,
                "label": theme["label"],
                "icon": theme["icon"],
                "impact": theme["impact"],
                "narrative": theme["narrative"],
                "positive_tickers": theme["positive_tickers"],
                "negative_tickers": theme["negative_tickers"],
                "articles": matched[:3],
            })
    return triggered


def build_ticker_impact_table(triggered_themes: list, watchlist_tickers: list) -> list:
    impact_map = {}
    for theme in triggered_themes:
        for t in theme["positive_tickers"]:
            if t in watchlist_tickers or not watchlist_tickers:
                impact_map.setdefault(t, {"positive": [], "negative": []})["positive"].append(theme["label"])
        for t in theme["negative_tickers"]:
            if t in watchlist_tickers or not watchlist_tickers:
                impact_map.setdefault(t, {"positive": [], "negative": []})["negative"].append(theme["label"])
    rows = []
    for ticker, impacts in impact_map.items():
        net = len(impacts["positive"]) - len(impacts["negative"])
        signal = "🟢 Positif" if net > 0 else ("🔴 Negatif" if net < 0 else "🟡 Mixed")
        rows.append({
            "Ticker": ticker,
            "Signal": signal,
            "Positif dari": ", ".join(impacts["positive"]) if impacts["positive"] else "-",
            "Negatif dari": ", ".join(impacts["negative"]) if impacts["negative"] else "-",
            "Net Score": net,
        })
    return sorted(rows, key=lambda x: x["Net Score"], reverse=True)


def build_ticker_impact_table_v2(
    triggered_themes: list,
    all_articles: list,
    watchlist_tickers: list,
) -> list:
    """Ticker impact table enhanced with direct mention signals from all news sources.

    Two signal layers:
    1. Macro theme impact (static ticker lists from MACRO_THEMES)
    2. Direct mention in headline: sentiment-classified articles that
       explicitly mention a 4-char ticker in their topics array.

    Watchlist filter applies to both layers — if watchlist is empty, all
    tickers are included.
    """
    pos_kw = ["naik", "tumbuh", "laba", "positif", "dividen", "akuisisi",
              "ekspansi", "profit", "growth", "rise", "gain", "upgrade",
              "bullish", "lunasi", "raih", "rekor", "surplus", "bangkit"]
    neg_kw = ["turun", "rugi", "gagal", "krisis", "utang", "debt", "loss",
              "downgrade", "bearish", "crash", "tunda", "henti", "anjlok",
              "merugi", "default", "sanksi", "protes", "ancam", "pailit"]

    # Layer 1: macro theme static tickers
    impact_map: dict[str, dict] = {}
    for theme in triggered_themes:
        for t in theme["positive_tickers"]:
            if not watchlist_tickers or t in watchlist_tickers:
                e = impact_map.setdefault(t, {
                    "macro_pos": [], "macro_neg": [],
                    "mention_pos": [], "mention_neg": [],
                    "latest_ts": 0,
                    "latest_time": "-",
                })
                e["macro_pos"].append(theme["label"])
        for t in theme["negative_tickers"]:
            if not watchlist_tickers or t in watchlist_tickers:
                e = impact_map.setdefault(t, {
                    "macro_pos": [], "macro_neg": [],
                    "mention_pos": [], "mention_neg": [],
                    "latest_ts": 0,
                    "latest_time": "-",
                })
                e["macro_neg"].append(theme["label"])

    # Layer 2: direct ticker mention in headlines
    from data.sentiment import _score_headline, is_relevant_to_ticker
    
    # Pre-lookup company name maps to avoid false positives
    ticker_company_map = {}
    if watchlist_tickers:
        # Match from active sheet registry or database if available
        # But we can fall back to ticker code matching directly
        pass

    for art in all_articles:
        title_l = art["title"].lower()
        score = _score_headline(art["title"])
        if score == 0.0:
            continue
        source_label = art.get("source", "news").upper()
        snippet = art["title"][:60] + ("…" if len(art["title"]) > 60 else "")
        created_display = art.get("created_display", "")
        time_str = f" [{created_display}]" if created_display else ""
        try:
            art_ts = int(float(art.get("ts", 0) or 0))
        except (ValueError, TypeError):
            art_ts = 0
        
        # Scan watchlist for relevance to avoid false-positives
        scan_list = watchlist_tickers if watchlist_tickers else []
        for t in scan_list:
            if is_relevant_to_ticker(art["title"], t):
                e = impact_map.setdefault(t, {
                    "macro_pos": [], "macro_neg": [],
                    "mention_pos": [], "mention_neg": [],
                    "latest_ts": 0,
                    "latest_time": "-",
                })
                if art_ts > e["latest_ts"]:
                    e["latest_ts"] = art_ts
                    e["latest_time"] = created_display or "-"
                if score > 0:
                    e["mention_pos"].append(f"[{source_label}]{time_str} {snippet}")
                elif score < 0:
                    e["mention_neg"].append(f"[{source_label}]{time_str} {snippet}")

    rows = []
    for ticker, e in impact_map.items():
        macro_net = len(e["macro_pos"]) - len(e["macro_neg"])
        mention_net = len(e["mention_pos"]) - len(e["mention_neg"])
        net = macro_net + mention_net
        signal = "🟢 Positif" if net > 0 else ("🔴 Negatif" if net < 0 else "🟡 Mixed")
        rows.append({
            "Ticker": ticker,
            "Signal": signal,
            "Net Score": net,
            "Macro +": ", ".join(e["macro_pos"]) if e["macro_pos"] else "-",
            "Macro -": ", ".join(e["macro_neg"]) if e["macro_neg"] else "-",
            "Mention +": f"{len(e['mention_pos'])} headline(s)" if e["mention_pos"] else "-",
            "Mention -": f"{len(e['mention_neg'])} headline(s)" if e["mention_neg"] else "-",
            "Latest Mention": e["latest_time"],
            "_mention_pos_detail": e["mention_pos"],
            "_mention_neg_detail": e["mention_neg"],
        })
    return sorted(rows, key=lambda x: x["Net Score"], reverse=True)


def build_per_ticker_sentiment(
    all_articles: list,
    yfinance_data: dict,
    watchlist_tickers: list,
) -> list:
    """Per-ticker sentiment enriched with multi-source news mentions.

    Combines:
    - yfinance sentiment score + headline count (existing)
    - Multi-source mention count + headline snippets from all_articles

    Args:
        all_articles: flat list of article dicts from all 6 sources
        yfinance_data: {ticker: {sentiment, count, latest}} from fetch_news_for_tickers
        watchlist_tickers: list of ticker strings

    Returns:
        list of dicts sorted by combined_score desc
    """
    from data.sentiment import _score_headline, is_relevant_to_ticker
    from data.fetchers import safe_float

    # Build mention map from all_articles
    mention_map: dict[str, dict] = {}
    for art in all_articles:
        for t in (watchlist_tickers or []):
            if is_relevant_to_ticker(art["title"], t):
                score = _score_headline(art["title"])
                if score == 0.0:
                    continue
                m = mention_map.setdefault(t, {
                    "count": 0, "score": 0.0, "headlines": [], "sources": set()
                })
                m["count"] += 1
                m["score"] += score
                m["sources"].add(art.get("source", "?"))
                if len(m["headlines"]) < 3:
                    m["headlines"].append({
                        "title": art["title"],
                        "link": art.get("link", ""),
                        "source": art.get("source", ""),
                        "created_display": art.get("created_display", ""),
                    })

    rows = []
    all_tickers = set(watchlist_tickers or []) | set(yfinance_data.keys()) | set(mention_map.keys())

    for ticker in all_tickers:
        if watchlist_tickers and ticker not in watchlist_tickers:
            continue

        yf = yfinance_data.get(ticker, {})
        yf_score = safe_float(yf.get("sentiment", 0))
        yf_count = yf.get("count", 0)
        yf_latest = yf.get("latest", "-")
        yf_latest_time = yf.get("latest_time", "")

        yf_latest_display = f"[{yf_latest_time}] {yf_latest}" if yf_latest_time and yf_latest != "-" else yf_latest

        mn = mention_map.get(ticker, {})
        mn_score = mn.get("score", 0.0)
        mn_count = mn.get("count", 0)
        mn_sources = ", ".join(sorted(mn.get("sources", set()))) if mn.get("sources") else "-"
        mn_headlines = mn.get("headlines", [])

        combined = yf_score + mn_score
        sent_label = (
            "🟢 Positif" if combined >= 0.3
            else "🔴 Negatif" if combined <= -0.3
            else "🟡 Netral"
        )

        rows.append({
            "Ticker": ticker,
            "Sentimen": sent_label,
            "Combined Score": combined,
            "yFinance Headlines": yf_count,
            "Multi-Source Mentions": mn_count,
            "Sumber Berita": mn_sources,
            "Latest (yFinance)": yf_latest_display[:100] + ("…" if len(yf_latest_display) > 100 else ""),
            "_mn_headlines": mn_headlines,
            "_combined": combined,
        })

    return sorted(rows, key=lambda x: x["_combined"], reverse=True)

