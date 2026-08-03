"""Durable swing portfolio lock for EOD / Book P&L.

Swing symbols live in last_market_snapshot.dhanSwingPicks until locked here.
Intraday long/short stay in intradAy_session.json — do not overwrite this file.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_SERVICES_DIR)
_BACKEND_DIR = os.path.dirname(_APP_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

_SWING_SESSION_PATH = os.environ.get(
    "SWING_SESSION_FILE",
    os.path.join(_REPO_ROOT, "swing_session.json"),
)
_SNAPSHOT_PATH = os.path.join(_SERVICES_DIR, "last_market_snapshot.json")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ist_today() -> str:
    return datetime.now(tz=IST).strftime("%Y-%m-%d")


def _atomic_write(path: str, payload: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_swing_session() -> dict[str, Any]:
    return _read_json(_SWING_SESSION_PATH)


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_swing_row(raw: dict[str, Any], session_date: str) -> dict[str, Any] | None:
    symbol = str(raw.get("symbol") or raw.get("ticker") or "").upper().strip()
    if not symbol:
        return None
    entry = _f(raw.get("entryPrice") or raw.get("buyAbove") or raw.get("entry") or raw.get("ltp") or raw.get("scanLtp"))
    stop = _f(raw.get("stopLoss"))
    t1 = _f(raw.get("target1") or raw.get("target_price"))
    t2 = _f(raw.get("target2"))
    if entry is None or stop is None or t1 is None:
        return None
    risk = _f(raw.get("riskPerShare"))
    if risk is None:
        risk = abs(entry - stop)
    return {
        "symbol": symbol,
        "name": raw.get("name") or symbol,
        "direction": "LONG",
        "book": "SWING",
        "entryDate": raw.get("entryDate") or session_date,
        "entryPrice": entry,
        "buyAbove": _f(raw.get("buyAbove")) or entry,
        "stopLoss": stop,
        "target1": t1,
        "target2": t2,
        "riskPerShare": risk,
        "rewardRisk": _f(raw.get("rewardRisk") or raw.get("rrT2")),
        "approxQty": int(raw.get("approxQty") or raw.get("approx_qty") or 0),
        "deployedCapital": _f(raw.get("deployedCapital")) or 0.0,
        "score": _f(raw.get("score")),
        "sector": raw.get("sector"),
        "scanLtp": _f(raw.get("scanLtp") or raw.get("ltp")),
        "currentPrice": _f(raw.get("currentPrice") or raw.get("ltp") or raw.get("scanLtp") or entry),
        "status": raw.get("status") or "RUNNING",
        "sessionLocked": True,
        "source": "swing_session",
    }


def _picks_from_snapshot() -> tuple[list[dict[str, Any]], str]:
    snap = _read_json(_SNAPSHOT_PATH)
    block = snap.get("dhanSwingPicks") if isinstance(snap.get("dhanSwingPicks"), dict) else {}
    picks = block.get("picks") if isinstance(block, dict) else None
    if not isinstance(picks, list):
        picks = []
    src = str((block or {}).get("source") or "dhanSwingPicks")
    return [p for p in picks if isinstance(p, dict)], src


def lock_swing_session(*, force: bool = False) -> dict[str, Any]:
    """Snapshot current swing portfolio (dhanSwingPicks) into swing_session.json."""
    existing = load_swing_session()
    if existing.get("locked") and not force and (existing.get("long") or []):
        return {
            "success": True,
            "alreadyLocked": True,
            "session": existing,
        }

    raw_picks, snap_src = _picks_from_snapshot()
    session_date = _ist_today()
    long_rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for raw in raw_picks:
        row = _normalize_swing_row(raw, session_date)
        if row is None:
            sym = str(raw.get("symbol") or "?").upper()
            skipped.append(sym)
            continue
        long_rows.append(row)

    if not long_rows:
        return {
            "success": False,
            "error": "No swing picks with entry/SL/T1 in dhanSwingPicks — refresh market data first.",
            "skipped": skipped,
            "session": existing,
        }

    committed_at = _utc_now_iso()
    session = {
        "success": True,
        "locked": True,
        "book": "SWING",
        "sessionDate": session_date,
        "committedAt": committed_at,
        "updatedAt": committed_at,
        "executionPolicy": "MANUAL_ONLY",
        "source": snap_src,
        "long": long_rows,
        "short": [],
        "skippedIncomplete": skipped,
        "counts": {"long": len(long_rows), "short": 0, "total": len(long_rows)},
    }
    _atomic_write(_SWING_SESSION_PATH, session)
    log.info("Locked swing session: %d LONGs (%s)", len(long_rows), session_date)
    return {"success": True, "alreadyLocked": False, "session": session}


def ensure_swing_session_locked() -> dict[str, Any]:
    """Idempotent lock — used by intradAy commit and EOD ingest."""
    existing = load_swing_session()
    if existing.get("locked") and (existing.get("long") or []):
        return existing
    result = lock_swing_session(force=False)
    return result.get("session") or existing
