from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def is_session(day: date, holidays: set[date] | None = None) -> bool:
    if holidays is None:
        from ..nse_trading_calendar import is_nse_trading_day

        return is_nse_trading_day(day)
    return day.weekday() < 5 and day not in holidays


def next_session(day: date, holidays: set[date] | None = None) -> date:
    cursor = day + timedelta(days=1)
    while not is_session(cursor, holidays):
        cursor += timedelta(days=1)
    return cursor


def session_age(entry_day: date, current_day: date, holidays: set[date] | None = None) -> int:
    if current_day <= entry_day:
        return 0
    count, cursor = 0, entry_day
    while cursor < current_day:
        cursor = next_session(cursor, holidays)
        if cursor <= current_day:
            count += 1
    return count


def time_exit_due(now_ist: datetime, holding_session_age: int, *, max_overnights: int = 2, exit_clock: str = "15:15") -> bool:
    local = now_ist.astimezone(IST)
    hour, minute = (int(part) for part in exit_clock.split(":"))
    return holding_session_age >= max_overnights and local.time().replace(tzinfo=None) >= time(hour, minute)


def entry_window_state(now_ist: datetime, *, freeze: str = "15:10", expiry: str = "15:20") -> str:
    local_time = now_ist.astimezone(IST).time().replace(tzinfo=None)
    freeze_t = time(*(int(part) for part in freeze.split(":")))
    expiry_t = time(*(int(part) for part in expiry.split(":")))
    if local_time < freeze_t:
        return "PRE_DECISION"
    if local_time <= expiry_t:
        return "ORDER_WINDOW"
    return "EXPIRED"
