from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

# Swing is a 1-hour / two-session strategy, not the 5-minute Intraday desk.
# A 10-second lock gate made a 500-750 name sequential scan practically
# impossible to lock even when the underlying 1h setup was valid. Keep quotes
# and depth genuinely recent, while allowing the latest completed 1h bar to
# remain valid for its natural timeframe.
SCAN_MAX_AGE = {
    "quote": int(os.getenv("SWING_SCAN_QUOTE_MAX_AGE_SEC", "900")),
    "bars1h": int(os.getenv("SWING_SCAN_BARS1H_MAX_AGE_SEC", "86400")),
}
LOCK_MAX_AGE = {
    "quote": int(os.getenv("SWING_LOCK_QUOTE_MAX_AGE_SEC", "300")),
    "bars1h": int(os.getenv("SWING_LOCK_BARS1H_MAX_AGE_SEC", "86400")),
}


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
        # Compatibility for snapshots produced before the 1h timestamp rename.
        stamp = stamps.get(field)
        if field == "bars1h" and not stamp:
            stamp = stamps.get("bars5m")
        age = age_seconds(stamp, now)
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