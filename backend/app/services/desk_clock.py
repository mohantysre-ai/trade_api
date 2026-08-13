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


def cash_session_phase(for_date=None, now: datetime | None = None) -> str:
    """Return PRE_OPEN, OPEN, or CLOSED for an IST trading date."""
    n = ist_now(now)
    target = for_date or n.date()
    if target < n.date() or target.weekday() >= 5:
        return "CLOSED"
    if target > n.date():
        return "PRE_OPEN"
    minutes = _mins(n.hour, n.minute)
    if minutes < _mins(9, 15):
        return "PRE_OPEN"
    if minutes <= _mins(15, 30):
        return "OPEN"
    return "CLOSED"


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


# --- Rotation / replacement windows (separate from primary basket lock) ---
# Primary: 09:45–10:15 | Continuation: 10:15–12:45 | Afternoon: 13:30–14:45
# After 14:45 — no new replacement (risk-reduction / square-off only).
_ROT_CONT_END_H, _ROT_CONT_END_M = _parse_hhmm(
    os.getenv("DESK_ROTATION_CONT_END", "12:45"), 12, 45
)
_ROT_AFT_START_H, _ROT_AFT_START_M = _parse_hhmm(
    os.getenv("DESK_ROTATION_AFT_START", "13:30"), 13, 30
)
_ROT_AFT_END_H, _ROT_AFT_END_M = _parse_hhmm(
    os.getenv("DESK_ROTATION_AFT_END", "14:45"), 14, 45
)


def rotation_window_config() -> dict[str, Any]:
    return {
        "primaryStart": f"{_LOCK_START_H:02d}:{_LOCK_START_M:02d}",
        "primaryEnd": f"{_LOCK_END_H:02d}:{_LOCK_END_M:02d}",
        "continuationEnd": f"{_ROT_CONT_END_H:02d}:{_ROT_CONT_END_M:02d}",
        "afternoonStart": f"{_ROT_AFT_START_H:02d}:{_ROT_AFT_START_M:02d}",
        "afternoonEnd": f"{_ROT_AFT_END_H:02d}:{_ROT_AFT_END_M:02d}",
        "timezone": "Asia/Kolkata",
        "rationale": (
            "Primary basket 09:45–10:15; continuation/retest scan until 12:45; "
            "afternoon high-quality scan 13:30–14:45; no new replacement after 14:45"
        ),
    }


def rotation_window_allowed(now: datetime | None = None) -> tuple[bool, str]:
    """Return (allowed, window_code) for live rotation / replacement scans.

    window_code:
      weekend | pre_lock | primary | continuation | midday_pause |
      afternoon | after_rotation
    """
    n = ist_now(now)
    if n.weekday() >= 5:
        return False, "weekend"

    mins = _mins(n.hour, n.minute)
    primary_start = _mins(_LOCK_START_H, _LOCK_START_M)
    primary_end = _mins(_LOCK_END_H, _LOCK_END_M)
    cont_end = _mins(_ROT_CONT_END_H, _ROT_CONT_END_M)
    aft_start = _mins(_ROT_AFT_START_H, _ROT_AFT_START_M)
    aft_end = _mins(_ROT_AFT_END_H, _ROT_AFT_END_M)
    if primary_end <= primary_start:
        primary_end = primary_start + 30
    if cont_end < primary_end:
        cont_end = primary_end
    if aft_end <= aft_start:
        aft_end = aft_start + 30

    if mins < primary_start:
        return False, "pre_lock"
    if mins < primary_end:
        return True, "primary"
    if mins < cont_end:
        return True, "continuation"
    if mins < aft_start:
        return False, "midday_pause"
    if mins < aft_end:
        return True, "afternoon"
    return False, "after_rotation"


def can_add_replacement(
    now: datetime | None = None,
    *,
    daily_loss_hit: bool = False,
    max_names_hit: bool = False,
    allow_manual_override: bool = False,
) -> tuple[bool, str]:
    """Portfolio-level replacement gate (time window + hard risk stops).

    Does not invent opportunity quality — callers still run entry_quality_gate.
    """
    if allow_manual_override:
        return True, "manual_override"
    if daily_loss_hit:
        return False, "daily_loss_limit"
    if max_names_hit:
        return False, "max_concurrent_names"
    ok, code = rotation_window_allowed(now)
    if not ok:
        return False, code
    return True, code


def swing_entry_hunt_config() -> dict[str, Any]:
    """SWING hunts a qualified BUY entry — not a 10:15 hard stop."""
    return {
        "huntStart": f"{_LOCK_START_H:02d}:{_LOCK_START_M:02d}",
        "huntEnd": f"{_ROT_AFT_END_H:02d}:{_ROT_AFT_END_M:02d}",
        "timezone": "Asia/Kolkata",
        "rationale": (
            "Hunt a fully qualified BUY from 09:45 IST; lock each entry when found; "
            "do not cash-finalize at 10:15; hunt closes 14:45"
        ),
    }


def swing_entry_hunt_allowed(
    now: datetime | None = None,
    *,
    allow_manual_override: bool = False,
) -> tuple[bool, str]:
    """Return (allowed, reason_code) for SWING entry hunt / lock-when-found.

    Opens 09:45 (post auction). Stays open through the cash session until
    afternoon rotation end (14:45). Not a 10:15 hard stop.

    reason_code: weekend | pre_lock | entry_hunt | after_hunt | manual_override
    """
    if allow_manual_override:
        return True, "manual_override"

    n = ist_now(now)
    if n.weekday() >= 5:
        return False, "weekend"

    mins = _mins(n.hour, n.minute)
    start = _mins(_LOCK_START_H, _LOCK_START_M)
    end = _mins(_ROT_AFT_END_H, _ROT_AFT_END_M)
    if end <= start:
        end = start + 30
    if mins < start:
        return False, "pre_lock"
    if mins < end:
        return True, "entry_hunt"
    return False, "after_hunt"


def swing_entry_hunt_block_message(reason: str) -> str:
    cfg = swing_entry_hunt_config()
    if reason == "weekend":
        return "Swing entry hunt disabled on weekends (NSE cash closed)."
    if reason == "pre_lock":
        return (
            f"Pre-open / early auction — swing entry hunt opens {cfg['huntStart']} IST "
            f"(wait for opening-range settle)."
        )
    if reason == "after_hunt":
        return (
            f"Swing entry hunt closed at {cfg['huntEnd']} IST — "
            "no new names; empty book is cash-held."
        )
    return f"Swing entry hunt not allowed ({reason})."
