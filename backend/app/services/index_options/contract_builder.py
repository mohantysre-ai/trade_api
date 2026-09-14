"""Contract builder helpers for deterministic strike construction."""

from __future__ import annotations

from typing import Any


def build_long_call(context: Any) -> dict[str, Any]:
    contract = _pick_atm(context, "CALL")
    if not contract:
        return {}
    return {
        "strategyId": "LONG_CALL",
        "strategyMode": "BUY_PREMIUM",
        "bias": "BULLISH",
        "expiry": context.expiry,
        "legs": [],
        "contract": contract,
    }


def build_long_put(context: Any) -> dict[str, Any]:
    contract = _pick_atm(context, "PUT")
    if not contract:
        return {}
    return {
        "strategyId": "LONG_PUT",
        "strategyMode": "BUY_PREMIUM",
        "bias": "BEARISH",
        "expiry": context.expiry,
        "legs": [],
        "contract": contract,
    }


def _pick_atm(context: Any, option_type: str) -> dict[str, Any] | None:
    spot = context.spot
    if spot is None:
        return None
    candidates = []
    for row in context.chain:
        if row.get("optionType") != option_type:
            continue
        strike = row.get("strike")
        if strike is None:
            continue
        try:
            distance = abs(float(strike) - spot)
        except (TypeError, ValueError):
            continue
        candidates.append((distance, row))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]
