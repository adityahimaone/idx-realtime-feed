"""
Config loader for idx-realtime-feed.
"""

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
    # Service account JSON as string, or fallback to ~/.hermes/google_token.json (user OAuth)
    GOOGLE_SERVICE_ACCOUNT: str = os.getenv("GOOGLE_SERVICE_ACCOUNT", "")
    MARKET_ALPHA_SPREADSHEET_ID: str = os.getenv("MARKET_ALPHA_SPREADSHEET_ID", "")
    REALTIME_SHEET_NAME: str = os.getenv("REALTIME_SHEET_NAME", "Realtime_Watchlist")
    WATCHLIST_SHEET_NAME: str = os.getenv("WATCHLIST_SHEET_NAME", "Alpha_Watchlist")

    # --- Feature Management ---
    FEATURE_MANIFEST_PATH: str = os.getenv(
        "FEATURE_MANIFEST_PATH", "manifest/feature_manifest.json"
    )

    # --- Obscura (headless browser CDP server) ---
    OBSCURA_CDP_URL: str = os.getenv("OBSCURA_CDP_URL", "ws://127.0.0.1:9222")

    # --- Sync behaviour ---
    SYNC_INTERVAL_SECONDS: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "45"))
    MAX_WATCHLIST_SIZE: int = int(os.getenv("MAX_WATCHLIST_SIZE", "20"))
    DEFAULT_WATCHLIST: list[str] = ["TPIA", "BREN", "CUAN"] # Fallback

    # --- Local cache / history ---
    SQLITE_PATH: str = os.getenv("SQLITE_PATH", "data/realtime_history.db")


config = Config()
