"""BULL_PUT_CREDIT_SPREAD — defined-risk credit spread for bullish outlook."""

from __future__ import annotations

from typing import Any

from ...index_options_seller import (
    MIN_CREDIT_TO_RISK,
    SELLER_MIN_SCORE,
    build_defined_risk_seller_setup,
)
from .base import OptionStrategy, StrategyResult
from .context import IndexOptionContext


class BullPutCreditSpread(OptionStrategy):
    strategy_id = "BULL_PUT_CREDIT_SPREAD"
    family = "VOLATILITY_COMPRESSION"
    bias = "BULLISH"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        if context.direction != "CALL":
            return False
        if context.structure.get("status") not in {"CONFIRMED", "NO_BREAKOUT"}:
            return False
        score = context.futures_oi_state
        return True  # Defer to build() for full eligibility

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
        if strategy_type != "BULL_PUT_CREDIT_SPREAD":
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
        breakevens = [risk.get("lowerBreakEven")] if risk.get("lowerBreakEven") is not None else []
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
