# 📈 StockPick IDX

A web dashboard and daemon sync engine built with Python and Streamlit to monitor, score, and analyze Indonesian Stock Exchange (IDX) tickers in near-realtime using orderbooks and momentum filters. **StockPick IDX** consolidates every signal into a single **Mega Score + Tier** verdict on the landing **Pick of the Day** tab.

---

## 🖥️ Streamlit Interactive Dashboard (`app.py`)

The primary frontend interface of the application. It visualizes live feeds, aggregates scores, and provides interactive deep orderbook analysis and trading calculator tools.

### 🌟 UI Key Features
1. **Brand Header + API Status Board**: New app header (gradient brand tile, title, market tag) sits above a live status board with per-source pulse dots — green connected, amber degraded/standby, red hard-down for Google Sheets / Exodus API — plus the **🔴 LIVE** / **⏸️ CLOSED** market badge and a live WIB clock.
2. **🏆 Pick of the Day (landing page)**: The unified Mega Score + Tier verdict for the whole watchlist, now augmented with the **Best-Pick Conviction Engine** (Engine E). Navigation is a lazy `st.pills` switcher — only the selected page renders and fetches, so opening a page is what triggers its network work. The Pick page builds the memoized Mega Score bundles on open (per fetch fingerprint, with a **🔄 Hitung Ulang** override). Horizon selector (Scalping / Swing-BSJP / Long Term) is persisted in session state. Each candidate expands to show:
   - 3-tier entries (`calculate_strategies`), SL/TP, position size at 1% portfolio risk
   - One-line "why" (top-2 breakdown contributors) and a signal-availability confidence badge
   - **Best-Pick detail panel**: researched IDX conviction score, ATR-based entry/SL/TP, per-factor breakdown, risk gates, and rationale
   - Filters narrow to BSJP / Minervini-PASSED / Pre-ARA / Trending candidates; a card view is available for mobile.
3. **📋 Watchlist + Portfolio**: Merges the live feed (active tickers + Stockbit overrides), the custom watchlist, and the portfolio tracker + DCA calculator into Watchlist / Holdings / DCA sections.
4. **🔍 Deep Dive (Exodus API)**: Real-time bid/ask queue details, wall detection, delta tracking, **Grounded 3-Tier Execution Strategies**, ARA-aware warnings, and live P/L cross-links — plus the **🌊 Elliott Wave** analysis folded in below as an expander. **Engine D — Trade Book Momentum** pulls the public daily trade-book chart from `exodus.stockbit.com` (per-minute cumulative buy/sell lots & values, net flow, big-money series) and re-calibrates the Aggressive / Moderate / Low Risk tiers: big-money sell ≥55% disables Aggressive and widens stops (capped cumulative SL widening ≤25%), big-money accumulation tightens them, and sell-dominant books flag caution. The Deep Dive shows a **single verdict** — Engine D when the trade book is available, otherwise Engine A — while Engine B (sentiment) and Engine C (Fibonacci) render as confirmation badges. Trade-book VWAP feeds Engine B's average-price input, and the live score consumes the Exodus imbalance ratio plus a trade-flow slot when the profile is present.
5. **📊 General Screener**: Health ranking of active stocks by Intraday Health Score, with scalping / swing / long-term sub-tables.
6. **📰 News Signals**: Restored multi-source news pipeline (Stockbit, CNBC, Kontan, Antara, Bisnis Indonesia, IDX Disclosure) with **auto-fetch on open** — because pages render lazily, clicking the News page immediately triggers a full multi-source sync (manual **Fetch All Sources** and auto-refresh still available). Includes macro-narrative detection, ticker impact tables, and per-ticker sentiment.
7. **📅 Corporate Calendar**: thin secondary tab.

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
- `ITICK_TOKEN` (optional backup source — itick.org, free plan 5 calls/minute)
- `MARKET_ALPHA_SPREADSHEET_ID` (target Google Sheet ID)

### 3. Update Token Manually
If your Bearer token expires or the automated browser login is blocked, you can use our manual helper script:
```bash
python scripts/update_token.py
```
Paste your fresh bearer token extracted from the browser's developer network tools and press **Enter** to instantly update the `.env` configuration.

### 4. Sheet Setup & Diagnostics (consolidated)
All legacy root-level `setup_*.py` / `check_*.py` scripts were consolidated into two canonical tools:

```bash
# Google Sheets setup (Dashboard [IRW] formulas / computed / watchlists)
uv run python scripts/setup_sheets.py --full
uv run python scripts/setup_sheets.py --computed
uv run python scripts/setup_sheets.py --watchlists

# One-time migration: replace =GOOGLEFINANCE(...) cells with the last cached value
uv run python scripts/setup_sheets.py --deformula --sheet-id <id> --worksheet "All Tickers"

# Diagnostics
uv run python scripts/diagnostics.py --dashboard
uv run python scripts/diagnostics.py --irw
uv run python scripts/diagnostics.py --sheets
uv run python scripts/diagnostics.py --staging
```

### 5. Freshness Engine (multi-source)
`data/fetchers.py::pick_freshest_source` (async) compares **Stockbit**, **itick.org**,
**IDX endpoint**, **Google Sheets**, and **yfinance** quotes and picks the freshest
winner:

- Freshness thresholds: Stockbit 2.0 min, itick 2.0 min, IDX 5.0 min,
  GSheet/yfinance 10.0 min.
- Tie-break within a 5s window by priority: stockbit > itick > idx > gsheet > yfinance.
- Stockbit is a guarded 4th source: 60s TTL cache per symbol + a rolling budget
  of 8 fetches per 60s window so the ~40 req/5-min token limit is never hit.
- **itick.org is a backup source** (token from `ITICK_TOKEN`): batched quotes
  are pre-fetched once per refresh (`fetch_itick_quotes_batch`, max 50 codes/call)
  and fed to the freshness engine via an in-memory dict — no per-ticker network
  calls. Deep Analysis falls back to itick Quotes + Depth when Stockbit fails.
  Free plan limited to 5 calls/minute, guarded by a rolling budget + 60s TTL
  cache; skipped silently when the token is empty or invalid (HTTP 401).
- `services/auth_service.py::get_cached_token()` returns env/cache tokens only —
  never triggers an Obscura browser login (safe for the Streamlit event loop).

---

## 📊 Formulations & Core Logic

### 1. Intraday Health Score (`compute_intraday_score`)
Calculates a stock's health on a `0–100` scale (weights sum to 1.0):
$$\text{Score} = \text{Flow} \times 0.25 + \text{Orderbook} \times 0.20 + \text{Trend} \times 0.20 + \text{Momentum} \times 0.15 + \text{Historical} \times 0.10 + \text{Risk} \times 0.10$$

- **Flow (0.25)**: volume spike tiers (0.6) + foreign buy/sell ratio tiers (0.4).
- **Orderbook (0.20)**: `Total Bid Lot` / `Total Ask Lot` from the sync-daemon-fed sheet: ≥2.5→100, ≥1.5→75, ≥0.8→50, else 20.
- **Trend (0.20)**: price vs MA20/MA50/MA200 stack (100 / 70 / 40 / 20), +10 bonus (capped at 100) when `-10 ≤ Dist to 52W High ≤ 0`.
- **Momentum (0.15)**: intraday change% tiers, ×0.75 if RSI ≥ 70, ×0.5 if RSI ≥ 75.
- **Historical (0.10)**: `Score v2` baseline (kept until the future column migration).
- **Risk (0.10)**: neutral 50.

Hard caps apply after weighting (most restrictive wins, each adds a warning):
`0 < ARA_Dist_Pct ≤ 2` → cap 55 · `UMA` set → cap 40 · `Corp Action` set → cap 60.

**Live-data overrides** (optional, backward-compatible — bots and other callers
that omit them keep the exact legacy weights/behavior):
- `imbalance_ratio` replaces the sheet-derived bid/ask ratio in the orderbook slot.
- `tradebook` (a `tradebook_profile` dict) splits the orderbook slot into
  orderbook 0.10 + **trade_flow 0.10**, where trade_flow = base(accumulating 80 /
  neutral 55 / distributing 30) + 20×net-positive-ratio ±10 momentum, capped at 40
  when big-money selling is dominant (≥55%).

All thresholds (big-money dominance, book imbalance, SL widen/tighten, TP scale,
ARA proximity 2.0%, sanity floor) live in `core/config.py` as one source of truth.

---

### 1b. Deep Dive verdict — Engine D / Engine A

The Deep Dive renders **one verdict row of 3 tier cards** (Aggressive /
Moderate / Low Risk):
- Trade book available → **Engine D** (`strategies_A` re-calibrated by
  `adjust_tiers_with_tradebook`); fallback → **Engine A** with the caption
  "Trade book tidak tersedia".
- Engine B (sentiment factor) and Engine C (Fibonacci mode/range) are
  confirmation badges, not duplicate card sets.
- Position sizing uses the shared `position_size_lots` helper (risk-first,
  capped by tier allocation).

> **Catatan audit #10 (sengaja dibiarkan):** Engine C tetap gated pada
> `intraday range ≥ 2.0%` sebelum `grounded_three_tier_C` dihitung. Ini bukan
> bug — Fib retracement pada range < 2% tidak reliabel, dan gate ini sengaja
> dipertahankan. Hanya dicatat di sini, tidak diubah.

---

### 6. Buy Verdict Consolidation (schema-stable)
**Mega Score + Tier** is the only buy verdict. The redundant verdict columns in
the sheet (`Score`, `Trend`, `Signal`, `Final_Signal`, `Rank`, `Breakout`,
`Reversal`, `Range_Signal`, `RSI Signal`, `Volume_Flag`/`Vol_Flag`, `Gap_Flag`)
are no longer read as verdicts anywhere — raw inputs (`RSI14`, `Vol_Ratio`,
`ARA_Dist_Pct`, MA stack, orderbook lots) remain supporting evidence.

A future one-shot migration will retire those columns. It is **not executed
yet** because it requires a coordinated change across three places at once:
the manifest, the sheet header, and the sync-daemon write path (see
`manifest/feature_manifest.json` → `future_migrations`). Until then the sheet
schema, manifest, integrity guard, and sync writes stay byte-for-byte
unchanged.

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

### 5. ARA/ARB Rules & Proximity (Current BEI Rules)

> **Updated Oct 2026** — reflects Kep-00003/BEI/04-2025 (8 Apr 2025) and Kep-00136/BEI/09-2026 (28 Sep 2026).

- **Auto Rejection Atas (ARA) Limit**:
  - Price $< 200 \rightarrow +35\%$
  - Price $200 - 5000 \rightarrow +25\%$
  - Price $\geq 5000 \rightarrow +20\%$
- **Auto Rejection Bawah (ARB)** — *asymmetric until 31 Dec 2026*:
  - Rp $1$ – $10$: nominal $-Rp1$
  - Price $> 10$: flat $-15\%$ across all tiers
  - *(Starting 1 Jan 2027 ARB returns to symmetric with ARA: −35% / −25% / −20%)*
- **Fraksi Harga (Tick Size)** — valid since 28 Sep 2026:
  - Rp $1$ – $< 200$: Rp $1$
  - Rp $200$ – $< 500$: Rp $2$
  - Rp $500$ – $< 2{,}000$: Rp $5$
  - Rp $2{,}000$ – $< 5{,}000$: Rp $10$
  - $\geq$ Rp $5{,}000$: Rp $25$
- **ARA Sanity Warning**:
  During ARA, orderbook bid levels below the ceiling are frequently depleted, causing algorithms to select unrealistically low prices for Moderate/Low Risk entries. The system calculates a threshold floor:
  $$\text{Floor Price} = \min(\text{Open Price}, \text{Current Price} \times (1 - 0.08))$$
  If an entry strategy suggests a level below this $\text{Floor Price}$, a warning is flagged explaining the orderbook gap due to the ARA state.

---

### 6. Best-Pick Conviction Engine (`data/recommendation.py`)

A transparent, per-horizon scoring system built from researched IDX-specific formulas. Each factor is scored 0–100. Missing data defaults to neutral 50 with reduced confidence — never fabricated.

#### Factor Formulas

| Factor | Description | Key Inputs |
|---|---|---|
| **Liquidity** | Average daily traded value gate (thin = danger) | `Vol_Avg × Price`, `value` |
| **Volatility** | ATR% sweet-spot per horizon | `ATR %`, `Daily_Range_Pct` |
| **Relative Strength** | Ticker 3M return vs IHSG 3M return | `ClosePrev`, yfinance 3M |
| **Trend Template** | Minervini Stage-2 condition count | MA20/50/200, 52W High/Low |
| **Flow** | Foreign flow + orderbook + tradebook big-money | `foreign_buy/sell`, bid/ask lots |
| **Momentum** | Intraday change% with RSI regime adjustment | `Change %`, `RSI14` |
| **Fundamental** | PE + MarketCap + Beta composite (long-term only) | `PE`, `MarketCap`, `Beta` |

#### Horizon Weights

| Factor | Scalping | Swing/BSJP | Long-term |
|---|---|---|---|
| Liquidity | 0.15 | 0.15 | 0.10 |
| Momentum | 0.25 | 0.15 | 0.10 |
| Flow | 0.25 | 0.20 | — |
| Volatility | 0.15 | 0.15 | 0.10 |
| Trend | 0.10 | 0.20 | 0.30 |
| RS vs IHSG | 0.10 | 0.15 | 0.15 |
| Fundamental | — | — | 0.25 |

#### Hard Risk Gates (most restrictive wins)

- UMA flag → cap 40
- Corporate Action → cap 60
- Near-ARA (`ARA_Dist_Pct ≤ 2%`) → cap 55
- Extreme volatility (`ATR% > 15`) → cap 50
- Illiquidity (avg value < Rp 250 M) → cap 55
- Big-money distributing + negative net flow → cap 60

#### ATR-Based Entry / SL / TP

| Tier | ATR k | Max Risk % | R/R Target |
|---|---|---|---|
| Aggressive | 1.0× ATR | 3% | 1.5x |
| Moderate | 1.5× ATR | 4% | 2.0x |
| Low Risk | 2.0× ATR | 6% | 2.5x |

SL is floored at structural support (sheet `Support` or `MA20 × 0.97`). TP is capped at **52W High** and **ARA price**. All prices are tick-aligned with the correct IDX fraksi harga.

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

### 3. Telegram Bot Cron Jobs (Mon–Fri)
Telegram credentials come from `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Run from the repo root with `uv`:

| WIB | Job | Command |
|---|---|---|
| 08:40 | 🔭 Pre-Market Watch (heuristic gap-up watch list) | `uv run python -m bot.pre_market_predictor` |
| 08:50 | ☀️ Morning Brief (pre-market) | `uv run python -c "from bot.morning import run_and_send; import asyncio; asyncio.run(run_and_send('premarket'))"` |
| 09:15 | ☀️ Morning Open (early bird) | `uv run python -c "from bot.morning import run_and_send; import asyncio; asyncio.run(run_and_send('early'))"` |
| 14:30 | 🌙 BSJP Closing Auction | `uv run python -c "from bot.bsjp import run_and_send; import asyncio; asyncio.run(run_and_send())"` |
| 16:00 | 📊 EOD Recap | `uv run python -c "from bot.eod import run_and_send; import asyncio; asyncio.run(run_and_send())"` |

Example crontab lines (adjust the repo path):

```cron
# idx-realtime-feed Telegram bots — Mon–Fri
40 8 * * 1-5  cd /path/to/idx-realtime-feed && uv run python -m bot.pre_market_predictor >> logs/cron.log 2>&1
50 8 * * 1-5  cd /path/to/idx-realtime-feed && uv run python -c "from bot.morning import run_and_send; import asyncio; asyncio.run(run_and_send('premarket'))" >> logs/cron.log 2>&1
15 9 * * 1-5  cd /path/to/idx-realtime-feed && uv run python -c "from bot.morning import run_and_send; import asyncio; asyncio.run(run_and_send('early'))" >> logs/cron.log 2>&1
30 14 * * 1-5 cd /path/to/idx-realtime-feed && uv run python -c "from bot.bsjp import run_and_send; import asyncio; asyncio.run(run_and_send())" >> logs/cron.log 2>&1
0 16 * * 1-5  cd /path/to/idx-realtime-feed && uv run python -c "from bot.eod import run_and_send; import asyncio; asyncio.run(run_and_send())" >> logs/cron.log 2>&1
```

The 08:40 job persists its rows to SQLite (`pre_market_predictions`); the Pick of the Day tab renders them read-only, and `uv run python scripts/backtest_premarket.py --days 7` recalibrates the heuristic weights.

---

## 🔒 Integrity & Security System

Protects the Google Sheets Staging database from data corruption:
1. **`ensure_integrity(ws)`**: Matches column header structures against `manifest/feature_manifest.json` before writing.
2. **`check_anti_rollback(ws)`**: Identifies if a write request has an outdated timestamp to prevent overwriting newer updates.
3. **`log_integrity_event()`**: Stores integrity check outcomes in `data/integrity_log.json`.
