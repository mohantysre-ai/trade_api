"""Live radar compose: Angel → ScanX → Lemonn, plus session replay routing."""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Callable

from .angel_index_options import (
    _apply_oi_baselines,
    _effective_breadth_gate,
    active_index_expiries,
    cached_angel_index_option_snapshot,
    option_data_to_strategy_inputs,
    persist_radar,
    unavailable_provider_snapshot,
)
from .angel_one_feed import ensure_fresh_market_snapshot
from .angel_index_stream import ANGEL_INDEX_STREAM
from .dhan_scanx_options import apply_scanx_fallback
from .index_options_engine import build_index_options_radar
from .index_options_paper import index_options_market_open, reconcile_paper_book
from .index_options_replay import parse_session_date, replay_index_options_session
from .lemonn_options import LEMONN_SLUGS, apply_lemonn_fallback, discover_lemonn_expiries
from .trendlyne_oi import apply_oi_enrichment


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _live_structural_levels(row: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Return the original structural stop, live target and opening-range width.

    The structural stop remains anchored to the confirmed candle structure, but
    reward is re-valued from the current streamed spot rather than the last
    completed five-minute close.
    """
    direction = str(row.get("direction") or "").upper()
    structure = row.get("structure") if isinstance(row.get("structure"), dict) else {}
    spot = _float(row.get("spot"))
    structure_entry = _float(structure.get("last"))
    ema9 = _float(structure.get("ema9"))
    orb_high = _float(structure.get("orbHigh"))
    orb_low = _float(structure.get("orbLow"))
    atr = _float(structure.get("atr5m"))
    if direction not in {"CALL", "PUT"} or not spot or not structure_entry or not ema9 or not orb_high or not orb_low or not atr:
        return None, None, None
    opening_range = orb_high - orb_low
    if opening_range <= 0:
        return None, None, None
    if direction == "CALL":
        stops = [level for level in (orb_high, ema9) if level < structure_entry]
        stop = max(stops) if stops else None
        targets = [orb_high + opening_range, spot + atr]
        target = min((level for level in targets if level > spot), default=None)
    else:
        stops = [level for level in (orb_low, ema9) if level > structure_entry]
        stop = min(stops) if stops else None
        targets = [orb_low - opening_range, spot - atr]
        target = max((level for level in targets if level < spot), default=None)
    return stop, target, opening_range


def _refresh_live_breadth_confirmation(row: dict[str, Any], expected_r: float) -> None:
    """Re-evaluate adaptive breadth after live spot changes contract R:R.

    Initial breadth confirmation is computed from the last completed candle.
    The live risk guard then re-prices entry economics from streamed spot.  The
    old implementation updated only the R:R gate, leaving breadth blocked by
    stale pre-live economics.  Always restart from ``strictAligned`` so an old
    adaptive result cannot carry forward without current independent evidence.
    """
    direction = str(row.get("direction") or "").upper()
    evidence = row.get("gateEvidence") if isinstance(row.get("gateEvidence"), dict) else {}
    breadth = evidence.get("breadth") if isinstance(evidence.get("breadth"), dict) else row.get("breadth")
    futures = evidence.get("futuresOi") if isinstance(evidence.get("futuresOi"), dict) else {}
    chain = evidence.get("optionChain") if isinstance(evidence.get("optionChain"), dict) else {}
    economics = evidence.get("contractEconomics") if isinstance(evidence.get("contractEconomics"), dict) else {}
    if not isinstance(breadth, dict) or direction not in {"CALL", "PUT"}:
        return
    oi_state = str(futures.get("state") or "").upper()
    strong_oi = (direction == "CALL" and oi_state == "LONG_BUILDUP") or (
        direction == "PUT" and oi_state == "SHORT_BUILDUP"
    )
    base_breadth = {**breadth, "aligned": breadth.get("strictAligned")}
    refreshed = _effective_breadth_gate(
        base_breadth,
        strong_oi=strong_oi,
        chain_aligned=chain.get("aligned"),
        expected_r=expected_r,
        spread_pct=_float(economics.get("spreadPct")),
        vix_regime=str(row.get("vixRegime") or "").upper() or None,
    )
    row["breadth"] = refreshed
    evidence["breadth"] = refreshed
    row.setdefault("gates", {})["breadth"] = refreshed.get("aligned")


def _apply_live_spot_risk_guard(strategy_inputs: dict[str, Any]) -> dict[str, Any]:
    """Re-value option risk from live spot and block intrabar stop violations.

    The candle structure still defines the setup. Once a setup exists, however,
    the current streamed index price is the only valid entry reference. A setup
    is invalidated immediately when live spot crosses its original structural
    stop, even if the five-minute candle has not closed yet.

    To prevent a 1-3 point structural stop from manufacturing unrealistic 9R+
    readings, modelled underlying risk is floored at the largest of:
      * current spot-to-structural-stop distance,
      * 20% of five-minute ATR, and
      * one quoted option spread translated back into underlying points by delta.
    """
    indices = strategy_inputs.get("indices") if isinstance(strategy_inputs.get("indices"), dict) else {}
    for row in indices.values():
        if not isinstance(row, dict):
            continue
        direction = str(row.get("direction") or "").upper()
        spot = _float(row.get("spot"))
        contract = row.get("contract") if isinstance(row.get("contract"), dict) else None
        structure = row.get("structure") if isinstance(row.get("structure"), dict) else {}
        if direction not in {"CALL", "PUT"} or not spot or not contract:
            continue

        stop, target, opening_range = _live_structural_levels(row)
        atr = _float(structure.get("atr5m"))
        premium = _float(contract.get("ltp"))
        delta = abs(_float(contract.get("delta")) or 0.0)
        gamma = abs(_float(contract.get("gamma")) or 0.0)
        gate_evidence = row.setdefault("gateEvidence", {})
        economics = gate_evidence.get("contractEconomics") if isinstance(gate_evidence.get("contractEconomics"), dict) else {}
        spread_pct = max(0.0, _float(economics.get("spreadPct")) or 0.0)
        gates = row.setdefault("gates", {})
        limitations = row.setdefault("dataLimitations", [])
        if not isinstance(limitations, list):
            limitations = []
            row["dataLimitations"] = limitations

        invalidated = bool(
            stop is not None and (
                (direction == "CALL" and spot <= stop) or
                (direction == "PUT" and spot >= stop)
            )
        )
        if invalidated:
            gates["structure"] = False
            gates["breakout"] = False
            gates["riskReward"] = False
            row["expectedR"] = 0.0
            if "LIVE_SPOT_CROSSED_STRUCTURAL_STOP" not in limitations:
                limitations.append("LIVE_SPOT_CROSSED_STRUCTURAL_STOP")
            gate_evidence["riskReward"] = {
                "expectedR": 0.0,
                "aligned": False,
                "minimumR": 1.5,
                "basis": "LIVE_SPOT_STRUCTURAL_INVALIDATION",
                "entryUnderlying": round(spot, 4),
                "stop": round(stop, 4),
                "target": round(target, 4) if target is not None else None,
                "liveInvalidated": True,
            }
            continue

        if stop is None or target is None or not atr or not premium or delta <= 0 or not opening_range:
            continue

        structural_risk = abs(spot - stop)
        atr_floor = atr * 0.20
        spread_cost = premium * spread_pct / 100.0
        spread_underlying = spread_cost / delta if spread_cost > 0 else 0.0
        risk_move = max(structural_risk, atr_floor, spread_underlying)
        reward_move = abs(target - spot)
        theoretical_loss = delta * risk_move - 0.5 * gamma * risk_move * risk_move
        theoretical_gain = delta * reward_move + 0.5 * gamma * reward_move * reward_move
        option_loss = max(theoretical_loss + spread_cost, spread_cost, 0.05)
        option_gain = max(theoretical_gain - spread_cost, 0.0)
        expected_r = round(option_gain / option_loss, 3) if option_loss > 0 else 0.0
        row["expectedR"] = expected_r
        gates["riskReward"] = expected_r >= 1.5
        gate_evidence["riskReward"] = {
            "expectedR": expected_r,
            "aligned": expected_r >= 1.5,
            "minimumR": 1.5,
            "basis": "LIVE_SPOT_ORB_INVALIDATION_WITH_ATR_SPREAD_RISK_FLOOR",
            "entryUnderlying": round(spot, 4),
            "stop": round(stop, 4),
            "target": round(target, 4),
            "riskPoints": round(risk_move, 4),
            "structuralRiskPoints": round(structural_risk, 4),
            "atrRiskFloorPoints": round(atr_floor, 4),
            "spreadEquivalentUnderlyingPoints": round(spread_underlying, 4),
            "rewardPoints": round(reward_move, 4),
            "projectedOptionLoss": round(option_loss, 4),
            "projectedOptionGain": round(option_gain, 4),
            "spreadCost": round(spread_cost, 4),
            "atr5m": round(atr, 4),
            "openingRangePoints": round(opening_range, 4),
            "liveInvalidated": False,
        }
        _refresh_live_breadth_confirmation(row, expected_r)
    return strategy_inputs


def compose_live_index_options_radar(
    snapshot: dict[str, Any],
    *,
    live: bool = True,
    client: Any,
    persist: bool = True,
    scanx_fn: Callable[..., dict[str, Any]] = apply_scanx_fallback,
    lemonn_fn: Callable[..., dict[str, Any]] = apply_lemonn_fallback,
    lemonn_discover_fn: Callable[..., dict[str, date]] = discover_lemonn_expiries,
    oi_enrichment_fn: Callable[..., dict[str, Any]] = apply_oi_enrichment,
    expiries_fn: Callable[..., dict[str, date]] = active_index_expiries,
    snapshot_fn: Callable[..., dict[str, Any]] = cached_angel_index_option_snapshot,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the live radar. Lemonn fills indexes still unusable after ScanX."""
    book = ensure_fresh_market_snapshot(snapshot, reason="index_options_breadth")
    option_data: dict[str, Any] | None = None
    if live:
        try:
            option_data = snapshot_fn(client)
        except Exception as exc:
            option_data = unavailable_provider_snapshot(exc)
        expiries: dict[str, date] = {}
        try:
            expiries.update(expiries_fn())
        except Exception as exc:
            option_data["fallbackSource"] = "SCANX"
            option_data["expiryMasterError"] = str(exc)
        missing_expiry = [key for key in LEMONN_SLUGS if key not in expiries]
        if missing_expiry:
            try:
                expiries.update(lemonn_discover_fn(missing_expiry))
            except Exception:
                pass
        try:
            option_data = scanx_fn(option_data, expiries)
        except Exception as exc:
            option_data["fallbackSource"] = "SCANX"
            option_data["fallbackError"] = str(exc)
        try:
            option_data = lemonn_fn(option_data, expiries)
        except Exception as exc:
            option_data["thirdFallbackSource"] = "LEMONN"
            option_data["thirdFallbackError"] = str(exc)
        try:
            option_data = oi_enrichment_fn(option_data, expiries)
        except Exception as exc:
            option_data["oiEnrichment"] = {
                "source": "SIGQ_RESEARCH",
                "status": "UNAVAILABLE",
                "error": str(exc),
            }
        option_data = _apply_oi_baselines(option_data)
        strategy_inputs = option_data_to_strategy_inputs(option_data, book)
        book["indexOptions"] = _apply_live_spot_risk_guard(strategy_inputs)
        book["indexOptionProvider"] = option_data
    result = build_index_options_radar(book)
    market_open = index_options_market_open(now)
    result["paperBook"] = reconcile_paper_book(result, client=client, persist=persist, now=now)
    result["sessionStatus"] = "OPEN" if market_open else "CLOSED"
    result["huntActive"] = market_open
    result["limits"]["huntMode"] = "CONTINUOUS_MARKET_SESSION" if market_open else "SESSION_CLOSED"
    result["provider"] = "ANGEL_ONE_WITH_SCANX_AND_LEMONN_FALLBACK"
    result["providerEvidence"] = book.get("indexOptionProvider")
    result["streamStatus"] = ANGEL_INDEX_STREAM.status()
    if persist:
        persist_radar(result)
    return result


def finalize_closed_index_options_radar(
    radar: dict[str, Any], *, client: Any, persist: bool = True, now: datetime | None = None,
) -> dict[str, Any]:
    """Freeze decisions after close while marking/squaring off an existing paper book.

    This deliberately avoids a full chain/futures/candle refresh after the entry
    session. Direct quotes are requested only for contracts already in the book.
    """
    result = dict(radar)
    result["paperBook"] = reconcile_paper_book(result, client=client, persist=persist, now=now)
    result["sessionStatus"] = "CLOSED"
    result["huntActive"] = False
    limits = dict(result.get("limits") or {})
    limits["huntMode"] = "SESSION_CLOSED"
    result["limits"] = limits
    result["cacheStatus"] = "SESSION_FROZEN"
    if persist:
        persist_radar(result)
    return result


def replay_session_payload(
    client: Any,
    raw_session_date: str,
    *,
    today: date | None = None,
    persist: bool = True,
    master: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Closed-session replay. Invalid dates raise ValueError for the HTTP layer."""
    replay_day = parse_session_date(raw_session_date, today=today)
    try:
        return replay_index_options_session(client, replay_day, persist=persist, master=master)
    except Exception as exc:
        return {
            "success": False,
            "mode": "SESSION_REPLAY",
            "sessionDate": replay_day.isoformat(),
            "executionPolicy": "MANUAL_ONLY",
            "candidates": [],
            "selected": [],
            "buySideContracts": [],
            "implemented": [],
            "error": str(exc),
        }
