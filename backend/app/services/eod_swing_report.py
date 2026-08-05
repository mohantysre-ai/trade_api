"""Post-market-close swing analysis for the locked swing portfolio.

Uses real close marks (snapshot / Yahoo) vs entry — never mock 0→false SL_HIT.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from .trade_outcome import load_fixed_trade_plan, get_alert_history, _today_ist
from .eod_reference import get_reference_price, generate_swing_analysis

log = logging.getLogger(__name__)

DEFAULT_SWING_CAPITAL = 1_000_000.0  # ₹10L
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


def _evaluate_swing_pick(pick: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one swing pick vs reference + real close mark (never mock-0 → SL)."""
    from .eod_reference import get_close_mark_price

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
    for raw in (pick.get("_closeMark"), pick.get("currentPrice")):
        try:
            if raw is not None and float(raw) > 0:
                eod_price = float(raw)
                break
        except (TypeError, ValueError):
            pass
    if eod_price is None:
        eod_price = get_close_mark_price(symbol)
    if eod_price is None:
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
            "deployedCapital": float(pick.get("deployedCapital") or ((base_entry or 0) * qty)),
            "pnl": None,
            "pnlPct": None,
            "status": "NO_MARK",
            "analysis": analysis,
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
    pnl_pct = sign * (eod_price - base_entry) / base_entry * 100
    pnl = sign * (eod_price - base_entry) * qty if qty else None

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
    if status in ("SL_HIT", "T1_HIT", "T2_HIT"):
        diag_reason = status
    elif status == "OPEN":
        diag_reason = "EOD_SQUAREOFF"
    miss_diagnostic = None
    if diag_reason:
        from .eod_intraday_report import _build_levels_diagnostic

        exit_for_diag = eod_price
        if status == "SL_HIT" and sl > 0:
            exit_for_diag = sl
        elif status == "T1_HIT" and t1 > 0:
            exit_for_diag = t1
        elif status == "T2_HIT" and t2 > 0:
            exit_for_diag = t2
        miss_diagnostic = _build_levels_diagnostic(
            {
                **pick,
                "entryPrice": base_entry,
                "stopLoss": sl,
                "target1": t1,
                "target2": t2,
                "direction": direction,
                "rrT2": pick.get("rewardRisk") or pick.get("rrT2"),
            },
            diag_reason,
            exit_for_diag,
            float(pnl or 0),
        )

    desk_ic = None
    for key in ("deskIcSummary", "deskIc"):
        if isinstance(pick.get(key), dict):
            desk_ic = pick.get(key)
            break

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
    }


def _ensure_mock_plan() -> dict[str, Any]:
    """Legacy fallback only — prefer swing_session via load_day_picks."""
    plan = load_fixed_trade_plan()
    if plan and (plan.get("long") or plan.get("short")) and plan.get("source") != "intraday_session_engine":
        return plan
    long_picks = [p for p in _MOCK_SWING_PICKS if p.get("direction") == "LONG"]
    short_picks = [p for p in _MOCK_SWING_PICKS if p.get("direction") == "SHORT"]
    return {"long": long_picks, "short": short_picks, "updatedAt": datetime.utcnow().isoformat() + "Z", "isMock": True}


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
    all_picks, is_mock, symbol_source, desk_counts = _load_swing_book_picks(as_of)

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
            else:
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
            "totalPnl": 0,
            "totalPnlPct": None,
            "winCount": 0,
            "lossCount": 0,
            "bestPerformer": None,
            "worstPerformer": None,
            "pnlByDayBucket": {},
            "isMock": False,
            "symbolSource": symbol_source or "swing_session_empty",
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

    for pick in all_picks:
        evaluated = _evaluate_swing_pick(pick)
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

    rows = attach_outcome_narratives(rows, force=force, refresh_existing=False)
    active_rows = [r for r in rows if not r.get("skipped") and r.get("status") != "NOT_TRIGGERED"]
    winners = [r for r in active_rows if (r.get("pnl") or 0) > 0 or ((r.get("pnlPct") or 0) > 0 and r.get("pnl") is None)]
    losers = [r for r in active_rows if (r.get("pnl") or 0) < 0 or ((r.get("pnlPct") or 0) < 0 and r.get("pnl") is None)]
    lessons = build_day_lessons(rows, force=force, refresh_existing=False, existing=prior_lessons)

    report = {
        "date": as_of.isoformat(),
        "totalPicks": len(rows),
        "activePicks": len(active_rows),
        "skippedNotTriggered": skipped_count,
        "totalDeployed": round(total_deployed, 2),
        "totalPnl": round(total_pnl, 2),
        "totalPnlPct": round((total_pnl / total_deployed * 100), 2) if total_deployed else None,
        "winCount": len(winners),
        "lossCount": len(losers),
        "bestPerformer": max(
            active_rows,
            key=lambda r: float(r["pnl"] if r.get("pnl") is not None else (r.get("pnlPct") or float("-inf"))),
            default=None,
        ),
        "worstPerformer": min(
            active_rows,
            key=lambda r: float(r["pnl"] if r.get("pnl") is not None else (r.get("pnlPct") or float("inf"))),
            default=None,
        ),
        "pnlByDayBucket": {str(k): round(v, 2) for k, v in bucket_totals.items()},
        "picks": rows,
        "isMock": is_mock,
        "symbolSource": symbol_source,
        "deskCounts": desk_counts,
        "rotation": "DAILY",
        "source": "asset_matrix_buy",
        "attribution": {
            "locked": len(rows),
            "triggered": len(active_rows),
            "skipped": skipped_count,
            "wins": len(winners),
            "losses": len(losers),
            "deployed": round(total_deployed, 2),
        },
        "dayLessons": lessons,
    }
    return save_book_cache(as_of, "swing", report)
