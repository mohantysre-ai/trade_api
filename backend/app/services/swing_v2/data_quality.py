from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCAN_MAX_AGE = {"quote": 60, "depth": 60, "bars5m": 420}
LOCK_MAX_AGE = {"quote": 10, "depth": 10, "bars5m": 420}


def age_seconds(timestamp: str | None, now: datetime | None = None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return max(0.0, ((now or datetime.now(timezone.utc)) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def evaluate_freshness(row: dict[str, Any], *, final_lock: bool, now: datetime | None = None) -> tuple[bool, list[str]]:
    limits = LOCK_MAX_AGE if final_lock else SCAN_MAX_AGE
    reasons: list[str] = []
    stamps = row.get("sourceTimestamps") or {}
    for field, maximum in limits.items():
        age = age_seconds(stamps.get(field), now)
        if age is None:
            reasons.append(f"MISSING_{field.upper()}_TIMESTAMP")
        elif age > maximum:
            reasons.append(f"STALE_{field.upper()}")
    for field in ("dailyBarsThroughPreviousClose", "corporateEventsCurrent", "surveillanceCurrent", "universeCurrent"):
        if row.get(field) is not True:
            reasons.append(f"MISSING_OR_STALE_{field.upper()}")
    return not reasons, reasons


def source_lineage(value: Any, *, source: str, source_timestamp: str, received_at: str, quality: str = "OK") -> dict[str, Any]:
    return {"value": value, "source": source, "sourceTimestamp": source_timestamp, "receivedAt": received_at, "ageSec": age_seconds(source_timestamp), "qualityStatus": quality}
