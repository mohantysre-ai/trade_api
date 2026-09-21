from __future__ import annotations

from typing import Any

from .config import load_config

LIMITS = {
    "NIFTY100": (500_000_000.0, 1.00, 0.0025),
    "NIFTY_100": (500_000_000.0, 1.00, 0.0025),
    "NIFTY_MIDCAP150": (250_000_000.0, 1.00, 0.0025),
    "NIFTY_MIDCAP_150": (250_000_000.0, 1.00, 0.0025),
    "NIFTY_SMALLCAP250": (100_000_000.0, 1.50, 0.0015),
    "NIFTY_SMALLCAP_250": (100_000_000.0, 1.50, 0.0015),
    "NIFTY500_FALLBACK": (100_000_000.0, 1.50, 0.0015),
    "NIFTY_MICROCAP250": (10_000_000.0, 2.00, 0.0010),
    "NIFTY_MICROCAP_250": (10_000_000.0, 2.00, 0.0010),
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
    if observations < load_config().min_daily_observations:
        reasons.append("INSUFFICIENT_DAILY_HISTORY")
    if mdtv < minimum_mdtv:
        reasons.append("MDTV20_BELOW_SEGMENT_MINIMUM")
    if cost is None:
        cost = 0.35 if "MICRO" in segment else (0.25 if "SMALL" in segment or segment == "NIFTY500_FALLBACK" else 0.20)
    if float(cost) > max_cost:
        reasons.append("MISSING_OR_EXCESS_EXECUTION_COST")
    if spread is None or depth is None or float(depth) <= 0:
        fallback_spread = 1.2 if "MICRO" in segment else (0.8 if "SMALL" in segment or segment == "NIFTY500_FALLBACK" else 0.5)
        if spread is None:
            spread = fallback_spread
        if depth is None or float(depth) <= 0:
            depth = 1
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
    for flag, reason in (
        ("corporateEventsCurrent", "CORPORATE_EVENTS_FEED_STALE"),
        ("surveillanceCurrent", "SURVEILLANCE_FEED_STALE"),
        ("universeCurrent", "UNIVERSE_FEED_STALE"),
    ):
        if row.get(flag) is not True:
            reasons.append(reason)
    return not reasons, reasons


def participation_limit(segment: str) -> float:
    return LIMITS.get(segment.upper(), (0.0, 0.0, 0.0))[2]