#!/usr/bin/env python3
"""List all Stockbit watchlists with their IDs.

Usage:
    python scripts/list_watchlists.py

Output:
    ID          Name
    2624360     All Watchlist (default)
    4162869     Portfolio
    ...
"""

import httpx
import sys
from pathlib import Path

# Try reading token from .env
env_path = Path(__file__).parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith("STOCKBIT_BEARER_TOKEN="):
            token = line.split("=", 1)[1].strip()
            break
else:
    token = ""

if not token:
    print("STOCKBIT_BEARER_TOKEN not found in .env", file=sys.stderr)
    sys.exit(1)

resp = httpx.get(
    "https://exodus.stockbit.com/watchlist",
    params={
        "page": 1,
        "limit": 500,
        "category_types": [
            "CATEGORY_TYPE_ALL_WATCHLIST",
            "CATEGORY_TYPE_PORTFOLIO",
            "CATEGORY_TYPE_NORMAL",
        ],
    },
    headers={"Authorization": f"Bearer {token}"},
    timeout=10,
)
resp.raise_for_status()
data = resp.json()

print(f"{'ID':<12} {'Name':<30} {'Default'}")
print("-" * 55)
for wl in data["data"]:
    is_def = "(default)" if wl.get("is_default") else ""
    print(f"{wl['watchlist_id']:<12} {wl['name']:<30} {is_def}")
print(f"\nTotal: {len(data['data'])} watchlists")
