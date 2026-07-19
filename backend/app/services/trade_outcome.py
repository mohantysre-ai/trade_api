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
from datetime import datetime, timezone, timedelta
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

# NSE equity cash trading session (IST)
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MIN = 15
_MARKET_CLOSE_HOUR = 15
_MARKET_CLOSE_MIN = 30
_IST_ZONE = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> datetime:
    return datetime.now(tz=_IST_ZONE)


def _is_trading_day(now: datetime | None = None) -> bool:
    """True if now (IST) falls on a weekday (Mon–Fri)."""
    now = now or _ist_now()
    return now.weekday() < 5


def _is_market_open(now: datetime | None = None) -> bool:
    """True only during the live NSE equity session (Mon–Fri 09:15–15:30 IST)."""
    now = now or _ist_now()
    if not _is_trading_day(now):
        return False
    minutes = now.hour * 60 + now.minute
    open_min = _MARKET_OPEN_HOUR * 60 + _MARKET_OPEN_MIN
    close_min = _MARKET_CLOSE_HOUR * 60 + _MARKET_CLOSE_MIN
    return open_min <= minutes <= close_min


def _is_after_market_close(now: datetime | None = None) -> bool:
    """True once the session for the day has ended (or it's a non-trading day)."""
    now = now or _ist_now()
    if not _is_trading_day(now):
        return True
    minutes = now.hour * 60 + now.minute
    close_min = _MARKET_CLOSE_HOUR * 60 + _MARKET_CLOSE_MIN
    return minutes > close_min


def _snapshot_path() -> str:
    return _SNAPSHOT_FILE


def _load_snapshot() -> dict[str, Any]:
    try:
        with open(_snapshot_path(), "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _atomic_write(path: str, payload: dict[str, Any]) -> None:
    """Write JSON atomically, falling back to a direct overwrite."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)


def _save_snapshot(payload: dict[str, Any]) -> None:
    try:
        _atomic_write(_snapshot_path(), payload)
    except Exception as exc:
        log.warning("Failed to save snapshot: %s", exc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_ts() -> int:
    return int(time.time())


def _persist_picks(picks: list[dict[str, Any]], direction: str, scan_ltp: float | None = None) -> None:
    """Persist scan results to snapshot under scannerPicks."""
    snapshot = _load_snapshot()
    picks_map = snapshot.get("scannerPicks") or {}
    now = _utc_ts()
    
    for p in picks:
        sym = p.get("symbol") or p.get("ticker")
        if not sym:
            continue
        key = f"{sym.upper()}:{direction}"
        existing = picks_map.get(key)
        
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
    """Load picks from snapshot, archive + prune expired sessions, return flat list.

    Expired picks are archived to eod_archive/{date}.json BEFORE being removed
    from the live snapshot, so EOD reports can still be built from them.
    """
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
    if expired:
        try:
            from .eod_archive import archive_all_expiring
            archive_all_expiring(picks_map, expired, for_date=_ist_now().date())
        except Exception as exc:
            log.warning("Failed to archive expiring picks: %s", exc)
        for key in expired:
            del picks_map[key]
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


def _resolve_ltp(pick: dict[str, Any]) -> float:
    """Resolve the best available last traded price for a pick."""
    entry = float(pick.get("entryPrice") or 0)
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
    return float(ltp)


def compute_outcome(pick: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate target1 / target2 / stopLoss against current live price."""
    entry = float(pick.get("entryPrice") or 0)
    sl = float(pick.get("stopLoss") or 0)
    t1 = float(pick.get("target1") or 0)
    t2 = float(pick.get("target2") or 0)
    direction = str(pick.get("direction") or "LONG")
    if not entry or not sl or not t1 or not t2:
        return None

    ltp = _resolve_ltp(pick)
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


def _finalize_pending_outcome(pick: dict[str, Any], ltp: float) -> dict[str, Any]:
    """Mark a still-PENDING intraday pick as NOT TRIGGERED at market close."""
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
    if not _is_after_market_close() or not finalize_if_closed:
        return compute_outcome(pick)

    existing = pick.get("outcome")
    if existing and (existing.get("hitLevel") or existing.get("final")):
        return existing

    ltp = _resolve_ltp(pick)
    pick["currentPrice"] = ltp
    pick["priceUpdatedAt"] = _utc_now()
    pending = compute_outcome(pick)
    if pending and pending.get("hitLevel") is None:
        return _finalize_pending_outcome(pick, ltp)
    return pending


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


_FIXED_PLAN_FILE = os.environ.get(
    "FIXED_PLAN_FILE",
    os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "fixed_trade_plan.json",
        )
    ),
)


def load_fixed_trade_plan() -> dict[str, Any]:
    """Load the fixed/static trade plan from JSON."""
    try:
        with open(_FIXED_PLAN_FILE, "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            return payload
        return {}
    except Exception:
        return {}


def save_fixed_trade_plan(payload: dict[str, Any]) -> None:
    """Persist the fixed trade plan to JSON."""
    try:
        _atomic_write(_FIXED_PLAN_FILE, payload)
    except Exception as exc:
        log.warning("Failed to save fixed trade plan: %s", exc)


_ALERT_HISTORY_FILE = os.environ.get(
    "ALERT_HISTORY_FILE",
    os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "alert_history.json",
        )
    ),
)


def _load_alert_history() -> list[dict[str, Any]]:
    """Load fired alert history."""
    try:
        with open(_ALERT_HISTORY_FILE, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_alert_history(history: list[dict[str, Any]]) -> None:
    """Persist alert history (keep last 500)."""
    try:
        trimmed = (history or [])[-500:]
        tmp = _ALERT_HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(trimmed, fh, indent=2, default=str)
        os.replace(tmp, _ALERT_HISTORY_FILE)
    except Exception as exc:
        log.warning("Failed to save alert history: %s", exc)


def _record_alert(alert: dict[str, Any]) -> None:
    history = _load_alert_history()
    history.append(alert)
    _save_alert_history(history)


def get_live_prices_for_plan() -> dict[str, Any]:
    """Return live prices + evaluated outcomes for symbols in the fixed plan."""
    fixed = load_fixed_trade_plan()
    if not fixed:
        return {"long": [], "short": [], "updatedAt": _utc_now(), "source": "none"}
    
    long_plan = fixed.get("long") or []
    short_plan = fixed.get("short") or []
    if not long_plan and not short_plan:
        return {"long": [], "short": [], "updatedAt": _utc_now(), "source": "none"}
    
    all_plan_symbols = [p.get("symbol", "").upper() for p in long_plan + short_plan if p.get("symbol")]
    unique_symbols = list(dict.fromkeys(all_plan_symbols))
    
    snapshot = _get_market_snapshot() or {}
    quotes = snapshot.get("stockQuotes") or {}
    snapshot_updated = snapshot.get("updatedAt", "")

    market_open = _is_market_open()
    after_close = _is_after_market_close()
    plan_changed: list[bool] = []

    alert_history = _load_alert_history()
    new_alerts: list[dict[str, Any]] = []

    def enrich_pick(p: dict[str, Any]) -> dict[str, Any]:
        symbol = (p.get("symbol") or "").upper()
        ltp = None

        if symbol in quotes:
            q = quotes[symbol]
            raw = q.get("ltpRaw") or q.get("ltp") or q.get("lastPrice")
            if raw is not None:
                try:
                    ltp = float(raw)
                except (TypeError, ValueError):
                    pass

        if ltp is None:
            raw = p.get("scanLtp")
            if raw is not None:
                try:
                    ltp = float(raw)
                except (TypeError, ValueError):
                    pass

        if ltp is None:
            ltp = p.get("currentPrice")

        if ltp is None:
            ltp = float(p.get("entryPrice") or 0)
        ltp = float(ltp)

        outcome = evaluate_outcome({**p, "currentPrice": ltp, "scanLtp": None}, finalize_if_closed=after_close)

        entry = {
            "ltp": ltp,
            "ltpSource": "snapshot" if (symbol in quotes and quotes[symbol].get("ltpRaw")) else "cached",
        }

        if outcome:
            hit_level = (outcome.get("hitLevel") if isinstance(outcome, dict) else None)
            if hit_level:
                alert_key = f"{symbol}:{p.get('direction','')}:{hit_level}"
                already_fired = any(
                    (a.get("key") == alert_key and a.get("planDate") == _today_ist())
                    for a in alert_history
                )
                if not already_fired:
                    new_alerts.append({
                        "key": alert_key,
                        "symbol": symbol,
                        "direction": p.get("direction", "LONG"),
                        "hitLevel": hit_level,
                        "label": outcome.get("label", ""),
                        "ltp": ltp,
                        "planDate": _today_ist(),
                        "firedAt": _utc_now(),
                    })
            entry["outcome"] = outcome
            entry["priceUpdatedAt"] = _utc_now()
            if hit_level or outcome.get("final"):
                p["outcome"] = outcome
                plan_changed.append(True)
        else:
            entry["outcome"] = None
            entry["priceUpdatedAt"] = _utc_now()

        merged = {**p, **entry}
        return merged

    enriched_long = [enrich_pick(p) for p in long_plan]
    enriched_short = [enrich_pick(p) for p in short_plan]

    if plan_changed:
        save_fixed_trade_plan({"long": long_plan, "short": short_plan, "updatedAt": _utc_now()})

    if new_alerts:
        _record_alert(new_alerts[0])
        for a in new_alerts[1:]:
            _record_alert(a)

    return {
        "long": enriched_long,
        "short": enriched_short,
        "updatedAt": _utc_now(),
        "snapshotUpdatedAt": snapshot_updated,
        "source": "fixed_plan",
        "newAlerts": new_alerts,
        "marketOpen": market_open,
        "sessionClosed": after_close,
    }


def get_alert_history(since: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Return fired alert history, optionally filtered by date."""
    history = _load_alert_history()
    today = _today_ist()
    if since:
        history = [a for a in history if a.get("planDate", "") >= since]
    else:
        history = [a for a in history if a.get("planDate") == today]
    history = history[-limit:]
    return {"alerts": history, "total": len(history), "today": today}


def _today_ist() -> str:
    """Return today's date in IST (YYYY-MM-DD)."""
    from datetime import datetime, timezone, timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")


def get_trade_outcomes() -> dict[str, Any]:
    """Return all picks with their latest outcomes for the API/frontend."""
    refresh_outcomes()

    fixed = load_fixed_trade_plan()
    if fixed and (fixed.get("long") or fixed.get("short")):
        after_close = _is_after_market_close()
        plan_changed = False
        for picks in (fixed.get("long") or [], fixed.get("short") or []):
            for p in picks:
                oc = p.get("outcome")
                if oc and (oc.get("hitLevel") or oc.get("final")):
                    continue
                outcome = evaluate_outcome(p, finalize_if_closed=after_close)
                if outcome:
                    p["outcome"] = outcome
                    plan_changed = True
        if plan_changed:
            save_fixed_trade_plan(fixed)
        fixed["updatedAt"] = _utc_now()
        fixed["marketOpen"] = _is_market_open()
        fixed["sessionClosed"] = after_close
        return fixed
    
    picks = _load_persisted_picks()
    long_rows: list[dict[str, Any]] = []
    short_rows: list[dict[str, Any]] = []
    for p in picks:
        if p.get("direction") == "SHORT":
            short_rows.append(p)
        else:
            long_rows.append(p)
    rank = {"t2": 0, "t1": 1, "sl": 2, None: 3}
    long_rows.sort(key=lambda r: rank.get((r.get("outcome") or {}).get("hitLevel"), 3))
    short_rows.sort(key=lambda r: rank.get((r.get("outcome") or {}).get("hitLevel"), 3))
    return {
        "long": long_rows,
        "short": short_rows,
        "updatedAt": _utc_now(),
    }