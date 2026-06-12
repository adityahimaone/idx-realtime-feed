"""
Schema untuk orderbook snapshot per ticker.

Field-field ini dipetakan langsung ke framework analisa 3-tier
(Aggressive / Moderat / Low Risk):
- total_bid_lot / total_ask_lot -> sentimen bid vs ask
- imbalance_ratio               -> bid/ask comparison
- support_price / resistance_price -> diambil dari level dengan lot terbesar
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PriceLevel(BaseModel):
    """Satu level harga di orderbook (bid atau ask)."""

    price: float
    lot: int
    freq: int = 0  # jumlah transaksi di level ini, kalau tersedia dari provider


class DataSource(str, Enum):
    STOCKBIT = "stockbit"
    RTI = "rti"


class OrderbookSnapshot(BaseModel):
    """Snapshot orderbook untuk satu ticker pada satu titik waktu."""

    ticker: str
    timestamp: datetime
    source: DataSource

    last_price: float
    prev_close: float

    bid_levels: list[PriceLevel] = Field(default_factory=list)
    ask_levels: list[PriceLevel] = Field(default_factory=list)

    @property
    def total_bid_lot(self) -> int:
        return sum(level.lot for level in self.bid_levels)

    @property
    def total_ask_lot(self) -> int:
        return sum(level.lot for level in self.ask_levels)

    @property
    def imbalance_ratio(self) -> float | None:
        """Bid lot / ask lot. None kalau ask_lot == 0 (hindari div by zero)."""
        if self.total_ask_lot == 0:
            return None
        return round(self.total_bid_lot / self.total_ask_lot, 2)

    @property
    def support_price(self) -> float | None:
        """Harga bid dengan lot terbesar -> dianggap support."""
        if not self.bid_levels:
            return None
        return max(self.bid_levels, key=lambda lvl: lvl.lot).price

    @property
    def resistance_price(self) -> float | None:
        """Harga ask dengan lot terbesar -> dianggap resistance."""
        if not self.ask_levels:
            return None
        return max(self.ask_levels, key=lambda lvl: lvl.lot).price

    @property
    def change_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return round((self.last_price - self.prev_close) / self.prev_close * 100, 2)
