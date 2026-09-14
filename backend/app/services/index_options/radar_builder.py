"""Radar builder: converts new StrategyResult back to legacy format."""

from __future__ import annotations

from typing import Any

from .context import IndexOptionContext
from .strategy_registry import get_registered_strategies, is_strategy_enabled
from .strategy_selector import select_strategies


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
    gates = supplied.get("gates") if isinstance(supplied.get("gates"), dict) else {}
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
        index=index["key"],
        spot=spot,
        futures_price=None,
        direction=str(supplied.get("direction") or "").upper() or None,
        direction_score=_num(scores.get("regime")),
        trend_score=_num(scores.get("trend")),
        breakout_score=_num(scores.get("breakout")),
        breadth_score=_num(breadth.get("score")),
        breadth_coverage=_num(breadth.get("coveragePct")),
        breadth_directional_score=_num(breadth.get("directionalScore")),
        futures_oi_state=str(futures_oi.get("state") or "").upper() or None,
        futures_oi_aligned=futures_oi.get("aligned"),
        realized_vol=None,
        atm_iv=None,
        iv_rank=None,
        iv_percentile=None,
        skew=None,
        term_structure=None,
        expected_move=None,
        chain=chain,
        expiry=str(expiry) if expiry else None,
        session_time=now,
        structure=structure,
        breadth=breadth,
        futures_oi=futures_oi,
        gate_evidence=gate_evidence,
        data_limitations=data_limitations,
        provider_status=provider_status,
        data_source=data_source,
        component_freshness=component_freshness,
            raw_snapshot=supplied,
            full_snapshot=snapshot,
    )


def _legacy_from_strategy_result(result: Any, index_config: dict[str, str]) -> dict[str, Any]:
    """Convert a StrategyResult to the legacy candidate/seller dict format."""
    is_seller = result.family == "VOLATILITY_COMPRESSION"
    base = {
        **index_config,
        "spot": result.extra.get("spot"),
        "direction": (result.bias or "").upper() if result.bias else None,
        "state": result.state,
        "reason": result.reason,
        "score": result.strategy_score,
        "scoreFloor": None,
        "failedGates": [],
        "gates": {},
        "missingInputs": [],
        "strategyMode": "SELL_PREMIUM" if is_seller else "BUY_PREMIUM",
        "strategyType": result.strategy_id,
        "bias": result.bias,
        "eligible": result.eligible,
        "providerStatus": None,
        "dataSource": None,
        "expiry": result.expiry,
        "dataLimitations": result.reason_codes,
        "gateEvidence": {},
        "chain": [],
        "structure": {},
        "oiResearch": {},
        "componentFreshness": {},
    }
    if not is_seller:
        base.update({
            "contract": result.extra.get("contract"),
            "failedGates": result.extra.get("failedGates", []),
            "missingInputs": result.extra.get("missingInputs", []),
            "gates": result.extra.get("gates", {}),
            "gateEvidence": result.extra.get("gateEvidence", {}),
            "chain": result.extra.get("chain", []),
            "structure": result.extra.get("structure"),
            "providerStatus": result.extra.get("providerStatus"),
            "dataSource": result.extra.get("dataSource"),
            "componentFreshness": result.extra.get("componentFreshness", {}),
            "dataLimitations": result.extra.get("dataLimitations", []),
            "scoreFloor": result.extra.get("scoreFloor"),
        })
    else:
        base.update({
            "legs": result.legs,
            "scores": result.extra.get("scores", {}),
            "gates": result.extra.get("gates", {}),
            "risk": result.extra.get("risk", {}),
            "constructionStatus": result.extra.get("constructionStatus"),
            "gateEvidence": result.extra.get("gateEvidence", {}),
            "dataLimitations": result.extra.get("dataLimitations", []),
            "primaryContract": result.extra.get("contract"),
            "providerStatus": result.extra.get("providerStatus"),
            "dataSource": result.extra.get("dataSource"),
            "componentFreshness": result.extra.get("componentFreshness", {}),
        })
    return base


def build_index_options_radar_v2(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    candidates = []
    seller_candidates = []
    for index in __import__("app.services.index_options_engine", fromlist=["INDEX_CONFIG"]).INDEX_CONFIG:
        context = _build_context(index, payload)
        if context is None:
            continue
        for strategy_id, strategy in get_registered_strategies().items():
            if not is_strategy_enabled(strategy_id):
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

    eligible = sorted(
        [row for row in [*candidates, *seller_candidates] if row.get("eligible")],
        key=lambda row: row.get("score") or 0,
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    used_buckets: set[str] = set()
    used_indexes: set[str] = set()
    for row in eligible:
        bucket = next((idx["bucket"] for idx in __import__("app.services.index_options_engine", fromlist=["INDEX_CONFIG"]).INDEX_CONFIG if idx["key"] == row.get("key")), "")
        if bucket in used_buckets or row.get("key") in used_indexes or len(selected) >= 2:
            continue
        selected.append(row)
        used_buckets.add(bucket)
        used_indexes.add(row.get("key", ""))

    return {
        "success": True,
        "executionPolicy": "AUTO_PAPER_ONLY",
        "strategy": "LONG_PREMIUM_OR_DEFINED_RISK_PREMIUM_SELLING",
        "updatedAt": payload.get("updatedAt"),
        "candidates": candidates,
        "sellerCandidates": seller_candidates,
        "selected": selected,
        "limits": {
            "minDailyEntries": 0,
            "maxDailyEntries": 20,
            "maxConcurrent": 2,
            "maxPerCorrelationBucket": 1,
            "scoreFloor": 70.0,
            "huntMode": "CONTINUOUS_MARKET_SESSION",
        },
        "reentryPolicy": {
            "maxAttemptsPerIndex": 20,
            "hardBanAfterStopLosses": 2,
            "targetCooldownMin": 20,
            "profitTrailCooldownMin": 30,
            "sameDirectionStopCooldownMin": 45,
            "confirmationRequired": ["freshBreakout", "futuresOi", "weightedBreadth"],
            "riskScale": 0.5,
        },
    }
