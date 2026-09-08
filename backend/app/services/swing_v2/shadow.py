from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import load_config
from .risk import build_exit_and_size, gap_stress_loss
from .setups import evaluate_setups


def _hard_gate(row: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    price = float(row.get("decisionPrice") or row.get("ltp") or 0)
    if price < 50:
        reasons.append("PRICE_BELOW_50")
    if row.get("surveillanceRestricted"):
        reasons.append("SURVEILLANCE_RESTRICTED")
    if row.get("scheduledResultBeforeD2"):
        reasons.append("RESULT_EVENT_BEFORE_D2")
    if row.get("nearPriceBand"):
        reasons.append("WITHIN_1PCT_PRICE_BAND")
    if row.get("mandatoryDataFresh") is not True:
        reasons.append("MANDATORY_DATA_STALE_OR_MISSING")
    if row.get("tradable") is not True:
        reasons.append("NOT_EXECUTABLY_TRADABLE")
    return not reasons, reasons


def _score(row: dict[str, Any]) -> float:
    factors = [
        ("trendPriorPctile", .20), ("residualStrengthPctile", .20),
        ("setupQualityPctile", .15), ("rvolPctile", .15),
        ("clvPctile", .10), ("sectorStrengthPctile", .10),
        ("liquidityPctile", .10),
    ]
    base = sum(float(row.get(k) or 0) * w for k, w in factors)
    if float(row.get("extensionAtr") or 0) > 2.0:
        base -= 10
    if float(row.get("unexplainedGapPct") or 0) > 2.0:
        base -= 10
    if float(row.get("sectorStrengthPctile") or 100) < 40:
        base -= 10
    return max(0.0, min(100.0, base))


def build_shadow_v2(rows: list[dict[str, Any]], *, universe_coverage: float = 0.0, regime: str = "REGIME_UNRATED") -> dict[str, Any]:
    cfg = load_config()
    now = datetime.now(timezone.utc).isoformat()
    if not cfg.enabled:
        return {"strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version, "mode": "SHADOW", "enabled": False, "validationState": "RESEARCH_HYPOTHESIS", "candidates": []}
    if universe_coverage < cfg.required_coverage:
        return {"strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version, "mode": "SHADOW", "enabled": True, "validationState": "RESEARCH_HYPOTHESIS", "blocked": True, "blockReason": "UNIVERSE_COVERAGE_BELOW_99PCT", "coverage": universe_coverage, "candidates": []}
    if regime == "REGIME_UNRATED":
        return {"strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version, "mode": "SHADOW", "enabled": True, "validationState": "RESEARCH_HYPOTHESIS", "blocked": True, "blockReason": "REGIME_UNRATED", "candidates": []}

    qualified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        gate_ok, gate_reasons = _hard_gate(row)
        setup = evaluate_setups(row) if gate_ok else {"eligible": False, "passedSetupIds": [], "rejections": {}}
        expected = row.get("expectedNetR")
        expectancy_ok = expected is not None and float(expected) >= cfg.min_expected_net_r
        capacity_ok = float(row.get("upsideCapacityR") or 0) >= cfg.min_upside_capacity_r
        if not gate_ok or not setup["eligible"] or not expectancy_ok or not capacity_ok:
            rejected.append({"symbol": row.get("symbol"), "hardGateReasons": gate_reasons, "setupRejections": setup.get("rejections"), "expectancyStatus": "PASS" if expectancy_ok else "UNRATED_OR_LOW", "capacityStatus": "PASS" if capacity_ok else "LOW"})
            continue
        row["setupIds"] = setup["passedSetupIds"]
        row["score"] = _score(row)
        qualified.append(row)

    qualified.sort(key=lambda r: float(r.get("expectedNetR") or 0), reverse=True)
    selected: list[dict[str, Any]] = []
    remaining_risk = cfg.nav * cfg.max_portfolio_risk_bps / 10000.0
    stress = 0.0
    sectors: dict[str, int] = {}
    for row in qualified:
        if len(selected) >= cfg.max_positions:
            break
        sector = str(row.get("sector") or "UNKNOWN")
        if sectors.get(sector, 0) >= 2:
            continue
        sized = build_exit_and_size(row, cfg, remaining_risk_rupees=remaining_risk)
        if not sized.get("riskEligible"):
            continue
        new_stress = stress + gap_stress_loss(sized)
        if new_stress > cfg.nav * .025:
            continue
        selected.append(sized)
        sectors[sector] = sectors.get(sector, 0) + 1
        remaining_risk -= float(sized.get("initialRiskRupees") or 0)
        stress = new_stress

    return {"strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version, "mode": "SHADOW", "enabled": True, "validationState": "RESEARCH_HYPOTHESIS", "generatedAt": now, "regime": regime, "coverage": universe_coverage, "candidateCount": len(rows), "qualifiedCount": len(qualified), "selectedCount": len(selected), "candidates": selected, "rejected": rejected, "portfolioInitialRisk": round(cfg.nav * cfg.max_portfolio_risk_bps / 10000.0 - remaining_risk, 2), "gapStressLoss": round(stress, 2), "liveCapitalApproved": False}
