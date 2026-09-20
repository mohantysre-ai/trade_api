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
    from .index_options.runtime import strategy_eod
    from .index_options.accounting import eod_positions, merge_paper_books

    strategy = strategy_eod(day)
    matching_live = isinstance(live, dict) and str(live.get("sessionDate") or "")[:10] == day
    cached = None if matching_live else load_book_cache(for_date, "index_options")
    if not matching_live:
        live = {"sessionDate": day, "open": [], "closed": []}
        if cached:
            for row in cached.get("positions") or []:
                closed = row.get("pnlKind") == "realised" or row.get("status") == "CLOSED"
                live["closed" if closed else "open"].append(row)
            if not strategy["positions"]:
                strategy = cached.get("strategyAttribution") or strategy
    if not matching_live and not cached and not strategy["positions"]:
        return {
            "date": day,
            "sessionDate": day,
            "archiveStatus": "NO_BOOK",
            "entryCount": 0,
            "closedCount": 0,
            "totalPnl": None,
            "realizedPnl": None,
            "openPnl": None,
            "positions": [],
        }

    book = merge_paper_books(live, strategy)
    positions = eod_positions(book)
    strategy_rows = strategy["positions"]
    strategy_realized = round(float(strategy.get("realizedPnl") or 0), 2)
    strategy_unrealized = round(float(strategy.get("unrealizedPnl") or 0), 2)

    report = {
        "date": day,
        "sessionDate": day,
        "archiveStatus": "ARCHIVED",
        "mode": live.get("mode") or "AUTO_PAPER_ONLY",
        "entryCount": book["entryCount"],
        "closedCount": book["closedCount"],
        "openCount": book["openCount"],
        "realizedPnl": book["realizedPnl"],
        "openPnl": book["openPnl"],
        "totalPnl": book["totalPnl"],
        "positions": positions,
        "strategyEntryCount": len(strategy_rows),
        "strategyPositions": strategy_rows,
        "strategyRealizedPnl": strategy_realized,
        "strategyUnrealizedPnl": strategy_unrealized,
        "updatedAt": live.get("updatedAt"),
    }
    report["strategyAttribution"] = strategy
    return save_book_cache(for_date, "index_options", report)
