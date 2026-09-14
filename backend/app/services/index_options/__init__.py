"""Index-options deterministic multi-strategy architecture.

Phase 1: refactor existing five strategies (LONG_CALL, LONG_PUT,
BULL_PUT_CREDIT_SPREAD, BEAR_CALL_CREDIT_SPREAD, IRON_CONDOR) into
deterministic strategy modules without changing behavior.

Phase 2-5: add new strategies behind feature flags.
"""

from __future__ import annotations

from typing import Any

from .radar_builder import build_index_options_radar_v2
from .strategy_registry import enabled_strategy_ids, get_registered_strategies, is_strategy_enabled
from .strategies import (
    BearCallCreditSpread,
    BearPutDebitSpread,
    BullCallDebitSpread,
    BullPutCreditSpread,
    CallCalendarStrategy,
    CallDiagonalStrategy,
    IronButterflyStrategy,
    IronCondorStrategy,
    LongCallButterflyStrategy,
    LongCallStrategy,
    LongPutButterflyStrategy,
    LongPutStrategy,
    LongStraddleStrategy,
    LongStrangleStrategy,
    PutCalendarStrategy,
    PutDiagonalStrategy,
)

__all__ = [
    "build_index_options_radar_v2",
    "enabled_strategy_ids",
    "is_strategy_enabled",
    "get_registered_strategies",
    "LongCallStrategy",
    "LongPutStrategy",
    "BullPutCreditSpread",
    "BearCallCreditSpread",
    "IronCondorStrategy",
    "BullCallDebitSpread",
    "BearPutDebitSpread",
    "LongStraddleStrategy",
    "LongStrangleStrategy",
    "IronButterflyStrategy",
    "LongCallButterflyStrategy",
    "LongPutButterflyStrategy",
    "CallCalendarStrategy",
    "PutCalendarStrategy",
    "CallDiagonalStrategy",
    "PutDiagonalStrategy",
]
