# idx-realtime-feed

Near-realtime price & orderbook feed untuk IDX watchlist (10-20 ticker), sync ke sheet `Realtime_Watchlist` di Market Alpha Dashboard.

---

## 🖥️ Streamlit Interactive Dashboard (`app.py`)

Aplikasi dashboard web berbasis Streamlit untuk visualisasi data realtime multi-sumber, screening intraday, dan analisis orderbook mendalam.

### Fitur Utama Dashboard:
1. **API Status Board**: Tampilan panel di bagian atas dengan animasi pulse hijau/kuning untuk memantau status keaktifan koneksi ke Google Sheets, Yahoo Finance, IDX endpoint, dan Stockbit Exodus API. Label **🔴 LIVE** otomatis menyala saat jam perdagangan bursa (day trade) dan beralih ke **⏸️ CLOSED** di luar jam bursa.
2. **Tab 1: Displaying Tickers**: Menampilkan seluruh emiten aktif beserta data harga awal yang dimuat secara instan dari spreadsheet MAS Staging "All Tickers".
3. **Tab 2: Intraday Buy Recommendations**: Menampilkan 30 rekomendasi pembelian teratas berkategori "STRONG BUY" yang dilengkapi visualisasi card premium, detail target (TP), batas risiko (SL) berbasis ATR, rasio risk/reward, dan info kesegaran sumber data.
4. **Tab 3: General Screener Board**: Tabel pemeringkatan skor kesehatan intraday (Intraday Health Score) dari seluruh ticker yang memenuhi kriteria filter watchlist.
5. **Tab 4: Deep Stock Analysis (Exodus API)**: Kolom pencarian interaktif untuk menarik data bid/ask queue terdalam serta kalkulasi strategi eksekusi 3-tier dari Exodus API secara langsung.
6. **Double Sync Buttons**:
   - **`🔄 Refresh Live Feed (Multi)`**: Mengambil data ter-update menggunakan pipeline ke Google Sheets, Yahoo Finance, dan IDX Trading Summary.
   - **`🚀 Refresh Live Feed (Stockbit)`**: Melakukan polling batch ke Stockbit Exodus API secara langsung untuk menarik data live.

### Cara Menjalankan Dashboard:
```bash
uv run streamlit run app.py --server.port 8501
```

---

## ⚙️ Daemon Sync Scripts (Backend Engine)

Kumpulan script otomatisasi yang berjalan di latar belakang (daemon) untuk memperbarui data orderbook dan menulisnya ke Google Sheets.

### 1. Full Mode Sync (`main.py`)
Melakukan sinkronisasi menyeluruh dengan mengambil data kedalaman orderbook (bids/asks queue) per ticker secara berkala.
- **Jalan satu kali:** `uv run python main.py`
- **Deploy via PM2:**
  ```bash
  pm2 start main.py --interpreter python3 --name idx-realtime-feed --cwd /path/to/idx-realtime-feed
  ```

### 2. Light Mode Sync (`main_light.py`)
Versi ringan yang meng-update watchlist dalam satu request tunggal (batch-fetch) untuk efisiensi jaringan dan meminimalisir kemungkinan kena rate-limit API Stockbit.
- **Jalan satu kali:** `uv run python main_light.py`
- **Deploy via PM2:**
  ```bash
  pm2 start main_light.py --interpreter python3 --name idx-realtime-feed-light --cwd /path/to/idx-realtime-feed
  ```

### 3. Ticker Analysis CLI (`ticker.py` & `ticker_stream.py`)
* **`ticker.py` (Single-run CLI)**: Menganalisis kedalaman bid/ask bursa untuk satu ticker tertentu menggunakan formulasi strategi 3-tier (Aggressive, Moderat, Low Risk) dengan validasi IDX tick rules dan pembatasan risk <= 4%.
  ```bash
  uv run python ticker.py BBCA
  ```
* **`ticker_stream.py` (Streaming CLI)**: Menganalisis ticker tertentu secara streaming (memperbarui visualisasi setiap 5 detik di CLI console).
  ```bash
  uv run python ticker_stream.py BBCA
  ```

---

## 📊 Data Flow & Architecture

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

## 🛠️ Setup & Prerequisites

### 1. Install Dependencies
```bash
git clone <repo-url>
cd idx-realtime-feed
uv sync
uv run playwright install chromium

# Copy & Edit .env
cp .env.example .env
# Isi STOCKBIT_USERNAME, STOCKBIT_PASSWORD, MARKET_ALPHA_SPREADSHEET_ID
```

### 2. Dapatkan/Perbarui Token
**Option A — CDP Script (direkomendasikan):**
```bash
# 1. Start Brave/Chrome dengan remote debugging:
/Applications/Brave\ Browser.app/Contents/MacOS/Brave\ Browser --remote-debugging-port=9222

# 2. Login ke stockbit.com di browser tersebut.
# 3. Jalankan script refresh:
uv run python scripts/refresh_token.py
```

---

## 🔒 Integrity & Security System

Sistem perlindungan terintegrasi sebelum melakukan proses write ke Google Sheets:
1. **`ensure_integrity(ws)`** — Validasi struktur header kolom dengan `feature_manifest.json`.
2. **`check_anti_rollback(ws)`** — Deteksi clock skew / tabrakan writer lain berdasarkan timestamp pengeditan.
3. **`log_integrity_event()`** — Melacak jejak audit integritas pada `data/integrity_log.json`.
