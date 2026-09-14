"""Frozen configuration surface for the modular index-options engine.

Everything the strategy modules, economics, execution and lifecycle layers read
lives here so parallel workstreams share one contract. Values are conservative
by default and every new-family flag is OFF unless explicitly enabled.
"""

from __future__ import annotations

import os
from typing import Any

# --- Feature flags (all new families default OFF) ---------------------------
def _flag(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def debit_spreads_enabled() -> bool:
    return _flag("INDEX_STRAT_DEBIT_SPREADS")


def long_vol_enabled() -> bool:
    return _flag("INDEX_STRAT_LONG_VOL")


def butterflies_enabled() -> bool:
    return _flag("INDEX_STRAT_BUTTERFLIES")


def calendars_enabled() -> bool:
    return _flag("INDEX_STRAT_CALENDARS")


def diagonals_enabled() -> bool:
    return _flag("INDEX_STRAT_DIAGONALS")


# --- Family routing ---------------------------------------------------------
FAMILY_DIRECTIONAL = "DIRECTIONAL"
FAMILY_VOL_COMPRESSION = "VOLATILITY_COMPRESSION"
FAMILY_VOL_EXPANSION = "VOLATILITY_EXPANSION"
FAMILY_RANGE = "RANGE"
FAMILY_TERM_STRUCTURE = "TERM_STRUCTURE"

FAMILY_BY_STRATEGY: dict[str, str] = {
    "LONG_CALL": FAMILY_DIRECTIONAL,
    "LONG_PUT": FAMILY_DIRECTIONAL,
    "BULL_CALL_DEBIT_SPREAD": FAMILY_DIRECTIONAL,
    "BEAR_PUT_DEBIT_SPREAD": FAMILY_DIRECTIONAL,
    "BULL_PUT_CREDIT_SPREAD": FAMILY_VOL_COMPRESSION,
    "BEAR_CALL_CREDIT_SPREAD": FAMILY_VOL_COMPRESSION,
    "IRON_CONDOR": FAMILY_RANGE,
    "IRON_BUTTERFLY": FAMILY_RANGE,
    "LONG_CALL_BUTTERFLY": FAMILY_RANGE,
    "LONG_PUT_BUTTERFLY": FAMILY_RANGE,
    "LONG_STRADDLE": FAMILY_VOL_EXPANSION,
    "LONG_STRANGLE": FAMILY_VOL_EXPANSION,
    "CALL_CALENDAR": FAMILY_TERM_STRUCTURE,
    "PUT_CALENDAR": FAMILY_TERM_STRUCTURE,
    "CALL_DIAGONAL": FAMILY_TERM_STRUCTURE,
    "PUT_DIAGONAL": FAMILY_TERM_STRUCTURE,
}

LEGACY_ALWAYS_ENABLED = (
    "LONG_CALL",
    "LONG_PUT",
    "BULL_PUT_CREDIT_SPREAD",
    "BEAR_CALL_CREDIT_SPREAD",
    "IRON_CONDOR",
)

# --- Regime vocabulary ------------------------------------------------------
REGIME_TREND_UP = "TREND_UP"
REGIME_TREND_DOWN = "TREND_DOWN"
REGIME_BREAKOUT_UP = "BREAKOUT_UP"
REGIME_BREAKOUT_DOWN = "BREAKOUT_DOWN"
REGIME_RANGE = "RANGE"
REGIME_VOL_EXPANSION = "VOL_EXPANSION"
REGIME_VOL_COMPRESSION = "VOL_COMPRESSION"
REGIME_PINNING = "PINNING"
REGIME_EVENT_VOL = "EVENT_VOL"
REGIME_UNDEFINED = "UNDEFINED"

# --- Execution / liquidity thresholds ---------------------------------------
# Maximum acceptable bid/ask spread as a percentage of the ask for a leg.
MAX_LEG_SPREAD_PCT = float(os.getenv("INDEX_MAX_LEG_SPREAD_PCT", "4.0"))
# Minimum acceptable volume on a leg when volume evidence is present.
MIN_LEG_VOLUME = int(os.getenv("INDEX_MIN_LEG_VOLUME", "0"))
# Minimum acceptable open interest on a leg (0 disables the check).
MIN_LEG_OI = int(os.getenv("INDEX_MIN_LEG_OI", "0"))
# Paper slippage applied conservatively against the trader (in premium points).
PAPER_SLIPPAGE_POINTS = float(os.getenv("INDEX_PAPER_SLIPPAGE_POINTS", "0.0"))

# --- Reward/risk minimums ---------------------------------------------------
MIN_DEBIT_SPREAD_REWARD_RISK = float(os.getenv("INDEX_MIN_DEBIT_SPREAD_RR", "1.0"))
MIN_CREDIT_SPREAD_REWARD_RISK = float(os.getenv("INDEX_MIN_CREDIT_SPREAD_RR", "0.25"))
MIN_BUTTERFLY_REWARD_RISK = float(os.getenv("INDEX_MIN_BUTTERFLY_RR", "1.5"))

# --- Volatility expansion buffers -------------------------------------------
# Required move must exceed breakeven move plus this safety buffer (points).
STRADDLE_SAFETY_BUFFER = float(os.getenv("INDEX_STRADDLE_SAFETY_BUFFER", "0.0"))
STRANGLE_EXTRA_BUFFER = float(os.getenv("INDEX_STRANGLE_EXTRA_BUFFER", "0.0"))

# --- Expiry-day handling ----------------------------------------------------
EXPIRY_DAY_NEW_ENTRY_CUTOFF_IST = os.getenv("INDEX_EXPIRY_CUTOFF_IST", "14:30")


def reward_risk_floor(strategy_id: str) -> float:
    if strategy_id in {"BULL_CALL_DEBIT_SPREAD", "BEAR_PUT_DEBIT_SPREAD"}:
        return MIN_DEBIT_SPREAD_REWARD_RISK
    if strategy_id in {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR", "IRON_BUTTERFLY"}:
        return MIN_CREDIT_SPREAD_REWARD_RISK
    if strategy_id in {"LONG_CALL_BUTTERFLY", "LONG_PUT_BUTTERFLY"}:
        return MIN_BUTTERFLY_REWARD_RISK
    return 0.0


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None
