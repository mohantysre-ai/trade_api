from pathlib import Path

path = Path(r"d:\trade_api\backend\app\services\intraday_session_engine.py")
text = path.read_text(encoding="utf-8")
start = text.index("def commit_session(force: bool = False)")
# end at next top-level def after commit_session
# find "def get_session" or similar after start
rest = text[start + 1 :]
# find next \ndef that is at module level for a following function
import re
m = re.search(r"\ndef [a-zA-Z_]", rest)
if not m:
    raise SystemExit("no next def")
end = start + 1 + m.start() + 1  # include leading newline before next def

new_fn = r'''def commit_session(force: bool = False) -> dict[str, Any]:
    """Lock high-probability 5 BUY + 5 SELL from the 10+10 candidate pool."""
    existing = load_session()
    if existing.get("locked") and not force:
        return {
            "success": False,
            "error": "SESSION BASKET LOCKED — symbols immutable. Pass force=true only to rebuild after explicit unlock.",
            "session": existing,
        }

    candidates = generate_candidates()
    pool_long = candidates.get("proposedLong") or []
    pool_short = candidates.get("proposedShort") or []
    long_rows = candidates.get("adoptLong") or []
    short_rows = candidates.get("adoptShort") or []
    if len(pool_long) < LOCK_SIZE or len(pool_short) < LOCK_SIZE:
        return {
            "success": False,
            "error": (
                f"Insufficient candidate pool for {LOCK_SIZE}+{LOCK_SIZE} adopt "
                f"(got {len(pool_long)}L / {len(pool_short)}S of {BASKET_SIZE}+{BASKET_SIZE}). "
                f"Refresh market snapshot."
            ),
            "candidates": candidates,
        }
    if len(long_rows) < LOCK_SIZE or len(short_rows) < LOCK_SIZE:
        regime = candidates.get("regime") or {}
        long_rows = _adopt_high_probability(
            pool_long, LOCK_SIZE, direction="LONG", capital=LONG_CAPITAL, regime=regime
        )
        short_rows = _adopt_high_probability(
            pool_short, LOCK_SIZE, direction="SHORT", capital=SHORT_CAPITAL, regime=regime
        )
    if len(long_rows) < LOCK_SIZE or len(short_rows) < LOCK_SIZE:
        return {
            "success": False,
            "error": (
                f"Could not adopt {LOCK_SIZE}+{LOCK_SIZE} high-probability picks "
                f"(got {len(long_rows)}L / {len(short_rows)}S)."
            ),
            "candidates": candidates,
        }

    session_date = _ist_now().strftime("%Y-%m-%d")
    committed_at = _utc_now_iso()
    events = [
        {
            "type": "SESSION_COMMIT",
            "at": committed_at,
            "long": [r["symbol"] for r in long_rows],
            "short": [r["symbol"] for r in short_rows],
            "candidatePoolLong": [r["symbol"] for r in pool_long],
            "candidatePoolShort": [r["symbol"] for r in pool_short],
            "funnel": f"{len(pool_long)}+{len(pool_short)} → adopt {len(long_rows)}+{len(short_rows)}",
            "sleeves": {
                "momentumSlots": MOMENTUM_SLOTS,
                "meanRevSlots": (candidates.get("capital") or {}).get("meanRevSlots"),
                "lockSize": LOCK_SIZE,
                "candidatePoolSize": BASKET_SIZE,
            },
            "executionPolicy": "MANUAL_ONLY",
        }
    ]

    capital = dict(candidates.get("capital") or {})
    capital["basketSize"] = LOCK_SIZE
    capital["candidatePoolSize"] = BASKET_SIZE
    capital["lockSize"] = LOCK_SIZE

    session = {
        "success": True,
        "locked": True,
        "sessionDate": session_date,
        "committedAt": committed_at,
        "updatedAt": committed_at,
        "snapshotUpdatedAt": candidates.get("snapshotUpdatedAt"),
        "dataStale": candidates.get("dataStale"),
        "regime": candidates.get("regime"),
        "meanRevGate": candidates.get("meanRevGate"),
        "capital": capital,
        "executionPolicy": "MANUAL_ONLY",
        "long": long_rows,
        "short": short_rows,
        "candidatePoolLong": pool_long,
        "candidatePoolShort": pool_short,
        "events": events,
        "funnel": candidates.get("funnel"),
        "weights": candidates.get("weights"),
        "meanRevWeights": candidates.get("meanRevWeights"),
    }
    save_session(session)

    try:
        from .swing_session import ensure_swing_session_locked
        ensure_swing_session_locked()
    except Exception as exc:
        log.warning("Swing session auto-lock failed: %s", exc)

    plan = {
        "long": [
            {
                "symbol": r["symbol"],
                "direction": "LONG",
                "entryDate": session_date,
                "approxQty": r.get("approxQty"),
                "deployedCapital": r.get("deployedCapital"),
                "entryPrice": r.get("entryPrice"),
                "stopLoss": r.get("stopLoss"),
                "target1": r.get("target1"),
                "target2": r.get("target2"),
                "scanLtp": r.get("ltp"),
                "currentPrice": r.get("ltp"),
                "score": r.get("score"),
                "sector": r.get("sector"),
                "rewardRisk": r.get("rewardRisk"),
                "status": "RUNNING",
                "sessionLocked": True,
                "adopted": True,
            }
            for r in long_rows
        ],
        "short": [
            {
                "symbol": r["symbol"],
                "direction": "SHORT",
                "entryDate": session_date,
                "approxQty": r.get("approxQty"),
                "deployedCapital": r.get("deployedCapital"),
                "entryPrice": r.get("entryPrice"),
                "stopLoss": r.get("stopLoss"),
                "target1": r.get("target1"),
                "target2": r.get("target2"),
                "scanLtp": r.get("ltp"),
                "currentPrice": r.get("ltp"),
                "score": r.get("score"),
                "sector": r.get("sector"),
                "rewardRisk": r.get("rewardRisk"),
                "status": "RUNNING",
                "sessionLocked": True,
                "adopted": True,
            }
            for r in short_rows
        ],
        "updatedAt": committed_at,
        "sessionDate": session_date,
        "locked": True,
        "executionPolicy": "MANUAL_ONLY",
        "capital": capital,
        "regime": candidates.get("regime"),
        "source": "intraday_session_engine",
        "funnel": f"{BASKET_SIZE}+{BASKET_SIZE} candidates → {LOCK_SIZE}+{LOCK_SIZE} locked",
    }
    _atomic_write(_FIXED_PLAN_FILE, plan)
    session["fixedPlanSynced"] = True
    return session

'''
path.write_text(text[:start] + new_fn + text[end:], encoding="utf-8")
print("ok commit_session patched", start, end)
