import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import angel_one_feed as feed


def test_market_snapshot_loader_parses_once_for_same_mtime(tmp_path, monkeypatch):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"success": True, "stocks": [], "updatedAt": "2026-08-28T09:00:00+00:00"}), encoding="utf-8")
    monkeypatch.setattr(feed, "_snapshot_path", lambda: snap)
    monkeypatch.setattr(feed, "_normalize_snapshot", lambda payload: payload)
    feed._MARKET_SNAPSHOT_MEMORY = None
    feed._MARKET_SNAPSHOT_MEMORY_PATH = None
    feed._MARKET_SNAPSHOT_MEMORY_MTIME_NS = None

    original = Path.read_text
    calls = {"n": 0}

    def counted(self, *args, **kwargs):
        if self == snap:
            calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    with ThreadPoolExecutor(max_workers=32) as executor:
        rows = list(executor.map(lambda _: feed._load_last_snapshot(), range(200)))
    assert all(row and row["success"] for row in rows)
    assert calls["n"] == 1


def test_market_snapshot_loader_invalidates_on_file_change(tmp_path, monkeypatch):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps({"success": True, "version": 1}), encoding="utf-8")
    monkeypatch.setattr(feed, "_snapshot_path", lambda: snap)
    monkeypatch.setattr(feed, "_normalize_snapshot", lambda payload: payload)
    feed._MARKET_SNAPSHOT_MEMORY = None
    feed._MARKET_SNAPSHOT_MEMORY_PATH = None
    feed._MARKET_SNAPSHOT_MEMORY_MTIME_NS = None
    assert feed._load_last_snapshot()["version"] == 1
    snap.write_text(json.dumps({"success": True, "version": 2, "padding": "changed"}), encoding="utf-8")
    assert feed._load_last_snapshot()["version"] == 2
