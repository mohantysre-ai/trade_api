"""Post-market-close swing analysis for the Asset Matrix fixed trade plan.

Unlike the intraday side, the swing plan (fixed_trade_plan.json) already
persists indefinitely — no archiving gap here. This module just reads it
plus alert_history.json (which already records T1/T2/SL fire timestamps)
and produces the day-bucketed P&L report: Day 1 / Day 7 / Day 15 / Day 30.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .trade_outcome import load_fixed_trade_plan, get_alert_history, _today_ist

DEFAULT_SWING_CAPITAL = 500_000.0  # ₹5L, informational only — actual sizing comes from each pick
DAY_BUCKETS = (1, 7, 15, 30)


def _days_held(entry_date_str: str | None, as_of: date) -> int | None:
    if not entry_date_str:
        return None
    try:
        entry_date = datetime.fromisoformat(entry_date_str).date() if "T" in entry_date_str else date.fromisoformat(entry_date_str)
    except Exception:
        return None
    return (as_of - entry_date).days


def _pick_pnl(pick: dict[str, Any]) -> tuple[float, float, str]:
    """Returns (pnl, pnl_pct, status) for one swing pick using its current outcome."""
    direction = pick.get("direction", "LONG")
    entry = float(pick.get("entryPrice") or 0)
    qty = int(pick.get("approxQty") or 0)
    ltp = float(pick.get("currentPrice") or pick.get("ltp") or entry)
    outcome = pick.get("outcome") or {}
    hit_level = outcome.get("hitLevel")

    if hit_level == "t2":
        status = "T2_HIT"
    elif hit_level == "t1":
        status = "T1_HIT"
    elif hit_level == "sl":
        status = "SL_HIT"
    elif outcome.get("label") == "NOT TRIGGERED":
        status = "NOT_TRIGGERED"
    else:
        status = "OPEN"

    sign = 1 if direction == "LONG" else -1
    pnl = sign * (ltp - entry) * qty if entry and qty else 0.0
    pnl_pct = (pnl / (entry * qty) * 100) if entry and qty else 0.0
    return round(pnl, 2), round(pnl_pct, 2), status


def _nearest_bucket(days_held: int | None) -> int | None:
    if days_held is None:
        return None
    eligible = [b for b in DAY_BUCKETS if days_held >= b]
    return max(eligible) if eligible else None


def generate_swing_eod_report(for_date: date | None = None) -> dict[str, Any]:
    as_of = for_date or date.fromisoformat(_today_ist())
    plan = load_fixed_trade_plan()
    all_picks = (plan.get("long") or []) + (plan.get("short") or [])

    if not all_picks:
        return {"date": as_of.isoformat(), "picks": [], "summary": {"note": "No picks in fixed trade plan"}}

    alerts = get_alert_history(since="2000-01-01", limit=5000)

    rows = []
    total_pnl = 0.0
    total_deployed = 0.0
    bucket_totals: dict[int, float] = {b: 0.0 for b in DAY_BUCKETS}

    for pick in all_picks:
        pnl, pnl_pct, status = _pick_pnl(pick)
        deployed = float(pick.get("deployedCapital") or 0)
        days_held = _days_held(pick.get("entryDate"), as_of)
        bucket = _nearest_bucket(days_held)

        total_pnl += pnl
        total_deployed += deployed
        if bucket:
            bucket_totals[bucket] += pnl

        symbol_alerts = [
            a for a in alerts.get("alerts", []) if isinstance(a, dict) and a.get("symbol") == pick.get("symbol")
        ] if isinstance(alerts, dict) else []

        rows.append({
            "symbol": pick.get("symbol"),
            "direction": pick.get("direction"),
            "entryDate": pick.get("entryDate"),
            "daysHeld": days_held,
            "dayBucket": bucket,
            "status": status,
            "entryPrice": pick.get("entryPrice"),
            "currentPrice": pick.get("currentPrice"),
            "deployedCapital": deployed,
            "pnl": pnl,
            "pnlPct": pnl_pct,
            "alertsFired": symbol_alerts,
        })

    winners = [r for r in rows if r["pnl"] > 0]
    losers = [r for r in rows if r["pnl"] < 0]

    return {
        "date": as_of.isoformat(),
        "totalPicks": len(rows),
        "totalDeployed": round(total_deployed, 2),
        "totalPnl": round(total_pnl, 2),
        "totalPnlPct": round((total_pnl / total_deployed * 100), 2) if total_deployed else None,
        "winCount": len(winners),
        "lossCount": len(losers),
        "bestPerformer": max(rows, key=lambda r: r["pnl"], default=None),
        "worstPerformer": min(rows, key=lambda r: r["pnl"], default=None),
        "pnlByDayBucket": {str(k): round(v, 2) for k, v in bucket_totals.items()},
        "picks": rows,
    }