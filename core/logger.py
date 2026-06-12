"""
Logger setup pakai loguru.

Output ke file di bawah `logs/`, supaya bisa di-tail oleh Netdata/Grafana
sebagaimana monitoring stack existing lo di Hetzner VPS.
"""

from __future__ import annotations

import sys

from loguru import logger
from rich.logging import RichHandler
from rich.text import Text

logger.remove()

# RichHandler for beautiful terminal logging
logger.add(
    RichHandler(
        rich_tracebacks=True,
        markup=True,
        show_path=False,
        show_time=True,
        show_level=True,
    ),
    format="{message}",
    level="INFO",
)


def file_formatter(record) -> str:
    """Format loguru records for files, stripping Rich markup tags."""
    raw_message = record["message"]
    try:
        plain_message = Text.from_markup(raw_message).plain
    except Exception:
        plain_message = raw_message

    record["extra"]["plain_message"] = plain_message
    return "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[plain_message]}\n{exception}"


logger.add(
    "logs/idx_realtime_feed.log",
    rotation="10 MB",
    retention="14 days",
    level="DEBUG",
    enqueue=True,
    format=file_formatter,
)

__all__ = ["logger"]
