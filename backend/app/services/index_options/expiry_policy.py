"""Expiry selection policy for index-options strategies."""

from __future__ import annotations

from datetime import date
from typing import Any


def select_expiry(available: list[Any], now: date | None = None) -> Any | None:
    if not available:
        return None
    today = now or date.today()
    future = [exp for exp in available if _to_date(exp) >= today]
    if not future:
        return None
    return min(future, key=_to_date)


def _to_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value or "").strip().upper()
    for fmt in ("%Y-%m-%d", "%d%b%Y", "%d-%b-%Y"):
        try:
            return __import__("datetime").datetime.strptime(text, fmt).date()
        except (ValueError, TypeError):
            continue
    return date.max
