"""Post-market-close swing analysis for the Asset Matrix fixed trade plan.

Computes P&L by comparing each pick's current/exit price against the 9:30 AM
reference price on July 17, 2026 (the canonical entry reference).

For every Asset Matrix stock, we calculate:
  - What was the 9:30 AM price on July 17? (Angel One candle or seed table)
  - What is the current/last price? (mock EOD for now, or live price)
  - What happened? Did T1/T2/SL get hit? What's the P&L vs the reference?
  - Hedge Fund analysis — per-stock diagnosis text explaining the move

P&L day-bucketing: Day 1 / Day 7 / Day 15 / Day 30 from July 17 to report date.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .trade_outcome import load_fixed_trade_plan, get_alert_history, _today_ist
from .eod_reference import get_reference_price, get_mock_eod_price, get_reference_and_eod, generate_swing_analysis

DEFAULT_SWING_CAPITAL = 500_000.0  # ₹5L, informational
DAY_BUCKETS = (1, 7, 15, 30)

# ---------------------------------------------------------------------------
#  Mock swing trade plan — used when no fixed_trade_plan.json exists yet.
#  Contains picks matching the Asset Matrix / scan results.
# ---------------------------------------------------------------------------
_MOCK_SWING_PICKS: list[dict[str, Any]] = [
    # === Scanner Shorts (10 picks) ===
    {"symbol": "KALAMANDIR", "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 1000, "deployedCapital": 91970.00,  "entryPrice": 91.97,  "stopLoss": 95.86,  "target1": 86.14,  "target2": 82.25},
    {"symbol": "RAMASTEEL",  "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 20000, "deployedCapital": 86600.00,  "entryPrice": 4.33,   "stopLoss": 4.50,   "target1": 4.08,   "target2": 3.91},
    {"symbol": "GTLINFRA",   "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 80000, "deployedCapital": 99200.00,  "entryPrice": 1.24,   "stopLoss": 1.30,   "target1": 1.15,   "target2": 1.09},
    {"symbol": "VIKASLIFE",  "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 70000, "deployedCapital": 93800.00,  "entryPrice": 1.34,   "stopLoss": 1.39,   "target1": 1.27,   "target2": 1.22},
    {"symbol": "JAINREC",    "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 300,   "deployedCapital": 98640.00,  "entryPrice": 328.80, "stopLoss": 346.37, "target1": 302.44, "target2": 284.88},
    {"symbol": "GREENPOWER", "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 10000, "deployedCapital": 99500.00,  "entryPrice": 9.95,   "stopLoss": 10.21,  "target1": 9.56,   "target2": 9.30},
    {"symbol": "BSE",        "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 25,    "deployedCapital": 89545.00,  "entryPrice": 3581.80,"stopLoss": 3697.29,"target1": 3408.57,"target2": 3293.08},
    {"symbol": "BAJAJCON",   "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 200,   "deployedCapital": 105130.00, "entryPrice": 525.65, "stopLoss": 557.41, "target1": 478.01, "target2": 446.25},
    {"symbol": "VIKASECO",   "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 80000, "deployedCapital": 92000.00,  "entryPrice": 1.15,   "stopLoss": 1.19,   "target1": 1.09,   "target2": 1.05},
    {"symbol": "NCC",        "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 700,   "deployedCapital": 97720.00,  "entryPrice": 139.60, "stopLoss": 143.53, "target1": 133.70, "target2": 129.78},
    # === Scanner Longs (10 picks) ===
    {"symbol": "RELAXO",     "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 250,   "deployedCapital": 109987.50, "entryPrice": 439.95, "stopLoss": 418.48, "target1": 472.15, "target2": 504.36},
    {"symbol": "CUPID",      "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 500,   "deployedCapital": 107390.00, "entryPrice": 214.78, "stopLoss": 203.38, "target1": 231.88, "target2": 248.98},
    {"symbol": "NAVKARURB",  "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 80000, "deployedCapital": 92800.00,  "entryPrice": 1.16,   "stopLoss": 1.10,   "target1": 1.25,   "target2": 1.34},
    {"symbol": "BAJFINANCE", "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 100,   "deployedCapital": 105630.00, "entryPrice": 1056.30, "stopLoss": 1031.65, "target1": 1093.27, "target2": 1130.25},
    {"symbol": "ADANIENT",   "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 30,    "deployedCapital": 94821.00,  "entryPrice": 3160.70, "stopLoss": 3078.29, "target1": 3284.31, "target2": 3407.93},
    {"symbol": "ZEEL",       "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 1000,  "deployedCapital": 107400.00, "entryPrice": 107.40, "stopLoss": 102.17, "target1": 115.25, "target2": 123.09},
    {"symbol": "BPCL",       "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 350,   "deployedCapital": 110442.50, "entryPrice": 315.55, "stopLoss": 307.74, "target1": 327.26, "target2": 338.98},
    {"symbol": "SBIN",       "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 100,   "deployedCapital": 104430.00, "entryPrice": 1044.30, "stopLoss": 1024.73, "target1": 1073.65, "target2": 1103.01},
    {"symbol": "M&M",        "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 35,    "deployedCapital": 111272.00, "entryPrice": 3179.20, "stopLoss": 3105.88, "target1": 3289.18, "target2": 3399.16},
    {"symbol": "PIRAMALFIN", "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 50,    "deployedCapital": 107215.00, "entryPrice": 2144.30, "stopLoss": 2075.93, "target1": 2246.86, "target2": 2349.41},
    # === Swing Longs (additional) ===
    {"symbol": "RELIANCE",   "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 50,    "deployedCapital": 147500.00, "entryPrice": 2950.00, "stopLoss": 2850.00, "target1": 3100.00, "target2": 3250.00},
    {"symbol": "TCS",        "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 30,    "deployedCapital": 123600.00, "entryPrice": 4120.00, "stopLoss": 3980.00, "target1": 4320.00, "target2": 4500.00},
    {"symbol": "HDFCBANK",   "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 80,    "deployedCapital": 134400.00, "entryPrice": 1680.00, "stopLoss": 1620.00, "target1": 1760.00, "target2": 1850.00},
    {"symbol": "INFY",       "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 80,    "deployedCapital": 121600.00, "entryPrice": 1520.00, "stopLoss": 1470.00, "target1": 1600.00, "target2": 1680.00},
    {"symbol": "BHARTIARTL", "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 100,   "deployedCapital": 142500.00, "entryPrice": 1425.00, "stopLoss": 1380.00, "target1": 1500.00, "target2": 1580.00},
    {"symbol": "LT",         "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 40,    "deployedCapital": 146000.00, "entryPrice": 3650.00, "stopLoss": 3530.00, "target1": 3830.00, "target2": 4000.00},
    {"symbol": "SUNPHARMA",  "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 80,    "deployedCapital": 126400.00, "entryPrice": 1580.00, "stopLoss": 1650.00, "target1": 1480.00, "target2": 1400.00},
    {"symbol": "TITAN",      "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 35,    "deployedCapital": 131600.00, "entryPrice": 3760.00, "stopLoss": 3640.00, "target1": 3950.00, "target2": 4120.00},
    {"symbol": "MARUTI",     "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 10,    "deployedCapital": 124500.00, "entryPrice": 12450.00,"stopLoss": 12100.00,"target1": 13000.00,"target2": 13600.00},
    {"symbol": "HINDUNILVR", "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 50,    "deployedCapital": 132500.00, "entryPrice": 2650.00, "stopLoss": 2750.00, "target1": 2520.00, "target2": 2400.00},
    {"symbol": "ITC",        "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 300,   "deployedCapital": 144000.00, "entryPrice": 480.00,  "stopLoss": 465.00,  "target1": 505.00,  "target2": 530.00},
    {"symbol": "WIPRO",      "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 250,   "deployedCapital": 127500.00, "entryPrice": 510.00,  "stopLoss": 494.00,  "target1": 535.00,  "target2": 560.00},
    {"symbol": "NTPC",       "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 400,   "deployedCapital": 146000.00, "entryPrice": 365.00,  "stopLoss": 353.00,  "target1": 383.00,  "target2": 400.00},
    {"symbol": "ONGC",       "direction": "SHORT", "entryDate": "2026-07-17", "approxQty": 450,   "deployedCapital": 128250.00, "entryPrice": 285.00,  "stopLoss": 298.00,  "target1": 268.00,  "target2": 252.00},
    {"symbol": "JSWSTEEL",   "direction": "LONG",  "entryDate": "2026-07-17", "approxQty": 150,   "deployedCapital": 138000.00, "entryPrice": 920.00,  "stopLoss": 890.00,  "target1": 965.00,  "target2": 1010.00},
]


def _days_held(entry_date_str: str | None, as_of: date) -> int | None:
    if not entry_date_str:
        return None
    try:
        entry_date = datetime.fromisoformat(entry_date_str).date() if "T" in entry_date_str else date.fromisoformat(entry_date_str)
    except Exception:
        return None
    return (as_of - entry_date).days


def _evaluate_swing_pick(pick: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one swing pick against its 9:30 AM reference price and mock EOD."""
    symbol = (pick.get("symbol") or "").upper()
    direction = pick.get("direction", "LONG")
    entry = float(pick.get("entryPrice") or 0)
    qty = int(pick.get("approxQty") or 0)
    sl = float(pick.get("stopLoss") or 0)
    t1 = float(pick.get("target1") or 0)
    t2 = float(pick.get("target2") or 0)

    ref_price = get_reference_price(symbol)
    eod_price = get_mock_eod_price(symbol)
    base_entry = entry if entry else ref_price

    sign = 1 if direction == "LONG" else -1
    pnl = sign * (eod_price - base_entry) * qty if base_entry and qty else 0.0
    pnl_pct = (pnl / (base_entry * qty) * 100) if base_entry and qty else 0.0

    if direction == "LONG":
        if eod_price >= t2 and t2 > 0:
            status = "T2_HIT"
        elif eod_price >= t1 and t1 > 0:
            status = "T1_HIT"
        elif eod_price <= sl and sl > 0:
            status = "SL_HIT"
        else:
            status = "OPEN"
    else:
        if eod_price <= t2 and t2 > 0:
            status = "T2_HIT"
        elif eod_price <= t1 and t1 > 0:
            status = "T1_HIT"
        elif eod_price >= sl and sl > 0:
            status = "SL_HIT"
        else:
            status = "OPEN"

    # Generate hedge fund analysis for this pick
    analysis = generate_swing_analysis(symbol, direction, base_entry, eod_price, pnl, pnl_pct, status)

    return {
        "symbol": symbol,
        "direction": direction,
        "entryDate": pick.get("entryDate"),
        "entryPrice": base_entry,
        "refPrice930": ref_price,
        "currentPrice": eod_price,
        "stopLoss": sl,
        "target1": t1,
        "target2": t2,
        "qty": qty,
        "deployedCapital": float(pick.get("deployedCapital") or (base_entry * qty)),
        "pnl": round(pnl, 2),
        "pnlPct": round(pnl_pct, 2),
        "status": status,
        "analysis": analysis,
    }


def _ensure_mock_plan() -> dict[str, Any]:
    """If no fixed trade plan exists, seed one from the mock picks."""
    plan = load_fixed_trade_plan()
    if plan and (plan.get("long") or plan.get("short")):
        return plan
    long_picks = [p for p in _MOCK_SWING_PICKS if p.get("direction") == "LONG"]
    short_picks = [p for p in _MOCK_SWING_PICKS if p.get("direction") == "SHORT"]
    return {"long": long_picks, "short": short_picks, "updatedAt": datetime.utcnow().isoformat() + "Z", "isMock": True}


def generate_swing_eod_report(for_date: date | None = None) -> dict[str, Any]:
    as_of = for_date or date.fromisoformat(_today_ist())
    plan = _ensure_mock_plan()
    all_picks = (plan.get("long") or []) + (plan.get("short") or [])

    if not all_picks:
        return {"date": as_of.isoformat(), "picks": [], "summary": {"note": "No picks in fixed trade plan"}}

    alerts = get_alert_history(since="2000-01-01", limit=5000)

    rows = []
    total_pnl = 0.0
    total_deployed = 0.0
    bucket_totals: dict[int, float] = {b: 0.0 for b in DAY_BUCKETS}

    for pick in all_picks:
        evaluated = _evaluate_swing_pick(pick)
        deployed = evaluated["deployedCapital"]
        days_held = _days_held(evaluated.get("entryDate"), as_of)
        bucket = max([b for b in DAY_BUCKETS if days_held is not None and days_held >= b], default=None)

        total_pnl += evaluated["pnl"]
        total_deployed += deployed
        if bucket:
            bucket_totals[bucket] += evaluated["pnl"]

        symbol_alerts = [
            a for a in alerts.get("alerts", []) if isinstance(a, dict) and a.get("symbol") == evaluated["symbol"]
        ] if isinstance(alerts, dict) else []

        rows.append({
            **evaluated,
            "daysHeld": days_held,
            "dayBucket": bucket,
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
        "isMock": plan.get("isMock", False),
        "referenceDate": "2026-07-17",
        "referenceLabel": "9:30 AM IST July 17 open (Friday session reference)",
    }