"""Schema untuk orderbook snapshot per ticker.

Field-field ini dipetakan langsung ke framework analisa 3-tier
(Aggressive / Moderat / Low Risk):
- total_bid_lot / total_ask_lot -> sentimen bid vs ask
- imbalance_ratio               -> bid/ask comparison
- support_price / resistance_price -> diambil dari level dengan lot terbesar
- fbuy / fsell / fnet           -> foreign flow
- ara / arb                     -> auto-rejection limits
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PriceLevel(BaseModel):
    price: float
    lot: int
    freq: int = 0


class DataSource(str, Enum):
    STOCKBIT = "stockbit"
    RTI = "rti"


class OrderbookSnapshot(BaseModel):
    ticker: str
    timestamp: datetime
    source: DataSource

    last_price: float
    prev_close: float
    high: float = 0.0
    low: float = 0.0
    open_price: float = 0.0
    change: int = 0
    volume: float = 0.0

    # New fields from company-price-feed v2
    fbuy: float = 0.0
    fsell: float = 0.0
    fnet: float = 0.0
    ara_price: float = 0.0
    arb_price: float = 0.0
    frequency: int = 0
    value: float = 0.0
    average_price: float = 0.0

    bid_levels: list[PriceLevel] = Field(default_factory=list)
    ask_levels: list[PriceLevel] = Field(default_factory=list)

    prices: list[float] = Field(default_factory=list)
    uma: bool = False
    corp_action_active: bool = False
    corp_action_text: str = ""
    name: str = ""

    @property
    def total_bid_lot(self) -> int:
        return sum(level.lot for level in self.bid_levels)

    @property
    def total_ask_lot(self) -> int:
        return sum(level.lot for level in self.ask_levels)

    @property
    def imbalance_ratio(self) -> float | None:
        if self.total_ask_lot == 0:
            return None
        return round(self.total_bid_lot / self.total_ask_lot, 2)

    @property
    def support_price(self) -> float | None:
        if not self.bid_levels:
            return None
        return max(self.bid_levels, key=lambda lvl: lvl.lot).price

    @property
    def resistance_price(self) -> float | None:
        if not self.ask_levels:
            return None
        return max(self.ask_levels, key=lambda lvl: lvl.lot).price

    @property
    def change_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return round((self.last_price - self.prev_close) / self.prev_close * 100, 2)

    @property
    def best_bid(self) -> float | None:
        if not self.bid_levels:
            return None
        return max(lvl.price for lvl in self.bid_levels)

    @property
    def best_ask(self) -> float | None:
        if not self.ask_levels:
            return None
        return min(lvl.price for lvl in self.ask_levels)

    @property
    def spread(self) -> float | None:
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None or self.last_price == 0:
            return None
        return round((ba - bb) / self.last_price * 100, 2)

    @property
    def bid_ask_ratio(self) -> float | None:
        a = self.total_ask_lot
        if a == 0:
            return None
        return round(self.total_bid_lot / a, 2)

    @property
    def ara_distance_pct(self) -> float | None:
        if self.ara_price == 0 or self.last_price == 0:
            return None
        return round((self.ara_price - self.last_price) / self.last_price * 100, 2)

    @property
    def arb_distance_pct(self) -> float | None:
        if self.arb_price == 0 or self.last_price == 0:
            return None
        return round((self.last_price - self.arb_price) / self.last_price * 100, 2)
