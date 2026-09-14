"""Process-local bounded event bus.

Strategy engines and the feed publish events. The persistence worker and
SSE broadcaster subscribe. Durable events (ENTRY, EXIT, STOP_CHANGE, ...)
are never silently dropped.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from .schemas import Event, EventType


_DURABLE_EVENT_TYPES = {
    EventType.TRADE_EVENT,
    EventType.EOD_READY,
    EventType.INTRADAY_STATE_CHANGED,
    EventType.SWING_STATE_CHANGED,
    EventType.INDEX_OPTIONS_STATE_CHANGED,
}


class EventBus:
    def __init__(self, max_size: int = 2048) -> None:
        self._queue: deque[Event] = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._subscribers: dict[EventType, list[Callable[[Event], None]]] = {}
        self._dropped_low_priority = 0

    def publish(self, event: Event) -> None:
        with self._lock:
            if event.type in _DURABLE_EVENT_TYPES:
                self._queue.append(event)
            elif len(self._queue) < self._queue.maxlen:
                self._queue.append(event)
            else:
                self._dropped_low_priority += 1
        for callback in self._subscribers.get(event.type, []):
            try:
                callback(event)
            except Exception:
                pass

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def drain(self) -> list[Event]:
        with self._lock:
            events = list(self._queue)
            self._queue.clear()
            return events

    @property
    def dropped_low_priority(self) -> int:
        with self._lock:
            return self._dropped_low_priority


EVENT_BUS: EventBus | None = None


def get_event_bus() -> EventBus:
    global EVENT_BUS
    if EVENT_BUS is None:
        EVENT_BUS = EventBus()
    return EVENT_BUS
