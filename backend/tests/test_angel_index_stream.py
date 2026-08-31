from app.services.angel_index_stream import AngelIndexStream


class _FakeSdkSocket:
    def __init__(self):
        self.calls = []

    def subscribe(self, correlation_id, mode, token_list):
        self.calls.append((correlation_id, mode, token_list))


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
