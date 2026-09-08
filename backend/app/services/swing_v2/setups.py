from __future__ import annotations

from typing import Any


def _f(row: dict[str, Any], key: str) -> float | None:
    try:
        value = row.get(key)
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def breakout_close_v1(row: dict[str, Any]) -> tuple[bool, list[str]]:
    rules = [
        ("TREND_PRIOR_P60", _f(row, "trendPriorPctile"), lambda v: v >= 60),
        ("BREAKS_PRIOR_20D_HIGH", _f(row, "decisionPrice"), lambda v: v >= float(row.get("prior20dHigh") or 1e99)),
        ("CLV_080", _f(row, "clv"), lambda v: v >= 0.80),
        ("RVOL_150", _f(row, "rvolPaced"), lambda v: v >= 1.50),
        ("RESIDUAL_P70", _f(row, "residualStrengthPctile"), lambda v: v >= 70),
        ("SECTOR_P50", _f(row, "sectorStrengthPctile"), lambda v: v >= 50),
        ("BREAKOUT_DISTANCE", _f(row, "breakoutDistanceAtr"), lambda v: 0 <= v <= 0.75),
        ("EXTENSION_MAX", _f(row, "extensionAtr"), lambda v: v <= 2.50),
    ]
    failed = [name for name, value, test in rules if value is None or not test(value)]
    return not failed, failed


def pullback_reclaim_v1(row: dict[str, Any]) -> tuple[bool, list[str]]:
    required = {
        "trendPriorPctile": lambda v: v >= 70,
        "distanceToPrior20dHighAtr": lambda v: v <= 1.50,
        "intradayLowToVwapAtr": lambda v: v <= 0.10,
        "last3ClosesAboveVwap": bool,
        "lastCloseAboveEma9": bool,
        "clv": lambda v: v >= 0.70,
        "rvolPaced": lambda v: v >= 1.20,
        "residualStrengthPctile": lambda v: v >= 60,
    }
    failed: list[str] = []
    for key, test in required.items():
        value = row.get(key)
        if value is None:
            failed.append(f"MISSING_{key}")
            continue
        try:
            if not test(value):
                failed.append(key)
        except Exception:
            failed.append(key)
    return not failed, failed


def evaluate_setups(row: dict[str, Any]) -> dict[str, Any]:
    passed: list[str] = []
    reasons: dict[str, list[str]] = {}
    ok, why = breakout_close_v1(row)
    if ok:
        passed.append("BREAKOUT_CLOSE_V1")
    else:
        reasons["BREAKOUT_CLOSE_V1"] = why
    ok, why = pullback_reclaim_v1(row)
    if ok:
        passed.append("PULLBACK_RECLAIM_V1")
    else:
        reasons["PULLBACK_RECLAIM_V1"] = why
    return {"passedSetupIds": passed, "rejections": reasons, "eligible": bool(passed)}
