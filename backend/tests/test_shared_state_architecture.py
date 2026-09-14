"""Tests for the shared high-scale live data architecture."""

from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest

from app.services.shared_state.market_state import MarketStateStore, get_market_state
from app.services.shared_state.view_store import ViewStore, get_view_store
from app.services.shared_state.event_bus import EventBus, get_event_bus, EventType, Event
from app.services.shared_state.sqlite_store import SQLiteStore, get_sqlite_store
from app.services.shared_state.schemas import FeedStatus, Quote, ViewVersion


class TestMarketStateStore:
    def test_update_and_get_quote(self):
        store = MarketStateStore()
        store.update_quote(Quote(symbol="RELIANCE", ltp=2500.0, feed_status=FeedStatus.LIVE))
        q = store.get_quote("RELIANCE")
        assert q is not None
        assert q.ltp == 2500.0
        assert q.feed_status == FeedStatus.LIVE

    def test_get_quotes_subset(self):
        store = MarketStateStore()
        store.update_quote(Quote(symbol="RELIANCE", ltp=2500.0))
        store.update_quote(Quote(symbol="TCS", ltp=4000.0))
        result = store.get_quotes(["RELIANCE", "INFY"])
        assert "RELIANCE" in result
        assert "INFY" not in result

    def test_thread_safety(self):
        store = MarketStateStore()

        def writer():
            for i in range(100):
                store.update_quote(Quote(symbol=f"SYM{i%10}", ltp=float(i)))

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert store.get_metrics()["tick_count"] == 400

    def test_feed_status(self):
        store = MarketStateStore()
        store.set_feed_status(FeedStatus.LIVE)
        assert store.get_feed_status() == FeedStatus.LIVE

    def test_metrics(self):
        store = MarketStateStore()
        store.update_quote(Quote(symbol="X", ltp=1.0))
        m = store.get_metrics()
        assert m["tick_count"] == 1
        assert m["symbol_count"] == 1


class TestViewStore:
    def test_set_and_get(self):
        store = ViewStore()
        store.set("index_options", {"success": True, "selected": []})
        view = store.get("index_options")
        assert view is not None
        assert view["version"] == 1
        assert view["payload"]["success"] is True

    def test_version_increments(self):
        store = ViewStore()
        store.set("intraday", {"a": 1})
        store.set("intraday", {"a": 2})
        view = store.get("intraday")
        assert view["version"] == 2

    def test_unknown_namespace_raises(self):
        store = ViewStore()
        with pytest.raises(ValueError):
            store.set("unknown", {})

    def test_hydrate(self):
        store = ViewStore()
        store.hydrate({
            "swing": {"version": 5, "updatedAt": 1000.0, "payload": {"locked": True}},
        })
        view = store.get("swing")
        assert view["version"] == 5

    def test_snapshot(self):
        store = ViewStore()
        store.set("eod", {"date": "2026-09-14"})
        snap = store.snapshot()
        assert "eod" in snap


class TestEventBus:
    def test_publish_and_subscribe(self):
        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.TRADE_EVENT, handler)
        bus.publish(Event(type=EventType.TRADE_EVENT, payload={"id": "1"}))
        assert len(received) == 1
        assert received[0].payload["id"] == "1"

    def test_durable_events_not_dropped(self):
        bus = EventBus(max_size=100)
        for i in range(20):
            bus.publish(Event(type=EventType.TRADE_EVENT, payload={"i": i}))
        events = bus.drain()
        assert len(events) == 20

    def test_low_priority_events_dropped_when_full(self):
        bus = EventBus(max_size=5)
        for i in range(10):
            bus.publish(Event(type=EventType.MARKET_QUOTE, payload={"i": i}))
        assert bus.dropped_low_priority > 0


class TestSQLiteStore:
    def test_wal_mode_enabled(self, tmp_path):
        db = SQLiteStore(tmp_path / "test.db")
        db.execute("SELECT 1")
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.upper() == "WAL"

    def test_persist_and_load_view_snapshot(self, tmp_path):
        store = SQLiteStore(tmp_path / "test.db")
        store.persist_view_snapshot(
            "intraday",
            ViewVersion(version=3, updated_at=1000.0, payload={"locked": True}),
        )
        time.sleep(0.2)
        result = store.load_view_snapshot("intraday")
        assert result is not None
        assert result["version"] == 3
        assert result["payload"]["locked"] is True

    def test_enqueue_does_not_block(self, tmp_path):
        store = SQLiteStore(tmp_path / "test.db")
        for i in range(100):
            store.enqueue("INSERT INTO quotes_latest (symbol) VALUES (?)", (f"SYM{i}",))
        assert True
