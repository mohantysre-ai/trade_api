"""Deterministic institutional scale-out + R-ratchet trailing exit plan.

The exit engine owns execution economics for an already-triggered position.
Forensic diagnostics must never redefine realized P&L or R.
"""
from __future__ import annotations

import math
from typing import Any

# Confirmed move -> fraction booked. 40% is deliberately retained as a runner.
SCALE_LEGS: list[tuple[float, float]] = [
    (1.00, 0.20),
    (1.50, 0.20),
    (2.00, 0.20),
]
RUNNER_FRAC = 0.40

# NSE hybrid trail, expressed in R (desk 1R = initial risk).
# 0–2R: fixed initial SL, with partial fills at 1R and 1.5R.
# Do not move to BE after partial fills: 20% at 1R + 80% at BE is
# only 0.2R for the whole trade. Arm the profit trail at 2R instead.
# 2R: ATR×1.5 analogue → lock mfe−1.5 = 0.5R.
# 3R+: structure analogue → tighter lock, still room to run.
# Initial SL and trail gap are also capped at MAX_STOP_PCT (0.5%) of price.
# Stop is monotonic and never loosens.
TRAIL_RATCHET: dict[float, float] = {
    1.00: -1.00,
    1.50: -1.00,
    2.00: 0.50,
    3.00: 1.50,
    4.00: 2.50,
    5.00: 3.50,
}

PROFIT_GUARD_TRIGGER_R = 2.0
PROFIT_GUARD_LOCK_R = 0.5
PCT_TRAIL_TRIGGER_R = 2.0
MAX_STOP_PCT = 0.005
REF_T1_R = 1.5
REF_T2_R = 3.0
EXIT_POLICY_VERSION = "1r_scale_2r_trail_blended_1r_max_0p5pct"
SWING_TRAIL_RATCHET = {**TRAIL_RATCHET, 1.0: 0.0, 1.5: 0.0}
# 40R at 0.5% risk = 20% (upper circuit class). 80–100R trails are not market.
MAX_STATE_MFE_R = 40.0
MAX_INTRADAY_PRICE_RATIO = 1.50
MIN_INTRADAY_PRICE_RATIO = 0.50


def allocate_leg_qty(total_qty: int, fracs: list[float] | None = None) -> list[int]:
    n = int(total_qty or 0)
    if n <= 0:
        return []
    parts = list(fracs) if fracs is not None else [p for _, p in SCALE_LEGS] + [RUNNER_FRAC]
    if n < len(parts):
        return [0] * (len(parts) - 1) + [n]
    raw = [n * f for f in parts]
    floors = [int(x) for x in raw]
    rem = n - sum(floors)
    order = sorted(range(len(parts)), key=lambda i: (raw[i] - floors[i], -i), reverse=True)
    for i in order[:rem]:
        floors[i] += 1
    return floors


def _sign(direction: str) -> int:
    return -1 if str(direction or "LONG").upper() == "SHORT" else 1


def _target_price(entry: float, risk: float, r_mult: float, direction: str) -> float:
    return round(entry + _sign(direction) * risk * r_mult, 2)


def _stop_at_r(entry: float, risk: float, lock_r: float, direction: str) -> float:
    return round(entry + _sign(direction) * risk * lock_r, 2)


def _initial_stop(entry: float, risk: float, direction: str) -> float:
    return round(entry - _sign(direction) * risk, 2)


def cap_stop_risk(entry: float, risk: float) -> float:
    """Hard cap: stop distance ≤ 0.5% of entry. Never widens a tighter stop."""
    if entry <= 0 or risk <= 0:
        return max(float(risk or 0), 0.0)
    return min(float(risk), round(float(entry) * MAX_STOP_PCT, 6))


def apply_max_stop_cap(row: dict[str, Any]) -> dict[str, Any]:
    """Put the 0.5% initial-stop cap on the row. Never widens a valid tighter stop."""
    out = dict(row)
    entry = _fnum(out.get("entryPrice"))
    if entry is None or entry <= 0:
        return out
    direction = str(out.get("direction") or "LONG").upper()
    raw_stop = _fnum(out.get("stopLoss"))
    plan = out.get("exitPlan") if isinstance(out.get("exitPlan"), dict) else {}
    state = out.get("exitState") if isinstance(out.get("exitState"), dict) else {}
    if raw_stop is None:
        raw_stop = _fnum(plan.get("initialStop") or state.get("initialStop"))
    raw_risk = _fnum(out.get("riskPerShare") or plan.get("riskPerShare"))
    if raw_risk is None and raw_stop is not None:
        raw_risk = abs(entry - raw_stop)
    wrong_side = raw_stop is not None and not _valid_stop(entry, raw_stop, direction)
    if raw_risk is None or raw_risk <= 0 or wrong_side:
        raw_risk = entry * MAX_STOP_PCT
    risk = cap_stop_risk(entry, raw_risk)
    stop = _initial_stop(entry, risk, direction)
    out["riskPerShare"] = risk
    out["stopLoss"] = stop
    if plan:
        next_plan = dict(plan)
        next_plan["initialStop"] = stop
        next_plan["riskPerShare"] = risk
        notes = [str(n) for n in (next_plan.get("notes") or [])]
        if "max_stop_0p5pct" not in notes:
            notes.append("max_stop_0p5pct")
        next_plan["notes"] = notes
        next_plan["policyVersion"] = EXIT_POLICY_VERSION
        out["exitPlan"] = next_plan
    return out


def _tighter_stop(direction: str, current: float, candidate: float) -> float:
    return min(current, candidate) if str(direction).upper() == "SHORT" else max(current, candidate)


def _pct_trail_from_mfe(entry: float, risk: float, direction: str, r_now: float) -> float:
    """Trail at most MAX_STOP_PCT behind the favourable extreme."""
    mfe_px = entry + _sign(direction) * risk * max(float(r_now), 0.0)
    if str(direction).upper() == "SHORT":
        return round(mfe_px * (1.0 + MAX_STOP_PCT), 2)
    return round(mfe_px * (1.0 - MAX_STOP_PCT), 2)


def _valid_stop(entry: float, stop: float, direction: str) -> bool:
    """Hard invariant: LONG stop below entry; SHORT stop above entry."""
    return stop < entry if str(direction).upper() == "LONG" else stop > entry


def build_exit_plan(
    entry: float,
    risk_per_share: float,
    direction: str,
    qty: int,
    *,
    initial_stop: float | None = None,
) -> dict[str, Any]:
    entry, risk, qty = float(entry or 0), float(risk_per_share or 0), int(qty or 0)
    direction = str(direction or "LONG").upper()
    if entry <= 0 or risk <= 0 or qty <= 0:
        return {
            "mode": "SCALE_TRAIL",
            "legs": [],
            "runnerQty": 0,
            "initialStop": initial_stop,
            "target1": None,
            "target2": None,
            "validRiskModel": False,
            "notes": ["invalid_entry_risk_or_qty"],
        }

    supplied_stop = float(initial_stop) if initial_stop is not None else None
    stop_repaired = supplied_stop is not None and not _valid_stop(entry, supplied_stop, direction)
    stop_capped = False
    if supplied_stop is not None and _valid_stop(entry, supplied_stop, direction):
        # Keep locked-book stops as-is (do not retro-tighten open positions).
        risk = abs(entry - supplied_stop)
        hard_sl = round(supplied_stop, 2)
    else:
        capped = cap_stop_risk(entry, risk)
        stop_capped = capped + 1e-12 < risk
        risk = capped
        hard_sl = _initial_stop(entry, risk, direction)

    lots = allocate_leg_qty(qty)
    legs: list[dict[str, Any]] = []
    for i, (r_mult, pct) in enumerate(SCALE_LEGS):
        legs.append({
            "r": r_mult,
            "qtyPct": pct,
            "qty": lots[i],
            "price": _target_price(entry, risk, r_mult, direction),
            "trailStopAfter": TRAIL_RATCHET[r_mult],
        })

    return {
        "mode": "SCALE_TRAIL",
        "direction": direction,
        "entry": round(entry, 2),
        "riskPerShare": round(risk, 4),
        "initialStop": hard_sl,
        "legs": legs,
        "runnerQty": lots[-1] if lots else 0,
        "runnerFrac": RUNNER_FRAC,
        "trailRatchet": {str(k): v for k, v in TRAIL_RATCHET.items()},
        "target1": _target_price(entry, risk, REF_T1_R, direction),
        "target2": _target_price(entry, risk, REF_T2_R, direction),
        "validRiskModel": True,
        "stopRepaired": stop_repaired,
        "stopCapped": stop_capped,
        "notes": [
            "40pct_runner",
            "monotonic_r_ratchet",
            "trail_after_2r_blended_1r",
            "max_stop_0p5pct",
            "nse_hybrid_trail",
            "no_stop_loosen",
            "book_pnl_authoritative",
        ],
    }


def attach_exit_plan(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    entry = float(out.get("entryPrice") or 0)
    direction = str(out.get("direction") or "LONG").upper()
    risk = float(out.get("riskPerShare") or 0)
    if risk <= 0:
        sl = float(out.get("stopLoss") or 0)
        if entry > 0 and sl > 0 and _valid_stop(entry, sl, direction):
            risk = abs(entry - sl)
    # If the supplied stop is inverted, derive risk from the existing magnitude
    # but repair the actual stop to the correct side.
    if risk <= 0:
        sl = float(out.get("stopLoss") or 0)
        if entry > 0 and sl > 0:
            risk = abs(entry - sl)

    supplied_stop = float(out["stopLoss"]) if out.get("stopLoss") is not None else None
    plan = build_exit_plan(
        entry,
        risk,
        direction,
        int(out.get("approxQty") or 0),
        initial_stop=supplied_stop,
    )
    if out.get("exitPolicyScope") == "SWING":
        plan["scope"] = "SWING"
        plan["policyVersion"] = "1r_be_2r_trail_max_0p5pct"
        plan["trailRatchet"] = {str(k): v for k, v in SWING_TRAIL_RATCHET.items()}
        plan["notes"] = ["be_after_1r_scale" if n == "trail_after_2r_blended_1r" else n
                         for n in plan.get("notes", [])]
        for leg in plan.get("legs", []):
            leg["trailStopAfter"] = SWING_TRAIL_RATCHET[leg["r"]]
    out["exitPlan"] = plan
    if plan.get("target1") is not None:
        out["target1"] = plan["target1"]
    if plan.get("target2") is not None:
        out["target2"] = plan["target2"]
    if plan.get("initialStop") is not None:
        out["stopLoss"] = plan["initialStop"]
    out["riskPerShare"] = plan.get("riskPerShare") or risk
    out["riskModelValid"] = bool(plan.get("validRiskModel"))
    out["stopRepaired"] = bool(plan.get("stopRepaired"))
    return out


def exit_plan_is_current(plan: dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict) or plan.get("mode") != "SCALE_TRAIL":
        return False
    notes = plan.get("notes") or []
    if plan.get("scope") == "SWING":
        return "be_after_1r_scale" in notes and "max_stop_0p5pct" in notes
    return "trail_after_2r_blended_1r" in notes and "max_stop_0p5pct" in notes


def refresh_exit_policy(row: dict[str, Any], *, keep_exit_state: bool = True) -> dict[str, Any]:
    """Rebuild SCALE_TRAIL notes/ratchet to current desk policy.

    Keeps locked initialStop and booked exitState. Does not invent PnL.
    """
    out = dict(row)
    state = row.get("exitState") or {}
    if keep_exit_state and (row.get("closed") or state.get("closed")) and state.get("legsFilled") and _exit_state_is_sane(row, state):
        return out
    booked = out.get("exitPlan") if isinstance(out.get("exitPlan"), dict) else None
    if keep_exit_state and isinstance(booked, dict) and not exit_plan_is_current(booked):
        out["bookedExitPlan"] = {
            "notes": list(booked.get("notes") or []),
            "trailRatchet": dict(booked.get("trailRatchet") or {}),
        }
    attached = attach_exit_plan(out)
    plan = attached.get("exitPlan")
    if isinstance(plan, dict):
        plan = dict(plan)
        if plan.get("scope") != "SWING":
            plan["policyVersion"] = EXIT_POLICY_VERSION
        out["exitPlan"] = plan
        if plan.get("target1") is not None:
            out["target1"] = plan["target1"]
        if plan.get("target2") is not None:
            out["target2"] = plan["target2"]
        out["riskPerShare"] = attached.get("riskPerShare", out.get("riskPerShare"))
        out["riskModelValid"] = attached.get("riskModelValid")
        out["stopRepaired"] = attached.get("stopRepaired")
        closed = bool(out.get("closed") or str(out.get("status") or "").upper() == "CLOSED")
        if not closed and attached.get("stopLoss") is not None:
            out["stopLoss"] = attached["stopLoss"]
    if keep_exit_state and isinstance(row.get("exitState"), dict):
        state = dict(row["exitState"])
        closed = bool(row.get("closed") or str(row.get("status") or "").upper() == "CLOSED")
        legacy_early_be = isinstance(booked, dict) and bool(
            {"be_at_0p5r", "be_after_1r_scale"}.intersection(booked.get("notes") or [])
        )
        numeric_fills = [
            float(x.get("r")) for x in (state.get("legsFilled") or [])
            if isinstance(x, dict) and isinstance(x.get("r"), (int, float))
        ]
        peak_r = float(state.get("mfeR") or 0)
        if legacy_early_be and out.get("exitPolicyScope") != "SWING" and not closed and peak_r < 2.0 and not any(r >= 2.0 for r in numeric_fills):
            # Explicit open-paper policy migration. Keep every partial fill,
            # but remove the old early BE stop before the new 2R trigger.
            state["profitGuardActive"] = False
            state["effectiveStop"] = plan.get("initialStop") if isinstance(plan, dict) else out.get("stopLoss")
            out["effectiveStop"] = state["effectiveStop"]
        out["exitState"] = state
        if closed:
            if state.get("effectiveStop") is not None:
                out["effectiveStop"] = state["effectiveStop"]
            if state.get("remainingQty") is not None:
                out["remainingQty"] = state["remainingQty"]
    return out


def apply_exit_policy_to_rows(rows: list[Any]) -> tuple[list[Any], bool]:
    changed = False
    out: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        plan = row.get("exitPlan") if isinstance(row.get("exitPlan"), dict) else None
        if exit_plan_is_current(plan):
            out.append(row)
            continue
        if not row.get("entryPrice"):
            out.append(row)
            continue
        if not (row.get("approxQty") or row.get("stopLoss") or row.get("riskPerShare")):
            out.append(row)
            continue
        try:
            out.append(refresh_exit_policy(row, keep_exit_state=True))
            changed = True
        except Exception:
            out.append(row)
    return out, changed


def _row_initial_stop(row: dict[str, Any]) -> float | None:
    plan = row.get("exitPlan") if isinstance(row.get("exitPlan"), dict) else {}
    state = row.get("exitState") if isinstance(row.get("exitState"), dict) else {}
    for candidate in (plan.get("initialStop"), state.get("initialStop"), row.get("stopLoss")):
        stop = _fnum(candidate)
        if stop is not None:
            return stop
    return None


def _needs_path_overwrite(row: dict[str, Any]) -> bool:
    state = row.get("exitState") if isinstance(row.get("exitState"), dict) else {}
    if (
        str(state.get("policyVersion") or "") == EXIT_POLICY_VERSION
        and _exit_state_is_sane(row, state)
    ):
        return False
    status = str(row.get("executionStatus") or "").upper()
    if status == "NOT_TRIGGERED":
        return False
    triggered = (
        status == "TRIGGERED"
        or bool(row.get("triggered"))
        or bool(row.get("closed"))
        or bool(state)
    )
    if not triggered:
        return False
    if not row.get("entryPrice"):
        return False
    return int(row.get("approxQty") or row.get("qty") or 0) > 0


def _plausible_trade_price(entry: float, value: Any) -> float | None:
    price = _fnum(value)
    if entry <= 0 or price is None or price <= 0:
        return None
    if price < entry * MIN_INTRADAY_PRICE_RATIO or price > entry * MAX_INTRADAY_PRICE_RATIO:
        return None
    return price


def _exit_state_is_sane(row: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
    """Reject persisted state that can create impossible stop prices or P&L."""
    state = state if isinstance(state, dict) else {}
    entry = _fnum(row.get("entryPrice") or (row.get("exitPlan") or {}).get("entry"))
    qty = int(row.get("approxQty") or row.get("qty") or 0)
    if entry is None or entry <= 0 or qty <= 0:
        return False

    mfe = _fnum(state.get("mfeR"))
    if mfe is not None and (mfe < 0 or mfe > MAX_STATE_MFE_R):
        return False
    for key in ("effectiveStop", "initialStop"):
        if state.get(key) is not None and _plausible_trade_price(entry, state.get(key)) is None:
            return False

    booked_qty = 0
    recomputed_realized = 0.0
    for leg in state.get("legsFilled") or []:
        if not isinstance(leg, dict):
            return False
        try:
            leg_qty = int(leg.get("qty") or 0)
        except (TypeError, ValueError):
            return False
        price = _plausible_trade_price(entry, leg.get("price"))
        pnl = _fnum(leg.get("pnl"))
        if leg_qty < 0 or price is None or pnl is None:
            return False
        booked_qty += leg_qty
        if booked_qty > qty:
            return False
        expected = _mtm_pnl(str(row.get("direction") or "LONG"), entry, price, leg_qty)
        if abs(pnl - expected) > max(1.0, abs(expected) * 0.01):
            return False
        recomputed_realized += expected

    realized = _fnum(state.get("realizedPnl"))
    if realized is not None:
        if abs(realized) > entry * qty * (MAX_INTRADAY_PRICE_RATIO - 1.0) + 1.0:
            return False
        if state.get("legsFilled") and abs(realized - recomputed_realized) > max(1.0, abs(recomputed_realized) * 0.01):
            return False
    for key in ("economicPnl", "unrealizedPnl"):
        value = _fnum(state.get(key))
        if value is not None and abs(value) > entry * qty * (MAX_INTRADAY_PRICE_RATIO - 1.0) + 1.0:
            return False
    return True


def overwrite_row_with_current_policy(
    row: dict[str, Any],
    quotes: dict[str, Any] | None = None,
    *,
    after_close: bool = False,
    force: bool = False,
    ohlc_bars: list[tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    """Replay SCALE_TRAIL with the 0.5% initial-stop cap and current trail math."""
    state = row.get("exitState") or {}
    if (row.get("closed") or state.get("closed")) and state.get("legsFilled") and _exit_state_is_sane(row, state):
        # Real executed fills are not a counterfactual replay under a new policy.
        return row
    qty = int(row.get("approxQty") or row.get("qty") or 0)
    if not row.get("entryPrice") or qty <= 0:
        return row
    capped = apply_max_stop_cap(row)
    stop_changed = _fnum(capped.get("stopLoss")) != _fnum(row.get("stopLoss"))
    open_row = not bool(row.get("closed"))
    if not force and not stop_changed and not open_row and not _needs_path_overwrite(row):
        return row
    mark, high, low = _row_path_marks(capped, quotes)
    if ohlc_bars:
        last_close = float(ohlc_bars[-1][2])
        highs = [float(b[0]) for b in ohlc_bars]
        lows = [float(b[1]) for b in ohlc_bars]
        mark = last_close if mark is None else mark
        high = max(highs)
        low = min(lows)
        capped = dict(capped)
        capped["ltp"] = capped["currentPrice"] = last_close
        capped["sessionHigh"] = capped["dayHigh"] = high
        capped["sessionLow"] = capped["dayLow"] = low
    if mark is None:
        return row
    work = {k: v for k, v in capped.items() if k != "exitState"}
    if force or stop_changed:
        work.pop("exitPlan", None)
        work.pop("bookedExitPlan", None)
    work["approxQty"] = qty
    work = refresh_exit_policy(work, keep_exit_state=False)
    if ohlc_bars:
        ev = evaluate_scale_trail_candles(work, ohlc_bars, after_close=after_close)
    else:
        ev = evaluate_scale_trail_path(work, mark, high, low, after_close=after_close)
    if not ev:
        return work
    state = ev.get("exitState") if isinstance(ev.get("exitState"), dict) else {}
    closed = bool(ev.get("closed"))
    pnl = round(float(ev.get("economicPnl") or 0), 2)
    out = dict(work)
    out["exitState"] = state
    out["realizedPnl"] = ev.get("realizedPnl")
    out["unrealizedPnl"] = ev.get("unrealizedPnl")
    out["totalPnl"] = pnl
    out["pnl"] = pnl
    out["remainingQty"] = ev.get("remainingQty")
    out["effectiveStop"] = ev.get("effectiveStop")
    if ev.get("effectiveStop") is not None:
        out["stopLoss"] = ev.get("effectiveStop")
    out["closed"] = closed
    label = str(ev.get("label") or "").upper()
    if not closed:
        out["status"] = "RUNNING"
    elif "TRAIL STOP" in label:
        out["status"] = "TRAIL STOP HIT"
    elif "INITIAL STOP" in label:
        out["status"] = "STOP LOSS HIT"
    else:
        out["status"] = "CLOSED"
    out["mfeR"] = state.get("mfeR") if state.get("mfeR") is not None else out.get("mfeR")
    out["rMultiple"] = ev.get("rMultiple")
    out["economicR"] = ev.get("economicR")
    out["pathR"] = ev.get("pathR")
    out["outcome"] = {
        "label": ev.get("label"),
        "detail": ev.get("detail"),
        "hitLevel": ev.get("hitLevel"),
        "ltp": ev.get("ltp"),
        "pctChange": ev.get("pctChange"),
        "scaleTrail": True,
        "closed": closed,
    }
    if state.get("policyVersion") is None and isinstance(out.get("exitState"), dict):
        out["exitState"] = {**state, "policyVersion": EXIT_POLICY_VERSION}
    if (
        not force
        and bool(out.get("closed")) == bool(row.get("closed"))
        and out.get("remainingQty") == row.get("remainingQty")
        and _fnum(out.get("realizedPnl")) == _fnum(row.get("realizedPnl"))
        and _fnum(out.get("stopLoss")) == _fnum(row.get("stopLoss"))
        and str(out.get("status") or "") == str(row.get("status") or "")
    ):
        return row
    return out


def overwrite_rows_with_current_policy(
    rows: list[Any],
    quotes: dict[str, Any] | None = None,
    *,
    after_close: bool = False,
    force: bool = False,
) -> tuple[list[Any], bool]:
    changed = False
    out: list[Any] = []
    for row in rows or []:
        if not isinstance(row, dict):
            out.append(row)
            continue
        updated = overwrite_row_with_current_policy(
            row, quotes, after_close=after_close, force=force,
        )
        if updated is not row:
            changed = True
        out.append(updated)
    return out, changed


def profit_guard_active(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    try:
        r_mult = float(state.get("rMultiple") or 0)
    except (TypeError, ValueError):
        r_mult = 0.0
    if r_mult + 1e-9 >= PROFIT_GUARD_TRIGGER_R or state.get("profitGuardActive") is True:
        return True
    for x in state.get("legsFilled") or []:
        if isinstance(x, dict) and isinstance(x.get("r"), (int, float)) and float(x["r"]) >= PROFIT_GUARD_TRIGGER_R:
            return True
    return False


def _r_reached(entry: float, risk: float, ltp: float, direction: str) -> float:
    return _sign(direction) * (ltp - entry) / risk if entry > 0 and risk > 0 else 0.0


def _leg_crossed(price: float, ltp: float, direction: str) -> bool:
    return ltp <= price if direction == "SHORT" else ltp >= price


def _stop_hit(stop: float, ltp: float, direction: str) -> bool:
    return ltp >= stop if direction == "SHORT" else ltp <= stop


def _mtm_pnl(direction: str, entry: float, exit_px: float, qty: int) -> float:
    return round(_sign(direction) * (exit_px - entry) * qty, 2)


def _ratchet_stop(
    entry: float,
    risk: float,
    direction: str,
    current: float,
    r_now: float,
    *,
    trail_ratchet: dict[float, float] | None = None,
    profit_guard_trigger: float | None = None,
    use_pct_trail: bool = True,
) -> float:
    stop = current
    trigger_r = PROFIT_GUARD_TRIGGER_R if profit_guard_trigger is None else float(profit_guard_trigger)
    ratchet = trail_ratchet if trail_ratchet is not None else TRAIL_RATCHET
    if r_now + 1e-9 >= trigger_r:
        lock_r = PROFIT_GUARD_LOCK_R if profit_guard_trigger is None else 0.0
        stop = _tighter_stop(direction, stop, _stop_at_r(entry, risk, lock_r, direction))
        if use_pct_trail and r_now + 1e-9 >= PCT_TRAIL_TRIGGER_R:
            stop = _tighter_stop(direction, stop, _pct_trail_from_mfe(entry, risk, direction, r_now))
    for trigger, lock_r in ratchet.items():
        if r_now + 1e-9 < trigger:
            break
        stop = _tighter_stop(direction, stop, _stop_at_r(entry, risk, lock_r, direction))
    return round(stop, 2)


def _economic_r(total_pnl: float, entry: float, risk: float, qty: int) -> float:
    denominator = float(risk or 0) * int(qty or 0)
    return round(total_pnl / denominator, 3) if denominator > 0 else 0.0


def evaluate_scale_trail(
    pick: dict[str, Any],
    ltp: float | None = None,
    *,
    after_close: bool = False,
    trail_ratchet: dict[float, float] | None = None,
    profit_guard_trigger: float | None = None,
    use_pct_trail: bool = True,
) -> dict[str, Any]:
    plan = pick.get("exitPlan") if isinstance(pick.get("exitPlan"), dict) else None
    if not plan or plan.get("mode") != "SCALE_TRAIL":
        return {}
    if plan.get("scope") == "SWING" and trail_ratchet is None and profit_guard_trigger is None:
        trail_ratchet = SWING_TRAIL_RATCHET
        profit_guard_trigger = 1.0
    entry = float(pick.get("entryPrice") or plan.get("entry") or 0)
    risk = float(pick.get("riskPerShare") or plan.get("riskPerShare") or 0)
    direction = str(pick.get("direction") or plan.get("direction") or "LONG").upper()
    total_qty = int(pick.get("approxQty") or 0)
    ltp = float(pick.get("currentPrice") or pick.get("ltp") or entry) if ltp is None else float(ltp)
    if entry <= 0 or risk <= 0 or total_qty <= 0 or ltp <= 0:
        return {}

    prior = pick.get("exitState") if isinstance(pick.get("exitState"), dict) else {}
    if prior and not _exit_state_is_sane(pick, prior):
        # Fail closed on corrupted durable state. The path evaluator will
        # reconstruct economics from today's bounded high/low/mark instead.
        prior = {}
    legs_filled = [
        dict(x)
        for x in prior.get("legsFilled", [])
        if isinstance(x, dict)
        and (
            isinstance(x.get("r"), (int, float))
            or x.get("r") in {"INITIAL_SL", "TRAIL_SL", "EOD_SQUAREOFF"}
        )
    ]
    filled_rs = {float(x["r"]) for x in legs_filled if isinstance(x.get("r"), (int, float))}
    initial_stop = float(plan.get("initialStop") or pick.get("stopLoss") or _initial_stop(entry, risk, direction))
    if not _valid_stop(entry, initial_stop, direction):
        initial_stop = _initial_stop(entry, risk, direction)
    effective_stop = float(prior.get("effectiveStop") or initial_stop)
    if effective_stop != entry and not _valid_stop(entry, effective_stop, direction):
        # Trail may sit at BE or on the profit side (LONG stop > entry).
        profit_trail = (
            (direction != "SHORT" and effective_stop > entry)
            or (direction == "SHORT" and effective_stop < entry)
        )
        if not profit_trail:
            effective_stop = initial_stop

    for leg in plan.get("legs", []):
        r_mult, leg_qty, leg_px = float(leg.get("r") or 0), int(leg.get("qty") or 0), float(leg.get("price") or 0)
        if r_mult in filled_rs or leg_qty <= 0 or leg_px <= 0 or not _leg_crossed(leg_px, ltp, direction):
            continue
        legs_filled.append({"r": r_mult, "qty": leg_qty, "price": leg_px, "pnl": _mtm_pnl(direction, entry, leg_px, leg_qty)})
        filled_rs.add(r_mult)

    r_now = _r_reached(entry, risk, ltp, direction)
    peak_leg = max(filled_rs) if filled_rs else None
    try:
        prior_mfe = float(prior.get("mfeR")) if prior.get("mfeR") is not None else None
    except (TypeError, ValueError):
        prior_mfe = None
    # MFE is an excursion from entry.  A trade that never traded above entry
    # has zero favourable excursion, not a negative MFE.
    peak_r = max(0.0, r_now)
    for cand in (prior_mfe, peak_leg):
        if cand is not None:
            peak_r = max(peak_r, float(cand))
    effective_stop = _ratchet_stop(
        entry,
        risk,
        direction,
        effective_stop,
        peak_r,
        trail_ratchet=trail_ratchet,
        profit_guard_trigger=profit_guard_trigger,
        use_pct_trail=use_pct_trail,
    )

    booked_qty = sum(int(x.get("qty") or 0) for x in legs_filled)
    remaining = max(0, total_qty - booked_qty)
    realized = round(sum(float(x.get("pnl") or 0) for x in legs_filled), 2)
    trail_hit = False
    square_off = False

    guard_trigger = PROFIT_GUARD_TRIGGER_R if profit_guard_trigger is None else float(profit_guard_trigger)
    guard_active = bool(prior.get("profitGuardActive")) or peak_r + 1e-9 >= guard_trigger

    if peak_r + 1e-9 >= guard_trigger and remaining > 0 and trail_ratchet is None and profit_guard_trigger is None:
        # Quantity rounding (especially tiny positions) can leave less booked
        # profit than the nominal percentages imply. Protect 1R on the original
        # full quantity, not merely 1R on a small tranche. Gross, before costs.
        floor_px = entry + _sign(direction) * (risk * total_qty - realized) / remaining
        # Round toward profit so paise rounding cannot undercut the floor.
        floor_px = (math.floor(floor_px * 100 + 1e-8) if direction == "SHORT"
                    else math.ceil(floor_px * 100 - 1e-8)) / 100
        effective_stop = _tighter_stop(direction, effective_stop, floor_px)

    if remaining > 0 and _stop_hit(effective_stop, ltp, direction):
        px = effective_stop
        pnl = _mtm_pnl(direction, entry, px, remaining)
        stop_leg = "TRAIL_SL" if guard_active else "INITIAL_SL"
        legs_filled.append({"r": stop_leg, "qty": remaining, "price": px, "pnl": pnl})
        realized = round(realized + pnl, 2)
        remaining = 0
        trail_hit = True
    elif remaining > 0 and after_close:
        pnl = _mtm_pnl(direction, entry, ltp, remaining)
        legs_filled.append({"r": "EOD_SQUAREOFF", "qty": remaining, "price": round(ltp, 2), "pnl": pnl})
        realized = round(realized + pnl, 2)
        remaining = 0
        square_off = True

    unrealized = _mtm_pnl(direction, entry, ltp, remaining) if remaining > 0 else 0.0
    total_economic_pnl = round(realized + unrealized, 2)
    economic_r = _economic_r(total_economic_pnl, entry, risk, total_qty)
    path_r_now = round(r_now, 3)

    if trail_hit:
        label, hit = ("TRAIL STOP HIT", "sl") if guard_active else ("INITIAL STOP HIT", "sl")
    elif square_off:
        label, hit = "EOD SQUAREOFF", None
    elif remaining == 0:
        label, hit = "SCALE COMPLETE", "partial"
    elif legs_filled:
        max_leg = max((float(x["r"]) for x in legs_filled if isinstance(x.get("r"), (int, float))), default=0)
        label, hit = f"PARTIAL {max_leg:g}R", "partial"
    else:
        label, hit = "PENDING", None

    state = {
        "legsFilled": legs_filled,
        "remainingQty": remaining,
        "effectiveStop": round(effective_stop, 2),
        "realizedPnl": realized,
        "unrealizedPnl": unrealized,
        "economicPnl": total_economic_pnl,
        "rMultiple": economic_r,  # alias of economicR (Book headline R)
        "economicR": economic_r,
        "pathR": path_r_now,
        "mfeR": round(max(peak_r, float(prior.get("mfeR") or peak_r)), 3),
        "profitGuardActive": guard_active,
        "closed": trail_hit or square_off or remaining == 0,
        "mode": "SCALE_TRAIL",
        "initialStop": round(initial_stop, 2),
        "totalQty": total_qty,
        "riskPerShare": round(risk, 4),
    }
    return {
        "label": label,
        "detail": f"R {economic_r:+.2f} · trail SL {effective_stop:.2f} · rem {remaining}",
        "hitLevel": hit,
        "stopKind": "TRAIL" if trail_hit and guard_active else "INITIAL" if trail_hit else None,
        "ltp": round(ltp, 2),
        "pctChange": round((_sign(direction) * (ltp - entry)) / entry * 100, 2),
        "exitState": state,
        "remainingQty": remaining,
        "realizedPnl": realized,
        "unrealizedPnl": unrealized,
        "economicPnl": total_economic_pnl,
        "effectiveStop": round(effective_stop, 2),
        "rMultiple": economic_r,
        "economicR": economic_r,
        "pathR": path_r_now,
        "closed": state["closed"],
        "scaleTrail": True,
    }


def evaluate_scale_trail_path(
    pick: dict[str, Any],
    mark: float,
    day_high: float | None = None,
    day_low: float | None = None,
    *,
    after_close: bool = True,
    trail_ratchet: dict[float, float] | None = None,
    profit_guard_trigger: float | None = None,
    use_pct_trail: bool = True,
) -> dict[str, Any]:
    """Evaluate favourable excursion first, then adverse path against the ratcheted stop."""
    work = dict(pick)
    direction = str(work.get("direction") or "LONG").upper()
    entry = float(work.get("entryPrice") or 0)
    hi = float(day_high) if day_high is not None else float(mark)
    lo = float(day_low) if day_low is not None else float(mark)
    fav = hi if direction == "LONG" else lo
    adv = lo if direction == "LONG" else hi
    fav = _plausible_trade_price(entry, fav) or float(mark)
    adv = _plausible_trade_price(entry, adv) or float(mark)
    first = evaluate_scale_trail(
        work,
        fav,
        after_close=False,
        trail_ratchet=trail_ratchet,
        profit_guard_trigger=profit_guard_trigger,
        use_pct_trail=use_pct_trail,
    )
    if first.get("exitState"):
        work["exitState"] = first["exitState"]
    state = work.get("exitState") or {}
    stop = float(state.get("effectiveStop") or work.get("stopLoss") or 0)
    stop_crossed = stop > 0 and ((direction == "LONG" and adv <= stop) or (direction == "SHORT" and adv >= stop))
    eval_px = stop if stop_crossed else float(mark)
    return evaluate_scale_trail(
        work,
        eval_px,
        after_close=after_close,
        trail_ratchet=trail_ratchet,
        profit_guard_trigger=profit_guard_trigger,
        use_pct_trail=use_pct_trail,
    )


def evaluate_scale_trail_candles(
    pick: dict[str, Any],
    ohlc_bars: list[tuple[float, float, float]],
    *,
    after_close: bool = True,
    trail_ratchet: dict[float, float] | None = None,
    profit_guard_trigger: float | None = None,
    use_pct_trail: bool = True,
) -> dict[str, Any]:
    """Walk 1-minute bars in order. Intra-bar: adverse extreme before MFE.

    Bars are (high, low, close) already sliced to post-entry. A later spike
    cannot book profit after an earlier 0.5% stop.
    """
    work = dict(pick)
    direction = str(work.get("direction") or "LONG").upper()
    entry = float(work.get("entryPrice") or 0)
    last_ev: dict[str, Any] = {}
    last_close: float | None = None
    kwargs = {
        "after_close": False,
        "trail_ratchet": trail_ratchet,
        "profit_guard_trigger": profit_guard_trigger,
        "use_pct_trail": use_pct_trail,
    }
    for high, low, close in ohlc_bars or []:
        hi = _plausible_trade_price(entry, high)
        lo = _plausible_trade_price(entry, low)
        cl = _plausible_trade_price(entry, close)
        if cl is None:
            continue
        last_close = cl
        adv = (lo if lo is not None else cl) if direction != "SHORT" else (hi if hi is not None else cl)
        fav = (hi if hi is not None else cl) if direction != "SHORT" else (lo if lo is not None else cl)
        adv_ev = evaluate_scale_trail(work, adv, **kwargs)
        if adv_ev.get("closed"):
            return adv_ev
        if adv_ev.get("exitState"):
            work["exitState"] = adv_ev["exitState"]
        fav_ev = evaluate_scale_trail(work, fav, **kwargs)
        if fav_ev.get("exitState"):
            work["exitState"] = fav_ev["exitState"]
        last_ev = fav_ev
        if fav_ev.get("closed"):
            return fav_ev
        stop = float((work.get("exitState") or {}).get("effectiveStop") or work.get("stopLoss") or 0)
        if stop > 0 and _stop_hit(stop, adv, direction):
            hit = evaluate_scale_trail(work, stop, **kwargs)
            if hit:
                return hit
    if last_close is None:
        return last_ev
    return evaluate_scale_trail(
        work,
        last_close,
        after_close=after_close,
        trail_ratchet=trail_ratchet,
        profit_guard_trigger=profit_guard_trigger,
        use_pct_trail=use_pct_trail,
    )


def blended_pnl_from_state(
    pick: dict[str, Any],
    mark: float,
    *,
    after_close: bool = True,
    day_high: float | None = None,
    day_low: float | None = None,
) -> tuple[float, float, dict[str, Any]]:
    result = (
        evaluate_scale_trail_path(pick, mark, day_high, day_low, after_close=after_close)
        if (day_high is not None or day_low is not None)
        else evaluate_scale_trail(pick, mark, after_close=after_close)
    )
    if not result:
        return 0.0, mark, {}
    total = round(float(result.get("economicPnl") if result.get("economicPnl") is not None else float(result.get("realizedPnl") or 0) + float(result.get("unrealizedPnl") or 0)), 2)
    filled = (result.get("exitState") or {}).get("legsFilled") or []
    qty = int(pick.get("approxQty") or 0)
    if filled and qty > 0:
        notional = sum(float(x.get("price") or 0) * int(x.get("qty") or 0) for x in filled)
        booked = sum(int(x.get("qty") or 0) for x in filled)
        rem = int((result.get("exitState") or {}).get("remainingQty") or 0)
        if rem > 0:
            notional += float(mark) * rem
            booked += rem
        avg = round(notional / booked, 2) if booked else float(mark)
    else:
        avg = float(mark)
    return total, avg, result


def format_scale_progress(
    exit_plan: dict[str, Any] | None,
    exit_state: dict[str, Any] | None,
    *,
    r_multiple: float | None = None,
) -> str | None:
    if not isinstance(exit_plan, dict) or exit_plan.get("mode") != "SCALE_TRAIL":
        return None
    state = exit_state if isinstance(exit_state, dict) else {}
    filled = {float(x.get("r")) for x in state.get("legsFilled", []) if isinstance(x, dict) and isinstance(x.get("r"), (int, float))}
    mfe = float(state.get("mfeR") or 0)
    parts = [f"{r:g}R{'+' if (r in filled or mfe + 1e-9 >= r) else '.'}" for r in TRAIL_RATCHET]
    rem = state.get("remainingQty")
    eff = state.get("effectiveStop")
    parts.append(f"MFE {mfe:+.2f}R")
    if r_multiple is not None:
        parts.append(f"R {float(r_multiple):+.2f}")
    rem_qty = int(rem) if rem is not None else None
    if rem_qty is not None:
        parts.append(f"rem {rem_qty}")
    if eff is not None:
        parts.append(f"trail SL {float(eff):.2f}")
    return " ".join(parts)


def _fnum(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _quote_high_low(quotes: dict[str, Any] | None, symbol: str) -> tuple[float | None, float | None]:
    if not isinstance(quotes, dict) or not symbol:
        return None, None
    quote = quotes.get(symbol) or quotes.get(symbol.upper())
    if not isinstance(quote, dict):
        return None, None
    return _fnum(quote.get("high") or quote.get("dayHigh")), _fnum(quote.get("low") or quote.get("dayLow"))


def _row_path_marks(row: dict[str, Any], quotes: dict[str, Any] | None) -> tuple[float | None, float | None, float | None]:
    symbol = str(row.get("symbol") or "").upper()
    evidence = row.get("entryEvidence") if isinstance(row.get("entryEvidence"), dict) else {}
    quote_high, quote_low = _quote_high_low(quotes, symbol)
    entry = _fnum(row.get("entryPrice")) or 0.0
    def _first_plausible(*values: Any) -> float | None:
        for value in values:
            price = _plausible_trade_price(entry, value)
            if price is not None:
                return price
        return None

    mark = _first_plausible(
        row.get("ltp"), row.get("currentPrice"), row.get("closeMark"),
        row.get("exitPrice"), evidence.get("ltp"), entry,
    )
    high = _first_plausible(
        row.get("sessionHigh"), row.get("dayHigh"), evidence.get("postEntryHigh"), quote_high, mark,
    )
    low = _first_plausible(
        row.get("sessionLow"), row.get("dayLow"), evidence.get("postEntryLow"), quote_low, mark,
    )
    if mark is None:
        return None, None, None
    if high is None:
        high = mark
    if low is None:
        low = mark
    # Do not invent a favourable extreme from stored mfeR — that is how
    # 80R ghost trails (GRSE 3735, ZEEL 143) appear against a sane session high.
    if high < low:
        high, low = low, high
    return mark, high, low
