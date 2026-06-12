# idx-realtime-feed

Near-realtime price & orderbook feed untuk IDX watchlist (10-20 ticker),
sync ke sheet `Realtime_Watchlist` di Market Alpha Dashboard.

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Watchlist Discovery (auto, every cycle)                     │
│                                                                 │
│  GET https://exodus.stockbit.com/watchlist?page=1&limit=500     │
│  └── Response: list of user's watchlists with IDs              │
│  └── Picks default watchlist (or first)                         │
│      e.g. ID 2624360 — "All Watchlist" (26 tickers)            │
│                                                                 │
│  2. Fetch Tickers                                               │
│                                                                 │
│  GET https://exodus.stockbit.com/watchlist/{id}?page=1&limit=100│
│  └── Response: array of ticker metadata                        │
│  └── Extracts symbol list: ADRO, ANTM, ARCI, ...               │
│                                                                 │
│  3. Fetch Orderbook (per ticker, with 1-4s jitter)              │
│                                                                 │
│  GET https://exodus.stockbit.com/company-price-feed/v2          │
│      /orderbook/companies/{ticker}                              │
│  └── Response: lastprice, bid[], offer[], volume, fnet, etc    │
│  └── Parsed into OrderbookSnapshot (Pydantic)                   │
│                                                                 │
│  4. Write to Google Sheets                                      │
│                                                                 │
│  ┌─ Realtime_Watchlist [IRW] ← raw snapshots (20 cols)         │
│  ├─ Dashboard [IRW]       ← computed signals (15 cols)         │
│  ├─ Dashboard Formula [IRW] ← live formulas (15 cols)          │
│  └─ Market Recap [IRW]    ← sorted signals (4 cols)            │
│                                                                 │
│  5. Staging (dual-write)                                        │
│  └─ Same data written to MAS Staging spreadsheet               │
│  └─ restore_ticker_ordering.py runs to sync ordering           │
└─────────────────────────────────────────────────────────────────┘
```

All requests require `Authorization: Bearer {token}` header.
Token from env `STOCKBIT_BEARER_TOKEN` or auto-refresh via Obscura.

## Features

- **Manifest-driven**: sheet config (columns, name) disimpan di `manifest/feature_manifest.json`
- **Integrity guard**: validate header structure sebelum write, anti-rollback timestamp check
- **Dual auth**: Google service account (primary) + OAuth user token fallback
- **Anti-burst**: jitter antar-request (1-4s), watchlist max 20 ticker
- **Dual provider**: Stockbit exodus API (primary) → RTI Business via Obscura (fallback)
- **Local history**: SQLite audit trail untuk backtest
- **Audit log**: semua integrity events di-log ke `data/integrity_log.json`

## Setup & Run

### 1. Install & Setup
```bash
# Clone & Setup
git clone <repo-url>
cd idx-realtime-feed
uv sync
uv run playwright install chromium

# Copy & Edit .env
cp .env.example .env
# Isi STOCKBIT_USERNAME, STOCKBIT_PASSWORD, MARKET_ALPHA_SPREADSHEET_ID
```

### 2. Get/Refresh Token

**Option A — CDP Script (recommended):**
```bash
# 1. Start Brave dengan remote debugging (sekali doang):
/Applications/Brave\ Browser.app/Contents/MacOS/Brave\ Browser \
    --remote-debugging-port=9222

# 2. Login ke stockbit.com di browser

# 3. Refresh token:
uv run python scripts/refresh_token.py
```

**Option B — Manual:**
Buka `https://stockbit.com/watchlist` → DevTools > Network > filter `exodus` →
Copy `Authorization: Bearer <token>` → paste ke `.env` sebagai `STOCKBIT_BEARER_TOKEN`.

### 3. Run
```bash
uv run python main.py
```

### 4. Deploy (PM2)
```bash
pm2 start main.py --interpreter python3 --name idx-realtime-feed \
    --cwd /path/to/idx-realtime-feed
```

## Structure

```
core/           config + logger
manifest/       feature_manifest.json (sheet schema definition)
providers/      data source adapters (stockbit, rti, obscura)
schemas/        pydantic models (OrderbookSnapshot, PriceLevel)
repositories/   persistence + integrity guard (Google Sheets, SQLite)
services/       orchestration (auth, sync loop)
data/           runtime data (sqlite db, integrity logs)
main.py         entrypoint
```

## Integrity System

Ported from Market Alpha Scout anti-rollback pattern:

1. **`ensure_integrity(ws)`** — validate header row matches `feature_manifest.json`
2. **`check_anti_rollback(ws)`** — detect if sheet timestamp is in the future (manual edit / concurrent writer)
3. **`log_integrity_event()`** — append audit trail to `data/integrity_log.json`

All checks run automatically before every `write_snapshots()` call.
