"""Central strategy registry with feature-flag gating."""

from __future__ import annotations

import os
from typing import Any

from .base import OptionStrategy

# Feature flags — all new strategies default OFF.
INDEX_STRAT_DEBIT_SPREADS = os.getenv("INDEX_STRAT_DEBIT_SPREADS", "0").strip().lower() in {"1", "true", "yes"}
INDEX_STRAT_LONG_VOL = os.getenv("INDEX_STRAT_LONG_VOL", "0").strip().lower() in {"1", "true", "yes"}
INDEX_STRAT_BUTTERFLIES = os.getenv("INDEX_STRAT_BUTTERFLIES", "0").strip().lower() in {"1", "true", "yes"}
INDEX_STRAT_CALENDARS = os.getenv("INDEX_STRAT_CALENDARS", "0").strip().lower() in {"1", "true", "yes"}
INDEX_STRAT_DIAGONALS = os.getenv("INDEX_STRAT_DIAGONALS", "0").strip().lower() in {"1", "true", "yes"}

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
        return INDEX_STRAT_DEBIT_SPREADS
    if strategy_id in {"LONG_STRADDLE", "LONG_STRANGLE"}:
        return INDEX_STRAT_LONG_VOL
    if strategy_id in {"IRON_BUTTERFLY", "LONG_CALL_BUTTERFLY", "LONG_PUT_BUTTERFLY"}:
        return INDEX_STRAT_BUTTERFLIES
    if strategy_id in {"CALL_CALENDAR", "PUT_CALENDAR"}:
        return INDEX_STRAT_CALENDARS
    if strategy_id in {"CALL_DIAGONAL", "PUT_DIAGONAL"}:
        return INDEX_STRAT_DIAGONALS
    return False


def enabled_strategy_ids() -> list[str]:
    return [sid for sid in _REGISTRY if is_strategy_enabled(sid)]
