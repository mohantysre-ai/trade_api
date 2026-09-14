"""Base protocol and shared types for index-options strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StrategyResult:
    """Normalized output contract for every strategy candidate."""
    strategy_id: str
    family: str
    bias: str | None
    defined_risk: bool
    expiry: str | None
    legs: list[dict[str, Any]]
    entry_debit: float | None
    entry_credit: float | None
    max_profit: float | None
    max_loss: float | None
    breakevens: list[float]
    reward_risk: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    margin: float | None
    liquidity_score: float | None
    execution_score: float | None
    strategy_score: float | None
    reason_codes: list[str]
    state: str
    reason: str
    eligible: bool
    extra: dict[str, Any] = field(default_factory=dict)


class OptionStrategy(ABC):
    """Deterministic strategy interface."""
    strategy_id: str = ""
    family: str = ""
    bias: str | None = None
    defined_risk: bool = False

    @abstractmethod
    def eligible(self, context: Any) -> bool:
        raise NotImplementedError

    @abstractmethod
    def build(self, context: Any) -> StrategyResult:
        raise NotImplementedError

    def evaluate_economics(self, structure: StrategyResult, context: Any) -> StrategyResult:
        return structure

    def risk(self, structure: StrategyResult, context: Any) -> StrategyResult:
        return structure

    def entry_allowed(self, structure: StrategyResult, context: Any) -> tuple[bool, str]:
        return structure.eligible, structure.reason

    def manage(self, position: dict[str, Any], context: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        return position, None

    def eod(self, position: dict[str, Any]) -> dict[str, Any]:
        return position
