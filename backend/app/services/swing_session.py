"""Compatibility shim: Swing V1 has been removed.

All runtime callers should route through swing_v2.authoritative.
This module preserves the old import surface so remaining references
do not break during the transition.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .market_snapshot_store import readable_market_snapshot_path

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
SWING_MATRIX_LOCK_COUNT = 5


def _matrix_snapshot_path() -> str:
    return str(readable_market_snapshot_path())


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ist_today() -> str:
    return datetime.now(tz=IST).strftime("%Y-%m-%d")


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return n


def _parse_price(v: Any) -> float | None:
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
    cleaned = text.replace("₹", "").replace(",", "").strip()
    try:
        f = float(cleaned)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _invalidate_swing_response_cache() -> None:
    return None


def apply_swing_sizing(
    session: dict[str, Any] | None = None,
    *,
    persist: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    return dict(session or {})


def load_swing_session() -> dict[str, Any]:
    from .swing_v2.authoritative import get_authoritative_session

    return get_authoritative_session(live=False)


def lock_swing_session(*, force: bool = False, **kwargs: Any) -> dict[str, Any]:
    from .swing_v2.authoritative import lock_authoritative_session

    return lock_authoritative_session(force=force)


def ensure_swing_session_locked(**kwargs: Any) -> dict[str, Any]:
    from .swing_v2.authoritative import run_authoritative_cycle

    return run_authoritative_cycle()


def refresh_swing_session_state(**kwargs: Any) -> dict[str, Any]:
    from .swing_v2.authoritative import run_authoritative_cycle

    return run_authoritative_cycle()


def get_swing_session(*, live: bool = False) -> dict[str, Any]:
    from .swing_v2.authoritative import get_authoritative_session

    return get_authoritative_session(live=live)


def _compute_swing_session(*, live: bool = False) -> dict[str, Any]:
    return get_swing_session(live=live)


# V1-only helpers retained as no-ops/stubs for transition period.
# Tests and scripts should migrate to swing_v2 equivalents.


def _ensure_today_matrix_snapshot() -> tuple[bool, str]:
    return True, "V2_REMOVED"


def _run_swing_matrix_refresh() -> dict[str, Any]:
    return {}


def _evaluate_swing_buy_contract(
    row: dict[str, Any], *, context: str = "legacy"
) -> tuple[bool, dict[str, Any], list[str]]:
    return False, {}, ["V1_REMOVED"]


def _matrix_row_levels(
    row: dict[str, Any], entry: float
) -> tuple[float, float, float, float, str]:
    return entry, entry, entry, entry, "V2_REMOVED"


def _normalize_swing_row(
    raw: dict[str, Any], session_date: str
) -> dict[str, Any] | None:
    return None


def _stock_is_matrix_buy(row: dict[str, Any]) -> bool:
    return False


def _in_candle_screen(row: dict[str, Any]) -> bool:
    return False


def _swing_screen_rows(snap: dict[str, Any]) -> list[dict[str, Any]]:
    return []


def _dhan_recommended_symbols(snap: dict[str, Any]) -> list[str]:
    return []


def _picks_from_asset_matrix(
    snapshot: dict[str, Any] | None = None,
    *,
    exclude_symbols: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    return [], "V2_REMOVED"


def _swing_universe_diagnostics(
    *, exclude_symbols: set[str] | None = None, snapshot: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"v2Removed": True}


def _hydrate_swing_contract_row(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _selection_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [row, {}, {}]


def _selection_value(row: dict[str, Any], *keys: str) -> Any:
    return None


def _selection_bool(row: dict[str, Any], *keys: str) -> bool | None:
    return None


def _explicit_deterministic_side(
    row: dict[str, Any],
) -> tuple[str, str | None]:
    return "V2_REMOVED", None


def _risk_audit_values(row: dict[str, Any]) -> list[str]:
    return []


def _snapshot_data_date(snap: dict[str, Any]) -> str:
    return ""


def _snapshot_age_sec(snap: dict[str, Any]) -> float | None:
    return None


def _matrix_snapshot_ready_for_today(
    snap: dict[str, Any],
) -> tuple[bool, str]:
    return False, "V2_REMOVED"


def _normalize_candidate_rows(
    raw_picks: list[dict[str, Any]],
    session_date: str,
    *,
    source: str = "legacy",
) -> tuple[list[dict[str, Any]], list[str]]:
    return [], []


def _size_new_swing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(rows)


def _paper_execute_swing_row(
    row: dict[str, Any], *, filled_at: str | None = None
) -> dict[str, Any]:
    return dict(row)


def _paper_execute_swing_rows(
    rows: list[dict[str, Any]], *, filled_at: str | None = None
) -> list[dict[str, Any]]:
    return list(rows)


def _row_status_label(row: dict[str, Any]) -> str:
    return ""


def _unique_swing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(rows)


def _swing_occupied_symbols(session: dict[str, Any]) -> set[str]:
    return set()


def _dedupe_swing_session_rows(
    session: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    return dict(session), []


def _append_new_swing_entries(
    session: dict[str, Any],
) -> dict[str, Any] | None:
    return None


def _active_swing_rows(session: dict[str, Any]) -> list[dict[str, Any]]:
    return []


def _enrich_swing_row_prices(
    row: dict[str, Any], quotes: dict[str, Any]
) -> dict[str, Any]:
    return dict(row)


def _append_invalid_selection_audit(
    session: dict[str, Any], row: dict[str, Any], reasons: list[str]
) -> dict[str, Any]:
    return dict(session)


def _recompute_active_swing_totals(session: dict[str, Any]) -> None:
    return None


def _scrub_ineligible_swing_rows(
    session: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    return dict(session), []


def _scrub_cross_book_swing_rows(
    session: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    return dict(session), []


def _persist_swing_if_changed(
    original: dict[str, Any], updated: dict[str, Any]
) -> dict[str, Any]:
    return dict(updated)


def _enforce_swing_position_cap(
    session: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    return dict(session), []


def _swing_universe_diagnostics(
    *, exclude_symbols: set[str] | None = None, snapshot: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"v2Removed": True}
