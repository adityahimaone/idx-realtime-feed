import streamlit as st
from data.fetchers import safe_float
from data.scoring import compute_action_recommendation, minify_html


def render_tab2(scored_list):
    """Render Tab 2: Intraday Buy Recommendations"""
    st.markdown("### 🎯 Intraday Buy Recommendations")
    st.caption("Active recommendations generated using target prices and risk/reward formulas (Top 30 Strong Buys).")
    
    if scored_list:
        rec_list = []
        for s in scored_list:
            price = safe_float(s["Live Price"])
            score = s["Intraday Score"]
            hist_row = s["hist_row_obj"]
            
            # Stop loss: support or MA20 or standard 7%
            sl_prac = safe_float(hist_row.get("SL_Practical"))
            ma20 = safe_float(hist_row.get("MA20"))
            sl = sl_prac if sl_prac > 0 else round(max(ma20 * 0.97, price * 0.93), 2)
            if sl >= price:
                sl = round(price * 0.93, 2)
                
            # Target: 52W High or standard 15%
            high52 = safe_float(hist_row.get("52W High"))
            tp = round(min(high52, price * 1.15), 2) if high52 > 0 else round(price * 1.15, 2)
            
            rsi = safe_float(hist_row.get("RSI14"))
            
            action, max_pos, notes = compute_action_recommendation(price, sl, tp, score, rsi)
            
            # Append ATR stop-loss if ATR14 is available
            atr = safe_float(hist_row.get("ATR14"))
            if atr > 0:
                sl_atr = round(price - 1.5 * atr, 2)
                notes += f" | SL_ATR={sl_atr}"
                
            # Append UMA & Corporate Action warnings
            uma_str = hist_row.get("UMA", "")
            corp_act_str = hist_row.get("Corp Action", "")
            if uma_str:
                notes += f" | {uma_str}"
            if corp_act_str:
                notes += f" | CorpAct: {corp_act_str}"
            
            if "STRONG BUY" in action:
                rec_list.append({
                    "Ticker": s["Ticker"],
                    "Company Name": s["Company Name"],
                    "Sector": s["Sector"],
                    "Price": price,
                    "Intraday Score": score,
                    "Buy Target": price,
                    "Stop Loss (SL)": sl,
                    "Target Price (TP)": tp,
                    "R/R Ratio": round((tp - price) / max(1.0, price - sl), 2),
                    "Max Pos": max_pos,
                    "Action": action,
                    "Notes": notes,
                    "Change Pct": s["Change %"],
                    "Vol Spike": s["Vol Spike"],
                    "Live Signal": s["Live Signal"],
                    "Source Used": s["Source Used"]
                })
                
        if rec_list:
            # Sort by Intraday Score descending and take top 30
            rec_list = sorted(rec_list, key=lambda x: x["Intraday Score"], reverse=True)[:30]
            # Display recommendations as premium HTML cards
            html_cards = '<div class="card-grid">'
            for r in rec_list:
                # Determine Action Class
                act = r["Action"]
                if "STRONG BUY" in act:
                    act_class = "action-strong-buy"
                elif "BUY" in act:
                    act_class = "action-buy"
                else:
                    act_class = "action-speculative"
                    
                # Price change styling
                chg = r["Change Pct"]
                chg_class = "change-up" if chg >= 0 else "change-down"
                chg_sign = "+" if chg > 0 else ""
                
                # Progress bar color based on score
                sc = r["Intraday Score"]
                if sc >= 85:
                    bar_color = "#10B981" # green
                elif sc >= 70:
                    bar_color = "#3B82F6" # blue
                elif sc >= 50:
                    bar_color = "#F59E0B" # yellow/orange
                else:
                    bar_color = "#EF4444" # red
                    
                card_html = f"""
                <div class="rec-card">
                    <div class="card-header">
                        <div>
                            <span class="ticker-badge">{r['Ticker']}</span>
                            <div class="company-name">{r['Company Name']}</div>
                            <div class="sector-tag">{r['Sector']}</div>
                        </div>
                        <span class="action-badge {act_class}">{r['Action']}</span>
                    </div>
                    <div class="price-display">
                        <span class="price-value">IDR {r['Price']:,.0f}</span>
                        <span class="price-change {chg_class}">{chg_sign}{chg:.2f}%</span>
                    </div>
                    <div class="score-section">
                        <div class="score-header">
                            <span>Intraday Health Score</span>
                            <span style="color: {bar_color}; font-weight: bold;">{sc}/100</span>
                        </div>
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill" style="width: {sc}%; background-color: {bar_color};"></div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric-box">
                            <div class="metric-label">Target Price (TP)</div>
                            <div class="metric-value" style="color: #10B981; font-weight: bold;">IDR {r['Target Price (TP)']:,.0f}</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Stop Loss (SL)</div>
                            <div class="metric-value" style="color: #EF4444; font-weight: bold;">IDR {r['Stop Loss (SL)']:,.0f}</div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric-box">
                            <div class="metric-label">Risk/Reward (R/R)</div>
                            <div class="metric-value" style="color: #38BDF8; font-weight: bold;">{r['R/R Ratio']:.2f}x</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Max Position Size</div>
                            <div class="metric-value" style="color: #F59E0B; font-weight: bold;">{r['Max Pos']}</div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric-box">
                            <div class="metric-label">Volume Spike</div>
                            <div class="metric-value">{r['Vol Spike']:.2f}x avg</div>
                        </div>
                        <div class="metric-box">
                            <div class="metric-label">Source & Age</div>
                            <div class="metric-value" style="font-size: 0.85em; text-transform: uppercase;">{r['Source Used']}</div>
                        </div>
                    </div>
                    <div class="notes-section">
                        <b>Setup Notes:</b> {r['Notes']}
                    </div>
                </div>
                """
                html_cards += minify_html(card_html)
            html_cards += "</div>"
            st.markdown(html_cards, unsafe_allow_html=True)
        else:
            st.info("No active recommendations found. Scoring is currently under HOLD/SELL thresholds.")
    else:
        st.info("Please refresh the feed to calculate live recommendations.")