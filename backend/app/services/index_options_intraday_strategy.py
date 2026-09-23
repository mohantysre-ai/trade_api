"""Intraday index-option strategy: fixed 20-point SL, 40-point target, partial
booking + SL tranche after target, pyramiding on favorable move, parallel leg
evaluation.

This module is advisory and never places broker orders.  It owns the per-leg
state machine for long-premium index-option paper trades and is designed to be
plugged into the existing ``index_options_paper`` reconcile loop or used
standalone.
"""
from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any

from .angel_index_options import IST_ZONE, _float

# ---------------------------------------------------------------------------
# Tunables (env-overridable)
# ---------------------------------------------------------------------------
INTRADAY_SL_POINTS: float = float(os.environ.get("INTRADAY_SL_POINTS", "20"))
INTRADAY_TARGET_POINTS: float = float(os.environ.get("INTRADAY_TARGET_POINTS", "40"))
INTRADAY_PARTIAL_BOOK_PCT: float = float(os.environ.get("INTRADAY_PARTIAL_BOOK_PCT", "0.5"))
INTRADAY_PYRAMID_ADD_LOTS: int = int(os.environ.get("INTRADAY_PYRAMID_ADD_LOTS", "1"))
INTRADAY_MAX_PYRAMID_LOTS: int = int(os.environ.get("INTRADAY_MAX_PYRAMID_LOTS", "3"))
INTRADAY_PYRAMID_TRIGGER_POINTS: float = float(os.environ.get("INTRADAY_PYRAMID_TRIGGER_POINTS", "20"))
INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS: float = float(os.environ.get("INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS", "20"))
INTRADAY_SQUARE_OFF_TIME: dt_time = dt_time(
    int(os.environ.get("INTRADAY_SQUARE_OFF_HOUR", "15")),
    int(os.environ.get("INTRADAY_SQUARE_OFF_MINUTE", "29")),
)
INTRADAY_MARK_INTERVAL_SECONDS: float = float(os.environ.get("INTRADAY_MARK_INTERVAL_SECONDS", "60"))

_LOCK = threading.Lock()


def _positive_env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# ---------------------------------------------------------------------------
# Per-leg state
# ---------------------------------------------------------------------------
@dataclass
class LegState:
    """Mutable state for a single option leg."""

    symbol: str
    direction: str  # LONG or SHORT
    entry_price: float
    initial_qty: int
    current_qty: int
    average_entry_price: float = 0.0
    pyramided_qty: int = 0
    partial_booked_qty: int = 0
    stop_price: float = 0.0
    target_price: float = 0.0
    peak_price: float = 0.0
    mfe_points: float = 0.0
    target_hit: bool = False
    trail_active: bool = False
    closed: bool = False
    exit_reason: str = ""
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    minute_marks: list[dict[str, Any]] = field(default_factory=list)

    def profit_points(self, mark: float) -> float:
        sign = 1.0 if self.direction == "LONG" else -1.0
        return sign * (mark - self.entry_price)

    def update_peak(self, mark: float) -> None:
        if self.direction == "LONG" and mark > self.peak_price:
            self.peak_price = mark
        elif self.direction == "SHORT" and (self.peak_price == 0 or mark < self.peak_price):
            self.peak_price = mark
        self.mfe_points = self.profit_points(self.peak_price)


# ---------------------------------------------------------------------------
# Position-level container
# ---------------------------------------------------------------------------
@dataclass
class IntradayPosition:
    """One index-option position (single leg or multi-leg spread)."""

    position_id: str
    index: str
    direction: str
    legs: list[LegState]
    entry_time: str
    status: str = "OPEN"
    exit_reason: str = ""
    total_realized_pnl: float = 0.0
    remaining_qty: int = 0
    pyramided_lots: int = 0
    policy_version: str = "intraday_20sl_40target_pyramid_v1"

    def total_initial_qty(self) -> int:
        return sum(leg.initial_qty for leg in self.legs)

    def total_current_qty(self) -> int:
        return sum(leg.current_qty for leg in self.legs)

    def total_realized(self) -> float:
        return sum(leg.realized_pnl for leg in self.legs)

    def any_leg_closed(self) -> bool:
        return any(leg.closed for leg in self.legs)

    def all_legs_closed(self) -> bool:
        return all(leg.closed for leg in self.legs)


# ---------------------------------------------------------------------------
# Position factory
# ---------------------------------------------------------------------------
def create_position(
    index: str,
    direction: str,
    entry_price: float,
    qty: int,
    symbol: str,
    now: datetime,
    sequence: int,
) -> IntradayPosition:
    stamp = now.astimezone(IST_ZONE).date().isoformat()
    position_id = f"{stamp}-{sequence:03d}-{index}-{direction}"
    leg = LegState(
        symbol=symbol,
        direction=direction,
        entry_price=round(entry_price, 2),
        initial_qty=qty,
        current_qty=qty,
        average_entry_price=round(entry_price, 2),
        stop_price=round(entry_price - INTRADAY_SL_POINTS, 2) if direction == "LONG" else round(entry_price + INTRADAY_SL_POINTS, 2),
        target_price=round(entry_price + INTRADAY_TARGET_POINTS, 2) if direction == "LONG" else round(entry_price - INTRADAY_TARGET_POINTS, 2),
        peak_price=entry_price,
    )
    return IntradayPosition(
        position_id=position_id,
        index=index,
        direction=direction,
        legs=[leg],
        entry_time=now.isoformat(),
        remaining_qty=qty,
    )


# ---------------------------------------------------------------------------
# Core leg evaluator
# ---------------------------------------------------------------------------
def _eod_square_off(leg: LegState, mark: float, now: datetime) -> LegState | None:
    if leg.closed or leg.current_qty <= 0:
        return leg
    sign = 1.0 if leg.direction == "LONG" else -1.0
    pnl = round(sign * (mark - (leg.average_entry_price or leg.entry_price)) * leg.current_qty, 2)
    leg.realized_pnl = round(leg.realized_pnl + pnl, 2)
    leg.current_qty = 0
    leg.closed = True
    leg.exit_reason = "EOD_SQUAREOFF"
    leg.exit_price = round(mark, 2)
    leg.minute_marks.append({
        "at": now.isoformat(),
        "premium": round(mark, 2),
        "qty": 0,
        "pnl": pnl,
        "reason": "EOD_SQUAREOFF",
    })
    return leg


def _initial_stop_hit(leg: LegState, mark: float, now: datetime) -> LegState | None:
    if leg.closed or leg.current_qty <= 0:
        return leg
    sign = 1.0 if leg.direction == "LONG" else -1.0
    sl_hit = (mark <= leg.stop_price) if leg.direction == "LONG" else (mark >= leg.stop_price)
    if not sl_hit:
        return leg
    pnl = round(sign * (mark - (leg.average_entry_price or leg.entry_price)) * leg.current_qty, 2)
    leg.realized_pnl = round(leg.realized_pnl + pnl, 2)
    leg.current_qty = 0
    leg.closed = True
    leg.exit_reason = "INITIAL_STOP"
    leg.exit_price = round(mark, 2)
    leg.minute_marks.append({
        "at": now.isoformat(),
        "premium": round(mark, 2),
        "qty": 0,
        "pnl": pnl,
        "reason": "INITIAL_STOP",
    })
    return leg


def _target_hit(leg: LegState, mark: float, now: datetime) -> LegState | None:
    if leg.closed or leg.target_hit or leg.current_qty <= 0:
        return leg
    target_hit = (mark >= leg.target_price) if leg.direction == "LONG" else (mark <= leg.target_price)
    if not target_hit:
        return leg
    leg.target_hit = True
    book_qty = max(1, int(math.floor(leg.current_qty * INTRADAY_PARTIAL_BOOK_PCT)))
    remain_qty = leg.current_qty - book_qty
    sign = 1.0 if leg.direction == "LONG" else -1.0
    book_pnl = round(sign * (mark - (leg.average_entry_price or leg.entry_price)) * book_qty, 2)
    leg.realized_pnl = round(leg.realized_pnl + book_pnl, 2)
    leg.partial_booked_qty = book_qty
    leg.current_qty = remain_qty
    basis = leg.average_entry_price or leg.entry_price
    trail = mark - INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS if leg.direction == "LONG" else mark + INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS
    leg.stop_price = round(max(basis, trail) if leg.direction == "LONG" else min(basis, trail), 2)
    leg.trail_active = remain_qty > 0
    if remain_qty == 0:
        leg.closed = True
        leg.exit_reason = "TARGET"
        leg.exit_price = round(mark, 2)
    leg.minute_marks.append({
        "at": now.isoformat(),
        "premium": round(mark, 2),
        "qty": remain_qty,
        "booked_qty": book_qty,
        "pnl": book_pnl,
        "reason": "PARTIAL_BOOK_AT_TARGET",
    })
    return leg


def _trail_stop_hit(leg: LegState, mark: float, now: datetime) -> LegState | None:
    if leg.closed or not leg.trail_active or leg.current_qty <= 0:
        return leg
    trail_hit = (mark <= leg.stop_price) if leg.direction == "LONG" else (mark >= leg.stop_price)
    if not trail_hit:
        return leg
    sign = 1.0 if leg.direction == "LONG" else -1.0
    pnl = round(sign * (mark - (leg.average_entry_price or leg.entry_price)) * leg.current_qty, 2)
    leg.realized_pnl = round(leg.realized_pnl + pnl, 2)
    leg.current_qty = 0
    leg.closed = True
    leg.exit_reason = "TRAIL_SL"
    leg.exit_price = round(mark, 2)
    leg.minute_marks.append({
        "at": now.isoformat(),
        "premium": round(mark, 2),
        "qty": 0,
        "pnl": pnl,
        "reason": "TRAIL_SL",
    })
    return leg


def _pyramid_trigger(leg: LegState, mark: float, now: datetime, position: IntradayPosition) -> LegState | None:
    if leg.closed or not leg.target_hit or leg.current_qty <= 0:
        return leg
    if position.pyramided_lots >= INTRADAY_MAX_PYRAMID_LOTS - 1:
        return leg
    profit = leg.profit_points(mark)
    if profit < INTRADAY_TARGET_POINTS + (position.pyramided_lots + 1) * INTRADAY_PYRAMID_TRIGGER_POINTS:
        return leg
    add_lots = min(INTRADAY_PYRAMID_ADD_LOTS, INTRADAY_MAX_PYRAMID_LOTS - 1 - position.pyramided_lots)
    add_qty = add_lots * leg.initial_qty
    if add_qty <= 0:
        return leg
    old_basis = leg.average_entry_price or leg.entry_price
    leg.average_entry_price = round((old_basis * leg.current_qty + mark * add_qty) / (leg.current_qty + add_qty), 4)
    leg.pyramided_qty += add_qty
    leg.current_qty += add_qty
    position.pyramided_lots += add_lots
    if leg.direction == "LONG":
        leg.stop_price = round(max(leg.stop_price, leg.average_entry_price), 2)
    else:
        leg.stop_price = round(min(leg.stop_price, leg.average_entry_price), 2)
    leg.minute_marks.append({
        "at": now.isoformat(),
        "premium": round(mark, 2),
        "qty": leg.current_qty,
        "pyramid_add": add_qty,
        "reason": "PYRAMID_ADD",
    })
    return leg


def evaluate_leg(leg: LegState, mark: float, now: datetime, position: IntradayPosition) -> LegState:
    if leg.closed:
        return leg
    if leg.target_hit and leg.trail_active:
        leg.update_peak(mark)
        basis = leg.average_entry_price or leg.entry_price
        trail = leg.peak_price - INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS if leg.direction == "LONG" else leg.peak_price + INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS
        leg.stop_price = round(max(leg.stop_price, basis, trail) if leg.direction == "LONG" else min(leg.stop_price, basis, trail), 2)
    # After partial book, trail SL takes precedence over the breakeven stop.
    if leg.target_hit and leg.trail_active and leg.current_qty > 0:
        leg = _trail_stop_hit(leg, mark, now)
        if leg.closed:
            return leg
    # Before target or after partial book but no trail hit: check initial SL.
    if not leg.target_hit:
        leg = _initial_stop_hit(leg, mark, now)
        if leg.closed:
            return leg
    # Target hit check.
    if not leg.target_hit:
        leg = _target_hit(leg, mark, now)
        if leg.closed:
            return leg
    if leg.target_hit and not leg.closed:
        leg = _pyramid_trigger(leg, mark, now, position)
    # Update peak after all exit checks.
    leg.update_peak(mark)
    return leg


def evaluate_position(position: IntradayPosition, marks: dict[str, float], now: datetime) -> IntradayPosition:
    if position.status == "CLOSED" or position.all_legs_closed():
        return position
    eod = now.astimezone(IST_ZONE).time().replace(tzinfo=None) >= INTRADAY_SQUARE_OFF_TIME
    for leg in position.legs:
        mark = marks.get(leg.symbol)
        if mark is None or mark <= 0:
            continue
        if eod and not leg.closed:
            leg = _eod_square_off(leg, mark, now)
        else:
            leg = evaluate_leg(leg, mark, now, position)
    position.legs = [leg for leg in position.legs]
    position.total_realized_pnl = position.total_realized()
    position.remaining_qty = sum(leg.current_qty for leg in position.legs if not leg.closed)
    if position.all_legs_closed():
        position.status = "CLOSED"
        reasons = [leg.exit_reason for leg in position.legs if leg.exit_reason]
        position.exit_reason = reasons[0] if reasons else "UNKNOWN"
    return position


# ---------------------------------------------------------------------------
# Batch evaluator (parallel across positions)
# ---------------------------------------------------------------------------
def evaluate_positions(positions: list[IntradayPosition], marks: dict[str, float], now: datetime) -> list[IntradayPosition]:
    results: list[IntradayPosition] = []
    for position in positions:
        results.append(evaluate_position(position, marks, now))
    return results


# ---------------------------------------------------------------------------
# Paper book integration helpers
# ---------------------------------------------------------------------------
def position_from_dict(row: dict[str, Any], sequence: int) -> IntradayPosition | None:
    try:
        direction = str(row.get("direction") or "LONG").upper()
        legs_raw = row.get("legs") or [row]
        legs: list[LegState] = []
        for idx, leg_raw in enumerate(legs_raw):
            symbol = str(leg_raw.get("symbol") or row.get("symbol") or f"LEG_{idx}")
            entry = _float(leg_raw.get("entryPrice") or leg_raw.get("entryPremium") or row.get("entryPrice") or row.get("entryPremium"))
            qty = int(leg_raw.get("qty") or leg_raw.get("quantity") or row.get("quantity") or 0)
            if entry is None or entry <= 0 or qty <= 0:
                continue
            stop_raw = _float(leg_raw.get("stopPrice") or leg_raw.get("stopLoss") or leg_raw.get("initialStopPremium"))
            target_raw = _float(leg_raw.get("targetPrice") or leg_raw.get("targetPremium"))
            peak_raw = _float(leg_raw.get("peakPrice") or leg_raw.get("peakPremium"))
            leg = LegState(
                symbol=symbol,
                direction=direction,
                entry_price=round(entry, 2),
                initial_qty=int(leg_raw.get("initialQty") or qty),
                current_qty=qty,
                average_entry_price=round(_float(leg_raw.get("averageEntryPrice")) or entry, 4),
                pyramided_qty=int(leg_raw.get("pyramidedQty") or 0),
                partial_booked_qty=int(leg_raw.get("partialBookedQty") or 0),
                stop_price=round(stop_raw, 2) if stop_raw is not None else round(entry - INTRADAY_SL_POINTS, 2) if direction == "LONG" else round(entry + INTRADAY_SL_POINTS, 2),
                target_price=round(target_raw, 2) if target_raw is not None else round(entry + INTRADAY_TARGET_POINTS, 2) if direction == "LONG" else round(entry - INTRADAY_TARGET_POINTS, 2),
                peak_price=round(peak_raw, 2) if peak_raw is not None else entry,
                mfe_points=round(float(leg_raw.get("mfePoints") or 0.0), 2),
                target_hit=bool(leg_raw.get("targetHit")),
                trail_active=bool(leg_raw.get("trailActive")),
                closed=bool(leg_raw.get("closed")),
                exit_reason=str(leg_raw.get("exitReason") or ""),
                exit_price=round(float(leg_raw.get("exitPrice") or 0.0), 2),
                realized_pnl=round(float(leg_raw.get("realizedPnl") or 0.0), 2),
            )
            if leg_raw.get("minuteMarks") and isinstance(leg_raw.get("minuteMarks"), list):
                leg.minute_marks = [m for m in leg_raw["minuteMarks"] if isinstance(m, dict)]
            legs.append(leg)
        if not legs:
            return None
        pos = IntradayPosition(
            position_id=str(row.get("id") or row.get("positionId") or ""),
            index=str(row.get("index") or row.get("key") or ""),
            direction=direction,
            legs=legs,
            entry_time=str(row.get("enteredAt") or row.get("entryTime") or ""),
            status=str(row.get("status") or "OPEN"),
            exit_reason=str(row.get("exitReason") or ""),
            total_realized_pnl=round(_float(row.get("pnl") or row.get("realizedPnl") or 0) or 0, 2),
            remaining_qty=int(row.get("remainingQty") or sum(leg.current_qty for leg in legs)),
            pyramided_lots=int(row.get("pyramidedLots") or 0),
        )
        return pos
    except Exception:
        return None


def position_to_dict(position: IntradayPosition) -> dict[str, Any]:
    return {
        "id": position.position_id,
        "positionId": position.position_id,
        "index": position.index,
        "key": position.index,
        "direction": position.direction,
        "status": position.status,
        "exitReason": position.exit_reason,
        "pnl": round(position.total_realized_pnl, 2),
        "realizedPnl": round(position.total_realized_pnl, 2),
        "remainingQty": position.remaining_qty,
        "pyramidedLots": position.pyramided_lots,
        "legs": [
            {
                "symbol": leg.symbol,
                "direction": leg.direction,
                "entryPrice": leg.entry_price,
                "averageEntryPrice": leg.average_entry_price or leg.entry_price,
                "qty": leg.current_qty,
                "initialQty": leg.initial_qty,
                "pyramidedQty": leg.pyramided_qty,
                "partialBookedQty": leg.partial_booked_qty,
                "stopPrice": leg.stop_price,
                "targetPrice": leg.target_price,
                "peakPrice": leg.peak_price,
                "mfePoints": round(leg.mfe_points, 2),
                "targetHit": leg.target_hit,
                "trailActive": leg.trail_active,
                "closed": leg.closed,
                "exitReason": leg.exit_reason,
                "exitPrice": leg.exit_price,
                "realizedPnl": round(leg.realized_pnl, 2),
                "minuteMarks": leg.minute_marks,
            }
            for leg in position.legs
        ],
        "strategyMode": "INTRADAY_PYRAMID",
        "strategyType": "LONG_PREMIUM_PYRAMID",
        "policyVersion": position.policy_version,
        "entryTime": position.entry_time,
    }


# ---------------------------------------------------------------------------
# Book-level reconcile (drop-in for paper supervisor)
# ---------------------------------------------------------------------------
def reconcile_intraday_book(
    book: dict[str, Any],
    marks: dict[str, float],
    now: datetime | None = None,
    *,
    persist: bool = False,
    book_path: Path | None = None,
) -> dict[str, Any]:
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    session = clock.date().isoformat()
    out = dict(book)
    out.setdefault("open", [])
    out.setdefault("closed", [])
    positions: list[IntradayPosition] = []
    for row in list(out["open"]):
        pos = position_from_dict(row, sequence=0)
        if pos is not None:
            positions.append(pos)
    updated = evaluate_positions(positions, marks, clock)
    next_open: list[dict[str, Any]] = []
    closed_now: list[dict[str, Any]] = []
    for pos in updated:
        d = position_to_dict(pos)
        if pos.all_legs_closed():
            closed_now.append(d)
        else:
            next_open.append(d)
    out["open"] = next_open
    out["closed"].extend(closed_now)
    out["entryCount"] = len(out["open"]) + len(out["closed"])
    out["updatedAt"] = clock.isoformat()
    out["openPnl"] = round(sum(_float(p.get("unrealizedPnl") or 0) or 0 for p in out["open"]), 2)
    out["realizedPnl"] = round(sum(_float(p.get("pnl") or 0) or 0 for p in out["closed"]), 2)
    out["totalPnl"] = round(out["openPnl"] + out["realizedPnl"], 2)
    if persist and book_path:
        from .json_atomic import atomic_write_json
        atomic_write_json(book_path, out)
    return out


# ---------------------------------------------------------------------------
# Parallel mark evaluator
# ---------------------------------------------------------------------------
def evaluate_marks_parallel(
    positions: list[IntradayPosition],
    marks: dict[str, float],
    now: datetime,
) -> list[IntradayPosition]:
    """Evaluate each position independently; safe for concurrent leg updates."""
    threads: list[threading.Thread] = []
    results: list[IntradayPosition | None] = [None] * len(positions)
    for idx, position in enumerate(positions):
        def _run(i: int = idx, p: IntradayPosition = position) -> None:
            results[i] = evaluate_position(p, marks, now)
        t = threading.Thread(target=_run)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    return [r for r in results if r is not None]


__all__ = [
    "INTRADAY_SL_POINTS",
    "INTRADAY_TARGET_POINTS",
    "INTRADAY_PARTIAL_BOOK_PCT",
    "INTRADAY_PYRAMID_ADD_LOTS",
    "INTRADAY_MAX_PYRAMID_LOTS",
    "INTRADAY_PYRAMID_TRIGGER_POINTS",
    "INTRADAY_TRAIL_SL_AFTER_TARGET_POINTS",
    "INTRADAY_SQUARE_OFF_TIME",
    "INTRADAY_MARK_INTERVAL_SECONDS",
    "LegState",
    "IntradayPosition",
    "create_position",
    "evaluate_leg",
    "evaluate_position",
    "evaluate_positions",
    "evaluate_marks_parallel",
    "position_from_dict",
    "position_to_dict",
    "reconcile_intraday_book",
]
