"""IRON_CONDOR — range-bound defined-risk strategy."""

from __future__ import annotations

from typing import Any

from ...index_options_seller import build_defined_risk_seller_setup
from .base import OptionStrategy, StrategyResult
from .context import IndexOptionContext


class IronCondorStrategy(OptionStrategy):
    strategy_id = "IRON_CONDOR"
    family = "RANGE"
    bias = "NEUTRAL"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        if context.structure.get("status") != "NO_BREAKOUT":
            return False
        return True

    def build(self, context: IndexOptionContext) -> StrategyResult:
        raw = build_defined_risk_seller_setup(
            chain=context.chain,
            spot=context.spot,
            expiry_value=context.expiry,
            structure=context.structure,
            breadth_neutral=context.breadth,
            breadth_directional=context.breadth,
            futures_oi=context.futures_oi,
            directional_oi_aligned=context.futures_oi_aligned,
            vix=context.atm_iv,
            vix_regime=context.data_limitations[0] if context.data_limitations else None,
            provider_live=context.is_fresh(),
            now=context.session_time,
        )

        strategy_type = raw.get("strategyType")
        if strategy_type != "IRON_CONDOR":
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
                reason_codes=[raw.get("constructionStatus", "WRONG_STRATEGY_TYPE")],
                state="NO_TRADE",
                reason=raw.get("constructionStatus", "WRONG_STRATEGY_TYPE"),
                eligible=False,
                extra={"raw": raw},
            )

        eligible = raw.get("state") == "ELIGIBLE"
        reason = raw.get("reason", "UNKNOWN")
        risk = raw.get("risk", {})
        legs = raw.get("legs", [])
        entry_credit = risk.get("entryCredit")
        max_profit = risk.get("maxProfitPerLot")
        max_loss = risk.get("maxLossPerUnit")
        breakevens = []
        lower = risk.get("lowerBreakEven")
        upper = risk.get("upperBreakEven")
        if lower is not None:
            breakevens.append(lower)
        if upper is not None:
            breakevens.append(upper)
        reward_risk = risk.get("creditToRisk")

        return StrategyResult(
            strategy_id=self.strategy_id,
            family=self.family,
            bias=self.bias,
            defined_risk=self.defined_risk,
            expiry=context.expiry,
            legs=legs,
            entry_debit=None,
            entry_credit=entry_credit,
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            reward_risk=reward_risk,
            delta=None,
            gamma=risk.get("netGamma"),
            theta=risk.get("netTheta"),
            vega=None,
            margin=None,
            liquidity_score=None,
            execution_score=None,
            strategy_score=raw.get("score"),
            reason_codes=[reason] if reason else [],
            state=raw.get("state", "NO_TRADE"),
            reason=reason,
            eligible=eligible,
            extra={
                "scores": raw.get("scores", {}),
                "gates": raw.get("gates", {}),
                "gateEvidence": raw.get("gateEvidence", {}),
                "risk": risk,
                "dataLimitations": raw.get("dataLimitations", []),
                "constructionStatus": raw.get("constructionStatus"),
                "legs": legs,
                "contract": raw.get("primaryContract"),
            },
        )
