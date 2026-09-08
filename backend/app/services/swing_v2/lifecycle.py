from __future__ import annotations

from datetime import datetime
from typing import Any

from .calendar import time_exit_due


def _fill_pnl(position: dict[str, Any], qty: int, price: float) -> float:
    entry = float(position.get("entryPrice") or 0)
    cost_per_share = float(position.get("roundTripCostPerShare") or 0)
    return qty * (price - entry - cost_per_share)


def update_stop(position: dict[str, Any], proposed: float) -> dict[str, Any]:
    out = dict(position)
    current = float(out.get("effectiveStop") or out.get("initialStop") or 0)
    if proposed > current:
        out["effectiveStop"] = proposed
    return out


def thesis_break(two_15m_bars: list[dict[str, Any]], *, vwap: float, locked_level: float, residual_percentile: float) -> bool:
    if len(two_15m_bars) < 2 or residual_percentile >= 30:
        return False
    return all(float(bar.get("close") or float("inf")) < vwap and float(bar.get("close") or float("inf")) < locked_level for bar in two_15m_bars[-2:])


def evaluate_position(position: dict[str, Any], bar: dict[str, Any], *, is_d2_exit: bool = False, thesis_broken: bool = False) -> dict[str, Any]:
    """Apply exactly one chronological bar; ambiguous stop/target paths are adverse-first."""
    out = dict(position)
    if out.get("closed") or out.get("terminal"):
        return out
    if position.get("entryTimestamp") and bar.get("timestamp"):
        entry_ts = datetime.fromisoformat(str(position["entryTimestamp"]).replace("Z", "+00:00"))
        bar_ts = datetime.fromisoformat(str(bar["timestamp"]).replace("Z", "+00:00"))
        if bar_ts <= entry_ts:
            return out

    open_price = float(bar.get("open") or bar.get("close") or 0)
    low, high, close = float(bar.get("low") or 0), float(bar.get("high") or 0), float(bar.get("close") or 0)
    stop = float(out.get("effectiveStop") or out.get("initialStop") or 0)
    t1, t2 = float(out.get("t1") or 0), float(out.get("t2") or 0)
    entry = float(out.get("entryPrice") or 0)
    risk = float(out.get("riskPerShare") or (entry - float(out.get("initialStop") or 0)))
    remaining = int(out.get("remainingQty") if out.get("remainingQty") is not None else out.get("qty") or 0)
    t1_filled = bool(out.get("t1Filled"))
    realized = float(out.get("realizedPnl") or 0)
    mfe_r = max(float(out.get("mfeR") or 0), (high - entry) / risk if risk > 0 else 0)
    mae_r = min(float(out.get("maeR") or 0), (low - entry) / risk if risk > 0 else 0)
    out.update({"mfeR": mfe_r, "maeR": mae_r})

    next_target = t2 if t1_filled else t1
    if stop > 0 and low <= stop:
        ambiguous = next_target > 0 and high >= next_target
        exit_price = open_price if 0 < open_price < stop else stop
        realized += _fill_pnl(out, remaining, exit_price)
        out.update({"closed": True, "terminal": True, "status": "CLOSED_STOP", "remainingQty": 0, "exitReason": "STOP_LOSS_FILLED" if not t1_filled else "TRAIL_STOP_FILLED", "exitPrice": exit_price, "realizedPnl": round(realized, 2), "unrealizedPnl": 0.0, "totalPnl": round(realized, 2), "pathQuality": "AMBIGUOUS" if ambiguous else "ORDERED"})
        return out

    if not t1_filled and t1 > 0 and high >= t1:
        tranche = min(max(1, int(out.get("t1Qty") or remaining // 2)), remaining)
        realized += _fill_pnl(out, tranche, t1)
        remaining -= tranche
        cost_buffer = float(out.get("roundTripCostPerShare") or 0)
        out.update({"t1Filled": True, "t1FillPrice": t1, "t1FilledQty": tranche, "remainingQty": remaining, "effectiveStop": max(stop, entry + cost_buffer), "status": "PARTIAL_T1", "realizedPnl": round(realized, 2)})
        t1_filled = True

    # The runner trail is impossible before confirmed T1.
    if t1_filled and remaining > 0 and mfe_r >= float(out.get("trailArmR") or 1.5):
        out = update_stop(out, entry + float(out.get("trailLockR") or .75) * risk)
        out["trailArmed"] = True

    if t1_filled and remaining > 0 and t2 > 0 and high >= t2:
        realized += _fill_pnl(out, remaining, t2)
        out.update({"closed": True, "terminal": True, "status": "CLOSED_T2", "remainingQty": 0, "exitReason": "T2_FILLED", "exitPrice": t2, "realizedPnl": round(realized, 2), "unrealizedPnl": 0.0, "totalPnl": round(realized, 2), "pathQuality": out.get("pathQuality") or "ORDERED"})
        return out

    if thesis_broken and remaining > 0 and close > 0:
        realized += _fill_pnl(out, remaining, close)
        out.update({"closed": True, "terminal": True, "status": "CLOSED_THESIS_BREAK", "remainingQty": 0, "exitReason": "THESIS_BREAK_EXIT", "exitPrice": close, "realizedPnl": round(realized, 2), "unrealizedPnl": 0.0, "totalPnl": round(realized, 2)})
        return out

    if is_d2_exit and remaining > 0:
        if close <= 0:
            out.update({"status": "EXIT_EXECUTION_FAILED", "exitReason": "EXIT_EXECUTION_FAILED"})
            return out
        realized += _fill_pnl(out, remaining, close)
        out.update({"closed": True, "terminal": True, "status": "CLOSED_TIME", "remainingQty": 0, "exitReason": "TIME_EXIT_FILLED", "exitPrice": close, "realizedPnl": round(realized, 2), "unrealizedPnl": 0.0, "totalPnl": round(realized, 2)})
    elif close > 0:
        unrealized = _fill_pnl(out, remaining, close)
        out.update({"unrealizedPnl": round(unrealized, 2), "totalPnl": round(realized + unrealized, 2)})
    return out


__all__ = ["evaluate_position", "thesis_break", "time_exit_due", "update_stop"]
