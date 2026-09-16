"""Strategy selector: regime → eligible families → strategies → rank → select."""

from __future__ import annotations

from typing import Any

from .context import IndexOptionContext
from .strategy_registry import get_registered_strategies, is_strategy_enabled


def _classify_regime(context: IndexOptionContext) -> str:
    """Map existing structure/direction inputs to a market regime."""
    structure_status = str(context.structure.get("status") or "").upper()
    direction = (context.direction or "").upper()
    if structure_status == "CONFIRMED" and direction == "CALL":
        return "TREND_UP"
    if structure_status == "CONFIRMED" and direction == "PUT":
        return "TREND_DOWN"
    if structure_status == "NO_BREAKOUT":
        return "RANGE"
    if structure_status == "CONFIRMED" and direction not in {"CALL", "PUT"}:
        return "BREAKOUT"
    return "UNDEFINED"


def _regime_family_map(regime: str) -> set[str]:
    """Determine which strategy families are eligible for a regime."""
    if regime == "TREND_UP":
        return {"DIRECTIONAL", "VOLATILITY_COMPRESSION"}
    if regime == "TREND_DOWN":
        return {"DIRECTIONAL", "VOLATILITY_COMPRESSION"}
    if regime == "RANGE":
        return {"RANGE", "VOLATILITY_COMPRESSION"}
    if regime == "BREAKOUT":
        return {"DIRECTIONAL"}
    if regime == "VOL_EXPANSION":
        return {"VOLATILITY_EXPANSION", "DIRECTIONAL"}
    if regime == "VOL_COMPRESSION":
        return {"VOLATILITY_COMPRESSION", "RANGE"}
    return set()


def select_strategies(context: IndexOptionContext) -> list[dict[str, Any]]:
    """Evaluate enabled strategies and return normalized candidate list."""
    regime = _classify_regime(context)
    allowed_families = _regime_family_map(regime)
    if context.term_structure is not None and context.far_chain and context.far_expiry:
        allowed_families.add("TERM_STRUCTURE")
    if context.atm_iv is not None and context.realized_vol is not None:
        if context.atm_iv < context.realized_vol:
            allowed_families.add("VOLATILITY_EXPANSION")
        elif context.atm_iv > context.realized_vol:
            allowed_families.add("VOLATILITY_COMPRESSION")
    candidates = []

    for strategy_id, strategy in get_registered_strategies().items():
        if not is_strategy_enabled(strategy_id):
            continue
        if strategy.family not in allowed_families:
            continue
        if not strategy.eligible(context):
            continue
        try:
            result = strategy.build(context)
        except Exception:
            continue
        if not result.eligible:
            continue
        candidate = {
            "strategyId": result.strategy_id,
            "family": result.family,
            "bias": result.bias,
            "definedRisk": result.defined_risk,
            "expiry": result.expiry,
            "legs": result.legs,
            "entryDebit": result.entry_debit,
            "entryCredit": result.entry_credit,
            "maxProfit": result.max_profit,
            "maxLoss": result.max_loss,
            "breakevens": result.breakevens,
            "rewardRisk": result.reward_risk,
            "delta": result.delta,
            "gamma": result.gamma,
            "theta": result.theta,
            "vega": result.vega,
            "margin": result.margin,
            "liquidityScore": result.liquidity_score,
            "executionScore": result.execution_score,
            "strategyScore": result.strategy_score,
            "reasonCodes": result.reason_codes,
            "state": result.state,
            "reason": result.reason,
            "eligible": result.eligible,
            "regime": regime,
            **result.extra,
        }
        candidates.append(candidate)

    candidates.sort(key=lambda row: row.get("strategyScore") or 0, reverse=True)
    return candidates
