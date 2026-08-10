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

from .exit_plan import attach_exit_plan, evaluate_scale_trail

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

_YAHOO_FINANCE_CACHE: dict[str, tuple[float, float]] = {}
_YAHOO_FINANCE_CACHE_TTL = 30  # seconds

# NSE equity cash trading session (IST)
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MIN = 15
_MARKET_CLOSE_HOUR = 15
_MARKET_CLOSE_MIN = 30
_IST_ZONE = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> datetime:
    return datetime.now(tz=_IST_ZONE)


def _fetch_yahoo_finance_price(symbol: str) -> float | None:
    """LTP / last print from Yahoo Finance (works session + post-close)."""
    now = time.time()
    cached = _YAHOO_FINANCE_CACHE.get(symbol)
    if cached and (now - cached[1]) < _YAHOO_FINANCE_CACHE_TTL:
        return cached[0]
    try:
        import urllib.request
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.NS"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        meta = data.get("chart", {}).get("result", [{}])[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None:
            price = meta.get("postMarketPrice") or meta.get("previousClose")
        if price is not None:
            price = float(price)
            _YAHOO_FINANCE_CACHE[symbol] = (price, now)
            return price
    except Exception:
        pass
    return None


def _fetch_angel_plan_prices(symbols: list[str]) -> dict[str, float]:
    """Angel One ltpData for fixed-plan symbols (last traded print after close too)."""
    out: dict[str, float] = {}
    if not symbols:
        return out
    try:
        from . import angel_one_feed as aof
    except Exception:
        return out
    client = None
    try:
        client = aof._get_fixed_plan_client()
    except Exception:
        return out
    if client is None:
        return out
    for sym in symbols:
        try:
            quote = client.fetch_symbol_quote(sym)
            if not quote:
                continue
            ltp = float(quote.get("ltp", 0) or 0)
            if ltp > 0:
                out[sym.upper()] = ltp
        except Exception:
            continue
    return out


def fetch_live_marks_for_symbols(symbols: list[str]) -> dict[str, float]:
    """Angel (when session open) + Yahoo fill for arbitrary symbols on trading days.

    Used by plan live-prices and swing-session live MTM so Book/EOD can refresh
    marks without rewriting book_*.json caches.
    """
    unique = list(dict.fromkeys(str(s or "").upper().strip() for s in symbols if s))
    unique = [s for s in unique if s]
    if not unique or not _is_trading_day():
        return {}

    market_open = _is_market_open()
    after_close = _is_after_market_close()
    if not _should_refresh_plan_ltps(market_open, after_close):
        return {}

    out: dict[str, float] = {}
    if market_open:
        out.update(_fetch_angel_plan_prices(unique))

    now = time.time()
    for sym in unique:
        if sym in out:
            continue
        cached = _YAHOO_FINANCE_CACHE.get(sym)
        if cached and (now - cached[1]) < _YAHOO_FINANCE_CACHE_TTL:
            out[sym] = cached[0]
            continue
        price = _fetch_yahoo_finance_price(sym)
        if price is not None:
            out[sym] = price
    return out


def _should_refresh_plan_ltps(market_open: bool, after_close: bool) -> bool:
    """Refresh every plan ticker on trading days — session open and post-close."""
    if not _is_trading_day():
        return False
    return bool(market_open or after_close)


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
    """True once today's NSE session has ended (after 15:30 IST), or non-trading day.

    Pre-open (before 09:15) is *not* after-close — use ``not _is_market_open()`` for
    overnight SESSION CLOSED display so we do not spam Yahoo refresh all night.
    """
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


def load_persisted_long_scanner_picks() -> list[dict[str, Any]]:
    """Public accessor: non-expired LONG scanner picks from trade_api_snapshot.json."""
    return [
        p for p in _load_persisted_picks()
        if str(p.get("direction") or "LONG").upper() == "LONG" and p.get("symbol")
    ]


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
    """Evaluate exits against LTP — scale-trail when exitPlan present, else binary T1/T2/SL."""
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
        log.warning("fixed trade plan is not a JSON object: %s", _FIXED_PLAN_FILE)
        return {}
    except Exception as exc:
        log.error("Failed to load fixed trade plan (%s): %s", _FIXED_PLAN_FILE, exc)
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


def _alert_already_fired(history: list[dict[str, Any]], key: str, plan_date: str) -> bool:
    return any(a.get("key") == key and a.get("planDate") == plan_date for a in history)


def emit_book_lock_alerts(
    *,
    book: str,
    session_date: str,
    long_rows: list[dict[str, Any]] | None = None,
    short_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Persist BUY/SELL pick alerts when a swing or intraday book locks."""
    history = _load_alert_history()
    today = (session_date or _today_ist())[:10]
    new_alerts: list[dict[str, Any]] = []

    def _px(row: dict[str, Any]) -> float | None:
        for k in ("entryPrice", "buyAbove", "ltp", "scanLtp", "currentPrice"):
            raw = row.get(k)
            if raw is None:
                continue
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
        return None

    def _one(row: dict[str, Any], direction: str) -> None:
        if not isinstance(row, dict):
            return
        sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
        if not sym:
            return
        hit = "buy" if direction == "LONG" else "sell"
        action = "BUY" if direction == "LONG" else "SELL"
        key = f"{sym}:{direction}:lock:{book}:{today}"
        if _alert_already_fired(history, key, today):
            return
        px = _px(row)
        alert = {
            "key": key,
            "symbol": sym,
            "direction": direction,
            "hitLevel": hit,
            "label": f"{book} PICK · {action}",
            "ltp": float(px or 0.0),
            "entryPrice": px,
            "planDate": today,
            "firedAt": _utc_now(),
            "book": book,
            "action": action,
        }
        new_alerts.append(alert)
        history.append(alert)

    for r in long_rows or []:
        _one(r, "LONG")
    for r in short_rows or []:
        _one(r, "SHORT")
    for a in new_alerts:
        _record_alert(a)
    return new_alerts


def emit_replacement_alerts(
    *,
    session_date: str,
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Persist BUY/SELL alerts when an intraday free-slot replacement is applied."""
    history = _load_alert_history()
    today = (session_date or _today_ist())[:10]
    new_alerts: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        direction = str(row.get("direction") or "LONG").upper()
        hit = "buy" if direction == "LONG" else "sell"
        action = "BUY" if direction == "LONG" else "SELL"
        key = f"{sym}:{direction}:replace:INTRADAY:{today}"
        if _alert_already_fired(history, key, today):
            continue
        try:
            px = float(row.get("entryPrice") or row.get("ltp") or 0)
        except (TypeError, ValueError):
            px = 0.0
        alert = {
            "key": key,
            "symbol": sym,
            "direction": direction,
            "hitLevel": hit,
            "label": f"INTRADAY REPLACE · {action}",
            "ltp": px,
            "entryPrice": px or None,
            "planDate": today,
            "firedAt": _utc_now(),
            "book": "INTRADAY",
            "action": action,
            "replacedFrom": row.get("replacedFrom"),
        }
        new_alerts.append(alert)
        history.append(alert)
    for a in new_alerts:
        _record_alert(a)
    return new_alerts


def collect_hit_alerts_from_rows(
    rows: list[dict[str, Any]],
    *,
    book: str = "INTRADAY",
) -> list[dict[str, Any]]:
    """Fire T1/T2/SL/partial alerts for enriched book rows (deduped by day)."""
    history = _load_alert_history()
    today = _today_ist()
    new_alerts: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
        hit_level = outcome.get("hitLevel")
        if not hit_level:
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            continue
        direction = str(row.get("direction") or "LONG").upper()
        if direction not in ("LONG", "SHORT"):
            direction = "LONG"
        key = f"{sym}:{direction}:{hit_level}:{book}"
        if _alert_already_fired(history, key, today):
            continue
        try:
            ltp = float(outcome.get("ltp") if outcome.get("ltp") is not None else row.get("ltp") or 0)
        except (TypeError, ValueError):
            ltp = 0.0
        entry = row.get("entryPrice")
        try:
            entry_f = float(entry) if entry is not None else None
        except (TypeError, ValueError):
            entry_f = None
        hl = str(hit_level).lower()
        if hl == "buy":
            action = "BUY"
        elif hl == "sell":
            action = "SELL"
        else:
            # Targets / SL / partial book — reverse the sleeve side
            action = "SELL" if direction == "LONG" else "BUY"
        alert = {
            "key": key,
            "symbol": sym,
            "direction": direction,
            "hitLevel": hit_level,
            "label": outcome.get("label") or f"{book} · {str(hit_level).upper()}",
            "ltp": ltp,
            "entryPrice": entry_f,
            "planDate": today,
            "firedAt": _utc_now(),
            "book": book,
            "action": action,
        }
        new_alerts.append(alert)
        history.append(alert)
    for a in new_alerts:
        _record_alert(a)
    return new_alerts


def get_live_prices_for_plan() -> dict[str, Any]:
    """Return prices + evaluated outcomes for symbols in the fixed plan.

    Honesty contract:
    - Prefer Angel One ltpData / snapshot; Yahoo fills gaps on trading days
      (session open and after 15:30 close marks) for every plan ticker.
    - Never claim tick-live or "no external APIs" — sources are reported per symbol.
    - Cached/entry fallbacks set dataStale=True. Missing price → ltp null, not invented.
    """
    snapshot_prefetch = _get_market_snapshot() or {}
    snapshot_updated_prefetch = snapshot_prefetch.get("updatedAt", "")

    fixed = load_fixed_trade_plan()
    plan_note = None
    if not fixed or (not (fixed.get("long") or []) and not (fixed.get("short") or [])):
        # Corrupt/missing plan must not kill the desk — fall back to locked session basket.
        try:
            from .intraday_session_engine import load_session

            sess = load_session() or {}
            long_fb = list(sess.get("long") or [])
            short_fb = list(sess.get("short") or [])
            if long_fb or short_fb:
                fixed = {
                    "long": long_fb,
                    "short": short_fb,
                    "updatedAt": sess.get("updatedAt") or _utc_now(),
                    "source": "intraday_session_fallback",
                }
                plan_note = "Fixed plan missing/corrupt; pricing locked session basket"
                log.error("%s (%s)", plan_note, _FIXED_PLAN_FILE)
        except Exception as exc:
            log.error("Session fallback after empty fixed plan failed: %s", exc)

    if not fixed:
        return {
            "long": [],
            "short": [],
            "updatedAt": _utc_now(),
            "snapshotUpdatedAt": snapshot_updated_prefetch,
            "source": "none",
            "priceSourcesNote": "No fixed plan; Yahoo not attempted",
            "marketOpen": _is_market_open(),
            "sessionClosed": not _is_market_open(),
            "dataStale": True,
            "ltpSourceMix": {"live": 0, "snapshot": 0, "cached": 0, "none": 0},
        }

    long_plan = fixed.get("long") or []
    short_plan = fixed.get("short") or []
    if not long_plan and not short_plan:
        return {
            "long": [],
            "short": [],
            "updatedAt": _utc_now(),
            "snapshotUpdatedAt": snapshot_updated_prefetch,
            "source": "none",
            "priceSourcesNote": "Empty fixed plan; Yahoo not attempted",
            "marketOpen": _is_market_open(),
            "sessionClosed": not _is_market_open(),
            "dataStale": True,
            "ltpSourceMix": {"live": 0, "snapshot": 0, "cached": 0, "none": 0},
        }

    all_plan_symbols = [p.get("symbol", "").upper() for p in long_plan + short_plan if p.get("symbol")]
    unique_symbols = list(dict.fromkeys(all_plan_symbols))

    snapshot = snapshot_prefetch
    quotes = snapshot.get("stockQuotes") or {}
    snapshot_updated = snapshot_updated_prefetch

    snapshot_age_sec: int | None = None
    if snapshot_updated:
        try:
            snap_dt = datetime.fromisoformat(str(snapshot_updated).replace("Z", "+00:00"))
            snapshot_age_sec = max(
                0,
                int((datetime.now(tz=timezone.utc) - snap_dt.astimezone(timezone.utc)).total_seconds()),
            )
        except Exception:
            snapshot_age_sec = None

    market_open = _is_market_open()
    after_close = _is_after_market_close()
    plan_changed: list[bool] = []

    alert_history = _load_alert_history()
    new_alerts: list[dict[str, Any]] = []
    source_mix = {"live": 0, "snapshot": 0, "cached": 0, "none": 0}

    # Trading-day refresh for every plan ticker (session + post-close close marks).
    # Session: Angel first, Yahoo fills gaps. Post-close: Yahoo only (fast close marks;
    # Angel searchScrip can hang DNS and block the desk).
    live_quotes: dict[str, float] = {}
    live_attempted = False
    if _should_refresh_plan_ltps(market_open, after_close) and unique_symbols:
        live_attempted = True
        if market_open:
            angel_quotes = _fetch_angel_plan_prices(unique_symbols)
            live_quotes.update(angel_quotes)
        now = time.time()
        for sym in unique_symbols:
            if sym in live_quotes:
                continue
            cached = _YAHOO_FINANCE_CACHE.get(sym)
            if cached and (now - cached[1]) < _YAHOO_FINANCE_CACHE_TTL:
                live_quotes[sym] = cached[0]
                continue
            price = _fetch_yahoo_finance_price(sym)
            if price is not None:
                live_quotes[sym] = price

    def enrich_pick(p: dict[str, Any]) -> dict[str, Any]:
        symbol = (p.get("symbol") or "").upper()
        ltp = None
        ltp_source = "none"
        from_snapshot = False

        if symbol in quotes:
            q = quotes[symbol]
            raw = q.get("ltpRaw") or q.get("ltp") or q.get("lastPrice")
            if raw is not None:
                try:
                    ltp = float(raw)
                    from_snapshot = True
                    ltp_source = "snapshot"
                except (TypeError, ValueError):
                    pass

        # Prefer fresh Angel/Yahoo last print over stale snapshot (incl. after close)
        if symbol in live_quotes:
            ltp = live_quotes[symbol]
            ltp_source = "live"
            from_snapshot = False

        if ltp is None:
            for key in ("scanLtp", "currentPrice", "entryPrice"):
                raw = p.get(key)
                if raw is not None:
                    try:
                        ltp = float(raw)
                        ltp_source = "cached"
                        break
                    except (TypeError, ValueError):
                        pass

        data_stale = ltp_source in ("cached", "none") or (
            ltp_source == "snapshot"
            and snapshot_age_sec is not None
            and snapshot_age_sec > max(_PRICE_TTL, 300)
        )
        source_mix[ltp_source] = source_mix.get(ltp_source, 0) + 1

        entry: dict[str, Any] = {
            "ltp": round(ltp, 2) if ltp is not None else None,
            "currentPrice": round(ltp, 2) if ltp is not None else None,
            "ltpSource": ltp_source,
            "dataStale": data_stale,
            "priceUpdatedAt": _utc_now(),
        }

        if ltp is None:
            entry["outcome"] = None
            entry["status"] = "DATA STALE"
            return {**p, **entry}

        # CLOSED positions stay CLOSED — do not re-open via price refresh
        if p.get("closed") or str(p.get("status") or "").upper() == "CLOSED":
            entry["status"] = "CLOSED"
            entry["closed"] = True
            entry["outcome"] = p.get("outcome")
            return {**p, **entry}

        outcome = evaluate_outcome({**p, "currentPrice": ltp, "scanLtp": None}, finalize_if_closed=after_close)

        if outcome:
            hit_level = (outcome.get("hitLevel") if isinstance(outcome, dict) else None)
            if hit_level:
                alert_key = f"{symbol}:{p.get('direction','')}:{hit_level}"
                already_fired = any(
                    (a.get("key") == alert_key and a.get("planDate") == _today_ist())
                    for a in alert_history
                )
                if not already_fired:
                    direction = str(p.get("direction") or "LONG").upper()
                    # LONG exits / targets / SL / partial = SELL; SHORT covers = BUY
                    action = "SELL" if direction == "LONG" else "BUY"
                    entry_raw = p.get("entryPrice")
                    try:
                        entry_f = float(entry_raw) if entry_raw is not None else None
                    except (TypeError, ValueError):
                        entry_f = None
                    new_alerts.append({
                        "key": alert_key,
                        "symbol": symbol,
                        "direction": direction,
                        "hitLevel": hit_level,
                        "label": outcome.get("label", ""),
                        "ltp": ltp,
                        "entryPrice": entry_f,
                        "planDate": _today_ist(),
                        "firedAt": _utc_now(),
                        "book": "INTRADAY",
                        "action": action,
                    })
            entry["outcome"] = outcome
            if hit_level or outcome.get("final") or outcome.get("closed"):
                p["outcome"] = outcome
                if isinstance(outcome.get("exitState"), dict):
                    p["exitState"] = outcome["exitState"]
                plan_changed.append(True)
                if outcome.get("closed") or hit_level == "sl":
                    entry["closed"] = True
                    if hit_level == "sl" and outcome.get("scaleTrail"):
                        entry["status"] = "TRAIL STOP HIT"
                    elif hit_level == "sl":
                        entry["status"] = "STOP LOSS HIT"
                    else:
                        entry["status"] = "CLOSED"
                elif hit_level == "partial":
                    entry["status"] = str(outcome.get("label") or "PARTIAL")
                    entry["closed"] = False
                elif hit_level in ("t1", "t2"):
                    entry["status"] = (
                        "TARGET 2 HIT" if hit_level == "t2" else "TARGET 1 HIT"
                    )
                elif after_close or outcome.get("final"):
                    entry["status"] = "SESSION CLOSED"
            if outcome.get("realizedPnl") is not None:
                entry["realizedPnl"] = outcome.get("realizedPnl")
            if outcome.get("unrealizedPnl") is not None:
                entry["unrealizedPnl"] = outcome.get("unrealizedPnl")
            if outcome.get("remainingQty") is not None:
                entry["remainingQty"] = outcome.get("remainingQty")
            if outcome.get("effectiveStop") is not None:
                entry["effectiveStop"] = outcome.get("effectiveStop")
            if isinstance(outcome.get("exitState"), dict):
                entry["exitState"] = outcome["exitState"]
        else:
            entry["outcome"] = None

        if data_stale and not entry.get("closed") and market_open:
            entry["status"] = "DATA STALE"
        elif not market_open and not entry.get("closed") and not entry.get("status"):
            entry["status"] = "SESSION CLOSED"
        elif from_snapshot and not market_open and not entry.get("status"):
            entry["status"] = "SESSION CLOSED"
        elif not market_open and not entry.get("closed") and entry.get("status") in (
            None,
            "",
            "RUNNING",
            "DATA STALE",
            "SL APPROACHING",
            "TARGET APPROACHING",
        ):
            entry["status"] = "SESSION CLOSED"

        return {**p, **entry}

    enriched_long = [enrich_pick(p) for p in long_plan]
    enriched_short = [enrich_pick(p) for p in short_plan]

    if plan_changed:
        # Preserve lock metadata when rewriting plan after outcomes
        merged_plan = {
            **{k: v for k, v in fixed.items() if k not in ("long", "short")},
            "long": long_plan,
            "short": short_plan,
            "updatedAt": _utc_now(),
        }
        save_fixed_trade_plan(merged_plan)

    if new_alerts:
        _record_alert(new_alerts[0])
        for a in new_alerts[1:]:
            _record_alert(a)

    any_stale = any(r.get("dataStale") for r in enriched_long + enriched_short) or (
        snapshot_age_sec is not None and snapshot_age_sec > max(_PRICE_TTL, 300)
    )

    return {
        "long": enriched_long,
        "short": enriched_short,
        "updatedAt": _utc_now(),
        "snapshotUpdatedAt": snapshot_updated,
        "snapshotAgeSec": snapshot_age_sec,
        "source": "fixed_plan" if not plan_note else "session_fallback",
        "priceSourcesNote": (
            plan_note
            or (
                (
                    "Angel One ltpData + Yahoo last print for every plan ticker"
                    if market_open
                    else "Yahoo close marks for every plan ticker (post-close)"
                )
                if live_attempted
                else "Angel One snapshot / plan cache only (weekend or no plan symbols)"
            )
        ),
        "newAlerts": new_alerts,
        "marketOpen": market_open,
        "sessionClosed": after_close if market_open else True,
        "dataStale": bool(any_stale),
        "ltpSourceMix": source_mix,
        "locked": bool(fixed.get("locked")),
        "executionPolicy": fixed.get("executionPolicy") or "MANUAL_ONLY",
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
        fixed["sessionClosed"] = not fixed["marketOpen"]
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