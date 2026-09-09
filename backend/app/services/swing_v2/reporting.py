from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from .ledger import SwingLedger, materialize_position


def candidate_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stages = ("freshData", "tradable", "safetyPass", "setupPass", "expectancyPass", "portfolioPass", "locked", "filled")
    return {"universe": len(rows), **{stage: sum(bool(row.get(stage)) for row in rows) for stage in stages}, "topRejectionReasons": Counter(reason for row in rows for reason in row.get("reasonCodes", [])).most_common(10)}


def reconcile_positions(positions: list[dict[str, Any]]) -> dict[str, Any]:
    realized = sum(float(row.get("realizedPnl") or 0) for row in positions)
    unrealized = sum(float(row.get("unrealizedPnl") or 0) for row in positions)
    return {"realizedPnl": round(realized, 2), "unrealizedPnl": round(unrealized, 2), "totalPnl": round(realized + unrealized, 2), "reconciled": abs((realized + unrealized) - sum(float(row.get("totalPnl") or 0) for row in positions)) <= .01}


def ledger_eod_report(ledger: SwingLedger, session_date: str) -> dict[str, Any]:
    all_events = ledger.events()
    ist = ZoneInfo("Asia/Kolkata")
    report_day = datetime.fromisoformat(session_date).date()
    cutoff = datetime.combine(report_day, time.max, tzinfo=ist)
    def event_day(event: dict[str, Any]) -> str | None:
        try:
            return datetime.fromisoformat(str(event.get("eventTimestamp") or "").replace("Z", "+00:00")).astimezone(ist).date().isoformat()
        except (TypeError, ValueError):
            return None

    events = [event for event in all_events if event_day(event) == session_date]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in all_events:
        if not event.get("positionId"):
            continue
        try:
            stamp = datetime.fromisoformat(str(event.get("eventTimestamp") or "").replace("Z", "+00:00")).astimezone(ist)
        except (TypeError, ValueError):
            continue
        if stamp <= cutoff:
            grouped[str(event["positionId"])].append(event)
    positions = []
    for group in grouped.values():
        state = materialize_position(group)
        last_day = event_day(group[-1])
        # New positions, carried-open positions, and positions closed today are
        # in this EOD. Positions terminal before today are not.
        if str(state.get("sessionDate") or "") == session_date or not state.get("terminal") or last_day == session_date:
            positions.append(state)
    event_counts = Counter(str(event.get("eventType") or "UNKNOWN") for event in events)
    return {"strategyId": "SWING_2S_MOMENTUM_V2", "policyVersion": "2.0.0", "validationState": "RESEARCH_HYPOTHESIS", "date": session_date, "sessionDate": session_date, "eventCount": len(events), "eventCounts": dict(event_counts), "positions": positions, **reconcile_positions(positions)}
