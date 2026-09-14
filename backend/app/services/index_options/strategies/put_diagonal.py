"""PUT_DIAGONAL — Phase 5 term-structure diagonal."""

from __future__ import annotations

from ..strike_selection import build_diagonal_legs, atm_row
from ..economics_v2 import calendar_economics
from .base import OptionStrategy, StrategyResult, structured_result, blocked_result
from .context import IndexOptionContext
from ..strategy_registry import is_strategy_enabled


class PutDiagonalStrategy(OptionStrategy):
    strategy_id = "PUT_DIAGONAL"
    family = "TERM_STRUCTURE"
    bias = "BEARISH"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        if not is_strategy_enabled(self.strategy_id):
            return False
        if context.far_expiry is None:
            return False
        if context.expiry is None:
            return False
        if not context.far_chain:
            return False
        return True

    def build(self, context: IndexOptionContext) -> StrategyResult:
        if not self.eligible(context):
            return blocked_result(
                strategy=self,
                context=context,
                reason="FEATURE_DISABLED_OR_DATA_INCOMPLETE",
            )

        legs = build_diagonal_legs(
            context.chain,
            context.far_chain,
            option_type="PUT",
            spot=context.spot,
            strategy_position_id=self.strategy_id,
            near_expiry=context.expiry,
            far_expiry=context.far_expiry,
            expected_move=context.expected_move,
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
            )

        economics = calendar_economics(legs)
        if economics.entry_debit is None or economics.entry_debit <= 0:
            return structured_result(
                strategy=self,
                context=context,
                legs=legs,
                economics=economics,
                state="NO_TRADE",
                reason="NON_POSITIVE_DEBIT",
                eligible=False,
            )

        return structured_result(
            strategy=self,
            context=context,
            legs=legs,
            economics=economics,
            state="ELIGIBLE",
            reason="DIAGONAL_LEGS_BUILT",
            eligible=True,
        )
