"""EOD archive persistence for intraday scanner picks.

Problem this solves: trade_outcome.py's `_load_persisted_picks()` prunes any
pick older than SESSION_TTL (6h) by deleting it outright. That means nothing
survives past end-of-day for the intraday scanner picks (scannerPicks in
trade_api_snapshot.json), so there was no data left to build an EOD report
from. This module gives those expiring picks somewhere durable to land
*before* they're removed from the live snapshot.

Storage: one flat JSON file per trading day, under backend/app/services/eod_archive/.
Matches the existing persistence pattern in this codebase (atomic write, no
new dependencies, no DB).
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

_ARCHIVE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "eod_archive",
)


def _archive_path(for_date: date) -> str:
    os.makedirs(_ARCHIVE_DIR, exist_ok=True)
    return os.path.join(_ARCHIVE_DIR, f"{for_date.isoformat()}.json")


def pick_session_date(pick: dict[str, Any], fallback: date | None = None) -> date | None:
    """Resolve the trading day carried by a persisted pick."""
    for key in ("sessionDate", "tradeDate", "date"):
        raw = str(pick.get(key) or "").strip()[:10]
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                pass
    for key in ("createdAt", "committedAt", "updatedAt"):
        raw = str(pick.get(key) or "").strip()
        if raw:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            except ValueError:
                pass
    return fallback


def _atomic_write(path: str, payload: dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)


def load_archive(for_date: date) -> dict[str, Any]:
    """Load the archive for a given trading day. Returns {} if none exists yet."""
    path = _archive_path(for_date)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def archive_pick(key: str, pick: dict[str, Any], for_date: date) -> None:
    """Archive a single intraday pick before it's pruned from the live snapshot.

    Call this from trade_outcome._load_persisted_picks() at the point where
    expired entries are currently `del`-eted — archive first, delete after.
    """
    for_date = pick_session_date(pick, for_date) or for_date
    archive = load_archive(for_date)
    picks = archive.setdefault("intradayPicks", {})
    # Don't overwrite an already-archived (possibly more complete) entry
    if key not in picks:
        picks[key] = pick
    archive["date"] = for_date.isoformat()
    _atomic_write(_archive_path(for_date), archive)


def archive_all_expiring(picks_map: dict[str, dict[str, Any]], expired_keys: list[str], for_date: date) -> None:
    """Batch version — archives every expiring key in one write instead of N writes."""
    if not expired_keys:
        return
    by_day: dict[date, list[tuple[str, dict[str, Any]]]] = {}
    for key in expired_keys:
        p = picks_map.get(key)
        if isinstance(p, dict):
            pick_day = pick_session_date(p, for_date) or for_date
            by_day.setdefault(pick_day, []).append((key, p))
    for pick_day, rows in by_day.items():
        archive = load_archive(pick_day)
        picks = archive.setdefault("intradayPicks", {})
        for key, p in rows:
            if key not in picks:
                picks[key] = p
        archive["date"] = pick_day.isoformat()
        _atomic_write(_archive_path(pick_day), archive)


def list_archived_dates() -> list[str]:
    if not os.path.isdir(_ARCHIVE_DIR):
        return []
    return sorted(
        f[:-5] for f in os.listdir(_ARCHIVE_DIR) if f.endswith(".json")
    )
