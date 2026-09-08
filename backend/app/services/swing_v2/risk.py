from __future__ import annotations

import math
from typing import Any

from .config import SwingV2Config


def build_exit_and_size(row: dict[str, Any], cfg: SwingV2Config, *, remaining_risk_rupees: float | None = None) -> dict[str, Any]:
    entry = float(row.get("executableEntry") or row.get("decisionPrice") or 0)
    atr = float(row.get("atr14") or 0)
    structure_stop = float(row.get("structureStop") or 0)
    segment = str(row.get("universeSegment") or "").upper()
    if entry <= 0 or atr <= 0 or structure_stop <= 0 or structure_stop >= entry:
        return {**row, "riskEligible": False, "riskRejectReason": "INVALID_ENTRY_ATR_OR_STRUCTURE_STOP"}

    structure_distance = entry - structure_stop
    risk_distance = max(structure_distance, cfg.stop_atr_mult * atr)
    risk_pct = 100.0 * risk_distance / entry
    max_stop = cfg.max_stop_micro_pct if "MICRO" in segment else (cfg.max_stop_small_pct if "SMALL" in segment else cfg.max_stop_core_pct)
    if risk_pct < cfg.min_stop_pct or risk_pct > max_stop:
        return {**row, "riskEligible": False, "riskRejectReason": "STOP_OUTSIDE_SWING_BAND", "riskPct": round(risk_pct, 4)}

    risk_bps = cfg.microcap_risk_bps if "MICRO" in segment else cfg.core_risk_bps
    risk_rupees = cfg.nav * risk_bps / 10_000.0
    if remaining_risk_rupees is not None:
        risk_rupees = min(risk_rupees, max(0.0, remaining_risk_rupees))
    max_notional = cfg.nav * (10.0 if "MICRO" in segment else cfg.max_name_notional_pct) / 100.0
    mdtv = float(row.get("mdtv20") or 0)
    participation = 0.001 if "MICRO" in segment else (0.0015 if "SMALL" in segment else 0.0025)
    liquidity_notional = mdtv * participation if mdtv > 0 else 0
    if liquidity_notional <= 0:
        return {**row, "riskEligible": False, "riskRejectReason": "MISSING_MDTV20"}

    qty = min(
        math.floor(risk_rupees / risk_distance),
        math.floor(max_notional / entry),
        math.floor(liquidity_notional / entry),
    )
    if qty < 2:
        return {**row, "riskEligible": False, "riskRejectReason": "SIZE_BELOW_TWO_SHARES"}

    stop = entry - risk_distance
    t1 = entry + cfg.t1_r * risk_distance
    t2 = entry + cfg.t2_r * risk_distance
    return {
        **row,
        "riskEligible": True,
        "entryPrice": round(entry, 4),
        "initialStop": round(stop, 4),
        "effectiveStop": round(stop, 4),
        "riskPerShare": round(risk_distance, 4),
        "riskPct": round(risk_pct, 4),
        "qty": qty,
        "initialRiskRupees": round(qty * risk_distance, 2),
        "deployedCapital": round(qty * entry, 2),
        "t1": round(t1, 4),
        "t2": round(t2, 4),
        # Never round the risk-bearing T1 tranche upward.
        "t1Qty": max(1, math.floor(qty * cfg.t1_qty_pct / 100.0)),
        "remainingQty": qty,
        "filledQty": qty,
        "plannedMaxBlendedR": 1.50,
        "upsideCapacityR": row.get("upsideCapacityR"),
        "expectedNetR": row.get("expectedNetR"),
        "expectedNetRStatus": row.get("expectedNetRStatus") or ("CALIBRATED" if row.get("expectedNetR") is not None else "UNRATED"),
        "exitPolicyScope": "SWING_V2",
    }


def gap_stress_loss(row: dict[str, Any]) -> float:
    segment = str(row.get("universeSegment") or "").upper()
    gap = 0.12 if "MICRO" in segment else (0.08 if "SMALL" in segment else 0.05)
    return float(row.get("deployedCapital") or 0) * gap
