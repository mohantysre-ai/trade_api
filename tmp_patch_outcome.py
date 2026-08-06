from pathlib import Path

p = Path(r"d:\trade_api\backend\app\services\trade_outcome.py")
t = p.read_text(encoding="utf-8")
start = t.find("def compute_outcome(pick:")
end = t.find("def refresh_outcomes()")
if start < 0 or end < 0:
    raise SystemExit(f"markers {start} {end}")

new = '''def compute_outcome(pick: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate exits against LTP — scale-trail when exitPlan present, else binary T1/T2/SL."""
    from .exit_plan import attach_exit_plan, evaluate_scale_trail

    entry = float(pick.get("entryPrice") or 0)
    sl = float(pick.get("stopLoss") or 0)
    t1 = float(pick.get("target1") or 0)
    t2 = float(pick.get("target2") or 0)
    direction = str(pick.get("direction") or "LONG")

    ltp = _resolve_ltp(pick)
    pick["currentPrice"] = ltp
    pick["priceUpdatedAt"] = _utc_now()

    plan = pick.get("exitPlan") if isinstance(pick.get("exitPlan"), dict) else None
    if (not plan or plan.get("mode") != "SCALE_TRAIL") and entry and (sl or pick.get("riskPerShare")) and pick.get("approxQty"):
        enriched = attach_exit_plan(pick)
        pick["exitPlan"] = enriched.get("exitPlan")
        if enriched.get("target1") is not None:
            pick["target1"] = enriched["target1"]
        if enriched.get("target2") is not None:
            pick["target2"] = enriched["target2"]
        plan = pick.get("exitPlan")

    if plan and plan.get("mode") == "SCALE_TRAIL":
        result = evaluate_scale_trail(pick, ltp, after_close=False)
        if result:
            if result.get("closed"):
                result["resolvedAt"] = _utc_now()
            if isinstance(result.get("exitState"), dict):
                pick["exitState"] = result["exitState"]
            pick["realizedPnl"] = result.get("realizedPnl")
            pick["unrealizedPnl"] = result.get("unrealizedPnl")
            pick["remainingQty"] = result.get("remainingQty")
            pick["effectiveStop"] = result.get("effectiveStop")
            if result.get("closed"):
                pick["closed"] = True
            return {
                "label": result.get("label"),
                "detail": result.get("detail"),
                "hitLevel": result.get("hitLevel"),
                "ltp": result.get("ltp"),
                "pctChange": result.get("pctChange"),
                "resolvedAt": result.get("resolvedAt"),
                "exitState": result.get("exitState"),
                "realizedPnl": result.get("realizedPnl"),
                "unrealizedPnl": result.get("unrealizedPnl"),
                "remainingQty": result.get("remainingQty"),
                "effectiveStop": result.get("effectiveStop"),
                "rMultiple": result.get("rMultiple"),
                "closed": result.get("closed"),
                "scaleTrail": True,
            }

    if not entry or not sl or not t1 or not t2:
        return None

    outcome_label = "PENDING"
    outcome_detail = "Awaiting trade"
    hit_level = None
    pct_change = ((ltp - entry) / entry * 100) if entry else 0.0

    if direction == "LONG":
        if ltp >= t2:
            outcome_label = "TARGET 2 HIT"
            outcome_detail = f"LTP {ltp:.2f} >= T2 {t2:.2f}"
            hit_level = "t2"
        elif ltp >= t1:
            outcome_label = "TARGET 1 HIT"
            outcome_detail = f"LTP {ltp:.2f} >= T1 {t1:.2f}"
            hit_level = "t1"
        elif ltp <= sl:
            outcome_label = "STOP LOSS HIT"
            outcome_detail = f"LTP {ltp:.2f} <= SL {sl:.2f}"
            hit_level = "sl"
        else:
            outcome_label = "PENDING"
            outcome_detail = f"LTP {ltp:.2f} | Entry {entry:.2f} | {pct_change:+.2f}%"
            hit_level = None
    else:
        if ltp <= t2:
            outcome_label = "TARGET 2 HIT"
            outcome_detail = f"LTP {ltp:.2f} <= T2 {t2:.2f}"
            hit_level = "t2"
        elif ltp <= t1:
            outcome_label = "TARGET 1 HIT"
            outcome_detail = f"LTP {ltp:.2f} <= T1 {t1:.2f}"
            hit_level = "t1"
        elif ltp >= sl:
            outcome_label = "STOP LOSS HIT"
            outcome_detail = f"LTP {ltp:.2f} >= SL {sl:.2f}"
            hit_level = "sl"
        else:
            outcome_label = "PENDING"
            outcome_detail = f"LTP {ltp:.2f} | Entry {entry:.2f} | {pct_change:+.2f}%"
            hit_level = None

    return {
        "label": outcome_label,
        "detail": outcome_detail,
        "hitLevel": hit_level,
        "ltp": ltp,
        "pctChange": round(pct_change, 2),
        "resolvedAt": _utc_now() if hit_level else None,
    }


def _finalize_pending_outcome(pick: dict[str, Any], ltp: float) -> dict[str, Any]:
    """Mark a still-PENDING intradAy pick as NOT TRIGGERED at market close."""
    entry = float(pick.get("entryPrice") or 0)
    pct_change = ((ltp - entry) / entry * 100) if entry else 0.0
    return {
        "label": "NOT TRIGGERED",
        "detail": f"LTP {ltp:.2f} | never crossed T1/SL | {pct_change:+.2f}%",
        "hitLevel": None,
        "ltp": ltp,
        "pctChange": round(pct_change, 2),
        "resolvedAt": _utc_now(),
        "final": True,
    }


def evaluate_outcome(pick: dict[str, Any], finalize_if_closed: bool = False) -> dict[str, Any] | None:
    """Compute an outcome, finalizing a still-pending pick if the market has closed."""
    from .exit_plan import evaluate_scale_trail

    plan = pick.get("exitPlan") if isinstance(pick.get("exitPlan"), dict) else None
    after_close = bool(_is_after_market_close() and finalize_if_closed)

    if plan and plan.get("mode") == "SCALE_TRAIL":
        ltp = _resolve_ltp(pick)
        pick["currentPrice"] = ltp
        existing = pick.get("outcome")
        if existing and existing.get("closed") and existing.get("final"):
            return existing
        result = evaluate_scale_trail(pick, ltp, after_close=after_close)
        if result:
            if result.get("closed"):
                result["resolvedAt"] = _utc_now()
                if after_close:
                    result["final"] = True
            if isinstance(result.get("exitState"), dict):
                pick["exitState"] = result["exitState"]
            return {
                "label": result.get("label"),
                "detail": result.get("detail"),
                "hitLevel": result.get("hitLevel"),
                "ltp": result.get("ltp"),
                "pctChange": result.get("pctChange"),
                "resolvedAt": result.get("resolvedAt"),
                "exitState": result.get("exitState"),
                "realizedPnl": result.get("realizedPnl"),
                "unrealizedPnl": result.get("unrealizedPnl"),
                "remainingQty": result.get("remainingQty"),
                "effectiveStop": result.get("effectiveStop"),
                "rMultiple": result.get("rMultiple"),
                "closed": result.get("closed"),
                "scaleTrail": True,
                "final": result.get("final"),
            }

    if not after_close:
        return compute_outcome(pick)

    existing = pick.get("outcome")
    if existing and (existing.get("hitLevel") or existing.get("final")):
        return existing

    ltp = _resolve_ltp(pick)
    pick["currentPrice"] = ltp
    pick["priceUpdatedAt"] = _utc_now()
    pending = compute_outcome(pick)
    if pending and pending.get("hitLevel") is None and not pending.get("scaleTrail"):
        return _finalize_pending_outcome(pick, ltp)
    return pending


'''

p.write_text(t[:start] + new + t[end:], encoding="utf-8")
print("ok", start, end)
