from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .ledger import SwingLedger, materialize_position


def candidate_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stages = ("freshData", "tradable", "safetyPass", "setupPass", "expectancyPass", "portfolioPass", "locked", "filled")
    return {"universe": len(rows), **{stage: sum(bool(row.get(stage)) for row in rows) for stage in stages}, "topRejectionReasons": Counter(reason for row in rows for reason in row.get("reasonCodes", [])).most_common(10)}


def reconcile_positions(positions: list[dict[str, Any]]) -> dict[str, Any]:
    realized = sum(float(row.get("realizedPnl") or 0) for row in positions)
    unrealized = sum(float(row.get("unrealizedPnl") or 0) for row in positions)
    return {"realizedPnl": round(realized, 2), "unrealizedPnl": round(unrealized, 2), "totalPnl": round(realized + unrealized, 2), "reconciled": abs((realized + unrealized) - sum(float(row.get("totalPnl") or 0) for row in positions)) <= .01}


def ledger_eod_report(ledger: SwingLedger, session_date: str) -> dict[str, Any]:
    events = ledger.events(session_date=session_date)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event.get("positionId") or event["decisionId"]].append(event)
    positions = [materialize_position(group) for group in grouped.values()]
    return {"strategyId": "SWING_2S_MOMENTUM_V2", "policyVersion": "2.0.0", "validationState": "RESEARCH_HYPOTHESIS", "sessionDate": session_date, "eventCount": len(events), "positions": positions, **reconcile_positions(positions)}
