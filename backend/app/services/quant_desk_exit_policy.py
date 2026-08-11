"""Quant-desk EOD exit policy.

Selection remains deterministic and outside this module. This module owns
execution truth, canonical P&L classification, Economic vs Path R, and
forensic taxonomy. Trading selection / ratchet economics live elsewhere.
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

OUTCOME_SCHEMA_VERSION = 1


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
    if reason in {"NOT_TRIGGERED", "NO_MARK"}:
        return "SKIPPED"
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


def economic_r(*, pnl: float, risk_per_share: float | None, qty: int | None) -> float | None:
    """Book economic R = Book_PnL / Initial_Risk_Capital."""
    risk = _f(risk_per_share)
    q = int(qty or 0)
    if risk is None or risk <= 0 or q <= 0:
        return None
    return round(float(pnl) / (risk * q), 3)


def path_r(
    *,
    entry: float | None,
    exit_price: float | None,
    risk_per_share: float | None,
    direction: str = "LONG",
) -> float | None:
    """Path R = signed price move / initial risk (ignore quantity / scale fills)."""
    entry_f, exit_f, risk = _f(entry), _f(exit_price), _f(risk_per_share)
    if entry_f is None or exit_f is None or risk is None or risk <= 0:
        return None
    sign = -1.0 if str(direction).upper() == "SHORT" else 1.0
    return round(sign * (exit_f - entry_f) / risk, 3)


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


def infer_mae_r(
    *,
    exit_state: dict[str, Any] | None = None,
    current_r: float | None = None,
    entry: float | None = None,
    risk_per_share: float | None = None,
    direction: str = "LONG",
    day_high: float | None = None,
    day_low: float | None = None,
) -> float | None:
    """Peak adverse excursion in R (negative or zero for longs)."""
    st = exit_state if isinstance(exit_state, dict) else {}
    for key in ("maeR", "minR"):
        raw = _f(st.get(key))
        if raw is not None:
            return raw
    entry_f, risk, hi, lo = _f(entry), _f(risk_per_share), _f(day_high), _f(day_low)
    cur = _f(current_r)
    candidates: list[float] = []
    if cur is not None:
        candidates.append(cur)
    if entry_f and risk and risk > 0 and hi is not None and lo is not None:
        sign = -1.0 if str(direction).upper() == "SHORT" else 1.0
        adv = lo if sign > 0 else hi
        candidates.append(sign * (adv - entry_f) / risk)
    if not candidates:
        return None
    return round(min(candidates), 3)


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
    entry_f, risk, stop = _f(entry), _f(risk_per_share), _f(
        effective_stop if effective_stop is not None else st.get("effectiveStop")
    )
    if entry_f is not None and risk and risk > 0 and stop is not None:
        sign = -1.0 if str(direction).upper() == "SHORT" else 1.0
        return (stop - entry_f) / (sign * risk)
    return locked_r_for_mfe(float(mfe_r)) if mfe_r is not None else -1.0


def classify_taxonomy(
    *,
    execution_status: str,
    exit_reason: str | None,
    pnl: float,
    mfe_r: float | None,
    stop_utilization: float | None = None,
    economic_r: float | None = None,
    gap_to_t2_pct: float | None = None,
    trigger_source: str | None = None,
) -> tuple[str, list[str]]:
    """Forensic rootCause — never sets outcomeBucket. First match wins."""
    status = str(execution_status or "").upper()
    reason = str(exit_reason or "").upper()
    mfe = float(mfe_r) if mfe_r is not None else None
    factors: list[str] = []

    if status == "NOT_TRIGGERED" or reason == "NOT_TRIGGERED":
        src = str(trigger_source or "none").upper()
        return "ENTRY_NEVER_CROSSED", ["NOT_TRIGGERED", "SKIP_PNL", f"TRIGGER_SRC_{src}"]

    if status == "UNKNOWN" or reason == "NO_MARK":
        return "MISSING_CLOSE_MARK", ["NO_MARK", "SKIP_PNL"]

    # HINDZINC-style: never favourable → ENTRY_FAILURE before STALL/ADVERSE
    if mfe is not None and mfe < 0.10 and pnl <= 0:
        factors = ["NO_FAVOURABLE_EXCURSION", "ADVERSE_FROM_ENTRY"]
        if stop_utilization is not None and stop_utilization >= 0.9:
            factors.append("FULL_STOP_TRAVERSAL")
        if reason == "SL_HIT":
            factors.append("STOP_HIT")
        return "ENTRY_FAILURE", factors

    if reason == "SL_HIT":
        factors = ["STOP_HIT"]
        if mfe is not None and 0.10 <= mfe < 1.0:
            factors.append("PARTIAL_FAVOURABLE_MOVE")
            return "FAILED_FOLLOWTHROUGH", factors
        if mfe is not None and mfe >= 1.0:
            factors.append("GAVE_BACK_>=1R")
            return "GOOD_ENTRY_BAD_EXIT", factors
        if stop_utilization is not None and stop_utilization >= 0.9:
            factors.extend(["FULL_STOP_TRAVERSAL", "IMMEDIATE_STOP"])
            return "ADVERSE", factors
        factors.append("STOP_BEFORE_FOLLOWTHROUGH")
        return "ADVERSE", factors

    if reason in {"TRAIL_SL", "TRAIL_SL_HIT"}:
        factors = ["TRAIL_STOP_HIT"]
        if pnl > 0:
            factors.append("TRAIL_LOCKED_GAINS")
            return "TRAIL_CAPTURED", factors
        factors.append("GAVE_BACK")
        return "GOOD_ENTRY_BAD_EXIT", factors

    if reason in {"EOD", "EOD_SQUAREOFF", "OPEN"}:
        factors = ["TARGET_NOT_REACHED", "EOD_FORCED_EXIT"]
        if mfe is not None and mfe >= 1.0 and pnl <= 0:
            factors.append("GAVE_BACK")
            return "GOOD_ENTRY_BAD_EXIT", factors
        if pnl > 0:
            factors.append("POSITIVE_EOD_SQUAREOFF")
            return "PARTIAL_FOLLOWTHROUGH", factors
        if mfe is not None and mfe < 0.25 and pnl <= 0:
            factors.append("NEGATIVE_OR_FLAT_EOD")
            factors.append("NO_FOLLOWTHROUGH")
            return "STALL", factors
        if mfe is not None and mfe >= 0.25 and pnl <= 0:
            factors.append("INITIAL_MOVE_FADED")
            return "FAILED_BREAKOUT", factors
        factors.append("NEGATIVE_OR_FLAT_EOD")
        return "STALL", factors

    if reason.startswith("PARTIAL"):
        factors = ["SCALE_LEGS_FILLED"]
        if pnl > 0:
            factors.append("POSITIVE_SCALE_BOOK")
            return "PARTIAL_FOLLOWTHROUGH", factors
        factors.append("NEGATIVE_OR_FLAT_SCALE")
        return "STALL", factors

    if reason == "T2_HIT":
        factors = ["TARGET_REACHED", "T2_HIT"]
        if economic_r is not None and economic_r >= 2.0:
            factors.append("STRONG_R")
        return "GOOD_TREND", factors

    if reason == "T1_HIT":
        factors = ["TARGET_REACHED", "T1_HIT"]
        if gap_to_t2_pct is not None and gap_to_t2_pct > 0:
            factors.append("T2_NOT_REACHED")
        return "GOOD_TREND", factors

    return "UNKNOWN", []


def build_trade_outcome(
    *,
    triggered: bool | None,
    realized_pnl: float | None,
    exit_reason: str | None,
    exit_state: dict[str, Any] | None = None,
    entry: float | None = None,
    exit_price: float | None = None,
    risk_per_share: float | None = None,
    qty: int | None = None,
    direction: str = "LONG",
    effective_stop: float | None = None,
    current_r: float | None = None,
    day_high: float | None = None,
    day_low: float | None = None,
    mae_pct: float | None = None,
    mfe_pct: float | None = None,
    stop_utilization: float | None = None,
    gap_to_t2_pct: float | None = None,
    trigger_source: str | None = None,
    lineage: dict[str, Any] | None = None,
    economic_r_hint: float | None = None,
    path_r_hint: float | None = None,
) -> dict[str, Any]:
    """Single canonical TradeOutcome. All EOD surfaces must derive from this."""
    exec_status = execution_truth(triggered=triggered, realized_pnl=realized_pnl)
    pnl = canonical_pnl(execution_status=exec_status, realized_pnl=realized_pnl)
    bucket = outcome_bucket(execution_status=exec_status, pnl=pnl)
    reason = str(exit_reason or ("NOT_TRIGGERED" if exec_status == "NOT_TRIGGERED" else "EOD_SQUAREOFF"))

    st = exit_state if isinstance(exit_state, dict) else {}
    risk = _f(risk_per_share) if risk_per_share is not None else _f(st.get("riskPerShare"))
    q = int(qty if qty is not None else (st.get("totalQty") or 0) or 0)

    if exec_status == "NOT_TRIGGERED":
        root, factors = classify_taxonomy(
            execution_status=exec_status,
            exit_reason=reason,
            pnl=pnl,
            mfe_r=None,
            trigger_source=trigger_source,
        )
        return {
            "executionStatus": exec_status,
            "pnl": pnl,
            "outcomeBucket": "SKIPPED",
            "deskExitLabel": "SKIPPED",
            "exitReason": reason,
            "deskProgress": None,
            "rMultiple": None,
            "economicR": None,
            "pathR": None,
            "mfeR": None,
            "maeR": None,
            "effectiveStopR": None,
            "maePct": mae_pct,
            "mfePct": mfe_pct,
            "rootCause": root,
            "factors": factors,
            "isHit": False,
            "isMiss": False,
            "isSkip": True,
            "lineage": lineage,
            "outcomeSchemaVersion": OUTCOME_SCHEMA_VERSION,
            "chain": [
                "execution_truth",
                "canonical_pnl",
                "economic_r",
                "path_r",
                "mfe_mae",
                "taxonomy",
                "desk_label",
                "outcome_bucket",
            ],
            "policyChain": [
                "execution_truth",
                "canonical_pnl",
                "economic_r",
                "path_r",
                "mfe_mae",
                "taxonomy",
                "desk_label",
                "outcome_bucket",
            ],
        }

    desk_label = desk_exit_label(reason, pnl)

    # Economic R from Book P&L (authoritative). Prefer fresh calc over stale hints
    # that may have been path R mixed into rMultiple.
    econ = economic_r(pnl=pnl, risk_per_share=risk, qty=q)
    if econ is None:
        econ = _f(economic_r_hint)
    if econ is None:
        # Prefer explicit economicR on state; avoid rMultiple (may be path-polluted)
        econ = _f(st.get("economicR"))
    if econ is None and risk and q > 0:
        econ = 0.0

    path = path_r(entry=entry, exit_price=exit_price, risk_per_share=risk, direction=direction)
    if path is None:
        path = _f(path_r_hint)
    if path is None:
        path = _f(st.get("pathR"))
    if path is None:
        path = _f(current_r)

    mfe = infer_mfe_r(
        exit_state=st,
        current_r=path if path is not None else current_r,
        entry=entry,
        risk_per_share=risk,
        direction=direction,
        day_high=day_high,
        day_low=day_low,
    )
    mae = infer_mae_r(
        exit_state=st,
        current_r=path if path is not None else current_r,
        entry=entry,
        risk_per_share=risk,
        direction=direction,
        day_high=day_high,
        day_low=day_low,
    )
    stop_r = infer_stop_r(
        exit_state=st,
        entry=entry,
        risk_per_share=risk,
        direction=direction,
        effective_stop=effective_stop,
        mfe_r=mfe,
    )
    ladder_r = econ if econ is not None else (path if path is not None else 0.0)
    progress = desk_progress(float(mfe), float(ladder_r), float(stop_r))

    # Stop utilization for taxonomy
    stop_util = _f(stop_utilization)
    if stop_util is None and risk and path is not None and reason == "SL_HIT":
        stop_util = abs(path) / 1.0 if risk else None
        if path is not None:
            stop_util = abs(float(path))

    root, factors = classify_taxonomy(
        execution_status=exec_status,
        exit_reason=reason,
        pnl=pnl,
        mfe_r=mfe,
        stop_utilization=stop_util,
        economic_r=econ,
        gap_to_t2_pct=gap_to_t2_pct,
        trigger_source=trigger_source,
    )

    is_hit = reason in {"T1_HIT", "T2_HIT"}
    is_miss = reason in {"SL_HIT", "TRAIL_SL_HIT"} or (reason in {"EOD_SQUAREOFF", "EOD", "OPEN"} and pnl <= 0)

    econ_rounded = None if econ is None else round(float(econ), 3)
    path_rounded = None if path is None else round(float(path), 3)

    return {
        "executionStatus": exec_status,
        "pnl": pnl,
        "outcomeBucket": bucket,
        "deskExitLabel": desk_label,
        "exitReason": reason,
        "deskProgress": progress,
        # rMultiple aliases economicR (headline Book R)
        "rMultiple": econ_rounded,
        "economicR": econ_rounded,
        "pathR": path_rounded,
        "mfeR": round(float(mfe), 3),
        "maeR": None if mae is None else round(float(mae), 3),
        "effectiveStopR": round(float(stop_r), 3),
        "maePct": mae_pct,
        "mfePct": mfe_pct,
        "rootCause": root,
        "factors": factors,
        "isHit": is_hit,
        "isMiss": is_miss,
        "isSkip": False,
        "initialRiskCapital": round(float(risk) * q, 2) if risk and q > 0 else None,
        "lineage": lineage,
        "outcomeSchemaVersion": OUTCOME_SCHEMA_VERSION,
        "chain": [
            "execution_truth",
            "canonical_pnl",
            "economic_r",
            "path_r",
            "mfe_mae",
            "taxonomy",
            "desk_label",
            "outcome_bucket",
        ],
        "policyChain": [
            "execution_truth",
            "canonical_pnl",
            "economic_r",
            "path_r",
            "mfe_mae",
            "taxonomy",
            "desk_label",
            "outcome_bucket",
        ],
    }


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
    exit_price: float | None = None,
    qty: int | None = None,
    stop_utilization: float | None = None,
    gap_to_t2_pct: float | None = None,
    trigger_source: str | None = None,
    lineage: dict[str, Any] | None = None,
    economic_r_hint: float | None = None,
    path_r_hint: float | None = None,
) -> dict[str, Any]:
    """Thin wrapper — prefer build_trade_outcome at call sites."""
    return build_trade_outcome(
        triggered=triggered,
        realized_pnl=realized_pnl,
        exit_reason=exit_reason,
        exit_state=exit_state,
        entry=entry,
        exit_price=exit_price,
        risk_per_share=risk_per_share,
        qty=qty,
        direction=direction,
        effective_stop=effective_stop,
        current_r=current_r,
        day_high=day_high,
        day_low=day_low,
        mae_pct=mae_pct,
        mfe_pct=mfe_pct,
        stop_utilization=stop_utilization,
        gap_to_t2_pct=gap_to_t2_pct,
        trigger_source=trigger_source,
        lineage=lineage,
        economic_r_hint=economic_r_hint,
        path_r_hint=path_r_hint,
    )
