"""Pure analytics engines for Institutional EOD Analysis.

Never mutates live recommendation/strategy parameters.
Evidence-driven only — missing inputs yield null / explicit notes.
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import (
    AttributionBreakdown,
    CounterfactualScenario,
    EfficiencyMetrics,
    ExecutiveSummary,
    MarketRegimeLabel,
    MissedOpportunity,
    ModeledTCA,
    PMCommentary,
    ProposalStatus,
    RegimeBreadth,
    StrategyImprovementProposal,
    TCABasis,
    TradeOutcome,
    TradeScorecardNode,
)
from .ingestion import EOD_DATA_ROOT
from ..intraday_session_engine import _passes_filters, detect_regime
from ..llm_client import (
    LLM_CALL_TIMEOUT_SECONDS,
    _call_gemini,
    _call_openai,
    _llm_config,
    _llm_quota_available,
)

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

MIN_PROPOSAL_SAMPLES = 30
COUNTERFACTUAL_SCENARIOS = (
    "ATR_2X_TRAIL",
    "ANCHORED_VWAP_FLOOR",
    "VCP_PIVOT",
    "PARABOLIC_SAR",
    "FIXED_EOD_SQUAREOFF",
)


def _round(v: float | None, n: int = 4) -> float | None:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), n)


def _parse_ts(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=IST)
    s = str(ts).strip()
    if not s:
        return None
    try:
        # Angel One often returns "YYYY-MM-DDTHH:MM:SS+05:30" or similar
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=IST)
    except Exception:
        return None


def _mins_between(a: datetime | None, b: datetime | None) -> int | None:
    if a is None or b is None:
        return None
    return max(0, int((b - a).total_seconds() // 60))


# ---------------------------------------------------------------------------
# Regime & breadth
# ---------------------------------------------------------------------------

def map_regime_label(raw: dict[str, Any] | None) -> MarketRegimeLabel:
    """Map detect_regime / plan regime to schema MarketRegimeLabel."""
    raw = raw or {}
    label = str(raw.get("label") or raw.get("regime") or "").upper()
    vix = raw.get("indiaVix")
    try:
        vix_f = float(vix) if vix is not None else None
    except (TypeError, ValueError):
        vix_f = None

    if label in ("RISK_ON", "BULL", "BULL_TRENDING"):
        return MarketRegimeLabel.BULL_TRENDING
    if label in ("RISK_OFF", "BEAR", "BEAR_TRENDING"):
        return MarketRegimeLabel.BEAR_TRENDING
    if vix_f is not None and vix_f >= 18:
        return MarketRegimeLabel.HIGH_VOLATILITY_SIDEWAYS
    if vix_f is not None and vix_f <= 12:
        return MarketRegimeLabel.LOW_VOLATILITY_COMPRESSION
    if label == "NEUTRAL":
        return MarketRegimeLabel.LOW_VOLATILITY_COMPRESSION
    return MarketRegimeLabel.SECTOR_ROTATION_SELECTIVE


def compute_regime_breadth(
    regime: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
) -> RegimeBreadth:
    regime = regime or {}
    snapshot = snapshot or {}

    # Prefer live detect_regime when snapshot present
    try:
        if snapshot:
            detected = detect_regime(snapshot)
            if detected:
                regime = {**regime, **detected}
    except Exception as exc:
        log.debug("detect_regime unavailable: %s", exc)

    advances = declines = 0
    sector_moves: dict[str, list[float]] = {}
    quotes = snapshot.get("stockQuotes") or {}
    rows: list[dict[str, Any]] = []
    if isinstance(quotes, dict):
        rows = [v for v in quotes.values() if isinstance(v, dict)]
    elif isinstance(quotes, list):
        rows = [v for v in quotes if isinstance(v, dict)]
    if not rows:
        rows = [s for s in (snapshot.get("stocks") or []) if isinstance(s, dict)]

    for row in rows:
        delta = row.get("delta")
        chg: float | None = None
        if isinstance(delta, (int, float)):
            chg = float(delta)
        elif isinstance(delta, str):
            try:
                chg = float(delta.replace("%", "").replace("+", "").strip())
            except ValueError:
                chg = None
        if chg is None:
            continue
        if chg > 0:
            advances += 1
        elif chg < 0:
            declines += 1
        sector = str(row.get("sector") or row.get("capSize") or "OTHER")
        sector_moves.setdefault(sector, []).append(chg)

    ad_ratio = (advances / declines) if declines > 0 else (float(advances) if advances else None)
    rotation = [
        {
            "sector": sec,
            "avg_change_pct": _round(statistics.mean(vals), 3),
            "n": len(vals),
        }
        for sec, vals in sector_moves.items()
        if vals
    ]
    rotation.sort(key=lambda x: float(x.get("avg_change_pct") or 0), reverse=True)

    return RegimeBreadth(
        market_regime=map_regime_label(regime),
        raw_regime_label=str(regime.get("label") or regime.get("regime") or "") or None,
        bias=regime.get("bias"),
        nifty_change_pct=_round(_safe_float(regime.get("niftyChangePct"))),
        bank_nifty_change_pct=_round(_safe_float(regime.get("bankNiftyChangePct"))),
        india_vix=_round(_safe_float(regime.get("indiaVix"))),
        advance_decline_ratio=_round(ad_ratio, 3),
        advances=advances or None,
        declines=declines or None,
        sector_rotation=rotation[:12],
        reasons=list(regime.get("reasons") or []),
    )


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Candle path helpers — entry / outcome / MAE-MFE
# ---------------------------------------------------------------------------

def _find_entry_idx(
    candles: list[dict[str, Any]],
    entry: float,
    direction: str,
) -> int | None:
    for i, bar in enumerate(candles):
        high = float(bar.get("high") or 0)
        low = float(bar.get("low") or 0)
        if direction == "LONG":
            if high >= entry:
                return i
        else:
            if low <= entry:
                return i
    return None


def _resolve_path_outcome(
    candles: list[dict[str, Any]],
    entry: float,
    stop: float,
    target: float,
    direction: str,
) -> dict[str, Any]:
    """Walk 1-min path from entry trigger; determine outcome + exit print."""
    if not candles:
        return {
            "outcome": TradeOutcome.NO_ENTRY,
            "entry_idx": None,
            "exit_idx": None,
            "fill_price": None,
            "exit_price": None,
            "events": [],
        }

    entry_idx = _find_entry_idx(candles, entry, direction)
    events: list[dict[str, Any]] = []
    first = candles[0]
    events.append({
        "event": "SESSION_OPEN",
        "ts": first.get("ts"),
        "price": _round(float(first.get("open") or first.get("close") or 0)),
    })

    if entry_idx is None:
        events.append({
            "event": "NO_ENTRY",
            "ts": candles[-1].get("ts"),
            "price": _round(float(candles[-1].get("close") or 0)),
            "detail": "price never crossed signal entry",
        })
        return {
            "outcome": TradeOutcome.NO_ENTRY,
            "entry_idx": None,
            "exit_idx": None,
            "fill_price": None,
            "exit_price": None,
            "events": events,
        }

    fill_bar = candles[entry_idx]
    # Modeled fill at signal entry (MANUAL_ONLY — no OMS)
    fill_price = entry
    events.append({
        "event": "ENTRY_TRIGGER",
        "ts": fill_bar.get("ts"),
        "price": _round(fill_price),
        "bar_open": _round(float(fill_bar.get("open") or 0)),
    })

    # VWAP retests after entry (running VWAP)
    vwap = _running_vwap_at(candles, entry_idx)
    if vwap is not None:
        for j in range(entry_idx + 1, min(entry_idx + 60, len(candles))):
            bar = candles[j]
            low = float(bar.get("low") or 0)
            high = float(bar.get("high") or 0)
            if low <= vwap <= high:
                events.append({
                    "event": "VWAP_RETEST",
                    "ts": bar.get("ts"),
                    "price": _round(vwap),
                })
                break

    outcome = TradeOutcome.EOD_SQUAREOFF
    exit_idx = len(candles) - 1
    exit_price = float(candles[-1].get("close") or fill_price)

    for j in range(entry_idx, len(candles)):
        bar = candles[j]
        high = float(bar.get("high") or 0)
        low = float(bar.get("low") or 0)
        if direction == "LONG":
            stop_hit = low <= stop
            tgt_hit = high >= target
        else:
            stop_hit = high >= stop
            tgt_hit = low <= target
        # Same-bar ambiguity: assume stop first (conservative)
        if stop_hit and tgt_hit:
            outcome = TradeOutcome.STOP_HIT
            exit_idx = j
            exit_price = stop
            events.append({"event": "STOP_HIT", "ts": bar.get("ts"), "price": _round(stop)})
            break
        if stop_hit:
            outcome = TradeOutcome.STOP_HIT
            exit_idx = j
            exit_price = stop
            events.append({"event": "STOP_HIT", "ts": bar.get("ts"), "price": _round(stop)})
            break
        if tgt_hit:
            outcome = TradeOutcome.TARGET_HIT
            exit_idx = j
            exit_price = target
            events.append({"event": "TARGET_HIT", "ts": bar.get("ts"), "price": _round(target)})
            break

    if outcome == TradeOutcome.EOD_SQUAREOFF:
        events.append({
            "event": "EOD_SQUAREOFF",
            "ts": candles[exit_idx].get("ts"),
            "price": _round(exit_price),
        })

    return {
        "outcome": outcome,
        "entry_idx": entry_idx,
        "exit_idx": exit_idx,
        "fill_price": fill_price,
        "exit_price": exit_price,
        "events": events,
    }


def _running_vwap_at(candles: list[dict[str, Any]], upto: int) -> float | None:
    num = 0.0
    den = 0.0
    for bar in candles[: upto + 1]:
        h = float(bar.get("high") or 0)
        l = float(bar.get("low") or 0)
        c = float(bar.get("close") or 0)
        v = float(bar.get("volume") or 0)
        typical = (h + l + c) / 3.0
        num += typical * v
        den += v
    if den <= 0:
        return None
    return num / den


def _pnl_pct(direction: str, entry: float, exit_px: float) -> float:
    if not entry:
        return 0.0
    sign = 1.0 if direction == "LONG" else -1.0
    return sign * (exit_px - entry) / entry * 100.0


def compute_efficiency(
    candles: list[dict[str, Any]],
    entry_idx: int | None,
    exit_idx: int | None,
    fill_price: float | None,
    exit_price: float | None,
    stop: float,
    direction: str,
    realized_pnl_pct: float,
) -> EfficiencyMetrics:
    if entry_idx is None or fill_price is None or not candles:
        return EfficiencyMetrics()

    end = exit_idx if exit_idx is not None else len(candles) - 1
    path = candles[entry_idx : end + 1]
    if not path:
        return EfficiencyMetrics()

    if direction == "LONG":
        worst = min(float(b.get("low") or fill_price) for b in path)
        best = max(float(b.get("high") or fill_price) for b in path)
        mae = (worst - fill_price) / fill_price * 100.0
        mfe = (best - fill_price) / fill_price * 100.0
        stop_dist = abs(fill_price - stop) / fill_price * 100.0
        adverse_used = abs(min(0.0, mae))
    else:
        worst = max(float(b.get("high") or fill_price) for b in path)
        best = min(float(b.get("low") or fill_price) for b in path)
        mae = (fill_price - worst) / fill_price * 100.0  # negative when adverse
        mfe = (fill_price - best) / fill_price * 100.0
        stop_dist = abs(stop - fill_price) / fill_price * 100.0
        adverse_used = abs(min(0.0, mae)) if mae < 0 else abs(mae) if worst > fill_price else 0.0
        # For shorts: mae_pct as negative adverse
        mae = -abs((worst - fill_price) / fill_price * 100.0) if worst > fill_price else 0.0
        mfe = abs((fill_price - best) / fill_price * 100.0) if best < fill_price else 0.0

    # Normalize LONG mae as negative adverse
    if direction == "LONG":
        mae = min(0.0, mae)  # already worst-fill
        mfe = max(0.0, mfe)

    rr_ratio = None
    if mfe and abs(mfe) > 1e-9:
        rr_ratio = realized_pnl_pct / mfe

    stop_eff = None
    if stop_dist > 1e-9:
        stop_eff = adverse_used / stop_dist

    return EfficiencyMetrics(
        mae_pct=_round(mae, 4),
        mfe_pct=_round(mfe, 4),
        realized_return_ratio=_round(rr_ratio, 4),
        stop_efficiency_index=_round(stop_eff, 4),
    )


def compute_modeled_tca(
    candles: list[dict[str, Any]],
    signal_entry: float,
    fill_price: float | None,
    entry_idx: int | None,
    direction: str,
    efficiency: EfficiencyMetrics,
) -> ModeledTCA:
    """Modeled TCA only — spread/impact null (no OMS fills)."""
    if not candles or fill_price is None or entry_idx is None:
        return ModeledTCA(
            implementation_shortfall_bps=None,
            delay_cost_bps=None,
            spread_cost_bps=None,
            market_impact_bps=None,
            opportunity_cost_bps=None,
            basis=TCABasis.MODELED,
        )

    first_open = float(candles[0].get("open") or candles[0].get("close") or signal_entry)
    # Delay: signal price vs first session open (proxy for open delay)
    delay = _pnl_pct(direction, signal_entry, first_open) * -1.0  # cost positive when worse
    delay_bps = abs(delay) * 100.0 if delay != 0 else 0.0
    # Sign: positive cost when fill worse than signal
    signed_delay = (fill_price - signal_entry) / signal_entry * 10000.0
    if direction == "SHORT":
        signed_delay = -signed_delay

    # Opportunity: MFE left on table after exit (proxy) — use unused favorable
    opp_bps = None
    if efficiency.mfe_pct is not None and efficiency.realized_return_ratio is not None:
        leftover = max(0.0, efficiency.mfe_pct * (1.0 - min(1.0, max(0.0, efficiency.realized_return_ratio))))
        opp_bps = leftover * 100.0  # pct → bps

    is_bps = signed_delay + (opp_bps or 0.0)

    return ModeledTCA(
        implementation_shortfall_bps=_round(is_bps, 2),
        delay_cost_bps=_round(signed_delay, 2),
        spread_cost_bps=None,
        market_impact_bps=None,
        opportunity_cost_bps=_round(opp_bps, 2),
        basis=TCABasis.MODELED,
    )


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def compute_attribution(
    pick: dict[str, Any],
    realized_pnl_pct: float,
    snapshot: dict[str, Any] | None,
) -> AttributionBreakdown:
    fb = pick.get("factorBreakdown") or {}
    contribs: dict[str, float | None] = {
        "volume_expansion_contrib": None,
        "vwap_alignment_contrib": None,
        "momentum_velocity_contrib": None,
        "sector_relative_strength_contrib": None,
        "open_interest_buildup_contrib": None,
        "news_sentiment_contrib": None,
    }
    key_map = {
        "volume": "volume_expansion_contrib",
        "relativeVolume": "volume_expansion_contrib",
        "vwap": "vwap_alignment_contrib",
        "vwapAlignment": "vwap_alignment_contrib",
        "momentum": "momentum_velocity_contrib",
        "trend": "momentum_velocity_contrib",
        "relativeStrength": "sector_relative_strength_contrib",
        "sector": "sector_relative_strength_contrib",
        "oi": "open_interest_buildup_contrib",
        "openInterest": "open_interest_buildup_contrib",
        "news": "news_sentiment_contrib",
    }
    for k, node in (fb.items() if isinstance(fb, dict) else []):
        if not isinstance(node, dict):
            continue
        score = _safe_float(node.get("score"))
        weight = _safe_float(node.get("weight")) or 0.0
        if score is None:
            continue
        mapped = key_map.get(k)
        if mapped:
            contribs[mapped] = _round(score * weight / 100.0, 4)

    alpha = _safe_float(pick.get("score"))

    # Brinson-style: sector benchmark move vs stock move
    allocation = selection = interaction = None
    sector = pick.get("sector")
    day_chg = None
    sector_avg = None
    if snapshot:
        quotes = snapshot.get("stockQuotes") or {}
        sym = pick.get("symbol")
        row = quotes.get(sym) if isinstance(quotes, dict) else None
        if isinstance(row, dict):
            day_chg = _parse_delta(row.get("delta"))
        if sector and isinstance(quotes, dict):
            vals = []
            for r in quotes.values():
                if not isinstance(r, dict):
                    continue
                if str(r.get("sector") or "") == str(sector):
                    d = _parse_delta(r.get("delta"))
                    if d is not None:
                        vals.append(d)
            if vals:
                sector_avg = statistics.mean(vals)

    # Portfolio weight proxy: equal weight among picks not available here — use 1/N later.
    # Selection = stock excess vs sector; allocation left null without benchmark weights.
    if day_chg is not None and sector_avg is not None:
        selection = _round(day_chg - sector_avg, 4)
        interaction = _round(realized_pnl_pct - (sector_avg or 0) - (selection or 0), 4)

    return AttributionBreakdown(
        alpha_score=_round(alpha, 2),
        volume_expansion_contrib=contribs["volume_expansion_contrib"],
        vwap_alignment_contrib=contribs["vwap_alignment_contrib"],
        momentum_velocity_contrib=contribs["momentum_velocity_contrib"],
        sector_relative_strength_contrib=contribs["sector_relative_strength_contrib"],
        open_interest_buildup_contrib=contribs["open_interest_buildup_contrib"],
        news_sentiment_contrib=contribs["news_sentiment_contrib"],
        allocation_effect=allocation,
        selection_effect=selection,
        interaction_effect=interaction,
    )


def _parse_delta(delta: Any) -> float | None:
    if isinstance(delta, (int, float)):
        return float(delta)
    if isinstance(delta, str):
        try:
            return float(delta.replace("%", "").replace("+", "").strip())
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Counterfactual simulator (5 exit models)
# ---------------------------------------------------------------------------

def simulate_counterfactuals(
    candles: list[dict[str, Any]],
    entry_idx: int | None,
    fill_price: float | None,
    stop: float,
    target: float,
    direction: str,
    atr_pct: float | None,
    actual_pnl_pct: float,
) -> list[CounterfactualScenario]:
    if entry_idx is None or fill_price is None or not candles:
        return [
            CounterfactualScenario(
                scenario_name=name,
                simulated_outcome="NO_ENTRY",
                simulated_pnl_pct=None,
                pnl_delta_vs_actual_pct=None,
                max_drawdown_during_trade_pct=None,
            )
            for name in COUNTERFACTUAL_SCENARIOS
        ]

    atr_abs = (atr_pct or 1.5) / 100.0 * fill_price
    path = candles[entry_idx:]
    results: list[CounterfactualScenario] = []

    results.append(
        _sim_atr_trail(path, fill_price, direction, atr_abs * 2.0, actual_pnl_pct, "ATR_2X_TRAIL")
    )
    results.append(
        _sim_vwap_floor(candles, entry_idx, fill_price, direction, actual_pnl_pct)
    )
    results.append(
        _sim_vcp_pivot(path, fill_price, direction, actual_pnl_pct)
    )
    results.append(
        _sim_psar(path, fill_price, direction, actual_pnl_pct)
    )
    results.append(
        _sim_eod(path, fill_price, direction, actual_pnl_pct)
    )
    return results


def _max_dd(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v - peak) / peak * 100.0 if peak else 0.0
        max_dd = min(max_dd, dd)
    return max_dd


def _sim_result(
    name: str,
    outcome: str,
    entry: float,
    exit_px: float,
    direction: str,
    path: list[dict[str, Any]],
    actual_pnl: float,
) -> CounterfactualScenario:
    pnl = _pnl_pct(direction, entry, exit_px)
    closes = [float(b.get("close") or entry) for b in path]
    # Equity as mark-to-market from entry
    if direction == "LONG":
        equity = [entry] + closes
    else:
        equity = [entry] + [entry - (c - entry) for c in closes]
    return CounterfactualScenario(
        scenario_name=name,
        simulated_outcome=outcome,
        simulated_pnl_pct=_round(pnl, 4),
        pnl_delta_vs_actual_pct=_round(pnl - actual_pnl, 4),
        max_drawdown_during_trade_pct=_round(_max_dd(equity), 4),
    )


def _sim_atr_trail(
    path: list[dict[str, Any]],
    entry: float,
    direction: str,
    trail_dist: float,
    actual: float,
    name: str,
) -> CounterfactualScenario:
    extreme = entry
    for bar in path:
        high = float(bar.get("high") or entry)
        low = float(bar.get("low") or entry)
        close = float(bar.get("close") or entry)
        if direction == "LONG":
            extreme = max(extreme, high)
            trail = extreme - trail_dist
            if low <= trail:
                return _sim_result(name, "TRAILED_EXIT", entry, trail, direction, path, actual)
        else:
            extreme = min(extreme, low)
            trail = extreme + trail_dist
            if high >= trail:
                return _sim_result(name, "TRAILED_EXIT", entry, trail, direction, path, actual)
    return _sim_result(name, "EOD_SQUAREOFF", entry, float(path[-1].get("close") or entry), direction, path, actual)


def _sim_vwap_floor(
    candles: list[dict[str, Any]],
    entry_idx: int,
    entry: float,
    direction: str,
    actual: float,
) -> CounterfactualScenario:
    path = candles[entry_idx:]
    for i, bar in enumerate(path):
        abs_idx = entry_idx + i
        vwap = _running_vwap_at(candles, abs_idx)
        if vwap is None:
            continue
        close = float(bar.get("close") or entry)
        low = float(bar.get("low") or entry)
        high = float(bar.get("high") or entry)
        if direction == "LONG" and low < vwap and close < vwap:
            return _sim_result("ANCHORED_VWAP_FLOOR", "TRAILED_EXIT", entry, vwap, direction, path, actual)
        if direction == "SHORT" and high > vwap and close > vwap:
            return _sim_result("ANCHORED_VWAP_FLOOR", "TRAILED_EXIT", entry, vwap, direction, path, actual)
    return _sim_result(
        "ANCHORED_VWAP_FLOOR",
        "EOD_SQUAREOFF",
        entry,
        float(path[-1].get("close") or entry),
        direction,
        path,
        actual,
    )


def _sim_vcp_pivot(
    path: list[dict[str, Any]],
    entry: float,
    direction: str,
    actual: float,
) -> CounterfactualScenario:
    """Pivot = swing low/high of first 5 bars after entry; exit on break."""
    window = path[:5] if len(path) >= 5 else path
    if direction == "LONG":
        pivot = min(float(b.get("low") or entry) for b in window)
        for bar in path[5:] if len(path) > 5 else []:
            if float(bar.get("low") or entry) < pivot:
                return _sim_result("VCP_PIVOT", "TRAILED_EXIT", entry, pivot, direction, path, actual)
    else:
        pivot = max(float(b.get("high") or entry) for b in window)
        for bar in path[5:] if len(path) > 5 else []:
            if float(bar.get("high") or entry) > pivot:
                return _sim_result("VCP_PIVOT", "TRAILED_EXIT", entry, pivot, direction, path, actual)
    return _sim_result(
        "VCP_PIVOT",
        "EOD_SQUAREOFF",
        entry,
        float(path[-1].get("close") or entry),
        direction,
        path,
        actual,
    )


def _sim_psar(
    path: list[dict[str, Any]],
    entry: float,
    direction: str,
    actual: float,
) -> CounterfactualScenario:
    """Simplified Parabolic SAR trail."""
    af = 0.02
    af_max = 0.2
    if direction == "LONG":
        sar = float(path[0].get("low") or entry)
        ep = float(path[0].get("high") or entry)
        long = True
    else:
        sar = float(path[0].get("high") or entry)
        ep = float(path[0].get("low") or entry)
        long = False

    for bar in path[1:]:
        high = float(bar.get("high") or entry)
        low = float(bar.get("low") or entry)
        if long:
            sar = sar + af * (ep - sar)
            if high > ep:
                ep = high
                af = min(af_max, af + 0.02)
            if low < sar:
                return _sim_result("PARABOLIC_SAR", "TRAILED_EXIT", entry, sar, direction, path, actual)
        else:
            sar = sar + af * (ep - sar)
            if low < ep:
                ep = low
                af = min(af_max, af + 0.02)
            if high > sar:
                return _sim_result("PARABOLIC_SAR", "TRAILED_EXIT", entry, sar, direction, path, actual)

    return _sim_result(
        "PARABOLIC_SAR",
        "EOD_SQUAREOFF",
        entry,
        float(path[-1].get("close") or entry),
        direction,
        path,
        actual,
    )


def _sim_eod(
    path: list[dict[str, Any]],
    entry: float,
    direction: str,
    actual: float,
) -> CounterfactualScenario:
    exit_px = float(path[-1].get("close") or entry)
    return _sim_result("FIXED_EOD_SQUAREOFF", "EOD_SQUAREOFF", entry, exit_px, direction, path, actual)


# ---------------------------------------------------------------------------
# Root cause / false positives
# ---------------------------------------------------------------------------

def classify_root_cause(
    outcome: TradeOutcome,
    efficiency: EfficiencyMetrics,
    confidence: float,
    realized_pnl_pct: float,
) -> tuple[list[str], list[str], str | None, bool]:
    success: list[str] = []
    failure: list[str] = []
    root: str | None = None
    false_pos = False

    mfe = efficiency.mfe_pct
    mae = efficiency.mae_pct
    stop_eff = efficiency.stop_efficiency_index

    if outcome == TradeOutcome.TARGET_HIT:
        success.append("TARGET_REACHED")
        if mfe is not None and mfe >= 1.0:
            success.append("STRONG_MFE")
        if stop_eff is not None and stop_eff < 0.5:
            success.append("SHALLOW_DRAWDOWN")
        root = "TREND_FOLLOWTHROUGH"
    elif outcome == TradeOutcome.STOP_HIT:
        failure.append("STOP_HIT")
        if mfe is not None and abs(mfe) < 0.3:
            failure.append("FAKE_BREAKOUT_MFE_LT_0.3R")
            root = "FAKE_BREAKOUT"
        elif mae is not None and abs(mae) >= 0.9:
            failure.append("FULL_STOP_TRAVERSAL")
            root = "ADVERSE_TRAJECTORY"
        else:
            root = "STOP_BEFORE_FOLLOWTHROUGH"
        if confidence >= 0.7:
            false_pos = True
            failure.append("HIGH_SCORE_LOSER")
    elif outcome == TradeOutcome.NO_ENTRY:
        failure.append("ENTRY_NEVER_TRIGGERED")
        root = "NO_TRIGGER"
    elif outcome == TradeOutcome.EOD_SQUAREOFF:
        if realized_pnl_pct > 0:
            success.append("POSITIVE_EOD_SQUAREOFF")
            root = "PARTIAL_FOLLOWTHROUGH"
        else:
            failure.append("NEGATIVE_OR_FLAT_EOD")
            root = "STALLED_TRADE"

    return success, failure, root, false_pos


# ---------------------------------------------------------------------------
# Missed opportunities
# ---------------------------------------------------------------------------

def scan_missed_opportunities(
    snapshot: dict[str, Any] | None,
    selected_symbols: set[str],
    threshold_pct: float = 2.0,
) -> list[MissedOpportunity]:
    if not snapshot:
        return []
    quotes = snapshot.get("stockQuotes") or {}
    rows: list[dict[str, Any]] = []
    if isinstance(quotes, dict):
        rows = list(quotes.values())
    elif isinstance(quotes, list):
        rows = quotes

    missed: list[MissedOpportunity] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
        if not ticker or ticker in selected_symbols:
            continue
        chg = _parse_delta(row.get("delta"))
        if chg is None or abs(chg) < threshold_pct:
            continue
        # Prefer hard filter / session filter reasons when present
        reasons: list[str] = []
        intra = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
        hf = intra.get("hard_filter_reasons") or row.get("hard_filter_reasons")
        if isinstance(hf, list) and hf:
            reasons = [str(r) for r in hf]
        elif row.get("passes_hard_filters") is False:
            reasons = ["failed_hard_filters"]
        else:
            try:
                ok, fr = _passes_filters(row)
                if not ok:
                    reasons = fr
                else:
                    reasons = ["passed_filters_not_selected"]
            except Exception:
                reasons = ["unselected_mover"]

        missed.append(
            MissedOpportunity(
                ticker=ticker,
                day_change_pct=_round(chg, 3),
                filter_reasons=reasons,
                potential_move_pct=_round(chg, 3),
            )
        )

    missed.sort(key=lambda m: abs(m.day_change_pct or 0), reverse=True)
    return missed[:25]


# ---------------------------------------------------------------------------
# Calibration (ECE / Brier) — confidence = score/100
# ---------------------------------------------------------------------------

def compute_calibration(
    scorecards: list[TradeScorecardNode],
    n_bins: int = 10,
) -> tuple[float | None, float | None]:
    pairs: list[tuple[float, int]] = []
    for sc in scorecards:
        if sc.outcome == TradeOutcome.NO_ENTRY:
            continue
        y = 1 if sc.realized_pnl_pct > 0 else 0
        pairs.append((sc.confidence_score, y))
    if not pairs:
        return None, None

    brier = statistics.mean((p - y) ** 2 for p, y in pairs)

    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        bins[idx].append((p, y))

    ece = 0.0
    n = len(pairs)
    for bucket in bins:
        if not bucket:
            continue
        conf = statistics.mean(p for p, _ in bucket)
        acc = statistics.mean(y for _, y in bucket)
        ece += (len(bucket) / n) * abs(conf - acc)

    return _round(ece, 4), _round(brier, 4)


# ---------------------------------------------------------------------------
# Scorecard builder
# ---------------------------------------------------------------------------

def build_scorecard(
    pick: dict[str, Any],
    candles: list[dict[str, Any]],
    snapshot: dict[str, Any] | None,
) -> TradeScorecardNode:
    symbol = pick["symbol"]
    direction = pick["direction"]
    entry = float(pick["entryPrice"])
    stop = float(pick["stopLoss"])
    target = float(pick["target1"])
    score = _safe_float(pick.get("score")) or 0.0
    confidence = max(0.0, min(1.0, score / 100.0))

    path = _resolve_path_outcome(candles, entry, stop, target, direction)
    outcome: TradeOutcome = path["outcome"]
    fill = path["fill_price"]
    exit_px = path["exit_price"]
    entry_idx = path["entry_idx"]
    exit_idx = path["exit_idx"]

    # Fallback to plan outcome label when no candles
    if not candles and isinstance(pick.get("outcome"), dict):
        label = str(pick["outcome"].get("label") or "").upper()
        hit = pick["outcome"].get("hitLevel")
        if hit in ("t1", "t2") or "TARGET" in label:
            outcome = TradeOutcome.TARGET_HIT
            exit_px = target
            fill = entry
        elif hit == "sl" or "STOP" in label or "SL" in label:
            outcome = TradeOutcome.STOP_HIT
            exit_px = stop
            fill = entry
        elif "NOT TRIGGERED" in label:
            outcome = TradeOutcome.NO_ENTRY
            fill = None
            exit_px = None

    realized = 0.0
    if fill is not None and exit_px is not None and outcome != TradeOutcome.NO_ENTRY:
        realized = _pnl_pct(direction, fill, exit_px)

    qty = int(pick.get("approxQty") or 0)
    pnl_abs = None
    if fill is not None and exit_px is not None and qty:
        sign = 1 if direction == "LONG" else -1
        pnl_abs = sign * (exit_px - fill) * qty

    efficiency = compute_efficiency(
        candles, entry_idx, exit_idx, fill, exit_px, stop, direction, realized
    )
    tca = compute_modeled_tca(candles, entry, fill, entry_idx, direction, efficiency)
    attribution = compute_attribution(pick, realized, snapshot)
    counterfactuals = simulate_counterfactuals(
        candles,
        entry_idx,
        fill,
        stop,
        target,
        direction,
        _safe_float(pick.get("atrPct")),
        realized,
    )
    success, failure, root, false_pos = classify_root_cause(
        outcome, efficiency, confidence, realized
    )

    hold = None
    if entry_idx is not None and exit_idx is not None and candles:
        hold = _mins_between(
            _parse_ts(candles[entry_idx].get("ts")),
            _parse_ts(candles[exit_idx].get("ts")),
        )

    trade_id = f"{symbol}:{direction}"
    return TradeScorecardNode(
        trade_id=trade_id,
        ticker=symbol,
        direction=direction,  # type: ignore[arg-type]
        confidence_score=round(confidence, 4),
        confidence_basis="FACTOR_SCORE",
        entry_price=_round(fill),
        exit_price=_round(exit_px),
        stop_loss=stop,
        target_price=target,
        signal_entry_price=_round(entry),
        outcome=outcome,
        realized_pnl_pct=_round(realized, 4) or 0.0,
        realized_pnl_abs=_round(pnl_abs, 2),
        holding_duration_mins=hold,
        sector=pick.get("sector"),
        score=_round(score, 2),
        qty=qty or None,
        deployed_capital=_round(_safe_float(pick.get("deployedCapital")), 2),
        risk_per_share=_round(_safe_float(pick.get("riskPerShare")), 4),
        tca=tca,
        efficiency=efficiency,
        attribution=attribution,
        counterfactuals=counterfactuals,
        success_factors=success,
        failure_factors=failure,
        root_cause=root,
        false_positive=false_pos,
        timeline_events=path.get("events") or [],
        factor_breakdown=pick.get("factorBreakdown"),
    )


# ---------------------------------------------------------------------------
# Executive metrics
# ---------------------------------------------------------------------------

def build_executive_summary(
    scorecards: list[TradeScorecardNode],
    regime_breadth: RegimeBreadth,
    missed: list[MissedOpportunity],
    capital: dict[str, Any] | None,
) -> ExecutiveSummary:
    total = len(scorecards)
    wins = sum(1 for s in scorecards if s.realized_pnl_pct > 0 and s.outcome != TradeOutcome.NO_ENTRY)
    losses = sum(1 for s in scorecards if s.realized_pnl_pct < 0 and s.outcome != TradeOutcome.NO_ENTRY)
    no_entry = sum(1 for s in scorecards if s.outcome == TradeOutcome.NO_ENTRY)
    decided = wins + losses
    win_rate = (wins / decided * 100.0) if decided else None

    # Avg RR from |win|/|loss| means
    win_pnls = [s.realized_pnl_pct for s in scorecards if s.realized_pnl_pct > 0]
    loss_pnls = [abs(s.realized_pnl_pct) for s in scorecards if s.realized_pnl_pct < 0]
    avg_rr = None
    if win_pnls and loss_pnls:
        avg_rr = statistics.mean(win_pnls) / statistics.mean(loss_pnls)

    deployed = sum(float(s.deployed_capital or 0) for s in scorecards)
    pnl_abs = sum(float(s.realized_pnl_abs or 0) for s in scorecards)
    long_cap = _safe_float((capital or {}).get("longCapital")) or 0.0
    short_cap = _safe_float((capital or {}).get("shortCapital")) or 0.0
    total_cap = long_cap + short_cap
    if total_cap <= 0:
        total_cap = deployed or None

    net_ret = None
    if total_cap and total_cap > 0:
        net_ret = pnl_abs / total_cap * 100.0
    elif scorecards:
        net_ret = statistics.mean(s.realized_pnl_pct for s in scorecards)

    cap_eff = None
    if total_cap and total_cap > 0 and deployed > 0:
        cap_eff = deployed / total_cap * 100.0

    ece, brier = compute_calibration(scorecards)
    fp_count = sum(1 for s in scorecards if s.false_positive)

    # Institutional score 0-10 from win rate, ECE, net return
    score = 5.0
    if win_rate is not None:
        score += (win_rate - 50.0) / 20.0
    if net_ret is not None:
        score += max(-2.0, min(2.0, net_ret))
    if ece is not None:
        score += 1.0 if ece < 0.05 else (-1.0 if ece > 0.15 else 0.0)
    score = max(0.0, min(10.0, score))

    return ExecutiveSummary(
        overall_institutional_score=_round(score, 2) or 0.0,
        total_trades=total,
        win_trades=wins,
        loss_trades=losses,
        no_entry_trades=no_entry,
        win_rate_pct=_round(win_rate, 2),
        average_risk_reward=_round(avg_rr, 3),
        net_strategy_return_pct=_round(net_ret, 4),
        capital_efficiency_pct=_round(cap_eff, 2),
        expected_calibration_error=ece,
        brier_score=brier,
        market_regime=regime_breadth.market_regime,
        regime_breadth=regime_breadth,
        missed_opportunities=missed,
        false_positive_count=fp_count,
    )


# ---------------------------------------------------------------------------
# Learning proposals (N>=30 guard; never mutates live params)
# ---------------------------------------------------------------------------

def _load_historical_scorecards(exclude_date: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not os.path.isdir(EOD_DATA_ROOT):
        return rows
    for name in os.listdir(EOD_DATA_ROOT):
        if exclude_date and name == exclude_date:
            continue
        path = os.path.join(EOD_DATA_ROOT, name, "scorecards.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
            items = data if isinstance(data, list) else data.get("scorecards") or []
            for item in items:
                if isinstance(item, dict):
                    rows.append(item)
        except Exception:
            continue
    return rows


def generate_learning_proposals(
    scorecards: list[TradeScorecardNode],
    analysis_date: str,
) -> list[StrategyImprovementProposal]:
    """Statistical scan only — emits proposals; never writes strategy configs."""
    historical = _load_historical_scorecards(exclude_date=analysis_date)
    # Include today's cards in the sample pool for counting
    today_dicts = [s.model_dump() for s in scorecards]
    pool = historical + today_dicts
    n = len([r for r in pool if r.get("outcome") != "NO_ENTRY"])

    proposals: list[StrategyImprovementProposal] = []

    # Proposal 1: stop-distance vs MAE
    stop_effs = [
        float(r.get("efficiency", {}).get("stop_efficiency_index"))
        for r in pool
        if isinstance(r.get("efficiency"), dict)
        and r.get("efficiency", {}).get("stop_efficiency_index") is not None
        and r.get("outcome") == "STOP_HIT"
    ]
    status = (
        ProposalStatus.PENDING_REVIEW
        if n >= MIN_PROPOSAL_SAMPLES
        else ProposalStatus.INSUFFICIENT_SAMPLES
    )
    mean_eff = statistics.mean(stop_effs) if stop_effs else None
    proposals.append(
        StrategyImprovementProposal(
            proposal_id=f"{analysis_date}-stop-distance",
            parameter_name="stop_atr_multiple",
            current_value="plan_levels",
            proposed_value="widen_1.2x" if (mean_eff is not None and mean_eff > 0.85) else "hold",
            expected_pnl_uplift_pct=_round(2.0 if status == ProposalStatus.PENDING_REVIEW else None, 2)
            if status == ProposalStatus.PENDING_REVIEW and mean_eff and mean_eff > 0.85
            else None,
            confidence_interval="n/a" if status == ProposalStatus.INSUFFICIENT_SAMPLES else "95% CI provisional",
            supporting_evidence={
                "sample_count": n,
                "stop_hit_samples": len(stop_effs),
                "mean_stop_efficiency_index": _round(mean_eff, 4),
                "rule": "If mean stop_efficiency_index > 0.85 on stop-hits, stops may be tight vs realized MAE",
                "min_required_samples": MIN_PROPOSAL_SAMPLES,
            },
            status=status,
            sample_count=n,
        )
    )

    # Proposal 2: volume / high-score losers
    high_score_losers = [
        r
        for r in pool
        if float(r.get("confidence_score") or 0) >= 0.7
        and r.get("outcome") == "STOP_HIT"
    ]
    proposals.append(
        StrategyImprovementProposal(
            proposal_id=f"{analysis_date}-volume-multiplier",
            parameter_name="min_volume_multiplier",
            current_value="session_filter",
            proposed_value="raise_threshold",
            expected_pnl_uplift_pct=None,
            confidence_interval="n/a" if n < MIN_PROPOSAL_SAMPLES else "95% CI provisional",
            supporting_evidence={
                "sample_count": n,
                "high_score_stop_hits": len(high_score_losers),
                "rule": "High factor-score stop-hits suggest tightening volume/liquidity gates",
                "min_required_samples": MIN_PROPOSAL_SAMPLES,
            },
            status=status,
            sample_count=n,
        )
    )

    return proposals


# ---------------------------------------------------------------------------
# PM commentary (schema-bound LLM with deterministic fallback)
# ---------------------------------------------------------------------------

def build_pm_commentary(
    executive: ExecutiveSummary,
    scorecards: list[TradeScorecardNode],
    proposals: list[StrategyImprovementProposal],
    *,
    allow_llm: bool = False,
    cached: PMCommentary | None = None,
) -> PMCommentary:
    """Build PM commentary.

    LLM is opt-in only (`allow_llm=True`). Refresh / default runs use cached
    commentary or a deterministic fact summary — never call the model on
    every request.
    """
    if cached is not None and not allow_llm:
        return cached

    facts = {
        "overall_score": executive.overall_institutional_score,
        "win_rate_pct": executive.win_rate_pct,
        "net_return_pct": executive.net_strategy_return_pct,
        "ece": executive.expected_calibration_error,
        "brier": executive.brier_score,
        "regime": executive.market_regime.value,
        "false_positives": executive.false_positive_count,
        "trades": [
            {
                "ticker": s.ticker,
                "direction": s.direction,
                "outcome": s.outcome.value,
                "pnl_pct": s.realized_pnl_pct,
                "confidence": s.confidence_score,
                "root_cause": s.root_cause,
                "tca_basis": s.tca.basis.value,
                "delay_bps": s.tca.delay_cost_bps,
            }
            for s in scorecards
        ],
        "proposals": [
            {
                "id": p.proposal_id,
                "parameter": p.parameter_name,
                "status": p.status.value,
                "samples": p.sample_count,
            }
            for p in proposals
        ],
    }

    if allow_llm:
        llm_result = _try_llm_commentary(facts)
        if llm_result is not None:
            return llm_result

    # Deterministic fallback from computed facts only
    wr = executive.win_rate_pct
    nr = executive.net_strategy_return_pct
    exec_sum = (
        f"Institutional score {executive.overall_institutional_score}/10 on "
        f"{executive.market_regime.value}. "
        f"Trades={executive.total_trades}, wins={executive.win_trades}, "
        f"losses={executive.loss_trades}, no-entry={executive.no_entry_trades}. "
        f"Win rate={wr if wr is not None else '—'}%, "
        f"net return={nr if nr is not None else '—'}%."
    )
    attr = (
        f"False-positive high-score losers={executive.false_positive_count}. "
        f"ECE={executive.expected_calibration_error if executive.expected_calibration_error is not None else '—'} "
        f"(confidence_basis=FACTOR_SCORE). "
        f"Missed movers scanned={len(executive.missed_opportunities)}."
    )
    exec_review = (
        "Execution is MANUAL_ONLY; TCA fields are MODELED from 1-min candles. "
        "Spread and market-impact are null (no OMS fills). "
        f"Sample delay_cost_bps values drawn from scorecards with basis=MODELED."
    )
    directives = []
    for p in proposals:
        directives.append(
            f"{p.parameter_name}: {p.current_value} → {p.proposed_value} "
            f"[{p.status.value}, N={p.sample_count}]"
        )
    if not directives:
        directives.append("No proposals generated.")

    return PMCommentary(
        executive_summary=exec_sum,
        attribution_narrative=attr,
        execution_and_slippage_review=exec_review,
        actionable_directives=directives,
        source="DETERMINISTIC_FALLBACK",
    )


def _compact_pm_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Shrink LLM input so the model can finish valid JSON (avoid truncation)."""
    trades = list(facts.get("trades") or [])
    # Prefer losers + no-entry for narrative; cap total rows.
    ranked = sorted(
        trades,
        key=lambda t: (
            0 if str(t.get("outcome") or "").upper() in {"STOP_HIT", "EOD_SQUAREOFF"} else 1,
            float(t.get("pnl_pct") or 0.0),
        ),
    )
    compact_trades = [
        {
            "ticker": t.get("ticker"),
            "outcome": t.get("outcome"),
            "pnl_pct": t.get("pnl_pct"),
            "root_cause": t.get("root_cause"),
        }
        for t in ranked[:12]
    ]
    return {
        "overall_score": facts.get("overall_score"),
        "win_rate_pct": facts.get("win_rate_pct"),
        "net_return_pct": facts.get("net_return_pct"),
        "ece": facts.get("ece"),
        "brier": facts.get("brier"),
        "regime": facts.get("regime"),
        "false_positives": facts.get("false_positives"),
        "trade_count": len(trades),
        "trades_sample": compact_trades,
        "proposals": facts.get("proposals") or [],
    }


def _parse_llm_json_object(text: str) -> dict[str, Any]:
    """Parse LLM JSON; strip fences and extract first object if needed."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if "```" in cleaned:
            cleaned = cleaned[: cleaned.index("```")]
        cleaned = cleaned.strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM commentary JSON must be an object")
    return data


def _try_llm_commentary(facts: dict[str, Any]) -> PMCommentary | None:
    if not _llm_quota_available():
        return None
    provider, api_key, api_url, model, oauth_token_path = _llm_config()
    if not provider or not api_key:
        return None

    system = (
        "You are an institutional PM writing EOD research. "
        "Use ONLY the provided JSON facts. Do not invent metrics, fills, or spreads. "
        "Return strict JSON with keys: executive_summary, attribution_narrative, "
        "execution_and_slippage_review, actionable_directives (array of strings). "
        "Keep each string under 400 characters. No markdown."
    )
    prompt = (
        "Produce PM commentary from these computed EOD facts only:\n"
        + json.dumps(_compact_pm_facts(facts), default=str)[:6000]
    )
    try:
        if provider == "gemini":
            text = _call_gemini(
                prompt=prompt,
                api_key=api_key,
                model=model,
                system_instruction=system,
                timeout=min(45, LLM_CALL_TIMEOUT_SECONDS),
                oauth_token_path=oauth_token_path,
            )
        elif provider == "openai":
            text = _call_openai(
                prompt, api_key, api_url, model, timeout=min(45, LLM_CALL_TIMEOUT_SECONDS)
            )
        else:
            return None
        data = _parse_llm_json_object(text)
        return PMCommentary(
            executive_summary=str(data.get("executive_summary") or ""),
            attribution_narrative=str(data.get("attribution_narrative") or ""),
            execution_and_slippage_review=str(data.get("execution_and_slippage_review") or ""),
            actionable_directives=[str(x) for x in (data.get("actionable_directives") or [])],
            source="LLM",
        )
    except Exception as exc:
        log.warning("PM commentary LLM failed: %s", exc)
        return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
