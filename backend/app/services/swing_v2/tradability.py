from __future__ import annotations

from typing import Any

LIMITS = {
    "NIFTY100": (2_500_000_000.0, 0.30, 0.0025),
    "NIFTY_100": (2_500_000_000.0, 0.30, 0.0025),
    "NIFTY_MIDCAP150": (2_500_000_000.0, 0.30, 0.0025),
    "NIFTY_MIDCAP_150": (2_500_000_000.0, 0.30, 0.0025),
    "NIFTY_SMALLCAP250": (1_500_000_000.0, 0.50, 0.0015),
    "NIFTY_SMALLCAP_250": (1_500_000_000.0, 0.50, 0.0015),
    "NIFTY_MICROCAP250": (1_000_000_000.0, 0.70, 0.0010),
    "NIFTY_MICROCAP_250": (1_000_000_000.0, 0.70, 0.0010),
}


def evaluate_tradability(row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    segment = str(row.get("universeSegment") or "").upper()
    minimum_mdtv, max_cost, _ = LIMITS.get(segment, (float("inf"), 0.0, 0.0))
    price = float(row.get("decisionPrice") or row.get("ltp") or 0)
    mdtv = float(row.get("mdtv20") or 0)
    cost = row.get("modeledRoundTripCostPct")
    spread = row.get("spreadPct")
    depth = row.get("availableAskDepth")
    observations = int(row.get("dailyObservationCount") or 0)
    if price < 50:
        reasons.append("PRICE_BELOW_50")
    if observations < 252:
        reasons.append("INSUFFICIENT_DAILY_HISTORY")
    if mdtv < minimum_mdtv:
        reasons.append("MDTV20_BELOW_SEGMENT_MINIMUM")
    if cost is None or float(cost) > max_cost:
        reasons.append("MISSING_OR_EXCESS_EXECUTION_COST")
    if spread is None or depth is None or float(depth) <= 0:
        reasons.append("MISSING_SPREAD_OR_DEPTH")
    for flag, reason in (
        ("surveillanceRestricted", "SURVEILLANCE_RESTRICTED"),
        ("suspended", "SUSPENDED"),
        ("nonRollingSettlement", "NON_ROLLING_SETTLEMENT"),
        ("scheduledResultBeforeD2", "RESULT_EVENT_BEFORE_D2"),
        ("corporateActionUnadjustable", "CORPORATE_ACTION_UNADJUSTABLE"),
        ("nearPriceBand", "WITHIN_1PCT_PRICE_BAND"),
        ("stressedExitCapacityFailed", "STRESSED_EXIT_CAPACITY_FAILED"),
    ):
        if row.get(flag):
            reasons.append(reason)
    return not reasons, reasons


def participation_limit(segment: str) -> float:
    return LIMITS.get(segment.upper(), (0.0, 0.0, 0.0))[2]
