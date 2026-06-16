"""
SQLite repository: simpan history snapshot orderbook untuk backtest /
audit trail. Skema sengaja flat (1 row = 1 snapshot) supaya mudah di-query
untuk analisa pola orderbook lo nantinya (mirip trading-journal skill).
"""

from __future__ import annotations

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
