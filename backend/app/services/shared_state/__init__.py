"""Shared state initialization and helpers."""

from __future__ import annotations

from .event_bus import get_event_bus
from .market_state import get_market_state
from .persistence_worker import get_persistence_worker
from .sqlite_store import get_sqlite_store
from .view_store import get_view_store


def init_shared_state() -> dict[str, Any]:
    market_state = get_market_state()
    view_store = get_view_store()
    event_bus = get_event_bus()
    sqlite_store = get_sqlite_store()
    worker = get_persistence_worker()
    worker.start()
    return {
        "market_state": market_state,
        "view_store": view_store,
        "event_bus": event_bus,
        "sqlite_store": sqlite_store,
        "persistence_worker": worker,
    }


def hydrate_from_sqlite() -> None:
    view_store = get_view_store()
    sqlite_store = get_sqlite_store()
    try:
        snap = sqlite_store.load_all_view_snapshots()
        if snap:
            view_store.hydrate(snap)
    except Exception:
        pass
    try:
        quotes = sqlite_store.load_latest_quotes()
        if quotes:
            get_market_state().hydrate_quotes(quotes)
    except Exception:
        pass
