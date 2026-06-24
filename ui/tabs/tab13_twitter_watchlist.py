"""
Twitter/X Watchlist Scraper Tab.
Fetches stock watchlists from Twitter/X accounts WITHOUT API keys.
Uses Twitter Syndication endpoint as primary + manual paste as reliable fallback.
"""
import streamlit as st
import pandas as pd
import re
import json
import time
from datetime import datetime
from curl_cffi import requests as requests_cf
from data.fetchers import safe_float
from data.scoring import compute_intraday_score

WIB = __import__("pytz").timezone("Asia/Jakarta")

# ─── Ticker extraction ────────────────────────────────────────────────────────
TICKER_PATTERN = re.compile(r'\$([A-Z]{3,5})\b')


def _extract_tickers(text: str, valid_tickers: set) -> list[str]:
    """Extract $TICKER symbols from text, filtered to valid IDX tickers."""
    found = TICKER_PATTERN.findall(text)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for t in found:
        if t not in seen and t in valid_tickers:
            seen.add(t)
            result.append(t)
    return result


def _extract_watchlist_title(text: str) -> str:
    """Try to extract the watchlist title/date line from tweet text."""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    for line in lines:
        # Watchlist title usually doesn't start with $ and contains date-like words
        if not line.startswith('$') and not line.lower().startswith('disclaimer'):
            # Check if it looks like a title (has letters, maybe numbers for date)
            if any(kw in line.lower() for kw in ['watchlist', 'wl', 'list', 'pick', 'saham', 'scalp', 'swing']):
                return line
    # Fallback: first non-ticker line
    for line in lines:
        if not line.startswith('$') and not line.lower().startswith('disclaimer') and len(line) > 5:
            return line
    return "Twitter Watchlist"


# ─── Twitter Syndication Scraper ──────────────────────────────────────────────

def _extract_texts_from_json(obj, depth=0) -> list[str]:
    """Recursively extract text content from __NEXT_DATA__ JSON."""
    texts = []
    if depth > 20:
        return texts
    if isinstance(obj, dict):
        # Look for known tweet text keys
        for key in ('text', 'full_text', 'tweet_text'):
            if key in obj and isinstance(obj[key], str) and len(obj[key]) > 10:
                texts.append(obj[key])
        for v in obj.values():
            texts.extend(_extract_texts_from_json(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            texts.extend(_extract_texts_from_json(item, depth + 1))
    return texts


def _fetch_twitter_timeline(username: str) -> list[dict]:
    """
    Fetch recent tweets via Twitter syndication (no API key needed).
    Returns list of dicts with 'text' key, or empty list on failure.
    """
    url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
    try:
        resp = requests_cf.get(
            url, impersonate="chrome", timeout=15,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }
        )
        if resp.status_code != 200:
            return []

        html = resp.text
        tweet_texts = []

        # Method 1: __NEXT_DATA__ JSON extraction
        nd_match = re.search(
            r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if nd_match:
            try:
                nd = json.loads(nd_match.group(1))
                tweet_texts = _extract_texts_from_json(nd)
            except (json.JSONDecodeError, KeyError):
                pass

        # Method 2: Extract from rendered tweet HTML
        if not tweet_texts:
            # Look for tweet text in data-testid or aria patterns
            text_matches = re.findall(
                r'data-testid="tweetText"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )
            if not text_matches:
                # Broader: any text block containing $TICKER
                text_matches = re.findall(r'>([^<]*\$[A-Z]{3,5}[^<]*)<', html)
            tweet_texts = [re.sub(r'<[^>]+>', '', t).strip() for t in text_matches]

        # Method 3: Last resort — extract all spans/divs with ticker patterns
        if not tweet_texts:
            all_text_blocks = re.findall(r'>([^<]{15,})<', html)
            tweet_texts = [t.strip() for t in all_text_blocks if '$' in t and TICKER_PATTERN.search(t)]

        results = []
        seen_texts = set()
        for text in tweet_texts:
            text = text.strip()
            # Dedup by first 50 chars
            key = text[:50]
            if text and key not in seen_texts:
                seen_texts.add(key)
                results.append({"text": text})
        return results[:15]

    except Exception as e:
        return []


# ─── Main render function ─────────────────────────────────────────────────────

def render_tab13_twitter(ticker_df, scored_list, screener_data_map):
    """Render Tab 13: Twitter Watchlist — fetch stock picks from Twitter accounts."""

    st.markdown("### 🐦 Twitter Watchlist Scanner")
    st.caption(
        "Extract stock watchlists from Twitter/X accounts. "
        "Uses syndication scraping (no API key needed) + manual paste fallback."
    )

    valid_tickers = set(ticker_df["Clean Ticker"].unique().tolist()) if not ticker_df.empty else set()

    # Build hist_lookup from scored_list
    hist_lookup = {}
    for s in scored_list:
        hist_lookup[s["Ticker"]] = s.get("hist_row_obj", {})

    # ── Config Section ────────────────────────────────────────────────────────
    st.markdown("---")
    cfg1, cfg2, cfg3 = st.columns([2, 1, 1])

    with cfg1:
        twitter_user = st.text_input(
            "Twitter/X Username (tanpa @):",
            value=st.session_state.get("tw_username", "saptaipb"),
            key="tw_user_input",
            placeholder="e.g. saptaipb"
        ).strip().lstrip('@')

    with cfg2:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        fetch_clicked = st.button("🔄 Fetch Tweets", use_container_width=True)

    with cfg3:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        clear_clicked = st.button("🗑️ Clear", use_container_width=True)

    if clear_clicked:
        for key in ["tw_fetched_tweets", "tw_fetch_time", "tw_username", "tw_extracted"]:
            st.session_state.pop(key, None)
        st.rerun()

    # ── Fetch Logic ───────────────────────────────────────────────────────────
    if fetch_clicked and twitter_user:
        st.session_state.tw_username = twitter_user
        with st.spinner(f"⚡ Fetching tweets from @{twitter_user}..."):
            tweets = _fetch_twitter_timeline(twitter_user)
            st.session_state.tw_fetched_tweets = tweets
            st.session_state.tw_fetch_time = time.time()
            if tweets:
                st.toast(f"✅ Fetched {len(tweets)} tweets from @{twitter_user}")
            else:
                st.toast(f"⚠️ Could not fetch tweets from @{twitter_user}. Use manual paste below.", icon="⚠️")

    # ── Input Sources ─────────────────────────────────────────────────────────
    st.markdown("#### 📥 Input Sources")
    src1, src2 = st.columns(2)

    with src1:
        st.markdown("##### ✍️ Manual Paste (Reliable)")
        st.caption("Paste tweet text directly — always works.")
        manual_text = st.text_area(
            "Paste tweet containing $TICKER symbols:",
            height=200,
            key="tw_manual_text",
            placeholder=(
                "Watchlist scalping 24 Juni 26\n\n"
                "$BUVA\n$LEAD\n\n"
                "Disclaimer on"
            )
        )
        parse_manual = st.button("📋 Parse Manual Text", use_container_width=True)

    with src2:
        st.markdown("##### 🌐 Fetched Tweets (Auto)")
        cached_tweets = st.session_state.get("tw_fetched_tweets", [])
        fetch_time = st.session_state.get("tw_fetch_time", 0)

        if cached_tweets:
            age_min = (time.time() - fetch_time) / 60
            st.caption(f"✅ {len(cached_tweets)} tweets loaded ({age_min:.0f} min ago)")

            # Show fetched tweets in expandable preview
            for i, tweet in enumerate(cached_tweets[:5]):
                txt_preview = tweet["text"][:120] + "..." if len(tweet["text"]) > 120 else tweet["text"]
                tickers_in = TICKER_PATTERN.findall(tweet["text"])
                ticker_badge = f" — **{', '.join(tickers_in)}**" if tickers_in else ""
                with st.expander(f"Tweet #{i+1}{ticker_badge}", expanded=(i == 0)):
                    st.text(tweet["text"])
        else:
            st.info(
                "No tweets fetched yet. Click **🔄 Fetch Tweets** above, "
                "or paste tweet text in the left panel."
            )

    # ── Extract tickers ───────────────────────────────────────────────────────
    combined_text = ""

    if parse_manual and manual_text.strip():
        combined_text = manual_text.strip()
    elif cached_tweets and not parse_manual:
        # Auto-use fetched tweets if no manual parse requested
        combined_text = "\n\n".join(t["text"] for t in cached_tweets)

    # Also always combine manual if it has $TICKER in it (background merge)
    if manual_text and TICKER_PATTERN.search(manual_text) and not parse_manual:
        if combined_text:
            combined_text = manual_text.strip() + "\n\n" + combined_text
        else:
            combined_text = manual_text.strip()

    if combined_text:
        extracted = _extract_tickers(combined_text, valid_tickers)
        title = _extract_watchlist_title(combined_text)

        # Also extract tickers NOT in valid set for warning
        all_found = TICKER_PATTERN.findall(combined_text)
        unknown = [t for t in set(all_found) if t not in valid_tickers and t not in extracted]

        if extracted:
            st.session_state.tw_extracted = extracted
        
        if unknown:
            st.caption(f"⚠️ Tickers not found in IDX database (skipped): {', '.join(sorted(unknown))}")

    # ── Display Watchlist ─────────────────────────────────────────────────────
    extracted = st.session_state.get("tw_extracted", [])

    if extracted:
        title = st.session_state.get("tw_title", "Twitter Watchlist")

        st.markdown("---")
        st.markdown(f"### 📋 Extracted Watchlist — **{len(extracted)} tickers**")
        source_label = f"@{st.session_state.get('tw_username', '?')}"
        now_str = datetime.now(WIB).strftime('%H:%M:%S WIB')
        st.caption(f"Source: {source_label} | Parsed at {now_str}")

        # ── Ticker Cards ──────────────────────────────────────────────────────
        # Show top tickers as metric cards (max 6 per row)
        card_cols = st.columns(min(len(extracted), 6))
        for i, ticker in enumerate(extracted[:6]):
            with card_cols[i]:
                price = 0
                chg_pct = 0.0
                if ticker in screener_data_map:
                    raw = screener_data_map[ticker]
                    price = raw.get("last", 0)
                    prev = raw.get("prev_close", price)
                    if prev and prev > 0:
                        chg_pct = (price - prev) / prev * 100
                elif ticker in hist_lookup:
                    hr = hist_lookup[ticker]
                    price = safe_float(hr.get("Price", 0))
                    chg_pct = safe_float(hr.get("Change%", 0))

                chg_color = "#00D4AA" if chg_pct >= 0 else "#FF6B6B"
                chg_sign = "+" if chg_pct > 0 else ""
                st.markdown(f"""
                <div class="metric-card" style="border-left-color: {chg_color}; text-align:center;">
                    <h3 style="margin:0; color: #E2E8F0;">{ticker}</h3>
                    <h2 style="margin:4px 0;">IDR {price:,.0f}</h2>
                    <span style="color: {chg_color}; font-weight:600;">{chg_sign}{chg_pct:.2f}%</span>
                </div>
                """, unsafe_allow_html=True)

        # ── Full Data Table ───────────────────────────────────────────────────
        wl_rows = []
        for ticker in extracted:
            row = {"Ticker": ticker}
            if ticker in hist_lookup:
                hr = hist_lookup[ticker]
                row["Company"] = hr.get("Company Name", "")
                row["Sector"] = hr.get("Sector", "")
            else:
                row["Company"] = ""
                row["Sector"] = ""

            if ticker in screener_data_map:
                raw = screener_data_map[ticker]
                row["Price"] = raw.get("last", 0)
                prev = raw.get("prev_close", row["Price"])
                row["Change %"] = ((row["Price"] - prev) / prev * 100) if prev > 0 else 0.0
                row["Volume"] = raw.get("volume", 0)
                row["Source"] = "🟢 Live"
            elif ticker in hist_lookup:
                hr = hist_lookup[ticker]
                row["Price"] = safe_float(hr.get("Price", 0))
                row["Change %"] = safe_float(hr.get("Change%", 0))
                row["Volume"] = safe_float(hr.get("Volume", 0))
                row["Source"] = "📊 Cached"
            else:
                row["Price"] = 0
                row["Change %"] = 0
                row["Volume"] = 0
                row["Source"] = "❓ Unknown"

            if ticker in hist_lookup:
                hr = hist_lookup[ticker]
                row["RSI14"] = safe_float(hr.get("RSI14", 0))
                row["Support"] = safe_float(hr.get("Support", 0))
                row["Resistance"] = safe_float(hr.get("Breakout", 0))
            else:
                row["RSI14"] = 0
                row["Support"] = 0
                row["Resistance"] = 0

            wl_rows.append(row)

        if wl_rows:
            wl_df = pd.DataFrame(wl_rows)
            st.dataframe(
                wl_df,
                column_config={
                    "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                    "Change %": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                    "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                    "RSI14": st.column_config.NumberColumn("RSI14", format="%.1f"),
                    "Support": st.column_config.NumberColumn("Support", format="IDR %d"),
                    "Resistance": st.column_config.NumberColumn("Resistance", format="IDR %d"),
                },
                use_container_width=True,
                hide_index=True,
            )

        # ── Quick Actions ─────────────────────────────────────────────────────
        st.markdown("#### ⚡ Quick Actions")
        act_cols = st.columns(min(len(extracted), 4))
        for i, ticker in enumerate(extracted[:4]):
            with act_cols[i]:
                if st.button(f"🔍 Analyze {ticker}", key=f"tw_analyze_{ticker}", use_container_width=True):
                    st.session_state.deep_analyzed_ticker = ticker
                    st.toast(f"Switched Deep Analysis to {ticker}. Go to 🔍 Deep Stock Analysis tab.")

        # ── Bulk add to Custom Watchlist ───────────────────────────────────────
        st.markdown("---")
        if st.button("⭐ Add All to Custom Watchlist", use_container_width=True):
            from repositories.sqlite_repository import sqlite_repository
            added = 0
            for ticker in extracted:
                if ticker not in st.session_state.get("custom_watchlist", []):
                    sqlite_repository.add_watchlist(ticker)
                    added += 1
            if added > 0:
                st.session_state.custom_watchlist = sqlite_repository.get_watchlist()
                st.toast(f"✅ Added {added} tickers to Custom Watchlist!")
                st.rerun()
            else:
                st.info("All tickers are already in your Custom Watchlist.")

    elif not combined_text:
        st.markdown("---")
        st.info(
            "👆 Paste tweet text in the **Manual Paste** box above, or "
            "enter a Twitter username and click **🔄 Fetch Tweets** to get started."
        )
