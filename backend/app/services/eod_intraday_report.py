"""Post-market-close reconciliation for the day's intraday scanner picks.

Reads the day's archived intraday picks (see eod_archive.py), reconciles each
against T1/T2/SL, computes P&L vs capital, and builds structured miss
diagnostics for SL / EOD-squareoff legs from plan levels + institutional
scorecards when present (no LLM prose).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any

from .eod_archive import load_archive

log = logging.getLogger(__name__)

DEFAULT_INTRADAY_CAPITAL = 1_000_000.0  # ₹10L
DASH_ROOT = {
    "SL_HIT": "ADVERSE_TRAJECTORY",
    "EOD_SQUAREOFF": "STALLED_TRADE",
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


def _leg_pnl(pick: dict[str, Any]) -> tuple[str, float, float]:
    """Return (exit_reason, exit_price, pnl) for one intraday pick."""
    direction = pick.get("direction", "LONG")
    entry = float(pick.get("entryPrice") or 0)
    qty = int(pick.get("approxQty") or 0)
    outcome = pick.get("outcome") or {}
    hit_level = outcome.get("hitLevel") if isinstance(outcome, dict) else None
    ltp = float(pick.get("currentPrice") or (outcome.get("ltp") if isinstance(outcome, dict) else None) or entry)

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
    return reason, exit_price, pnl


def _build_levels_diagnostic(
    pick: dict[str, Any],
    reason: str,
    exit_price: float,
    pnl: float,
) -> dict[str, Any] | None:
    """Deterministic outcome metrics from plan levels — facts only, no narrative."""
    if reason not in ("SL_HIT", "EOD_SQUAREOFF", "T1_HIT", "T2_HIT"):
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
    if reason == "SL_HIT" and risk and signed_move is not None:
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
    elif reason == "EOD_SQUAREOFF":
        factors.append("TARGET_NOT_REACHED")
        if pnl > 0 or (move_pct is not None and move_pct > 0):
            root = "PARTIAL_FOLLOWTHROUGH"
            factors.append("POSITIVE_EOD_SQUAREOFF")
        else:
            root = "STALLED_TRADE"
            factors.append("NEGATIVE_OR_FLAT_EOD")
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


def _apply_scorecard_to_leg(
    pick: dict[str, Any],
    card: dict[str, Any],
) -> tuple[str, float, float]:
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

    return reason, float(exit_price), float(pnl)


def generate_intraday_eod_report(
    for_date: date,
    capital: float = DEFAULT_INTRADAY_CAPITAL,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Build intraday Book P&L. Serves per-day JSON cache unless force=True."""
    from .eod_book_cache import load_book_cache, save_book_cache

    if not force:
        cached = load_book_cache(for_date, "intraday")
        if cached is not None:
            return cached

    archive = load_archive(for_date)
    picks = list((archive.get("intradayPicks") or {}).values())
    scorecards = _load_scorecard_by_ticker(for_date)

    is_mock = False
    if not picks:
        picks = _generate_mock_intraday_picks()
        is_mock = True

    rows = []
    total_pnl = 0.0
    total_deployed = 0.0
    hits = {"T1_HIT": 0, "T2_HIT": 0, "SL_HIT": 0, "EOD_SQUAREOFF": 0}
    miss_rows = 0

    for pick in picks:
        ticker = str(pick.get("symbol") or "").upper()
        card = scorecards.get(ticker)

        if card and _outcome_unresolved(pick):
            reason, exit_price, pnl = _apply_scorecard_to_leg(pick, card)
            exit_source = "SCORECARD"
        else:
            reason, exit_price, pnl = _leg_pnl(pick)
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
        elif card and _f(card.get("realized_pnl_pct")) is not None:
            pnl_pct = _round(_f(card.get("realized_pnl_pct")), 2)

        rows.append({
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
        })

    remaining_capital = capital + total_pnl
    scored = sum(1 for r in rows if r.get("missDiagnostic") and r["missDiagnostic"].get("source") == "SCORECARD")
    hit_rows = sum(1 for r in rows if r.get("missDiagnostic") and r["missDiagnostic"].get("isHit"))

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
        "trades": rows,
    }
    return save_book_cache(for_date, "intraday", report)
