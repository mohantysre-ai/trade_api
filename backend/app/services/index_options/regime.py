"""Market regime classification for index-options strategy routing."""

from __future__ import annotations

from typing import Any


def classify_regime(context: Any) -> str:
    structure_status = str(context.structure.get("status") or "").upper()
    direction = (context.direction or "").upper()
    if structure_status == "CONFIRMED" and direction == "CALL":
        return "TREND_UP"
    if structure_status == "CONFIRMED" and direction == "PUT":
        return "TREND_DOWN"
    if structure_status == "NO_BREAKOUT":
        return "RANGE"
    if structure_status == "CONFIRMED" and direction not in {"CALL", "PUT"}:
        return "BREAKOUT"
    return "UNDEFINED"


def eligible_families(regime: str) -> set[str]:
    if regime == "TREND_UP":
        return {"DIRECTIONAL", "VOLATILITY_COMPRESSION"}
    if regime == "TREND_DOWN":
        return {"DIRECTIONAL", "VOLATILITY_COMPRESSION"}
    if regime == "RANGE":
        return {"RANGE", "VOLATILITY_COMPRESSION"}
    if regime == "BREAKOUT":
        return {"DIRECTIONAL"}
    if regime == "VOL_EXPANSION":
        return {"VOLATILITY_EXPANSION", "DIRECTIONAL"}
    if regime == "VOL_COMPRESSION":
        return {"VOLATILITY_COMPRESSION", "RANGE"}
    return set()
