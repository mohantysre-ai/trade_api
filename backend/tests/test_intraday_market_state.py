import time

from app.services.intraday_market_state import (
    AngelIntradayStream,
    IntradayMarketState,
    IntradayUniverse,
)


def _tick(ltp: float, seq: int | None = None, close: float | None = None):
    message = {"last_traded_price": int(ltp * 100)}
    if seq is not None:
        message["sequenceNumber"] = seq
    if close is not None:
        message["closed_price"] = int(close * 100)
    return message


def _state() -> IntradayMarketState:
    rows = [
        {"symbol": "RELIANCE", "exchange": "NSE", "token": "2885",
         "tradingsymbol": "RELIANCE-EQ", "indexGroup": None, "active": True},
        {"symbol": "TCS", "exchange": "NSE", "token": "11536",
         "tradingsymbol": "TCS-EQ", "indexGroup": None, "active": True},
    ]
    state = IntradayMarketState(IntradayUniverse(rows))
    state.update_universe(state.universe)
    return state


def test_new_tick_updates_ltp_source_and_prev_close():
    state = _state()
    assert state.apply_tick("2885", 1, _tick(2432.25, seq=10, close=2430.0)) == "new"
    row = state.symbol_state("2885")
    assert row["ltp"] == 2432.25
    assert row["prevClose"] == 2430.0
    assert row["source"] == "ANGEL_WS"
    assert row["freshness"] == "LIVE"
    assert row["sequence"] == 10


def test_duplicate_and_older_sequence_ticks_are_rejected():
    state = _state()
    state.apply_tick("2885", 1, _tick(100.0, seq=5))
    assert state.apply_tick("2885", 1, _tick(90.0, seq=5)) == "duplicate"
    assert state.apply_tick("2885", 1, _tick(80.0, seq=4)) == "older"
    # LTP must never move backwards from a stale packet.
    assert state.symbol_state("2885")["ltp"] == 100.0


def test_latest_tick_wins_without_sequence():
    state = _state()
    state.apply_tick("2885", 1, _tick(100.0))
    state.apply_tick("2885", 1, _tick(105.0))
    assert state.symbol_state("2885")["ltp"] == 105.0


def test_invalid_ticks_are_rejected():
    state = _state()
    assert state.apply_tick("2885", 1, {"last_traded_price": 0}) == "invalid"
    assert state.apply_tick("2885", 1, None) == "invalid"
    assert state.apply_tick("", 1, {"ltp": 10}) == "invalid"
    assert state.symbol_state("2885") is None or state.symbol_state("2885")["ltp"] is None


def test_unknown_universe_ticks_do_not_create_state_rows():
    state = _state()

    assert state.apply_tick("999999", 1, _tick(100.0)) == "invalid"
    assert state.symbol_state("999999") is None


def test_per_symbol_freshness_and_stale_isolation():
    state = _state()
    state.apply_tick("2885", 1, _tick(100.0))
    state.apply_tick("11536", 1, _tick(200.0))
    state.set_connected(True)  # socket up, but one symbol stopped ticking
    with state._lock:
        state._state["11536"]["receivedMonotonic"] = time.monotonic() - 120
    assert state.freshness("2885") == "LIVE"
    assert state.freshness("11536") == "STALE"
    status = state.stream_status()
    assert status["symbolsLive"] == 1
    assert status["symbolsStale"] == 1
    assert status["feedStatus"] == "DEGRADED"
    # Only the stale symbol needs targeted recovery.
    stale = [row["symbol"] for row in state.stale_symbols()]
    assert stale == ["TCS"]


def test_diagnostic_block_handles_mapping_session_shapes():
    state = _state()
    session = {
        "sessionDate": "2026-09-13",
        "sessionStatus": "DEGRADED",
        "openPositions": {"LONG": [{"symbol": "RELIANCE"}], "SHORT": [{"symbol": "TCS"}]},
        "freeSlots": {"LONG": 3, "SHORT": 2},
    }

    block = state.diagnostic_block(session)

    assert "Locked        : 2" in block
    assert "Free Slots    : 5" in block


def test_capture_snapshot_is_immutable_vs_live_state():
    state = _state()
    state.apply_tick("2885", 1, _tick(100.0))
    snapshot = state.capture_snapshot()
    assert snapshot["generation"] == state.generation
    state.apply_tick("2885", 1, _tick(999.0))
    assert snapshot["quotes"]["RELIANCE"]["ltp"] == 100.0
    assert state.symbol_state("2885")["ltp"] == 999.0


def test_generation_increments_per_new_tick():
    state = _state()
    before = state.generation
    state.apply_tick("2885", 1, _tick(100.0, seq=1))
    state.apply_tick("2885", 1, _tick(101.0, seq=2))
    state.apply_tick("2885", 1, _tick(100.0, seq=2))  # duplicate: no bump
    assert state.generation == before + 2


def test_rest_recovery_seeds_and_ws_tick_rekeys_row():
    state = _state()
    assert state.apply_rest_quote("RELIANCE", {"ltp": 111.0}) is True
    row = state.symbol_state("RELIANCE")
    assert row["ltp"] == 111.0
    assert row["source"] == "ANGEL_REST_RECOVERY"
    # First WS tick re-keys the same row and restores WS authority.
    state.apply_tick("2885", 1, _tick(112.0))
    row = state.symbol_state("RELIANCE")
    assert row["ltp"] == 112.0
    assert row["source"] == "ANGEL_WS"
    assert state.ltp_source_mix().get("ANGEL_WS") == 1


class _FakeSdkSocket:
    def __init__(self):
        self.calls = []

    def subscribe(self, correlation_id, mode, token_list):
        self.calls.append((correlation_id, mode, token_list))


class _FailingSdkSocket(_FakeSdkSocket):
    def __init__(self):
        super().__init__()
        self.closed = False

    def subscribe(self, correlation_id, mode, token_list):
        raise RuntimeError("subscribe failed")

    def close_connection(self):
        self.closed = True


def test_failed_subscription_is_not_reported_as_connected():
    stream = AngelIntradayStream(_state())
    sdk = _FailingSdkSocket()
    stream._socket = sdk

    stream._on_open(sdk)

    assert sdk.closed is True
    assert stream.market_state.stream_status()["wsConnected"] is False


def test_stream_credentials_use_smartapi_token_attributes():
    class FakeSmart:
        access_token = "access"
        feed_token = "feed"

    class FakeClient:
        api_key = "api-key"
        client_id = "client-id"

        def connect(self):
            return FakeSmart()

    stream = AngelIntradayStream(_state())
    stream._client = FakeClient()

    assert stream._credentials() == ("access", "api-key", "client-id", "feed")


def test_no_subscription_churn_from_repeated_ensure_or_lock_events():
    stream = AngelIntradayStream(_state())
    stream._market_state.ensure_universe(loader=lambda: ([], "INTRADAY_750"))
    sdk = _FakeSdkSocket()
    stream._socket = sdk
    stream._opened = True
    stream._subscribe_desired(sdk)
    first = list(sdk.calls)
    # Locking/closing trades re-invokes ensure/subscribe with same universe.
    stream._subscribe_desired(sdk)
    assert sdk.calls == first
    assert len(first) == 1
    assert first[0][1] == 3  # SNAP_QUOTE mode
