"""Single persistence worker that owns all SQLite writes."""

from __future__ import annotations

import threading
import time
from typing import Any

from .schemas import Event, EventType
from .sqlite_store import get_sqlite_store
from .view_store import get_view_store
from .market_state import get_market_state
from .event_bus import get_event_bus


class PersistenceWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        sqlite = get_sqlite_store()
        view_store = get_view_store()
        market_state = get_market_state()
        event_bus = get_event_bus()
        while not self._stop.is_set():
            try:
                events = event_bus.drain()
                for event in events:
                    try:
                        sqlite.persist_trade_event(
                            event.type.value,
                            event.payload,
                        )
                    except Exception:
                        pass
                for quote in market_state.drain_dirty_quotes():
                    sqlite.persist_quote({
                        "symbol": quote.symbol,
                        "ltp": quote.ltp,
                        "bid": quote.bid,
                        "ask": quote.ask,
                        "volume": quote.volume,
                        "oi": quote.oi,
                        "source": quote.source,
                        "updated_at": quote.timestamp,
                    })
                snap = view_store.snapshot()
                for namespace, view in snap.items():
                    sqlite.persist_view_snapshot(namespace, view)
            except Exception:
                pass
            self._stop.wait(1.0)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


PERSISTENCE_WORKER: PersistenceWorker | None = None


def get_persistence_worker() -> PersistenceWorker:
    global PERSISTENCE_WORKER
    if PERSISTENCE_WORKER is None:
        PERSISTENCE_WORKER = PersistenceWorker()
    return PERSISTENCE_WORKER
