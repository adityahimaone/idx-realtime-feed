# 📋 IDX Recommendation Engine — Audit & Improvement Report

> **Date:** 2026-10-11  
> **Scope:** `data/scoring.py`, `data/mega_score.py`, `data/orderbook_wall.py`, `data/pre_ara.py`, `data/recommendation.py`, `app.py`, `ui/tabs/tab_pick_of_the_day.py`, `ticker.py`  
> **Status:** Fixes applied + new Best-Pick engine deployed. 55 core tests passing.

---

## Executive Summary

The StockPick IDX recommendation stack was audited for correctness against current BEI market-microstructure rules and quantitative best-practice literature. **Five correctness bugs** were found and fixed, the **ARB rule** was updated from an outdated −7% to the current −15% flat (Kep-00003/BEI/04-2025), and a **new Best-Pick Conviction Engine** (`data/recommendation.py`) was built with researched IDX-specific formulas: liquidity gate, ATR-normalised risk, relative strength vs IHSG, Minervini trend template, bandarmology flow scoring, and fundamental quality for long-term picks.

---

## 1. Bug Fixes (Correctness)

### P0 — Wrong tick-size tiers in `orderbook_wall.py`

| | Before (bug) | After (fixed) |
|---|---|---|
| Rp 2.000 – < Rp 5.000 | **Rp 25** (wrong) | **Rp 10** (correct) |
| ≥ Rp 5.000 | **Rp 50** (wrong) | **Rp 25** (correct) |

**File:** `data/orderbook_wall.py:127-133`  
**Impact:** Every Engine A/B/C entry, SL, and TP for mid/high-priced tickers was mis-aligned by one or two ticks.  
**Fix:** Updated to match BEI Kep-00136/BEI/09-2026 fraksi harga.

### P1 — Position sizing risk-cap hole

**File:** `data/scoring.py:326-341`  
**Bug:** When `lots_risk` computed to `0` (e.g. very wide SL or tiny portfolio), the old code returned `lots_cap`, which **exceeded the 1% risk budget**.

```python
# OLD (risk hole)
return min(lots_risk, lots_cap) if lots_risk > 0 else lots_cap

# NEW (risk-first)
return min(lots_risk, lots_cap)
```

### P1 — Dishonest confidence/availability in Mega Score

**File:** `app.py:1134-1159` (old), `data/mega_score.py:74-107` (new helper)  
**Bug:** Sub-signals (BSJP, Minervini, Pre-ARA, Trending) that were genuinely absent for a ticker were passed as `50` (neutral placeholder) with `available=True`. The confidence badge therefore showed ~100% for scalping even when half the signals were missing.  
**Fix:** Extracted `build_mega_signals()` — absent signals are now passed as `None`, so `compute_mega_score` correctly marks them `defaulted` and the confidence badge reflects real data coverage.

### P1 — Minervini score discontinuity

**File:** `app.py:1114-1116` (old)  
**Bug:** Failed Minervini stocks were scored with `score_int / 8 * 100`. A 7/10 failure scored **87.5** — higher than the passing threshold representation of some passed stocks, creating a counter-intuitive jump.  
**Fix:** `minervini_to_score()` maps failed stocks linearly `score_int / 10 * 100` (7/10 → 70). Passed stocks still get 100.

### P2 — Outdated ARB rule

**File:** `data/pre_ara.py:7`, `ticker.py:68-84`  
**Bug:** ARB was coded as flat −7% (an older rule). Since 8 April 2025, BEI Kep-00003/BEI/04-2025 sets ARB to **flat −15%** for all stocks > Rp 10 on Papan Utama / Pengembangan / Ekonomi Baru. Rp 1–10 uses nominal ±Rp1.  
**Fix:** Updated `get_arb_limit()` and `get_arb_price()` in `pre_ara.py`, plus `calculate_ara_arb_fallbacks()` in `ticker.py`.

---

## 2. New Capability — Best-Pick Conviction Engine (`data/recommendation.py`)

A transparent, per-horizon scoring system built from researched IDX formulas. Each factor is 0–100. Missing data defaults to 50 with reduced confidence — never fabricated.

### Factor Formulas

#### Liquidity Score
Avoids thin/gorengan by gating on **average daily traded value** (Rp):

| Avg Daily Value | Score | Gate |
|---|---|---|
| ≥ Rp 50 B | 100 | — |
| ≥ Rp 10 B | 85 | — |
| ≥ Rp 5 B | 70 | — |
| ≥ Rp 1 B | 55 | — |
| ≥ Rp 250 M | 35 | Thin |
| < Rp 250 M | 15 | Very thin |

*Fallback chain:* `raw_data.value` → `Vol_Avg × Price × 100` → today's `value` → neutral 50.

#### Volatility Score (ATR-normalised)
Per-horizon sweet-spots penalise both dead stocks and extreme gorengan:

| Horizon | Sweet Spot | Dead | Wild |
|---|---|---|---|
| Scalping | 2% – 5% | < 1% | > 10% |
| Swing/BSJP | 2% – 6% | < 1.5% | > 12% |
| Long-term | 1.5% – 4% | < 1% | > 10% |

*Fallback chain:* `ATR %` (sheet) → `Daily_Range_Pct` → intraday `(high-low)/prev_close`.

#### Relative Strength vs IHSG
O'Neil / Minervini RS rating:

```
RS = ticker_3m_return% - IHSG_3m_return%
Score = 50 + (RS / 30) * 50   [clamped 0–100]
```

*Fallback:* 52-week position proxy when 3-month return is unavailable.

#### Trend Template Score
Lightweight Minervini Stage-2 reconstruction from sheet MA stack + volume + 52W range. Counts satisfied conditions and scales to 0–100.

#### Flow / Bandarmology Score
Composite of:
- **Foreign flow** (40%): buy/sell ratio tiers (same as Intraday Score)
- **Orderbook imbalance** (35%): bid/ask ratio tiers
- **Tradebook big-money** (25%): accumulating/neutral/distributing + net-positive ratio

#### Momentum Score
Intraday change% with **RSI regime adjustment** per horizon:
- Scalping: penalise RSI > 70 (overbought intraday)
- Swing: boost RSI 45–65, penalise > 75
- Long-term: boost RSI 50–70, penalise > 80

#### Fundamental Quality (long-term only)
Composite of PE grade, market-cap tier, and beta stability:

| Factor | Ideal | Penalised |
|---|---|---|
| PE | 5–15 | ≤ 0 (loss-making) |
| MarketCap | ≥ Rp 50 T | < Rp 100 B |
| Beta | 0.8–1.2 | > 1.5 |

Weights: PE 40%, MarketCap 35%, Beta 25%.

### Horizon Weights

| Factor | Scalping | Swing/BSJP | Long-term |
|---|---|---|---|
| Liquidity | 0.15 | 0.15 | 0.10 |
| Momentum | 0.25 | 0.15 | 0.10 |
| Flow | 0.25 | 0.20 | — |
| Volatility | 0.15 | 0.15 | 0.10 |
| Trend | 0.10 | 0.20 | 0.30 |
| RS vs IHSG | 0.10 | 0.15 | 0.15 |
| Fundamental | — | — | 0.25 |

### Hard Risk Gates (most restrictive wins)

| Gate | Cap | Conditions |
|---|---|---|
| UMA | 40 | Any non-empty UMA flag |
| Corporate Action | 60 | Any non-empty Corp Action flag |
| Near-ARA | 55 | `0 < ARA_Dist_Pct ≤ 2%` |
| Extreme Volatility | 50 | `ATR% > 15` |
| Illiquidity | 55 | Avg daily value < Rp 250 M |
| Big-money distributing + negative net | 60 | Tradebook profile present |
| Large gap on thin volume | 60 | Gap > 8% with value < Rp 1 B |

### Entry / SL / TP (ATR + structure)

Risk-first stop using ATR multipliers, floored at structural support (sheet `Support` or `MA20 × 0.97`):

| Tier | ATR k | Max Risk % | R/R Target |
|---|---|---|---|
| Aggressive | 1.0 | 3% | 1.5x |
| Moderate | 1.5 | 4% | 2.0x |
| Low Risk | 2.0 | 6% | 2.5x |

TP is capped at **52W High** and **ARA price** (current BEI rule). All prices are tick-aligned with the correct IDX fraksi harga.

---

## 3. UI Integration

The Best-Pick verdict is computed in `_build_mega_rows()` (app.py) and stored in each row as `BestPick`. The Pick of the Day detail expander now renders:

- Best-Pick tier + score + confidence
- Per-factor breakdown
- Per-tier entry/SL/TP with ATR risk % and lot sizing
- Rationale line (top-3 contributors + warnings)

No existing UI elements were removed — the new panel is additive.

---

## 4. Test Coverage

| Module | Tests | Notes |
|---|---|---|
| `test_formulas.py` | 3 | Tick size, alignment, action recommendation |
| `test_mega_score.py` | 6 | Defaults, confidence, tier boundaries, sentiment mapping |
| `test_scoring_stockpick.py` | 18 | Weights, MA stack, RSI discount, hard caps, live overrides |
| `test_orderbook_wall.py` | 1 | Engines A/B/C contract |
| `test_recommendation.py` | **29** | **New** — liquidity, volatility, RS, trend, flow, momentum, fundamentals, gates, levels, integration, ranking |

**Total core tests: 55 passing.** (Premarket tests have pre-existing sandbox `PermissionError` unrelated to this change.)

---

## 5. References

1. **BEI Kep-00136/BEI/09-2026** — Fraksi Harga (28 Sep 2026). Maybank Sekuritas, *Fraksi Harga Saham: Tabel Terbaru*.
2. **BEI Kep-00003/BEI/04-2025** — Perubahan Peraturan II-A (8 Apr 2025). ARB flat −15% untuk saham > Rp 10.
3. **Minervini, M.** — *Trade Like a Stock Market Wizard* (Stage 2 Trend Template).
4. **O'Neil, W.** — *How to Make Money in Stocks* (RS Rating, CANSLIM).
5. **Bursa Efek Indonesia** — Auto Rejection Atas/Bawah tier table (2025–2026 asymmetric period).

---

## 6. Files Changed

```
data/orderbook_wall.py      — tick-size fix (2000–5000: 25→10, ≥5000: 50→25)
data/scoring.py             — position_size_lots risk-cap fix
data/pre_ara.py             — ARB rule update (-7% → -15%, + Rp1–Rp10 nominal)
data/mega_score.py          — minervini_to_score() + build_mega_signals()
data/recommendation.py      — NEW Best-Pick engine
ticker.py                   — calculate_ara_arb_fallbacks() ARB fix
app.py                      — wire BestPick + confidence fix
tab_pick_of_the_day.py      — render BestPick detail panel
tests/test_recommendation.py — NEW 29 tests
```
