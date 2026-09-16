"""Strategy state persistence helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any


def strategy_snapshot_path() -> str:
    override = os.getenv("INDEX_OPTIONS_STRATEGY_SNAPSHOT_FILE", "").strip()
    if override:
        return override
    base = os.path.dirname(__file__)
    return os.path.join(base, "..", "..", "data", "index_options_strategy_snapshot.json")


def save_strategy_snapshot(state: dict[str, Any]) -> None:
    path = strategy_snapshot_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, default=str)
    os.replace(tmp, path)


def load_strategy_snapshot() -> dict[str, Any]:
    path = strategy_snapshot_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}
