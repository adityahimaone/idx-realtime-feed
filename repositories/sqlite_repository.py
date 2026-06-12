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


sqlite_repository = SQLiteRepository()
