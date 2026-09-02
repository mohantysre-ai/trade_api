"""Post-market-close swing analysis for the locked swing portfolio.

Uses real close marks (snapshot / Yahoo) vs entry — never mock 0→false SL_HIT.
Book symbols come only from date-matched swing_session (Asset Matrix lock).
"""
from __future__ import annotations

import logging
import json
import os
from datetime import date, datetime
from typing import Any

from .trade_outcome import get_alert_history, _today_ist
from .eod_reference import get_close_mark_price, get_reference_price, generate_swing_analysis
from .eod_intraday_report import _build_levels_diagnostic, _exit_reason_from_scale_eval
from .exit_plan import attach_exit_plan, blended_pnl_from_state, format_scale_progress, refresh_exit_policy
from .quant_desk_exit_policy import build_trade_outcome

log = logging.getLogger(__name__)

DEFAULT_SWING_CAPITAL = 1_000_000.0  # ₹10L
DAY_BUCKETS = (1, 7, 15, 30)


def _live_direction_conflicts() -> dict[str, str]:
    """Latest persisted scanner direction, used only as a conflict veto."""
    path = os.environ.get("SNAPSHOT_FILE")
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            snap = json.load(fh)
    except Exception:
        return {}
    picks = snap.get("scannerPicks") if isinstance(snap, dict) else None
    out: dict[str, str] = {}
    if isinstance(picks, dict):
        for raw in picks.values():
            if not isinstance(raw, dict):
                continue
            sym = str(raw.get("symbol") or "").upper().strip()
            direction = str(raw.get("direction") or "").upper().strip()
            if sym and direction in {"LONG", "SHORT"}:
                out[sym] = direction
    return out


def _signal_conflict_row(pick: dict[str, Any], live_direction: str) -> dict[str, Any]:
    symbol = str(pick.get("symbol") or "").upper()
    locked_direction = str(pick.get("direction") or "LONG").upper()
    return {
        "symbol": symbol,
        "direction": locked_direction,
        "entryDate": pick.get("entryDate"),
        "entryPrice": pick.get("entryPrice"),
        "currentPrice": pick.get("currentPrice"),
        "stopLoss": pick.get("stopLoss"),
        "target1": pick.get("target1"),
        "target2": pick.get("target2"),
        "qty": pick.get("approxQty") or 0,
        "deployedCapital": 0.0,
        "pnl": 0.0,
        "pnlPct": 0.0,
        "status": "SIGNAL_CONFLICT",
        "exitReason": "SIGNAL_CONFLICT",
        "executionStatus": "NOT_TRIGGERED",
        "outcomeBucket": "SKIPPED",
        "deskExitLabel": "SKIPPED",
        "triggered": False,
        "skipped": True,
        "skipReason": f"locked_{locked_direction.lower()}_live_{live_direction.lower()}",
        "signalConflict": {"lockedDirection": locked_direction, "liveDirection": live_direction},
        "analysis": f"Excluded: locked {locked_direction} conflicts with current scanner {live_direction}.",
        "score": pick.get("score"),
        "lineage": pick.get("lineage"),
    }


def _exit_path_tag(
    *,
    status: str,
    triggered: bool,
    exit_state: dict[str, Any] | None,
    mfe_r: float | None,
) -> str:
    if not triggered:
        return "NEVER_TRIGGERED"
    reason = str(status or "").upper()
    if reason in {"SL_HIT"} and (mfe_r is None or mfe_r < 0.10):
        return "IMMEDIATE_STOP"
    if reason in {"TRAIL_SL_HIT", "TRAIL_SL"}:
        legs = (exit_state or {}).get("legsFilled") or []
        scaled = any(isinstance(x, dict) and isinstance(x.get("r"), (int, float)) for x in legs)
        return "PARTIAL_SCALE_RUNNER_TRAILED" if scaled else "FULL_TRAIL"
    if reason in {"EOD_SQUAREOFF", "OPEN"}:
        return "FULL_EOD"
    if reason.startswith("PARTIAL"):
        return "PARTIAL_SCALE_RUNNER_TRAILED"
    if reason in {"T1_HIT", "T2_HIT"}:
        return "FULL_TRAIL"
    return "FULL_EOD"


def _merge_lineage(
    pick: dict[str, Any],
    *,
    triggered: bool,
    trigger_src: str | None,
    exit_state: dict[str, Any] | None,
    status: str,
    mfe_r: float | None,
) -> dict[str, Any]:
    base = pick.get("lineage") if isinstance(pick.get("lineage"), dict) else {}
    lineage = dict(base)
    lineage.setdefault("source", pick.get("source") or "swing_session")
    lineage.setdefault("score", pick.get("score"))
    lineage.setdefault("selectionReason", pick.get("selectionReason") or pick.get("selection_reason"))
    lineage.setdefault("verdict", pick.get("verdict"))
    lineage.setdefault("sector", pick.get("sector"))
    lineage.setdefault("levelsSource", pick.get("levelsSource"))
    if triggered:
        # A daily OHLC crossing proves that the level traded, but not when.  Do
        # not fabricate a trigger timestamp from the report generation time.
        lineage["triggeredAt"] = base.get("triggeredAt")
        if isinstance(exit_state, dict):
            lineage["executedFills"] = exit_state.get("legsFilled")
    else:
        lineage["triggeredAt"] = None
        lineage["executedFills"] = None
    lineage["exitPathTag"] = _exit_path_tag(
        status=status, triggered=triggered, exit_state=exit_state, mfe_r=mfe_r
    )
    if trigger_src:
        lineage["triggerSource"] = trigger_src
    return lineage


def _days_held(entry_date_str: str | None, as_of: date) -> int | None:
    if not entry_date_str:
        return None
    try:
        entry_date = datetime.fromisoformat(entry_date_str).date() if "T" in entry_date_str else date.fromisoformat(entry_date_str)
    except Exception:
        return None
    return (as_of - entry_date).days


def _day_range_from_pick(pick: dict[str, Any]) -> tuple[float | None, float | None]:
    """Best-effort day high/low from pick / quote fields (never invent)."""
    high = None
    low = None
    for key in ("dayHigh", "high", "High", "day_high"):
        try:
            v = pick.get(key)
            if v is not None and float(v) > 0:
                high = float(v)
                break
        except (TypeError, ValueError):
            pass
    for key in ("dayLow", "low", "Low", "day_low"):
        try:
            v = pick.get(key)
            if v is not None and float(v) > 0:
                low = float(v)
                break
        except (TypeError, ValueError):
            pass
    return high, low


def _entry_was_triggered(
    *,
    direction: str,
    entry: float,
    day_high: float | None,
    day_low: float | None,
    eod_price: float | None,
) -> tuple[bool, str]:
    """Whether price crossed the signal entry today.

    LONG: day high >= entry (or EOD mark >= entry if no high).
    SHORT: day low <= entry (or EOD mark <= entry if no low).
    If no range and no mark → assume triggered at lock (entry ≈ scan LTP).
    """
    if entry <= 0:
        return False, "missing_entry"
    if direction == "LONG":
        if day_high is not None:
            return day_high >= entry, "day_high"
        if eod_price is not None and eod_price > 0:
            return eod_price >= entry * 0.999, "close_mark"
        return True, "assume_lock_fill"
    if day_low is not None:
        return day_low <= entry, "day_low"
    if eod_price is not None and eod_price > 0:
        return eod_price <= entry * 1.001, "close_mark"
    return True, "assume_lock_fill"


def _evaluate_swing_pick(
    pick: dict[str, Any],
    *,
    after_close: bool,
    require_date_matched_mark: bool = False,
) -> dict[str, Any]:
    """Evaluate one swing pick vs reference + real close mark (never mock-0 → SL)."""
    symbol = (pick.get("symbol") or "").upper()
    direction = pick.get("direction", "LONG")
    entry = float(pick.get("entryPrice") or pick.get("buyAbove") or 0)
    qty = int(pick.get("approxQty") or 0)
    sl = float(pick.get("stopLoss") or 0)
    t1 = float(pick.get("target1") or 0)
    t2 = float(pick.get("target2") or 0)
    day_high, day_low = _day_range_from_pick(pick)

    ref_price = get_reference_price(symbol, allow_network=False)
    # Prefetched mark on pick, else live close mark, else session LTP
    eod_price = None
    mark_candidates = (
        (pick.get("_sessionCloseMark"),)
        if require_date_matched_mark
        else (pick.get("_closeMark"), pick.get("currentPrice"))
    )
    for raw in mark_candidates:
        try:
            if raw is not None and float(raw) > 0:
                eod_price = float(raw)
                break
        except (TypeError, ValueError):
            pass
    if eod_price is None and not require_date_matched_mark:
        eod_price = get_close_mark_price(symbol)
    if eod_price is None and not require_date_matched_mark:
        for raw in (pick.get("ltp"), pick.get("scanLtp")):
            try:
                if raw is not None and float(raw) > 0:
                    eod_price = float(raw)
                    break
            except (TypeError, ValueError):
                pass

    base_entry = entry if entry else (ref_price or 0.0)

    if eod_price is None or eod_price <= 0 or not base_entry:
        analysis = generate_swing_analysis(
            symbol, direction, base_entry or 0.0, 0.0, 0.0, 0.0, "NO_MARK"
        )
        lineage = _merge_lineage(
            pick, triggered=False, trigger_src=None, exit_state=None, status="NO_MARK", mfe_r=None
        )
        desk = build_trade_outcome(
            triggered=False,
            realized_pnl=0.0,
            exit_reason="NO_MARK",
            lineage=lineage,
        )
        return {
            "symbol": symbol,
            "direction": direction,
            "entryDate": pick.get("entryDate"),
            "entryPrice": base_entry or None,
            "refPrice930": ref_price,
            "currentPrice": None,
            "stopLoss": sl,
            "target1": t1,
            "target2": t2,
            "qty": qty,
            "plannedCapital": float(pick.get("deployedCapital") or ((base_entry or 0) * qty)),
            "deployedCapital": 0.0,
            "pnl": 0.0,
            "pnlPct": None,
            "status": "NO_MARK",
            "analysis": analysis,
            "executionStatus": desk.get("executionStatus"),
            "outcomeBucket": "SKIPPED",
            "deskExitLabel": "SKIPPED",
            "deskProgress": None,
            "economicR": None,
            "pathR": None,
            "rMultiple": None,
            "lineage": lineage,
            "policyChain": desk.get("policyChain") or desk.get("chain"),
            "missDiagnostic": {
                "isMiss": False,
                "isHit": False,
                "isSkip": True,
                "exitReason": "NO_MARK",
                "rootCause": "MISSING_CLOSE_MARK",
                "factors": ["NO_MARK", "SKIP_PNL"],
                "rMultiple": None,
                "movePct": None,
                "gapToT1Pct": None,
                "gapToT2Pct": None,
                "stopUtilization": None,
                "plannedRr": None,
                "riskPerShare": None,
                "maePct": None,
                "mfePct": None,
                "stopEff": None,
                "falsePositive": False,
                "holdingMins": None,
                "source": "SKIP",
            },
            "markSource": "none",
            "triggered": None,
            "skipped": True,
            "skipReason": "no_close_mark",
        }

    triggered, trigger_src = _entry_was_triggered(
        direction=direction,
        entry=base_entry,
        day_high=day_high,
        day_low=day_low,
        eod_price=eod_price,
    )
    if not triggered:
        analysis = generate_swing_analysis(
            symbol, direction, base_entry, eod_price, 0.0, 0.0, "NOT_TRIGGERED"
        )
        gap_entry_pct = None
        if base_entry and eod_price:
            sign = 1.0 if direction == "LONG" else -1.0
            gap_entry_pct = round(sign * (eod_price - base_entry) / base_entry * 100.0, 2)
        lineage = _merge_lineage(
            pick,
            triggered=False,
            trigger_src=trigger_src,
            exit_state=None,
            status="NOT_TRIGGERED",
            mfe_r=None,
        )
        desk = build_trade_outcome(
            triggered=False,
            realized_pnl=0.0,
            exit_reason="NOT_TRIGGERED",
            entry=base_entry,
            direction=direction,
            day_high=day_high,
            day_low=day_low,
            trigger_source=trigger_src,
            lineage=lineage,
        )
        return {
            "symbol": symbol,
            "direction": direction,
            "entryDate": pick.get("entryDate"),
            "entryPrice": base_entry,
            "refPrice930": ref_price,
            "currentPrice": eod_price,
            "dayHigh": day_high,
            "dayLow": day_low,
            "stopLoss": sl,
            "target1": t1,
            "target2": t2,
            "qty": qty,
            "deployedCapital": 0.0,
            "pnl": 0.0,
            "pnlPct": 0.0,
            "status": "NOT_TRIGGERED",
            "analysis": analysis,
            "executionStatus": desk.get("executionStatus"),
            "outcomeBucket": desk.get("outcomeBucket"),
            "deskExitLabel": desk.get("deskExitLabel"),
            "deskProgress": None,
            "economicR": None,
            "pathR": None,
            "rMultiple": None,
            "lineage": lineage,
            "policyChain": desk.get("policyChain") or desk.get("chain"),
            "missDiagnostic": {
                "isMiss": False,
                "isHit": False,
                "isSkip": True,
                "exitReason": "NOT_TRIGGERED",
                "rootCause": "ENTRY_NEVER_CROSSED",
                "factors": [
                    "NOT_TRIGGERED",
                    "SKIP_PNL",
                    f"TRIGGER_SRC_{str(trigger_src or 'none').upper()}",
                ],
                "rMultiple": None,
                "movePct": gap_entry_pct,
                "gapToT1Pct": None,
                "gapToT2Pct": None,
                "stopUtilization": None,
                "plannedRr": None,
                "riskPerShare": None,
                "maePct": None,
                "mfePct": None,
                "stopEff": None,
                "falsePositive": False,
                "holdingMins": None,
                "source": "SKIP",
            },
            "markSource": "close_mark",
            "triggered": False,
            "triggerSource": trigger_src,
            "skipped": True,
            "skipReason": "entry_never_crossed",
        }

    sign = 1 if direction == "LONG" else -1
    scale_extra: dict[str, Any] = {}
    used_scale = False
    pnl = 0.0
    pnl_pct = 0.0
    status = "OPEN"

    # Scale-trail blended PnL when exitPlan present or attachable
    work: dict[str, Any] | None = None
    plan = pick.get("exitPlan") if isinstance(pick.get("exitPlan"), dict) else None
    if plan and plan.get("mode") == "SCALE_TRAIL":
        work = refresh_exit_policy(
            {
                **pick,
                "exitPolicyScope": "SWING",
                "entryPrice": base_entry,
                "approxQty": qty,
                "direction": direction,
                "stopLoss": sl or pick.get("stopLoss"),
                "target1": t1 or pick.get("target1"),
                "target2": t2 or pick.get("target2"),
            },
            keep_exit_state=True,
        )
    else:
        risk = float(pick.get("riskPerShare") or 0)
        if base_entry > 0 and qty > 0 and (risk > 0 or sl > 0):
            work = attach_exit_plan({
                **pick,
                "exitPolicyScope": "SWING",
                "entryPrice": base_entry,
                "approxQty": qty,
                "direction": direction,
                "stopLoss": sl or pick.get("stopLoss"),
            })
            attached = work.get("exitPlan") if isinstance(work.get("exitPlan"), dict) else None
            if not attached or attached.get("mode") != "SCALE_TRAIL":
                work = None

    if work is not None:
        if isinstance(pick.get("exitState"), dict) and not work.get("exitState"):
            work["exitState"] = pick["exitState"]
        # Apply the paper strategy's SL/scale/break-even/trail state on every
        # current tick. `after_close` only controls EOD square-off; it must not
        # disable risk controls during the cash session.
        # Daily high/low proves an entry crossing, but contains no event order.
        # Feeding both extremes into the trail engine invents a favourable-first
        # path (and can book a ratchet/stop that never occurred).  Until a
        # timestamped tick ledger exists, value the modeled position from the
        # verified close only.
        total_pnl, avg_exit, eval_result = blended_pnl_from_state(
            work, eod_price, after_close=after_close
        )
        if eval_result:
            used_scale = True
            pnl = float(total_pnl)
            pnl_pct = sign * (avg_exit - base_entry) / base_entry * 100 if base_entry else 0.0
            status = _exit_reason_from_scale_eval(eval_result)
            if not eval_result.get("closed"):
                status = "OPEN"
            exit_state = eval_result.get("exitState")
            scale_extra = {
                "exitPrice": round(float(avg_exit), 2),
                "exitState": exit_state,
                "realizedPnl": eval_result.get("realizedPnl"),
                "unrealizedPnl": eval_result.get("unrealizedPnl"),
                "remainingQty": eval_result.get("remainingQty"),
                "effectiveStop": eval_result.get("effectiveStop"),
                "rMultiple": eval_result.get("economicR", eval_result.get("rMultiple")),
                "economicR": eval_result.get("economicR", eval_result.get("rMultiple")),
                "pathR": eval_result.get("pathR"),
                "scaleTrail": True,
                "exitPlan": work.get("exitPlan"),
                "scaleProgress": format_scale_progress(
                    work.get("exitPlan") if isinstance(work.get("exitPlan"), dict) else None,
                    exit_state if isinstance(exit_state, dict) else None,
                    r_multiple=float(eval_result.get("economicR") or eval_result.get("rMultiple") or 0)
                    if (eval_result.get("economicR") is not None or eval_result.get("rMultiple") is not None)
                    else None,
                ),
            }

    if not used_scale:
        # Legacy binary T1/T2/SL full-qty
        pnl_pct = sign * (eod_price - base_entry) / base_entry * 100
        pnl = sign * (eod_price - base_entry) * qty if qty else 0.0

        if direction == "LONG":
            if t2 > 0 and eod_price >= t2:
                status = "T2_HIT"
            elif t1 > 0 and eod_price >= t1:
                status = "T1_HIT"
            elif sl > 0 and eod_price <= sl:
                status = "SL_HIT"
            else:
                status = "OPEN"
        else:
            if t2 > 0 and eod_price <= t2:
                status = "T2_HIT"
            elif t1 > 0 and eod_price <= t1:
                status = "T1_HIT"
            elif sl > 0 and eod_price >= sl:
                status = "SL_HIT"
            else:
                status = "OPEN"

    analysis = generate_swing_analysis(
        symbol, direction, base_entry, eod_price, pnl or 0.0, pnl_pct, status
    )

    # Deterministic diagnostic — OPEN maps to EOD_SQUAREOFF FactPack shape for Outcome Desk
    diag_reason = None
    if status in ("SL_HIT", "T1_HIT", "T2_HIT", "TRAIL_SL_HIT", "PARTIAL_SCALE", "EOD_SQUAREOFF"):
        diag_reason = status
    elif status == "OPEN":
        diag_reason = "EOD_SQUAREOFF"
    miss_diagnostic = None
    exit_for_diag = eod_price
    if used_scale and scale_extra.get("exitPrice") is not None:
        exit_for_diag = float(scale_extra["exitPrice"])
    elif status == "SL_HIT" and sl > 0:
        exit_for_diag = sl
    elif status == "T1_HIT" and t1 > 0:
        exit_for_diag = t1
    elif status == "T2_HIT" and t2 > 0:
        exit_for_diag = t2
    # The swing trigger is proven by daily OHLC, but its timestamp/order is not
    # known.  Whole-day extrema therefore cannot be represented as post-entry
    # MFE/MAE.  Use the evaluated path/exit state until timestamped bars exist.
    diagnostic_high = pick.get("postEntryHigh")
    diagnostic_low = pick.get("postEntryLow")
    if diag_reason:
        miss_diagnostic = _build_levels_diagnostic(
            {
                **pick,
                "entryPrice": base_entry,
                "stopLoss": sl,
                "target1": t1,
                "target2": t2,
                "direction": direction,
                "rrT2": pick.get("rewardRisk") or pick.get("rrT2"),
                "dayHigh": diagnostic_high,
                "dayLow": diagnostic_low,
            },
            diag_reason,
            exit_for_diag,
            float(pnl or 0),
            day_high=diagnostic_high,
            day_low=diagnostic_low,
        )

    exit_state = scale_extra.get("exitState") if isinstance(scale_extra.get("exitState"), dict) else None
    if not isinstance(exit_state, dict) and isinstance(pick.get("exitState"), dict):
        exit_state = pick["exitState"]
    risk_ps = float(pick.get("riskPerShare") or 0) or None
    if risk_ps is None and base_entry and sl:
        risk_ps = abs(base_entry - sl)

    desk = build_trade_outcome(
        triggered=True,
        realized_pnl=pnl,
        exit_reason=diag_reason or status,
        exit_state=exit_state,
        entry=base_entry,
        exit_price=float(exit_for_diag) if exit_for_diag else eod_price,
        risk_per_share=risk_ps,
        qty=qty,
        direction=direction,
        effective_stop=(
            float(exit_state["effectiveStop"])
            if isinstance(exit_state, dict) and exit_state.get("effectiveStop") is not None
            else (sl or None)
        ),
        day_high=diagnostic_high,
        day_low=diagnostic_low,
        mae_pct=(miss_diagnostic or {}).get("maePct") if miss_diagnostic else None,
        mfe_pct=(miss_diagnostic or {}).get("mfePct") if miss_diagnostic else None,
        stop_utilization=(miss_diagnostic or {}).get("stopUtilization") if miss_diagnostic else None,
        gap_to_t2_pct=(miss_diagnostic or {}).get("gapToT2Pct") if miss_diagnostic else None,
        trigger_source=trigger_src,
        economic_r_hint=scale_extra.get("economicR") if scale_extra.get("economicR") is not None else scale_extra.get("rMultiple"),
        path_r_hint=scale_extra.get("pathR"),
    )
    pnl = float(desk["pnl"])
    lineage = _merge_lineage(
        pick,
        triggered=True,
        trigger_src=trigger_src,
        exit_state=exit_state if isinstance(exit_state, dict) else None,
        status=diag_reason or status,
        mfe_r=desk.get("mfeR"),
    )
    desk["lineage"] = lineage

    if miss_diagnostic:
        if desk.get("rootCause"):
            miss_diagnostic["rootCause"] = desk["rootCause"]
        if desk.get("factors"):
            miss_diagnostic["factors"] = list(desk["factors"])
        miss_diagnostic["isHit"] = bool(desk.get("isHit"))
        miss_diagnostic["isMiss"] = bool(desk.get("isMiss"))
        if desk.get("pathR") is not None:
            miss_diagnostic["pathR"] = desk["pathR"]
        if desk.get("mfeR") is not None:
            miss_diagnostic["mfeR"] = desk["mfeR"]

    if desk.get("deskProgress") and not scale_extra.get("scaleProgress"):
        scale_extra["scaleProgress"] = desk["deskProgress"]
    if desk.get("deskProgress"):
        scale_extra["deskProgress"] = desk["deskProgress"]

    desk_ic = None
    for key in ("deskIcSummary", "deskIc"):
        if isinstance(pick.get(key), dict):
            desk_ic = pick.get(key)
            break

    outcome_bucket = desk.get("outcomeBucket")
    if pnl < 0 and outcome_bucket == "WIN":
        outcome_bucket = "LOSS"

    book_exit_price = scale_extra.get("exitPrice")
    if book_exit_price is None:
        if status == "SL_HIT" and sl > 0:
            book_exit_price = sl
        elif status == "T1_HIT" and t1 > 0:
            book_exit_price = t1
        elif status == "T2_HIT" and t2 > 0:
            book_exit_price = t2
        else:
            book_exit_price = eod_price

    return {
        "symbol": symbol,
        "direction": direction,
        "entryDate": pick.get("entryDate"),
        "entryPrice": base_entry,
        "refPrice930": ref_price,
        "currentPrice": eod_price,
        "exitPrice": round(float(book_exit_price), 2) if book_exit_price is not None else None,
        "dayHigh": day_high,
        "dayLow": day_low,
        "stopLoss": sl,
        "target1": t1,
        "target2": t2,
        "qty": qty,
        "deployedCapital": float(pick.get("deployedCapital") or (base_entry * qty)),
        "pnl": round(pnl, 2) if pnl is not None else None,
        "pnlPct": round(pnl_pct, 2),
        "status": status,
        "analysis": analysis,
        "missDiagnostic": miss_diagnostic,
        "deskIcSummary": desk_ic,
        "selectionReason": pick.get("selectionReason") or pick.get("selection_reason"),
        "score": pick.get("score"),
        "markSource": "close_mark",
        "triggered": True,
        "triggerSource": trigger_src,
        "skipped": False,
        **scale_extra,
        # Desk truth last so scale_extra cannot overwrite table/narrative R
        "executionStatus": desk.get("executionStatus"),
        "outcomeBucket": outcome_bucket,
        "deskExitLabel": desk.get("deskExitLabel"),
        "mfeR": desk.get("mfeR"),
        "maeR": desk.get("maeR"),
        "economicR": desk.get("economicR"),
        "pathR": desk.get("pathR"),
        "effectiveStopR": desk.get("effectiveStopR"),
        "rMultiple": desk.get("economicR") if desk.get("economicR") is not None else desk.get("rMultiple"),
        "deskProgress": desk.get("deskProgress") or scale_extra.get("deskProgress") or scale_extra.get("scaleProgress"),
        "lineage": lineage,
        "policyChain": desk.get("policyChain") or desk.get("chain"),
        "outcomeSchemaVersion": desk.get("outcomeSchemaVersion"),
    }


def _load_swing_book_picks(as_of: date) -> tuple[list[dict[str, Any]], bool, str, dict[str, int]]:
    """Swing Book — locked Asset Matrix BUY portfolio for matching IST date only.

    Read-only: does not call ensure_swing_session_locked (avoids wiping prior-day lock).
    Sizing applied in-memory only when sessionDate matches as_of.
    """
    from .eod_engine.ingestion import load_day_picks
    from .swing_session import apply_swing_sizing, load_swing_session

    day = load_day_picks(as_of)
    desk_counts = dict(day.get("deskCounts") or {})
    swing = day.get("swingSession") if isinstance(day.get("swingSession"), dict) else load_swing_session()
    swing_date = str(swing.get("sessionDate") or "").strip()[:10]
    if swing.get("locked") and swing_date == as_of.isoformat() and (swing.get("long") or []):
        # In-memory sizing for Book math — do not persist (read path)
        apply_swing_sizing(swing, persist=False, force=False)

    swing_rows = [
        p for p in (day.get("picks") or [])
        if isinstance(p, dict) and p.get("symbol") and str(p.get("book") or "").upper() == "SWING"
    ]
    if swing_rows:
        picks: list[dict[str, Any]] = []
        # Enrich day high/low from market snapshot quotes when present
        quote_map: dict[str, dict[str, Any]] = {}
        desk_ic_map: dict[str, Any] = {}
        try:
            from .angel_one_feed import _load_last_snapshot

            snap = _load_last_snapshot() or {}
            quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
            for k, v in quotes.items():
                if isinstance(v, dict):
                    quote_map[str(k).upper()] = v
            for row in snap.get("stocks") or []:
                if isinstance(row, dict) and row.get("ticker"):
                    quote_map.setdefault(str(row["ticker"]).upper(), row)
            raw_ic = snap.get("deskIcByTicker")
            if isinstance(raw_ic, dict):
                desk_ic_map = {str(k).upper(): v for k, v in raw_ic.items() if isinstance(v, dict)}
        except Exception:
            pass

        for p in swing_rows:
            raw = p.get("raw") if isinstance(p.get("raw"), dict) else {}
            sym = str(p.get("symbol") or "").upper()
            q = quote_map.get(sym) or {}
            picks.append({
                **raw,
                "symbol": p.get("symbol"),
                "direction": p.get("direction") or "LONG",
                "entryDate": raw.get("entryDate") or (day.get("swingSession") or {}).get("sessionDate"),
                "entryPrice": p.get("entryPrice"),
                "buyAbove": raw.get("buyAbove") or p.get("entryPrice"),
                "stopLoss": p.get("stopLoss"),
                "target1": p.get("target1"),
                "target2": p.get("target2"),
                "approxQty": p.get("approxQty") or raw.get("approxQty") or 0,
                "deployedCapital": p.get("deployedCapital") or raw.get("deployedCapital") or 0,
                "currentPrice": raw.get("currentPrice") or p.get("entryPrice"),
                "dayHigh": raw.get("dayHigh") or q.get("high") or q.get("High") or q.get("dayHigh"),
                "dayLow": raw.get("dayLow") or q.get("low") or q.get("Low") or q.get("dayLow"),
                "selectionReason": raw.get("selectionReason") or raw.get("selection_reason"),
                "score": raw.get("score") or p.get("score"),
                "deskIcSummary": raw.get("deskIcSummary") or desk_ic_map.get(sym),
                "book": "SWING",
            })
        return picks, False, "swing_session", desk_counts

    # Date parity miss or empty lock — never invent mock / ScanX symbols for Book P&L
    log.info(
        "No date-matched Asset Matrix swing lock for %s — empty Book (no mock)",
        as_of.isoformat(),
    )
    return [], False, "swing_session_empty", desk_counts


def generate_swing_eod_report(
    for_date: date | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Build swing Book P&L from locked swing portfolio (not intradAy mirror)."""
    from .eod_book_cache import load_book_cache, save_book_cache

    as_of = for_date or date.fromisoformat(_today_ist())
    from .desk_clock import cash_session_phase
    market_phase = cash_session_phase(as_of)
    after_close = market_phase == "CLOSED"
    all_picks, is_mock, symbol_source, desk_counts = _load_swing_book_picks(as_of)
    from .swing_session import load_swing_session

    swing_live = load_swing_session()
    live_for_date = str(swing_live.get("sessionDate") or "")[:10] == as_of.isoformat()
    cached_hist = load_book_cache(as_of, "swing")
    if not live_for_date:
        if cached_hist is not None:
            return cached_hist

    if not force:
        cached = load_book_cache(as_of, "swing")
        if cached is not None:
            cached_syms = {
                str(t.get("symbol") or "").upper()
                for t in (cached.get("picks") or [])
                if t.get("symbol")
            }
            live_syms = {
                str(p.get("symbol") or "").upper()
                for p in all_picks
                if p.get("symbol")
            }
            stale_mock = bool(cached.get("isMock") and all_picks and not is_mock)
            stale_source = (
                cached.get("symbolSource") in (None, "fixed_trade_plan", "mock")
                and symbol_source == "swing_session"
            )
            stale_set = bool(live_syms) and cached_syms != live_syms
            ghost_cache = bool(cached_syms) and not live_syms and symbol_source in (
                "swing_session_empty",
                "empty",
                "intraday_session_stale",
            )
            if stale_mock or stale_source or stale_set or ghost_cache:
                log.info(
                    "Rebuilding swing book for %s (mock=%s source=%s set_mismatch=%s ghost=%s)",
                    as_of.isoformat(),
                    stale_mock,
                    stale_source,
                    stale_set,
                    ghost_cache,
                )
            elif market_phase == "CLOSED" and str(cached.get("marketPhase") or "") == market_phase:
                return cached

    if not all_picks:
        empty = {
            "date": as_of.isoformat(),
            "picks": [],
            "summary": {"note": "No locked Asset Matrix swing portfolio for this IST date"},
            "totalPicks": 0,
            "activePicks": 0,
            "skippedNotTriggered": 0,
            "totalDeployed": 0,
            "totalPnl": None if not live_for_date else 0,
            "totalPnlPct": None,
            "winCount": 0,
            "lossCount": 0,
            "bestPerformer": None,
            "worstPerformer": None,
            "pnlByDayBucket": {},
            "isMock": False,
            "symbolSource": symbol_source or "swing_session_empty",
            "archiveStatus": "NO_BOOK" if not live_for_date else None,
            "deskCounts": desk_counts,
            "attribution": {
                "locked": 0,
                "triggered": 0,
                "skipped": 0,
                "wins": 0,
                "losses": 0,
                "deployed": 0,
            },
        }
        if not live_for_date:
            return empty
        return save_book_cache(as_of, "swing", empty)

    alerts = get_alert_history(since=as_of.isoformat(), limit=200)

    from .eod_reference import prefetch_close_marks

    marks = prefetch_close_marks([str(p.get("symbol") or "") for p in all_picks])
    for pick in all_picks:
        if isinstance(pick, dict):
            sym = str(pick.get("symbol") or "").upper()
            if sym in marks:
                pick["currentPrice"] = marks[sym]
                pick["_closeMark"] = marks[sym]

    rows = []
    total_pnl = 0.0
    total_deployed = 0.0
    bucket_totals: dict[int, float] = {b: 0.0 for b in DAY_BUCKETS}
    skipped_count = 0
    live_directions = _live_direction_conflicts()
    day_range_cache: dict[str, tuple] = {}

    for pick in all_picks:
        # Trigger classification requires same-session range evidence. Snapshot
        # highs can be stale or from an incompatible price series; refresh the
        # day bar before declaring that an entry was never crossed.
        from .eod_intraday_report import _enrich_pick_day_range

        refreshed = _enrich_pick_day_range(
            {**pick, "dayHigh": None, "dayLow": None},
            day_range_cache,
            for_date=as_of,
        )
        pick = {
            **pick,
            "dayHigh": refreshed.get("dayHigh"),
            "dayLow": refreshed.get("dayLow"),
            "_sessionCloseMark": refreshed.get("_sessionCloseMark"),
        }
        symbol = str(pick.get("symbol") or "").upper()
        locked_direction = str(pick.get("direction") or "LONG").upper()
        live_direction = live_directions.get(symbol)
        evaluated = (
            _signal_conflict_row(pick, live_direction)
            if live_direction and live_direction != locked_direction
            else _evaluate_swing_pick(
                pick,
                after_close=after_close,
                require_date_matched_mark=True,
            )
        )
        days_held = _days_held(evaluated.get("entryDate"), as_of)
        # Daily Matrix lock → de-emphasize multi-day buckets (mostly 0–1)
        bucket = max([b for b in DAY_BUCKETS if days_held is not None and days_held >= b], default=None)

        # Skip untriggered names from P&L / deployed (still listed in picks)
        if evaluated.get("skipped") or evaluated.get("status") == "NOT_TRIGGERED":
            skipped_count += 1
        else:
            deployed = float(evaluated.get("deployedCapital") or 0)
            total_pnl += float(evaluated["pnl"] or 0)
            total_deployed += deployed
            if bucket:
                bucket_totals[bucket] += float(evaluated["pnl"] or 0)

        symbol_alerts = [
            a for a in alerts.get("alerts", []) if isinstance(a, dict) and a.get("symbol") == evaluated["symbol"]
        ] if isinstance(alerts, dict) else []

        rows.append({
            **evaluated,
            "daysHeld": days_held,
            "dayBucket": bucket,
            "alertsFired": symbol_alerts,
            "book": "SWING",
            "exitReason": evaluated.get("status"),
            "executionBasis": "MODELED_PAPER",
            "pnlKind": "skipped" if evaluated.get("skipped") else "realised" if after_close or evaluated.get("status") != "OPEN" else "unrealised",
        })

    from .outcome_narrative import attach_outcome_narratives, build_day_lessons

    prior_lessons: list[str] = []
    if force:
        prior = load_book_cache(as_of, "swing") or {}
        prior_lessons = list(prior.get("dayLessons") or []) if isinstance(prior.get("dayLessons"), list) else []
        prior_narr = {
            str(t.get("symbol") or "").upper(): t.get("outcomeNarrative")
            for t in (prior.get("picks") or [])
            if isinstance(t, dict) and t.get("outcomeNarrative")
        }
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if sym in prior_narr and not r.get("outcomeNarrative"):
                r["outcomeNarrative"] = prior_narr[sym]

    rows = attach_outcome_narratives(rows, force=force, refresh_existing=force)
    active_rows = [r for r in rows if not r.get("skipped") and r.get("status") != "NOT_TRIGGERED" and r.get("outcomeBucket") != "SKIPPED"]
    winners = [r for r in active_rows if r.get("outcomeBucket") == "WIN"]
    losers = [r for r in active_rows if r.get("outcomeBucket") == "LOSS"]
    lessons = build_day_lessons(rows, force=force, refresh_existing=False, existing=prior_lessons)

    def _book_pnl(r: dict[str, Any]) -> float:
        try:
            return float(r["pnl"]) if r.get("pnl") is not None else float("-inf")
        except (TypeError, ValueError):
            return float("-inf")

    best = max(active_rows, key=_book_pnl, default=None) if active_rows else None
    worst = min(active_rows, key=lambda r: float(r["pnl"]) if r.get("pnl") is not None else float("inf"), default=None) if active_rows else None
    # Guard: best must have max Book P&L among triggered
    if best is not None and best.get("pnl") is None:
        best = None
    if worst is not None and worst.get("pnl") is None:
        worst = None

    triggered = len(active_rows)
    win_count = len(winners)
    hit_rate = round(win_count / triggered * 100, 1) if triggered else 0.0

    report = {
        "date": as_of.isoformat(),
        "totalPicks": len(rows),
        "activePicks": triggered,
        "skippedNotTriggered": skipped_count,
        "totalDeployed": round(total_deployed, 2),
        "totalPnl": round(total_pnl, 2),
        "totalPnlPct": round((total_pnl / total_deployed * 100), 2) if total_deployed else None,
        "winCount": win_count,
        "lossCount": len(losers),
        "hitRatePct": hit_rate,
        "bestPerformer": best,
        "worstPerformer": worst,
        "pnlByDayBucket": {str(k): round(v, 2) for k, v in bucket_totals.items()},
        "picks": rows,
        "isMock": is_mock,
        "symbolSource": symbol_source,
        "executionPolicy": "MANUAL_ONLY",
        "executionBasis": "MODELED_PAPER",
        "marketPhase": market_phase,
        "deskCounts": desk_counts,
        "rotation": "DAILY",
        "source": "asset_matrix_buy",
        "attribution": {
            "locked": len(rows),
            "triggered": triggered,
            "skipped": skipped_count,
            "wins": win_count,
            "losses": len(losers),
            "deployed": round(total_deployed, 2),
        },
        "dayLessons": lessons,
    }
    return save_book_cache(as_of, "swing", report)
