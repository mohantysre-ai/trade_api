import threading
import time

import pytest

from app.services import angel_one_feed as feed


def _reset_gates() -> None:
    feed._ANGEL_CANDLE_CIRCUIT_UNTIL = 0.0
    feed._CANDLE_COOLDOWN_UNTIL_MONO = 0.0
    feed._CANDLE_LAST_CALL_MONO = 0.0
    feed._ANGEL_LAST_CALL_BY_CLASS.clear()
    feed._ANGEL_COOLDOWN_BY_CLASS.clear()
    feed._ANGEL_LAST_CALL_ANY_MONO = 0.0
    feed._ANGEL_TRIP_COUNT = 0
    feed._ANGEL_LAST_TRIP_AT_MONO = 0.0
    feed._ANGEL_GATE_STATS.clear()
    feed._ANGEL_LOGIN_LAST_AT_MONO = 0.0
    feed._ANGEL_LOGIN_COUNT = 0


def test_batch_rate_limit_does_not_degrade_into_ltp_flood(monkeypatch):
    _reset_gates()
    monkeypatch.setattr(feed, "ANGEL_QUOTE_CIRCUIT_SECONDS", 1.0)

    class DummySmart:
        def __init__(self):
            self.ltp_calls = 0

        def getMarketData(self, *_args, **_kwargs):
            return {
                "status": False,
                "message": "Too many requests",
                "errorcode": "AB1021",
                "data": None,
            }

        def ltpData(self, *_args, **_kwargs):
            self.ltp_calls += 1
            return {"status": True, "data": {"ltp": 1}}

    from app.utils.symbols import Instrument

    instruments = [
        Instrument(f"S{i}", "NSE", f"S{i}-EQ", f"{1000 + i}", f"S{i}") for i in range(5)
    ]
    client = object.__new__(feed.AngelOneClient)
    dummy = DummySmart()
    monkeypatch.setattr(client, "connect", lambda: dummy)
    monkeypatch.setattr(client, "_is_auth_error", lambda _exc: False)

    fetched = feed._fetch_quote_chunk(dummy, instruments, {inst.token: inst.key for inst in instruments}, client)

    assert fetched == {}
    assert dummy.ltp_calls == 0
    assert feed._angel_candle_calls_allowed() is False


def test_rate_limit_pauses_all_products_and_then_recovers(monkeypatch):
    _reset_gates()
    monkeypatch.setattr(feed, "ANGEL_QUOTE_CIRCUIT_SECONDS", 1.0)

    class DummySmart:
        def getMarketData(self, *_args, **_kwargs):
            return {
                "status": False,
                "message": "Too many requests",
                "errorcode": "AB1021",
                "data": None,
            }

    from app.utils.symbols import Instrument

    inst = Instrument("S0", "NSE", "S0-EQ", "1000", "S0")
    client = object.__new__(feed.AngelOneClient)
    monkeypatch.setattr(client, "connect", lambda: DummySmart())
    monkeypatch.setattr(client, "_is_auth_error", lambda _exc: False)

    feed._fetch_quote_chunk(DummySmart(), [inst], {"1000": "S0"}, client)
    assert feed._ANGEL_COOLDOWN_BY_CLASS["marketdata"] > time.monotonic()
    assert feed._ANGEL_COOLDOWN_BY_CLASS["ltp"] > time.monotonic()
    assert feed._ANGEL_COOLDOWN_BY_CLASS["greeks"] > time.monotonic()
    assert feed._CANDLE_COOLDOWN_UNTIL_MONO > time.monotonic()

    feed._ANGEL_COOLDOWN_BY_CLASS.clear()
    feed._CANDLE_COOLDOWN_UNTIL_MONO = 0.0
    assert feed._angel_candle_calls_allowed() is True


def test_batch_quotes_wait_out_rate_limit_pause(monkeypatch):
    _reset_gates()
    feed._ANGEL_COOLDOWN_BY_CLASS["marketdata"] = time.monotonic() + 1.0

    calls: list[float] = []

    class DummySmart:
        def getMarketData(self, *_args, **_kwargs):
            calls.append(time.monotonic())
            return {"status": True, "data": {"fetched": []}}

    from app.utils.symbols import Instrument

    inst = Instrument("S0", "NSE", "S0-EQ", "1000", "S0")
    started = time.monotonic()
    result = feed._fetch_quote_chunk(DummySmart(), [inst], {"1000": "S0"}, None)
    assert result == {}
    assert len(calls) == 1
    assert calls[0] - started >= 0.9


def test_concurrent_callers_are_serialized_and_paced(monkeypatch):
    _reset_gates()
    intervals: list[float] = []
    lock = threading.Lock()

    class DummySmart:
        def getMarketData(self, *_args, **_kwargs):
            with lock:
                intervals.append(time.monotonic())
            return {"status": True, "data": {"fetched": []}}

    from app.utils.symbols import Instrument

    instruments = [
        Instrument(f"S{i}", "NSE", f"S{i}-EQ", f"{1000 + i}", f"S{i}") for i in range(4)
    ]
    token_to_key = {inst.token: inst.key for inst in instruments}
    errors: list[Exception] = []

    def worker(idx: int) -> None:
        try:
            feed._fetch_quote_chunk(
                DummySmart(),
                [instruments[idx]],
                {instruments[idx].token: instruments[idx].key},
                None,
            )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(intervals) == 4
    gaps = [b - a for a, b in zip(intervals, intervals[1:])]
    assert all(gap >= feed.ANGEL_MARKETDATA_MIN_INTERVAL_SECONDS - 0.15 for gap in gaps)


def test_gate_wait_deadline_fails_fast(monkeypatch):
    _reset_gates()
    feed._ANGEL_COOLDOWN_BY_CLASS["marketdata"] = time.monotonic() + 30.0

    started = time.monotonic()
    with pytest.raises(feed.AngelGateTimeout):
        with feed._angel_marketdata_gate(deadline=1.0):
            pass
    assert time.monotonic() - started < 5.0


def test_gate_wedged_upstream_does_not_block_other_callers(monkeypatch):
    _reset_gates()

    class WedgedSmart:
        def getMarketData(self, *_a, **_k):
            time.sleep(8.0)
            return {"status": True, "data": {"fetched": []}}

    from app.utils.symbols import Instrument

    inst = Instrument("S0", "NSE", "S0-EQ", "1000", "S0")
    slow_result: list = []

    def slow_caller():
        slow_result.append(
            feed._fetch_quote_chunk(WedgedSmart(), [inst], {"1000": "S0"}, None, deadline=30.0)
        )

    thread = threading.Thread(target=slow_caller, daemon=True)
    thread.start()
    time.sleep(0.4)
    started = time.monotonic()
    with pytest.raises(feed.AngelGateTimeout):
        with feed._angel_marketdata_gate(deadline=1.0):
            pass
    assert time.monotonic() - started < 4.0
    thread.join(timeout=15)
    assert slow_result


def test_cooldown_rechecked_before_fire(monkeypatch):
    _reset_gates()
    feed._ANGEL_COOLDOWN_BY_CLASS["marketdata"] = time.monotonic() + 2.0
    calls: list[float] = []

    class DummySmart:
        def getMarketData(self, *_a, **_k):
            calls.append(time.monotonic())
            return {"status": True, "data": {"fetched": []}}

    def trip_mid_wait():
        time.sleep(0.3)
        feed._trip_angel_quote_circuit(3.0)

    threading.Thread(target=trip_mid_wait, daemon=True).start()
    raised = False
    try:
        # 2.5s deadline cannot absorb the mid-wait trip (cooldown now runs to
        # ~3.3s): the request must fail fast, not fire late and stale.
        with feed._angel_marketdata_gate(deadline=2.5):
            DummySmart().getMarketData()
    except feed.AngelGateTimeout:
        raised = True
    assert raised and not calls, "request must not fire through a cooldown tripped mid-wait"


def test_auth_error_does_not_trip_rate_limit_circuit():
    _reset_gates()
    assert feed._is_angel_rate_limited(RuntimeError("Invalid token: session expired")) is False
    assert feed._is_angel_rate_limited(RuntimeError("connection read timed out")) is False
    assert feed._is_angel_rate_limited({"status": False, "errorcode": "AB1004", "message": "Access Denied"}) is False
    assert not feed._ANGEL_COOLDOWN_BY_CLASS

def test_timeout_exception_does_not_trip_circuit(monkeypatch):
    _reset_gates()

    class TimeoutSmart:
        def getMarketData(self, *_a, **_k):
            raise RuntimeError("Read timed out")

    from app.utils.symbols import Instrument

    inst = Instrument("S0", "NSE", "S0-EQ", "1000", "S0")
    monkeypatch.setenv("ANGEL_MARKETDATA_ATTEMPTS", "1")
    fetched = feed._fetch_quote_chunk(TimeoutSmart(), [inst], {"1000": "S0"}, None, deadline=3.0)
    assert fetched == {}
    assert not feed._ANGEL_COOLDOWN_BY_CLASS, "network timeout must not open the AB1021 cooldown"


def test_partial_batch_is_counted_not_zero_filled(monkeypatch):
    _reset_gates()

    class PartialSmart:
        def getMarketData(self, *_a, **_k):
            return {
                "status": True,
                "data": {"fetched": [{"symbolToken": "1000", "ltp": 10.0}]},
            }

        def ltpData(self, *_a, **_k):
            return {"status": False}

    from app.utils.symbols import Instrument

    insts = [
        Instrument("A", "NSE", "A-EQ", "1000", "A"),
        Instrument("B", "NSE", "B-EQ", "2000", "B"),
    ]
    fetched = feed._fetch_quote_chunk(PartialSmart(), insts, {i.token: i.key for i in insts}, None)
    assert set(fetched) == {"A"}
    stats = feed._ANGEL_GATE_STATS["marketdata"]
    assert stats["partialBatchesTotal"] == 1
    assert stats["requestedTokensTotal"] == 2
    assert stats["returnedTokensTotal"] == 1


def test_zero_ltp_row_marked_stale():
    from app.utils.symbols import Instrument

    row = feed._build_stock_row(
        Instrument("A", "NSE", "A-EQ", "1000", "A"),
        {"ltp": 0, "close": 0},
        "TEST",
    )
    assert row["fresh"] is False
    assert row["staleReason"] == "zero_or_missing_ltp"


def test_concurrent_login_is_serialized_and_paced(monkeypatch):
    _reset_gates()
    login_times: list[float] = []
    lock = threading.Lock()

    class FakeSmart:
        def __init__(self, *_a, **_k):
            pass

        def generateSession(self, *_a, **_k):
            with lock:
                login_times.append(time.monotonic())
            return {"status": True, "data": {}}

    monkeypatch.setattr(feed, "SmartConnect", FakeSmart)
    monkeypatch.setattr(feed, "ANGEL_LOGIN_MIN_INTERVAL_SECONDS", 0.5)
    clients = []
    for _ in range(4):
        c = object.__new__(feed.AngelOneClient)
        c.api_key = "k"
        c.client_id = "c"
        c.credential = "s"
        c.totp_secret = "JBSWY3DPEHPK3PXP"
        c._smart = None
        clients.append(c)

    threads = [threading.Thread(target=c.connect) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(login_times) == 4
    gaps = [b - a for a, b in zip(login_times, login_times[1:])]
    assert all(g >= 0.4 for g in gaps), f"logins not paced: {gaps}"


def test_repeated_trips_escalate_backoff(monkeypatch):
    _reset_gates()
    holds = [feed._next_quote_circuit_hold() for _ in range(4)]
    assert holds[1] > holds[0] * 1.2
    assert holds[2] > holds[1] * 1.2
    assert holds[3] <= feed.ANGEL_CIRCUIT_BACKOFF_CAP_SECONDS + 1.0


def test_marketdata_ltp_greeks_aggregate_rate_is_globally_bounded():
    _reset_gates()
    arrivals: list[float] = []
    lock = threading.Lock()
    min_global = feed.ANGEL_GLOBAL_MIN_INTERVAL_SECONDS - 0.12

    def caller(gate):
        with gate:
            with lock:
                arrivals.append(time.monotonic())

    threads = [
        threading.Thread(target=caller, args=(feed._angel_marketdata_gate(10.0),))
        for _ in range(3)
    ] + [
        threading.Thread(target=caller, args=(feed._angel_ltp_gate(10.0),))
        for _ in range(3)
    ] + [
        threading.Thread(target=caller, args=(feed._angel_greeks_gate(10.0),))
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    arrivals.sort()
    gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
    assert all(g >= min_global for g in gaps), f"global floor violated: {gaps}"


def test_greeks_gate_holds_for_all_callers(monkeypatch):
    _reset_gates()
    started: list[float] = []
    lock = threading.Lock()

    class DummySmart:
        def optionGreek(self, _params):
            with lock:
                started.append(time.monotonic())
            return {"status": True, "data": [{"iv": 1}]}

    client = object.__new__(feed.AngelOneClient)
    monkeypatch.setattr(client, "connect", lambda: DummySmart())
    monkeypatch.setattr(client, "_is_auth_error", lambda _exc: False)

    results: list[list] = []

    def run():
        results.append(client.fetch_option_greeks("NIFTY", "26SEP2026"))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert all(rows == [{"iv": 1}] for rows in results)
    assert started[1] - started[0] >= feed.ANGEL_GREEKS_MIN_INTERVAL_SECONDS - 0.15