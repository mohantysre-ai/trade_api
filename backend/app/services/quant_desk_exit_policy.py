"""Quant-desk EOD exit policy: R-ratchet + execution-accounting rules.

This module is intentionally deterministic. It does not decide whether a trade
should be selected; it only defines how an already-triggered position is managed
and how EOD outcomes should be classified.
"""
from __future__ import annotations

from typing import Any

# Highest favourable excursion (R) -> minimum locked R on the remaining runner.
# The stop is monotonic: it can only move in the profit-protecting direction.
R_RATCHET: tuple[tuple[float, float], ...] = (
    (0.25, -0.25),  # chop protection: reduce risk materially
    (0.50, 0.00),   # hard break-even
    (0.75, 0.25),   # first locked profit
    (1.00, 0.50),   # trend confirmation
    (1.25, 0.75),
    (1.50, 1.00),
    (2.00, 1.25),
    (3.00, 2.00),
    (4.00, 3.00),
    (5.00, 4.00),
)

# Scale only a portion early; preserve a large runner for trend days.
SCALE_LEGS: tuple[tuple[float, float], ...] = (
    (0.50, 0.20),
    (1.00, 0.20),
    (1.50, 0.20),
)
RUNNER_FRACTION = 0.40


def locked_r_for_mfe(mfe_r: float) -> float:
    """Return the maximum stop lock allowed by the highest MFE reached."""
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
    """Canonical execution classification.

    A true skip can never contribute P&L. A realized Book P&L means the trade
    executed and must never be relabelled NO_TRIGGER by a forensic diagnostic.
    """
    if realized_pnl is not None and abs(float(realized_pnl)) > 1e-9:
        return "TRIGGERED"
    if triggered is False:
        return "NOT_TRIGGERED"
    if triggered is True:
        return "TRIGGERED"
    return "UNKNOWN"


def canonical_pnl(*, execution_status: str, realized_pnl: float | None) -> float:
    """Return reportable P&L; NOT_TRIGGERED is always zero."""
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
    """Separate execution/financial outcome from diagnostic terminology."""
    reason = str(exit_reason or "EOD_SQUAREOFF").upper()
    if reason in {"TRAIL_SL", "TRAIL_SL_HIT", "SL_HIT"}:
        return "TRAIL_STOP" if reason.startswith("TRAIL") else "INITIAL_SL"
    if reason in {"EOD", "EOD_SQUAREOFF"}:
        return "EOD_SQUAREOFF"
    if reason.startswith("PARTIAL"):
        return "PARTIAL_SCALE"
    return "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"


def desk_progress(mfe_r: float, current_r: float, effective_stop_r: float) -> str:
    """Compact EOD ladder for the Outcome Desk."""
    parts: list[str] = []
    for trigger, _ in R_RATCHET:
        parts.append(f"{trigger:g}R{'+' if mfe_r + 1e-9 >= trigger else '.'}")
    parts.append(f"MFE {mfe_r:+.2f}R")
    parts.append(f"R {current_r:+.2f}")
    parts.append(f"SL {effective_stop_r:+.2f}R")
    return " ".join(parts)
