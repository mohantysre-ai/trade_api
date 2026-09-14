"""Re-export base types from parent package for strategy submodules."""

from __future__ import annotations

from ..base import OptionStrategy, StrategyResult

__all__ = ["OptionStrategy", "StrategyResult"]
