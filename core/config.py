"""Config loader for idx-realtime-feed."""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- Stockbit auth ---
    STOCKBIT_USERNAME: str = os.getenv("STOCKBIT_USERNAME", "")
    STOCKBIT_PASSWORD: str = os.getenv("STOCKBIT_PASSWORD", "")
    STOCKBIT_BEARER_TOKEN: str = os.getenv("STOCKBIT_BEARER_TOKEN", "")
    STOCKBIT_TOKEN_CACHE_PATH: str = os.getenv(
        "STOCKBIT_TOKEN_CACHE_PATH", ".cache/stockbit_token.json"
    )

    # --- Google Sheets ---
    GOOGLE_SERVICE_ACCOUNT: str = os.getenv("GOOGLE_SERVICE_ACCOUNT", "")
    MARKET_ALPHA_SPREADSHEET_ID: str = os.getenv("MARKET_ALPHA_SPREADSHEET_ID", "")
    MAS_STAGING_SPREADSHEET_ID: str = os.getenv("MAS_STAGING_SPREADSHEET_ID", "")
    REALTIME_SHEET_NAME: str = os.getenv("REALTIME_SHEET_NAME", "Realtime_Watchlist")
    WATCHLIST_SHEET_NAME: str = os.getenv("WATCHLIST_SHEET_NAME", "Alpha_Watchlist")

    # --- Feature Management ---
    FEATURE_MANIFEST_PATH: str = os.getenv(
        "FEATURE_MANIFEST_PATH", "manifest/feature_manifest.json"
    )

    # --- Obscura ---
    OBSCURA_CDP_URL: str = os.getenv("OBSCURA_CDP_URL", "ws://127.0.0.1:9222")
    USE_STANDARD_CHROMIUM: bool = os.getenv("USE_STANDARD_CHROMIUM", "true").lower() == "true"

    # --- Proxy Settings (for VPS / Stealth) ---
    PROXY_SERVER: str = os.getenv("PROXY_SERVER", "")
    PROXY_USERNAME: str = os.getenv("PROXY_USERNAME", "")
    PROXY_PASSWORD: str = os.getenv("PROXY_PASSWORD", "")

    # --- Sync behaviour ---
    SYNC_INTERVAL_SECONDS: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "45"))
    STOCKBIT_WATCHLIST_ID: int = int(os.getenv("STOCKBIT_WATCHLIST_ID", "2624360"))
    MAX_WATCHLIST_SIZE: int = int(os.getenv("MAX_WATCHLIST_SIZE", "50"))
    DEFAULT_WATCHLIST: list[str] = ["TPIA", "BREN", "CUAN"]

    # --- Local cache / history ---
    SQLITE_PATH: str = os.getenv("SQLITE_PATH", "data/realtime_history.db")

    # --- Engine D / Trade Book thresholds (centralized audit #8) ---
    BIG_MONEY_DOMINANCE_PCT: float = 55.0    # big-money sell/buy ≥ this → dominant
    BIG_MONEY_TREND_RATIO: float = 0.05      # ±5% of total value = accumulating/distributing
    BOOK_IMBALANCE_SELL: float = 0.85        # imbalance below this = sell-dominant book
    BOOK_IMBALANCE_BUY: float = 1.3          # imbalance at/above this = buy-dominant book
    NET_FLOW_SELL_PCT: float = 50.0          # net flow + big-money sell caution floor
    SL_WIDEN_BIG_MONEY: float = 0.15         # SL widened by 15% on big-money distribution
    SL_WIDEN_THIN_BOOK: float = 0.10         # SL widened by 10% on sell-dominant book
    SL_TIGHTEN_MID_LOW: float = 0.12         # SL tightened by 12% (Moderate / Low Risk)
    SL_TIGHTEN_AGG: float = 0.10             # SL tightened by 10% (Aggressive)
    TP_SCALE_DOWN: float = 0.92              # TP pulled 8% closer on net-flow negative
    MAX_SL_WIDEN_PCT: float = 0.25           # cumulative SL widen cap across rules
    ARA_PROXIMITY_WARNING_PCT: float = 2.0   # near-ARA window for score cap / sanity warning
    SANITY_FLOOR_FALLBACK_PCT: float = 0.08  # sanity floor when ATR % column is empty
    SANITY_ATR_MULTIPLIER: float = 1.5       # sanity floor = current * (1 − ATR% × 1.5)


config = Config()
