"""Timestamped entry evidence shared by the live Intraday desk and EOD Book."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ENTRY_CUTOFF = time(14, 45)
CASH_CLOSE = time(15, 30)


def _dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=IST)
        return parsed.astimezone(IST)
    except (TypeError, ValueError):
        return None


def candle_entry_evidence(
    pick: dict[str, Any],
    candles: list[dict[str, Any]],
    *,
    session_date: date,
    committed_at: str | datetime | None,
    cutoff: time = ENTRY_CUTOFF,
) -> dict[str, Any]:
    """Find the first tradable entry crossing after lock and before cutoff.

    A daily high/low or a price already beyond entry at lock is not a modeled
    fill.  The entry level must lie inside a timestamped candle range.
    """
    try:
        entry = float(pick.get("entryPrice") or 0)
    except (TypeError, ValueError):
        entry = 0.0
    direction = str(pick.get("direction") or "LONG").upper()
    commit_dt = committed_at if isinstance(committed_at, datetime) else _dt(committed_at)
    cutoff_dt = datetime.combine(session_date, cutoff, tzinfo=IST)
    if entry <= 0 or commit_dt is None:
        return {"triggered": False, "reason": "MISSING_ENTRY_EVIDENCE"}

    trigger_index: int | None = None
    trigger_dt: datetime | None = None
    trigger_high: float | None = None
    trigger_low: float | None = None
    for index, candle in enumerate(candles):
        ts = _dt(candle.get("ts") or candle.get("timestamp") or candle.get("time"))
        if ts is None or ts < commit_dt or ts > cutoff_dt:
            continue
        try:
            high = float(candle.get("high"))
            low = float(candle.get("low"))
        except (TypeError, ValueError):
            continue
        if low <= entry <= high:
            trigger_index = index
            trigger_dt = ts
            trigger_high = high
            trigger_low = low
            break

    if trigger_index is not None and trigger_dt is not None:
        close_dt = datetime.combine(session_date, CASH_CLOSE, tzinfo=IST)
        post_entry_highs: list[float] = []
        post_entry_lows: list[float] = []
        for candle in candles[trigger_index:]:
            ts = _dt(candle.get("ts") or candle.get("timestamp") or candle.get("time"))
            if ts is None or ts < trigger_dt or ts > close_dt:
                continue
            try:
                post_entry_highs.append(float(candle.get("high")))
                post_entry_lows.append(float(candle.get("low")))
            except (TypeError, ValueError):
                continue
        return {
            "triggered": True,
            "triggeredAt": trigger_dt.isoformat(),
            "triggerPrice": entry,
            "triggerSource": "one_minute_candle",
            "triggerCandle": {"high": trigger_high, "low": trigger_low},
            # These extrema start at the actual entry candle, so they are valid
            # MFE/MAE evidence.  Whole-session OHLC is not.
            "postEntryHigh": max(post_entry_highs) if post_entry_highs else trigger_high,
            "postEntryLow": min(post_entry_lows) if post_entry_lows else trigger_low,
        }

    return {
        "triggered": False,
        "reason": "ENTRY_NOT_CROSSED_POST_LOCK",
        "cutoffAt": cutoff_dt.isoformat(),
        "direction": direction,
    }


def _bar_ohlc(candle: Any) -> tuple[Any, float, float, float] | None:
    if isinstance(candle, dict):
        ts = candle.get("ts") or candle.get("timestamp") or candle.get("time")
        try:
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close") if candle.get("close") is not None else candle.get("high"))
        except (TypeError, ValueError):
            return None
    elif isinstance(candle, (list, tuple)) and len(candle) >= 5:
        ts, _open, high, low, close = candle[0], candle[1], candle[2], candle[3], candle[4]
        try:
            high, low, close = float(high), float(low), float(close)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if high <= 0 or low <= 0 or close <= 0:
        return None
    return ts, high, low, close


def post_entry_ohlc_bars(
    candles: list[Any],
    *,
    entry_at: str | datetime | None,
    session_date: date | None = None,
) -> list[tuple[float, float, float]]:
    """1-minute (high, low, close) from the fill bar through cash close."""
    start = _dt(entry_at)
    close_dt = datetime.combine(session_date, CASH_CLOSE, tzinfo=IST) if session_date else None
    bars: list[tuple[float, float, float]] = []
    for candle in candles or []:
        parsed = _bar_ohlc(candle)
        if parsed is None:
            continue
        ts, high, low, close = parsed
        ts_dt = _dt(ts)
        if start is not None and ts_dt is not None and ts_dt < start:
            continue
        if close_dt is not None and ts_dt is not None and ts_dt > close_dt:
            continue
        bars.append((high, low, close))
    return bars


def post_entry_ohlc_events(
    candles: list[Any],
    *,
    entry_at: str | datetime | None,
    session_date: date | None = None,
) -> list[dict[str, Any]]:
    """Timestamped one-minute evidence from the actual fill onward."""
    start = _dt(entry_at)
    close_dt = datetime.combine(session_date, CASH_CLOSE, tzinfo=IST) if session_date else None
    events: list[dict[str, Any]] = []
    for candle in candles or []:
        parsed = _bar_ohlc(candle)
        if parsed is None:
            continue
        ts, high, low, close = parsed
        ts_dt = _dt(ts)
        if start is not None and ts_dt is not None and ts_dt < start:
            continue
        if close_dt is not None and ts_dt is not None and ts_dt > close_dt:
            continue
        events.append({
            "at": ts_dt.isoformat() if ts_dt is not None else str(ts or ""),
            "high": high, "low": low, "close": close,
        })
    return events


_SESSION_FILL_STATUSES = frozenset({"TRIGGERED", "EXECUTED", "FILLED"})


def session_lock_fill_evidence(pick: dict[str, Any]) -> dict[str, Any] | None:
    """Honor a live locked-session fill so EOD Book matches the Intraday desk.

    Candle reconstruction can miss a fill when lock LTP already sat on the
    entry and later bars never trade back through that print. The persisted
    session stamp is the execution source of truth for that name.
    """
    status = str(pick.get("executionStatus") or "").upper()
    if pick.get("triggered") is not True and status not in _SESSION_FILL_STATUSES:
        return None
    entry = pick.get("entryPrice") or pick.get("lockObservedPrice")
    return {
        "triggered": True,
        "triggeredAt": pick.get("triggeredAt"),
        "triggerPrice": entry,
        "triggerSource": "session_lock_fill",
        "lockObservedPrice": pick.get("lockObservedPrice"),
    }


def persisted_entry_evidence(
    pick: dict[str, Any],
    *,
    session_date: date,
    committed_at: str | datetime | None,
) -> dict[str, Any]:
    from .eod_engine.ingestion import load_persisted_candles

    symbol = str(pick.get("symbol") or "").upper()
    payload = load_persisted_candles(session_date, symbol)
    candles = payload.get("candles") if isinstance(payload, dict) else []
    return candle_entry_evidence(
        pick,
        candles if isinstance(candles, list) else [],
        session_date=session_date,
        committed_at=committed_at,
    )


def mark_not_triggered(row: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Zero all execution economics while retaining planned size for audit."""
    out = dict(row)
    planned = float(out.get("plannedCapital") or out.get("deployedCapital") or 0)
    out.update({
        "triggered": False,
        "executionStatus": "NOT_TRIGGERED",
        "status": "NOT_TRIGGERED",
        "skipped": True,
        "skipReason": evidence.get("reason") or "ENTRY_NOT_CROSSED_POST_LOCK",
        "entryEvidence": evidence,
        "plannedCapital": planned,
        "deployedCapital": 0.0,
        "positionValue": 0.0,
        "remainingQty": 0,
        "realizedPnl": 0.0,
        "unrealizedPnl": 0.0,
        "totalPnl": 0.0,
        "pnl": 0.0,
        "pnlPct": 0.0,
        "closed": True,
        "slotFreed": False,
        "slotStatus": "NOT_TRIGGERED",
        "outcome": None,
        "exitState": None,
    })
    return out
