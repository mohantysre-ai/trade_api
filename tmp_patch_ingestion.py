from pathlib import Path

path = Path(r"d:\trade_api\backend\app\services\eod_engine\ingestion.py")
text = path.read_text(encoding="utf-8")
start = text.index("def _normalize_pick(")
end = text.index("def _session_bounds(")
new_mid = r'''def _normalize_pick(raw: dict[str, Any], source: str, *, book: str | None = None) -> dict[str, Any] | None:
    symbol = str(raw.get("symbol") or raw.get("ticker") or "").upper().strip()
    if not symbol:
        return None
    direction = str(raw.get("direction") or "LONG").upper()
    if direction not in ("LONG", "SHORT"):
        direction = "LONG"
    entry = _f(
        raw.get("entryPrice")
        or raw.get("entry")
        or raw.get("buyAbove")
        or raw.get("ltp")
        or raw.get("scanLtp")
    )
    stop = _f(raw.get("stopLoss"))
    t1 = _f(raw.get("target1") or raw.get("target_price") or raw.get("sellPrice"))
    t2 = _f(raw.get("target2"))
    if entry is None or stop is None or t1 is None:
        return None
    score = _f(raw.get("score") or raw.get("alpha_score") or raw.get("confidence"))
    risk = _f(raw.get("riskPerShare") or raw.get("risk_per_share"))
    if risk is None and entry is not None and stop is not None:
        risk = abs(entry - stop)
    qty = int(raw.get("approxQty") or raw.get("approx_qty") or 0)
    deployed = _f(raw.get("deployedCapital") or raw.get("deployed_capital")) or 0.0
    resolved_book = str(
        book
        or raw.get("book")
        or ("SWING" if "swing" in source.lower() else "INTRADAY")
    ).upper()
    if resolved_book not in ("SWING", "INTRADAY"):
        resolved_book = "INTRADAY"
    return {
        "symbol": symbol,
        "name": raw.get("name") or symbol,
        "direction": direction,
        "book": resolved_book,
        "entryPrice": entry,
        "stopLoss": stop,
        "target1": t1,
        "target2": t2,
        "score": score,
        "sector": raw.get("sector"),
        "rewardRisk": _f(raw.get("rewardRisk") or raw.get("rrT2")),
        "approxQty": qty,
        "deployedCapital": deployed,
        "riskPerShare": risk,
        "factorBreakdown": raw.get("factorBreakdown") or raw.get("components"),
        "outcome": raw.get("outcome"),
        "atrPct": _f(raw.get("atrPct") or raw.get("atr_pct")),
        "vwap": _f(raw.get("vwap")),
        "source": source,
        "raw": raw,
    }


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_day_picks(for_date: date) -> dict[str, Any]:
    """Union locked Swing + Intraday baskets for EOD (target ~10 + 10 + 10 = 30).

    Sources (facts only, no invented symbols):
      - swing_session.json (or auto-lock from dhanSwingPicks) -> book=SWING
      - intradAy_session.json long/short -> book=INTRADAY
      - fixed_trade_plan.json only if intradAy session empty (legacy mirror)
      - eod_archive fills gaps for missing keys only
    """
    from ..swing_session import ensure_swing_session_locked, load_swing_session

    plan = load_fixed_trade_plan(for_date)
    session = load_intraday_session(for_date)
    archive = load_archive(for_date)
    snapshot = load_market_snapshot()

    ensure_swing_session_locked()
    swing = load_swing_session()

    by_key: dict[str, dict[str, Any]] = {}

    def _ingest(items: list[Any], source: str, *, book: str) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            pick = _normalize_pick(item, source, book=book)
            if not pick:
                continue
            key = f"{pick['symbol']}:{pick['direction']}:{pick['book']}"
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = pick
                continue
            if pick.get("factorBreakdown") and not existing.get("factorBreakdown"):
                existing["factorBreakdown"] = pick["factorBreakdown"]
            if existing.get("score") is None and pick.get("score") is not None:
                existing["score"] = pick["score"]
            if pick.get("outcome") and not existing.get("outcome"):
                existing["outcome"] = pick["outcome"]
            if pick.get("approxQty") and not existing.get("approxQty"):
                existing["approxQty"] = pick["approxQty"]
                existing["deployedCapital"] = pick.get("deployedCapital")

    _ingest(list(swing.get("long") or []), "swing_session", book="SWING")
    _ingest(list(swing.get("short") or []), "swing_session", book="SWING")

    if not any(p.get("book") == "SWING" for p in by_key.values()):
        block = snapshot.get("dhanSwingPicks") if isinstance(snapshot.get("dhanSwingPicks"), dict) else {}
        _ingest(list(block.get("picks") or []), "dhanSwingPicks", book="SWING")

    session_long = list(session.get("long") or [])
    session_short = list(session.get("short") or [])
    if session_long or session_short:
        _ingest(session_long, "intraday_session", book="INTRADAY")
        _ingest(session_short, "intraday_session", book="INTRADAY")
    else:
        _ingest(list(plan.get("long") or []), "fixed_trade_plan", book="INTRADAY")
        _ingest(list(plan.get("short") or []), "fixed_trade_plan", book="INTRADAY")

    archived = archive.get("intradayPicks") or {}
    if isinstance(archived, dict):
        for item in archived.values():
            if not isinstance(item, dict):
                continue
            book = str(item.get("book") or "INTRADAY").upper()
            if book not in ("SWING", "INTRADAY"):
                book = "INTRADAY"
            pick = _normalize_pick(item, "eod_archive", book=book)
            if not pick:
                continue
            key = f"{pick['symbol']}:{pick['direction']}:{pick['book']}"
            if key not in by_key:
                by_key[key] = pick

    picks = list(by_key.values())
    swing_n = sum(1 for p in picks if p.get("book") == "SWING")
    intra_long = sum(1 for p in picks if p.get("book") == "INTRADAY" and p.get("direction") == "LONG")
    intra_short = sum(1 for p in picks if p.get("book") == "INTRADAY" and p.get("direction") == "SHORT")

    regime = plan.get("regime") or session.get("regime") or swing.get("regime") or {}
    capital = plan.get("capital") or session.get("capital") or {}

    return {
        "date": for_date.isoformat(),
        "picks": picks,
        "regime": regime,
        "capital": capital,
        "plan": plan,
        "session": session,
        "swingSession": swing,
        "archive": archive,
        "snapshot": snapshot,
        "deskCounts": {
            "swing": swing_n,
            "intradayLong": intra_long,
            "intradayShort": intra_short,
            "total": len(picks),
        },
        "sources": {
            "planSessionDate": plan.get("sessionDate"),
            "sessionDate": session.get("sessionDate"),
            "swingSessionDate": swing.get("sessionDate"),
            "archiveDate": archive.get("date"),
            "pickCount": len(picks),
            "swingLocked": bool(swing.get("locked")),
            "intradayLocked": bool(session.get("locked")),
        },
    }


'''
path.write_text(text[:start] + new_mid + text[end:], encoding="utf-8")
print("ok", path.stat().st_size)
