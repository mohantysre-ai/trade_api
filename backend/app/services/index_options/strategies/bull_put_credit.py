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


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n else None


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
        seller = (context.raw_snapshot.get("seller") if isinstance(context.raw_snapshot.get("seller"), dict) else {}) or {}
        if seller:
            return self._from_seller_dict(seller, context)

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
        return self._from_build(raw, context)

    def _from_seller_dict(self, seller: dict[str, Any], context: IndexOptionContext) -> StrategyResult:
        strategy_type = str(seller.get("strategyType") or "")
        bias = str(seller.get("bias") or "").upper()
        construction_status = str(seller.get("constructionStatus") or "")
        legs = seller.get("legs") or []
        risk = seller.get("risk") or {}
        scores = seller.get("scores") or {}
        gates = seller.get("gates") or {}
        score = round(sum((_num(v) or 0.0) * w / 100.0 for v, w in {
            "structure": 15, "futuresRegime": 10, "optionChain": 15, "breadth": 15,
            "volatilityEdge": 15, "contract": 20, "theta": 10,
        }.items()), 2) if scores else None
        required_gates = ("fresh", "structure", "futuresRegime", "optionChain", "breadth", "volatilityEdge",
                          "contractEconomics", "definedRisk", "thetaCarry", "tailBuffer", "timeWindow")
        failed = [name for name in required_gates if gates.get(name) is False]
        unavailable = [name for name in required_gates if gates.get(name) is not True and name not in failed]
        if construction_status:
            state, reason = "NO_TRADE", f"SELLER_CONSTRUCTION_FAILED:{construction_status}"
            eligible = False
        elif not strategy_type or not bias:
            state, reason = "NO_TRADE", "SELLER_STRUCTURE_UNAVAILABLE"
            eligible = False
        elif failed:
            state, reason = "NO_TRADE", f"SELLER_GATE_FAILED:{','.join(failed)}"
            eligible = False
        elif unavailable:
            state, reason = "NO_TRADE", f"SELLER_DATA_INCOMPLETE:{','.join(sorted(set(unavailable)))}"
            eligible = False
        elif score is not None and score < SELLER_MIN_SCORE:
            state, reason = "WATCH", "SELLER_SCORE_BELOW_FLOOR"
            eligible = False
        else:
            state, reason = "ELIGIBLE", "DEFINED_RISK_SELLER_GATES_PASSED"
            eligible = True
        entry_credit = risk.get("entryCredit")
        max_profit = risk.get("maxProfitPerLot")
        max_loss = risk.get("maxLossPerUnit")
        breakevens = [risk.get("lowerBreakEven")] if risk.get("lowerBreakEven") is not None else []
        reward_risk = risk.get("creditToRisk")
        return StrategyResult(
            strategy_id=self.strategy_id,
            family=self.family,
            bias=bias or self.bias,
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
            strategy_score=score,
            reason_codes=[reason] if reason else [],
            state=state,
            reason=reason,
            eligible=eligible,
            extra={
                "scores": scores,
                "gates": gates,
                "gateEvidence": seller.get("gateEvidence", {}),
                "risk": risk,
                "dataLimitations": seller.get("dataLimitations") or [],
                "constructionStatus": construction_status or None,
                "legs": legs,
                "contract": seller.get("primaryContract"),
            },
        )

    def _from_build(self, raw: dict[str, Any], context: IndexOptionContext) -> StrategyResult:
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
