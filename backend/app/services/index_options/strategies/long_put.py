"""LONG_PUT strategy — single-leg long put option."""

from __future__ import annotations

from typing import Any

from ...index_options_engine import _candidate, MIN_ELIGIBLE_SCORE, INDEX_CONFIG
from .base import OptionStrategy, StrategyResult
from .context import IndexOptionContext


class LongPutStrategy(OptionStrategy):
    strategy_id = "LONG_PUT"
    family = "DIRECTIONAL"
    bias = "BEARISH"
    defined_risk = True

    def eligible(self, context: IndexOptionContext) -> bool:
        if context.direction != "PUT":
            return False
        if context.structure.get("status") != "CONFIRMED":
            return False
        score = context.direction_score
        return score is not None and score >= MIN_ELIGIBLE_SCORE

    def build(self, context: IndexOptionContext) -> StrategyResult:
        index_cfg = next((idx for idx in INDEX_CONFIG if idx["key"] == context.index), None)
        if index_cfg is None:
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
                reason_codes=["INDEX_CONFIG_UNAVAILABLE"],
                state="NO_TRADE",
                reason="INDEX_CONFIG_UNAVAILABLE",
                eligible=False,
            )

        snapshot = context.full_snapshot if context.full_snapshot is not None else {}
        raw = _candidate(index_cfg, snapshot)
        state = raw.get("state", "NO_TRADE")
        reason = raw.get("reason", "UNKNOWN")
        eligible = bool(raw.get("eligible"))
        contract = raw.get("contract") or {}
        ltp = contract.get("ltp")
        entry_debit = float(ltp) if ltp is not None else None
        max_loss = entry_debit
        max_profit = None
        breakevens = []
        reward_risk = None
        if entry_debit is not None and entry_debit > 0:
            max_profit = None  # unlimited
            max_loss = entry_debit
            reward_risk = None

        return StrategyResult(
            strategy_id=self.strategy_id,
            family=self.family,
            bias=self.bias,
            defined_risk=self.defined_risk,
            expiry=context.expiry,
            legs=[],
            entry_debit=entry_debit,
            entry_credit=None,
            max_profit=max_profit,
            max_loss=max_loss,
            breakevens=breakevens,
            reward_risk=reward_risk,
            delta=_float(contract.get("delta")),
            gamma=_float(contract.get("gamma")),
            theta=_float(contract.get("theta")),
            vega=_float(contract.get("vega")),
            margin=None,
            liquidity_score=None,
            execution_score=None,
            strategy_score=raw.get("score"),
            reason_codes=[reason] if reason else [],
            state=state,
            reason=reason,
            eligible=eligible,
            extra={
                "contract": contract,
                "gates": raw.get("gates", {}),
                "failedGates": raw.get("failedGates", []),
                "missingInputs": raw.get("missingInputs", []),
                "dataLimitations": raw.get("dataLimitations", []),
                "gateEvidence": raw.get("gateEvidence", {}),
                "chain": raw.get("chain", []),
                "structure": raw.get("structure"),
                "providerStatus": raw.get("providerStatus"),
                "dataSource": raw.get("dataSource"),
                "componentFreshness": raw.get("componentFreshness", {}),
                "spot": raw.get("spot"),
                "direction": raw.get("direction"),
                "scoreFloor": raw.get("scoreFloor"),
            },
        )


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None
