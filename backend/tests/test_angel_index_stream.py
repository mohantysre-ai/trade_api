import time

import pytest

from app.services.angel_index_stream import AngelIndexStream


class _FakeSdkSocket:
    def __init__(self):
        self.calls = []
        self.unsubscribed = []

    def subscribe(self, correlation_id, mode, token_list):
        self.calls.append((correlation_id, mode, token_list))

    def unsubscribe(self, correlation_id, mode, token_list):
        self.unsubscribed.append((correlation_id, mode, token_list))


class _FakeClient:
    def connect(self):
        return self


class _LiveWorker:
    def is_alive(self):
        return True


def _open_stream():
    stream = AngelIndexStream()
    stream._thread = _LiveWorker()
    socket = _FakeSdkSocket()
    stream._socket = socket
    stream._opened = True
    return stream, socket


def test_open_subscribes_through_sdk_wrapper_not_websocket_app():
    stream = AngelIndexStream()
    stream._wanted[(1, "99926000")] = {
        "exchange": "NSE", "token": "99926000", "indexKey": "NIFTY", "kind": "INDEX",
    }
    sdk = _FakeSdkSocket()
    stream._socket = sdk

    stream._on_open(sdk)

    assert sdk.calls == [
        ("sigqixopt", 3, [{"exchangeType": 1, "tokens": ["99926000"]}])
    ]


def test_subscription_is_deferred_until_current_socket_is_open():
    stream = AngelIndexStream()
    stream._wanted[(1, "99926000")] = {
        "exchange": "NSE", "token": "99926000", "indexKey": "NIFTY", "kind": "INDEX",
    }
    sdk = _FakeSdkSocket()
    stream._socket = sdk

    stream._subscribe_missing(sdk)

    assert sdk.calls == []


def test_retained_contract_stays_subscribed_until_the_last_owner_closes():
    stream, socket = _open_stream()
    client = _FakeClient()
    instrument = {"exchange": "NFO", "token": "111"}
    assert stream.retain(client, [instrument], owner="paper:A") == 1
    assert stream.retain(client, [instrument], owner="paper:B") == 1
    assert stream.retained_owners() == {"paper:A": 1, "paper:B": 1}
    assert (2, "111") in stream._wanted

    stream.retain(client, [instrument], owner="paper:B")  # idempotent on reconnect
    assert stream.retained_owners() == {"paper:A": 1, "paper:B": 1}
    assert len(socket.calls) == 1

    assert stream.release_owner("paper:A") == 0
    assert (2, "111") in stream._wanted
    assert socket.unsubscribed == []

    assert stream.release_owner("paper:B") == 1
    assert (2, "111") not in stream._wanted
    assert socket.unsubscribed == [("sigqixopt", 3, [{"exchangeType": 2, "tokens": ["111"]}])]


def test_release_never_unsubscribes_a_contract_held_open_by_another_owner():
    stream, socket = _open_stream()
    client = _FakeClient()
    stream.retain(client, [{"exchange": "NSE", "token": "99926000"}], owner="paper:A")
    stream.retain(client, [{"exchange": "NSE", "token": "99926001"}], owner="paper:B")

    assert stream.release_owner("paper:A") == 1
    assert socket.unsubscribed == [("sigqixopt", 3, [{"exchangeType": 1, "tokens": ["99926000"]}])]
    assert (1, "99926001") in stream._wanted
    assert stream.retained_owners() == {"paper:B": 1}


def test_radar_ensured_contract_is_never_dropped_by_position_release():
    stream, socket = _open_stream()
    client = _FakeClient()
    stream.ensure(client, [{"exchange": "NSE", "token": "99926000", "indexKey": "NIFTY", "kind": "INDEX"}])
    stream.retain(client, [{"exchange": "NSE", "token": "99926000"}], owner="paper:A")

    assert stream.release_owner("paper:A") == 0
    assert (1, "99926000") in stream._wanted
    assert socket.unsubscribed == []


def test_quote_row_reports_age_while_quote_enforces_the_ttl():
    stream = AngelIndexStream()
    stream._quotes["111"] = {
        "ltp": 100.0,
        "receivedAt": "2026-09-01T05:30:00+00:00",
        "receivedEpoch": time.time() - 30.0,
        "source": "ANGEL_WEBSOCKET",
    }
    row = stream.quote_row("111")
    assert row is not None
    assert row["ltp"] == 100.0
    assert row["ageSeconds"] == pytest.approx(30.0, abs=0.5)
    assert row["stale"] is False
    assert stream.quote("111", max_age_seconds=12.0) is None
    assert stream.quote("111", max_age_seconds=600.0) is not None
    assert stream.quote_row("999") is None


def test_stream_tick_updates_quote_and_local_five_minute_bar():
    stream = AngelIndexStream()
    stream._wanted[(1, "99926000")] = {
        "exchange": "NSE", "token": "99926000", "indexKey": "NIFTY", "kind": "INDEX",
    }
    stream._on_data({"exchange_type": 1, "token": "99926000", "last_traded_price": 2432250,
                     "open_interest": 1200, "volume_trade_for_the_day": 50, "closed_price": 2430000,
                     "best_5_buy_data": [{"price": 2432200}], "best_5_sell_data": [{"price": 2432300}]})
    quote = stream.quote("99926000")
    assert quote is not None
    assert quote["ltp"] == 24322.5
    assert quote["opnInterest"] == 1200
    assert quote["close"] == 24300
    assert quote["bestBidPrice"] == 24322
    assert quote["bestAskPrice"] == 24323
    bars = stream.candles("NIFTY")
    assert len(bars) == 1
    assert bars[0][1:5] == [24322.5, 24322.5, 24322.5, 24322.5]
