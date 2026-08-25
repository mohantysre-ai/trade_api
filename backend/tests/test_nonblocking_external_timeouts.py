import threading
import time

from app.services import angel_one_feed
from app.services import desk_ic_criteria


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_macro_refresh_returns_snapshot_immediately_while_worker_finishes(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()

    def slow_refresh(_client):
        started.set()
        release.wait(timeout=1)
        return {"success": True, "fresh": True}

    snapshot = {
        "updatedAt": "cached",
        "macroDataStrip": {"morning": []},
        "globalMacro": {"indices": [], "commodities": []},
    }
    monkeypatch.setattr(angel_one_feed, "_MACRO_REFRESH_LOCK", lock)
    monkeypatch.setattr(angel_one_feed, "_refresh_snapshot_macros_body", slow_refresh)
    monkeypatch.setattr(angel_one_feed, "_load_last_snapshot", lambda: snapshot)

    try:
        before = time.monotonic()
        result = angel_one_feed.refresh_snapshot_macros()
        elapsed = time.monotonic() - before
        assert started.wait(timeout=0.2)
        assert elapsed < 0.2
        assert result["accepted"] is True
        assert result["refreshScheduled"] is True
        assert result["payload"] == snapshot
        assert angel_one_feed.refresh_snapshot_macros()["busy"] is True
    finally:
        release.set()

    def lock_is_released():
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()
        return acquired

    assert _wait_until(lock_is_released)


def test_desk_ic_timeout_returns_deterministic_fallback_without_thread_pileup(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()

    def slow_llm(_fact_pack):
        started.set()
        release.wait(timeout=1)
        return {"deskDecision": "APPROVE", "criteria": []}

    monkeypatch.setattr(desk_ic_criteria, "_DESK_IC_LLM_LOCK", lock)
    monkeypatch.setattr(desk_ic_criteria, "DESK_IC_LLM_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(desk_ic_criteria, "_DESK_IC_LLM_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(desk_ic_criteria, "configured_llm_providers", lambda _purpose: ["fake"])
    monkeypatch.setattr(desk_ic_criteria, "_call_desk_ic_llm_inner", slow_llm)

    fact_pack = {"ticker": "TEST"}
    try:
        before = time.monotonic()
        assert desk_ic_criteria._call_desk_ic_llm(fact_pack) is None
        elapsed = time.monotonic() - before
        assert started.wait(timeout=0.2)
        assert elapsed < 0.2
        assert desk_ic_criteria._call_desk_ic_llm(fact_pack) is None
    finally:
        release.set()

    def lock_is_released():
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()
        return acquired

    assert _wait_until(lock_is_released)
