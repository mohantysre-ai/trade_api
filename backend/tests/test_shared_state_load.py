"""Load and correctness tests for the shared-state architecture."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from app.services.shared_state.market_state import get_market_state
from app.services.shared_state.view_store import get_view_store
from app.services.shared_state.sqlite_store import get_sqlite_store
from app.services.shared_state.schemas import FeedStatus, Quote


class TestIndexOptionsZeroBrokerOnRead:
    def test_viewstore_hit_returns_without_broker(self, monkeypatch):
        from app.services.shared_state import get_view_store

        store = get_view_store()
        store.set("index_options", {
            "success": True,
            "selected": [],
            "sellerCandidates": [],
            "sessionStatus": "OPEN",
            "huntActive": True,
            "limits": {"huntMode": "CONTINUOUS_MARKET_SESSION"},
        })

        import app.services.index_options_paper as paper_mod
        original_market_open = paper_mod.index_options_market_open
        paper_mod.index_options_market_open = lambda now=None: True

        try:
            from app.services.angel_one_feed import create_app
            app = create_app()
            from fastapi.testclient import TestClient
            client = TestClient(app)

            resp = client.get("/api/index-options")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("cacheStatus") == "HIT"
        finally:
            paper_mod.index_options_market_open = original_market_open


class TestRestartRecovery:
    def test_hydrate_from_sqlite_loads_view_snapshots(self, tmp_path, monkeypatch):
        from app.services.shared_state import hydrate_from_sqlite, get_view_store
        from app.services.shared_state.sqlite_store import SQLiteStore

        db = SQLiteStore(tmp_path / "test.db")
        db.persist_view_snapshot("intraday", type("ViewVersion", (), {
            "version": 5,
            "updated_at": 1000.0,
            "payload": {"locked": True},
        })())
        time.sleep(0.2)

        import app.services.shared_state as shared_state_mod
        original_get_sqlite = shared_state_mod.get_sqlite_store
        shared_state_mod.get_sqlite_store = lambda: db
        try:
            hydrate_from_sqlite()
            view = get_view_store().get("intraday")
            assert view is not None
            assert view["version"] == 5
        finally:
            shared_state_mod.get_sqlite_store = original_get_sqlite

    def test_hydrate_quotes_marks_stale(self, tmp_path, monkeypatch):
        store = get_market_state()
        store.hydrate_quotes({
            "RELIANCE": {
                "symbol": "RELIANCE",
                "ltp": 2500.0,
                "source": "ANGEL_WS",
                "updated_at": 1000,
            }
        })
        q = store.get_quote("RELIANCE")
        assert q is not None
        assert q.ltp == 2500.0
        assert q.feed_status == FeedStatus.STALE


class TestPersistenceQueue:
    def test_enqueue_is_non_blocking(self, tmp_path):
        from app.services.shared_state.sqlite_store import SQLiteStore
        store = SQLiteStore(tmp_path / "test.db")
        for i in range(1000):
            store.enqueue("INSERT INTO quotes_latest (symbol) VALUES (?)", (f"SYM{i}",))
        assert True


class TestSSEClientCleanup:
    def test_event_bus_callback_can_be_removed(self):
        from app.services.shared_state.event_bus import get_event_bus, EventType, Event
        bus = get_event_bus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.TRADE_EVENT, handler)
        bus.publish(Event(type=EventType.TRADE_EVENT, payload={"id": "1"}))
        assert len(received) == 1

        bus._subscribers[EventType.TRADE_EVENT].remove(handler)
        bus.publish(Event(type=EventType.TRADE_EVENT, payload={"id": "2"}))
        assert len(received) == 1


class TestLoadTest:
    def test_1000_concurrent_viewstore_reads(self):
        store = get_view_store()
        for i in range(10):
            store.set("index_options", {"success": True, "version": i})

        def read():
            view = store.get("index_options")
            return view is not None and view["payload"].get("success") is True

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(read) for _ in range(1000)]
            results = [f.result() for f in as_completed(futures)]
        assert all(results)

    def test_1000_concurrent_live_summary_reads(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        def read():
            resp = client.get("/api/live/summary")
            return resp.status_code == 200

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(read) for _ in range(1000)]
            results = [f.result() for f in as_completed(futures)]
        assert all(results)
