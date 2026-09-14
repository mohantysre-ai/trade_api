"""LONG_STRADDLE — Phase 3, feature-gated."""

from __future__ import annotations

from .base import OptionStrategy, StrategyResult
from .context import IndexOptionContext


class LongStraddleStrategy(OptionStrategy):
    strategy_id = "LONG_STRADDLE"
    family = "VOLATILITY_EXPANSION"
    bias = "NEUTRAL"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        return False

    def build(self, context: IndexOptionContext) -> StrategyResult:
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
            reason_codes=["PHASE_3_NOT_ENABLED"],
            state="NO_TRADE",
            reason="PHASE_3_NOT_ENABLED",
            eligible=False,
        )
