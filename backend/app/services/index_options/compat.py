"""Compatibility adapter: converts new StrategyResult to legacy radar dict format."""

from __future__ import annotations

from typing import Any

from .base import StrategyResult


def strategy_result_to_legacy(result: StrategyResult, index_config: dict[str, Any]) -> dict[str, Any]:
    """Convert a StrategyResult to the legacy candidate/seller dict format."""
    base = {
        **index_config,
        "spot": None,
        "direction": (result.bias or "").upper() if result.bias else None,
        "state": result.state,
        "reason": result.reason,
        "score": result.strategy_score,
        "scoreFloor": None,
        "failedGates": [],
        "gates": {},
        "missingInputs": [],
        "strategyMode": "BUY_PREMIUM" if result.family == "DIRECTIONAL" else "SELL_PREMIUM",
        "strategyType": result.strategy_id,
        "bias": result.bias,
        "eligible": result.eligible,
        "providerStatus": None,
        "dataSource": None,
        "expiry": result.expiry,
        "dataLimitations": result.reason_codes,
        "gateEvidence": {},
        "chain": [],
        "structure": {},
        "oiResearch": {},
        "componentFreshness": {},
    }

    if result.family == "DIRECTIONAL":
        base.update({
            "contract": result.extra.get("contract"),
            "failedGates": result.extra.get("failedGates", []),
            "missingInputs": result.extra.get("missingInputs", []),
            "gates": result.extra.get("gates", {}),
            "gateEvidence": result.extra.get("gateEvidence", {}),
            "chain": result.extra.get("chain", []),
            "structure": result.extra.get("structure"),
            "providerStatus": result.extra.get("providerStatus"),
            "dataSource": result.extra.get("dataSource"),
            "componentFreshness": result.extra.get("componentFreshness", {}),
            "dataLimitations": result.extra.get("dataLimitations", []),
            "scoreFloor": result.extra.get("scoreFloor"),
        })
    else:
        base.update({
            "legs": result.legs,
            "scores": result.extra.get("scores", {}),
            "gates": result.extra.get("gates", {}),
            "risk": result.extra.get("risk", {}),
            "constructionStatus": result.extra.get("constructionStatus"),
            "gateEvidence": result.extra.get("gateEvidence", {}),
            "dataLimitations": result.extra.get("dataLimitations", []),
            "primaryContract": result.extra.get("contract"),
            "providerStatus": result.extra.get("providerStatus"),
            "dataSource": result.extra.get("dataSource"),
            "componentFreshness": result.extra.get("componentFreshness", {}),
        })

    return base
