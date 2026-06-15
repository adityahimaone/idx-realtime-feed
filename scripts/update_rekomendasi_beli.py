#!/usr/bin/env python3
"""
update_rekomendasi_beli.py — Rebuilds 'Rekomendasi Beli [IRW]' sheet.

Invokes the SheetsRepository central logic to fetch watchlists, compute recommendations,
and rebuild the 'Rekomendasi Beli [IRW]' worksheet.
"""

import sys
from pathlib import Path
import argparse

# Make project root importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import config
from core.logger import logger
from repositories.sheets_repository import SheetsRepository


def parse_args():
    parser = argparse.ArgumentParser(description="Rebuild Rekomendasi Beli [IRW] sheet")
    parser.add_argument('--force', action='store_true', help='(compatibility flag)')
    return parser.parse_args()


def main():
    parse_args()
    
    # Initialize repository
    repo = SheetsRepository()
    sheet_id = config.MARKET_ALPHA_SPREADSHEET_ID
    if not sheet_id:
        logger.error("MARKET_ALPHA_SPREADSHEET_ID not set in configuration")
        sys.exit(1)
        
    logger.info(f"[Rekomendasi Beli] Rebuilding Rekomendasi Beli [IRW] on sheet {sheet_id[:20]}...")
    repo.update_rekomendasi_beli(sheet_id=sheet_id)
    logger.info("[Rekomendasi Beli] Process complete.")


if __name__ == "__main__":
    main()
