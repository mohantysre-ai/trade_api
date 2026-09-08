from __future__ import annotations

from datetime import datetime
from typing import Any


def evaluate_position(position: dict[str, Any], bar: dict[str, Any], *, is_d2_exit: bool = False) -> dict[str, Any]:
    """Chronological one-bar transition. Adverse-first if stop and target coexist."""
    out = dict(position)
    if out.get("closed"):
        return out
    low = float(bar.get("low") or 0)
    high = float(bar.get("high") or 0)
    close = float(bar.get("close") or 0)
    stop = float(out.get("effectiveStop") or out.get("initialStop") or 0)
    t1 = float(out.get("t1") or 0)
    t2 = float(out.get("t2") or 0)
    remaining = int(out.get("remainingQty") if out.get("remainingQty") is not None else out.get("qty") or 0)
    t1_filled = bool(out.get("t1Filled"))

    if stop > 0 and low <= stop:
        out.update({"closed": True, "remainingQty": 0, "exitReason": "STOP_LOSS_FILLED", "exitPrice": stop, "pathQuality": "AMBIGUOUS" if high >= (t2 if t1_filled else t1) > 0 else "ORDERED"})
        return out

    if not t1_filled and t1 > 0 and high >= t1:
        tranche = max(1, int(out.get("t1Qty") or max(1, remaining // 2)))
        tranche = min(tranche, remaining)
        remaining -= tranche
        out.update({"t1Filled": True, "t1FillPrice": t1, "remainingQty": remaining, "effectiveStop": float(out.get("entryPrice") or 0), "status": "PARTIAL_T1"})
        t1_filled = True

    if t1_filled and remaining > 0 and t2 > 0 and high >= t2:
        out.update({"closed": True, "remainingQty": 0, "exitReason": "T2_FILLED", "exitPrice": t2})
        return out

    if is_d2_exit and remaining > 0 and close > 0:
        out.update({"closed": True, "remainingQty": 0, "exitReason": "TIME_EXIT_FILLED", "exitPrice": close})
    return out


def time_exit_due(now_ist: datetime, holding_session_age: int) -> bool:
    return holding_session_age >= 2 and (now_ist.hour, now_ist.minute) >= (15, 15)
