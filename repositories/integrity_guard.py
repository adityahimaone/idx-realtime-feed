"""
Integrity guard for idx-realtime-feed.

Ported from Market Alpha Scout pattern. Validates spreadsheet state
before writing — prevents corruption from stale data or rollbacks.

Usage:
    from repositories.integrity_guard import ensure_integrity, check_anti_rollback

    ensure_integrity(ws)           # validate sheet structure
    check_anti_rollback(ws, snap)  # compare timestamp, abort if newer exists
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.logger import logger

MANIFEST_PATH = Path(__file__).parent.parent / "manifest" / "feature_manifest.json"


def load_manifest() -> dict:
    """Load feature_manifest.json."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_PATH}")
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def ensure_integrity(ws) -> tuple[bool, list[str]]:
    """Validate worksheet structure against manifest before writing.

    Args:
        ws: gspread Worksheet object (Realtime_Watchlist)

    Returns:
        (is_valid, issues) — True if safe to write, list of problems if not.
    """
    manifest = load_manifest()
    expected_columns = manifest["spreadsheet"]["columns"]
    issues: list[str] = []

    # 1. Check header row matches expected columns
    try:
        actual_headers = ws.row_values(1)
    except Exception as exc:
        issues.append(f"Cannot read headers: {exc}")
        return False, issues

    if not actual_headers:
        # Empty sheet — will be initialized by write_snapshots, OK
        logger.info("integrity: sheet empty, will initialize on write")
        return True, []

    # Compare headers
    for i, expected in enumerate(expected_columns):
        if i >= len(actual_headers):
            issues.append(f"Missing column {i+1}: expected '{expected}'")
        elif actual_headers[i] != expected:
            issues.append(
                f"Column {i+1} mismatch: expected '{expected}', got '{actual_headers[i]}'"
            )

    if issues:
        logger.warning(f"integrity: {len(issues)} issues found — blocking write")
    else:
        logger.debug("integrity: structure OK")

    return len(issues) == 0, issues


def check_anti_rollback(ws) -> tuple[bool, str | None]:
    """Anti-rollback check: ensure we're not overwriting newer data.

    Reads the 'Last Update (UTC)' column (col 14) from row 2.
    If existing timestamp is MORE RECENT than now minus sync_interval * 2,
    it means another process already wrote — safe to proceed.
    If existing timestamp is IN THE FUTURE relative to now, something is
    wrong (clock skew or manual edit) — block write.

    Returns:
        (safe_to_write, reason_if_blocked)
    """
    manifest = load_manifest()
    sync_interval = manifest.get("sync_interval_seconds", 45)

    # Find "Last Update (UTC)" column index from headers
    try:
        headers = ws.row_values(1)
        update_col = None
        for i, h in enumerate(headers):
            if "last update" in h.lower():
                update_col = i + 1  # 1-indexed
                break
        if update_col is None:
            logger.warning("anti-rollback: 'Last Update' column not found")
            return True, None
        
        last_update_str = ws.cell(2, update_col).value
    except Exception as exc:
        logger.warning(f"anti-rollback: cannot read headers or value: {exc}")
        return True, None

    if not last_update_str:
        # No data yet — safe to write
        return True, None

    try:
        last_update = datetime.fromisoformat(last_update_str)
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        # Try fallback formats (e.g. '12 Jun 21:44', '12 Jun 2026 21:44')
        _FALLBACK_FMTS = [
            "%d %b %H:%M",
            "%d %b %Y %H:%M",
            "%d %b %Y %H:%M:%S",
        ]
        parsed = None
        for fmt in _FALLBACK_FMTS:
            try:
                parsed = datetime.strptime(last_update_str, fmt).replace(tzinfo=timezone.utc)
                # '%d %b %H:%M' has no year — assume current year
                if parsed.year == 1900:
                    parsed = parsed.replace(year=datetime.now(timezone.utc).year)
                break
            except (ValueError, TypeError):
                continue
        if parsed is None:
            logger.warning(f"anti-rollback: unparseable timestamp '{last_update_str}'")
            return True, None
        last_update = parsed

    now = datetime.now(timezone.utc)
    drift = (last_update - now).total_seconds()

    # If sheet timestamp is >60s in the future — suspicious
    if drift > 60:
        reason = (
            f"Sheet timestamp {last_update.isoformat()} is {drift:.0f}s ahead of now. "
            f"Possible manual edit or clock skew. Blocking write."
        )
        logger.error(f"anti-rollback: {reason}")
        return False, reason

    # If last update was less than sync_interval/2 ago — another process might
    # be writing simultaneously. Allow but warn.
    staleness = (now - last_update).total_seconds()
    if staleness < sync_interval / 2:
        logger.info(
            f"anti-rollback: last write was only {staleness:.0f}s ago "
            f"(interval={sync_interval}s) — possible concurrent writer"
        )

    return True, None


def log_integrity_event(event: str, details: str) -> None:
    """Append integrity event to local audit log."""
    log_path = Path(__file__).parent.parent / "data" / "integrity_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "details": details,
    }

    logs: list[dict] = []
    if log_path.exists():
        try:
            logs = json.loads(log_path.read_text())
        except (json.JSONDecodeError, OSError):
            logs = []

    logs.append(entry)
    # Keep last 200 entries
    log_path.write_text(json.dumps(logs[-200:], indent=2))
    logger.debug(f"integrity: logged event '{event}'")
