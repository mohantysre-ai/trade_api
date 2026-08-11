"""Quant-desk EOD exit policy.

Selection remains deterministic and outside this module. This module only owns
execution truth, canonical P&L classification, and the R-ratchet presentation.
"""
from __future__ import annotations

from typing import Any

R_RATCHET: tuple[tuple[float, float], ...] = (
    (0.25, 0.00),
    (0.50, 0.25),
    (0.75, 0.50),
    (1.00, 0.75),
    (1.25, 1.00),
    (1.50, 1.25),
    (2.00, 1.50),
    (3.00, 2.25),
    (4.00, 3.25),
    (5.00, 4.25),
)

SCALE_LEGS: tuple[tuple[float, float], ...] = (
    (1.00, 0.20),
    (1.50, 0.20),
    (2.00, 0.20),
)
RUNNER_FRACTION = 0.40


def locked_r_for_mfe(mfe_r: float) -> float:
    lock = -1.0
    for trigger, stop_r in R_RATCHET:
        if mfe_r + 1e-9 >= trigger:
            lock = max(lock, stop_r)
        else:
            break
    return lock


def trail_stop_price(entry: float, risk_per_share: float, direction: str, lock_r: float) -> float:
    sign = -1.0 if str(direction).upper() == "SHORT" else 1.0
    return round(entry + sign * risk_per_share * lock_r, 2)


def execution_truth(*, triggered: bool | None, realized_pnl: float | None) -> str:
    """Book P&L is authoritative: any realized non-zero P&L means executed."""
    if realized_pnl is not None and abs(float(realized_pnl)) > 1e-9:
        return "TRIGGERED"
    if triggered is False:
        return "NOT_TRIGGERED"
    if triggered is True:
        return "TRIGGERED"
    return "UNKNOWN"


def canonical_pnl(*, execution_status: str, realized_pnl: float | None) -> float:
    if str(execution_status).upper() == "NOT_TRIGGERED":
        return 0.0
    return round(float(realized_pnl or 0.0), 2)


def outcome_bucket(*, execution_status: str, pnl: float) -> str:
    if execution_status == "NOT_TRIGGERED":
        return "SKIPPED"
    if pnl > 0:
        return "WIN"
    if pnl < 0:
        return "LOSS"
    return "FLAT"


def desk_exit_label(exit_reason: str | None, pnl: float) -> str:
    reason = str(exit_reason or "EOD_SQUAREOFF").upper()
    if reason in {"TRAIL_SL", "TRAIL_SL_HIT"}:
        return "TRAIL_STOP"
    if reason == "SL_HIT":
        return "INITIAL_SL"
    if reason in {"EOD", "EOD_SQUAREOFF"}:
        return "EOD_SQUAREOFF"
    if reason.startswith("PARTIAL"):
        return "PARTIAL_SCALE"
    return "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"


def desk_progress(mfe_r: float, current_r: float, effective_stop_r: float) -> str:
    parts = [f"{trigger:g}R{'+' if mfe_r + 1e-9 >= trigger else '.'}" for trigger, _ in R_RATCHET]
    parts.extend((f"MFE {mfe_r:+.2f}R", f"R {current_r:+.2f}", f"SL {effective_stop_r:+.2f}R"))
    return " ".join(parts)


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def infer_mfe_r(
    *,
    exit_state: dict[str, Any] | None = None,
    current_r: float | None = None,
    entry: float | None = None,
    risk_per_share: float | None = None,
    direction: str = "LONG",
    day_high: float | None = None,
    day_low: float | None = None,
) -> float:
    st = exit_state if isinstance(exit_state, dict) else {}
    for key in ("mfeR", "peakR", "maxR"):
        raw = _f(st.get(key))
        if raw is not None:
            return raw
    filled_rs = [
        float(x["r"])
        for x in (st.get("legsFilled") or [])
        if isinstance(x, dict) and isinstance(x.get("r"), (int, float))
    ]
    peak = max(filled_rs) if filled_rs else None
    cur = _f(current_r)
    if peak is not None:
        return max(peak, cur if cur is not None else peak)
    entry_f, risk, hi, lo = _f(entry), _f(risk_per_share), _f(day_high), _f(day_low)
    if entry_f and risk and risk > 0 and hi is not None and lo is not None:
        sign = -1.0 if str(direction).upper() == "SHORT" else 1.0
        fav = hi if sign > 0 else lo
        path_mfe = sign * (fav - entry_f) / risk
        return max(cur, path_mfe) if cur is not None else path_mfe
    return cur if cur is not None else 0.0


def infer_stop_r(
    *,
    exit_state: dict[str, Any] | None = None,
    entry: float | None = None,
    risk_per_share: float | None = None,
    direction: str = "LONG",
    effective_stop: float | None = None,
    mfe_r: float | None = None,
) -> float:
    st = exit_state if isinstance(exit_state, dict) else {}
    for key in ("effectiveStopR", "lockR", "trailStopR"):
        raw = _f(st.get(key))
        if raw is not None:
            return raw
    entry_f, risk, stop = _f(entry), _f(risk_per_share), _f(effective_stop if effective_stop is not None else st.get("effectiveStop"))
    if entry_f is not None and risk and risk > 0 and stop is not None:
        sign = -1.0 if str(direction).upper() == "SHORT" else 1.0
        return (stop - entry_f) / (sign * risk)
    return locked_r_for_mfe(float(mfe_r)) if mfe_r is not None else -1.0


def classify_desk_outcome(
    *,
    triggered: bool | None,
    realized_pnl: float | None,
    exit_reason: str | None,
    exit_state: dict[str, Any] | None = None,
    entry: float | None = None,
    risk_per_share: float | None = None,
    direction: str = "LONG",
    effective_stop: float | None = None,
    current_r: float | None = None,
    day_high: float | None = None,
    day_low: float | None = None,
    mae_pct: float | None = None,
    mfe_pct: float | None = None,
) -> dict[str, Any]:
    exec_status = execution_truth(triggered=triggered, realized_pnl=realized_pnl)
    pnl = canonical_pnl(execution_status=exec_status, realized_pnl=realized_pnl)
    bucket = outcome_bucket(execution_status=exec_status, pnl=pnl)

    if exec_status == "NOT_TRIGGERED":
        desk_label = "SKIPPED"
        r_now = mfe_r = stop_r = None
        progress = None
    else:
        desk_label = desk_exit_label(exit_reason, pnl)
        st = exit_state if isinstance(exit_state, dict) else {}
        r_now = _f(current_r)
        if r_now is None:
            r_now = _f(st.get("rMultiple"))
        if r_now is None:
            r_now = 0.0
        mfe_r = infer_mfe_r(
            exit_state=st,
            current_r=r_now,
            entry=entry,
            risk_per_share=risk_per_share,
            direction=direction,
            day_high=day_high,
            day_low=day_low,
        )
        stop_r = infer_stop_r(
            exit_state=st,
            entry=entry,
            risk_per_share=risk_per_share,
            direction=direction,
            effective_stop=effective_stop,
            mfe_r=mfe_r,
        )
        progress = desk_progress(float(mfe_r), float(r_now), float(stop_r))

    return {
        "executionStatus": exec_status,
        "pnl": pnl,
        "outcomeBucket": bucket,
        "deskExitLabel": desk_label,
        "exitReason": str(exit_reason or ("NOT_TRIGGERED" if exec_status == "NOT_TRIGGERED" else "EOD_SQUAREOFF")),
        "deskProgress": progress,
        "rMultiple": None if r_now is None else round(float(r_now), 3),
        "mfeR": None if mfe_r is None else round(float(mfe_r), 3),
        "effectiveStopR": None if stop_r is None else round(float(stop_r), 3),
        "maePct": mae_pct,
        "mfePct": mfe_pct,
        "chain": ["execution_truth", "canonical_pnl", "r_ladder", "mfe_mae", "desk_exit_label", "outcome_bucket"],
    }
