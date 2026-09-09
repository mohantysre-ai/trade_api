from __future__ import annotations

from datetime import datetime
from typing import Any

from .execution import simulate_paper_fill, transaction_cost
from .ledger import SwingLedger, materialize_position
from .lifecycle import evaluate_position
from .schemas import EventType


def execute_paper_order(
    ledger: SwingLedger,
    candidate: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    expiry: datetime,
) -> dict[str, Any]:
    decision_id = str(candidate["decisionId"])
    symbol = str(candidate["symbol"]).upper()
    session_date = str(candidate["sessionDate"])
    result = simulate_paper_fill(
        {
            "decisionTimestamp": candidate["decisionTimestamp"],
            "limitPrice": candidate["limitPrice"],
            "qty": candidate["qty"],
        },
        observations,
        expiry=expiry,
    )
    if result["executionStatus"] == "EXPIRED_UNFILLED":
        return ledger.append(
            idempotency_key=f"{decision_id}:ORDER_EXPIRED",
            decision_id=decision_id,
            position_id=decision_id,
            symbol=symbol,
            session_date=session_date,
            event_type=EventType.ORDER_EXPIRED,
            event_timestamp=expiry.isoformat(),
            payload={**result, "totalPnl": 0.0},
        )
    fill_price = float(result["fillPrice"])
    initial_stop = float(candidate["initialStop"])
    risk = fill_price - initial_stop
    filled_qty = int(result["filledQty"])
    cost = transaction_cost(
        fill_price * filled_qty,
        modeled_round_trip_pct=float(candidate.get("modeledRoundTripCostPct") or 0),
        fraction_of_round_trip=.5,
    )
    payload = {
        **candidate,
        **result,
        "entryPrice": fill_price,
        "entryTimestamp": result["fills"][0]["timestamp"],
        "initialStop": initial_stop,
        "effectiveStop": initial_stop,
        "riskPerShare": risk,
        "t1": fill_price + risk,
        "t2": fill_price + 2 * risk,
        "t1Qty": max(1, filled_qty // 2),
        "remainingQty": filled_qty,
        "entryCost": cost,
        "roundTripCostPerShare": cost / filled_qty if filled_qty else 0.0,
        "realizedPnl": -cost,
        "unrealizedPnl": 0.0,
        "totalPnl": -cost,
        "status": "OPEN",
    }
    event_type = EventType.FILL_COMPLETE if result["executionStatus"] == "FILLED" else EventType.FILL_PARTIAL
    return ledger.append(
        idempotency_key=f"{decision_id}:{event_type}",
        decision_id=decision_id,
        position_id=decision_id,
        symbol=symbol,
        session_date=session_date,
        event_type=event_type,
        event_timestamp=result["fills"][-1]["timestamp"],
        payload=payload,
    )


def process_position_bar(
    ledger: SwingLedger,
    position_id: str,
    bar: dict[str, Any],
    *,
    is_d2_exit: bool = False,
    thesis_broken: bool = False,
) -> dict[str, Any]:
    events = ledger.events(position_id=position_id)
    if not events:
        raise ValueError(f"unknown position {position_id}")
    before = materialize_position(events)
    after = evaluate_position(before, bar, is_d2_exit=is_d2_exit, thesis_broken=thesis_broken)
    timestamp = str(bar.get("timestamp") or datetime.now().astimezone().isoformat())
    event_types: list[EventType] = []
    if after.get("t1Filled") and not before.get("t1Filled"):
        event_types.append(EventType.T1_FILLED)
    if after.get("trailArmed") and not before.get("trailArmed"):
        event_types.append(EventType.STOP_UPDATED)
    reason_event = {
        "T2_FILLED": EventType.T2_FILLED,
        "STOP_LOSS_FILLED": EventType.STOP_FILLED,
        "TRAIL_STOP_FILLED": EventType.STOP_FILLED,
        "THESIS_BREAK_EXIT": EventType.THESIS_BREAK_FILLED,
        "TIME_EXIT_FILLED": EventType.TIME_EXIT_FILLED,
        "EXIT_EXECUTION_FAILED": EventType.EXIT_EXECUTION_FAILED,
    }.get(str(after.get("exitReason") or ""))
    if reason_event:
        event_types.append(reason_event)
    if not event_types:
        # A durable minute mark preserves MTM/MFE and advances the recovery
        # cursor without making any additional market-data request.
        event_types.append(EventType.MARK_OBSERVED)
    last_event = None
    for index, event_type in enumerate(event_types):
        last_event = ledger.append(
            idempotency_key=f"{position_id}:{timestamp}:{event_type}",
            decision_id=str(before["decisionId"]),
            position_id=position_id,
            symbol=str(before["symbol"]),
            session_date=str(before["sessionDate"]),
            event_type=event_type,
            event_timestamp=timestamp,
            payload=after,
        )
        # T1+T2 can share a bar. The T1 event is non-terminal; T2 then closes.
        if index == 0 and len(event_types) > 1 and event_type == EventType.T1_FILLED:
            continue
    return materialize_position(ledger.events(position_id=position_id)) if last_event else after
