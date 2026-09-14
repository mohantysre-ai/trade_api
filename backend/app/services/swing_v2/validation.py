from __future__ import annotations

from datetime import date
from typing import Any


def research_to_shadow_gates(metrics: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "OOS_FILLS_300": int(metrics.get("oosFills") or 0) >= 300,
        "ARCHETYPE_FILLS_100": all(int(value) >= 100 for value in (metrics.get("fillsByChampionSetup") or {}).values()) and bool(metrics.get("fillsByChampionSetup")),
        "MEAN_NET_R_012": float(metrics.get("meanNetR") or 0) >= .12,
        "PROFIT_FACTOR_125": float(metrics.get("profitFactor") or 0) >= 1.25,
        "BOOTSTRAP_FLOOR_POSITIVE": float(metrics.get("bootstrapLowerBoundR") or 0) > 0,
        "ROLLING_WINDOWS_70PCT": float(metrics.get("positiveRollingWindowsPct") or 0) >= 70,
        "FINAL_HOLDOUT_PROFITABLE": float(metrics.get("finalHoldoutNetReturn") or 0) > 0,
        "TWICE_COST_PF_105": float(metrics.get("twiceCostProfitFactor") or 0) >= 1.05,
        "CONCENTRATION_MAX_50PCT": float(metrics.get("maxProfitContributionPct") or 100) <= 50,
        "MAX_DRAWDOWN_8PCT": abs(float(metrics.get("maxDrawdownPct") or 100)) <= 8,
        "NO_DATA_LEAKAGE": metrics.get("unresolvedLeakage") is False,
    }
    return {"passed": all(checks.values()), "checks": checks, "failed": [key for key, passed in checks.items() if not passed]}


def shadow_to_paper_gates(metrics: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "SESSIONS_60": int(metrics.get("paperSessions") or 0) >= 60,
        "EXECUTABLE_FILLS_40": int(metrics.get("paperFills") or 0) >= 40,
        "NO_FALSE_FILLS": int(metrics.get("falseFills") or 0) == 0,
        "POSITIVE_EXPECTANCY": float(metrics.get("observedNetR") or 0) > 0,
        "SLIPPAGE_WITHIN_MODEL": float(metrics.get("p75SlippageMultiple") or 999) <= 1.5,
        "NO_DUPLICATES": int(metrics.get("duplicateEvents") or 0) == 0,
        "NO_STALE_LOCKS": int(metrics.get("staleLocks") or 0) == 0,
        "EOD_LEDGER_TIE": float(metrics.get("eodLedgerMismatchRupees") or 999) <= 1,
        "PERFORMANCE_IN_BAND": metrics.get("insideBacktestConfidenceBand") is True,
    }
    return {"passed": all(checks.values()), "checks": checks, "failed": [key for key, passed in checks.items() if not passed]}


def walk_forward_windows(start: date, final_holdout_start: date, *, training_months: int = 36, validation_months: int = 6) -> list[dict[str, date]]:
    def add_months(day: date, months: int) -> date:
        index = day.year * 12 + day.month - 1 + months
        year, month = divmod(index, 12)
        return date(year, month + 1, min(day.day, 28))
    windows, train_start = [], start
    while True:
        train_end = add_months(train_start, training_months)
        validation_end = add_months(train_end, validation_months)
        if validation_end > final_holdout_start:
            break
        windows.append({"trainStart": train_start, "trainEndExclusive": train_end, "validationStart": train_end, "validationEndExclusive": validation_end})
        train_start = add_months(train_start, validation_months)
    return windows
