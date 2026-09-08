from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import SwingV2Config, load_config
from .data_quality import evaluate_freshness
from .ledger import SwingLedger
from .portfolio import construct_portfolio
from .ranking import assign_segment_percentiles, rank_score
from .schemas import EventType, ValidationState
from .setups import evaluate_setups
from .tradability import evaluate_tradability


def _snapshot_hash(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _regime_scale(regime: str) -> tuple[float, int]:
    return {"NORMAL": (1.0, 5), "DEFENSIVE": (.5, 2), "HALT_NEW_LONGS": (0.0, 0)}.get(regime, (0.0, 0))


def _decision_id(snapshot_id: str, session_date: str, symbol: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{snapshot_id}:{session_date}:{symbol.upper()}"))


def _quality_and_safety(row: dict[str, Any], *, final_lock: bool, now: datetime) -> tuple[bool, list[str]]:
    fresh, freshness_reasons = evaluate_freshness(row, final_lock=final_lock, now=now)
    tradable, trade_reasons = evaluate_tradability(row)
    governance_reasons = []
    for flag, reason in (
        ("insolvencyOrDefault", "INSOLVENCY_OR_DEFAULT"),
        ("unresolvedAuditQualification", "UNRESOLVED_AUDIT_QUALIFICATION"),
        ("materialPromoterPledgeAlert", "MATERIAL_PROMOTER_PLEDGE_ALERT"),
    ):
        if row.get(flag):
            governance_reasons.append(reason)
    # OI and promoter holding intentionally do not enter this gate.
    return fresh and tradable and not governance_reasons, freshness_reasons + trade_reasons + governance_reasons


def build_shadow_v2(
    rows: list[dict[str, Any]],
    *,
    universe_coverage: float = 0.0,
    regime: str = "REGIME_UNRATED",
    final_lock: bool = False,
    occupied_symbols: set[str] | None = None,
    correlations: dict[tuple[str, str], float] | None = None,
    persist_events: bool = False,
    now: datetime | None = None,
    config: SwingV2Config | None = None,
) -> dict[str, Any]:
    cfg, now = config or load_config(), now or datetime.now(timezone.utc)
    base = {
        "strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version,
        "featureVersion": cfg.feature_version, "mode": "SHADOW",
        "enabled": cfg.enabled, "authoritative": False,
        "validationState": str(ValidationState.RESEARCH_HYPOTHESIS),
        "liveCapitalApproved": False,
        "executionMode": "PAPER",
        "manualBrokerOrderPlaced": False,
    }
    if not cfg.enabled:
        return {**base, "candidates": [], "funnel": {"universe": len(rows)}}
    if universe_coverage < cfg.required_coverage:
        return {**base, "blocked": True, "blockReason": "UNIVERSE_COVERAGE_BELOW_99PCT", "coverage": universe_coverage, "candidates": []}
    risk_scale, regime_cap = _regime_scale(regime)
    if regime == "REGIME_UNRATED":
        return {**base, "blocked": True, "blockReason": "REGIME_UNRATED", "coverage": universe_coverage, "candidates": []}
    if risk_scale == 0:
        return {**base, "blocked": True, "blockReason": "HALT_NEW_LONGS", "coverage": universe_coverage, "regime": regime, "candidates": []}

    snapshot_id = _snapshot_hash(rows)
    session_date = now.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    funnel = {"universe": len(rows), "freshData": 0, "tradable": 0, "safetyPass": 0, "setupPass": 0, "expectancyPass": 0, "portfolioPass": 0, "locked": 0, "filled": 0}
    qualified, rejected = [], []
    for raw in rows:
        row = dict(raw)
        symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
        segment = str(row.get("universeSegment") or "").replace("_", "").upper()
        active_segments = {value.replace("_", "").upper() for value in cfg.active_segments}
        segment_active = segment in active_segments or (segment == "NIFTYMICROCAP250" and cfg.microcap_mode == "SHADOW")
        fresh_ok, fresh_reasons = evaluate_freshness(row, final_lock=final_lock, now=now)
        trade_ok, trade_reasons = evaluate_tradability(row)
        gate_ok, gate_reasons = _quality_and_safety(row, final_lock=final_lock, now=now)
        funnel["freshData"] += int(fresh_ok); funnel["tradable"] += int(trade_ok); funnel["safetyPass"] += int(gate_ok)
        setup = evaluate_setups(row) if gate_ok else {"eligible": False, "passedSetupIds": [], "rejections": {}}
        funnel["setupPass"] += int(setup["eligible"])
        capacity_ok = float(row.get("upsideCapacityR") or 0) >= cfg.min_upside_capacity_r
        planned_ok = float(row.get("plannedMaxBlendedR") or 1.5) >= cfg.min_planned_blended_r
        expected = row.get("expectedNetR")
        calibrated = expected is not None and str(row.get("expectedNetRStatus") or "").upper() == "CALIBRATED"
        expectancy_ok = calibrated and float(expected) >= cfg.min_expected_net_r
        funnel["expectancyPass"] += int(expectancy_ok)
        rank = rank_score(row)
        reasons = fresh_reasons + trade_reasons + gate_reasons
        if not segment_active:
            reasons.append("SEGMENT_NOT_ACTIVE")
        if not segment_active or not gate_ok or not setup["eligible"] or not capacity_ok or not planned_ok or rank["status"] != "RATED":
            rejected.append({"symbol": symbol, "reasonCodes": sorted(set(reasons)), "setupRejections": setup.get("rejections"), "expectancyStatus": "PASS" if expectancy_ok else ("UNRATED" if expected is None else "LOW_OR_UNCALIBRATED"), "capacityStatus": "PASS" if capacity_ok else "LOW"})
            continue
        # Unrated expectancy may collect shadow fills; it can never confer promotion/live eligibility.
        gross_utility = float(expected) if expectancy_ok else float(rank["score"]) / 1000.0
        utility = gross_utility - float(row.get("costPenaltyR") or 0) - float(row.get("gapRiskPenaltyR") or 0)
        qualified.append({**row, **rank, "symbol": symbol, "setupIds": setup["passedSetupIds"], "expectedUtilityR": utility, "expectedNetRStatus": row.get("expectedNetRStatus") or "UNRATED", "promotionEligible": expectancy_ok, "decisionId": _decision_id(snapshot_id, session_date, symbol), "sourceSnapshotId": snapshot_id})

    qualified = assign_segment_percentiles(qualified)
    scaled_cfg = SwingV2Config(**{**cfg.__dict__, "max_positions": min(cfg.max_positions, regime_cap), "core_risk_bps": max(1, int(cfg.core_risk_bps * risk_scale)), "microcap_risk_bps": max(1, int(cfg.microcap_risk_bps * risk_scale))})
    portfolio = construct_portfolio(qualified, scaled_cfg, correlations=correlations, occupied_symbols=occupied_symbols)
    selected = portfolio["selected"]
    funnel["portfolioPass"] = len(selected)
    if final_lock:
        funnel["locked"] = len(selected)
    if persist_events:
        ledger = SwingLedger(cfg.ledger_path)
        selected_ids = {row["decisionId"] for row in selected}
        for row in qualified:
            event_type = EventType.POSITION_LOCKED if row["decisionId"] in selected_ids else EventType.CANDIDATE_QUALIFIED
            ledger.append(idempotency_key=f"{row['decisionId']}:{event_type}", decision_id=row["decisionId"], position_id=row["decisionId"] if event_type == EventType.POSITION_LOCKED else None, symbol=row["symbol"], session_date=session_date, event_type=event_type, event_timestamp=now.isoformat(), payload=row)
        for index, row in enumerate(rejected):
            symbol = row.get("symbol") or f"UNKNOWN_{index}"
            decision_id = _decision_id(snapshot_id, session_date, symbol)
            ledger.append(idempotency_key=f"{decision_id}:{EventType.CANDIDATE_REJECTED}", decision_id=decision_id, symbol=symbol, session_date=session_date, event_type=EventType.CANDIDATE_REJECTED, event_timestamp=now.isoformat(), payload=row)

    reason_counts: dict[str, int] = {}
    for row in rejected + portfolio["rejected"]:
        for reason in row.get("reasonCodes") or [row.get("portfolioRejectReason")]:
            if reason:
                reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    return {**base, "generatedAt": now.isoformat(), "regime": regime, "riskScale": risk_scale, "coverage": universe_coverage, "sourceSnapshotId": snapshot_id, "candidateCount": len(rows), "qualifiedCount": len(qualified), "selectedCount": len(selected), "candidates": selected, "rejected": rejected + portfolio["rejected"], "funnel": {**funnel, "topRejectionReasons": sorted(({"reason": key, "count": value} for key, value in reason_counts.items()), key=lambda item: item["count"], reverse=True)[:10]}, "portfolioInitialRisk": portfolio["portfolioInitialRisk"], "gapStressLoss": portfolio["gapStressLoss"], "cash": portfolio["cash"]}
