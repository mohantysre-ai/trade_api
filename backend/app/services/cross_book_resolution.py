"""Cross-book resolution between Swing and Intraday desks.

Intraday always keeps its symbols. Swing must discard any symbol that Intraday owns.

- Intraday LONG symbols are never promoted to Swing.
- Swing scrubs any symbol that exists on the Intraday LONG book.
- Intraday SHORT rows are never relevant to Swing (Swing book is BUY-only).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .desk_book_symbols import (
    _INTRADAY_SESSION_PATH,
    _SWING_SESSION_PATH,
    _read_json,
    filter_rows_excluding,
    locked_symbols_for_date,
)

log = logging.getLogger(__name__)


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_matrix_snapshot() -> dict[str, Any]:
    from .market_snapshot_store import readable_market_snapshot_path

    return _read_json(str(readable_market_snapshot_path()))


def _matrix_row_for_symbol(snapshot: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    sym = str(symbol or "").upper().strip()
    if not sym:
        return None
    stocks = snapshot.get("stocks") if isinstance(snapshot.get("stocks"), list) else []
    quotes = snapshot.get("stockQuotes") if isinstance(snapshot.get("stockQuotes"), dict) else {}
    row: dict[str, Any] | None = None
    for item in stocks:
        if not isinstance(item, dict):
            continue
        key = str(item.get("ticker") or item.get("symbol") or "").upper().strip()
        if key == sym:
            row = dict(item)
            break
    quote = quotes.get(sym) if isinstance(quotes.get(sym), dict) else None
    if row is None and quote is None:
        return None
    out = dict(row or quote or {})
    out.setdefault("symbol", sym)
    out.setdefault("ticker", sym)
    if isinstance(quote, dict):
        for key in ("ltp", "ltpRaw", "open", "close", "intraday", "oi", "prev_oi"):
            if out.get(key) in (None, "", []) and quote.get(key) is not None:
                out[key] = quote.get(key)
    if isinstance(row, dict):
        for key in (
            "score",
            "alpha_score",
            "confidence",
            "intraday",
            "passes_hard_filters",
            "passes_quality_filters",
            "deterministicSide",
            "direction",
            "side",
            "rsi",
            "vwap",
            "ema9",
            "oiSetup",
            "breakoutPass",
            "pivotR1Breakout",
            "rsiPivotBreak",
        ):
            if out.get(key) in (None, "", []) and row.get(key) is not None:
                out[key] = row.get(key)
    return out


def swing_probability_score(row: dict[str, Any]) -> float:
    """Higher = stronger Matrix swing BUY edge (facts-only fields)."""
    score = _float(row.get("score") or row.get("alpha_score")) or 0.0
    confidence = _float(row.get("confidence")) or 0.0
    intra = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    rsi = _float(row.get("rsi") or intra.get("rsi")) or 0.0
    return round(score * 0.55 + confidence * 0.25 + min(max(rsi, 0.0), 100.0) * 0.20, 4)


def intraday_probability_score(row: dict[str, Any]) -> float:
    """Higher = stronger intraday adoption edge."""
    qer = _float(row.get("qualityAdjustedExpectedR")) or 0.0
    score = _float(row.get("score")) or 0.0
    entry_state = str(row.get("entryState") or "").upper()
    qualified_boost = 35.0 if entry_state == "QUALIFIED" else 0.0
    return round(qualified_boost + qer * 45.0 + score * 0.45, 4)


def swing_prefers_over_intraday(
    symbol: str,
    intraday_row: dict[str, Any] | None,
    *,
    snapshot: dict[str, Any] | None = None,
) -> bool:
    """True when swing BUY contract passes and beats the intraday row.
    
    DISABLED: Intraday always keeps its symbols. Swing cannot promote from Intraday.
    """
    return False


def intraday_long_rows(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in session.get("long") or []:
        if not isinstance(row, dict) or row.get("closed"):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
        if sym:
            out[sym] = row
    return out


def symbols_swing_prefers_over_intraday(
    day: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> set[str]:
    """Symbols on today's intraday LONG book that should move to swing.
    
    DISABLED: Swing-first promotion is disabled. Intraday always keeps its symbols.
    """
    return set()


def intraday_blocks_swing_symbol(
    symbol: str,
    day: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> bool:
    """True when intraday still owns the symbol (swing must not hunt it)."""
    session = _read_json(_INTRADAY_SESSION_PATH)
    if str(session.get("sessionDate") or "")[:10] != str(day or "")[:10]:
        return False
    row = intraday_long_rows(session).get(str(symbol or "").upper().strip())
    if row is None:
        return False
    return not swing_prefers_over_intraday(symbol, row, snapshot=snapshot)


def intraday_locked_symbols_respecting_swing(day: str) -> set[str]:
    """Intraday LONG symbols that still block swing after swing-first resolution."""
    session = _read_json(_INTRADAY_SESSION_PATH)
    blocked = locked_symbols_for_date(session, day=day)
    if not blocked:
        return set()
    snap = _load_matrix_snapshot()
    return {
        sym
        for sym in blocked
        if intraday_blocks_swing_symbol(sym, day, snapshot=snap)
    }


def reconcile_cross_book(day: str, *, persist: bool = True) -> dict[str, Any]:
    """Apply cross-book rules: Intraday owns its symbols; Swing discards conflicts."""
    snap = _load_matrix_snapshot()
    intra_session = _read_json(_INTRADAY_SESSION_PATH)
    swing_session = _read_json(_SWING_SESSION_PATH)
    promoted: list[str] = []
    swing_scrubbed: list[str] = []

    # Swing-first promotion DISABLED: Intraday always keeps its symbols.
    # No symbols are promoted from Intraday to Swing.

    # Scrub swing symbols that Intraday already owns (Intraday wins conflicts).
    if (
        str(swing_session.get("sessionDate") or "")[:10] == str(day or "")[:10]
        and swing_session.get("locked")
    ):
        intra_rows = intraday_long_rows(intra_session)
        open_long = [
            r for r in (swing_session.get("long") or [])
            if isinstance(r, dict) and not r.get("closed")
        ]
        closed_long = [
            r for r in (swing_session.get("long") or [])
            if isinstance(r, dict) and r.get("closed")
        ]
        drop_from_swing: set[str] = set()
        for row in open_long:
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym or sym not in intra_rows:
                continue
            # Intraday owns this symbol -> swing must discard it
            drop_from_swing.add(sym)
        if drop_from_swing:
            kept, dropped = filter_rows_excluding(open_long, drop_from_swing)
            swing_scrubbed = sorted(set(dropped))
            sess = dict(swing_session)
            sess["long"] = closed_long + kept
            sess["crossBookExcluded"] = swing_scrubbed
            sess["updatedAt"] = _utc_now_iso()
            if persist:
                from .swing_session import _atomic_write, _recompute_active_swing_totals

                _recompute_active_swing_totals(sess)
                _atomic_write(_SWING_SESSION_PATH, sess)
            swing_session = sess
            log.info(
                "Scrubbed %d swing name(s) owned by Intraday desk: %s",
                len(swing_scrubbed),
                ",".join(swing_scrubbed),
            )

    return {
        "day": day,
        "swingPreferred": [],
        "promotedFromIntraday": promoted,
        "scrubbedFromSwing": swing_scrubbed,
        "intradayBlocksSwing": sorted(intraday_locked_symbols_respecting_swing(day)),
    }


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
