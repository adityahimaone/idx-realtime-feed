# 🎯 Stockbit Custom Screener Configuration Guide

This guide provides the exact rules, indicators, and configuration parameters to replicate the signals from the **IDX Intraday Multi-Source Screener** (Pre-ARA, BSJP, and Minervini Stage 2) directly inside the **Stockbit Screener** tool.

---

## 🚨 1. Pre-ARA Momentum Screener

Replicates the Stage 1 early breakout detection model.

### 📊 Screener Parameters

| No | Stockbit Parameter | Condition | Value / Target | Purpose |
|---|---|---|---|---|
| 1 | `Price Change (Daily)` | `>` | `5 %` | Early price acceleration |
| 2 | `Volume Change (Daily)` | `>` | `1.5` (or `150 %`) | Volume Surge Ratio (VSR) proxy |
| 3 | `Close Price` | `<` | `Upper Band (Bollinger)` | Room to hit target ceiling |
| 4 | `Value (Transaction)` | `>` | `10,000,000,000` (Rp 10B) | Liquidity threshold |

---

## 🌙 2. BSJP (Buy Sore Jual Pagi) Screener

Finds tickers showing high volume concentration and pricing pressure towards the close (after 14:30 WIB).

### 📊 Screener Parameters

| No | Stockbit Parameter | Condition | Value / Target | Purpose |
|---|---|---|---|---|
| 1 | `Current Price` | `>` | `VWAP` | Bullish intraday pressure |
| 2 | `Close Position in Range (CPR)` | `>` | `70 %` | Price closes near the high of the day |
| 3 | `Volume (1-Day)` | `>` | `Volume (Average 20-Day)` | High volume concentration at close |
| 4 | `Net Foreign Buy (Daily)` | `>` | `0` | Foreign confirmation flow |

---

## 📈 3. Mark Minervini Stage 2 Template

Replicates Mark Minervini's Stage 2 Uptrend template checks.

### 📊 Screener Parameters

| No | Stockbit Parameter | Condition | Value / Target | Purpose |
|---|---|---|---|---|
| 1 | `Current Price` | `>` | `Simple Moving Average 50` | Short-term momentum |
| 2 | `Simple Moving Average 50` | `>` | `Simple Moving Average 150` | Trend acceleration |
| 3 | `Simple Moving Average 150` | `>` | `Simple Moving Average 200` | Stage 2 confirmation |
| 4 | `Simple Moving Average 200` | `is sloping up` | `20-Day period` | Steady long-term trend |
| 5 | `Current Price` | `>` | `52-Week Low * 1.25` | Min. 25% bounce off bottom |
| 6 | `Current Price` | `>` | `52-Week High * 0.75` | Within 25% of absolute high |
