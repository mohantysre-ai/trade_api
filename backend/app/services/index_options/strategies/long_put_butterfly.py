"""LONG_PUT_BUTTERFLY — Phase 4, feature-gated."""

from __future__ import annotations

from ..config import MIN_BUTTERFLY_REWARD_RISK
from ..economics_v2 import long_butterfly_economics
from ..strike_selection import build_long_butterfly_legs
from ..strategy_registry import is_strategy_enabled
from .base import OptionStrategy, StrategyResult, blocked_result, structured_result
from .context import IndexOptionContext


class LongPutButterflyStrategy(OptionStrategy):
    strategy_id = "LONG_PUT_BUTTERFLY"
    family = "RANGE"
    bias = "NEUTRAL"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        if not is_strategy_enabled(self.strategy_id):
            return False
        if context.structure.get("status") not in {"CONFIRMED", "NO_BREAKOUT"}:
            return False
        return True

    def build(self, context: IndexOptionContext) -> StrategyResult:
        if context.spot is None or not context.chain:
            return blocked_result(self, context, reason="DATA_INCOMPLETE", state="NO_TRADE")

        legs = build_long_butterfly_legs(
            context.chain,
            option_type="PUT",
            target=context.spot,
            strategy_position_id=self.strategy_id,
            expiry=context.expiry,
            width=context.expected_move,
        )
        if legs is None:
            return blocked_result(self, context, reason="DATA_INCOMPLETE", state="NO_TRADE")

        economics = long_butterfly_economics(legs, "PUT")
        if economics.reward_risk is None:
            return blocked_result(self, context, reason="ECONOMICS_INVALID", state="NO_TRADE")

        if economics.reward_risk < MIN_BUTTERFLY_REWARD_RISK:
            return StrategyResult(
                strategy_id=self.strategy_id,
                family=self.family,
                bias=self.bias,
                defined_risk=self.defined_risk,
                expiry=context.expiry,
                legs=[leg.to_dict() for leg in legs],
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
                strategy_score=None,
                reason_codes=[f"REWARD_RISK_BELOW_FLOOR:{economics.reward_risk}<{MIN_BUTTERFLY_REWARD_RISK}"],
                state="WATCH",
                reason=f"REWARD_RISK_BELOW_FLOOR:{economics.reward_risk}<{MIN_BUTTERFLY_REWARD_RISK}",
                eligible=False,
            )

        return structured_result(
            self,
            context,
            legs,
            economics,
            state="ELIGIBLE",
            reason="LONG_PUT_BUTTERFLY_GATES_PASSED",
            eligible=True,
        )
