"""Deterministic index-options radar and re-entry governor.

This module is advisory only.  It never places broker orders and never fills
missing market evidence with inferred values.  A candidate becomes eligible
only when every directional, liquidity, breadth, OI, and option-economics gate
is explicitly present and passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .index_options_seller import SELLER_MIN_SCORE


INDEX_CONFIG: tuple[dict[str, str], ...] = (
    {"key": "NIFTY", "label": "NIFTY 50", "bucket": "BROAD", "exchange": "NSE"},
    {"key": "SENSEX", "label": "SENSEX", "bucket": "BROAD", "exchange": "BSE"},
    {"key": "BANKNIFTY", "label": "NIFTY BANK", "bucket": "FINANCIAL", "exchange": "NSE"},
    {"key": "FINNIFTY", "label": "NIFTY FIN SERVICE", "bucket": "FINANCIAL", "exchange": "NSE"},
)

MIN_DAILY_ENTRIES = 0
MAX_DAILY_ENTRIES = 20
MAX_ATTEMPTS_PER_INDEX = 20
MAX_CONCURRENT_TRADES = 2
MIN_ELIGIBLE_SCORE = 80.0


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _iso(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass
class IndexOptionReEntryGovernor:
    """Durable daily attempt/exit facts used by the options session engine."""

    trade_counts: dict[str, int] = field(default_factory=dict)
    sl_counts: dict[str, int] = field(default_factory=dict)
    last_exits: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record_entry(self, instrument: str) -> None:
        key = instrument.upper().strip()
        self.trade_counts[key] = self.trade_counts.get(key, 0) + 1

    def record_exit(
        self,
        instrument: str,
        exit_reason: str,
        direction: str,
        exit_time: datetime,
        exit_price: float,
    ) -> None:
        key = instrument.upper().strip()
        reason = exit_reason.upper().strip()
        self.last_exits[key] = {
            "time": exit_time.isoformat(),
            "reason": reason,
            "direction": direction.upper().strip(),
            "price": exit_price,
        }
        if reason == "STOP_LOSS":
            self.sl_counts[key] = self.sl_counts.get(key, 0) + 1


def can_reenter_index_option(
    instrument: str,
    candidate_direction: str,
    current_time: datetime,
    governor: IndexOptionReEntryGovernor,
    *,
    fresh_breakout_confirmed: bool = False,
    oi_aligned: bool = False,
    breadth_aligned: bool = False,
    opposite_confirmation: bool = False,
) -> dict[str, Any]:
    """Evaluate one index/side re-entry with auditable rejection reasons."""
    key = instrument.upper().strip()
    direction = candidate_direction.upper().strip()
    attempts = governor.trade_counts.get(key, 0)
    daily_entries = sum(max(0, int(value)) for value in governor.trade_counts.values())
    stops = governor.sl_counts.get(key, 0)
    base = {"allowed": False, "instrument": key, "attempts": attempts, "dailyEntries": daily_entries,
            "dailyEntryCap": MAX_DAILY_ENTRIES, "slHits": stops}
    if not key or direction not in {"CALL", "PUT", "BULLISH", "BEARISH", "NEUTRAL"}:
        return {**base, "reason": "INVALID_INSTRUMENT_OR_DIRECTION"}
    if daily_entries >= MAX_DAILY_ENTRIES:
        return {**base, "reason": "MAX_DAILY_ENTRIES_REACHED"}
    if attempts >= MAX_ATTEMPTS_PER_INDEX:
        return {**base, "reason": "MAX_INDEX_ATTEMPTS_REACHED"}
    if stops >= 2:
        return {**base, "reason": "HARD_BAN_TWO_SL_HITS"}
    prior = governor.last_exits.get(key)
    if not prior:
        return {**base, "allowed": True, "reason": "FRESH_INSTRUMENT"}

    exited_at = _iso(prior.get("time"))
    if exited_at is None:
        return {**base, "reason": "EXIT_TIMESTAMP_MISSING"}
    now = current_time if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
    elapsed = max(0.0, (now - exited_at.astimezone(now.tzinfo)).total_seconds() / 60.0)
    reason = str(prior.get("reason") or "").upper()
    prior_direction = str(prior.get("direction") or "").upper()

    if reason in {"TARGET", "TRAILING_SL_PROFIT"}:
        cooldown = 20.0 if reason == "TARGET" else 30.0
        if elapsed < cooldown:
            return {**base, "reason": "PROFIT_COOLDOWN_ACTIVE", "cooldownRemainingMin": round(cooldown - elapsed, 1)}
        if not (fresh_breakout_confirmed and oi_aligned and breadth_aligned):
            return {**base, "reason": "TREND_RESUMPTION_NOT_CONFIRMED"}
        return {**base, "allowed": True, "reason": "PROFIT_REENTRY_CONFIRMED", "riskScale": 0.5}

    if reason == "STOP_LOSS":
        if direction == prior_direction:
            if elapsed < 45.0:
                return {**base, "reason": "SL_SAME_DIRECTION_COOLDOWN", "cooldownRemainingMin": round(45.0 - elapsed, 1)}
            if not (fresh_breakout_confirmed and oi_aligned and breadth_aligned):
                return {**base, "reason": "SL_RECLAIM_NOT_CONFIRMED"}
            return {**base, "allowed": True, "reason": "SL_RECLAIM_CONFIRMED", "riskScale": 0.5}
        if not (opposite_confirmation and oi_aligned and breadth_aligned):
            return {**base, "reason": "REVERSAL_MISSING_CONFIRMATION"}
        return {**base, "allowed": True, "reason": "REVERSAL_CONFIRMED", "riskScale": 0.5}

    return {**base, "reason": "EXIT_STATE_NOT_ELIGIBLE"}


def _macro_lookup(snapshot: dict[str, Any], label: str) -> dict[str, Any]:
    rows = ((snapshot.get("macroDataStrip") or {}).get("morning") or [])
    wanted = label.upper()
    for row in rows:
        if str(row.get("label") or row.get("name") or "").upper() == wanted:
            return row
    return {}


def _candidate(index: dict[str, str], snapshot: dict[str, Any]) -> dict[str, Any]:
    supplied = ((snapshot.get("indexOptions") or {}).get("indices") or {}).get(index["key"], {})
    macro = _macro_lookup(snapshot, index["label"])
    spot = _num(supplied.get("spot") if supplied else macro.get("val"))
    components = supplied.get("scores") if isinstance(supplied.get("scores"), dict) else {}
    required_scores = ("trend", "breakout", "futuresOi", "optionChain", "breadth", "contract", "regime")
    weights = {"trend": 20, "breakout": 15, "futuresOi": 15, "optionChain": 15, "breadth": 20, "contract": 10, "regime": 5}
    missing = [name for name in required_scores if _num(components.get(name)) is None]
    score = None
    if not missing:
        score = round(sum((_num(components[name]) or 0.0) * weights[name] / 100.0 for name in required_scores), 2)

    gates = supplied.get("gates") if isinstance(supplied.get("gates"), dict) else {}
    required_gates = ("fresh", "structure", "breakout", "futuresOi", "optionChain", "breadth", "contractEconomics", "riskReward")
    failed = [name for name in required_gates if gates.get(name) is False]
    unavailable = [name for name in required_gates if gates.get(name) is not True and name not in failed]
    direction = str(supplied.get("direction") or "").upper()
    eligible = direction in {"CALL", "PUT"} and not failed and not unavailable and score is not None and score >= MIN_ELIGIBLE_SCORE
    if failed:
        state, reason = "NO_TRADE", f"HARD_GATE_FAILED:{','.join(failed)}"
    elif unavailable or missing:
        state, reason = "NO_TRADE", f"DATA_INCOMPLETE:{','.join(sorted(set(unavailable + missing)))}"
    elif score is not None and score < MIN_ELIGIBLE_SCORE:
        state, reason = "WATCH", "SCORE_BELOW_80"
    elif direction not in {"CALL", "PUT"}:
        state, reason = "NO_TRADE", "DIRECTION_NOT_PROVEN"
    else:
        state, reason = "ELIGIBLE", "ALL_GATES_PASSED"
    return {
        **index,
        "spot": spot,
        "direction": direction or None,
        "state": state,
        "reason": reason,
        "score": score,
        "scoreFloor": MIN_ELIGIBLE_SCORE,
        "failedGates": failed,
        "missingInputs": sorted(set(unavailable + missing)),
        "contract": supplied.get("contract"),
        "providerStatus": supplied.get("providerStatus"),
        "dataSource": supplied.get("source"),
        "expiry": supplied.get("expiry"),
        "dataLimitations": supplied.get("dataLimitations") or [],
        "gateEvidence": supplied.get("gateEvidence") or {},
        "chain": supplied.get("rawChain") or [],
        "structure": supplied.get("structure"),
        "oiResearch": supplied.get("oiResearch") or {},
        "componentFreshness": supplied.get("componentFreshness") or {},
        "eligible": eligible,
        "strategyMode": "BUY_PREMIUM",
        "strategyType": "LONG_CALL" if direction == "CALL" else "LONG_PUT" if direction == "PUT" else None,
    }


def _seller_candidate(index: dict[str, str], snapshot: dict[str, Any]) -> dict[str, Any]:
    supplied = ((snapshot.get("indexOptions") or {}).get("indices") or {}).get(index["key"], {})
    seller = supplied.get("seller") if isinstance(supplied.get("seller"), dict) else {}
    components = seller.get("scores") if isinstance(seller.get("scores"), dict) else {}
    required_scores = ("structure", "futuresRegime", "optionChain", "breadth", "volatilityEdge", "contract", "theta")
    weights = {"structure": 15, "futuresRegime": 10, "optionChain": 15, "breadth": 15,
               "volatilityEdge": 15, "contract": 20, "theta": 10}
    missing = [name for name in required_scores if _num(components.get(name)) is None]
    score = None
    if not missing:
        score = round(sum((_num(components[name]) or 0.0) * weights[name] / 100.0 for name in required_scores), 2)
    gates = seller.get("gates") if isinstance(seller.get("gates"), dict) else {}
    required_gates = ("fresh", "structure", "futuresRegime", "optionChain", "breadth", "volatilityEdge",
                      "contractEconomics", "definedRisk", "thetaCarry", "tailBuffer", "timeWindow")
    failed = [name for name in required_gates if gates.get(name) is False]
    unavailable = [name for name in required_gates if gates.get(name) is not True and name not in failed]
    strategy_type = str(seller.get("strategyType") or "")
    bias = str(seller.get("bias") or "").upper()
    construction_status = str(seller.get("constructionStatus") or "")
    eligible = bool(strategy_type and bias in {"BULLISH", "BEARISH", "NEUTRAL"} and not failed and not unavailable
                    and score is not None and score >= SELLER_MIN_SCORE)
    if construction_status:
        state, reason = "NO_TRADE", f"SELLER_CONSTRUCTION_FAILED:{construction_status}"
        failed, unavailable, missing = [], [], []
    elif not seller:
        state, reason = "NO_TRADE", "SELLER_STRUCTURE_UNAVAILABLE"
    elif failed:
        state, reason = "NO_TRADE", f"SELLER_GATE_FAILED:{','.join(failed)}"
    elif unavailable or missing:
        state, reason = "NO_TRADE", f"SELLER_DATA_INCOMPLETE:{','.join(sorted(set(unavailable + missing)))}"
    elif score is not None and score < SELLER_MIN_SCORE:
        state, reason = "WATCH", "SELLER_SCORE_BELOW_FLOOR"
    else:
        state, reason = "ELIGIBLE", "DEFINED_RISK_SELLER_GATES_PASSED"
    primary = seller.get("primaryContract") if isinstance(seller.get("primaryContract"), dict) else None
    return {
        **index,
        "spot": _num(supplied.get("spot")),
        "direction": bias or None,
        "bias": bias or None,
        "state": state,
        "reason": reason,
        "score": score,
        "scoreFloor": SELLER_MIN_SCORE,
        "failedGates": failed,
        "missingInputs": sorted(set(unavailable + missing)),
        "strategyMode": "SELL_PREMIUM",
        "strategyType": strategy_type or None,
        "constructionStatus": construction_status or None,
        "legs": seller.get("legs") or [],
        "risk": seller.get("risk") or {},
        "contract": primary,
        "providerStatus": supplied.get("providerStatus"),
        "dataSource": supplied.get("source"),
        "expiry": supplied.get("expiry"),
        "dataLimitations": seller.get("dataLimitations") or [],
        "gateEvidence": seller.get("gateEvidence") or {},
        "chain": supplied.get("rawChain") or [],
        "structure": supplied.get("structure"),
        "componentFreshness": supplied.get("componentFreshness") or {},
        "eligible": eligible,
    }


def build_index_options_radar(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    payload = snapshot if isinstance(snapshot, dict) else {}
    candidates = [_candidate(index, payload) for index in INDEX_CONFIG]
    seller_candidates = [_seller_candidate(index, payload) for index in INDEX_CONFIG]
    eligible = sorted((row for row in [*candidates, *seller_candidates] if row["eligible"]),
                      key=lambda row: row["score"] or 0, reverse=True)
    selected: list[dict[str, Any]] = []
    used_buckets: set[str] = set()
    used_indexes: set[str] = set()
    for row in eligible:
        if row["bucket"] in used_buckets or row["key"] in used_indexes or len(selected) >= MAX_CONCURRENT_TRADES:
            continue
        selected.append(row)
        used_buckets.add(row["bucket"])
        used_indexes.add(row["key"])
    return {
        "success": True,
        "executionPolicy": "AUTO_PAPER_ONLY",
        "strategy": "LONG_PREMIUM_OR_DEFINED_RISK_PREMIUM_SELLING",
        "updatedAt": payload.get("updatedAt"),
        "candidates": candidates,
        "sellerCandidates": seller_candidates,
        "selected": selected,
        "limits": {
            "minDailyEntries": MIN_DAILY_ENTRIES,
            "maxDailyEntries": MAX_DAILY_ENTRIES,
            "maxConcurrent": MAX_CONCURRENT_TRADES,
            "maxPerCorrelationBucket": 1,
            "scoreFloor": MIN_ELIGIBLE_SCORE,
            "huntMode": "CONTINUOUS_MARKET_SESSION",
        },
        "reentryPolicy": {
            "maxAttemptsPerIndex": MAX_ATTEMPTS_PER_INDEX,
            "hardBanAfterStopLosses": 2,
            "targetCooldownMin": 20,
            "profitTrailCooldownMin": 30,
            "sameDirectionStopCooldownMin": 45,
            "confirmationRequired": ["freshBreakout", "futuresOi", "weightedBreadth"],
            "riskScale": 0.5,
        },
    }
