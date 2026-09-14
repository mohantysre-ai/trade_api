"""LONG_STRADDLE — long volatility expansion strategy."""

from __future__ import annotations

from typing import Any

from ..strike_selection import build_straddle_legs, executable_rows
from ..economics_v2 import long_vol_economics
from .base import OptionStrategy, StrategyResult, structured_result
from .context import IndexOptionContext
from ..strategy_registry import is_strategy_enabled


class LongStraddleStrategy(OptionStrategy):
    strategy_id = "LONG_STRADDLE"
    family = "VOLATILITY_EXPANSION"
    bias = "NEUTRAL"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        if not is_strategy_enabled(self.strategy_id):
            return False
        if context.structure.get("status") not in {"CONFIRMED", "NO_BREAKOUT"}:
            return False
        chain = context.chain or []
        call_rows = executable_rows(chain, "CALL")
        put_rows = executable_rows(chain, "PUT")
        if not call_rows or not put_rows:
            return False
        return True

    def build(self, context: IndexOptionContext) -> StrategyResult:
        if not context.chain or not context.expiry or context.spot is None:
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

        legs = build_straddle_legs(
            context.chain,
            spot=context.spot,
            strategy_position_id=context.snapshot_id or "STRADDLE",
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
                reason_codes=["CHAIN_INSUFFICIENT"],
                state="NO_TRADE",
                reason="CHAIN_INSUFFICIENT",
                eligible=False,
            )

        for leg in legs:
            if leg.entry_price is None and leg.entry_mid is not None:
                leg.entry_price = leg.entry_mid

        econ = long_vol_economics(list(legs), context.spot)
        if econ.entry_debit is None or econ.max_loss is None or econ.max_loss <= 0 or not econ.breakevens:
            return StrategyResult(
                strategy_id=self.strategy_id,
                family=self.family,
                bias=self.bias,
                defined_risk=self.defined_risk,
                expiry=context.expiry,
                legs=[],
                entry_debit=econ.entry_debit,
                entry_credit=None,
                max_profit=None,
                max_loss=econ.max_loss,
                breakevens=econ.breakevens,
                reward_risk=None,
                delta=econ.net_delta,
                gamma=econ.net_gamma,
                theta=econ.net_theta,
                vega=econ.net_vega,
                margin=econ.margin,
                liquidity_score=None,
                execution_score=None,
                strategy_score=None,
                reason_codes=["ECONOMICS_INCOMPLETE"],
                state="NO_TRADE",
                reason="ECONOMICS_INCOMPLETE",
                eligible=False,
            )

        score = 50.0
        return structured_result(
            strategy=self,
            context=context,
            legs=list(legs),
            economics=econ,
            state="ELIGIBLE",
            reason="LONG_VOL_GATES_PASSED",
            eligible=True,
            strategy_score=score,
            reason_codes=["LONG_VOL_GATES_PASSED"],
            extra={
                "width": econ.width,
                "roundTripCosts": econ.round_trip_costs,
            },
        )
