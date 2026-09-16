"""Date-locked EOD snapshot of the automatic Index Options paper book.

Issue 3 parity: while the live paper book's IST sessionDate matches the
requested day, the EOD snapshot is ALWAYS rebuilt from the live book — a
stale cache must never hide positions (including modular multi-leg strategy
positions) that were opened after the last cache write.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .index_options_paper import paper_book_path
from .json_atomic import load_json_with_fallback


def generate_index_options_eod_report(for_date: date) -> dict[str, Any]:
    """Archive only the paper book whose IST session date matches ``for_date``."""
    from .eod_book_cache import load_book_cache, save_book_cache

    try:
        live = load_json_with_fallback(paper_book_path())
    except (FileNotFoundError, ValueError, TypeError):
        live = {}

    day = for_date.isoformat()
    if not isinstance(live, dict) or str(live.get("sessionDate") or "")[:10] != day:
        cached = load_book_cache(for_date, "index_options")
        if cached is not None:
            return cached
        return {
            "date": day,
            "sessionDate": day,
            "archiveStatus": "NO_BOOK",
            "totalPnl": None,
            "realizedPnl": None,
            "openPnl": None,
            "positions": [],
        }

    # Live parity path — the paper book is the execution source of truth.
    open_rows = [dict(r) for r in (live.get("open") or []) if isinstance(r, dict)]
    closed_rows = [dict(r) for r in (live.get("closed") or []) if isinstance(r, dict)]
    realized = round(sum(float(r.get("pnl") or 0) for r in closed_rows), 2)
    unrealized = round(sum(float(r.get("unrealizedPnl") or 0) for r in open_rows), 2)
    positions = [
        {**r, "pnl": float(r.get("unrealizedPnl") or 0), "pnlKind": "unrealised"}
        for r in open_rows
    ] + [
        {**r, "pnl": float(r.get("pnl") or 0), "pnlKind": "realised"}
        for r in closed_rows
    ]

    strategy: dict[str, Any] = {
        "sessionDate": day,
        "positions": [],
        "realizedPnl": 0.0,
        "unrealizedPnl": 0.0,
    }
    try:
        from .index_options.runtime import strategy_eod

        strategy = strategy_eod(day)
    except Exception:
        pass
    strategy_rows = [dict(r) for r in (strategy.get("positions") or []) if isinstance(r, dict)]
    strategy_realized = round(float(strategy.get("realizedPnl") or 0), 2)
    strategy_unrealized = round(float(strategy.get("unrealizedPnl") or 0), 2)

    report = {
        "date": day,
        "sessionDate": day,
        "archiveStatus": "ARCHIVED",
        "mode": live.get("mode") or "AUTO_PAPER_ONLY",
        "entryCount": len(positions),
        "realizedPnl": realized,
        "openPnl": unrealized,
        "totalPnl": round(realized + unrealized + strategy_realized + strategy_unrealized, 2),
        "positions": positions,
        "strategyEntryCount": len(strategy_rows),
        "strategyPositions": strategy_rows,
        "strategyRealizedPnl": strategy_realized,
        "strategyUnrealizedPnl": strategy_unrealized,
        "updatedAt": live.get("updatedAt"),
    }
    report["strategyAttribution"] = strategy
    return save_book_cache(for_date, "index_options", report)
