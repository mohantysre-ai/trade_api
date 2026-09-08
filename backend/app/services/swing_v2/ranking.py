from __future__ import annotations

from typing import Any

WEIGHTS = {
    "trendPriorPctile": 0.20,
    "residualStrengthPctile": 0.20,
    "setupQualityPctile": 0.15,
    "rvolPctile": 0.15,
    "clvPctile": 0.10,
    "sectorStrengthPctile": 0.10,
    "liquidityPctile": 0.10,
}


def rank_score(row: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in WEIGHTS if row.get(key) is None]
    if missing:
        return {"score": None, "status": "UNRATED", "reasonCodes": [f"MISSING_{key}" for key in missing]}
    base = sum(float(row[key]) * weight for key, weight in WEIGHTS.items())
    penalties: dict[str, float] = {}
    if float(row.get("extensionAtr") or 0) > 2:
        penalties["EXTENSION_ABOVE_2ATR"] = 10
    if float(row.get("unexplainedGapPct") or 0) > 2:
        penalties["UNEXPLAINED_GAP_ABOVE_2PCT"] = 10
    if float(row.get("sectorStrengthPctile") or 100) < 40:
        penalties["WEAK_SECTOR"] = 10
    cost_penalty = float(row.get("costPenalty") or 0)
    if cost_penalty:
        penalties["ELEVATED_COST"] = min(15, max(5, cost_penalty))
    return {"score": max(0.0, min(100.0, base - sum(penalties.values()))), "baseScore": base, "penalties": penalties, "status": "RATED"}


def assign_segment_percentiles(rows: list[dict[str, Any]], score_key: str = "score") -> list[dict[str, Any]]:
    by_segment: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_segment.setdefault(str(row.get("universeSegment") or "UNRATED"), []).append(row)
    out = []
    for group in by_segment.values():
        ranked = sorted(group, key=lambda r: float(r.get(score_key) or 0))
        denominator = max(1, len(ranked) - 1)
        for index, row in enumerate(ranked):
            out.append({**row, "segmentPercentile": round(100 * index / denominator, 4)})
    return out
