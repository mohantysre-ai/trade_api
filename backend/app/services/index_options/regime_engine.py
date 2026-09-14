"""Deterministic market-regime engine.

Regime is computed once per decision cycle from the immutable context, before
strategy ranking. Strategies whose family is incompatible with the classified
regime are reported BLOCKED / REGIME_MISMATCH — never assigned a fake low score.

This module is pure: given the same context it always returns the same regime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import (
    FAMILY_DIRECTIONAL,
    FAMILY_RANGE,
    FAMILY_TERM_STRUCTURE,
    FAMILY_VOL_COMPRESSION,
    FAMILY_VOL_EXPANSION,
    REGIME_BREAKOUT_DOWN,
    REGIME_BREAKOUT_UP,
    REGIME_EVENT_VOL,
    REGIME_PINNING,
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
    REGIME_UNDEFINED,
    REGIME_VOL_COMPRESSION,
    REGIME_VOL_EXPANSION,
)

# Thresholds (deterministic, tunable via constructor args only).
_IV_RANK_HIGH = 60.0
_IV_RANK_LOW = 25.0
_VOL_EXPANSION_REALIZED_GAP = 0.10  # implied - realized relative gap
_EXPECTED_MOVE_STRONG = 1.0  # expected_move / spot * 100 >= this
_RANGE_BREAKOUT_ATR = 1.0


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    reason: str
    evidence: dict[str, Any]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _family_map(regime: str) -> set[str]:
    if regime in {REGIME_TREND_UP, REGIME_TREND_DOWN}:
        return {FAMILY_DIRECTIONAL, FAMILY_VOL_COMPRESSION}
    if regime in {REGIME_BREAKOUT_UP, REGIME_BREAKOUT_DOWN}:
        return {FAMILY_DIRECTIONAL}
    if regime == REGIME_RANGE:
        return {FAMILY_RANGE, FAMILY_VOL_COMPRESSION}
    if regime == REGIME_PINNING:
        return {FAMILY_RANGE, FAMILY_VOL_COMPRESSION}
    if regime == REGIME_VOL_EXPANSION:
        return {FAMILY_VOL_EXPANSION, FAMILY_DIRECTIONAL}
    if regime == REGIME_VOL_COMPRESSION:
        return {FAMILY_VOL_COMPRESSION, FAMILY_RANGE}
    if regime == REGIME_EVENT_VOL:
        return {FAMILY_VOL_EXPANSION, FAMILY_TERM_STRUCTURE}
    return set()


def classify_regime_result(context: Any) -> RegimeResult:
    """Return the regime plus the deterministic evidence used to derive it."""
    structure = getattr(context, "structure", None) or {}
    status = str(structure.get("status") or "").upper()
    direction = (getattr(context, "direction", None) or "").upper()
    spot = _num(getattr(context, "spot", None))
    iv_rank = _num(getattr(context, "iv_rank", None))
    realized = _num(getattr(context, "realized_vol", None))
    atm_iv = _num(getattr(context, "atm_iv", None))
    expected_move = _num(getattr(context, "expected_move", None))
    dte = getattr(context, "dte", None)

    evidence: dict[str, Any] = {
        "structureStatus": status or None,
        "direction": direction or None,
        "ivRank": iv_rank,
        "atmIv": atm_iv,
        "realizedVol": realized,
        "expectedMove": expected_move,
        "dte": dte,
    }

    # 0. Missing material evidence never yields a tradeable regime.
    if spot is None:
        return RegimeResult(REGIME_UNDEFINED, "SPOT_UNAVAILABLE", evidence)

    # 1. Event volatility — expiry day or very short DTE with elevated IV rank.
    if (dte is not None and dte <= 1) and (
        iv_rank is not None and iv_rank >= _IV_RANK_HIGH
    ):
        return RegimeResult(REGIME_EVENT_VOL, "EXPIRY_EVENT_IV", evidence)

    # 2. Volatility expansion — implied well above realized with a strong move.
    if realized is not None and atm_iv is not None and realized > 0:
        rel_gap = (atm_iv - realized) / realized
        evidence["impliedRealizedGap"] = round(rel_gap, 4)
        if rel_gap >= _VOL_EXPANSION_REALIZED_GAP and (
            expected_move is None
            or (spot and expected_move / spot * 100.0 >= _EXPECTED_MOVE_STRONG)
        ):
            return RegimeResult(
                REGIME_VOL_EXPANSION, "IMPLIED_ABOVE_REALIZED", evidence
            )

    # 3. Volatility compression — low IV rank with flat structure.
    if (
        iv_rank is not None
        and iv_rank <= _IV_RANK_LOW
        and status in {"NO_BREAKOUT", ""}
    ):
        return RegimeResult(REGIME_VOL_COMPRESSION, "LOW_IV_RANK_FLAT", evidence)

    # 4. Directional trend / breakout from confirmed structure.
    if status == "CONFIRMED" and direction == "CALL":
        return RegimeResult(REGIME_TREND_UP, "CONFIRMED_CALL", evidence)
    if status == "CONFIRMED" and direction == "PUT":
        return RegimeResult(REGIME_TREND_DOWN, "CONFIRMED_PUT", evidence)

    # 5. Breakout without a proven direction.
    if status in {"BREAKOUT", "BREAKOUT_UP", "BREAKOUT_DOWN"}:
        if status == "BREAKOUT_UP" or direction == "CALL":
            return RegimeResult(REGIME_BREAKOUT_UP, "UNRESOLVED_BREAKOUT_UP", evidence)
        if status == "BREAKOUT_DOWN" or direction == "PUT":
            return RegimeResult(
                REGIME_BREAKOUT_DOWN, "UNRESOLVED_BREAKOUT_DOWN", evidence
            )
        return RegimeResult(REGIME_UNDEFINED, "BREAKOUT_DIRECTION_UNPROVEN", evidence)

    # 6. Range / pinning — no breakout, and pinning when IV rank is high but flat.
    if status == "NO_BREAKOUT":
        if iv_rank is not None and iv_rank >= _IV_RANK_HIGH:
            return RegimeResult(REGIME_PINNING, "FLAT_HIGH_IV_PINNING", evidence)
        return RegimeResult(REGIME_RANGE, "NO_BREAKOUT", evidence)

    return RegimeResult(REGIME_UNDEFINED, "INSUFFICIENT_STRUCTURE_EVIDENCE", evidence)


def classify_regime(context: Any) -> str:
    return classify_regime_result(context).regime


def eligible_families(regime: str) -> set[str]:
    return _family_map(regime)


def family_is_eligible(regime: str, family: str) -> bool:
    return family in _family_map(regime)
