"""Quant V2 decision layer for index options.

Deterministic and auditable.  This module does not place broker orders.  It
scores already-constructed defined-risk structures against an explicit
NO_TRADE alternative and produces portfolio-admission decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from math import exp
from typing import Any

QUANT_V2_ENGINE = "INDEX_OPTIONS_QUANT_V2"
NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class RegimeProbabilities:
    trend_up: float
    trend_down: float
    range: float
    vol_expansion: float
    vol_compression: float

    def normalized(self) -> "RegimeProbabilities":
        vals = [max(0.0, self.trend_up), max(0.0, self.trend_down), max(0.0, self.range), max(0.0, self.vol_expansion), max(0.0, self.vol_compression)]
        total = sum(vals) or 1.0
        vals = [v / total for v in vals]
        return RegimeProbabilities(*vals)


@dataclass(frozen=True)
class QuantDecision:
    strategy_id: str
    index: str
    utility: float
    expected_value: float
    cvar95: float
    transaction_cost: float
    tail_penalty: float
    greek_penalty: float
    concentration_penalty: float
    decision: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if value == value else default
    except (TypeError, ValueError):
        return default


def infer_regime_probabilities(candidate: dict[str, Any]) -> RegimeProbabilities:
    """Convert existing deterministic evidence into a probability simplex.

    This is deliberately transparent rather than ML-shaped.  It is a first
    production-safe bridge to the later calibrated distribution model.
    """
    evidence = candidate.get("gateEvidence") if isinstance(candidate.get("gateEvidence"), dict) else {}
    breadth = evidence.get("breadth") if isinstance(evidence.get("breadth"), dict) else {}
    futures = evidence.get("futuresOi") if isinstance(evidence.get("futuresOi"), dict) else {}
    vol = evidence.get("volatilityEdge") if isinstance(evidence.get("volatilityEdge"), dict) else {}
    direction = str(candidate.get("direction") or candidate.get("bias") or "").upper()
    breadth_score = max(-100.0, min(100.0, _num(breadth.get("directionalScore"), _num(breadth.get("score"))))) / 100.0
    oi_state = str(futures.get("state") or "").upper()
    iv_edge = _num(vol.get("ivEdgePoints"))

    up = 1.0 + max(0.0, breadth_score) * 2.0
    down = 1.0 + max(0.0, -breadth_score) * 2.0
    if direction in {"CALL", "BULLISH"}: up += 0.8
    if direction in {"PUT", "BEARISH"}: down += 0.8
    if oi_state in {"LONG_BUILDUP", "SHORT_COVERING"}: up += 0.7
    if oi_state in {"SHORT_BUILDUP", "LONG_UNWINDING"}: down += 0.7
    range_w = 1.2 + max(0.0, 1.0 - abs(breadth_score))
    expansion = 1.0 + max(0.0, -iv_edge) * 0.08
    compression = 1.0 + max(0.0, iv_edge) * 0.08
    return RegimeProbabilities(up, down, range_w, expansion, compression).normalized()


def _structure_payoff_proxy(candidate: dict[str, Any], regimes: RegimeProbabilities) -> tuple[float, float]:
    """Conservative EV/CVaR proxy until full scenario repricer lands.

    Uses bounded max-profit/max-loss economics and regime compatibility.  It
    never creates an unbounded-risk estimate and therefore rejects candidates
    without explicit max loss.
    """
    max_profit = abs(_num(candidate.get("maxProfit") or (candidate.get("risk") or {}).get("maxProfitPerLot")))
    max_loss = abs(_num(candidate.get("maxLoss") or (candidate.get("risk") or {}).get("maxLossPerLot")))
    if max_profit <= 0 or max_loss <= 0:
        return -1e9, max_loss
    sid = str(candidate.get("strategyId") or candidate.get("strategyType") or "")
    p = regimes
    if sid == "IRON_CONDOR": win = p.range + 0.55 * p.vol_compression
    elif sid == "BULL_PUT_CREDIT_SPREAD": win = p.trend_up + 0.45 * p.range + 0.30 * p.vol_compression
    elif sid == "BEAR_CALL_CREDIT_SPREAD": win = p.trend_down + 0.45 * p.range + 0.30 * p.vol_compression
    elif "BULL" in sid or "CALL" in sid: win = p.trend_up + 0.30 * p.vol_expansion
    elif "BEAR" in sid or "PUT" in sid: win = p.trend_down + 0.30 * p.vol_expansion
    elif "STRADDLE" in sid or "STRANGLE" in sid: win = p.vol_expansion
    else: win = max(p.range, p.trend_up, p.trend_down, p.vol_expansion, p.vol_compression)
    win_probability = max(0.05, min(0.90, win))
    ev = win_probability * max_profit - (1.0 - win_probability) * max_loss
    cvar95 = max_loss
    return ev, cvar95


def score_candidate(candidate: dict[str, Any], *, portfolio: list[dict[str, Any]] | None = None) -> QuantDecision:
    sid = str(candidate.get("strategyId") or candidate.get("strategyType") or "UNKNOWN")
    index = str(candidate.get("key") or candidate.get("index") or "UNKNOWN")
    if not candidate.get("eligible"):
        return QuantDecision(sid, index, -1e9, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "REJECT", ("UPSTREAM_INELIGIBLE",))
    regimes = infer_regime_probabilities(candidate)
    ev, cvar95 = _structure_payoff_proxy(candidate, regimes)
    if ev <= -1e8:
        return QuantDecision(sid, index, ev, cvar95, 0.0, cvar95, 0.0, 0.0, "REJECT", ("DEFINED_MAX_LOSS_REQUIRED",))

    legs = candidate.get("legs") or []
    spread_cost = sum(abs(_num(leg.get("spreadPct"))) for leg in legs) * 0.01
    notional = max(abs(_num(candidate.get("maxLoss") or (candidate.get("risk") or {}).get("maxLossPerLot"))), 1.0)
    transaction_cost = notional * min(0.10, spread_cost * 0.01)
    delta = abs(_num(candidate.get("delta"))); gamma = abs(_num(candidate.get("gamma"))); vega = abs(_num(candidate.get("vega")))
    greek_penalty = notional * min(0.25, delta * 0.01 + gamma * 0.10 + vega * 0.002)
    tail_penalty = 0.20 * cvar95
    existing = portfolio or []
    same_index = sum(1 for row in existing if str(row.get("index") or row.get("key")) == index)
    concentration_penalty = notional * 0.15 * same_index
    utility = ev - transaction_cost - tail_penalty - greek_penalty - concentration_penalty
    reasons: list[str] = []
    if utility <= 0: reasons.append("NO_TRADE_DOMINATES")
    if same_index: reasons.append("INDEX_CONCENTRATION_PENALTY")
    decision = "ADMIT" if utility > 0 else "REJECT"
    return QuantDecision(sid, index, round(utility, 2), round(ev, 2), round(cvar95, 2), round(transaction_cost, 2), round(tail_penalty, 2), round(greek_penalty, 2), round(concentration_penalty, 2), decision, tuple(reasons))


def select_quant_portfolio(candidates: list[dict[str, Any]], *, max_positions: int = 2) -> dict[str, Any]:
    """Greedy deterministic portfolio admission with NO_TRADE = utility 0."""
    ranked = sorted((score_candidate(c) for c in candidates), key=lambda d: d.utility, reverse=True)
    admitted: list[QuantDecision] = []
    selected_keys: set[tuple[str, str]] = set()
    # Re-score sequentially so concentration penalties are applied once.
    source = {(str(c.get("strategyId") or c.get("strategyType")), str(c.get("key") or c.get("index"))): c for c in candidates}
    for initial in ranked:
        if len(admitted) >= max_positions: break
        candidate = source.get((initial.strategy_id, initial.index))
        if not candidate: continue
        decision = score_candidate(candidate, portfolio=[{"index": d.index} for d in admitted])
        if decision.utility <= 0: continue
        key = (decision.strategy_id, decision.index)
        if key in selected_keys: continue
        admitted.append(decision); selected_keys.add(key)
    return {
        "engine": QUANT_V2_ENGINE,
        "noTradeUtility": 0.0,
        "selected": [d.to_dict() for d in admitted],
        "ranked": [d.to_dict() for d in ranked],
        "decision": "TRADE" if admitted else NO_TRADE,
    }
