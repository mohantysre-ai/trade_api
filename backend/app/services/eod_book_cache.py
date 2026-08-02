"""Per-day Book P&L report cache (same pattern as institutional EOD artifacts).

Files under ``backend/app/data/eod/YYYY-MM-DD/``:
  - book_intraday.json
  - book_swing.json

Refresh / GET serves these when present. Rebuild only with force=True or
when cache is missing (e.g. after Run EOD warms the cache).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _day_dir(for_date) -> str:
    from .eod_engine.ingestion import eod_day_dir

    return eod_day_dir(for_date)


def book_cache_path(for_date, kind: str) -> str:
    name = "book_intraday.json" if kind == "intraday" else "book_swing.json"
    return os.path.join(_day_dir(for_date), name)


def load_book_cache(for_date, kind: str) -> dict[str, Any] | None:
    path = book_cache_path(for_date, kind)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            out = dict(data)
            out["fromCache"] = True
            return out
    except Exception as exc:
        log.warning("book cache read failed %s: %s", path, exc)
    return None


def save_book_cache(for_date, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .eod_engine.ingestion import atomic_write_json

    path = book_cache_path(for_date, kind)
    to_store = {k: v for k, v in payload.items() if k != "fromCache"}
    to_store["cachedAt"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(path, to_store)
    out = dict(to_store)
    out["fromCache"] = False
    return out


def warm_book_caches(for_date) -> dict[str, Any]:
    """Rebuild and persist both book reports (called after institutional EOD run)."""
    from .eod_intraday_report import generate_intraday_eod_report
    from .eod_swing_report import generate_swing_eod_report

    intra = generate_intraday_eod_report(for_date, force=True)
    swing = generate_swing_eod_report(for_date, force=True)
    return {
        "intraday": bool(intra),
        "swing": bool(swing),
        "date": for_date.isoformat() if hasattr(for_date, "isoformat") else str(for_date),
    }
