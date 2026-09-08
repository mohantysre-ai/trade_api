from __future__ import annotations

from datetime import date
from typing import Any

SEGMENTS = {"NIFTY100", "NIFTY_MIDCAP150", "NIFTY_SMALLCAP250", "NIFTY_MICROCAP250"}


def point_in_time_members(rows: list[dict[str, Any]], on_date: date) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        start = date.fromisoformat(str(row.get("effectiveFrom") or "1900-01-01")[:10])
        end_raw = row.get("effectiveTo")
        end = date.fromisoformat(str(end_raw)[:10]) if end_raw else date.max
        segment = str(row.get("universeSegment") or "").upper()
        if start <= on_date <= end and segment in SEGMENTS:
            selected.append(dict(row))
    return selected


def activation_status(segment: str) -> str:
    return "SHADOW" if "MICROCAP" in segment.upper() else "ACTIVE_PAPER_CHAMPION"


def coverage(expected_symbols: set[str], fresh_symbols: set[str]) -> float:
    if not expected_symbols:
        return 0.0
    return len({s.upper() for s in expected_symbols} & {s.upper() for s in fresh_symbols}) / len(expected_symbols)
