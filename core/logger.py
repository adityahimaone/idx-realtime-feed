"""
Logger setup pakai loguru.

Output ke file di bawah `logs/`, supaya bisa di-tail oleh Netdata/Grafana
sebagaimana monitoring stack existing lo di Hetzner VPS.
"""

from __future__ import annotations

import sys

from loguru import logger

logger.remove()

logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
)

logger.add(
    "logs/idx_realtime_feed.log",
    rotation="10 MB",
    retention="14 days",
    level="DEBUG",
    enqueue=True,
)

__all__ = ["logger"]
