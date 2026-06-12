"""
Entrypoint: idx-realtime-feed

Jalankan sebagai PM2 process (bukan cron), supaya event loop + token
cache tetap hidup antar-cycle:

    pm2 start main.py --interpreter python3 --name idx-realtime-feed
"""

from __future__ import annotations

import asyncio

from core.logger import logger
from services.sync_service import sync_service


async def main() -> None:
    logger.info("idx-realtime-feed: starting up")
    await sync_service.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
