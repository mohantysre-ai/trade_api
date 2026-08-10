"""Deterministic institutional scale-out + R-ratchet trailing exit plan."""
from __future__ import annotations

from typing import Any

# Early scale is deliberately light so trend days retain a 40% runner.
SCALE_LEGS: list[tuple[float, float]] = [(0.50, 0.20), (1.00, 0.20), (1.50, 0.20)]
RUNNER_FRAC = 0.40

# Highest favourable R reached -> minimum locked R on remaining quantity.
# Stop is monotonic: it never moves back toward the original hard SL.
TRAIL_RATCHET: dict[float, float] = {
    0.25: -0.25,
    0.50: 0.00,
    0.75: 0.25,
    1.00: 0.50,
    1.25: 0.75,
    1.50: 1.00,
    2.00: 1.25,
    3.00: 2.00,
    4.00: 3.00,
    5.00: 4.00,
}

PROFIT_GUARD_TRIGGER_R = 0.25
PROFIT_GUARD_LOCK_R = -0.25
REF_T1_R = 1.5
REF_T2_R = 3.0


def allocate_leg_qty(total_qty: int, fracs: list[float] | None = None) -> list[int]:
    n = int(total_qty or 0)
    if n <= 0:
        return []
    parts = list(fracs) if fracs is not None else [p for _, p in SCALE_LEGS] + [RUNNER_FRAC]
    if n < 4:
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


def build_exit_plan(entry: float, risk_per_share: float, direction: str, qty: int, *, initial_stop: float | None = None) -> dict[str, Any]:
    entry, risk, qty = float(entry or 0), float(risk_per_share or 0), int(qty or 0)
    direction = str(direction or "LONG").upper()
    if entry <= 0 or risk <= 0:
        return {"mode": "SCALE_TRAIL", "legs": [], "runnerQty": 0, "initialStop": initial_stop, "target1": None, "target2": None, "notes": ["invalid_entry_or_risk"]}
    lots = allocate_leg_qty(qty)
    legs: list[dict[str, Any]] = []
    for i, (r_mult, pct) in enumerate(SCALE_LEGS):
        legs.append({"r": r_mult, "qtyPct": pct, "qty": lots[i], "price": _target_price(entry, risk, r_mult, direction), "trailStopAfter": TRAIL_RATCHET[r_mult]})
    hard_sl = round(float(initial_stop), 2) if initial_stop is not None else _initial_stop(entry, risk, direction)
    return {
        "mode": "SCALE_TRAIL", "direction": direction, "entry": round(entry, 2), "riskPerShare": round(risk, 2),
        "initialStop": hard_sl, "legs": legs, "runnerQty": lots[-1] if lots else 0, "runnerFrac": RUNNER_FRAC,
        "trailRatchet": {str(k): v for k, v in TRAIL_RATCHET.items()},
        "target1": _target_price(entry, risk, REF_T1_R, direction), "target2": _target_price(entry, risk, REF_T2_R, direction),
        "notes": ["40pct_runner", "monotonic_r_ratchet", "no_stop_loosen"],
    }


def attach_exit_plan(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    entry = float(out.get("entryPrice") or 0)
    risk = float(out.get("riskPerShare") or 0)
    if risk <= 0:
        sl = float(out.get("stopLoss") or 0)
        if entry > 0 and sl > 0:
            risk = abs(entry - sl)
    plan = build_exit_plan(entry, risk, str(out.get("direction") or "LONG"), int(out.get("approxQty") or 0), initial_stop=float(out["stopLoss"]) if out.get("stopLoss") is not None else None)
    out["exitPlan"] = plan
    if plan.get("target1") is not None: out["target1"] = plan["target1"]
    if plan.get("target2") is not None: out["target2"] = plan["target2"]
    if plan.get("initialStop") is not None and not out.get("stopLoss"): out["stopLoss"] = plan["initialStop"]
    return out


def _r_reached(entry: float, risk: float, ltp: float, direction: str) -> float:
    return _sign(direction) * (ltp - entry) / risk if entry > 0 and risk > 0 else 0.0


def _leg_crossed(price: float, ltp: float, direction: str) -> bool:
    return ltp <= price if direction == "SHORT" else ltp >= price


def _stop_hit(stop: float, ltp: float, direction: str) -> bool:
    return ltp >= stop if direction == "SHORT" else ltp <= stop


def _mtm_pnl(direction: str, entry: float, exit_px: float, qty: int) -> float:
    return round(_sign(direction) * (exit_px - entry) * qty, 2)


def _ratchet_stop(entry: float, risk: float, direction: str, current: float, r_now: float) -> float:
    stop = current
    for trigger, lock_r in TRAIL_RATCHET.items():
        if r_now + 1e-9 < trigger:
            break
        new = _stop_at_r(entry, risk, lock_r, direction)
        stop = min(stop, new) if direction == "SHORT" else max(stop, new)
    return round(stop, 2)


def evaluate_scale_trail(pick: dict[str, Any], ltp: float | None = None, *, after_close: bool = False) -> dict[str, Any]:
    plan = pick.get("exitPlan") if isinstance(pick.get("exitPlan"), dict) else None
    if not plan or plan.get("mode") != "SCALE_TRAIL": return {}
    entry = float(pick.get("entryPrice") or plan.get("entry") or 0)
    risk = float(pick.get("riskPerShare") or plan.get("riskPerShare") or 0)
    direction = str(pick.get("direction") or plan.get("direction") or "LONG").upper()
    total_qty = int(pick.get("approxQty") or 0)
    ltp = float(pick.get("currentPrice") or pick.get("ltp") or entry) if ltp is None else float(ltp)
    if entry <= 0 or risk <= 0 or total_qty <= 0 or ltp <= 0: return {}

    prior = pick.get("exitState") if isinstance(pick.get("exitState"), dict) else {}
    legs_filled = [dict(x) for x in prior.get("legsFilled", []) if isinstance(x, dict) and (isinstance(x.get("r"), (int, float)) or x.get("r") in {"TRAIL_SL", "EOD_SQUAREOFF"})]
    filled_rs = {float(x["r"]) for x in legs_filled if isinstance(x.get("r"), (int, float))}
    initial_stop = float(plan.get("initialStop") or pick.get("stopLoss") or _initial_stop(entry, risk, direction))
    effective_stop = float(prior.get("effectiveStop") or initial_stop)

    # Fill scale legs only once.
    for leg in plan.get("legs", []):
        r_mult, leg_qty, leg_px = float(leg.get("r") or 0), int(leg.get("qty") or 0), float(leg.get("price") or 0)
        if r_mult in filled_rs or leg_qty <= 0 or leg_px <= 0 or not _leg_crossed(leg_px, ltp, direction): continue
        legs_filled.append({"r": r_mult, "qty": leg_qty, "price": leg_px, "pnl": _mtm_pnl(direction, entry, leg_px, leg_qty)})
        filled_rs.add(r_mult)

    r_now = _r_reached(entry, risk, ltp, direction)
    effective_stop = _ratchet_stop(entry, risk, direction, effective_stop, r_now)
    booked_qty = sum(int(x.get("qty") or 0) for x in legs_filled)
    remaining = max(0, total_qty - booked_qty)
    realized = round(sum(float(x.get("pnl") or 0) for x in legs_filled), 2)
    trail_hit = False
    square_off = False

    if remaining > 0 and _stop_hit(effective_stop, ltp, direction):
        px = effective_stop
        pnl = _mtm_pnl(direction, entry, px, remaining)
        legs_filled.append({"r": "TRAIL_SL", "qty": remaining, "price": px, "pnl": pnl})
        realized = round(realized + pnl, 2); remaining = 0; trail_hit = True
    elif remaining > 0 and after_close:
        pnl = _mtm_pnl(direction, entry, ltp, remaining)
        legs_filled.append({"r": "EOD_SQUAREOFF", "qty": remaining, "price": round(ltp, 2), "pnl": pnl})
        realized = round(realized + pnl, 2); remaining = 0; square_off = True

    unrealized = _mtm_pnl(direction, entry, ltp, remaining) if remaining > 0 else 0.0
    if trail_hit: label, hit = "TRAIL STOP HIT", "sl"
    elif square_off: label, hit = "EOD SQUAREOFF", None
    elif remaining == 0: label, hit = "SCALE COMPLETE", "partial"
    elif legs_filled: label, hit = f"PARTIAL {max((float(x['r']) for x in legs_filled if isinstance(x.get('r'), (int, float))), default=0):g}R", "partial"
    else: label, hit = "PENDING", None

    state = {"legsFilled": legs_filled, "remainingQty": remaining, "effectiveStop": round(effective_stop, 2), "realizedPnl": realized, "unrealizedPnl": unrealized, "rMultiple": round(r_now, 3), "mfeR": max(r_now, float(prior.get("mfeR") or r_now)), "closed": trail_hit or square_off or remaining == 0, "mode": "SCALE_TRAIL"}
    return {"label": label, "detail": f"R {r_now:+.2f} · trail SL {effective_stop:.2f} · rem {remaining}", "hitLevel": hit, "ltp": round(ltp, 2), "pctChange": round((ltp-entry)/entry*100, 2), "exitState": state, "remainingQty": remaining, "realizedPnl": realized, "unrealizedPnl": unrealized, "effectiveStop": round(effective_stop, 2), "rMultiple": round(r_now, 3), "closed": state["closed"], "scaleTrail": True}


def evaluate_scale_trail_path(pick: dict[str, Any], mark: float, day_high: float | None = None, day_low: float | None = None, *, after_close: bool = True) -> dict[str, Any]:
    """Evaluate favourable excursion first, then adverse path against the ratcheted stop."""
    work = dict(pick)
    direction = str(work.get("direction") or "LONG").upper()
    hi = float(day_high) if day_high is not None else float(mark)
    lo = float(day_low) if day_low is not None else float(mark)
    fav = hi if direction == "LONG" else lo
    adv = lo if direction == "LONG" else hi
    first = evaluate_scale_trail(work, fav, after_close=False)
    if first.get("exitState"): work["exitState"] = first["exitState"]
    state = work.get("exitState") or {}
    stop = float(state.get("effectiveStop") or work.get("stopLoss") or 0)
    eval_px = stop if stop > 0 and ((direction == "LONG" and adv <= stop) or (direction == "SHORT" and adv >= stop)) else float(mark)
    return evaluate_scale_trail(work, eval_px, after_close=after_close)


def blended_pnl_from_state(pick: dict[str, Any], mark: float, *, after_close: bool = True, day_high: float | None = None, day_low: float | None = None) -> tuple[float, float, dict[str, Any]]:
    result = evaluate_scale_trail_path(pick, mark, day_high, day_low, after_close=after_close) if (day_high is not None or day_low is not None) else evaluate_scale_trail(pick, mark, after_close=after_close)
    if not result: return 0.0, mark, {}
    total = round(float(result.get("realizedPnl") or 0) + float(result.get("unrealizedPnl") or 0), 2)
    filled = (result.get("exitState") or {}).get("legsFilled") or []
    qty = int(pick.get("approxQty") or 0)
    if filled and qty > 0:
        notional = sum(float(x.get("price") or 0) * int(x.get("qty") or 0) for x in filled)
        booked = sum(int(x.get("qty") or 0) for x in filled)
        rem = int((result.get("exitState") or {}).get("remainingQty") or 0)
        if rem > 0: notional += float(mark) * rem; booked += rem
        avg = round(notional / booked, 2) if booked else float(mark)
    else: avg = float(mark)
    return total, avg, result


def format_scale_progress(exit_plan: dict[str, Any] | None, exit_state: dict[str, Any] | None, *, r_multiple: float | None = None) -> str | None:
    if not isinstance(exit_plan, dict) or exit_plan.get("mode") != "SCALE_TRAIL": return None
    state = exit_state if isinstance(exit_state, dict) else {}
    filled = {float(x.get("r")) for x in state.get("legsFilled", []) if isinstance(x, dict) and isinstance(x.get("r"), (int, float))}
    mfe = float(state.get("mfeR") or r_multiple or 0)
    parts = [f"{r:g}R{'+' if (r in filled or mfe + 1e-9 >= r) else '.'}" for r, _ in TRAIL_RATCHET.items()]
    rem = state.get("remainingQty")
    eff = state.get("effectiveStop")
    parts.append(f"MFE {mfe:+.2f}R")
    if r_multiple is not None: parts.append(f"R {float(r_multiple):+.2f}")
    if rem is not None: parts.append(f"rem {int(rem)}")
    if eff is not None: parts.append(f"trail SL {float(eff):.2f}")
    return " ".join(parts)
