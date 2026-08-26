from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event
import threading
import time

from app.services import intraday_session_engine as intraday
from app.services import swing_session
from app.services import trade_outcome


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def test_intraday_live_response_refresh_does_not_block_concurrent_callers(monkeypatch):
    calls = []
    live_started = Event()
    release_live = Event()
    monkeypatch.setattr(intraday, "_schedule_stale_session_rotation", lambda existing=None: False)

    def compute(*, include_live=True, persist=False):
        calls.append((include_live, persist))
        if include_live:
            live_started.set()
            release_live.wait(timeout=1)
            symbol = "LIVE"
        else:
            symbol = "STALE"
        return {"locked": True, "long": [{"symbol": symbol}]}

    monkeypatch.setattr(intraday, "_compute_session", compute)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE", None)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE_AT", 0.0)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_REFRESHING", False)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_GEN", 0)
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: intraday.get_session(include_live=True), range(20)))

        assert live_started.wait(timeout=0.5)
        assert calls.count((False, False)) == 1
        assert calls.count((True, False)) == 1
        assert all(row["long"][0]["symbol"] == "STALE" for row in results)
        assert all(row["liveRefreshPending"] is True for row in results)
    finally:
        release_live.set()

    assert _wait_until(lambda: not intraday._SESSION_RESPONSE_REFRESHING)
    live = intraday.get_session(include_live=True)
    assert live["long"][0]["symbol"] == "LIVE"


def test_stale_intraday_rotation_is_background_and_coalesced(monkeypatch):
    started = Event()
    release = Event()
    calls: list[str] = []

    def ensure():
        calls.append("ensure")
        started.set()
        release.wait(timeout=1)
        return {"locked": True, "sessionDate": "2026-08-26", "long": [], "short": []}

    monkeypatch.setattr(intraday, "_ist_now", lambda: datetime(2026, 8, 26, 10, 0))
    monkeypatch.setattr(intraday, "basket_lock_allowed", lambda: (True, "primary_window"))
    monkeypatch.setattr(intraday, "ensure_intraday_session_locked", ensure)
    monkeypatch.setattr(intraday, "refresh_session_state", lambda: {"locked": True})
    monkeypatch.setattr(intraday, "_SESSION_ROTATION_LOCK", threading.Lock())
    monkeypatch.setattr(intraday, "_SESSION_ROTATION_ATTEMPT_AT", 0.0)
    stale = {"locked": True, "sessionDate": "2026-08-25"}
    try:
        assert intraday._schedule_stale_session_rotation(stale) is True
        assert started.wait(timeout=0.2)
        assert intraday._schedule_stale_session_rotation(stale) is True
        assert calls == ["ensure"]
    finally:
        release.set()

    assert _wait_until(lambda: not intraday._SESSION_ROTATION_LOCK.locked())


def test_current_day_cash_lock_is_a_valid_intraday_session(monkeypatch):
    current = {"locked": True, "sessionDate": "2026-08-26", "long": [], "short": [], "cashHeld": True}
    monkeypatch.setattr(intraday, "load_session", lambda: current)
    monkeypatch.setattr(intraday, "_ist_now", lambda: datetime(2026, 8, 26, 10, 0))
    monkeypatch.setattr(intraday, "commit_session", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not recommit")))
    assert intraday.ensure_intraday_session_locked() == current


def test_swing_live_response_refresh_does_not_block_concurrent_callers(monkeypatch):
    calls = []
    live_started = Event()
    release_live = Event()

    def compute(*, live=False):
        calls.append(live)
        if live:
            live_started.set()
            release_live.wait(timeout=1)
            symbol = "LIVE"
        else:
            symbol = "STALE"
        return {"locked": True, "long": [{"symbol": symbol}], "live": live}

    monkeypatch.setattr(swing_session, "_compute_swing_session", compute)
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_CACHE", None)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_CACHE_AT", 0.0)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_REFRESHING", False)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_GEN", 0)
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: swing_session.get_swing_session(live=True), range(20)))

        assert live_started.wait(timeout=0.5)
        assert calls.count(False) == 1
        assert calls.count(True) == 1
        assert all(row["long"][0]["symbol"] == "STALE" for row in results)
        assert all(row["liveRefreshPending"] is True for row in results)
    finally:
        release_live.set()

    assert _wait_until(lambda: not swing_session._SWING_RESPONSE_REFRESHING)
    live = swing_session.get_swing_session(live=True)
    assert live["long"][0]["symbol"] == "LIVE"
    live["long"][0]["symbol"] = "MUTATED"
    assert swing_session.get_swing_session(live=True)["long"][0]["symbol"] == "LIVE"


def test_live_book_refresh_does_not_block_concurrent_callers(monkeypatch):
    calls = []
    live_started = Event()
    release_live = Event()

    def compute(*, allow_external=True, persist_transitions=True):
        calls.append(allow_external)
        if allow_external:
            live_started.set()
            release_live.wait(timeout=1)
            symbol = "LIVE"
        else:
            symbol = "STALE"
        return {"long": [{"symbol": symbol}], "short": [], "dataStale": not allow_external}

    monkeypatch.setattr(trade_outcome, "_compute_live_prices_for_plan", compute)
    monkeypatch.setattr(trade_outcome, "_is_market_open", lambda: True)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE", None)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE_AT", 0.0)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE_REFRESHING", False)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE_GEN", 0)
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: trade_outcome.get_live_prices_for_plan(), range(20)))

        assert live_started.wait(timeout=0.5)
        assert calls.count(False) == 1
        assert calls.count(True) == 1
        assert all(row["long"][0]["symbol"] == "STALE" for row in results)
    finally:
        release_live.set()

    assert _wait_until(lambda: not trade_outcome._LIVE_BOOK_CACHE_REFRESHING)
    assert trade_outcome.get_live_prices_for_plan()["long"][0]["symbol"] == "LIVE"


def test_intraday_stale_refresh_does_not_replace_post_lock_payload(monkeypatch):
    live_started = Event()
    release_live = Event()
    monkeypatch.setattr(intraday, "_schedule_stale_session_rotation", lambda existing=None: False)

    def compute(*, include_live=True, persist=False):
        if persist:
            return {"locked": True, "long": [{"symbol": "POSTLOCK"}]}
        if include_live:
            live_started.set()
            release_live.wait(timeout=1)
            return {"locked": True, "long": [{"symbol": "PRELOCK"}]}
        return {"locked": True, "long": [{"symbol": "DISK"}]}

    monkeypatch.setattr(intraday, "_compute_session", compute)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE", None)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE_AT", 0.0)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_REFRESHING", False)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_GEN", 0)
    try:
        pending = intraday.get_session(include_live=True)
        assert live_started.wait(timeout=0.5)
        assert pending["long"][0]["symbol"] == "DISK"
        published = intraday.refresh_session_state()
        assert published["long"][0]["symbol"] == "POSTLOCK"
    finally:
        release_live.set()

    assert _wait_until(lambda: not intraday._SESSION_RESPONSE_REFRESHING)
    assert intraday.get_session(include_live=True)["long"][0]["symbol"] == "POSTLOCK"


def test_intraday_stale_refresh_does_not_replace_after_save_session(monkeypatch):
    live_started = Event()
    release_live = Event()
    monkeypatch.setattr(intraday, "_schedule_stale_session_rotation", lambda existing=None: False)

    def compute(*, include_live=True, persist=False):
        if include_live:
            live_started.set()
            release_live.wait(timeout=1)
            return {"locked": True, "long": [{"symbol": "PRELOCK"}]}
        return {"locked": True, "long": [{"symbol": "DISK"}]}

    monkeypatch.setattr(intraday, "_compute_session", compute)
    monkeypatch.setattr(intraday, "_atomic_write", lambda *args, **kwargs: None)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE", None)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE_AT", 0.0)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_REFRESHING", False)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_GEN", 0)
    monkeypatch.setattr(trade_outcome, "invalidate_live_book_cache", lambda: None)
    try:
        intraday.get_session(include_live=True)
        assert live_started.wait(timeout=0.5)
        intraday.save_session({"locked": True, "long": [{"symbol": "POSTLOCK"}]})
    finally:
        release_live.set()

    assert _wait_until(lambda: not intraday._SESSION_RESPONSE_REFRESHING)
    cached = intraday._SESSION_RESPONSE_CACHE
    assert cached is None or cached["long"][0]["symbol"] != "PRELOCK"


def test_swing_stale_refresh_does_not_replace_post_lock_payload(monkeypatch, tmp_path):
    live_started = Event()
    release_live = Event()

    def compute(*, live=False):
        if live:
            live_started.set()
            release_live.wait(timeout=1)
            return {"locked": True, "long": [{"symbol": "PRELOCK"}]}
        return {"locked": True, "long": [{"symbol": "DISK"}]}

    monkeypatch.setattr(swing_session, "_compute_swing_session", compute)
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_CACHE", None)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_CACHE_AT", 0.0)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_REFRESHING", False)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_GEN", 0)
    try:
        pending = swing_session.get_swing_session(live=True)
        assert live_started.wait(timeout=0.5)
        assert pending["long"][0]["symbol"] == "DISK"
        swing_session._atomic_write(str(tmp_path / "swing_session.json"), {"locked": True})
    finally:
        release_live.set()

    assert _wait_until(lambda: not swing_session._SWING_RESPONSE_REFRESHING)
    cached = swing_session._SWING_RESPONSE_CACHE
    assert cached is None or cached["long"][0]["symbol"] != "PRELOCK"


def test_live_book_stale_refresh_does_not_replace_after_invalidate(monkeypatch):
    live_started = Event()
    release_live = Event()

    def compute(*, allow_external=True, persist_transitions=True):
        if allow_external:
            live_started.set()
            release_live.wait(timeout=1)
            return {"long": [{"symbol": "PRELOCK"}], "short": []}
        return {"long": [{"symbol": "DISK"}], "short": []}

    monkeypatch.setattr(trade_outcome, "_compute_live_prices_for_plan", compute)
    monkeypatch.setattr(trade_outcome, "_is_market_open", lambda: True)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE", None)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE_AT", 0.0)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE_REFRESHING", False)
    monkeypatch.setattr(trade_outcome, "_LIVE_BOOK_CACHE_GEN", 0)
    try:
        trade_outcome.get_live_prices_for_plan()
        assert live_started.wait(timeout=0.5)
        trade_outcome.invalidate_live_book_cache()
    finally:
        release_live.set()

    assert _wait_until(lambda: not trade_outcome._LIVE_BOOK_CACHE_REFRESHING)
    cached = trade_outcome._LIVE_BOOK_CACHE
    assert cached is None or cached["long"][0]["symbol"] != "PRELOCK"
