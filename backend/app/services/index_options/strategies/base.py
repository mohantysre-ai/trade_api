"""Re-export base types from parent package for strategy submodules."""

from __future__ import annotations

from typing import Any
from ..base import OptionStrategy, StrategyResult
from ..legs import OptionLeg

def structured_result(
    strategy: OptionStrategy,
    context: Any,
    legs: list[OptionLeg],
    economics: Any,
    *,
    state: str,
    reason: str,
    eligible: bool,
    reason_codes: list[str] | None = None,
    strategy_score: float | None = None,
    extra: dict[str, Any] | None = None,
) -> StrategyResult:
    # Assemble a StrategyResult from realised legs plus structure economics.
    identity = context.identity() if hasattr(context, "identity") else {}
    leg_dicts = [leg.to_dict() for leg in legs]
    payload: dict[str, Any] = {
        **identity,
        "strategyId": strategy.strategy_id,
        "family": strategy.family,
        "bias": strategy.bias,
        "definedRisk": strategy.defined_risk,
        "index": getattr(context, "index", None),
        "expiry": getattr(context, "expiry", None),
        "dte": getattr(context, "dte", None),
        "legs": leg_dicts,
        "entryDebit": economics.entry_debit,
        "entryCredit": economics.entry_credit,
        "maxProfit": economics.max_profit,
        "maxLoss": economics.max_loss,
        "breakevens": economics.breakevens,
        "rewardRisk": economics.reward_risk,
        "delta": economics.net_delta,
        "gamma": economics.net_gamma,
        "theta": economics.net_theta,
        "vega": economics.net_vega,
        "margin": economics.margin,
        "roundTripCosts": economics.round_trip_costs,
        "width": economics.width,
        "liquidityScore": economics.liquidity_score,
        "executionScore": economics.execution_score,
        "strategyScore": strategy_score,
        "eligibility": state,
        "reasonCodes": reason_codes or [reason],
    }
    if extra:
        payload.update(extra)
    return StrategyResult(
        strategy_id=strategy.strategy_id,
        family=strategy.family,
        bias=strategy.bias,
        defined_risk=strategy.defined_risk,
        expiry=getattr(context, "expiry", None),
        legs=leg_dicts,
        entry_debit=economics.entry_debit,
        entry_credit=economics.entry_credit,
        max_profit=economics.max_profit,
        max_loss=economics.max_loss,
        breakevens=economics.breakevens,
        reward_risk=economics.reward_risk,
        delta=economics.net_delta,
        gamma=economics.net_gamma,
        theta=economics.net_theta,
        vega=economics.net_vega,
        margin=economics.margin,
        liquidity_score=economics.liquidity_score,
        execution_score=economics.execution_score,
        strategy_score=strategy_score,
        reason_codes=reason_codes or [reason],
        state=state,
        reason=reason,
        eligible=eligible,
        extra=payload,
    )


def blocked_result(
    strategy: OptionStrategy,
    context: Any,
    *,
    reason: str,
    state: str = "BLOCKED",
) -> StrategyResult:
    # A non-eligible result carrying a deterministic blocking reason.
    identity = context.identity() if hasattr(context, "identity") else {}
    return StrategyResult(
        strategy_id=strategy.strategy_id,
        family=strategy.family,
        bias=strategy.bias,
        defined_risk=strategy.defined_risk,
        expiry=getattr(context, "expiry", None),
        legs=[],
        entry_debit=None,
        entry_credit=None,
        max_profit=None,
        max_loss=None,
        breakevens=[],
        reward_risk=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        margin=None,
        liquidity_score=None,
        execution_score=None,
        strategy_score=None,
        reason_codes=[reason],
        state=state,
        reason=reason,
        eligible=False,
        extra={
            **identity,
            "strategyId": strategy.strategy_id,
            "family": strategy.family,
            "index": getattr(context, "index", None),
            "eligibility": state,
            "legs": [],
        },
    )

__all__ = ["OptionStrategy", "StrategyResult", "structured_result", "blocked_result"]
