"""Live radar compose: Angel → ScanX → Lemonn, plus session replay routing."""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from .angel_index_options import (
    _apply_oi_baselines,
    active_index_expiries,
    cached_angel_index_option_snapshot,
    option_data_to_strategy_inputs,
    persist_radar,
    unavailable_provider_snapshot,
)
from .angel_index_stream import ANGEL_INDEX_STREAM
from .dhan_scanx_options import apply_scanx_fallback
from .index_options_engine import build_index_options_radar
from .index_options_paper import reconcile_paper_book
from .index_options_replay import parse_session_date, replay_index_options_session
from .lemonn_options import LEMONN_SLUGS, apply_lemonn_fallback, discover_lemonn_expiries
from .trendlyne_oi import apply_oi_enrichment


def compose_live_index_options_radar(
    snapshot: dict[str, Any],
    *,
    live: bool = True,
    client: Any,
    persist: bool = True,
    scanx_fn: Callable[..., dict[str, Any]] = apply_scanx_fallback,
    lemonn_fn: Callable[..., dict[str, Any]] = apply_lemonn_fallback,
    lemonn_discover_fn: Callable[..., dict[str, date]] = discover_lemonn_expiries,
    oi_enrichment_fn: Callable[..., dict[str, Any]] = apply_oi_enrichment,
    expiries_fn: Callable[..., dict[str, date]] = active_index_expiries,
    snapshot_fn: Callable[..., dict[str, Any]] = cached_angel_index_option_snapshot,
) -> dict[str, Any]:
    """Build the live radar. Lemonn fills indexes still unusable after ScanX."""
    book = dict(snapshot)
    option_data: dict[str, Any] | None = None
    if live:
        try:
            option_data = snapshot_fn(client)
        except Exception as exc:
            option_data = unavailable_provider_snapshot(exc)
        expiries: dict[str, date] = {}
        try:
            expiries.update(expiries_fn())
        except Exception as exc:
            option_data["fallbackSource"] = "SCANX"
            option_data["expiryMasterError"] = str(exc)
        missing_expiry = [key for key in LEMONN_SLUGS if key not in expiries]
        if missing_expiry:
            try:
                expiries.update(lemonn_discover_fn(missing_expiry))
            except Exception:
                pass
        try:
            option_data = scanx_fn(option_data, expiries)
        except Exception as exc:
            option_data["fallbackSource"] = "SCANX"
            option_data["fallbackError"] = str(exc)
        try:
            option_data = lemonn_fn(option_data, expiries)
        except Exception as exc:
            option_data["thirdFallbackSource"] = "LEMONN"
            option_data["thirdFallbackError"] = str(exc)
        try:
            option_data = oi_enrichment_fn(option_data, expiries)
        except Exception as exc:
            option_data["oiEnrichment"] = {
                "source": "SIGQ_RESEARCH",
                "status": "UNAVAILABLE",
                "error": str(exc),
            }
        option_data = _apply_oi_baselines(option_data)
        book["indexOptions"] = option_data_to_strategy_inputs(option_data, book)
        book["indexOptionProvider"] = option_data
    result = build_index_options_radar(book)
    result["paperBook"] = reconcile_paper_book(result, client=client, persist=persist)
    result["provider"] = "ANGEL_ONE_WITH_SCANX_AND_LEMONN_FALLBACK"
    result["providerEvidence"] = book.get("indexOptionProvider")
    result["streamStatus"] = ANGEL_INDEX_STREAM.status()
    if persist:
        persist_radar(result)
    return result


def replay_session_payload(
    client: Any,
    raw_session_date: str,
    *,
    today: date | None = None,
    persist: bool = True,
    master: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Closed-session replay. Invalid dates raise ValueError for the HTTP layer."""
    replay_day = parse_session_date(raw_session_date, today=today)
    try:
        return replay_index_options_session(client, replay_day, persist=persist, master=master)
    except Exception as exc:
        return {
            "success": False,
            "mode": "SESSION_REPLAY",
            "sessionDate": replay_day.isoformat(),
            "executionPolicy": "MANUAL_ONLY",
            "candidates": [],
            "selected": [],
            "buySideContracts": [],
            "implemented": [],
            "error": str(exc),
        }
