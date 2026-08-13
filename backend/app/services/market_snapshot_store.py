"""Canonical path for last_market_snapshot.json (Matrix + swing hunt)."""
from __future__ import annotations

import os
from pathlib import Path

_SERVICES_DIR = Path(__file__).resolve().parent
_BUNDLED_SNAPSHOT = _SERVICES_DIR / "last_market_snapshot.json"


def market_snapshot_path() -> Path:
    env = (os.environ.get("MARKET_SNAPSHOT_FILE") or os.environ.get("LAST_MARKET_SNAPSHOT_FILE") or "").strip()
    if env:
        return Path(env)
    return _BUNDLED_SNAPSHOT


def readable_market_snapshot_path() -> Path:
    primary = market_snapshot_path()
    if primary.is_file():
        return primary
    return _BUNDLED_SNAPSHOT
