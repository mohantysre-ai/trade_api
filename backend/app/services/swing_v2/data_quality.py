from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..nse_trading_calendar import is_nse_trading_day

# Swing is a 1-hour / two-session strategy, not the 5-minute Intraday desk.
# A 10-second lock gate made a 500-750 name sequential scan practically
# impossible to lock even when the underlying 1h setup was valid. Keep quotes
# and depth genuinely recent, while allowing the latest completed 1h bar to
# remain valid for its natural timeframe.
SCAN_MAX_AGE = {
    "quote": int(os.getenv("SWING_SCAN_QUOTE_MAX_AGE_SEC", "900")),
    "bars1h": int(os.getenv("SWING_SCAN_BARS1H_MAX_AGE_SEC", "259200")),
}
LOCK_MAX_AGE = {
    "quote": int(os.getenv("SWING_LOCK_QUOTE_MAX_AGE_SEC", "300")),
    "bars1h": int(os.getenv("SWING_LOCK_BARS1H_MAX_AGE_SEC", "259200")),
}

_IST = ZoneInfo("Asia/Kolkata")


def _parse_timestamp(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _previous_nse_trading_day(day: date) -> date:
    probe = day - timedelta(days=1)
    for _ in range(10):
        if is_nse_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    return probe


def _bars1h_session_fresh(timestamp: str | None, now: datetime | None = None) -> bool:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_ist = current.astimezone(_IST)
    bar_day = parsed.astimezone(_IST).date()
    # The latest completed one-hour bar may legitimately belong to the
    # previous NSE session (for example Friday -> Monday before a new bar is
    # available). Anything older than the previous actual trading session is
    # stale, so a weekday feed outage cannot hide behind a broad 72-hour TTL.
    return bar_day >= _previous_nse_trading_day(current_ist.date())


def age_seconds(timestamp: str | None, now: datetime | None = None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return max(0.0, ((now or datetime.now(timezone.utc)) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def evaluate_data_freshness(row: dict[str, Any], *, final_lock: bool, now: datetime | None = None) -> tuple[bool, list[str]]:
    """Data-availability freshness only.

    Checks actual data timestamps and daily-bar presence. Tradability and
    governance flags are evaluated separately so that coverage measures DATA
    existence rather than strategy qualification.
    """
    limits = LOCK_MAX_AGE if final_lock else SCAN_MAX_AGE
    reasons: list[str] = []
    stamps = row.get("sourceTimestamps") or {}
    for field, maximum in limits.items():
        stamp = stamps.get(field)
        if field == "bars1h" and not stamp:
            stamp = stamps.get("bars5m")
        age = age_seconds(stamp, now)
        if age is None:
            reasons.append(f"MISSING_{field.upper()}_TIMESTAMP")
        elif field == "bars1h":
            if not _bars1h_session_fresh(stamp, now):
                reasons.append("STALE_BARS1H")
        elif age > maximum:
            reasons.append(f"STALE_{field.upper()}")
    if row.get("dailyBarsThroughPreviousClose") is not True:
        reasons.append("MISSING_OR_STALE_DAILY_BARS_THROUGH_PREVIOUS_CLOSE")
    return not reasons, reasons


def evaluate_freshness(row: dict[str, Any], *, final_lock: bool, now: datetime | None = None) -> tuple[bool, list[str]]:
    """Data-only freshness (backward-compatible alias for evaluate_data_freshness).

    Tradability and governance checks are handled by evaluate_tradability and
    _quality_and_safety respectively.
    """
    return evaluate_data_freshness(row, final_lock=final_lock, now=now)


def source_lineage(value: Any, *, source: str, source_timestamp: str, received_at: str, quality: str = "OK") -> dict[str, Any]:
    return {"value": value, "source": source, "sourceTimestamp": source_timestamp, "receivedAt": received_at, "ageSec": age_seconds(source_timestamp), "qualityStatus": quality}