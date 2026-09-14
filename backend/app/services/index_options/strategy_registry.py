"""Central strategy registry with feature-flag gating."""

from __future__ import annotations

from typing import Any

from .base import OptionStrategy
from .config import butterflies_enabled, calendars_enabled, debit_spreads_enabled, diagonals_enabled, long_vol_enabled

# Feature flags — all new strategies default OFF.
# Phase 1 — always enabled (existing authoritative behavior).
_ALWAYS_ENABLED = {
    "LONG_CALL",
    "LONG_PUT",
    "BULL_PUT_CREDIT_SPREAD",
    "BEAR_CALL_CREDIT_SPREAD",
    "IRON_CONDOR",
}

_REGISTRY: dict[str, OptionStrategy] = {}


def register_strategy(strategy: OptionStrategy) -> None:
    _REGISTRY[strategy.strategy_id] = strategy


def get_registered_strategies() -> dict[str, OptionStrategy]:
    return dict(_REGISTRY)


def is_strategy_enabled(strategy_id: str) -> bool:
    if strategy_id in _ALWAYS_ENABLED:
        return True
    if strategy_id in {"BULL_CALL_DEBIT_SPREAD", "BEAR_PUT_DEBIT_SPREAD"}:
        return debit_spreads_enabled()
    if strategy_id in {"LONG_STRADDLE", "LONG_STRANGLE"}:
        return long_vol_enabled()
    if strategy_id in {"IRON_BUTTERFLY", "LONG_CALL_BUTTERFLY", "LONG_PUT_BUTTERFLY"}:
        return butterflies_enabled()
    if strategy_id in {"CALL_CALENDAR", "PUT_CALENDAR"}:
        return calendars_enabled()
    if strategy_id in {"CALL_DIAGONAL", "PUT_DIAGONAL"}:
        return diagonals_enabled()
    return False


def enabled_strategy_ids() -> list[str]:
    return [sid for sid in _REGISTRY if is_strategy_enabled(sid)]
