"""Trade outcome tracking for scanner picks.

Persists scanner picks and tracks whether target1/target2/stop-loss is hit
based on live prices. Outcomes are updated each refresh cycle.

State file: trade_api_snapshot.json -> scannerPicks
"""
from __future__ import annotations

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Any

from pathlib import Path
import json as _json

# Import from the correct snapshot file that stores live market data (last_market_snapshot.json)
_LAST_MARKET_SNAPSHOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "last_market_snapshot.json",
)

def _get_market_snapshot() -> dict | None:
    """Load the last market snapshot to get live prices."""
    try:
        with open(_LAST_MARKET_SNAPSHOT, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return None

log = logging.getLogger(__name__)

_SNAPSHOT_FILE = os.environ.get(
    "SNAPSHOT_FILE",
    os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "trade_api_snapshot.json",
        )
    ),
)
_SESSION_TTL = 6 * 3600  # 6 hours — session expires at EOD
_PRICE_TTL = 120  # seconds before we re-fetch live price


def _snapshot_path() -> str:
    return _SNAPSHOT_FILE


def _load_snapshot() -> dict[str, Any]:
    try:
        with open(_snapshot_path(), "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_snapshot(payload: dict[str, Any]) -> None:
    try:
        tmp = _snapshot_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        os.replace(tmp, _snapshot_path())
    except Exception as exc:
        log.warning("Failed to save snapshot: %s", exc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_ts() -> int:
    return int(time.time())


def _persist_picks(picks: list[dict[str, Any]], direction: str, scan_ltp: float | None = None) -> None:
    """Persist scan results to snapshot under scannerPicks.
    
    Picks persist until they hit a target/stop loss. Only expired at EOD (SESSION_TTL).
    DOES NOT remove existing unresolved picks that aren't in current scan results.
    
    Args:
        picks: list of pick dicts from the scanner
        direction: "LONG" or "SHORT"
        scan_ltp: optional live LTP from the Dhan scanner row (Sym.Ltp).
                  Stored in the pick so the outcome engine can use it.
    """
    snapshot = _load_snapshot()
    picks_map = snapshot.get("scannerPicks") or {}
    now = _utc_ts()
    
    # Update/add picks from current scan
    for p in picks:
        sym = p.get("symbol") or p.get("ticker")
        if not sym:
            continue
        key = f"{sym.upper()}:{direction}"
        existing = picks_map.get(key)
        
        # Preserve outcome if already resolved (don't reset levels)
        if existing and existing.get("outcome"):
            picks_map[key] = {**existing, "updatedAt": _utc_now()}
            continue
            
        entry = {
            "symbol": sym.upper(),
            "name": p.get("name", ""),
            "direction": direction,
            "entryPrice": round(float(p.get("entryPrice") or p.get("buyAbove") or p.get("entry", 0)), 2),
            "stopLoss": round(float(p.get("stopLoss") or 0), 2),
            "target1": round(float(p.get("target1") or 0), 2),
            "target2": round(float(p.get("target2") or 0), 2),
            "riskPerShare": round(float(p.get("riskPerShare") or p.get("risk_per_share") or 0), 2),
            "rrT2": round(float(p.get("rrT2") or 0), 1),
            "approxQty": int(p.get("approxQty") or p.get("approx_qty") or 0),
            "deployedCapital": round(float(p.get("deployedCapital") or p.get("deployed_capital") or 0), 2),
            "riskAmount": round(float(p.get("riskAmount") or p.get("risk_amount") or 0), 2),
            "currentPrice": existing.get("currentPrice") if existing else None,
            "outcome": existing.get("outcome") if existing else None,
            "scanLtp": scan_ltp if scan_ltp is not None else (existing.get("scanLtp") if existing else None),
            "sessionTs": existing.get("sessionTs", now) if existing else now,
            "updatedAt": _utc_now(),
        }
        if existing:
            picks_map[key] = {**existing, **entry, "outcome": existing.get("outcome")}
        else:
            picks_map[key] = entry
    
    snapshot["scannerPicks"] = picks_map
    snapshot["scannerPicksUpdatedAt"] = _utc_now()
    _save_snapshot(snapshot)


def _load_persisted_picks() -> list[dict[str, Any]]:
    """Load picks from snapshot, prune expired sessions, return flat list."""
    snapshot = _load_snapshot()
    picks_map = snapshot.get("scannerPicks") or {}
    now = _utc_ts()
    rows: list[dict[str, Any]] = []
    expired: list[str] = []
    for key, p in picks_map.items():
        age = now - int(p.get("sessionTs") or 0)
        if age > _SESSION_TTL:
            expired.append(key)
            continue
        rows.append(p)
    for key in expired:
        del picks_map[key]
    if expired:
        snapshot["scannerPicks"] = picks_map
        _save_snapshot(snapshot)
    return rows


def _fetch_live_price(ticker: str) -> float | None:
    """Try to get live LTP from market snapshot file."""
    try:
        data = _get_market_snapshot()
        if not data:
            return None
        quotes = data.get("stockQuotes") or {}
        q = quotes.get(ticker.upper())
        if isinstance(q, dict):
            raw = q.get("ltpRaw") or q.get("ltp") or q.get("lastPrice")
            if raw is not None:
                return float(raw)
    except Exception as exc:
        log.debug("Live price fetch failed for %s: %s", ticker, exc)
    return None


def _price_age_ok(pick: dict[str, Any]) -> bool:
    updated = pick.get("updatedAt")
    if not updated:
        return False
    try:
        dt = datetime.fromisoformat(updated)
        age = time.time() - dt.timestamp()
        return age < _PRICE_TTL
    except Exception:
        return False


def compute_outcome(pick: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate target1 / target2 / stopLoss against current live price.

    Live-price precedence:
    1. Angel One snapshot (last_market_snapshot.json) — works for Nifty-100 symbols.
    2. Dhan ScanX live Ltp stored on the pick at scan time ("scanLtp").
    3. Fallback to the last cached currentPrice on the pick itself.

    Returns:
        outcome dict if resolved, or None if still pending.
    """
    entry = float(pick.get("entryPrice") or 0)
    sl = float(pick.get("stopLoss") or 0)
    t1 = float(pick.get("target1") or 0)
    t2 = float(pick.get("target2") or 0)
    direction = str(pick.get("direction") or "LONG")
    if not entry or not sl or not t1 or not t2:
        return None

    raw = pick.get("scanLtp")
    ltp = _fetch_live_price(pick["symbol"])
    if ltp is None and raw is not None:
        try:
            ltp = float(raw)
        except (TypeError, ValueError):
            ltp = None
    if ltp is None:
        ltp = pick.get("currentPrice")
    if ltp is None:
        ltp = entry
    ltp = float(ltp)
    pick["currentPrice"] = ltp
    pick["priceUpdatedAt"] = _utc_now()

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
    else:  # SHORT
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

    outcome = {
        "label": outcome_label,
        "detail": outcome_detail,
        "hitLevel": hit_level,
        "ltp": ltp,
        "pctChange": round(pct_change, 2),
        "resolvedAt": _utc_now() if hit_level else None,
    }
    return outcome


def refresh_outcomes() -> None:
    """Re-evaluate all persisted picks and update their outcomes."""
    picks = _load_persisted_picks()
    snapshot = _load_snapshot()
    picks_map = snapshot.get("scannerPicks") or {}
    changed = False
    for p in picks:
        key = f"{p['symbol']}:{p['direction']}"
        entry = picks_map.get(key)
        if not entry:
            continue
        outcome = compute_outcome(entry)
        if outcome and outcome.get("hitLevel"):
            entry["outcome"] = outcome
            changed = True
        elif outcome:
            entry["outcome"] = outcome
            entry["currentPrice"] = outcome["ltp"]
            entry["priceUpdatedAt"] = outcome["resolvedAt"]
            changed = True
    if changed:
        _save_snapshot(snapshot)


def get_trade_outcomes() -> dict[str, Any]:
    """Return all picks with their latest outcomes for the API/frontend."""
    refresh_outcomes()
    picks = _load_persisted_picks()
    # Group by direction for frontend convenience
    long_rows: list[dict[str, Any]] = []
    short_rows: list[dict[str, Any]] = []
    for p in picks:
        if p.get("direction") == "SHORT":
            short_rows.append(p)
        else:
            long_rows.append(p)
    # Sort: T2 hit first, T1 hit next, pending last
    rank = {"t2": 0, "t1": 1, "sl": 2, None: 3}
    long_rows.sort(key=lambda r: rank.get((r.get("outcome") or {}).get("hitLevel"), 3))
    short_rows.sort(key=lambda r: rank.get((r.get("outcome") or {}).get("hitLevel"), 3))
    return {
        "long": long_rows,
        "short": short_rows,
        "updatedAt": _utc_now(),
    }