# 🔍 IDX Intraday Multi-Source Screener [IRW]

A web dashboard and daemon sync engine built with Python and Streamlit to monitor, score, and analyze Indonesian Stock Exchange (IDX) tickers in near-realtime using orderbooks and momentum filters.

---

## 🖥️ Streamlit Interactive Dashboard (`app.py`)

The primary frontend interface of the application. It visualizes live feeds, aggregates scores, and provides interactive deep orderbook analysis and trading calculator tools.

### 🌟 UI Key Features
1. **API Status Board**: Located at the top of the interface. Displays dynamic pulses (green/yellow) showing live connectivity stats for Google Sheets, Yahoo Finance, IDX, and Stockbit. Displays **🔴 LIVE** during market trading hours and switch to **⏸️ CLOSED** after hours.
2. **Tab 1: Live Feed / Watchlist**: Displays active tickers and real-time pricing retrieved from the Google Sheets Staging database.
3. **Tab 2: Recommendations**: Highlights top candidates marked with `STRONG BUY` signals, suggesting stop losses, targets, and risk/reward setups.
4. **Tab 3: General Screener Board**: Health ranking list of all active stocks sorted by their Intraday Health Score.
5. **Tab 4: Trending**: Displays trending tickers in the market.
6. **Tab 5: BSJP Setup**: Big Spurt Jump Play (BSJP) setups.
7. **Tab 6: Minervini VCP**: Screen stocks matching Mark Minervini's volatility contraction pattern.
8. **Tab 7: Deep Stock Analysis (Exodus API)**: 
   - Real-time bid/ask queue details direct from Exodus API.
   - Detects bid/ask walls and tracks order volume delta.
   - Visualizes **Grounded 3-Tier Execution Strategies**.
   - Proactively shows warnings if orderbook entry prices are distorted by ARA price ceilings.
   - Cross-links to the Portfolio tab for active positions, displaying current live P/L.
9. **💼 Live Portfolio Tracker & DCA Calculator**:
   - Track active holdings, invested value, current value, and profit/loss in real-time.
   - **Average Down Calculator**: Simulate adding lots to an existing position. Automatically computes the weighted average buy price, new breakeven distance, and ticker risk concentration. Warns when a single ticker represents >25% of the total portfolio value. Apply average down directly to update the database with a single click.

### 🚀 How to Run, Stop, and Restart the Dashboard:

**Start the dashboard:**
```bash
uv run streamlit run app.py --server.port 8501
```

**Stop the dashboard running on port 8501:**
```bash
kill -9 $(lsof -t -i:8501)
```

**Restart the dashboard (force-kills port 8501 and restarts):**
```bash
kill -9 $(lsof -t -i:8501) 2>/dev/null; uv run streamlit run app.py --server.port 8501
```

---

## 🛠️ Installation & Setup

### 1. Install Dependencies
Ensure you have `uv` installed, then clone the repository and install the environment:
```bash
git clone <repo-url>
cd idx-realtime-feed
uv sync
uv run playwright install chromium
```

### 2. Configure Environment Files
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```
Key configuration parameters:
- `STOCKBIT_USERNAME` / `STOCKBIT_PASSWORD` (used for headless authentication)
- `STOCKBIT_BEARER_TOKEN` (automatically managed or pasted manually)
- `MARKET_ALPHA_SPREADSHEET_ID` (target Google Sheet ID)

### 3. Update Token Manually
If your Bearer token expires or the automated browser login is blocked, you can use our manual helper script:
```bash
python update_token.py
```
Paste your fresh bearer token extracted from the browser's developer network tools and press **Enter** to instantly update the `.env` configuration.

---

## 📊 Formulations & Core Logic

### 1. Intraday Health Score (`compute_intraday_score`)
Calculates a stock's health on a `0–100` scale. The score is computed as a weighted average of:
$$\text{Score} = (\text{Volume Score} \times 0.25) + (\text{Net Foreign Score} \times 0.25) + (\text{Price Change Score} \times 0.20) + (\text{Spread Score} \times 0.15) + (\text{Historical Score} \times 0.15)$$

- **Volume Score**: Compares live trading volume against historical average volume (Vol Spike):
  - $\text{Spike} \geq 3.0 \rightarrow 100$
  - $\text{Spike} \geq 2.0 \rightarrow 80$
  - $\text{Spike} \geq 1.5 \rightarrow 60$
  - $\text{Spike} \geq 1.0 \rightarrow 40$
  - $\text{Otherwise} \rightarrow 20$
- **Net Foreign Score**: Ratio of foreign buy volume vs foreign sell volume.
- **Price Change Score**: Score given depending on intraday price growth.
- **Spread Score**: Calculated using position in the day's high-low range:
  $$\text{Spread Score} = 40 + \left( \frac{\text{Last} - \text{Low}}{\text{High} - \text{Low}} \right) \times 60$$

---

### 2. Grounded 3-Tier Execution Strategies
Uses active bid/ask walls in the orderbook depth to calculate support and entry points:
- **Aggressive (Breakout Play)**: Targets entry directly at the breakout level.
- **Moderate (Pullback Play)**: Targets entry near intermediate bid walls.
- **Low Risk (Support Buy)**: Targets entry near the strongest base support level.

---

### 3. Risk-First Position Sizing
Positions are sized dynamically to cap trade risk to exactly **1.0%** of total portfolio value:
$$\text{Lots}_{\text{risk}} = \frac{\text{Base Portfolio} \times 0.01}{(\text{Entry Price} - \text{Stop Loss Price}) \times 100}$$

This risk-based sizing is double-barrier-protected by capping the lot size to a maximum capital allocation percentage limit:
$$\text{Lots}_{\text{cap}} = \frac{\text{Base Portfolio} \times \text{Allocation \%}}{\text{Entry Price} \times 100}$$
$$\text{Lots} = \min(\text{Lots}_{\text{risk}}, \text{Lots}_{\text{cap}})$$
*(Allocation limits: Aggressive = 10%, Moderate = 15%, Low Risk = 20%)*

---

### 4. Average Down / DCA Formula
Computes the exact new average buy price when purchasing additional lots:
$$\text{New Average Buy Price} = \frac{(\text{Old Average} \times \text{Old Lots} \times 100) + (\text{Purchase Price} \times \text{New Lots Purchase} \times 100)}{(\text{Old Lots} + \text{New Lots Purchase}) \times 100}$$

---

### 5. ARA/ARB Rules & Proximity
- **Auto Rejection Atas (ARA) Limit**:
  - Price $< 200 \rightarrow 35\%$
  - Price $200 - 5000 \rightarrow 25\%$
  - Price $\geq 5000 \rightarrow 20\%$
- **Auto Rejection Bawah (ARB)**: Flat $-7\%$ across all price tiers.
- **ARA Sanity Warning**:
  During ARA, orderbook bid levels below the ceiling are frequently depleted, causing algorithms to select unrealistically low prices for Moderate/Low Risk entries. The system calculates a threshold floor:
  $$\text{Floor Price} = \min(\text{Open Price}, \text{Current Price} \times (1 - 0.08))$$
  If an entry strategy suggests a level below this $\text{Floor Price}$, a warning is flagged explaining the orderbook gap due to the ARA state.

---

## ⚙️ Daemon Sync Scripts & CLIs

Backend scripts intended to run persistently or as CLI tools.

### 1. Persistent Daemons (Backend Engines)
- **Full Mode Sync (`main.py`)**: Continuously syncs orderbook depths, bids, asks queue, and computed metrics to Google Sheets.
  - Run manually: `uv run python main.py`
  - Deploy with PM2:
    ```bash
    pm2 start main.py --interpreter python3 --name idx-realtime-feed --cwd /path/to/idx-realtime-feed
    ```
- **Light Mode Sync (`main_light.py`)**: Light mode script that queries tickers in batches to reduce network requests and stay safe from API rate limits.
  - Run manually: `uv run python main_light.py`
  - Deploy with PM2:
    ```bash
    pm2 start main_light.py --interpreter python3 --name idx-realtime-feed-light --cwd /path/to/idx-realtime-feed
    ```

### 2. Ticker Analysis CLIs
- **`ticker.py`**: Runs a single-run analysis on a selected stock in your terminal.
  ```bash
  uv run python ticker.py BBCA
  ```
- **`ticker_stream.py`**: Stream orderbook details directly inside the console, refreshing every 5 seconds.
  ```bash
  uv run python ticker_stream.py BBCA
  ```

---

## 🔒 Integrity & Security System

Protects the Google Sheets Staging database from data corruption:
1. **`ensure_integrity(ws)`**: Matches column header structures against `manifest/feature_manifest.json` before writing.
2. **`check_anti_rollback(ws)`**: Identifies if a write request has an outdated timestamp to prevent overwriting newer updates.
3. **`log_integrity_event()`**: Stores integrity check outcomes in `data/integrity_log.json`.
