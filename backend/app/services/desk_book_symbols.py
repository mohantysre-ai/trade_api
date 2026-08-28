"""Cross-book symbol exclusivity for Swing vs Intraday desks.

Same ticker must not appear in both books on the same IST session date.
Priority: Swing wins when the Matrix BUY contract passes with higher buy
probability than the intraday row; otherwise intraday keeps the symbol.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.dirname(_SERVICES_DIR)
_BACKEND_DIR = os.path.dirname(_APP_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

_SWING_SESSION_PATH = os.environ.get(
    "SWING_SESSION_FILE",
    os.path.join(_REPO_ROOT, "swing_session.json"),
)
_INTRADAY_SESSION_PATH = os.environ.get(
    "INTRADAY_SESSION_FILE",
    os.path.join(_REPO_ROOT, "intraday_session.json"),
)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def locked_symbols_for_date(session: dict[str, Any] | None, *, day: str) -> set[str]:
    """Uppercased symbols from long+short when locked and sessionDate matches day."""
    if not isinstance(session, dict) or not session.get("locked"):
        return set()
    if str(session.get("sessionDate") or "")[:10] != str(day or "")[:10]:
        return set()
    out: set[str] = set()
    for side in ("long", "short"):
        for row in session.get(side) or []:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
            if sym:
                out.add(sym)
    return out


def intraday_locked_symbols(day: str) -> set[str]:
    return locked_symbols_for_date(_read_json(_INTRADAY_SESSION_PATH), day=day)


def swing_locked_symbols(day: str) -> set[str]:
    return locked_symbols_for_date(_read_json(_SWING_SESSION_PATH), day=day)


def filter_rows_excluding(
    rows: list[Any],
    exclude: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep dict rows whose symbol is not in exclude. Returns (kept, dropped_syms)."""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
        if sym and sym in exclude:
            dropped.append(sym)
            continue
        kept.append(row)
    return kept, dropped
