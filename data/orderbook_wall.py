"""
Wall Detection & Multi-Snapshot Delta Tracking Engine.
Mengimplementasikan metodologi orderbook kamu: wall detection, delta
tracking, dan three-tier entry (Aggressive/Moderat/Low Risk) yang
grounded di support/resistance riil, bukan persentase arbitrary.
"""
from dataclasses import dataclass
from statistics import mean, median

@dataclass
class OrderbookLevel:
    price: float
    lot: int
    freq: int = 0

@dataclass
class WallSignal:
    price: float
    lot: int
    side: str             # "bid" | "ask"
    strength: float        # 0-100
    classification: str    # "Building" | "Pulled" | "Eaten" | "Static" | "New"

def detect_walls(levels: list[OrderbookLevel], side: str, k: float = 1.5) -> list[WallSignal]:
    """Flag level dengan lot volume jauh di atas rata-rata book."""
    if not levels:
        return []
    lots = [lv.lot for lv in levels]
    avg_lot = mean(lots)
    med_lot = median(lots)
    threshold = max(avg_lot + k * (max(lots) - avg_lot) * 0.3, med_lot * 3)

    walls = []
    for lv in levels:
        if lv.lot >= threshold and lv.lot > 0:
            strength = min(100.0, round((lv.lot / max(avg_lot, 1)) * 20, 1))
            walls.append(WallSignal(price=lv.price, lot=lv.lot, side=side,
                                     strength=strength, classification="Static"))
    return walls

def track_delta(prev_levels: list[OrderbookLevel], curr_levels: list[OrderbookLevel],
                 last_trade_price: float, side: str) -> list[WallSignal]:
    """Bandingkan dua snapshot sisi yang sama, klasifikasi perilaku tiap level."""
    prev_map = {lv.price: lv.lot for lv in prev_levels}
    signals = []
    for lv in curr_levels:
        prev_lot = prev_map.get(lv.price, 0)
        delta = lv.lot - prev_lot

        if prev_lot == 0 and lv.lot > 0:
            cls = "New"
        elif delta > 0:
            cls = "Building"
        elif delta < -0.5 * max(prev_lot, 1):
            crossed = (side == "bid" and last_trade_price <= lv.price) or \
                      (side == "ask" and last_trade_price >= lv.price)
            cls = "Eaten" if crossed else "Pulled"
        else:
            cls = "Static"

        if cls in ("Building", "Eaten", "Pulled", "New"):
            strength = min(100.0, round(abs(delta) / max(prev_lot, lv.lot, 1) * 100, 1))
            signals.append(WallSignal(price=lv.price, lot=lv.lot, side=side,
                                       strength=strength, classification=cls))
    return signals

def grounded_three_tier(price: float, bid_walls: list[WallSignal],
                         ask_walls: list[WallSignal]) -> dict:
    """Bangun level Aggressive/Moderat/Low Risk dari wall RIIL, bukan % arbitrary."""
    strongest_bid = max(bid_walls, key=lambda w: w.lot, default=None)
    strongest_ask = max(ask_walls, key=lambda w: w.lot, default=None)

    resistance = strongest_ask.price if strongest_ask else round(price * 1.05, 0)
    support = strongest_bid.price if strongest_bid else round(price * 0.95, 0)

    agg_entry = price
    agg_tp = resistance
    agg_sl = round(price * 0.97, 0)
    
    mod_entry = round((price + support) / 2, 0)
    mod_tp, mod_sl = resistance, round(support * 0.98, 0)
    low_entry, low_sl = support, round(support * 0.97, 0)
    low_tp = round((support + resistance) / 2, 0)

    def rr(entry, tp, sl):
        return round((tp - entry) / max(entry - sl, 1), 2)

    return {
        "Aggressive": {"entry": agg_entry, "tp": agg_tp, "sl": agg_sl, "rr": rr(agg_entry, agg_tp, agg_sl)},
        "Moderat":    {"entry": mod_entry, "tp": mod_tp, "sl": mod_sl, "rr": rr(mod_entry, mod_tp, mod_sl)},
        "Low Risk":   {"entry": low_entry, "tp": low_tp, "sl": low_sl, "rr": rr(low_entry, low_tp, low_sl),
                        "support_wall_lot": strongest_bid.lot if strongest_bid else None},
    }
