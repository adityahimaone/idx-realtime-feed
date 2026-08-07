"""
SQLite repository: simpan history snapshot orderbook untuk backtest /
audit trail. Skema sengaja flat (1 row = 1 snapshot) supaya mudah di-query
untuk analisa pola orderbook lo nantinya (mirip trading-journal skill).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.config import config
from schemas.orderbook import OrderbookSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orderbook_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    last_price REAL NOT NULL,
    prev_close REAL NOT NULL,
    total_bid_lot INTEGER NOT NULL,
    total_ask_lot INTEGER NOT NULL,
    imbalance_ratio REAL,
    support_price REAL,
    resistance_price REAL
);

CREATE INDEX IF NOT EXISTS idx_orderbook_ticker_ts
    ON orderbook_history (ticker, timestamp);

CREATE TABLE IF NOT EXISTS custom_watchlist (
    ticker TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    buy_price REAL NOT NULL,
    lots INTEGER NOT NULL
);

-- orderbook_snapshots: bahan multi-snapshot delta tracking
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    captured_at TEXT NOT NULL,     -- ISO8601 WIB
    side TEXT NOT NULL,            -- 'bid' | 'ask'
    price REAL NOT NULL,
    lot INTEGER NOT NULL,
    freq INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ob_ticker_time ON orderbook_snapshots(ticker, captured_at);

-- scan_history: bahan backtest & auto-journal
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    price REAL,
    intraday_score INTEGER,
    signal TEXT,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_ticker_time ON scan_history(ticker, captured_at);

-- sentiment_cache: caching LLM analysis per title hash
CREATE TABLE IF NOT EXISTS sentiment_cache (
    title_hash TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- persisted_news: news persistence for 7 days
CREATE TABLE IF NOT EXISTS persisted_news (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    ts REAL NOT NULL,
    link TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_ts ON persisted_news(ts);
-- bsjp_history: persisted closing-auction candidates (BSJP, 14:30 WIB)
CREATE TABLE IF NOT EXISTS bsjp_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,      -- WIB date YYYY-MM-DD
    tier TEXT,
    score REAL,
    cpr REAL,
    vcc REAL,
    net_foreign REAL,
    valid INTEGER,
    price REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bsjp_ticker_date ON bsjp_history (ticker, trade_date);

-- eod_snapshot: one row per scanned ticker at EOD recap (16:00 WIB)
CREATE TABLE IF NOT EXISTS eod_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,      -- WIB date YYYY-MM-DD
    chg_pct REAL,
    vol_spike REAL,
    score REAL,
    signal TEXT,
    at_ara INTEGER,
    approached_ara INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eod_ticker_date ON eod_snapshot (ticker, trade_date);

-- pre_market_predictions: heuristic pra-buka watch list (08:40 WIB)
CREATE TABLE IF NOT EXISTS pre_market_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pred_date TEXT NOT NULL,       -- WIB date YYYY-MM-DD
    ticker TEXT NOT NULL,
    score INTEGER,
    tier TEXT,
    reasons_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_premarket_date ON pre_market_predictions (pred_date, ticker);

-- pre_market_run_log: kapan job heuristic pra-buka terakhir jalan (biar UI bisa
-- membedakan "job belum jalan" vs "job sudah jalan tapi 0 kandidat")
CREATE TABLE IF NOT EXISTS pre_market_run_log (
    pred_date TEXT PRIMARY KEY,
    ran_at TEXT NOT NULL,
    n_candidates INTEGER NOT NULL
);


-- pre_market_cache: persistent TTL cache untuk fetch mahal di pre-market
-- predictor (ARA streak yfinance, news sentiment, macro context) supaya re-run
-- di hari yang sama cepat.
CREATE TABLE IF NOT EXISTS pre_market_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    expires_at REAL NOT NULL
);

"""


class SQLiteRepository:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or config.SQLITE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def save_snapshot(self, snapshot: OrderbookSnapshot) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orderbook_history (
                    ticker, timestamp, source, last_price, prev_close,
                    total_bid_lot, total_ask_lot, imbalance_ratio,
                    support_price, resistance_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.ticker,
                    snapshot.timestamp.isoformat(),
                    snapshot.source.value,
                    snapshot.last_price,
                    snapshot.prev_close,
                    snapshot.total_bid_lot,
                    snapshot.total_ask_lot,
                    snapshot.imbalance_ratio,
                    snapshot.support_price,
                    snapshot.resistance_price,
                ),
            )

    # Watchlist Persistent Methods
    def get_watchlist(self) -> list[str]:
        with self._connect() as conn:
            cursor = conn.execute("SELECT ticker FROM custom_watchlist")
            return [row[0] for row in cursor.fetchall()]

    def add_watchlist(self, ticker: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO custom_watchlist (ticker) VALUES (?)", (ticker.upper().strip(),))

    def remove_watchlist(self, ticker: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM custom_watchlist WHERE ticker = ?", (ticker.upper().strip(),))

    def clear_watchlist(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM custom_watchlist")

    # Portfolio Persistent Methods
    def get_portfolio(self) -> list[dict]:
        with self._connect() as conn:
            cursor = conn.execute("SELECT id, ticker, buy_price, lots FROM portfolio")
            return [
                {"id": row[0], "Ticker": row[1], "Buy Price": row[2], "Lots": row[3]}
                for row in cursor.fetchall()
            ]

    def add_portfolio(self, ticker: str, buy_price: float, lots: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO portfolio (ticker, buy_price, lots) VALUES (?, ?, ?)",
                (ticker.upper().strip(), buy_price, lots),
            )

    def remove_portfolio_by_id(self, item_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM portfolio WHERE id = ?", (item_id,))

    def remove_portfolio_by_ticker(self, ticker: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker.upper().strip(),))

    def clear_portfolio(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM portfolio")

    # Orderbook Snapshots Persistent Methods
    def save_orderbook_snapshot(self, ticker: str, side: str, price: float, lot: int, freq: int = 0) -> None:
        import datetime
        now = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orderbook_snapshots (ticker, captured_at, side, price, lot, freq)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ticker.upper().strip(), now, side, price, lot, freq)
            )

    def get_latest_orderbook_snapshots(self, ticker: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT side, price, lot, freq, captured_at FROM orderbook_snapshots
                WHERE ticker = ?
                ORDER BY captured_at DESC, price ASC
                LIMIT ?
                """,
                (ticker.upper().strip(), limit)
            )
            return [
                {"side": row[0], "price": row[1], "lot": row[2], "freq": row[3], "captured_at": row[4]}
                for row in cursor.fetchall()
            ]

    # Scan History Persistent Methods
    def save_scan_history_if_changed(
        self, ticker: str, price: float, intraday_score: int, signal: str,
        source: str, cooldown_minutes: int = 15,
    ) -> bool:
        """Log a scan row only when the signal changed within the cooldown window.

        App reruns Streamlit scripts on every interaction, so logging on every
        call would insert a row per ticker per rerun — unbounded DB growth and a
        churning cache key for the track-record forward-returns computation.
        Returns True when a row was actually inserted.
        """
        import datetime
        ticker = ticker.upper().strip()
        now = datetime.datetime.now().isoformat()
        window = (datetime.datetime.now() - datetime.timedelta(minutes=cooldown_minutes)).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT signal FROM scan_history WHERE ticker = ? AND captured_at >= ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (ticker, window),
            ).fetchone()
            if row and row[0] == signal:
                return False
            conn.execute(
                "INSERT INTO scan_history (ticker, captured_at, price, intraday_score, signal, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, now, price, intraday_score, signal, source),
            )
            return True

    def save_scan_history(self, ticker: str, price: float, intraday_score: int, signal: str, source: str) -> None:
        import datetime
        now = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scan_history (ticker, captured_at, price, intraday_score, signal, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ticker.upper().strip(), now, price, intraday_score, signal, source)
            )

    def get_scan_history(self, ticker: str, minutes_ago: int = 15) -> list[dict]:
        import datetime
        t = (datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT price, intraday_score, signal, captured_at FROM scan_history
                WHERE ticker = ? AND captured_at >= ?
                ORDER BY captured_at DESC
                """,
                (ticker.upper().strip(), t)
            )
            return [
                {"price": row[0], "intraday_score": row[1], "signal": row[2], "captured_at": row[3]}
                for row in cursor.fetchall()
            ]

    def get_scan_history_all(self, ticker: str | None = None,
                             signal_filter: tuple[str, ...] | None = None,
                             limit: int = 1000) -> list[dict]:
        """Return logged scan-history rows (track-record / backtest feed).

        Uses the existing scan_history table only — no schema migration.
        """
        sql = "SELECT ticker, captured_at, price, intraday_score, signal, source FROM scan_history"
        params: list = []
        conditions = []
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker.upper().strip())
        if signal_filter:
            placeholders = ",".join("?" for _ in signal_filter)
            conditions.append(f"signal IN ({placeholders})")
            params.extend(signal_filter)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY captured_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            return [
                {"ticker": r[0], "captured_at": r[1], "price": r[2],
                 "intraday_score": r[3], "signal": r[4], "source": r[5]}
                for r in cursor.fetchall()
            ]


    # BSJP History Methods
    def save_bsjp_result(self, ticker: str, trade_date: str, tier: str, score: float,
                         cpr: float, vcc: float, net_foreign: float, valid: bool,
                         price: float) -> None:
        """Persist one BSJP closing-auction candidate (WIB trade date)."""
        import datetime
        now = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bsjp_history (
                    ticker, trade_date, tier, score, cpr, vcc, net_foreign,
                    valid, price, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker.upper().strip(), trade_date, tier, score, cpr, vcc,
                    net_foreign, 1 if valid else 0, price, now,
                ),
            )

    def get_last_bsjp_result(self, ticker: str) -> dict | None:
        """Latest BSJP result for a ticker (newest trade_date, tie-break id DESC)."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT ticker, trade_date, tier, score, cpr, vcc, net_foreign,
                       valid, price
                FROM bsjp_history
                WHERE ticker = ?
                ORDER BY trade_date DESC, id DESC
                LIMIT 1
                """,
                (ticker.upper().strip(),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "ticker": row[0], "trade_date": row[1], "tier": row[2],
                "score": row[3], "cpr": row[4], "vcc": row[5],
                "net_foreign": row[6], "valid": bool(row[7]), "price": row[8],
            }

    # EOD Snapshot Methods
    def save_eod_snapshot(self, trade_date: str, rows: list[dict]) -> None:
        """Persist one EOD row per scanned ticker (WIB trade date)."""
        import datetime
        now = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            for r in rows:
                conn.execute(
                    """
                    INSERT INTO eod_snapshot (
                        ticker, trade_date, chg_pct, vol_spike, score, signal,
                        at_ara, approached_ara, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["ticker"].upper().strip(), trade_date,
                        r.get("chg_pct"), r.get("vol_spike"), r.get("score"),
                        r.get("signal"), 1 if r.get("at_ara") else 0,
                        1 if r.get("approached_ara") else 0, now,
                    ),
                )

    def get_eod_snapshot(self, trade_date: str) -> list[dict]:
        """EOD rows for a given WIB date."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT ticker, chg_pct, vol_spike, score, signal, at_ara, approached_ara
                FROM eod_snapshot
                WHERE trade_date = ?
                ORDER BY score DESC
                """,
                (trade_date,),
            )
            return [
                {
                    "ticker": r[0], "chg_pct": r[1], "vol_spike": r[2],
                    "score": r[3], "signal": r[4], "at_ara": bool(r[5]),
                    "approached_ara": bool(r[6]),
                }
                for r in cursor.fetchall()
            ]

    # Pre-Market Prediction Methods
    def save_premarket_predictions(self, pred_date: str, rows: list[dict]) -> None:
        """Replace a date's heuristic pre-market predictions (idempotent reruns)."""
        import datetime
        now = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM pre_market_predictions WHERE pred_date = ?", (pred_date,))
            for r in rows:
                conn.execute(
                    """
                    INSERT INTO pre_market_predictions (
                        pred_date, ticker, score, tier, reasons_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pred_date, r["ticker"].upper().strip(), r.get("score"),
                        r.get("tier"),
                        json.dumps(r.get("reasons", []), ensure_ascii=False),
                        now,
                    ),
                )

    def get_premarket_predictions(self, pred_date: str) -> list[dict]:
        """Heuristic pre-market predictions for a given WIB date."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT ticker, score, tier, reasons_json
                FROM pre_market_predictions
                WHERE pred_date = ?
                ORDER BY score DESC, id ASC
                """,
                (pred_date,),
            )
            return [
                {
                    "ticker": r[0], "score": r[1], "tier": r[2],
                    "reasons": json.loads(r[3]) if r[3] else [],
                }
                for r in cursor.fetchall()
            ]

    def get_premarket_predictions_all(self, limit: int = 500) -> list[dict]:
        """All pre-market prediction rows, newest date first (backtest feed)."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT pred_date, ticker, score, tier, reasons_json
                FROM pre_market_predictions
                ORDER BY pred_date DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "pred_date": r[0], "ticker": r[1], "score": r[2],
                    "tier": r[3], "reasons": json.loads(r[4]) if r[4] else [],
                }
                for r in cursor.fetchall()
            ]

    def save_premarket_run(self, pred_date: str, n_candidates: int, ran_at: str | None = None) -> None:
        """Record that the heuristic pre-market job ran for a date (idempotent)."""
        import datetime
        if ran_at is None:
            ran_at = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pre_market_run_log (pred_date, ran_at, n_candidates)
                VALUES (?, ?, ?)
                """,
                (pred_date, ran_at, n_candidates),
            )

    def get_premarket_run(self, pred_date: str) -> dict | None:
        """Last run info for a WIB date, or None if the job never ran."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT pred_date, ran_at, n_candidates FROM pre_market_run_log WHERE pred_date = ?",
                (pred_date,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {"pred_date": row[0], "ran_at": row[1], "n_candidates": row[2]}

    def cache_get(self, cache_key: str, now_ts: float | None = None) -> str | None:
        """Return a non-expired cached payload, or None."""
        import time
        now_ts = now_ts if now_ts is not None else time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM pre_market_cache WHERE cache_key = ? AND expires_at > ?",
                (cache_key, now_ts),
            ).fetchone()
            return row[0] if row else None

    def cache_set(self, cache_key: str, payload: str, ttl_sec: int) -> None:
        """Upsert a cached payload with TTL, pruning expired rows along the way."""
        import time
        now_ts = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM pre_market_cache WHERE expires_at <= ?", (now_ts,))
            conn.execute(
                "INSERT OR REPLACE INTO pre_market_cache (cache_key, payload, expires_at) VALUES (?, ?, ?)",
                (cache_key, payload, now_ts + ttl_sec),
            )

    # Sentiment Cache Methods
    def get_cached_sentiment(self, title_hash: str) -> str | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT label FROM sentiment_cache WHERE title_hash = ?", (title_hash,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def save_cached_sentiment(self, title_hash: str, label: str) -> None:
        import datetime
        now = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sentiment_cache (title_hash, label, created_at)
                VALUES (?, ?, ?)
                """,
                (title_hash, label, now)
            )

    # Persisted News Methods (7 days persistence)
    def save_news_articles(self, articles: list[dict]) -> None:
        import datetime
        now = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            for art in articles:
                art_id = art.get("id") or str(hash(art["title"] + str(art.get("ts", 0))))
                conn.execute(
                    """
                    INSERT OR IGNORE INTO persisted_news (id, title, source, ts, link, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (art_id, art["title"], art["source"], art.get("ts", 0.0), art.get("link", ""), now)
                )

    def get_persisted_news(self) -> list[dict]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT title, source, ts, link FROM persisted_news ORDER BY ts DESC"
            )
            return [
                {"title": row[0], "source": row[1], "ts": row[2], "link": row[3]}
                for row in cursor.fetchall()
            ]

    def prune_old_news(self, days: int = 7) -> None:
        import time
        limit_ts = time.time() - (days * 24 * 3600)
        with self._connect() as conn:
            conn.execute("DELETE FROM persisted_news WHERE ts < ?", (limit_ts,))


sqlite_repository = SQLiteRepository()
