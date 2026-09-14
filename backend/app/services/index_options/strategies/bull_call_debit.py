"""BULL_CALL_DEBIT_SPREAD — Phase 2 debit spread strategy."""

from __future__ import annotations

from ..strategy_registry import is_strategy_enabled
from ..strike_selection import build_debit_spread_legs, executable_rows
from ..economics_v2 import debit_spread_economics
from ..config import MIN_DEBIT_SPREAD_REWARD_RISK
from .base import OptionStrategy, StrategyResult, structured_result
from .context import IndexOptionContext


class BullCallDebitSpread(OptionStrategy):
    strategy_id = "BULL_CALL_DEBIT_SPREAD"
    family = "DIRECTIONAL"
    bias = "BULLISH"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        if not is_strategy_enabled(self.strategy_id):
            return False
        if context.direction != "CALL":
            return False
        if context.structure.get("status") != "CONFIRMED":
            return False
        if not executable_rows(context.chain, "CALL"):
            return False
        return True

    def build(self, context: IndexOptionContext) -> StrategyResult:
        if not is_strategy_enabled(self.strategy_id):
            return StrategyResult(
                strategy_id=self.strategy_id,
                family=self.family,
                bias=self.bias,
                defined_risk=self.defined_risk,
                expiry=context.expiry,
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
                reason_codes=["DEBIT_SPREAD_NOT_ENABLED"],
                state="NO_TRADE",
                reason="DEBIT_SPREAD_NOT_ENABLED",
                eligible=False,
                extra={
                    "chain": context.chain,
                    "structure": context.structure,
                    "gates": {
                        "featureEnabled": False,
                        "direction": context.direction,
                        "structureStatus": context.structure.get("status"),
                        "callLegsAvailable": bool(executable_rows(context.chain, "CALL")),
                    },
                },
            )

        legs = build_debit_spread_legs(
            context.chain,
            option_type="CALL",
            spot=context.spot or 0.0,
            expected_move=context.expected_move,
            strategy_position_id=self.strategy_id,
            expiry=context.expiry,
        )

        if legs is None:
            return StrategyResult(
                strategy_id=self.strategy_id,
                family=self.family,
                bias=self.bias,
                defined_risk=self.defined_risk,
                expiry=context.expiry,
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
                reason_codes=["DATA_INCOMPLETE"],
                state="NO_TRADE",
                reason="DATA_INCOMPLETE",
                eligible=False,
                extra={
                    "chain": context.chain,
                    "structure": context.structure,
                    "gates": {
                        "featureEnabled": True,
                        "direction": context.direction,
                        "structureStatus": context.structure.get("status"),
                        "callLegsAvailable": bool(executable_rows(context.chain, "CALL")),
                    },
                },
            )

        economics = debit_spread_economics(legs, "CALL")

        reason_codes = []
        state = "NO_TRADE"
        reason = "UNKNOWN"
        eligible = False
        strategy_score = None

        if economics.entry_debit is None or economics.entry_debit <= 0:
            reason_codes = ["INVALID_DEBIT"]
            state = "NO_TRADE"
            reason = "INVALID_DEBIT"
        elif economics.width is None or economics.entry_debit >= economics.width:
            reason_codes = ["DEBIT_GTE_WIDTH"]
            state = "NO_TRADE"
            reason = "DEBIT_GTE_WIDTH"
        elif economics.reward_risk is None or economics.reward_risk < MIN_DEBIT_SPREAD_REWARD_RISK:
            reason_codes = ["RR_BELOW_FLOOR"]
            state = "NO_TRADE"
            reason = "RR_BELOW_FLOOR"
        else:
            eligible = True
            state = "ELIGIBLE"
            reason = "DEBIT_SPREAD_GATES_PASSED"
            reason_codes = [reason]
            strategy_score = round(economics.reward_risk, 4)

        return structured_result(
            strategy=self,
            context=context,
            legs=legs,
            economics=economics,
            state=state,
            reason=reason,
            eligible=eligible,
            reason_codes=reason_codes,
            strategy_score=strategy_score,
            extra={
                "chain": context.chain,
                "structure": context.structure,
                "gates": {
                    "featureEnabled": True,
                    "direction": context.direction,
                    "structureStatus": context.structure.get("status"),
                    "callLegsAvailable": bool(executable_rows(context.chain, "CALL")),
                },
            },
        )
