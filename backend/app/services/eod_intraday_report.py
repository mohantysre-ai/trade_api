"""Post-market-close reconciliation for the day's locked desk symbols.

Canonical symbol source (same as forensic / live trade-outcomes):
  fixed_trade_plan + intraday_session + eod_archive via ``load_day_picks``.

Reconciles each leg against T1/T2/SL, computes P&L vs capital, and builds
structured miss diagnostics from plan levels + institutional scorecards
when present (no LLM prose). Mock picks are last-resort only when no plan,
session, or archive symbols exist.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any

from .eod_archive import load_archive
from .exit_plan import attach_exit_plan, blended_pnl_from_state, format_scale_progress
import json
import time
import urllib.request

log = logging.getLogger(__name__)

DEFAULT_INTRADAY_CAPITAL = 1_000_000.0  # ₹10L
DASH_ROOT = {
    "SL_HIT": "ADVERSE_TRAJECTORY",
    "TRAIL_SL_HIT": "ADVERSE_TRAJECTORY",
    "EOD_SQUAREOFF": "STALLED_TRADE",
    "PARTIAL_SCALE": "PARTIAL_FOLLOWTHROUGH",
}


def _build_rotation_attribution(
    session: dict[str, Any],
    trade_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """EOD ledger: freed slots, proposed replacements, cash held, closed P&L (facts only)."""
    events = list(session.get("events") or []) if isinstance(session, dict) else []
    freed: list[dict[str, Any]] = []
    proposed: list[dict[str, Any]] = []
    cash_held_events: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        et = str(ev.get("type") or "")
        if et == "CAPITAL_SLOT_FREED":
            freed.append(
                {
                    "at": ev.get("at"),
                    "freeSlots": ev.get("freeSlots"),
                }
            )
        elif et == "REPLACEMENT_PROPOSED":
            proposed.append(
                {
                    "at": ev.get("at"),
                    "freeSlots": ev.get("freeSlots"),
                    "candidates": ev.get("candidates") or [],
                }
            )
        elif et == "CASH_HELD":
            cash_held_events.append(
                {
                    "at": ev.get("at"),
                    "reason": ev.get("reason"),
                    "freeSlots": ev.get("freeSlots"),
                }
            )
        elif et in ("POSITION_CLOSED", "STOP_LOSS_HIT", "TRAIL_STOP_HIT", "TARGET_HIT"):
            freed.append(
                {
                    "at": ev.get("at"),
                    "symbol": ev.get("symbol"),
                    "direction": ev.get("direction"),
                    "status": ev.get("status") or et,
                    "realizedPnl": ev.get("realizedPnl"),
                }
            )

    closed_trades: list[dict[str, Any]] = []
    for t in trade_rows:
        if not isinstance(t, dict):
            continue
        reason = str(t.get("exitReason") or t.get("status") or "").upper()
        pnl = t.get("pnl")
        if pnl is None:
            pnl = t.get("realizedPnl")
        closed_trades.append(
            {
                "symbol": t.get("symbol"),
                "direction": t.get("direction"),
                "exitReason": t.get("exitReason") or t.get("status"),
                "pnl": pnl,
                "slotFreed": bool(
                    t.get("slotFreed")
                    or str(t.get("slotStatus") or "").upper() == "REPLACEABLE"
                    or "HIT" in reason
                    or reason in ("CLOSED", "STOP LOSS HIT", "TRAIL STOP HIT")
                ),
            }
        )

    last_proposals = session.get("lastReplacementProposals") if isinstance(session, dict) else None
    if isinstance(last_proposals, list) and last_proposals and not proposed:
        proposed.append(
            {
                "at": session.get("updatedAt"),
                "candidates": last_proposals,
                "source": "lastReplacementProposals",
            }
        )

    proposed_syms = {
        str(c.get("symbol") or "").upper()
        for block in proposed
        for c in (block.get("candidates") or [])
        if isinstance(c, dict) and c.get("symbol")
    }
    closed_pnl = [
        float(t["pnl"])
        for t in closed_trades
        if t.get("pnl") is not None
    ]

    return {
        "slotFreedEvents": len(freed),
        "freed": freed[-50:],
        "replacementProposals": proposed[-50:],
        "proposedSymbolCount": len(proposed_syms),
        "proposedSymbols": sorted(proposed_syms),
        "cashHeldEvents": cash_held_events[-20:],
        "cashHeld": bool(cash_held_events) or bool(
            isinstance(session, dict) and session.get("lastCashHeldAt")
        ),
        "closedTrades": closed_trades,
        "closedPnlSum": round(sum(closed_pnl), 2) if closed_pnl else None,
        "note": (
            "Proposals are advisory (proposalOnly); P&L is from closed book rows only. "
            "No invented replacement fills."
        ),
    }


def _eod_scorecards_path(for_date: date) -> str:
    root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "data", "eod", for_date.isoformat())
    )
    return os.path.join(root, "scorecards.json")


def _load_scorecard_by_ticker(for_date: date) -> dict[str, dict[str, Any]]:
    path = _eod_scorecards_path(for_date)
    if not os.path.isfile(path):
        return {}
    try:
        raw = json.loads(open(path, encoding="utf-8").read())
    except Exception as exc:
        log.warning("scorecards load failed %s: %s", path, exc)
        return {}
    cards = raw if isinstance(raw, list) else (raw.get("scorecards") or raw.get("trades") or [])
    out: dict[str, dict[str, Any]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        ticker = str(card.get("ticker") or card.get("symbol") or "").upper()
        if not ticker:
            continue
        # Prefer miss outcomes when duplicate tickers exist
        prev = out.get(ticker)
        outcome = str(card.get("outcome") or "").upper()
        if prev is None or outcome in {"STOP_HIT", "EOD_SQUAREOFF", "SL_HIT"}:
            out[ticker] = card
    return out


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def _round(v: float | None, digits: int = 2) -> float | None:
    if v is None:
        return None
    return round(float(v), digits)


def _exit_reason_from_scale_eval(eval_result: dict[str, Any]) -> str:
    """Map evaluate_scale_trail / blended result to Book exitReason (facts only)."""
    hit = eval_result.get("hitLevel")
    label = str(eval_result.get("label") or "").upper()
    if hit == "sl" or "TRAIL STOP" in label:
        return "TRAIL_SL_HIT"
    if "EOD SQUARE" in label:
        return "EOD_SQUAREOFF"
    if hit == "partial" or label.startswith("PARTIAL") or "SCALE COMPLETE" in label:
        return "PARTIAL_SCALE"
    if eval_result.get("closed"):
        return "PARTIAL_SCALE"
    return "PARTIAL_SCALE"


def _scale_trail_work_pick(pick: dict[str, Any]) -> dict[str, Any] | None:
    """Return pick with SCALE_TRAIL exitPlan, or None if binary fallback."""
    plan = pick.get("exitPlan") if isinstance(pick.get("exitPlan"), dict) else None
    if plan and plan.get("mode") == "SCALE_TRAIL":
        return pick
    entry = float(pick.get("entryPrice") or 0)
    qty = int(pick.get("approxQty") or 0)
    risk = float(pick.get("riskPerShare") or 0)
    sl = float(pick.get("stopLoss") or 0)
    if entry <= 0 or qty <= 0 or (risk <= 0 and sl <= 0):
        return None
    work = attach_exit_plan(pick)
    attached = work.get("exitPlan") if isinstance(work.get("exitPlan"), dict) else None
    if not attached or attached.get("mode") != "SCALE_TRAIL":
        return None
    if isinstance(pick.get("exitState"), dict) and not work.get("exitState"):
        work["exitState"] = pick["exitState"]
    return work


def _yahoo_day_range(symbol: str) -> tuple[float | None, float | None, float | None]:
    """Return (high, low, close) from Yahoo 1d bar, or (None, None, None)."""
    sym = str(symbol or "").upper().strip()
    if not sym:
        return None, None, None
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        q = data["chart"]["result"][0]["indicators"]["quote"][0]
        i = -1
        hi, lo, cl = q["high"][i], q["low"][i], q["close"][i]
        if hi is None or lo is None or cl is None:
            return None, None, None
        return float(hi), float(lo), float(cl)
    except Exception:
        return None, None, None


def _enrich_pick_day_range(pick: dict[str, Any], cache: dict[str, tuple]) -> dict[str, Any]:
    """Attach dayHigh/dayLow/closeMark for path-aware SCALE_TRAIL EOD."""
    out = dict(pick)
    if out.get("dayHigh") is not None and out.get("dayLow") is not None:
        return out
    sym = str(out.get("symbol") or "").upper()
    if sym not in cache:
        cache[sym] = _yahoo_day_range(sym)
        time.sleep(0.08)
    hi, lo, cl = cache[sym]
    if hi is not None:
        out["dayHigh"] = hi
    if lo is not None:
        out["dayLow"] = lo
    if cl is not None and not out.get("currentPrice"):
        out["currentPrice"] = cl
    return out


def _leg_pnl(pick: dict[str, Any]) -> tuple[str, float, float, dict[str, Any]]:
    """Return (exit_reason, exit_price, pnl, scale_meta) for one intraday pick."""
    direction = pick.get("direction", "LONG")
    entry = float(pick.get("entryPrice") or 0)
    qty = int(pick.get("approxQty") or 0)
    outcome = pick.get("outcome") or {}
    hit_level = outcome.get("hitLevel") if isinstance(outcome, dict) else None
    ltp = float(
        pick.get("currentPrice")
        or (outcome.get("ltp") if isinstance(outcome, dict) else None)
        or entry
    )

    work = _scale_trail_work_pick(pick)
    if work is not None:
        total_pnl, avg_exit, eval_result = blended_pnl_from_state(work, ltp, after_close=True)
        if eval_result:
            state = eval_result.get("exitState") if isinstance(eval_result.get("exitState"), dict) else {}
            plan = work.get("exitPlan") if isinstance(work.get("exitPlan"), dict) else None
            r_mult = eval_result.get("rMultiple")
            scale_meta = {
                "exitPlan": plan,
                "exitState": state,
                "remainingQty": eval_result.get("remainingQty"),
                "effectiveStop": eval_result.get("effectiveStop"),
                "realizedPnl": eval_result.get("realizedPnl"),
                "unrealizedPnl": eval_result.get("unrealizedPnl"),
                "rMultiple": r_mult,
                "scaleTrail": True,
                "scaleProgress": format_scale_progress(
                    plan, state, r_multiple=float(r_mult) if r_mult is not None else None
                ),
            }
            return (
                _exit_reason_from_scale_eval(eval_result),
                float(avg_exit),
                float(total_pnl),
                scale_meta,
            )

    # Legacy binary T1/T2/SL full-qty (no exitPlan / attach failed)
    if hit_level == "t2":
        exit_price = float(pick.get("target2") or ltp)
        reason = "T2_HIT"
    elif hit_level == "t1":
        exit_price = float(pick.get("target1") or ltp)
        reason = "T1_HIT"
    elif hit_level == "sl":
        exit_price = float(pick.get("stopLoss") or ltp)
        reason = "SL_HIT"
    else:
        exit_price = ltp
        reason = "EOD_SQUAREOFF"

    sign = 1 if direction == "LONG" else -1
    pnl = sign * (exit_price - entry) * qty
    return reason, exit_price, pnl, {}


def _build_levels_diagnostic(
    pick: dict[str, Any],
    reason: str,
    exit_price: float,
    pnl: float,
) -> dict[str, Any] | None:
    """Deterministic outcome metrics from plan levels — facts only, no narrative."""
    if reason not in (
        "SL_HIT",
        "TRAIL_SL_HIT",
        "EOD_SQUAREOFF",
        "T1_HIT",
        "T2_HIT",
        "PARTIAL_SCALE",
    ):
        return None

    direction = str(pick.get("direction") or "LONG").upper()
    entry = _f(pick.get("entryPrice")) or 0.0
    sl = _f(pick.get("stopLoss"))
    t1 = _f(pick.get("target1"))
    t2 = _f(pick.get("target2"))
    risk = _f(pick.get("riskPerShare"))
    if risk is None and entry and sl is not None:
        risk = abs(entry - sl)
    if not risk or risk <= 0:
        risk = None

    sign = 1.0 if direction == "LONG" else -1.0
    signed_move = sign * (exit_price - entry) if entry else None
    move_pct = (signed_move / entry * 100.0) if entry and signed_move is not None else None
    r_multiple = (signed_move / risk) if risk and signed_move is not None else None

    gap_t1_pct: float | None = None
    gap_t2_pct: float | None = None
    if entry and t1 is not None:
        gap_t1_pct = sign * (t1 - exit_price) / entry * 100.0
    if entry and t2 is not None:
        gap_t2_pct = sign * (t2 - exit_price) / entry * 100.0

    stop_util: float | None = None
    if reason in ("SL_HIT", "TRAIL_SL_HIT") and risk and signed_move is not None:
        stop_util = abs(signed_move) / risk

    factors: list[str] = []
    root: str
    is_miss = reason in ("SL_HIT", "EOD_SQUAREOFF")

    if reason == "SL_HIT":
        factors.append("STOP_HIT")
        if stop_util is not None and stop_util >= 0.9:
            factors.append("FULL_STOP_TRAVERSAL")
            root = "ADVERSE_TRAJECTORY"
        else:
            root = "STOP_BEFORE_FOLLOWTHROUGH"
            factors.append("STOP_BEFORE_FOLLOWTHROUGH")
    elif reason == "TRAIL_SL_HIT":
        factors.append("TRAIL_STOP_HIT")
        if pnl >= 0 or (move_pct is not None and move_pct >= 0):
            is_miss = False
            root = "TRAIL_LOCKED_GAINS"
            factors.append("TRAIL_LOCKED_GAINS")
        else:
            is_miss = True
            root = "ADVERSE_TRAJECTORY"
            factors.append("TRAIL_STOPPED_LOSS")
            if stop_util is not None and stop_util >= 0.9:
                factors.append("FULL_STOP_TRAVERSAL")
    elif reason == "EOD_SQUAREOFF":
        factors.append("TARGET_NOT_REACHED")
        if pnl > 0 or (move_pct is not None and move_pct > 0):
            root = "PARTIAL_FOLLOWTHROUGH"
            factors.append("POSITIVE_EOD_SQUAREOFF")
        else:
            root = "STALLED_TRADE"
            factors.append("NEGATIVE_OR_FLAT_EOD")
    elif reason == "PARTIAL_SCALE":
        factors.append("SCALE_LEGS_FILLED")
        if pnl > 0 or (move_pct is not None and move_pct > 0):
            is_miss = False
            root = "PARTIAL_FOLLOWTHROUGH"
            factors.append("POSITIVE_SCALE_BOOK")
        else:
            is_miss = True
            root = "STALLED_TRADE"
            factors.append("NEGATIVE_OR_FLAT_SCALE")
    elif reason == "T2_HIT":
        root = "TREND_FOLLOWTHROUGH"
        factors.extend(["TARGET_REACHED", "T2_HIT"])
        if r_multiple is not None and r_multiple >= 2.0:
            factors.append("STRONG_R_MULTIPLE")
    else:  # T1_HIT
        root = "TREND_FOLLOWTHROUGH"
        factors.extend(["TARGET_REACHED", "T1_HIT"])
        if gap_t2_pct is not None and gap_t2_pct > 0:
            factors.append("T2_NOT_REACHED")

    return {
        "isMiss": is_miss,
        "isHit": not is_miss,
        "exitReason": reason,
        "rootCause": root,
        "factors": factors,
        "rMultiple": _round(r_multiple, 2),
        "movePct": _round(move_pct, 2),
        "gapToT1Pct": _round(gap_t1_pct, 2),
        "gapToT2Pct": _round(gap_t2_pct, 2),
        "stopUtilization": _round(stop_util, 2),
        "plannedRr": _round(_f(pick.get("rrT2")), 2),
        "riskPerShare": _round(risk, 4),
        "maePct": None,
        "mfePct": None,
        "stopEff": None,
        "falsePositive": False,
        "holdingMins": None,
        "source": "LEVELS",
    }


def _merge_scorecard(diag: dict[str, Any], card: dict[str, Any] | None) -> dict[str, Any]:
    if not card:
        return diag
    outcome = str(card.get("outcome") or "").upper()
    # Map engine STOP_HIT → same miss family
    if outcome not in {"STOP_HIT", "EOD_SQUAREOFF", "SL_HIT", ""}:
        # Still pull efficiency if same ticker day
        pass

    root = card.get("root_cause")
    if root:
        diag["rootCause"] = str(root)

    fail = card.get("failure_factors") or []
    succ = card.get("success_factors") or []
    factors = [str(x) for x in (fail or succ) if x]
    if factors:
        diag["factors"] = factors

    eff = card.get("efficiency") if isinstance(card.get("efficiency"), dict) else {}
    diag["maePct"] = _round(_f(eff.get("mae_pct")), 2)
    diag["mfePct"] = _round(_f(eff.get("mfe_pct")), 2)
    diag["stopEff"] = _round(_f(eff.get("stop_efficiency_index")), 3)

    rr = _f(eff.get("realized_return_ratio"))
    if rr is not None:
        diag["rMultiple"] = _round(rr, 2)

    pnl_pct = _f(card.get("realized_pnl_pct"))
    if pnl_pct is not None:
        diag["movePct"] = _round(pnl_pct, 2)

    diag["falsePositive"] = bool(card.get("false_positive"))
    hold = card.get("holding_duration_mins")
    diag["holdingMins"] = int(hold) if hold is not None else diag.get("holdingMins")
    diag["source"] = "SCORECARD"
    return diag


def _miss_diagnostic(
    pick: dict[str, Any],
    reason: str,
    exit_price: float,
    pnl: float,
    scorecards: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    diag = _build_levels_diagnostic(pick, reason, exit_price, pnl)
    if not diag:
        return None
    ticker = str(pick.get("symbol") or "").upper()
    return _merge_scorecard(diag, scorecards.get(ticker))


def _generate_mock_intraday_picks() -> list[dict[str, Any]]:
    """Generate mock intraday picks for demo when the archive is empty."""
    from .eod_reference import get_reference_price, get_mock_eod_price

    mock_picks_data = [
        ("KALAMANDIR", "SHORT", 500),
        ("RAMASTEEL", "SHORT", 10000),
        ("GTLINFRA", "SHORT", 40000),
        ("VIKASLIFE", "SHORT", 35000),
        ("JAINREC", "SHORT", 150),
        ("GREENPOWER", "SHORT", 5000),
        ("BSE", "SHORT", 15),
        ("BAJAJCON", "SHORT", 100),
        ("VIKASECO", "SHORT", 40000),
        ("NCC", "SHORT", 350),
        ("RELAXO", "LONG", 100),
        ("CUPID", "LONG", 200),
        ("NAVKARURB", "LONG", 40000),
        ("BAJFINANCE", "LONG", 50),
        ("ADANIENT", "LONG", 15),
        ("ZEEL", "LONG", 450),
        ("BPCL", "LONG", 150),
        ("SBIN", "LONG", 50),
        ("M&M", "LONG", 15),
        ("PIRAMALFIN", "LONG", 25),
    ]

    result = []
    for sym, direction, qty in mock_picks_data:
        ref = get_reference_price(sym)
        eod = get_mock_eod_price(sym)
        if not ref or not eod:
            continue
        sl = round(ref * 0.96, 2) if direction == "LONG" else round(ref * 1.04, 2)
        t1 = round(ref * 1.03, 2) if direction == "LONG" else round(ref * 0.97, 2)
        t2 = round(ref * 1.06, 2) if direction == "LONG" else round(ref * 0.94, 2)
        risk = abs(ref - sl)

        if direction == "LONG":
            if eod >= t2:
                reason, exit_price = "T2_HIT", t2
            elif eod >= t1:
                reason, exit_price = "T1_HIT", t1
            elif eod <= sl:
                reason, exit_price = "SL_HIT", sl
            else:
                reason, exit_price = "EOD_SQUAREOFF", eod
        else:
            if eod <= t2:
                reason, exit_price = "T2_HIT", t2
            elif eod <= t1:
                reason, exit_price = "T1_HIT", t1
            elif eod >= sl:
                reason, exit_price = "SL_HIT", sl
            else:
                reason, exit_price = "EOD_SQUAREOFF", eod

        deployed = round(ref * qty, 2)
        sign = 1 if direction == "LONG" else -1
        pnl_final = round(sign * (exit_price - ref) * qty, 2)

        result.append({
            "symbol": sym,
            "direction": direction,
            "entryPrice": ref,
            "stopLoss": sl,
            "target1": t1,
            "target2": t2,
            "riskPerShare": risk,
            "rrT2": round(abs(t2 - ref) / risk, 2) if risk else None,
            "currentPrice": exit_price,
            "approxQty": qty,
            "deployedCapital": deployed,
            "outcome": {
                "hitLevel": (
                    "t2" if reason == "T2_HIT"
                    else "t1" if reason == "T1_HIT"
                    else "sl" if reason == "SL_HIT"
                    else None
                ),
                "ltp": exit_price,
            },
            "_mockExitReason": reason,
            "_mockPnl": pnl_final,
        })
    return result


def _outcome_unresolved(pick: dict[str, Any]) -> bool:
    outcome = pick.get("outcome")
    if not isinstance(outcome, dict):
        return True
    if outcome.get("hitLevel") in ("t1", "t2", "sl"):
        return False
    label = str(outcome.get("label") or "").upper()
    if label in {"PENDING", "", "NONE"}:
        return True
    # No hitLevel and LTP≈entry → not a real close mark
    entry = _f(pick.get("entryPrice"))
    ltp = _f(pick.get("currentPrice") or outcome.get("ltp"))
    if entry is not None and ltp is not None and abs(ltp - entry) < 1e-9:
        return True
    return outcome.get("hitLevel") is None and pick.get("currentPrice") is None


def _pick_from_canonical(normalized: dict[str, Any]) -> dict[str, Any]:
    """Flatten load_day_picks row into the shape Book / Outcome Desk expect."""
    raw = normalized.get("raw") if isinstance(normalized.get("raw"), dict) else {}
    outcome = normalized.get("outcome") or raw.get("outcome")
    current = raw.get("currentPrice")
    if current is None and isinstance(outcome, dict):
        current = outcome.get("ltp")
    return {
        **raw,
        "symbol": normalized.get("symbol") or raw.get("symbol"),
        "direction": normalized.get("direction") or raw.get("direction") or "LONG",
        "entryPrice": normalized.get("entryPrice") if normalized.get("entryPrice") is not None else raw.get("entryPrice"),
        "stopLoss": normalized.get("stopLoss") if normalized.get("stopLoss") is not None else raw.get("stopLoss"),
        "target1": normalized.get("target1") if normalized.get("target1") is not None else raw.get("target1"),
        "target2": normalized.get("target2") if normalized.get("target2") is not None else raw.get("target2"),
        "approxQty": normalized.get("approxQty") or raw.get("approxQty") or 0,
        "deployedCapital": normalized.get("deployedCapital") or raw.get("deployedCapital") or 0,
        "riskPerShare": normalized.get("riskPerShare") or raw.get("riskPerShare"),
        "outcome": outcome,
        "currentPrice": current,
        "source": normalized.get("source") or raw.get("source"),
        "book": normalized.get("book") or raw.get("book") or "INTRADAY",
    }


def _load_canonical_intraday_picks(for_date: date) -> tuple[list[dict[str, Any]], bool, str, dict[str, int]]:
    """Intraday Book — locked desk for matching IST sessionDate only.

    Prefer intradAy_session long/short when locked + date parity; else fixed_trade_plan
    for that date; else archive; else empty (no invented mock when a live lock exists
    for another day).
    """
    from .eod_engine.ingestion import load_day_picks, load_fixed_trade_plan, load_intraday_session

    day_key = for_date.isoformat()
    session = load_intraday_session(for_date)
    session_date = str(session.get("sessionDate") or "").strip()[:10]
    session_ok = bool(session.get("locked") and session_date == day_key)

    # Prefer unified loader (also supplies truthful deskCounts incl. swing)
    try:
        day = load_day_picks(for_date)
        desk_counts = dict(day.get("deskCounts") or {})
        sources = day.get("sources") or {}
        if sources.get("intradayDateParity") or session_ok:
            intra_rows = [
                p
                for p in (day.get("picks") or [])
                if isinstance(p, dict)
                and p.get("symbol")
                and str(p.get("book") or "").upper() == "INTRADAY"
            ]
            if intra_rows:
                rows: list[dict[str, Any]] = []
                for p in intra_rows:
                    raw = p.get("raw") if isinstance(p.get("raw"), dict) else {}
                    rows.append({
                        **raw,
                        **{k: v for k, v in p.items() if k != "raw"},
                        "symbol": str(p.get("symbol") or "").upper(),
                        "direction": str(p.get("direction") or "LONG").upper(),
                        "book": "INTRADAY",
                        "source": "intraday_session",
                        "approxQty": p.get("approxQty") or raw.get("approxQty") or 0,
                        "deployedCapital": p.get("deployedCapital") or raw.get("deployedCapital") or 0,
                        "currentPrice": raw.get("currentPrice") or p.get("entryPrice"),
                        "outcome": p.get("outcome") or raw.get("outcome"),
                    })
                return rows, False, "intraday_session", desk_counts
    except Exception as exc:
        log.warning("load_day_picks for intradAy book failed: %s", exc)
        desk_counts = {"swing": 0, "intradayLong": 0, "intradayShort": 0, "total": 0}

    if session.get("locked") and session_date and session_date != day_key:
        log.info(
            "Stale intradAy_session (%s != %s) — skip live lock, try plan/archive for date",
            session_date,
            day_key,
        )
        # Fall through — do not hard-empty the Book

    session_long = [p for p in (session.get("long") or []) if isinstance(p, dict) and p.get("symbol")] if session_ok else []
    session_short = [p for p in (session.get("short") or []) if isinstance(p, dict) and p.get("symbol")] if session_ok else []
    desk_counts = {
        "swing": int(desk_counts.get("swing") or 0) if isinstance(desk_counts, dict) else 0,
        "intradayLong": len(session_long),
        "intradayShort": len(session_short),
        "total": 0,
    }
    desk_counts["total"] = desk_counts["swing"] + desk_counts["intradayLong"] + desk_counts["intradayShort"]

    if session_long or session_short:
        rows = []
        for p in session_long + session_short:
            rows.append({
                **p,
                "symbol": str(p.get("symbol") or "").upper(),
                "direction": str(p.get("direction") or "LONG").upper(),
                "book": "INTRADAY",
                "source": "intraday_session",
                "approxQty": p.get("approxQty") or 0,
                "deployedCapital": p.get("deployedCapital") or 0,
                "currentPrice": p.get("currentPrice") or p.get("ltp") or p.get("entryPrice"),
                "outcome": p.get("outcome"),
            })
        return rows, False, "intraday_session", desk_counts

    plan = load_fixed_trade_plan(for_date)
    plan_date = str(plan.get("sessionDate") or "").strip()[:10]
    plan_ok = (not plan_date) or plan_date == day_key
    plan_long = [p for p in (plan.get("long") or []) if isinstance(p, dict) and p.get("symbol")] if plan_ok else []
    plan_short = [p for p in (plan.get("short") or []) if isinstance(p, dict) and p.get("symbol")] if plan_ok else []
    if plan_long or plan_short:
        rows = []
        for p in plan_long + plan_short:
            rows.append({
                **p,
                "symbol": str(p.get("symbol") or "").upper(),
                "direction": str(p.get("direction") or "LONG").upper(),
                "book": "INTRADAY",
                "source": "fixed_trade_plan",
                "approxQty": p.get("approxQty") or 0,
                "deployedCapital": p.get("deployedCapital") or 0,
                "currentPrice": p.get("currentPrice") or p.get("ltp") or p.get("entryPrice"),
                "outcome": p.get("outcome"),
            })
        desk_counts = {
            "swing": 0,
            "intradayLong": len(plan_long),
            "intradayShort": len(plan_short),
            "total": len(plan_long) + len(plan_short),
        }
        return rows, False, "fixed_trade_plan", desk_counts

    archive = load_archive(for_date)
    archived = list((archive.get("intradayPicks") or {}).values())
    archived = [p for p in archived if isinstance(p, dict) and p.get("symbol")]
    if archived:
        return archived, False, "eod_archive", desk_counts

    # Empty — do not invent mock symbols when requesting a real desk date
    return [], False, "empty", desk_counts


def _apply_scorecard_to_leg(
    pick: dict[str, Any],
    card: dict[str, Any],
) -> tuple[str, float, float, dict[str, Any]]:
    """When archive lacks a resolved exit, use institutional scorecard marks."""
    outcome_raw = str(card.get("outcome") or "").upper()
    if outcome_raw in {"STOP_HIT", "SL_HIT"}:
        reason = "SL_HIT"
    elif outcome_raw in {"TARGET_HIT"}:
        # Prefer T2 if exit near target2 else T1
        exit_px = _f(card.get("exit_price"))
        t2 = _f(pick.get("target2"))
        t1 = _f(pick.get("target1"))
        if exit_px is not None and t2 is not None and abs(exit_px - t2) <= abs(exit_px - (t1 or exit_px)):
            reason = "T2_HIT"
        else:
            reason = "T1_HIT"
    elif outcome_raw == "EOD_SQUAREOFF":
        reason = "EOD_SQUAREOFF"
    elif outcome_raw == "NO_ENTRY":
        reason = "EOD_SQUAREOFF"
    else:
        reason = "EOD_SQUAREOFF"

    exit_price = _f(card.get("exit_price"))
    if exit_price is None:
        exit_price = _f(pick.get("currentPrice")) or _f(pick.get("entryPrice")) or 0.0

    pnl_abs = _f(card.get("realized_pnl_abs"))
    if pnl_abs is not None:
        pnl = pnl_abs
    else:
        entry = _f(pick.get("entryPrice")) or _f(card.get("entry_price")) or 0.0
        qty = int(pick.get("approxQty") or card.get("qty") or 0)
        direction = str(pick.get("direction") or card.get("direction") or "LONG").upper()
        sign = 1 if direction == "LONG" else -1
        if qty > 0:
            pnl = sign * (exit_price - entry) * qty
        else:
            # Size unknown — keep abs PnL at 0; pct comes from scorecard on the row
            pnl = 0.0

    return reason, float(exit_price or 0), float(pnl or 0), {}


def generate_intraday_eod_report(
    for_date: date,
    capital: float = DEFAULT_INTRADAY_CAPITAL,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Build intraday Book P&L. Serves per-day JSON cache unless force=True."""
    from .eod_book_cache import load_book_cache, save_book_cache

    picks, is_mock, symbol_source, desk_counts = _load_canonical_intraday_picks(for_date)

    if not force:
        cached = load_book_cache(for_date, "intraday")
        if cached is not None:
            cached_syms = {
                str(t.get("symbol") or "").upper()
                for t in (cached.get("trades") or [])
                if t.get("symbol")
            }
            live_syms = {
                str(p.get("symbol") or "").upper()
                for p in picks
                if p.get("symbol")
            }
            stale_mock = bool(cached.get("isMock") and picks and not is_mock)
            stale_set = bool(live_syms) and cached_syms != live_syms
            ghost_cache = bool(cached_syms) and not live_syms and symbol_source in (
                "empty",
                "intraday_session_stale",
            )
            if stale_mock or stale_set or ghost_cache:
                log.info(
                    "Rebuilding intraday book for %s (mock=%s set_mismatch=%s ghost=%s live=%s cached=%s)",
                    for_date.isoformat(),
                    stale_mock,
                    stale_set,
                    ghost_cache,
                    sorted(live_syms),
                    sorted(cached_syms),
                )
            else:
                return cached

    # Prefetch close marks in parallel (cached) so Book UI does not hang
    from .eod_reference import prefetch_close_marks

    marks = prefetch_close_marks([str(p.get("symbol") or "") for p in picks])
    for pick in picks:
        if not isinstance(pick, dict):
            continue
        sym = str(pick.get("symbol") or "").upper()
        mark = marks.get(sym)
        if mark:
            pick["currentPrice"] = mark
            pick["ltp"] = mark

    scorecards = _load_scorecard_by_ticker(for_date)

    rows = []
    total_pnl = 0.0
    total_deployed = 0.0
    hits = {"T1_HIT": 0, "T2_HIT": 0, "SL_HIT": 0, "EOD_SQUAREOFF": 0, "TRAIL_SL_HIT": 0, "PARTIAL_SCALE": 0}
    miss_rows = 0
    ohlc_cache: dict[str, tuple] = {}

    for pick in picks:
        pick = _enrich_pick_day_range(pick, ohlc_cache)
        ticker = str(pick.get("symbol") or "").upper()
        card = scorecards.get(ticker)

        # Prefer SCALE_TRAIL blended PnL + ladder fields when attachable.
        # Scorecard only for legacy unresolved binary legs (no inventing ladder).
        if _scale_trail_work_pick(pick) is not None:
            reason, exit_price, pnl, scale_meta = _leg_pnl(pick)
            exit_source = "SCALE_TRAIL"
        elif card and _outcome_unresolved(pick):
            reason, exit_price, pnl, scale_meta = _apply_scorecard_to_leg(pick, card)
            exit_source = "SCORECARD"
        else:
            reason, exit_price, pnl, scale_meta = _leg_pnl(pick)
            exit_source = "ARCHIVE"

        deployed = float(pick.get("deployedCapital") or 0)
        if deployed <= 0:
            entry = float(pick.get("entryPrice") or 0)
            qty = int(pick.get("approxQty") or 0)
            if qty <= 0 and card:
                qty = int(card.get("qty") or 0)
            deployed = float(card.get("deployed_capital") or 0) if card and deployed <= 0 else deployed
            if deployed <= 0:
                deployed = round(entry * qty, 2) if entry and qty else 0.0

        total_pnl += pnl
        total_deployed += deployed
        hits[reason] = hits.get(reason, 0) + 1

        diagnostic = _miss_diagnostic(pick, reason, exit_price, pnl, scorecards)
        if diagnostic:
            diagnostic["exitSource"] = exit_source
            if diagnostic.get("isMiss"):
                miss_rows += 1

        pnl_pct = None
        if deployed:
            pnl_pct = round((pnl / deployed * 100), 2)
        else:
            entry_px = float(pick.get("entryPrice") or 0)
            if entry_px > 0:
                sign = 1 if str(pick.get("direction") or "LONG").upper() == "LONG" else -1
                pnl_pct = round(sign * (exit_price - entry_px) / entry_px * 100, 2)
            elif card and _f(card.get("realized_pnl_pct")) is not None:
                pnl_pct = _round(_f(card.get("realized_pnl_pct")), 2)

        row: dict[str, Any] = {
            "symbol": pick.get("symbol"),
            "direction": pick.get("direction") or (card.get("direction") if card else None),
            "entryPrice": pick.get("entryPrice") or (card.get("entry_price") if card else None),
            "exitPrice": round(exit_price, 2),
            "stopLoss": pick.get("stopLoss") or (card.get("stop_loss") if card else None),
            "target1": pick.get("target1"),
            "target2": pick.get("target2") or (card.get("target_price") if card else None),
            "exitReason": reason,
            "qty": pick.get("approxQty") or (card.get("qty") if card else None),
            "deployedCapital": deployed,
            "pnl": round(pnl, 2),
            "pnlPct": pnl_pct,
            "missAnalysis": None,
            "missDiagnostic": diagnostic,
            "pickSource": pick.get("source") or symbol_source,
        }
        if isinstance(scale_meta, dict) and scale_meta:
            row.update(scale_meta)
        else:
            row["scaleTrail"] = False
            row["scaleProgress"] = None
        rows.append(row)

    from .outcome_narrative import attach_outcome_narratives, build_day_lessons

    prior_lessons: list[str] = []
    if force:
        prior = load_book_cache(for_date, "intraday") or {}
        prior_lessons = list(prior.get("dayLessons") or []) if isinstance(prior.get("dayLessons"), list) else []
        prior_narr = {
            str(t.get("symbol") or "").upper(): t.get("outcomeNarrative")
            for t in (prior.get("trades") or [])
            if isinstance(t, dict) and t.get("outcomeNarrative")
        }
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if sym in prior_narr and not r.get("outcomeNarrative"):
                r["outcomeNarrative"] = prior_narr[sym]

    rows = attach_outcome_narratives(rows, force=force, refresh_existing=False)
    remaining_capital = capital + total_pnl
    scored = sum(1 for r in rows if r.get("missDiagnostic") and r["missDiagnostic"].get("source") == "SCORECARD")
    hit_rows = sum(1 for r in rows if r.get("missDiagnostic") and r["missDiagnostic"].get("isHit"))
    lessons = build_day_lessons(rows, force=force, refresh_existing=False, existing=prior_lessons)

    from .eod_engine.ingestion import load_intraday_session

    session_live = load_intraday_session(for_date)
    rotation = _build_rotation_attribution(
        session_live if isinstance(session_live, dict) else {},
        rows,
    )

    report = {
        "date": for_date.isoformat(),
        "capital": capital,
        "totalDeployed": round(total_deployed, 2),
        "totalPnl": round(total_pnl, 2),
        "remainingCapital": round(remaining_capital, 2),
        "hitBreakdown": hits,
        "hitRatePct": round((hits["T1_HIT"] + hits["T2_HIT"]) / len(picks) * 100, 1) if picks else 0,
        "missCount": miss_rows,
        "hitCount": hit_rows,
        "missScorecardCoverage": scored,
        "isMock": is_mock,
        "symbolSource": symbol_source,
        "deskCounts": desk_counts,
        "attribution": {
            "locked": len(rows),
            "triggered": len(rows),
            "skipped": 0,
            "wins": hit_rows,
            "losses": miss_rows,
            "deployed": round(total_deployed, 2),
        },
        "rotationAttribution": rotation,
        "dayLessons": lessons,
        "trades": rows,
    }
    return save_book_cache(for_date, "intraday", report)
