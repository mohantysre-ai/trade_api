from concurrent.futures import ThreadPoolExecutor
from threading import Event
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
