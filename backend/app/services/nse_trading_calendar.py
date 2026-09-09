"""Cached NSE cash-market holiday calendar.

The NSE holiday endpoint is fetched at most once per process/day and persisted
so a temporary NSE outage cannot change holding-day accounting.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

NSE_HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
_CACHE_PATH = Path(os.getenv("NSE_HOLIDAY_CACHE_FILE", str(Path(__file__).resolve().parents[1] / "data" / "nse_trading_holidays.json")))
_LOCK = threading.Lock()
_LAST_ATTEMPT_DAY: date | None = None

# Official NSE CM holidays known for 2026. Weekends are handled separately.
_SEED_HOLIDAYS = {
    date(2026, 1, 15), date(2026, 1, 26), date(2026, 3, 3),
    date(2026, 3, 26), date(2026, 3, 31), date(2026, 4, 3),
    date(2026, 4, 14), date(2026, 5, 1), date(2026, 5, 28),
    date(2026, 6, 26), date(2026, 9, 14), date(2026, 10, 2),
    date(2026, 10, 20), date(2026, 11, 10), date(2026, 11, 24),
    date(2026, 12, 25),
}


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _env_holidays() -> set[date]:
    return {parsed for raw in os.getenv("NSE_TRADING_HOLIDAYS", "").split(",") if (parsed := _parse_date(raw))}


def _read_cache() -> set[date]:
    try:
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return set()
    rows = payload.get("holidays") if isinstance(payload, dict) else []
    return {parsed for raw in (rows or []) if (parsed := _parse_date(raw))}


def _write_cache(holidays: set[date]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _CACHE_PATH.with_suffix(_CACHE_PATH.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "source": "NSE_HOLIDAY_MASTER_CM",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "holidays": sorted(day.isoformat() for day in holidays),
    }, indent=2), encoding="utf-8")
    os.replace(temporary, _CACHE_PATH)


def _fetch_official(session_factory: Any = requests.Session) -> set[date]:
    session = session_factory()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/resources/exchange-communication-holidays",
    })
    try:
        session.get("https://www.nseindia.com/", timeout=8)
        response = session.get(NSE_HOLIDAY_URL, timeout=12)
        response.raise_for_status()
        payload = response.json()
    finally:
        session.close()
    rows = payload.get("CM") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("NSE holiday response has no CM calendar")
    holidays = {parsed for row in rows if isinstance(row, dict) if (parsed := _parse_date(row.get("tradingDate")))}
    if not holidays:
        raise ValueError("NSE CM holiday calendar is empty")
    return holidays


def trading_holidays(*, refresh: bool = False, today: date | None = None) -> set[date]:
    """Return official/cached holidays without repeatedly calling NSE."""
    global _LAST_ATTEMPT_DAY
    current = today or date.today()
    holidays = set(_SEED_HOLIDAYS) | _read_cache() | _env_holidays()
    if not refresh:
        return holidays
    with _LOCK:
        if _LAST_ATTEMPT_DAY == current:
            return set(_SEED_HOLIDAYS) | _read_cache() | _env_holidays()
        _LAST_ATTEMPT_DAY = current
        try:
            holidays |= _fetch_official()
            _write_cache(holidays)
        except Exception:
            pass
    return holidays


def is_nse_trading_day(day: date, *, refresh: bool = False) -> bool:
    return day.weekday() < 5 and day not in trading_holidays(refresh=refresh, today=day)


__all__ = ["NSE_HOLIDAY_URL", "is_nse_trading_day", "trading_holidays"]
