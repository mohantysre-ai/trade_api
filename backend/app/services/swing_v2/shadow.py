from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from collections import Counter
from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import SwingV2Config, load_config
from .data_quality import evaluate_data_freshness
from .ledger import SwingLedger
from .portfolio import construct_portfolio
from .ranking import assign_segment_percentiles, rank_score
from .schemas import EventType, ValidationState
from .setups import evaluate_setups
from .tradability import evaluate_tradability

_LOG = logging.getLogger(__name__)
_COVERAGE_LOCK = threading.Lock()
_COVERAGE_STATE: dict[str, Any] = {"sessionDate": None, "tier": None, "pendingTier": None, "pendingCycles": 0}


def _snapshot_hash(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _regime_scale(regime: str) -> tuple[float, int]:
    return {"NORMAL": (1.0, 5), "DEFENSIVE": (.5, 2), "HALT_NEW_LONGS": (0.0, 0)}.get(regime, (0.0, 0))


def _raw_coverage_tier(coverage: float, cfg: SwingV2Config) -> tuple[str, float]:
    if coverage >= cfg.coverage_normal_threshold:
        return "NORMAL", cfg.coverage_normal_risk_multiplier
    if coverage >= cfg.coverage_degraded_threshold:
        return "DEGRADED", cfg.coverage_degraded_risk_multiplier
    if coverage >= cfg.coverage_defensive_threshold:
        return "DEFENSIVE", cfg.coverage_defensive_risk_multiplier
    return "BLOCK", 0.0


def _coverage_tier(coverage: float, cfg: SwingV2Config, *, session_date: str, apply_hysteresis: bool) -> tuple[str, float, dict[str, Any]]:
    raw_tier, raw_multiplier = _raw_coverage_tier(coverage, cfg)
    if not apply_hysteresis or cfg.coverage_hysteresis_cycles <= 1:
        return raw_tier, raw_multiplier, {"rawTier": raw_tier, "stableCycles": 1, "requiredCycles": cfg.coverage_hysteresis_cycles}
    with _COVERAGE_LOCK:
        if _COVERAGE_STATE["sessionDate"] != session_date:
            _COVERAGE_STATE.update(sessionDate=session_date, tier=raw_tier, pendingTier=None, pendingCycles=0)
        elif _COVERAGE_STATE["tier"] != raw_tier:
            if _COVERAGE_STATE["pendingTier"] == raw_tier:
                _COVERAGE_STATE["pendingCycles"] += 1
            else:
                _COVERAGE_STATE["pendingTier"] = raw_tier
                _COVERAGE_STATE["pendingCycles"] = 1
            if _COVERAGE_STATE["pendingCycles"] >= cfg.coverage_hysteresis_cycles:
                _COVERAGE_STATE.update(tier=raw_tier, pendingTier=None, pendingCycles=0)
        else:
            _COVERAGE_STATE.update(pendingTier=None, pendingCycles=0)
        tier = str(_COVERAGE_STATE["tier"] or raw_tier)
        multiplier = {"NORMAL": cfg.coverage_normal_risk_multiplier, "DEGRADED": cfg.coverage_degraded_risk_multiplier, "DEFENSIVE": cfg.coverage_defensive_risk_multiplier, "BLOCK": 0.0}[tier]
        return tier, multiplier, {"rawTier": raw_tier, "pendingTier": _COVERAGE_STATE["pendingTier"], "pendingCycles": _COVERAGE_STATE["pendingCycles"], "requiredCycles": cfg.coverage_hysteresis_cycles}


def _decision_id(snapshot_id: str, session_date: str, symbol: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{snapshot_id}:{session_date}:{symbol.upper()}"))


def _quality_and_safety(row: dict[str, Any], *, final_lock: bool, now: datetime) -> tuple[bool, list[str]]:
    fresh, freshness_reasons = evaluate_data_freshness(row, final_lock=final_lock, now=now)
    tradable, trade_reasons = evaluate_tradability(row)
    governance_reasons = []
    for flag, reason in (("insolvencyOrDefault", "INSOLVENCY_OR_DEFAULT"), ("unresolvedAuditQualification", "UNRESOLVED_AUDIT_QUALIFICATION"), ("materialPromoterPledgeAlert", "MATERIAL_PROMOTER_PLEDGE_ALERT")):
        if row.get(flag): governance_reasons.append(reason)
    return fresh and tradable and not governance_reasons, freshness_reasons + trade_reasons + governance_reasons


def build_shadow_v2(rows: list[dict[str, Any]], *, universe_coverage: float = 0.0, regime: str = "REGIME_UNRATED", final_lock: bool = False, occupied_symbols: set[str] | None = None, existing_positions: list[dict[str, Any]] | None = None, correlations: dict[tuple[str, str], float] | None = None, persist_events: bool = False, now: datetime | None = None, config: SwingV2Config | None = None, apply_coverage_hysteresis: bool = True) -> dict[str, Any]:
    cfg, now = config or load_config(), now or datetime.now(timezone.utc)
    base = {"strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version, "featureVersion": cfg.feature_version, "mode": cfg.mode, "enabled": cfg.enabled, "authoritative": cfg.paper_authoritative, "validationState": str(ValidationState.RESEARCH_HYPOTHESIS), "liveCapitalApproved": False, "executionMode": "PAPER", "manualBrokerOrderPlaced": False}
    if not cfg.enabled:
        return {**base, "candidates": [], "funnel": {"universe_size": len(rows), "evaluated_count": 0, "block_reason": "V2_DISABLED"}, "tradableCoverage": 0.0, "shadowCoverage": 0.0}

    tradable_rows = [r for r in rows if cfg.microcap_mode == "SHADOW" or "MICRO" not in str(r.get("universeSegment") or "").upper()]
    shadow_rows = [r for r in rows if cfg.microcap_mode != "SHADOW" and "MICRO" in str(r.get("universeSegment") or "").upper()]
    data_freshness = [(r, evaluate_data_freshness(r, final_lock=final_lock, now=now)) for r in tradable_rows]
    data_fresh_rows = [r for r, result in data_freshness if result[0]]
    data_stale_rows = [r for r, result in data_freshness if not result[0]]
    data_stale_reason_counts = Counter(reason for _, result in data_freshness if not result[0] for reason in result[1])
    candidate_fresh_rows = []
    candidate_stale_rows = []
    candidate_stale_reason_counts = Counter()
    for r in data_fresh_rows:
        gov_reasons = []
        for flag, reason in (
            ("corporateEventsCurrent", "CORPORATE_EVENTS_FEED_STALE"),
            ("surveillanceCurrent", "SURVEILLANCE_FEED_STALE"),
            ("universeCurrent", "UNIVERSE_FEED_STALE"),
        ):
            if r.get(flag) is not True:
                gov_reasons.append(reason)
        if gov_reasons:
            candidate_stale_rows.append(r)
            candidate_stale_reason_counts.update(gov_reasons)
        else:
            candidate_fresh_rows.append(r)
    candle_metrics = sum(
        bool((row.get("sourceTimestamps") or {}).get("bars1h") or (row.get("sourceTimestamps") or {}).get("bars5m"))
        for row in tradable_rows
    )
    shadow_covered = sum(1 for r in shadow_rows if evaluate_data_freshness(r, final_lock=final_lock, now=now)[0])
    total_universe = len(rows)
    tradable_universe = len(tradable_rows)
    data_coverage = len(data_fresh_rows) / total_universe if total_universe else universe_coverage
    tradable_coverage = len(candidate_fresh_rows) / tradable_universe if tradable_universe else universe_coverage
    paper_hunt_covered = sum(1 for r in candidate_fresh_rows if evaluate_tradability(r)[0])
    paper_hunt_coverage = paper_hunt_covered / total_universe if total_universe else universe_coverage
    shadow_coverage = shadow_covered / max(1, len(shadow_rows)) if shadow_rows else 1.0
    session_date = now.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    proposed_tier, proposed_multiplier, hysteresis = _coverage_tier(tradable_coverage, cfg, session_date=session_date, apply_hysteresis=apply_coverage_hysteresis)
    tiers_active = (not final_lock) or cfg.coverage_tiers_authoritative
    if tiers_active:
        tier, coverage_risk_multiplier = proposed_tier, proposed_multiplier
    else:
        tier = "NORMAL" if tradable_coverage >= cfg.coverage_normal_threshold else "BLOCK"
        coverage_risk_multiplier = 1.0 if tier == "NORMAL" else 0.0
    _LOG.info("Swing V2 coverage session=%s final_lock=%s tiers_active=%s data_fresh=%d data_stale=%d candidate_fresh=%d candidate_stale=%d total_universe=%d tradable_universe=%d data_coverage=%.4f tradable_coverage=%.4f paper_hunt_coverage=%.4f effective_tier=%s proposed_tier=%s data_stale_reasons=%s candidate_stale_reasons=%s", session_date, final_lock, tiers_active, len(data_fresh_rows), len(data_stale_rows), len(candidate_fresh_rows), len(candidate_stale_rows), total_universe, tradable_universe, data_coverage, tradable_coverage, paper_hunt_coverage, tier, proposed_tier, dict(data_stale_reason_counts), dict(candidate_stale_reason_counts))

    funnel = {"universe_size": total_universe, "evaluated_count": tradable_universe, "fresh_count": len(candidate_fresh_rows), "stale_excluded_count": len(candidate_stale_rows), "stale_reason_counts": dict(candidate_stale_reason_counts), "candleMetrics": candle_metrics, "candleTimeframe": "1H", "coverage_pct": round(tradable_coverage * 100.0, 4), "coverage_denominator": tradable_universe, "coverage_numerator": len(candidate_fresh_rows), "coverage_denominator_source": "ACTIVE_PAPER_HUNT_ROWS", "gate_tier": tier, "proposed_gate_tier": proposed_tier, "coverage_risk_multiplier": coverage_risk_multiplier, "dataCoverage": data_coverage, "tradableCoverage": tradable_coverage, "paperHuntCoverage": paper_hunt_coverage, "dataCoveragePct": round(data_coverage * 100.0, 4), "tradableCoveragePct": round(tradable_coverage * 100.0, 4), "paperHuntCoveragePct": round(paper_hunt_coverage * 100.0, 4), "totalUniverse": total_universe, "tradableUniverse": tradable_universe, "dataFreshCount": len(data_fresh_rows), "tradableFreshCount": len(candidate_fresh_rows), "paperHuntFreshCount": paper_hunt_covered, "candidates_in": len(candidate_fresh_rows), "qualified_out": 0, "qualified": 0, "locked_out": 0, "block_reason": None, "hysteresis": hysteresis, "universe": total_universe, "freshData": len(candidate_fresh_rows), "tradable": 0, "safetyPass": 0, "setupPass": 0, "expectancyPass": 0, "portfolioPass": 0, "locked": 0, "filled": 0, "blocked": False}
    if tier == "BLOCK":
        block_reason = "UNIVERSE_COVERAGE_BELOW_90PCT" if tiers_active and proposed_tier == "BLOCK" else "UNIVERSE_COVERAGE_BELOW_99PCT"
        funnel.update(blocked=True, block_reason=block_reason)

    regime_risk_scale, regime_cap = _regime_scale(regime)
    if regime == "REGIME_UNRATED":
        funnel.update(blocked=True, block_reason="REGIME_UNRATED", candidates_in=0)
        return {**base, "blocked": True, "blockReason": "REGIME_UNRATED", "coverage": tradable_coverage, "tradableCoverage": tradable_coverage, "coverageTier": tier, "coverageRiskMultiplier": coverage_risk_multiplier, "shadowCoverage": shadow_coverage, "candidates": [], "funnel": funnel}
    if regime_risk_scale == 0:
        funnel.update(blocked=True, block_reason="HALT_NEW_LONGS", candidates_in=0)
        return {**base, "blocked": True, "blockReason": "HALT_NEW_LONGS", "coverage": tradable_coverage, "tradableCoverage": tradable_coverage, "coverageTier": tier, "coverageRiskMultiplier": coverage_risk_multiplier, "shadowCoverage": shadow_coverage, "regime": regime, "candidates": [], "funnel": funnel}
    qualified, rejected = [], []
    snapshot_id, decision_timestamp = _snapshot_hash(rows), now.isoformat()
    stale_symbols = {str(r.get("symbol") or r.get("ticker") or "").upper() for r in candidate_stale_rows}
    for raw in rows:
        row = dict(raw); symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
        segment = str(row.get("universeSegment") or "").replace("_", "").upper(); active_segments = {value.replace("_", "").upper() for value in cfg.active_segments}
        segment_active = segment in active_segments or segment == "NIFTY500FALLBACK" or (segment == "NIFTYMICROCAP250" and cfg.microcap_mode == "SHADOW")
        fresh_ok, fresh_reasons = evaluate_data_freshness(row, final_lock=final_lock, now=now); trade_ok, trade_reasons = evaluate_tradability(row); gate_ok, gate_reasons = _quality_and_safety(row, final_lock=final_lock, now=now)
        funnel["tradable"] += int(trade_ok); funnel["safetyPass"] += int(gate_ok)
        if symbol in stale_symbols or not fresh_ok:
            rejected.append({"symbol": symbol, "reasonCodes": sorted(set(fresh_reasons or ["STALE_EXCLUDED_BY_COVERAGE_TIER"])), "qualificationStage": "FRESHNESS"}); continue
        setup = evaluate_setups(row) if gate_ok else {"eligible": False, "passedSetupIds": [], "rejections": {}}; rank = rank_score(row)
        score_lock_eligible = rank["status"] == "RATED" and float(rank.get("score") or 0) > 70; setup_ok = bool(setup["eligible"] or score_lock_eligible); funnel["setupPass"] += int(setup_ok)
        capacity_ok = float(row.get("upsideCapacityR") or 0) >= cfg.min_upside_capacity_r; planned_ok = float(row.get("plannedMaxBlendedR") or 1.5) >= cfg.min_planned_blended_r
        gross_r = float(row.get("upsideCapacityR") or row.get("plannedMaxBlendedR") or 1.5); cost_r = float(row.get("costPenaltyR") or 0) + float(row.get("spreadPenaltyR") or 0) + float(row.get("slippagePenaltyR") or 0)
        if cost_r == 0 and row.get("modeledRoundTripCostPct"):
            risk_dist = float(row.get("riskPerShare") or 5.0); price = float(row.get("decisionPrice") or row.get("entryPrice") or 100.0)
            if risk_dist > 0: cost_r = (float(row.get("modeledRoundTripCostPct")) / 100.0 * price) / risk_dist
        net_reward_r = gross_r - cost_r; row["expectedNetR"] = round(net_reward_r, 4) if row.get("expectedNetR") is None else row["expectedNetR"]; net_reward_ok = net_reward_r >= cfg.min_expected_net_r
        expected = row.get("expectedNetR"); calibrated = expected is not None and str(row.get("expectedNetRStatus") or "").upper() == "CALIBRATED"; expectancy_ok = calibrated and float(expected) >= cfg.min_expected_net_r; funnel["expectancyPass"] += int(expectancy_ok)
        reasons = fresh_reasons + trade_reasons + gate_reasons
        if not net_reward_ok: reasons.append("NET_REWARD_BELOW_MINIMUM")
        if not segment_active: reasons.append("SEGMENT_NOT_ACTIVE")
        if not segment_active or not gate_ok or not setup_ok or not capacity_ok or not planned_ok or not net_reward_ok or rank["status"] != "RATED":
            rejected.append({"symbol": symbol, "reasonCodes": sorted(set(reasons)), "setupRejections": setup.get("rejections"), "qualificationStage": "CANDIDATE_QUALIFICATION", "expectancyStatus": "PASS" if expectancy_ok else ("UNRATED" if expected is None else "LOW_OR_UNCALIBRATED"), "capacityStatus": "PASS" if capacity_ok else "LOW"}); continue
        gross_utility = float(expected) if expectancy_ok else float(rank["score"]) / 1000.0; utility = gross_utility - float(row.get("costPenaltyR") or 0) - float(row.get("gapRiskPenaltyR") or 0)
        qualified.append({**row, **rank, "symbol": symbol, "setupIds": setup["passedSetupIds"], "scoreLockEligible": score_lock_eligible, "expectedUtilityR": utility, "expectedNetRStatus": row.get("expectedNetRStatus") or "UNRATED", "promotionEligible": expectancy_ok, "decisionId": _decision_id(snapshot_id, session_date, symbol), "sourceSnapshotId": snapshot_id})

    qualified = assign_segment_percentiles(qualified); funnel["qualified_out"] = len(qualified)
    effective_risk_scale = regime_risk_scale * coverage_risk_multiplier
    scaled_cfg = SwingV2Config(**{**cfg.__dict__, "max_positions": min(cfg.max_positions, regime_cap), "core_risk_bps": max(1, int(round(cfg.core_risk_bps * effective_risk_scale))), "microcap_risk_bps": max(1, int(round(cfg.microcap_risk_bps * effective_risk_scale)))})
    portfolio = construct_portfolio(qualified, scaled_cfg, correlations=correlations, occupied_symbols=occupied_symbols, existing_positions=existing_positions); selected = portfolio["selected"]
    if tier == "BLOCK" and final_lock:
        selected = []
        portfolio["selected"] = []
        funnel["blocked"] = True
        funnel["block_reason"] = "UNIVERSE_COVERAGE_BELOW_90PCT" if tiers_active and proposed_tier == "BLOCK" else "UNIVERSE_COVERAGE_BELOW_99PCT"
    ist_now = now.astimezone(ZoneInfo("Asia/Kolkata")); cutoff_parts = [int(p) for p in cfg.entry_cutoff_ist.split(":")]; cutoff_time = time(cutoff_parts[0], cutoff_parts[1])
    if ist_now.time().replace(tzinfo=None) >= cutoff_time:
        for item in portfolio["selected"]: portfolio["rejected"].append({"symbol": item.get("symbol"), "portfolioRejectReason": f"ENTRY_CUTOFF_AFTER_{cfg.entry_cutoff_ist.replace(':','')}_IST"})
        portfolio["selected"] = []; selected = []
    for row in selected:
        row["sessionDate"] = session_date; row["decisionTimestamp"] = decision_timestamp; row["decision"] = "LOCKED" if final_lock else "SELECTED"; row["coverageTier"] = tier; row["coverageRiskMultiplier"] = coverage_risk_multiplier
        row["limitPrice"] = round(float(row.get("bestAsk") or row.get("decisionPrice") or row.get("entryPrice") or 0) * (1.0 + min(0.001, float(row.get("modeledRoundTripCostPct") or 0.2) / 400.0)), 4)
    funnel["portfolioPass"] = len(selected); funnel["locked"] = len(selected) if final_lock else 0; funnel["locked_out"] = funnel["locked"]
    # UI contract: qualified is the full pre-portfolio candidate funnel. locked is the post-sizing/slot final-lock outcome.
    funnel["qualified"] = funnel["qualified_out"]
    if persist_events:
        ledger = SwingLedger(cfg.ledger_path); selected_ids = {row["decisionId"] for row in selected}; selected_by_id = {row["decisionId"]: row for row in selected}
        for row in qualified:
            event_type = EventType.POSITION_LOCKED if row["decisionId"] in selected_ids else EventType.CANDIDATE_QUALIFIED; event_payload = selected_by_id.get(row["decisionId"], row)
            ledger.append(idempotency_key=f"{row['decisionId']}:{event_type}", decision_id=row["decisionId"], position_id=row["decisionId"] if event_type == EventType.POSITION_LOCKED else None, symbol=row["symbol"], session_date=session_date, event_type=event_type, event_timestamp=now.isoformat(), payload=event_payload)
        for index, row in enumerate(rejected):
            symbol = row.get("symbol") or f"UNKNOWN_{index}"; decision_id = _decision_id(snapshot_id, session_date, symbol)
            ledger.append(idempotency_key=f"{decision_id}:{EventType.CANDIDATE_REJECTED}", decision_id=decision_id, symbol=symbol, session_date=session_date, event_type=EventType.CANDIDATE_REJECTED, event_timestamp=now.isoformat(), payload=row)
    reason_counts: dict[str, int] = {}
    for row in rejected + portfolio["rejected"]:
        for reason in row.get("reasonCodes") or [row.get("portfolioRejectReason")]:
            if reason: reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    funnel["topRejectionReasons"] = sorted(({"reason": key, "count": value} for key, value in reason_counts.items()), key=lambda item: item["count"], reverse=True)[:10]
    return {**base, "generatedAt": now.isoformat(), "regime": regime, "regimeRiskScale": regime_risk_scale, "coverageTier": tier, "proposedCoverageTier": proposed_tier, "coverageTiersAuthoritative": tiers_active, "coverageRiskMultiplier": coverage_risk_multiplier, "effectiveRiskScale": effective_risk_scale, "coverage": tradable_coverage, "tradableCoverage": tradable_coverage, "dataCoverage": data_coverage, "paperHuntCoverage": paper_hunt_coverage, "coverageDenominatorSource": "ACTIVE_PAPER_HUNT_ROWS", "staleReasonCounts": dict(candidate_stale_reason_counts), "dataStaleReasonCounts": dict(data_stale_reason_counts), "shadowCoverage": shadow_coverage, "sourceSnapshotId": snapshot_id, "candidateCount": len(candidate_fresh_rows), "qualifiedCount": len(qualified), "selectedCount": len(selected), "candidates": selected, "rejected": rejected + portfolio["rejected"], "funnel": funnel, "portfolioInitialRisk": portfolio["portfolioInitialRisk"], "gapStressLoss": portfolio["gapStressLoss"], "cash": portfolio["cash"], "blocked": funnel.get("blocked", False), "blockReason": funnel.get("block_reason")}
