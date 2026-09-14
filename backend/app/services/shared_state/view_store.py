"""In-memory precomputed view store.

Strategy engines compose their output once into a ViewVersion, then UI reads
that immutable snapshot. No strategy recomputation on a user request.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .schemas import ViewVersion

_ALLOWED_NAMESPACES = {
    "market_summary",
    "intraday",
    "swing",
    "index_options",
    "eod",
}


class ViewStore:
    """Thread-safe view store with copy-on-write semantics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._views: dict[str, ViewVersion] = {}

    def set(self, namespace: str, payload: dict[str, Any]) -> None:
        if namespace not in _ALLOWED_NAMESPACES:
            raise ValueError(f"Unknown view namespace: {namespace}")
        with self._lock:
            current = self._views.get(namespace)
            version = (current.version + 1) if current else 1
            self._views[namespace] = ViewVersion(
                version=version,
                updated_at=time.time(),
                payload=dict(payload),
            )

    def get(self, namespace: str) -> dict[str, Any] | None:
        with self._lock:
            view = self._views.get(namespace)
            if view is None:
                return None
            return {
                "version": view.version,
                "updatedAt": view.updated_at,
                "payload": dict(view.payload),
            }

    def get_version(self, namespace: str) -> int:
        with self._lock:
            view = self._views.get(namespace)
            return view.version if view else 0

    def get_payload(self, namespace: str) -> dict[str, Any] | None:
        with self._lock:
            view = self._views.get(namespace)
            return dict(view.payload) if view else None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                ns: {
                    "version": v.version,
                    "updatedAt": v.updated_at,
                    "payload": dict(v.payload),
                }
                for ns, v in self._views.items()
            }

    def hydrate(self, state: dict[str, Any]) -> None:
        with self._lock:
            for ns, raw in state.items():
                if ns not in _ALLOWED_NAMESPACES:
                    continue
                if not isinstance(raw, dict):
                    continue
                self._views[ns] = ViewVersion(
                    version=int(raw.get("version") or 0),
                    updated_at=float(raw.get("updatedAt") or time.time()),
                    payload=dict(raw.get("payload") or {}),
                )


VIEW_STORE: ViewStore | None = None


def get_view_store() -> ViewStore:
    global VIEW_STORE
    if VIEW_STORE is None:
        VIEW_STORE = ViewStore()
    return VIEW_STORE
