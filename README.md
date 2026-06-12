# idx-realtime-feed

Near-realtime price & orderbook feed untuk IDX watchlist (10-20 ticker),
sync ke sheet `Realtime_Watchlist` di Market Alpha Dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    main.py (asyncio)                     │
│                         │                               │
│              ┌──────────┴──────────┐                    │
│              │   sync_service.py   │ ← orchestrator     │
│              └──────────┬──────────┘                    │
│         ┌───────────────┼───────────────┐               │
│         ▼               ▼               ▼               │
│   ┌───────────┐  ┌────────────┐  ┌───────────┐         │
│   │ Stockbit  │  │    RTI     │  │  Obscura  │         │
│   │ Provider  │  │  Provider  │  │  Client   │         │
│   │  (httpx)  │  │(playwright)│  │   (CDP)   │         │
│   └─────┬─────┘  └─────┬──────┘  └─────┬─────┘         │
│         │               │               │               │
│         ▼               ▼               │               │
│   exodus API       RTI Business ◄───────┘               │
│                                                         │
│              ┌──────────┴──────────┐                    │
│              │    auth_service     │                     │
│              │  (Obscura login +   │                     │
│              │   token caching)    │                     │
│              └─────────────────────┘                    │
│                                                         │
│              ┌──────────────────────────┐               │
│              │     Repositories          │               │
│              │  ┌────────────────────┐  │               │
│              │  │ sheets_repository  │──┼─► Google Sheets│
│              │  │ (integrity guard)  │  │               │
│              │  └────────────────────┘  │               │
│              │  ┌────────────────────┐  │               │
│              │  │ sqlite_repository  │──┼─► Local DB    │
│              │  └────────────────────┘  │               │
│              └──────────────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

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
