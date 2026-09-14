"""Single persistence worker that owns all SQLite writes."""

from __future__ import annotations

import threading
import time
from typing import Any

from .schemas import Event, EventType
from .sqlite_store import get_sqlite_store
from .view_store import get_view_store
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
