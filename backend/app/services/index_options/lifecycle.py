"""Position lifecycle management for index-options strategies."""

from __future__ import annotations

from typing import Any


def evaluate_lifecycle(position: dict[str, Any], context: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    strategy_mode = position.get("strategyMode", "BUY_PREMIUM")
    if strategy_mode == "BUY_PREMIUM":
        return _evaluate_long_lifecycle(position, context)
    if strategy_mode == "SELL_PREMIUM":
        return _evaluate_credit_lifecycle(position, context)
    return position, None


def _evaluate_long_lifecycle(position: dict[str, Any], context: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    mark = _current_mark(position)
    if mark is None:
        return position, None
    stop = float(position.get("initialStopPremium", 0))
    target = float(position.get("targetPremium", 0))
    now = context.session_time if hasattr(context, "session_time") else None
    if now is None:
        return position, None
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    if now.astimezone(ist).time() >= __import__("datetime").time(15, 29):
        return None, _close(position, mark, "EOD_SQUAREOFF", now)
    if mark <= stop:
        return None, _close(position, mark, "INITIAL_STOP", now)
    if mark >= target:
        return None, _close(position, mark, "TARGET", now)
    return _mark(position, mark, now), None


def _evaluate_credit_lifecycle(position: dict[str, Any], context: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return position, None


def _current_mark(position: dict[str, Any]) -> float | None:
    premium = position.get("currentPremium")
    if premium is not None:
        try:
            return float(premium)
        except (TypeError, ValueError):
            pass
    contract = position.get("contract") or {}
    ltp = contract.get("ltp")
    if ltp is not None:
        try:
            return float(ltp)
        except (TypeError, ValueError):
            pass
    return None


def _mark(position: dict[str, Any], mark: float, now: Any) -> dict[str, Any]:
    entry = float(position.get("entryPremium", 0))
    qty = int(position.get("quantity", 0))
    pnl = round((mark - entry) * qty, 2)
    return {
        **position,
        "currentPremium": round(mark, 2),
        "peakPremium": round(max(float(position.get("peakPremium", entry)), mark), 2),
        "unrealizedPnl": pnl,
        "updatedAt": now.isoformat(),
        "markedAt": now.isoformat(),
    }


def _close(position: dict[str, Any], mark: float, reason: str, now: Any) -> dict[str, Any]:
    entry = float(position.get("entryPremium", 0))
    qty = int(position.get("quantity", 0))
    pnl = round((mark - entry) * qty, 2)
    return {
        **position,
        "status": "CLOSED",
        "exitPremium": round(mark, 2),
        "exitReason": reason,
        "exitedAt": now.isoformat(),
        "pnl": pnl,
        "pnlPct": round((mark - entry) / entry * 100.0, 2) if entry else 0.0,
        "unrealizedPnl": 0.0,
    }
