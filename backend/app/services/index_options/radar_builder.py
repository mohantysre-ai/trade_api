"""Radar builder: converts StrategyResult back to legacy format."""

from __future__ import annotations

from typing import Any

from .context import IndexOptionContext
from .config import LEGACY_ALWAYS_ENABLED
from .strategy_registry import get_registered_strategies, is_strategy_enabled
from .strategy_selector import select_strategies
from ..index_options_engine import INDEX_CONFIG, MAX_CONCURRENT_PER_SLEEVE, select_sleeve_rows


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _build_context(index: dict[str, str], snapshot: dict[str, Any]) -> IndexOptionContext | None:
    supplied = ((snapshot.get("indexOptions") or {}).get("indices") or {}).get(index["key"], {})
    spot = _num(supplied.get("spot"))
    if spot is None:
        return None

    scores = supplied.get("scores") if isinstance(supplied.get("scores"), dict) else {}
    structure = supplied.get("structure") if isinstance(supplied.get("structure"), dict) else {}
    breadth = supplied.get("breadth") if isinstance(supplied.get("breadth"), dict) else {}
    futures_oi = supplied.get("futuresOi") if isinstance(supplied.get("futuresOi"), dict) else {}
    chain = supplied.get("rawChain") or []
    expiry = supplied.get("expiry")
    provider_status = supplied.get("providerStatus")
    data_source = supplied.get("source")
    component_freshness = supplied.get("componentFreshness") or {}
    data_limitations = supplied.get("dataLimitations") or []
    gate_evidence = supplied.get("gateEvidence") or {}

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    return IndexOptionContext(
        index=index["key"], spot=spot, futures_price=None,
        direction=str(supplied.get("direction") or "").upper() or None,
        direction_score=_num(scores.get("regime")), trend_score=_num(scores.get("trend")),
        breakout_score=_num(scores.get("breakout")), breadth_score=_num(breadth.get("score")),
        breadth_coverage=_num(breadth.get("coveragePct")), breadth_directional_score=_num(breadth.get("directionalScore")),
        futures_oi_state=str(futures_oi.get("state") or "").upper() or None,
        futures_oi_aligned=futures_oi.get("aligned"), realized_vol=_num(supplied.get("realizedVol")),
        atm_iv=_num(supplied.get("atmIv")), iv_rank=_num(supplied.get("ivRank")),
        iv_percentile=_num(supplied.get("ivPercentile")), skew=_num(supplied.get("skew")),
        term_structure=_num(supplied.get("termStructure")), expected_move=_num(supplied.get("expectedMove")),
        chain=chain, expiry=str(expiry) if expiry else None, session_time=now, structure=structure,
        breadth=breadth, futures_oi=futures_oi, gate_evidence=gate_evidence,
        data_limitations=data_limitations, provider_status=provider_status, data_source=data_source,
        component_freshness=component_freshness, raw_snapshot=supplied, full_snapshot=snapshot,
        snapshot_id=str(snapshot.get("snapshotId") or snapshot.get("updatedAt") or ""),
        decision_timestamp=str(snapshot.get("updatedAt") or now.isoformat()),
        market_generation=str(snapshot.get("marketGeneration") or ""), put_skew=_num(supplied.get("putSkew")),
        call_skew=_num(supplied.get("callSkew")), dte=int(supplied["dte"]) if supplied.get("dte") is not None else None,
        far_expiry=str(supplied.get("farExpiry")) if supplied.get("farExpiry") else None,
        far_chain=supplied.get("farChain") if isinstance(supplied.get("farChain"), list) else [],
        expiry_state=str(supplied.get("expiryState") or "NORMAL_EXPIRY_SESSION"),
    )


def _legacy_from_strategy_result(result: Any, index_config: dict[str, str]) -> dict[str, Any]:
    is_seller = result.family == "VOLATILITY_COMPRESSION"
    base = {
        **index_config, "spot": result.extra.get("spot"),
        "direction": (result.bias or "").upper() if result.bias else None,
        "state": result.state, "reason": result.reason, "score": result.strategy_score, "scoreFloor": None,
        "failedGates": [], "gates": {}, "missingInputs": [],
        "strategyMode": "SELL_PREMIUM" if is_seller else "BUY_PREMIUM",
        "strategyType": result.strategy_id, "strategyId": result.strategy_id, "family": result.family,
        "bias": result.bias, "eligible": result.eligible, "providerStatus": None, "dataSource": None,
        "expiry": result.expiry, "dataLimitations": result.reason_codes, "gateEvidence": {}, "chain": [],
        "structure": {}, "oiResearch": {}, "componentFreshness": {}, "entryDebit": result.entry_debit,
        "entryCredit": result.entry_credit, "maxProfit": result.max_profit, "maxLoss": result.max_loss,
        "breakevens": result.breakevens, "rewardRisk": result.reward_risk, "delta": result.delta,
        "gamma": result.gamma, "theta": result.theta, "vega": result.vega, "margin": result.margin,
        "liquidityScore": result.liquidity_score, "executionScore": result.execution_score,
        "snapshotId": result.extra.get("snapshotId"), "decisionTimestamp": result.extra.get("decisionTimestamp"),
        "marketGeneration": result.extra.get("marketGeneration"), "farExpiry": result.extra.get("farExpiry"),
        "expiryState": result.extra.get("expiryState"), "atmIv": result.extra.get("atmIv"),
    }
    if not is_seller:
        base.update({
            "contract": result.extra.get("contract"), "failedGates": result.extra.get("failedGates", []),
            "missingInputs": result.extra.get("missingInputs", []), "gates": result.extra.get("gates", {}),
            "gateEvidence": result.extra.get("gateEvidence", {}), "chain": result.extra.get("chain", []),
            "structure": result.extra.get("structure"), "providerStatus": result.extra.get("providerStatus"),
            "dataSource": result.extra.get("dataSource"), "componentFreshness": result.extra.get("componentFreshness", {}),
            "dataLimitations": result.extra.get("dataLimitations", []), "scoreFloor": result.extra.get("scoreFloor"),
        })
    else:
        base.update({
            "legs": result.legs, "scores": result.extra.get("scores", {}), "gates": result.extra.get("gates", {}),
            "risk": result.extra.get("risk", {}), "constructionStatus": result.extra.get("constructionStatus"),
            "gateEvidence": result.extra.get("gateEvidence", {}), "dataLimitations": result.extra.get("dataLimitations", []),
            "primaryContract": result.extra.get("contract"), "providerStatus": result.extra.get("providerStatus"),
            "dataSource": result.extra.get("dataSource"), "componentFreshness": result.extra.get("componentFreshness", {}),
        })
    return base


def build_index_options_radar_v2(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    candidates: list[dict[str, Any]] = []
    seller_candidates: list[dict[str, Any]] = []
    for index in INDEX_CONFIG:
        context = _build_context(index, payload)
        if context is None:
            continue
        selected_by_regime = {row["strategyId"] for row in select_strategies(context)}
        for strategy_id, strategy in get_registered_strategies().items():
            if not is_strategy_enabled(strategy_id):
                continue
            if strategy_id not in LEGACY_ALWAYS_ENABLED and strategy_id not in selected_by_regime:
                continue
            if not strategy.eligible(context):
                continue
            try:
                result = strategy.build(context)
            except Exception:
                continue
            legacy = _legacy_from_strategy_result(result, index)
            if strategy.family == "VOLATILITY_COMPRESSION":
                seller_candidates.append(legacy)
            else:
                candidates.append(legacy)

    # Long CALL/PUT remain owned by the existing single-leg paper authority.
    # Defined-risk legacy sellers are intentionally admitted here: the durable
    # strategy DB is now their canonical multi-leg lifecycle book.
    durable_candidates = [row for row in candidates if row.get("strategyId") not in LEGACY_ALWAYS_ENABLED]
    durable_sellers = [
        row for row in seller_candidates
        if row.get("strategyId") in {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR"}
        or row.get("strategyId") not in LEGACY_ALWAYS_ENABLED
    ]
    buy_selected = select_sleeve_rows(durable_candidates, max_rows=MAX_CONCURRENT_PER_SLEEVE)
    sell_selected = select_sleeve_rows(durable_sellers, max_rows=MAX_CONCURRENT_PER_SLEEVE)
    selected = [*buy_selected, *sell_selected]

    return {
        "success": True, "executionPolicy": "AUTO_PAPER_ONLY",
        "strategy": "LONG_PREMIUM_OR_DEFINED_RISK_PREMIUM_SELLING", "updatedAt": payload.get("updatedAt"),
        "candidates": candidates, "sellerCandidates": seller_candidates, "selected": selected,
        "buySelected": buy_selected, "sellSelected": sell_selected,
        "limits": {"minDailyEntries": 0, "maxDailyEntries": 20, "maxConcurrent": 2,
                   "maxConcurrentPerSleeve": MAX_CONCURRENT_PER_SLEEVE, "maxPerCorrelationBucket": 1,
                   "sleeveIsolation": "INDEPENDENT_INDEX_AND_BUCKET_PER_SLEEVE", "scoreFloor": 70.0,
                   "huntMode": "CONTINUOUS_MARKET_SESSION"},
        "reentryPolicy": {"maxAttemptsPerIndex": 20, "hardBanAfterStopLosses": 2, "targetCooldownMin": 20,
                          "profitTrailCooldownMin": 30, "sameDirectionStopCooldownMin": 45,
                          "confirmationRequired": ["freshBreakout", "futuresOi", "weightedBreadth"], "riskScale": 0.5},
    }
