"""Watchlist + Portfolio — merged Tab 1 (Live Feed), Custom Watchlist, and
Live Portfolio Tracker + DCA calculator into one tab with sections."""
import streamlit as st
import pandas as pd
from datetime import datetime

from data.fetchers import safe_float
from repositories.sqlite_repository import sqlite_repository

WIB = __import__("pytz").timezone("Asia/Jakarta")


def _render_live_feed(ticker_df):
    st.markdown("#### 📋 Active Tickers Pool (Live Feed vs Sheets)")
    active_ticker_df = ticker_df[ticker_df["Status"].str.contains("ACTIVE", na=False)].copy()
    st.markdown(f"**Total Emiten Aktif:** `{len(active_ticker_df)} emiten`")

    comparison_rows = []
    for _, row in active_ticker_df.iterrows():
        ticker = row["Clean Ticker"]
        sheet_ts = None
        raw_ts = row.get("Last Update", "")
        if raw_ts:
            try:
                sheet_ts = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        live_ts = None
        live_source = "gsheet"
        live_price = safe_float(row.get("Price"))

        if "screener_data" in st.session_state and ticker in st.session_state.screener_data:
            live_entry = st.session_state.screener_data[ticker]
            live_price = safe_float(live_entry.get("last", live_price))
            live_source = live_entry.get("source", "gsheet")
            live_ts_obj = live_entry.get("source_ts")
            if live_ts_obj:
                live_ts = live_ts_obj.replace(tzinfo=None) if hasattr(live_ts_obj, "replace") else live_ts_obj

        is_live_newer = False
        if live_source in ("stockbit", "exodus") and live_ts and sheet_ts:
            is_live_newer = live_ts > sheet_ts
        elif live_source in ("stockbit", "exodus") and live_ts and not sheet_ts:
            is_live_newer = True

        if is_live_newer:
            comparison_rows.append({
                "Ticker": ticker,
                "Company Name": row.get("Company Name", ""),
                "Google Sheets Price": safe_float(row.get("Price")),
                "Stockbit Live Price": live_price,
                "Google Sheets Update": raw_ts,
                "Stockbit Live Update": live_ts.strftime("%Y-%m-%d %H:%M:%S") if live_ts else "—",
                "Delta Price": live_price - safe_float(row.get("Price")),
            })

    st.markdown("##### ⚡ Live Stockbit Overrides")
    if comparison_rows:
        comp_df = pd.DataFrame(comparison_rows)
        st.dataframe(
            comp_df,
            column_config={
                "Google Sheets Price": st.column_config.NumberColumn("Sheets Price", format="IDR %d"),
                "Stockbit Live Price": st.column_config.NumberColumn("Stockbit Price", format="IDR %d"),
                "Delta Price": st.column_config.NumberColumn("Price Delta", format="IDR %+d"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Semua feed saat ini sinkron. Tidak ada ticker dengan update Stockbit yang lebih baru dibanding Google Sheets.")

    st.markdown("##### 📋 Database Pool (Google Sheets)")
    if not active_ticker_df.empty:
        col_order = [
            "Ticker", "Company Name", "Sector", "Rank", "Status", "Score v2",
            "Price", "Change%", "Volume", "Vol_Avg", "MA20", "Support", "Breakout",
            "RSI14", "SL_Practical", "TP_Target", "RR_Ratio", "Last Update",
        ]
        remaining_cols = [c for c in active_ticker_df.columns if c not in col_order and c != "Clean Ticker"]
        display_cols = col_order + remaining_cols
        st.dataframe(
            active_ticker_df[display_cols],
            column_config={
                "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                "Vol_Avg": st.column_config.NumberColumn("Vol Avg", format="%d"),
                "MA20": st.column_config.NumberColumn("MA20", format="IDR %d"),
                "Support": st.column_config.NumberColumn("Support", format="IDR %d"),
                "Breakout": st.column_config.NumberColumn("Breakout", format="IDR %d"),
                "SL_Practical": st.column_config.NumberColumn("SL Practical", format="IDR %d"),
                "TP_Target": st.column_config.NumberColumn("TP Target", format="IDR %d"),
                "RSI14": st.column_config.NumberColumn("RSI (14)", format="%.1f"),
                "Score v2": st.column_config.NumberColumn("Score v2", format="%.1f"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Tidak ada emiten aktif.")


def _render_custom_watchlist(ticker_df, hist_lookup):
    st.markdown("#### ⭐ Custom Watchlist")
    st.caption("Search, add, and monitor custom tickers with live/cached metrics.")

    all_tickers = sorted(ticker_df["Clean Ticker"].unique().tolist())
    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        add_ticker_select = st.selectbox(
            "Search Emiten to Add",
            options=all_tickers,
            key="wl_add_select",
            help="Select ticker to add to watchlist.",
        )
    with col_add2:
        st.write("")
        st.write("")
        if st.button("➕ Add to Watchlist", use_container_width=True):
            if add_ticker_select not in st.session_state.custom_watchlist:
                sqlite_repository.add_watchlist(add_ticker_select)
                st.session_state.custom_watchlist = sqlite_repository.get_watchlist()
                st.toast(f"Added {add_ticker_select} to watchlist! 🚀")
                st.rerun()
            else:
                st.warning(f"{add_ticker_select} is already in watchlist.")

    if st.session_state.custom_watchlist:
        wl_data = []
        for ticker in st.session_state.custom_watchlist:
            if ticker in hist_lookup:
                hist_row = hist_lookup[ticker]
                if ticker in st.session_state.screener_data:
                    raw_data = st.session_state.screener_data[ticker]
                    price = raw_data["last"]
                    prev_close = safe_float(hist_row.get("ClosePrev", price))
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
                    volume = raw_data.get("volume", 0)
                else:
                    price = safe_float(hist_row.get("Price"))
                    change_pct = safe_float(hist_row.get("Change%"))
                    volume = safe_float(hist_row.get("Volume"))
                wl_data.append({
                    "Ticker": ticker,
                    "Company Name": hist_row.get("Company Name", ""),
                    "Sector": hist_row.get("Sector", ""),
                    "Price": price,
                    "Change %": change_pct,
                    "Volume": volume,
                    "RSI14": safe_float(hist_row.get("RSI14")),
                    "Support": safe_float(hist_row.get("Support")),
                    "Breakout": safe_float(hist_row.get("Breakout")),
                })

        if wl_data:
            wl_df = pd.DataFrame(wl_data)
            st.dataframe(
                wl_df,
                column_config={
                    "Price": st.column_config.NumberColumn("Price", format="IDR %d"),
                    "Change %": st.column_config.NumberColumn("Change %", format="%+.2f%%"),
                    "Volume": st.column_config.NumberColumn("Volume", format="%d"),
                    "RSI14": st.column_config.NumberColumn("RSI14", format="%.2f"),
                    "Support": st.column_config.NumberColumn("Support", format="IDR %d"),
                    "Breakout": st.column_config.NumberColumn("Resistance", format="IDR %d"),
                },
                use_container_width=True,
                hide_index=True,
            )

            col_rem1, col_rem2, col_rem3 = st.columns([2, 1, 1])
            with col_rem1:
                rem_ticker_select = st.selectbox(
                    "Select Ticker to Remove",
                    options=st.session_state.custom_watchlist,
                    key="wl_rem_select",
                )
            with col_rem2:
                st.write("")
                st.write("")
                if st.button("❌ Remove Selected", use_container_width=True):
                    sqlite_repository.remove_watchlist(rem_ticker_select)
                    st.session_state.custom_watchlist = sqlite_repository.get_watchlist()
                    st.toast(f"Removed {rem_ticker_select} from watchlist.")
                    st.rerun()
            with col_rem3:
                st.write("")
                st.write("")
                if st.button("🗑️ Clear Watchlist", use_container_width=True):
                    sqlite_repository.clear_watchlist()
                    st.session_state.custom_watchlist = []
                    st.toast("Watchlist cleared.")
                    st.rerun()
    else:
        st.info("Watchlist is currently empty. Use the search box above to add stocks.")


def _render_portfolio(hist_lookup, total_portfolio_value):
    st.markdown("#### 💼 Holdings")
    st.caption("Track your holding value, average buy price, and lots, compared against real-time feed.")

    all_tickers = sorted(hist_lookup.keys())
    col_p1, col_p2, col_p3, col_p4 = st.columns([2, 1.2, 1.2, 1])
    with col_p1:
        port_ticker_select = st.selectbox(
            "Search Emiten",
            options=all_tickers,
            key="port_add_select",
            help="Select ticker to add to portfolio.",
        )
    with col_p2:
        buy_price_input = st.number_input("Buy Price (IDR)", min_value=1.0, value=100.0, step=10.0, key="port_buy_price")
    with col_p3:
        lots_input = st.number_input("Lots Size", min_value=1, value=10, step=1, key="port_lots")
    with col_p4:
        st.write("")
        st.write("")
        if st.button("➕ Add Asset", use_container_width=True):
            sqlite_repository.remove_portfolio_by_ticker(port_ticker_select)
            sqlite_repository.add_portfolio(port_ticker_select, buy_price_input, lots_input)
            st.session_state.portfolio = sqlite_repository.get_portfolio()
            st.toast(f"Added {port_ticker_select} to portfolio!")
            st.rerun()

    if st.session_state.portfolio:
        port_rows = []
        total_invested = 0.0
        total_current_val = 0.0
        for asset in st.session_state.portfolio:
            ticker = asset["Ticker"]
            buy_price = asset["Buy Price"]
            lots = asset["Lots"]
            live_price = buy_price
            if ticker in hist_lookup:
                hist_row = hist_lookup[ticker]
                live_price = st.session_state.screener_data.get(ticker, {}).get("last") or safe_float(hist_row.get("Price"), buy_price)
            invested_val = buy_price * lots * 100
            current_val = live_price * lots * 100
            gain_loss = current_val - invested_val
            gain_loss_pct = (live_price - buy_price) / buy_price * 100 if buy_price > 0 else 0.0
            total_invested += invested_val
            total_current_val += current_val
            port_rows.append({
                "Ticker": ticker,
                "Buy Price": buy_price,
                "Lots": lots,
                "Live Price": live_price,
                "Invested Value": invested_val,
                "Current Value": current_val,
                "Gain / Loss": gain_loss,
                "Gain / Loss %": gain_loss_pct,
            })

        total_gain_loss = total_current_val - total_invested
        total_gain_loss_pct = total_gain_loss / total_invested * 100 if total_invested > 0 else 0.0

        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("Total Invested", f"Rp {total_invested:,.0f}")
        col_s2.metric("Total Value", f"Rp {total_current_val:,.0f}")
        col_s3.metric("Total Profit/Loss", f"Rp {total_gain_loss:+,.0f}", f"{total_gain_loss_pct:+.2f}%")

        st.markdown("---")
        port_df = pd.DataFrame(port_rows)
        st.dataframe(
            port_df,
            column_config={
                "Buy Price": st.column_config.NumberColumn("Avg Buy Price", format="IDR %d"),
                "Lots": st.column_config.NumberColumn("Lots", format="%d"),
                "Live Price": st.column_config.NumberColumn("Live Price", format="IDR %d"),
                "Invested Value": st.column_config.NumberColumn("Invested Val", format="Rp %d"),
                "Current Value": st.column_config.NumberColumn("Current Val", format="Rp %d"),
                "Gain / Loss": st.column_config.NumberColumn("Profit / Loss", format="Rp %+d"),
                "Gain / Loss %": st.column_config.NumberColumn("P/L %", format="%+.2f%%"),
            },
            use_container_width=True,
            hide_index=True,
        )

        col_prem1, col_prem2, col_prem3 = st.columns([2, 1, 1])
        with col_prem1:
            rem_asset_select = st.selectbox(
                "Select Asset to Remove",
                options=[a["Ticker"] for a in st.session_state.portfolio],
                key="port_rem_select",
            )
        with col_prem2:
            st.write("")
            st.write("")
            if st.button("❌ Remove Asset", use_container_width=True):
                sqlite_repository.remove_portfolio_by_ticker(rem_asset_select)
                st.session_state.portfolio = sqlite_repository.get_portfolio()
                st.toast(f"Removed {rem_asset_select} from portfolio.")
                st.rerun()
        with col_prem3:
            st.write("")
            st.write("")
            if st.button("🗑️ Reset Portfolio", use_container_width=True):
                sqlite_repository.clear_portfolio()
                st.session_state.portfolio = []
                st.toast("Portfolio cleared.")
                st.rerun()

        _render_dca(total_portfolio_value)
    else:
        st.info("Portfolio is empty. Add assets using the fields above.")


def _render_dca(total_portfolio_value):
    st.markdown("---")
    st.markdown("#### 🔄 Average Down Calculator")
    st.caption(
        "Simulasikan dampak average down terhadap harga rata-rata, jarak breakeven, "
        "dan konsentrasi risiko sebelum eksekusi."
    )

    dca_ticker = st.selectbox(
        "Pilih posisi yang ingin di-average down",
        options=[a["Ticker"] for a in st.session_state.portfolio],
        key="dca_ticker_select",
    )
    asset = next(a for a in st.session_state.portfolio if a["Ticker"] == dca_ticker)
    old_avg = asset["Buy Price"]
    old_lots = asset["Lots"]
    live_price = st.session_state.screener_data.get(dca_ticker, {}).get("last", old_avg)

    dca_col1, dca_col2 = st.columns(2)
    with dca_col1:
        dca_price_mode = st.radio(
            "Harga beli tambahan", ["Live Price", "Custom"],
            horizontal=True, key="dca_price_mode",
        )
        dca_price = live_price if dca_price_mode == "Live Price" else st.number_input(
            "Harga custom (IDR)", min_value=1.0, value=float(live_price), step=1.0, key="dca_custom_price",
        )
    with dca_col2:
        dca_lots = st.number_input("Lot tambahan", min_value=1, value=old_lots, step=1, key="dca_lots_input")

    new_lots = old_lots + dca_lots
    new_invested = (old_avg * old_lots * 100) + (dca_price * dca_lots * 100)
    new_avg = new_invested / (new_lots * 100)
    breakeven_gap_pct = ((new_avg - live_price) / live_price * 100) if live_price > 0 else 0.0

    old_position_mkt_val = old_lots * live_price * 100
    new_position_mkt_val = new_lots * dca_price * 100
    total_after_dca = total_portfolio_value - old_position_mkt_val + new_position_mkt_val
    ticker_concentration = (new_position_mkt_val / total_after_dca * 100) if total_after_dca > 0 else 0.0

    st.markdown("##### 📊 Hasil Simulasi")
    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("Avg Lama → Baru", f"Rp {old_avg:,.0f} → Rp {new_avg:,.0f}")
    rc2.metric("Total Lot Baru", f"{new_lots:,} lot")
    rc3.metric(
        "Jarak ke Breakeven", f"{breakeven_gap_pct:+.2f}%",
        help="Positif = live price masih perlu naik sekian % untuk balik modal dari avg baru.",
    )
    rc4.metric("Konsentrasi di Ticker Ini", f"{ticker_concentration:.1f}%")

    if ticker_concentration > 25:
        st.warning(
            f"⚠️ Setelah average down, **{dca_ticker}** akan menyumbang "
            f"**{ticker_concentration:.1f}%** dari total portofolio — di atas batas "
            f"konsentrasi umum 25% per saham. Pertimbangkan ulang ukurannya."
        )

    confirm_dca = st.checkbox(
        f"Saya yakin ingin average down {dca_ticker} ke avg baru Rp {new_avg:,.0f} ({new_lots} lot)",
        key="dca_confirm",
    )
    if st.button("✅ Terapkan Average Down ke Portfolio", disabled=not confirm_dca, key="dca_apply_btn"):
        sqlite_repository.remove_portfolio_by_ticker(dca_ticker)
        sqlite_repository.add_portfolio(dca_ticker, round(new_avg, 2), new_lots)
        st.session_state.portfolio = sqlite_repository.get_portfolio()
        st.toast(f"Average down {dca_ticker} diterapkan! Avg baru: Rp {new_avg:,.0f}")
        st.rerun()


def render_tab_watchlist_portfolio(ticker_df, hist_lookup, total_portfolio_value=0.0):
    st.markdown("### 📋 Watchlist & Portfolio")
    st.caption("Live feed, custom watchlist, holdings, and DCA calculator in one place.")
    st.markdown("---")
    _render_live_feed(ticker_df)
    st.markdown("---")
    _render_custom_watchlist(ticker_df, hist_lookup)
    st.markdown("---")
    _render_portfolio(hist_lookup, total_portfolio_value)
