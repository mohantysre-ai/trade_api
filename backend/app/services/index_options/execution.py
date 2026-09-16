"""Paper execution helpers for index-options strategies."""

from __future__ import annotations

from typing import Any


def paper_entry_requirements(strategy_result: dict[str, Any]) -> tuple[bool, str]:
    if not strategy_result.get("eligible"):
        return False, strategy_result.get("reason", "NOT_ELIGIBLE")
    strategy_mode = strategy_result.get("strategyMode", "")
    if strategy_mode == "BUY_PREMIUM":
        contract = strategy_result.get("contract") or {}
        if not contract.get("symbol"):
            return False, "CONTRACT_MISSING"
        return True, "OK"
    if strategy_mode == "SELL_PREMIUM":
        legs = strategy_result.get("legs") or []
        if not legs:
            return False, "NO_LEGS"
        for leg in legs:
            if not leg.get("symbol"):
                return False, "LEG_MISSING_SYMBOL"
        return True, "OK"
    return False, "UNKNOWN_STRATEGY_MODE"


def build_paper_position(strategy_result: dict[str, Any], context: Any) -> dict[str, Any]:
    strategy_mode = strategy_result.get("strategyMode", "BUY_PREMIUM")
    if strategy_mode == "BUY_PREMIUM":
        contract = strategy_result.get("contract") or {}
        return {
            "strategyPositionId": _gen_id(),
            "strategyId": strategy_result.get("strategyId"),
            "index": context.index if hasattr(context, "index") else None,
            "expiry": strategy_result.get("expiry"),
            "strategyMode": strategy_mode,
            "status": "OPEN",
            "entryPremium": strategy_result.get("entryDebit") or _float(contract.get("ltp")),
            "currentPremium": strategy_result.get("entryDebit") or _float(contract.get("ltp")),
            "initialStopPremium": (strategy_result.get("entryDebit") or 0) - 20.0,
            "targetPremium": (strategy_result.get("entryDebit") or 0) + 40.0,
            "quantity": 1,
            "legs": [],
            "contract": contract,
            "enteredAt": context.session_time.isoformat() if hasattr(context, "session_time") else None,
        }
    legs = strategy_result.get("legs") or []
    return {
        "strategyPositionId": _gen_id(),
        "strategyId": strategy_result.get("strategyId"),
        "index": context.index if hasattr(context, "index") else None,
        "expiry": strategy_result.get("expiry"),
        "strategyMode": strategy_mode,
        "status": "OPEN",
        "entryCredit": strategy_result.get("entryCredit"),
        "maxLossPerUnit": strategy_result.get("maxLoss"),
        "creditToRisk": strategy_result.get("rewardRisk"),
        "quantity": 1,
        "legs": legs,
        "enteredAt": context.session_time.isoformat() if hasattr(context, "session_time") else None,
    }


def _gen_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None
