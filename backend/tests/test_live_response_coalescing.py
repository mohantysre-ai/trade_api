from concurrent.futures import ThreadPoolExecutor
import time

from app.services import intraday_session_engine as intraday
from app.services import swing_session


def test_intraday_live_response_is_computed_once_for_concurrent_callers(monkeypatch):
    calls = 0

    def compute(*, include_live=True, persist=False):
        nonlocal calls
        calls += 1
        time.sleep(0.03)
        return {"locked": True, "long": [{"symbol": "TEST"}], "includeLive": include_live, "persist": persist}

    monkeypatch.setattr(intraday, "_compute_session", compute)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE", None)
    monkeypatch.setattr(intraday, "_SESSION_RESPONSE_CACHE_AT", 0.0)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: intraday.get_session(include_live=True), range(20)))

    assert calls == 1
    assert all(row["long"][0]["symbol"] == "TEST" for row in results)
    results[0]["long"][0]["symbol"] = "MUTATED"
    assert results[1]["long"][0]["symbol"] == "TEST"


def test_swing_live_response_is_computed_once_for_concurrent_callers(monkeypatch):
    calls = 0

    def compute(*, live=False):
        nonlocal calls
        calls += 1
        time.sleep(0.03)
        return {"locked": True, "long": [{"symbol": "TEST"}], "live": live}

    monkeypatch.setattr(swing_session, "_compute_swing_session", compute)
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_CACHE", None)
    monkeypatch.setattr(swing_session, "_SWING_RESPONSE_CACHE_AT", 0.0)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: swing_session.get_swing_session(live=True), range(20)))

    assert calls == 1
    assert all(row["long"][0]["symbol"] == "TEST" for row in results)
    results[0]["long"][0]["symbol"] = "MUTATED"
    assert results[1]["long"][0]["symbol"] == "TEST"
