from pathlib import Path

path = Path(r"d:\trade_api\backend\app\services\eod_swing_report.py")
text = path.read_text(encoding="utf-8")
start = text.index("def _ensure_mock_plan(")
# replace through end of file
new_tail = r'''def _ensure_mock_plan() -> dict[str, Any]:
    """Legacy fallback only — prefer swing_session via load_day_picks."""
    plan = load_fixed_trade_plan()
    if plan and (plan.get("long") or plan.get("short")) and plan.get("source") != "intraday_session_engine":
        return plan
    long_picks = [p for p in _MOCK_SWING_PICKS if p.get("direction") == "LONG"]
    short_picks = [p for p in _MOCK_SWING_PICKS if p.get("direction") == "SHORT"]
    return {"long": long_picks, "short": short_picks, "updatedAt": datetime.utcnow().isoformat() + "Z", "isMock": True}


def _load_swing_book_picks(as_of: date) -> tuple[list[dict[str, Any]], bool, str, dict[str, int]]:
    """Swing Book — locked swing portfolio only (not intradAy session)."""
    from .eod_engine.ingestion import load_day_picks

    day = load_day_picks(as_of)
    desk_counts = dict(day.get("deskCounts") or {})
    swing_rows = [
        p for p in (day.get("picks") or [])
        if isinstance(p, dict) and p.get("symbol") and str(p.get("book") or "").upper() == "SWING"
    ]
    if swing_rows:
        picks: list[dict[str, Any]] = []
        for p in swing_rows:
            raw = p.get("raw") if isinstance(p.get("raw"), dict) else {}
            picks.append({
                **raw,
                "symbol": p.get("symbol"),
                "direction": p.get("direction") or "LONG",
                "entryDate": raw.get("entryDate") or (day.get("swingSession") or {}).get("sessionDate"),
                "entryPrice": p.get("entryPrice"),
                "stopLoss": p.get("stopLoss"),
                "target1": p.get("target1"),
                "target2": p.get("target2"),
                "approxQty": p.get("approxQty") or 0,
                "deployedCapital": p.get("deployedCapital") or 0,
                "currentPrice": raw.get("currentPrice") or p.get("entryPrice"),
                "book": "SWING",
            })
        return picks, False, "swing_session", desk_counts

    plan = _ensure_mock_plan()
    all_picks = (plan.get("long") or []) + (plan.get("short") or [])
    return all_picks, bool(plan.get("isMock")), ("mock" if plan.get("isMock") else "fixed_trade_plan"), desk_counts


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
            if cached.get("symbolSource") in (None, "fixed_trade_plan") and symbol_source == "swing_session":
                pass
            elif cached.get("isMock") and all_picks and not is_mock:
                pass
            else:
                return cached

    if not all_picks:
        empty = {
            "date": as_of.isoformat(),
            "picks": [],
            "summary": {"note": "No locked swing portfolio — lock swing or refresh dhanSwingPicks"},
            "totalPicks": 0,
            "totalDeployed": 0,
            "totalPnl": 0,
            "totalPnlPct": None,
            "winCount": 0,
            "lossCount": 0,
            "bestPerformer": None,
            "worstPerformer": None,
            "pnlByDayBucket": {},
            "isMock": True,
            "symbolSource": symbol_source,
            "deskCounts": desk_counts,
        }
        return save_book_cache(as_of, "swing", empty)

    alerts = get_alert_history(since=as_of.isoformat(), limit=200)

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
            "book": "SWING",
        })

    winners = [r for r in rows if r["pnl"] > 0]
    losers = [r for r in rows if r["pnl"] < 0]

    report = {
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
        "isMock": is_mock,
        "symbolSource": symbol_source,
        "deskCounts": desk_counts,
        "referenceDate": "2026-07-17",
        "referenceLabel": "9:30 AM IST July 17 open (Friday session reference)",
    }
    return save_book_cache(as_of, "swing", report)
'''
path.write_text(text[:start] + new_tail, encoding="utf-8")
print("ok", path.stat().st_size)
