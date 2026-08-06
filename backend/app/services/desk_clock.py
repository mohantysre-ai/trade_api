"""Institutional desk clock — basket lock / open cadence (IST).

Primary lock window: 09:45–10:15 IST (post open-auction / opening range).
Catch-up: if the app starts after 10:15, allow one lock until session end
so a late desk boot still builds today's book — never before 09:45.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any

_IST = timezone(timedelta(hours=5, minutes=30))


def _parse_hhmm(raw: str, default_h: int, default_m: int) -> tuple[int, int]:
    text = (raw or "").strip()
    if ":" not in text:
        return default_h, default_m
    try:
        hh_s, mm_s = text.split(":", 1)
        return int(hh_s), int(mm_s)
    except Exception:
        return default_h, default_m


_LOCK_START_H, _LOCK_START_M = _parse_hhmm(os.getenv("DESK_LOCK_START", "09:45"), 9, 45)
_LOCK_END_H, _LOCK_END_M = _parse_hhmm(os.getenv("DESK_LOCK_END", "10:15"), 10, 15)
# Late-start catch-up ceiling (still refuse after cash close)
_CATCHUP_END_H, _CATCHUP_END_M = _parse_hhmm(os.getenv("DESK_LOCK_CATCHUP_UNTIL", "15:30"), 15, 30)


def ist_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(tz=_IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=_IST)
    return now.astimezone(_IST)


def _mins(h: int, m: int) -> int:
    return h * 60 + m


def lock_window_config() -> dict[str, Any]:
    return {
        "lockStart": f"{_LOCK_START_H:02d}:{_LOCK_START_M:02d}",
        "lockEnd": f"{_LOCK_END_H:02d}:{_LOCK_END_M:02d}",
        "catchupUntil": f"{_CATCHUP_END_H:02d}:{_CATCHUP_END_M:02d}",
        "timezone": "Asia/Kolkata",
        "rationale": (
            "Post open-auction / opening-range settle (09:45); "
            "primary construction closes 10:15; late app start catch-up until cash close"
        ),
    }


def basket_lock_allowed(
    now: datetime | None = None,
    *,
    allow_manual_override: bool = False,
) -> tuple[bool, str]:
    """Return (allowed, reason_code).

    reason_code:
      weekend | pre_lock_window | primary_window | catchup_after_window |
      after_catchup | manual_override
    """
    if allow_manual_override:
        return True, "manual_override"

    n = ist_now(now)
    if n.weekday() >= 5:
        return False, "weekend"

    mins = _mins(n.hour, n.minute)
    start = _mins(_LOCK_START_H, _LOCK_START_M)
    end = _mins(_LOCK_END_H, _LOCK_END_M)
    catchup = _mins(_CATCHUP_END_H, _CATCHUP_END_M)
    if end <= start:
        end = start + 30
    if catchup < end:
        catchup = end

    if mins < start:
        return False, "pre_lock_window"
    if mins < end:
        return True, "primary_window"
    if mins < catchup:
        return True, "catchup_after_window"
    return False, "after_catchup"


def basket_lock_block_message(reason: str) -> str:
    cfg = lock_window_config()
    if reason == "weekend":
        return "Basket lock disabled on weekends (NSE cash closed)."
    if reason == "pre_lock_window":
        return (
            f"Pre-open / early auction — lock opens {cfg['lockStart']} IST "
            f"(wait for opening-range settle; refuse stale pre-{cfg['lockStart']} books)."
        )
    if reason == "after_catchup":
        return (
            f"Cash session closed — lock window was {cfg['lockStart']}–{cfg['lockEnd']} IST "
            f"(catch-up until {cfg['catchupUntil']})."
        )
    return f"Basket lock not allowed ({reason})."
