from __future__ import annotations

from typing import Any

from .config import SwingV2Config
from .risk import build_exit_and_size, gap_stress_loss


_TIER_PRIORITY = {
    "PRIMARY_SETUP": 3,
    "SCORE_SOFT_PASS": 2,
    "DIVERSIFIED_SOFT_PASS": 1,
    "NONE": 0,
}


def _average_correlation(symbol: str, selected: list[dict[str, Any]], correlations: dict[tuple[str, str], float]) -> float | None:
    values = []
    for row in selected:
        other = str(row.get("symbol") or "")
        value = correlations.get((symbol, other), correlations.get((other, symbol)))
        if value is not None:
            values.append(float(value))
    return sum(values) / len(values) if values else None


def _is_micro(row: dict[str, Any]) -> bool:
    return "MICRO" in str(row.get("universeSegment") or "").upper()


def _priority(row: dict[str, Any], cfg: SwingV2Config) -> tuple[float, float, float, float, float, float, float]:
    tier_priority = float(_TIER_PRIORITY.get(row.get("qualificationMode", "NONE"), 0))
    utility = float(row.get("expectedUtilityR") if row.get("expectedUtilityR") is not None else row.get("expectedNetR") or -999)
    score = float(row.get("score") or 0)
    liquidity = float(row.get("liquidityPctile") or 0)
    residual = float(row.get("residualStrengthPctile") or 0)
    setup_quality = float(row.get("setupQualityPctile") or 0)
    sector_strength = float(row.get("sectorStrengthPctile") or 0)
    if _is_micro(row):
        utility *= cfg.microcap_priority_weight
        score *= cfg.microcap_priority_weight
        liquidity *= cfg.microcap_priority_weight
        residual *= cfg.microcap_priority_weight
        setup_quality *= cfg.microcap_priority_weight
        sector_strength *= cfg.microcap_priority_weight
    return tier_priority, utility, score, liquidity, residual, setup_quality, sector_strength


def construct_portfolio(rows: list[dict[str, Any]], cfg: SwingV2Config, *, correlations: dict[tuple[str, str], float] | None = None, occupied_symbols: set[str] | None = None, existing_positions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    selected, rejected = [], []
    existing = [row for row in (existing_positions or []) if not row.get("terminal") and not row.get("closed")]
    correlations, occupied = correlations or {}, {value.upper() for value in (occupied_symbols or set())}
    occupied.update(str(row.get("symbol") or "").upper() for row in existing if row.get("symbol"))
    existing_risk = sum(float(row.get("initialRiskRupees") or 0) for row in existing)
    remaining_risk = max(0.0, cfg.nav * cfg.max_portfolio_risk_bps / 10_000 - existing_risk)
    sector_notional, sector_risk = {}, {}
    for position in existing:
        sector = str(position.get("sector") or "UNKNOWN")
        sector_notional[sector] = sector_notional.get(sector, 0) + float(position.get("deployedCapital") or 0)
        sector_risk[sector] = sector_risk.get(sector, 0) + float(position.get("initialRiskRupees") or 0)
    stress = sum(gap_stress_loss(row) for row in existing)
    microcaps = sum(_is_micro(row) for row in existing)
    # The upstream hunt is volume-screened; this second ordering makes the liquid
    # core deterministic while allowing at most one lower-priority microcap satellite.
    ordered = sorted(rows, key=lambda row: _priority(row, cfg), reverse=True)
    for row in ordered:
        symbol, sector = str(row.get("symbol") or "").upper(), str(row.get("sector") or "UNKNOWN")
        reason = None
        measured_correlation = _average_correlation(symbol, [*existing, *selected], correlations)
        if len(existing) + len(selected) >= cfg.max_positions: reason = "MAX_POSITIONS"
        elif symbol in occupied: reason = "CROSS_BOOK_CONFLICT"
        elif sum(1 for item in [*existing, *selected] if str(item.get("sector") or "UNKNOWN") == sector) >= 2: reason = "MAX_TWO_NAMES_PER_SECTOR"
        elif any(sum(1 for item in [*existing, *selected] if setup_id in (item.get("setupIds") or [])) >= 3 for setup_id in (row.get("setupIds") or [])): reason = "SETUP_CONCENTRATION_CAP"
        elif measured_correlation is not None and measured_correlation > cfg.max_average_correlation: reason = "EXCESS_PORTFOLIO_CORRELATION"
        elif _is_micro(row) and cfg.microcap_mode != "SATELLITE": reason = "MICROCAP_NOT_ACTIVE"
        elif _is_micro(row) and microcaps >= 1: reason = "MAX_ONE_MICROCAP_SATELLITE"
        if reason:
            rejected.append({"symbol": symbol, "portfolioRejectReason": reason}); continue
        sized = build_exit_and_size(row, cfg, remaining_risk_rupees=remaining_risk)
        if not sized.get("riskEligible"):
            rejected.append({"symbol": symbol, "portfolioRejectReason": sized.get("riskRejectReason")}); continue
        notional, risk = float(sized["deployedCapital"]), float(sized["initialRiskRupees"])
        if sector_notional.get(sector, 0) + notional > cfg.nav * cfg.max_sector_notional_pct / 100:
            rejected.append({"symbol": symbol, "portfolioRejectReason": "SECTOR_NOTIONAL_CAP"}); continue
        if sector_risk.get(sector, 0) + risk > cfg.nav * cfg.max_sector_risk_bps / 10_000:
            rejected.append({"symbol": symbol, "portfolioRejectReason": "SECTOR_RISK_CAP"}); continue
        next_stress = stress + gap_stress_loss(sized)
        if next_stress > cfg.nav * cfg.max_gap_stress_bps / 10_000:
            rejected.append({"symbol": symbol, "portfolioRejectReason": "GAP_STRESS_CAP"}); continue
        if _is_micro(sized):
            sized["selectionSleeve"] = "MICROCAP_SATELLITE_20PCT_PRIORITY"
        elif sized.get("qualificationMode") == "DIVERSIFIED_SOFT_PASS":
            sized["selectionSleeve"] = "DIVERSIFIED_MOMENTUM_SOFT_PASS"
        else:
            sized["selectionSleeve"] = "LIQUID_CORE_TOP500_PRIORITY"
        sized["priorityWeight"] = cfg.microcap_priority_weight if _is_micro(sized) else 1.0
        selected.append(sized); occupied.add(symbol)
        if _is_micro(row): microcaps += 1
        sector_notional[sector] = sector_notional.get(sector, 0) + notional; sector_risk[sector] = sector_risk.get(sector, 0) + risk
        remaining_risk -= risk; stress = next_stress
    return {"selected": selected, "rejected": rejected, "portfolioInitialRisk": round(cfg.nav * cfg.max_portfolio_risk_bps / 10_000 - remaining_risk, 2), "gapStressLoss": round(stress, 2), "cash": round(cfg.nav - sum(float(row.get("deployedCapital") or 0) for row in [*existing, *selected]), 2), "selectionPolicy": "LIQUID_CORE_TOP500_THEN_MICROCAP_SATELLITE", "microcapPriorityWeight": cfg.microcap_priority_weight, "correlationEvidencePairs": len(correlations), "correlationPolicy": "ENFORCE_MEASURED_PAIRS_ONLY"}
