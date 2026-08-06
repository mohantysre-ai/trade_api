"""Institutional scale-out + R-ratchet trailing exit plan.

Policy (original qty fractions via largest-remainder):
  +0.5R book 20%  — de-risk; keep initial hard SL
  +1.0R book 30%  — core harvest; trail stop → breakeven
  +1.5R book 25%  — harvest; trail stop → +0.5R
  Runner ~25%     — ratchet trail at 2R→+1R, 3R→+1.5R, 4R→+2.5R
  Remainder exits on trail stop hit or session square-off.

Legacy target1/target2 remain as 1.5R / 3.0R *reference* levels for UI.
Plans without exitPlan fall back to binary T1/T2/SL elsewhere.
"""
from __future__ import annotations

from typing import Any

SCALE_LEGS: list[tuple[float, float]] = [
    (0.5, 0.20),
    (1.0, 0.30),
    (1.5, 0.25),
]
# After scale legs, ~0.25 remains as runner
RUNNER_FRAC = round(1.0 - sum(p for _, p in SCALE_LEGS), 4)

# Highest R reached → trail stop locked at entry + k·R (LONG) / entry − k·R (SHORT)
# k=0.0 means breakeven (entry)
TRAIL_RATCHET: dict[float, float] = {
    1.0: 0.0,
    1.5: 0.5,
    2.0: 1.0,
    3.0: 1.5,
    4.0: 2.5,
}

REF_T1_R = 1.5
REF_T2_R = 3.0


def allocate_leg_qty(total_qty: int, fracs: list[float] | None = None) -> list[int]:
    """Largest-remainder allocation so integer lots sum to total_qty."""
    n = int(total_qty or 0)
    if n <= 0:
        return []
    parts = list(fracs) if fracs is not None else [p for _, p in SCALE_LEGS] + [RUNNER_FRAC]
    if abs(sum(parts) - 1.0) > 1e-6:
        s = sum(parts) or 1.0
        parts = [p / s for p in parts]

    # Tiny positions: collapse to single runner (no micro-legs)
    if n < 4:
        return [0] * (len(parts) - 1) + [n]

    raw = [n * f for f in parts]
    floors = [int(x) for x in raw]
    rem = n - sum(floors)
    order = sorted(range(len(parts)), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order:
        if rem <= 0:
            break
        floors[i] += 1
        rem -= 1
    diff = n - sum(floors)
    if diff != 0 and floors:
        floors[-1] = max(0, floors[-1] + diff)
    return floors


def _sign(direction: str) -> int:
    return -1 if str(direction or "LONG").upper() == "SHORT" else 1


def _target_price(entry: float, risk: float, r_mult: float, direction: str) -> float:
    return round(entry + _sign(direction) * risk * r_mult, 2)


def _stop_at_r(entry: float, risk: float, lock_r: float, direction: str) -> float:
    """Trail stop price for lock_r (0 = breakeven)."""
    return round(entry + _sign(direction) * risk * lock_r, 2)


def _initial_stop(entry: float, risk: float, direction: str) -> float:
    return round(entry - _sign(direction) * risk, 2)


def build_exit_plan(
    entry: float,
    risk_per_share: float,
    direction: str,
    qty: int,
    *,
    initial_stop: float | None = None,
) -> dict[str, Any]:
    """Build persistable SCALE_TRAIL plan + legacy T1/T2 reference levels."""
    entry = float(entry or 0)
    risk = float(risk_per_share or 0)
    direction = str(direction or "LONG").upper()
    qty = int(qty or 0)
    notes: list[str] = []

    if entry <= 0 or risk <= 0:
        return {
            "mode": "SCALE_TRAIL",
            "legs": [],
            "runnerQty": 0,
            "initialStop": initial_stop,
            "target1": None,
            "target2": None,
            "notes": ["invalid_entry_or_risk"],
        }

    fracs = [p for _, p in SCALE_LEGS] + [RUNNER_FRAC]
    lots = allocate_leg_qty(qty, fracs)
    if qty < 4:
        notes.append("qty_lt_4_collapsed_to_runner")

    legs: list[dict[str, Any]] = []
    for i, (r_mult, pct) in enumerate(SCALE_LEGS):
        leg_qty = lots[i] if i < len(lots) else 0
        trail_after = TRAIL_RATCHET.get(r_mult)
        legs.append(
            {
                "r": r_mult,
                "qtyPct": pct,
                "qty": leg_qty,
                "price": _target_price(entry, risk, r_mult, direction),
                "trailStopAfter": trail_after,
            }
        )

    runner_qty = lots[-1] if lots else 0
    hard_sl = (
        round(float(initial_stop), 2)
        if initial_stop is not None
        else _initial_stop(entry, risk, direction)
    )

    return {
        "mode": "SCALE_TRAIL",
        "direction": direction,
        "entry": round(entry, 2),
        "riskPerShare": round(risk, 2),
        "initialStop": hard_sl,
        "legs": legs,
        "runnerQty": runner_qty,
        "runnerFrac": RUNNER_FRAC,
        "trailRatchet": {str(k): v for k, v in TRAIL_RATCHET.items()},
        "target1": _target_price(entry, risk, REF_T1_R, direction),
        "target2": _target_price(entry, risk, REF_T2_R, direction),
        "notes": notes,
    }


def attach_exit_plan(row: dict[str, Any]) -> dict[str, Any]:
    """Return row copy with exitPlan + aligned reference T1/T2."""
    out = dict(row)
    entry = float(out.get("entryPrice") or 0)
    risk = float(out.get("riskPerShare") or 0)
    if risk <= 0:
        sl = float(out.get("stopLoss") or 0)
        if entry > 0 and sl > 0:
            risk = abs(entry - sl)
    qty = int(out.get("approxQty") or 0)
    direction = str(out.get("direction") or "LONG")
    initial_stop = out.get("stopLoss")
    plan = build_exit_plan(
        entry,
        risk,
        direction,
        qty,
        initial_stop=float(initial_stop) if initial_stop is not None else None,
    )
    out["exitPlan"] = plan
    if plan.get("target1") is not None:
        out["target1"] = plan["target1"]
    if plan.get("target2") is not None:
        out["target2"] = plan["target2"]
    if plan.get("initialStop") is not None and not out.get("stopLoss"):
        out["stopLoss"] = plan["initialStop"]
    return out


def _r_reached(entry: float, risk: float, ltp: float, direction: str) -> float:
    if entry <= 0 or risk <= 0:
        return 0.0
    signed = _sign(direction) * (ltp - entry)
    return signed / risk


def _leg_crossed(leg_price: float, ltp: float, direction: str) -> bool:
    if direction == "SHORT":
        return ltp <= leg_price
    return ltp >= leg_price


def _stop_hit(stop: float, ltp: float, direction: str) -> bool:
    if direction == "SHORT":
        return ltp >= stop
    return ltp <= stop


def _mtm_pnl(direction: str, entry: float, exit_px: float, qty: int) -> float:
    return round(_sign(direction) * (exit_px - entry) * qty, 2)


def evaluate_scale_trail(
    pick: dict[str, Any],
    ltp: float | None = None,
    *,
    after_close: bool = False,
) -> dict[str, Any]:
    """Evaluate scale-out + trail state for one pick.

    Idempotent vs prior exitState: legs only fill once; stop only ratchets.
    Returns outcome-compatible fields plus exitState / PnL split.
    """
    plan = pick.get("exitPlan") if isinstance(pick.get("exitPlan"), dict) else None
    if not plan or plan.get("mode") != "SCALE_TRAIL":
        return {}

    entry = float(pick.get("entryPrice") or plan.get("entry") or 0)
    risk = float(pick.get("riskPerShare") or plan.get("riskPerShare") or 0)
    direction = str(pick.get("direction") or plan.get("direction") or "LONG").upper()
    total_qty = int(pick.get("approxQty") or 0)
    if ltp is None:
        ltp = float(pick.get("currentPrice") or pick.get("ltp") or entry or 0)
    else:
        ltp = float(ltp)

    if entry <= 0 or risk <= 0 or total_qty <= 0 or ltp <= 0:
        return {}

    prior = pick.get("exitState") if isinstance(pick.get("exitState"), dict) else {}
    filled_rs: set[float] = set()
    for x in prior.get("legsFilled") or []:
        if isinstance(x, dict) and isinstance(x.get("r"), (int, float)):
            filled_rs.add(float(x["r"]))
    legs_filled: list[dict[str, Any]] = [
        dict(x) for x in (prior.get("legsFilled") or []) if isinstance(x, dict) and isinstance(x.get("r"), (int, float))
    ]

    initial_stop = float(
        plan.get("initialStop") or pick.get("stopLoss") or _initial_stop(entry, risk, direction)
    )
    effective_stop = float(prior.get("effectiveStop") or initial_stop)

    for leg in plan.get("legs") or []:
        if not isinstance(leg, dict):
            continue
        r_mult = float(leg.get("r") or 0)
        if r_mult in filled_rs:
            continue
        leg_qty = int(leg.get("qty") or 0)
        leg_px = float(leg.get("price") or 0)
        if leg_qty <= 0 or leg_px <= 0:
            continue
        if _leg_crossed(leg_px, ltp, direction):
            pnl = _mtm_pnl(direction, entry, leg_px, leg_qty)
            legs_filled.append({"r": r_mult, "qty": leg_qty, "price": leg_px, "pnl": pnl})
            filled_rs.add(r_mult)
            lock_r = leg.get("trailStopAfter")
            if lock_r is None:
                lock_r = TRAIL_RATCHET.get(r_mult)
            if lock_r is not None:
                new_stop = _stop_at_r(entry, risk, float(lock_r), direction)
                if direction == "SHORT":
                    effective_stop = min(effective_stop, new_stop)
                else:
                    effective_stop = max(effective_stop, new_stop)

    r_now = _r_reached(entry, risk, ltp, direction)
    for thresh in sorted(TRAIL_RATCHET.keys()):
        if r_now + 1e-9 >= thresh:
            lock_r = TRAIL_RATCHET[thresh]
            new_stop = _stop_at_r(entry, risk, lock_r, direction)
            if direction == "SHORT":
                effective_stop = min(effective_stop, new_stop)
            else:
                effective_stop = max(effective_stop, new_stop)

    booked_qty = sum(int(x.get("qty") or 0) for x in legs_filled)
    remaining = max(0, total_qty - booked_qty)
    realized = round(sum(float(x.get("pnl") or 0) for x in legs_filled), 2)

    closed = False
    trail_hit = False
    square_off = False

    if remaining > 0 and _stop_hit(effective_stop, ltp, direction):
        exit_px_rem = effective_stop
        rem_pnl = _mtm_pnl(direction, entry, exit_px_rem, remaining)
        realized = round(realized + rem_pnl, 2)
        legs_filled.append({"r": "TRAIL_SL", "qty": remaining, "price": exit_px_rem, "pnl": rem_pnl})
        remaining = 0
        closed = True
        trail_hit = True
    elif remaining > 0 and after_close:
        rem_pnl = _mtm_pnl(direction, entry, ltp, remaining)
        realized = round(realized + rem_pnl, 2)
        legs_filled.append({"r": "EOD_SQUAREOFF", "qty": remaining, "price": round(ltp, 2), "pnl": rem_pnl})
        remaining = 0
        closed = True
        square_off = True
    elif remaining <= 0:
        closed = True

    unrealized = _mtm_pnl(direction, entry, ltp, remaining) if remaining > 0 else 0.0
    pct_change = ((ltp - entry) / entry * 100) if entry else 0.0

    filled_r_labels = [f"{x.get('r')}R" for x in legs_filled if isinstance(x.get("r"), (int, float))]
    if trail_hit:
        label = "TRAIL STOP HIT"
        hit_level: str | None = "sl"
        detail = f"Trail SL {effective_stop:.2f} · LTP {ltp:.2f} · rem flat"
    elif square_off:
        label = "EOD SQUAREOFF"
        hit_level = None
        detail = f"Session square rem @ {ltp:.2f}"
    elif closed and booked_qty >= total_qty and not trail_hit:
        label = "SCALE COMPLETE"
        hit_level = "t2" if any(float(x.get("r") or 0) >= 1.5 for x in legs_filled if isinstance(x.get("r"), (int, float))) else "t1"
        detail = f"All scale legs filled · LTP {ltp:.2f}"
    elif legs_filled:
        max_r = max(
            (float(x["r"]) for x in legs_filled if isinstance(x.get("r"), (int, float))),
            default=0.0,
        )
        label = f"PARTIAL {max_r:g}R"
        hit_level = "partial"
        detail = f"Filled {filled_r_labels} · rem {remaining}"
    else:
        label = "PENDING"
        hit_level = None
        detail = f"LTP {ltp:.2f} | Entry {entry:.2f} | R {r_now:+.2f}"

    exit_state = {
        "legsFilled": legs_filled,
        "remainingQty": remaining,
        "effectiveStop": round(effective_stop, 2),
        "realizedPnl": realized,
        "unrealizedPnl": unrealized,
        "rMultiple": round(r_now, 3),
        "closed": closed,
        "mode": "SCALE_TRAIL",
    }

    return {
        "label": label,
        "detail": detail,
        "hitLevel": hit_level,
        "ltp": round(ltp, 2),
        "pctChange": round(pct_change, 2),
        "exitState": exit_state,
        "remainingQty": remaining,
        "realizedPnl": realized,
        "unrealizedPnl": unrealized,
        "effectiveStop": round(effective_stop, 2),
        "rMultiple": round(r_now, 3),
        "closed": closed,
        "scaleTrail": True,
    }


def blended_pnl_from_state(
    pick: dict[str, Any],
    mark: float,
    *,
    after_close: bool = True,
) -> tuple[float, float, dict[str, Any]]:
    """Return (total_pnl, avg_exit_price, eval_result) for EOD books."""
    result = evaluate_scale_trail(pick, mark, after_close=after_close)
    if not result:
        return 0.0, mark, {}
    realized = float(result.get("realizedPnl") or 0)
    unrealized = float(result.get("unrealizedPnl") or 0)
    total = round(realized + unrealized, 2)
    state = result.get("exitState") or {}
    filled = state.get("legsFilled") or []
    qty = int(pick.get("approxQty") or 0)
    if filled and qty > 0:
        notional = sum(float(x.get("price") or 0) * int(x.get("qty") or 0) for x in filled)
        booked = sum(int(x.get("qty") or 0) for x in filled)
        rem = int(state.get("remainingQty") or 0)
        if rem > 0:
            notional += mark * rem
            booked += rem
        avg = round(notional / booked, 2) if booked else mark
    else:
        avg = mark
    return total, avg, result
