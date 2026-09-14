from __future__ import annotations

from datetime import datetime
from typing import Any


def simulate_paper_fill(order: dict[str, Any], observations: list[dict[str, Any]], *, expiry: datetime) -> dict[str, Any]:
    decision = datetime.fromisoformat(str(order["decisionTimestamp"]).replace("Z", "+00:00"))
    limit = float(order["limitPrice"])
    requested = int(order["qty"])
    remaining, filled, notional = requested, 0, 0.0
    fills = []
    for observation in sorted(observations, key=lambda item: str(item.get("timestamp") or "")):
        stamp = datetime.fromisoformat(str(observation["timestamp"]).replace("Z", "+00:00"))
        if stamp <= decision or stamp > expiry:
            continue
        ask = float(observation.get("ask") or observation.get("open") or 0)
        available = int(observation.get("askDepth") or observation.get("volume") or 0)
        if ask <= 0 or ask > limit or available <= 0:
            continue
        qty = min(remaining, available)
        fills.append({"timestamp": stamp.isoformat(), "price": ask, "qty": qty, "source": observation.get("source") or "RECORDED_OBSERVATION"})
        filled += qty
        remaining -= qty
        notional += qty * ask
        if remaining == 0:
            break
    if filled == 0:
        return {"executionStatus": "EXPIRED_UNFILLED", "filledQty": 0, "remainingQty": requested, "realizedPnl": 0.0, "fills": []}
    return {"executionStatus": "FILLED" if remaining == 0 else "PARTIAL_FILL", "filledQty": filled, "remainingQty": remaining, "fillPrice": round(notional / filled, 4), "fills": fills}


def transaction_cost(notional: float, *, modeled_round_trip_pct: float, fraction_of_round_trip: float = 0.5) -> float:
    return round(max(0.0, notional) * max(0.0, modeled_round_trip_pct) / 100 * fraction_of_round_trip, 2)
