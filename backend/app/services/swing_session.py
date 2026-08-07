"""Durable swing portfolio lock for EOD / Book P&L.

Lock source = Asset Matrix BUY set (ledger_stocks → ranked stocks[]), never
dhanSwingPicks / ScanX. Intraday long/short stay in intradAy_session.json.
Once locked for the IST day: symbols immutable; prices update only.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .feed_scanner import SWING_MIN_PRICE, is_swing_desk_eligible
from .exit_plan import attach_exit_plan, evaluate_scale_trail
from .trade_outcome import _is_market_open
from .desk_clock import basket_lock_allowed, basket_lock_block_message
from .desk_book_symbols import filter_rows_excluding, intraday_locked_symbols

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

SWING_CAPITAL = float(os.environ.get("SWING_CAPITAL", "1000000"))  # ₹10L sleeve
SWING_RISK_FRACTION = float(os.environ.get("SWING_RISK_FRACTION", "0.01"))
# Cap matches Matrix BUY display (≤10–12)
SWING_MATRIX_LOCK_COUNT = min(12, max(1, int(os.environ.get("SWING_MATRIX_LOCK_COUNT", "12"))))
# Desk ATR% band when stock has no atr_pct / explicit levels (documented on row)
SWING_DEFAULT_ATR_PCT = float(os.environ.get("SWING_DEFAULT_ATR_PCT", "2.0"))
SWING_T1_R = float(os.environ.get("SWING_T1_R", "1.5"))
SWING_T2_R = float(os.environ.get("SWING_T2_R", "3.0"))


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


def _size_swing_row(
    row: dict[str, Any],
    *,
    sleeve: float,
    slots: int,
    force: bool = False,
) -> dict[str, Any]:
    """Risk + notional size for one swing name (same idea as intradAy desk)."""
    entry = _f(row.get("entryPrice")) or 0.0
    risk = _f(row.get("riskPerShare"))
    if risk is None or risk <= 0:
        stop = _f(row.get("stopLoss"))
        risk = abs(entry - stop) if stop is not None else entry * 0.02
    if entry <= 0 or risk <= 0 or sleeve <= 0:
        return {**row, "approxQty": 0, "deployedCapital": 0.0}

    existing_qty = int(row.get("approxQty") or 0)
    existing_dep = _f(row.get("deployedCapital")) or 0.0
    slots = max(1, slots)
    target_notional = sleeve / slots
    # Keep prior size only if already sized for this sleeve (±15%)
    if (
        not force
        and existing_qty > 0
        and existing_dep > 0
        and abs(existing_dep - target_notional) / max(target_notional, 1.0) <= 0.15
    ):
        return row

    risk_budget = sleeve * SWING_RISK_FRACTION
    qty_by_risk = int(risk_budget // risk)
    qty_by_notional = int(target_notional // entry)
    qty = max(0, min(qty_by_risk, qty_by_notional))
    if qty <= 0 and entry <= target_notional:
        qty = 1
    deployed = round(qty * entry, 2)
    return {
        **row,
        "approxQty": qty,
        "deployedCapital": deployed,
        "maxLoss": round(qty * risk, 2),
        "sizingNote": "SWING_SLEEVE_10L",
        "sleeveCapital": sleeve,
        "slotNotional": round(target_notional, 2),
    }


def apply_swing_sizing(
    session: dict[str, Any] | None = None,
    *,
    persist: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Fill approxQty/deployedCapital for ₹10L swing sleeve (fixes Book ₹0 / re-size)."""
    sess = dict(session or load_swing_session())
    long_rows = [r for r in (sess.get("long") or []) if isinstance(r, dict)]
    short_rows = [r for r in (sess.get("short") or []) if isinstance(r, dict)]
    if not long_rows and not short_rows:
        return sess

    prev_cap = _f((sess.get("capital") or {}).get("swingCapital"))
    must_force = force or (prev_cap is not None and abs(prev_cap - SWING_CAPITAL) > 1.0)

    slots = max(1, len(long_rows) + len(short_rows))
    sized_long = [
        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=slots, force=must_force))
        for r in long_rows
    ]
    sized_short = [
        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=slots, force=must_force))
        for r in short_rows
    ]
    changed = sized_long != long_rows or sized_short != short_rows or must_force
    sess["long"] = sized_long
    sess["short"] = sized_short
    sess["capital"] = {
        "swingCapital": SWING_CAPITAL,
        "riskFraction": SWING_RISK_FRACTION,
        "slots": slots,
        "perSlotNotional": round(SWING_CAPITAL / slots, 2),
    }
    if changed:
        sess["updatedAt"] = _utc_now_iso()
        if persist and sess.get("locked"):
            _atomic_write(_SWING_SESSION_PATH, sess)
            log.info(
                "Swing sizing applied: %d names · capital=%.0f · force=%s",
                slots,
                SWING_CAPITAL,
                must_force,
            )
    return sess


def _parse_price(v: Any) -> float | None:
    """Parse float LTP — accepts raw number or ₹1,234.50 strings."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            f = float(v)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None
    text = str(v).strip()
    if not text:
        return None
    cleaned = re.sub(r"[₹,\s]", "", text)
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    try:
        f = float(cleaned)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _matrix_row_levels(row: dict[str, Any], entry: float) -> tuple[float, float, float, float, str]:
    """Build SL/T1/T2 from Matrix facts; document levelsSource on the pick."""
    stop = _parse_price(row.get("stopLoss"))
    t1 = _parse_price(row.get("target1") or row.get("target_price"))
    t2 = _parse_price(row.get("target2"))
    if stop is not None and t1 is not None and stop < entry:
        risk = abs(entry - stop)
        if t2 is None:
            t2 = round(entry + SWING_T2_R * risk, 2)
        return stop, t1, t2, risk, "matrix_explicit_levels"

    atr_pct = None
    intraday = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    for raw in (
        row.get("atr_pct"),
        row.get("atrPct"),
        intraday.get("atr_pct") if isinstance(intraday, dict) else None,
    ):
        atr_pct = _f(raw)
        if atr_pct is not None and atr_pct > 0:
            break
    if atr_pct is None or atr_pct <= 0:
        atr_pct = SWING_DEFAULT_ATR_PCT
        levels_src = f"desk_atr_default_{SWING_DEFAULT_ATR_PCT:g}pct"
    else:
        levels_src = "matrix_atr_pct"

    atr_abs = entry * (atr_pct / 100.0)
    stop = round(entry - atr_abs, 2)
    risk = abs(entry - stop)
    t1 = round(entry + SWING_T1_R * risk, 2)
    t2 = round(entry + SWING_T2_R * risk, 2)
    return stop, t1, t2, risk, levels_src


def _normalize_swing_row(raw: dict[str, Any], session_date: str) -> dict[str, Any] | None:
    symbol = str(raw.get("symbol") or raw.get("ticker") or "").upper().strip()
    if not symbol:
        return None
    entry = _parse_price(
        raw.get("entryPrice")
        or raw.get("buyAbove")
        or raw.get("entry")
        or raw.get("ltp")
        or raw.get("ltpRaw")
        or raw.get("scanLtp")
    )
    if entry is None:
        return None
    if not is_swing_desk_eligible(symbol, entry):
        return None

    stop = _parse_price(raw.get("stopLoss"))
    t1 = _parse_price(raw.get("target1") or raw.get("target_price"))
    t2 = _parse_price(raw.get("target2"))
    levels_src = str(raw.get("levelsSource") or "")
    risk = _f(raw.get("riskPerShare"))
    if stop is None or t1 is None:
        stop, t1, t2, risk, levels_src = _matrix_row_levels(raw, entry)
    elif risk is None:
        risk = abs(entry - stop)
        if t2 is None and risk > 0:
            t2 = round(entry + SWING_T2_R * risk, 2)
        levels_src = levels_src or "matrix_explicit_levels"

    if stop is None or t1 is None or risk is None or risk <= 0:
        return None
    return {
        "symbol": symbol,
        "name": raw.get("name") or symbol,
        "direction": "LONG",
        "book": "SWING",
        "entryDate": raw.get("entryDate") or session_date,
        "entryPrice": entry,
        "buyAbove": _parse_price(raw.get("buyAbove")) or entry,
        "stopLoss": stop,
        "target1": t1,
        "target2": t2,
        "riskPerShare": risk,
        "rewardRisk": _f(raw.get("rewardRisk") or raw.get("rrT2")) or round(SWING_T2_R, 2),
        "approxQty": int(raw.get("approxQty") or raw.get("approx_qty") or 0),
        "deployedCapital": _f(raw.get("deployedCapital")) or 0.0,
        "score": _f(raw.get("score")),
        "sector": raw.get("sector"),
        "scanLtp": _parse_price(raw.get("scanLtp") or raw.get("ltp") or raw.get("ltpRaw")),
        "currentPrice": _parse_price(
            raw.get("currentPrice") or raw.get("ltp") or raw.get("ltpRaw") or raw.get("scanLtp") or entry
        ),
        "status": raw.get("status") or "RUNNING",
        "sessionLocked": True,
        "source": "swing_session",
        "levelsSource": levels_src or "matrix",
        "selectionReason": raw.get("selection_reason") or raw.get("selectionReason"),
        "verdict": raw.get("verdict") or raw.get("action"),
        "dayChangePct": _f(raw.get("dayChangePct") or raw.get("delta")),
    }


def _stock_is_matrix_buy(row: dict[str, Any]) -> bool:
    verdict = str(row.get("verdict") or row.get("action") or "").upper().strip()
    if verdict in ("BUY", "STRONG_BUY", "APPROVE", "CORE_BUY"):
        return True
    # Ledger rows often omit verdict — treat scored ledger entries as BUY display
    if row.get("_fromLedger"):
        return True
    score = _f(row.get("score"))
    return bool(score is not None and score >= 15.0 and verdict not in ("REJECT", "SELL", "AVOID"))


def _picks_from_asset_matrix(
    snapshot: dict[str, Any] | None = None,
    *,
    exclude_symbols: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """SWING PORTFOLIO lock source: ledger_stocks then ranked Matrix BUY stocks[].

    Never reads dhanSwingPicks. Skips symbols already locked on the intradAy desk.
    """
    snap = snapshot if isinstance(snapshot, dict) else _read_json(_SNAPSHOT_PATH)
    ti = snap.get("terminalIntelligence") if isinstance(snap.get("terminalIntelligence"), dict) else {}
    ledger = ti.get("ledger_stocks") if isinstance(ti.get("ledger_stocks"), list) else []
    stocks = snap.get("stocks") if isinstance(snap.get("stocks"), list) else []
    quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    blocked = {str(s).upper().strip() for s in (exclude_symbols or set()) if str(s).strip()}

    by_ticker: dict[str, dict[str, Any]] = {}
    for s in stocks:
        if not isinstance(s, dict):
            continue
        sym = str(s.get("ticker") or s.get("symbol") or s.get("Sym") or "").upper().strip()
        if sym:
            by_ticker[sym] = s

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set(blocked)
    skipped_cross = 0

    def _merge_quote(row: dict[str, Any], sym: str) -> dict[str, Any]:
        out = dict(row)
        q = quotes.get(sym) if isinstance(quotes.get(sym), dict) else None
        stock = by_ticker.get(sym)
        if stock:
            for k in ("ltp", "ltpRaw", "delta", "intraday", "score", "verdict", "name", "sector"):
                if out.get(k) in (None, "", []) and stock.get(k) is not None:
                    out[k] = stock.get(k)
            if not out.get("intraday") and isinstance(stock.get("intraday"), dict):
                out["intraday"] = stock["intraday"]
        if q:
            if out.get("ltp") in (None, "") and q.get("ltp") is not None:
                out["ltp"] = q.get("ltp")
            if out.get("ltpRaw") in (None, "") and q.get("ltpRaw") is not None:
                out["ltpRaw"] = q.get("ltpRaw")
            if out.get("delta") in (None, "") and q.get("delta") is not None:
                out["delta"] = q.get("delta")
        return out

    src = "asset_matrix_buy"
    if ledger:
        src = "asset_matrix_ledger"
        ranked_ledger = sorted(
            [r for r in ledger if isinstance(r, dict)],
            key=lambda r: float(r.get("score") or 0),
            reverse=True,
        )
        for row in ranked_ledger:
            sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            if sym in blocked:
                skipped_cross += 1
                continue
            if sym in seen:
                continue
            merged = _merge_quote({**row, "_fromLedger": True, "symbol": sym, "ticker": sym}, sym)
            if not _stock_is_matrix_buy(merged):
                continue
            seen.add(sym)
            candidates.append(merged)
            if len(candidates) >= SWING_MATRIX_LOCK_COUNT:
                break

    if len(candidates) < SWING_MATRIX_LOCK_COUNT:
        ranked = sorted(
            [s for s in stocks if isinstance(s, dict)],
            key=lambda r: float(r.get("score") or 0),
            reverse=True,
        )
        for row in ranked:
            sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            if sym in blocked:
                skipped_cross += 1
                continue
            if sym in seen:
                continue
            merged = _merge_quote({**row, "symbol": sym, "ticker": sym}, sym)
            if not _stock_is_matrix_buy(merged):
                continue
            seen.add(sym)
            candidates.append(merged)
            if len(candidates) >= SWING_MATRIX_LOCK_COUNT:
                break

    if skipped_cross:
        log.info(
            "Swing matrix skip %d intradAy-locked symbol(s) for cross-book uniqueness",
            skipped_cross,
        )
    return candidates[:SWING_MATRIX_LOCK_COUNT], src


def _scrub_ineligible_swing_rows(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop pennies / DVR names from an already-locked book."""
    removed: list[str] = []
    long_kept: list[dict[str, Any]] = []
    for r in session.get("long") or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper().strip()
        entry = _f(r.get("entryPrice") or r.get("scanLtp") or r.get("currentPrice"))
        if not is_swing_desk_eligible(sym, entry):
            removed.append(sym or "?")
            continue
        long_kept.append(r)
    short_kept: list[dict[str, Any]] = []
    for r in session.get("short") or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or "").upper().strip()
        entry = _f(r.get("entryPrice") or r.get("scanLtp") or r.get("currentPrice"))
        if not is_swing_desk_eligible(sym, entry):
            removed.append(sym or "?")
            continue
        short_kept.append(r)
    if not removed:
        return session, []
    sess = dict(session)
    sess["long"] = long_kept
    sess["short"] = short_kept
    prev_skip = list(sess.get("skippedIncomplete") or [])
    for sym in removed:
        tag = f"{sym}:desk_gate(min={SWING_MIN_PRICE:g}|no_dvr)"
        if tag not in prev_skip:
            prev_skip.append(tag)
    sess["skippedIncomplete"] = prev_skip
    sess["counts"] = {
        "long": len(long_kept),
        "short": len(short_kept),
        "total": len(long_kept) + len(short_kept),
    }
    sess["updatedAt"] = _utc_now_iso()
    log.info(
        "Scrubbed %d ineligible swing name(s) (min_price=%.0f, no DVR): %s",
        len(removed),
        SWING_MIN_PRICE,
        ",".join(removed),
    )
    return sess, removed


def _scrub_cross_book_swing_rows(session: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop swing rows whose symbol is already on today's locked intradAy desk.

    Does not re-size remaining rows — preserves qty / outcome fields.
    """
    day = str(session.get("sessionDate") or _ist_today())[:10]
    blocked = intraday_locked_symbols(day)
    if not blocked:
        return session, []
    long_kept, dropped_long = filter_rows_excluding(list(session.get("long") or []), blocked)
    short_kept, dropped_short = filter_rows_excluding(list(session.get("short") or []), blocked)
    removed = sorted(set(dropped_long + dropped_short))
    if not removed:
        return session, []
    sess = dict(session)
    sess["long"] = long_kept
    sess["short"] = short_kept
    prev_skip = list(sess.get("skippedIncomplete") or [])
    for sym in removed:
        tag = f"{sym}:cross_book_intraday"
        if tag not in prev_skip:
            prev_skip.append(tag)
    sess["skippedIncomplete"] = prev_skip
    sess["counts"] = {
        "long": len(long_kept),
        "short": len(short_kept),
        "total": len(long_kept) + len(short_kept),
    }
    sess["crossBookExcluded"] = removed
    sess["updatedAt"] = _utc_now_iso()
    log.info(
        "Scrubbed %d swing name(s) already on intradAy desk: %s",
        len(removed),
        ",".join(removed),
    )
    return sess, removed


def _persist_swing_if_changed(original: dict[str, Any], scrubbed: dict[str, Any]) -> dict[str, Any]:
    if scrubbed is original:
        return scrubbed
    if (
        scrubbed.get("long") == original.get("long")
        and scrubbed.get("short") == original.get("short")
        and scrubbed.get("skippedIncomplete") == original.get("skippedIncomplete")
    ):
        return scrubbed
    _atomic_write(_SWING_SESSION_PATH, scrubbed)
    return scrubbed


def lock_swing_session(*, force: bool = False, bypass_lock_window: bool = False) -> dict[str, Any]:
    """Snapshot Asset Matrix BUY set into swing_session.json.

    Daily rotation: a locked book from a prior IST sessionDate is treated as stale
    and re-locked from fresh Matrix BUY cards (force), irrespective of P&L.
    Never locks from dhanSwingPicks / ScanX.

    Time gate: primary 09:45–10:15 IST (or late-start catch-up). Only
    ``bypass_lock_window=True`` skips the clock. ``force`` rebuilds — does not open early.
    """
    existing = load_swing_session()
    today = _ist_today()
    existing_date = str(existing.get("sessionDate") or "").strip()[:10]
    stale_day = bool(
        existing.get("locked")
        and (existing.get("long") or [])
        and existing_date
        and existing_date != today
    )
    if stale_day and not force:
        log.info(
            "Swing sessionDate %s != today %s — forcing daily rotate from asset_matrix_buy",
            existing_date,
            today,
        )
        force = True

    if existing.get("locked") and not force and (existing.get("long") or []):
        scrubbed, removed_gate = _scrub_ineligible_swing_rows(existing)
        scrubbed, removed_cross = _scrub_cross_book_swing_rows(scrubbed)
        removed = removed_gate + removed_cross
        if removed_gate:
            scrubbed = apply_swing_sizing(scrubbed, persist=True, force=True)
        elif removed_cross:
            scrubbed = _persist_swing_if_changed(existing, scrubbed)
        return {
            "success": True,
            "alreadyLocked": True,
            "scrubbed": removed,
            "crossBookExcluded": removed_cross,
            "session": scrubbed,
        }

    allowed, reason = basket_lock_allowed(allow_manual_override=bool(bypass_lock_window))
    if not allowed:
        return {
            "success": False,
            "error": basket_lock_block_message(reason),
            "lockWindow": reason,
            "session": existing,
        }

    exclude = intraday_locked_symbols(today)
    raw_picks, snap_src = _picks_from_asset_matrix(exclude_symbols=exclude)
    session_date = today
    long_rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for raw in raw_picks:
        sym = str(raw.get("symbol") or raw.get("ticker") or "?").upper().strip()
        entry = _parse_price(
            raw.get("entryPrice")
            or raw.get("buyAbove")
            or raw.get("entry")
            or raw.get("ltp")
            or raw.get("ltpRaw")
            or raw.get("scanLtp")
        )
        row = _normalize_swing_row(raw, session_date)
        if row is None:
            if sym and entry is not None and not is_swing_desk_eligible(sym, entry):
                skipped.append(f"{sym}:desk_gate(min={SWING_MIN_PRICE:g}|no_dvr)")
            else:
                skipped.append(sym or "?")
            continue
        long_rows.append(row)

    if not long_rows:
        return {
            "success": False,
            "error": (
                "No Asset Matrix BUY names with entry/SL/T1 passing desk gates "
                f"(min price {SWING_MIN_PRICE:g}, no DVR) — refresh market snapshot / Matrix first."
            ),
            "skipped": skipped,
            "session": existing,
            "staleDay": stale_day,
        }

    slots = max(1, len(long_rows))
    long_rows = [
        attach_exit_plan(_size_swing_row(r, sleeve=SWING_CAPITAL, slots=slots))
        for r in long_rows
    ]

    committed_at = _utc_now_iso()
    session = {
        "success": True,
        "locked": True,
        "book": "SWING",
        "sessionDate": session_date,
        "committedAt": committed_at,
        "updatedAt": committed_at,
        "executionPolicy": "MANUAL_ONLY",
        "source": snap_src if snap_src.startswith("asset_matrix") else "asset_matrix_buy",
        "rotation": "DAILY",
        "priorSessionDate": existing_date if stale_day else None,
        "long": long_rows,
        "short": [],
        "skippedIncomplete": skipped,
        "capital": {
            "swingCapital": SWING_CAPITAL,
            "riskFraction": SWING_RISK_FRACTION,
            "slots": slots,
        },
        "counts": {"long": len(long_rows), "short": 0, "total": len(long_rows)},
        "deskGates": {"minPrice": SWING_MIN_PRICE, "rejectDvr": True},
        "crossBookExcluded": sorted(exclude),
    }
    _atomic_write(_SWING_SESSION_PATH, session)
    try:
        from .trade_outcome import emit_book_lock_alerts

        emit_book_lock_alerts(
            book="SWING",
            session_date=session_date,
            long_rows=long_rows,
            short_rows=[],
        )
    except Exception as exc:
        log.warning("Swing lock alerts failed: %s", exc)
    log.info(
        "Locked swing session from %s: %d LONGs (%s)%s%s",
        session["source"],
        len(long_rows),
        session_date,
        f" rotated from {existing_date}" if stale_day else "",
        f" excluded intradAy={sorted(exclude)}" if exclude else "",
    )
    return {
        "success": True,
        "alreadyLocked": False,
        "rotated": stale_day,
        "session": session,
    }


def ensure_swing_session_locked() -> dict[str, Any]:
    """Idempotent lock — rotates automatically when sessionDate != IST today."""
    existing = load_swing_session()
    today = _ist_today()
    existing_date = str(existing.get("sessionDate") or "").strip()[:10]
    if existing.get("locked") and (existing.get("long") or []) and existing_date == today:
        scrubbed, removed_gate = _scrub_ineligible_swing_rows(existing)
        scrubbed, removed_cross = _scrub_cross_book_swing_rows(scrubbed)
        if removed_gate:
            return apply_swing_sizing(scrubbed, persist=True, force=True)
        if removed_cross:
            return _persist_swing_if_changed(existing, scrubbed)
        return scrubbed
    # New day or empty → force re-lock from Asset Matrix BUY
    result = lock_swing_session(force=True if (existing.get("locked") and existing_date != today) else False)
    return result.get("session") or existing


def _enrich_swing_row_prices(
    row: dict[str, Any],
    quotes: dict[str, Any],
    stocks_by: dict[str, Any],
    live_marks: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Price-only MTM — never mutate symbol / levels / lock fields."""
    out = dict(row)
    symbol = str(out.get("symbol") or "").upper()
    ltp = None
    ltp_source = "none"
    delta = None
    # Prefer Angel/Yahoo live marks when provided (market-hours desk poll)
    if live_marks and symbol in live_marks:
        try:
            mark = float(live_marks[symbol])
            if mark > 0:
                ltp = mark
                ltp_source = "live"
        except (TypeError, ValueError):
            pass
    q = quotes.get(symbol) if isinstance(quotes.get(symbol), dict) else None
    s = stocks_by.get(symbol) if isinstance(stocks_by.get(symbol), dict) else None
    if ltp is None and q:
        ltp = _parse_price(q.get("ltpRaw") or q.get("ltp"))
        if ltp is not None:
            ltp_source = "snapshot_quote"
        delta = _f(q.get("delta"))
    if ltp is None and s:
        ltp = _parse_price(s.get("ltpRaw") or s.get("ltp"))
        if ltp is not None:
            ltp_source = "snapshot_stock"
        if delta is None:
            delta = _f(s.get("delta"))
    if ltp is None:
        ltp = _parse_price(out.get("currentPrice") or out.get("ltp") or out.get("scanLtp") or out.get("entryPrice"))
        ltp_source = "cached" if ltp is not None else "none"

    entry = _parse_price(out.get("entryPrice")) or 0.0
    qty = int(out.get("approxQty") or 0)
    unrealized = None
    unrealized_pct = None
    if ltp is not None and entry > 0:
        unrealized = round((ltp - entry) * qty, 2) if qty else None
        unrealized_pct = round((ltp - entry) / entry * 100.0, 2)
    out["ltp"] = round(ltp, 2) if ltp is not None else None
    out["currentPrice"] = out["ltp"]
    out["ltpSource"] = ltp_source
    out["dayChangePct"] = delta if delta is not None else out.get("dayChangePct")
    out["unrealizedPnl"] = unrealized
    out["unrealizedPnlPct"] = unrealized_pct

    # Scale-trail live MTM when exitPlan present (or attachable)
    after_close = False
    try:
        after_close = not _is_market_open()
    except Exception:
        after_close = False

    if not isinstance(out.get("exitPlan"), dict):
        try:
            attached = attach_exit_plan(out)
            if isinstance(attached.get("exitPlan"), dict):
                out["exitPlan"] = attached["exitPlan"]
        except Exception:
            pass

    if isinstance(out.get("exitPlan"), dict) and ltp is not None:
        try:
            ev = evaluate_scale_trail(out, ltp, after_close=after_close)
            if ev:
                out["outcome"] = {
                    "label": ev.get("label"),
                    "detail": ev.get("detail"),
                    "hitLevel": ev.get("hitLevel"),
                    "ltp": ev.get("ltp"),
                    "pctChange": ev.get("pctChange"),
                    "scaleTrail": True,
                    "closed": ev.get("closed"),
                }
                if isinstance(ev.get("exitState"), dict):
                    out["exitState"] = ev["exitState"]
                out["remainingQty"] = ev.get("remainingQty")
                out["realizedPnl"] = ev.get("realizedPnl")
                out["unrealizedPnl"] = ev.get("unrealizedPnl")
                out["effectiveStop"] = ev.get("effectiveStop")
                if entry > 0 and ltp is not None:
                    out["unrealizedPnlPct"] = round((ltp - entry) / entry * 100.0, 2)
                if ev.get("closed"):
                    out["closed"] = True
                    out["status"] = str(ev.get("label") or "CLOSED")
                elif ev.get("hitLevel") == "partial":
                    out["status"] = str(ev.get("label") or "PARTIAL")
                elif after_close:
                    st = str(out.get("status") or "").upper()
                    if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
                        out["status"] = "SESSION CLOSED"
            elif after_close:
                st = str(out.get("status") or "").upper()
                if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
                    out["status"] = "SESSION CLOSED"
        except Exception:
            if after_close:
                st = str(out.get("status") or "").upper()
                if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
                    out["status"] = "SESSION CLOSED"
    elif after_close:
        st = str(out.get("status") or "").upper()
        if st in ("", "RUNNING", "DATA STALE") or out.get("status") is None:
            out["status"] = "SESSION CLOSED"
    # Symbols / levels stay immutable
    return out


def get_swing_session(*, live: bool = False) -> dict[str, Any]:
    """Return locked swing session; with live=True enrich LTP/Δ only."""
    sess = load_swing_session()
    if not sess:
        return {"locked": False, "long": [], "short": [], "counts": {"total": 0}}
    if not live:
        return sess
    snap = _read_json(_SNAPSHOT_PATH)
    quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    stocks_by: dict[str, Any] = {}
    for s in snap.get("stocks") or []:
        if isinstance(s, dict):
            sym = str(s.get("ticker") or s.get("symbol") or "").upper().strip()
            if sym:
                stocks_by[sym] = s
    live_marks: dict[str, float] = {}
    try:
        from .trade_outcome import fetch_live_marks_for_symbols

        syms = [
            str(r.get("symbol") or "").upper()
            for r in (sess.get("long") or []) + (sess.get("short") or [])
            if isinstance(r, dict) and r.get("symbol")
        ]
        live_marks = fetch_live_marks_for_symbols(syms)
    except Exception:
        live_marks = {}
    out = dict(sess)
    out["long"] = [
        _enrich_swing_row_prices(r, quotes, stocks_by, live_marks)
        for r in (sess.get("long") or [])
        if isinstance(r, dict)
    ]
    out["short"] = [
        _enrich_swing_row_prices(r, quotes, stocks_by, live_marks)
        for r in (sess.get("short") or [])
        if isinstance(r, dict)
    ]
    long_u = sum(float(r.get("unrealizedPnl") or 0) for r in out["long"])
    out["portfolio"] = {
        "swingCapital": (sess.get("capital") or {}).get("swingCapital", SWING_CAPITAL),
        "unrealizedPnl": round(long_u, 2),
        "lockedCount": len(out["long"]),
    }
    out["priceOnly"] = True
    out["liveMarks"] = len(live_marks)
    out["updatedAt"] = _utc_now_iso()
    out["snapshotUpdatedAt"] = snap.get("updatedAt")
    try:
        from .trade_outcome import collect_hit_alerts_from_rows

        out["newAlerts"] = collect_hit_alerts_from_rows(
            list(out["long"]) + list(out["short"]),
            book="SWING",
        )
    except Exception:
        out["newAlerts"] = []
    return out
