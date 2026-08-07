"""
Backtest pre-market predictions against the next trading day's open gap.

Loads persisted rows from `pre_market_predictions` (written by the 08:40 WIB
job), joins each row with the first daily bar at/after the prediction date
(yfinance), and reports:
  - hit rate: gap-up >= +0.5% and >= +1.0%
  - median open gap
by tier (WATCH CLOSELY / ON RADAR) plus an overall row.

Writes `logs/premarket_backtest.csv`. This is the recalibration input for the
heuristic weights (ARA streak, BSJP tier, news confidence, calendar, macro).

Usage:
    uv run python scripts/backtest_premarket.py --days 7
"""
import argparse
import csv
import os
import sys
from datetime import datetime
from statistics import median

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repositories.sqlite_repository import sqlite_repository

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
CSV_PATH = os.path.join(LOG_DIR, "premarket_backtest.csv")

TIERS = ("WATCH CLOSELY", "ON RADAR")


def load_predictions(days: int) -> list[dict]:
    """Latest `days` distinct prediction dates, oldest-first within the window."""
    rows = sqlite_repository.get_premarket_predictions_all(limit=1000)
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        by_date.setdefault(r["pred_date"], []).append(r)
    dates = sorted(by_date.keys(), reverse=True)[:days]
    out: list[dict] = []
    for d in reversed(dates):
        out.extend(by_date[d])
    return out


def open_gap(ticker: str, pred_date) -> dict | None:
    """Open gap% of the first daily bar at/after pred_date.

    gap% = (open - prev_close) / prev_close * 100, where prev_close is the
    prior daily bar's close. Returns None when data is missing.
    """
    try:
        hist = yf.Ticker(f"{ticker}.JK").history(
            start=(pd.Timestamp(pred_date) - pd.Timedelta(days=10)),
            period="1mo",
        )
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    for i, idx in enumerate(hist.index):
        if idx.date() >= pred_date:
            if i == 0:
                return None  # need a prior close for the gap
            prev_close = float(hist["Close"].iloc[i - 1])
            open_ = float(hist["Open"].iloc[i])
            if prev_close <= 0:
                return None
            return {"bar_date": idx.date().isoformat(), "gap_pct": (open_ / prev_close - 1) * 100}
    return None


def summarize(results: list[dict]) -> list[dict]:
    stats = []
    for tier in TIERS:
        sub = [r for r in results if r["tier"] == tier]
        if not sub:
            continue
        gaps = [r["gap_pct"] for r in sub]
        stats.append({
            "Tier": tier,
            "n": len(sub),
            "Hit >= +0.5%": f"{sum(1 for g in gaps if g >= 0.5) / len(gaps) * 100:.0f}%",
            "Hit >= +1.0%": f"{sum(1 for g in gaps if g >= 1.0) / len(gaps) * 100:.0f}%",
            "Median Gap": f"{median(gaps):+.2f}%",
        })
    if results:
        gaps = [r["gap_pct"] for r in results]
        stats.append({
            "Tier": "ALL",
            "n": len(gaps),
            "Hit >= +0.5%": f"{sum(1 for g in gaps if g >= 0.5) / len(gaps) * 100:.0f}%",
            "Hit >= +1.0%": f"{sum(1 for g in gaps if g >= 1.0) / len(gaps) * 100:.0f}%",
            "Median Gap": f"{median(gaps):+.2f}%",
        })
    return stats


def main(days: int) -> None:
    preds = load_predictions(days)
    if not preds:
        print("Tidak ada prediksi tersimpan. Jalankan `bot.pre_market_predictor` dulu.")
        return

    results = []
    for p in preds:
        pred_date = datetime.strptime(p["pred_date"], "%Y-%m-%d").date()
        g = open_gap(p["ticker"], pred_date)
        if g:
            results.append({**p, "bar_date": g["bar_date"], "gap_pct": g["gap_pct"]})

    if not results:
        print("Prediksi ada, tapi tidak ada data harga yfinance yang cocok.")
        return

    stats = summarize(results)
    width = max(len(s["Tier"]) for s in stats)
    header = f"{'Tier'.ljust(width)} | {'n':>3} | {'Hit ≥ +0.5%':>11} | {'Hit ≥ +1.0%':>11} | {'Median Gap':>10}"
    print(header)
    print("-" * len(header))
    for s in stats:
        print(
            f"{s['Tier'].ljust(width)} | {s['n']:>3} | {s['Hit >= +0.5%']:>11} | "
            f"{s['Hit >= +1.0%']:>11} | {s['Median Gap']:>10}"
        )

    os.makedirs(LOG_DIR, exist_ok=True)
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["pred_date", "ticker", "tier", "score", "bar_date", "gap_pct"]
        )
        writer.writeheader()
        for r in results:
            writer.writerow({
                "pred_date": r["pred_date"], "ticker": r["ticker"], "tier": r["tier"],
                "score": r["score"], "bar_date": r["bar_date"], "gap_pct": round(r["gap_pct"], 4),
            })
    print(f"\nCSV: {CSV_PATH} ({len(results)} rows)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Jumlah tanggal prediksi terakhir")
    args = parser.parse_args()
    main(days=args.days)
