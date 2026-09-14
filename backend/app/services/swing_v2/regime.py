from __future__ import annotations

from typing import Any


def classify_regime(inputs: dict[str, Any]) -> dict[str, Any]:
    required = ("nifty500Close", "nifty500Ema20", "breadthAboveEma20Pct", "nifty500Return5dPct", "vixPercentile", "vixChange1dPct")
    missing = [key for key in required if inputs.get(key) is None]
    if missing:
        return {"state": "REGIME_UNRATED", "riskScale": 0.0, "positionCap": 0, "stressPoints": None, "reasonCodes": [f"MISSING_{key}" for key in missing]}
    checks = {
        "INDEX_BELOW_EMA20": float(inputs["nifty500Close"]) < float(inputs["nifty500Ema20"]),
        "BREADTH_BELOW_40": float(inputs["breadthAboveEma20Pct"]) < 40,
        "INDEX_5D_AT_OR_BELOW_MINUS_3": float(inputs["nifty500Return5dPct"]) <= -3,
        "VIX_STRESS": float(inputs["vixPercentile"]) >= 85 or float(inputs["vixChange1dPct"]) >= 15,
    }
    points = sum(checks.values())
    state, scale, cap = ("NORMAL", 1.0, 5) if points <= 1 else (("DEFENSIVE", .5, 2) if points == 2 else ("HALT_NEW_LONGS", 0.0, 0))
    return {"state": state, "riskScale": scale, "positionCap": cap, "stressPoints": points, "reasonCodes": [key for key, active in checks.items() if active]}
