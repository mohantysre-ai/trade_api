from datetime import datetime, timezone

from app.services import market_data_provider as provider


def test_nse_quote_is_normalized_to_existing_market_shape():
    quote = provider._nse_quote_to_canonical(
        {
            "lastPrice": 123.45,
            "open": 120,
            "dayHigh": 125,
            "dayLow": 119,
            "previousClose": 121,
            "totalTradedVolume": 999,
            "totalTradedValue": 123000,
            "pChange": 2.02,
        }
    )
    assert quote == {
        "ltp": 123.45,
        "open": 120,
        "high": 125,
        "low": 119,
        "close": 121,
        "tradeVolume": 999,
        "totalTradedValue": 123000,
        "percentChange": 2.02,
        "quoteProvider": "nse",
    }


def test_scanx_quote_is_normalized_without_credentials():
    quote = provider._dhan_quote_to_canonical(
        {"Sid": 3812, "Ltp": 102.28, "Pchange": 5.53, "PPerchange": 5.71, "Volume": 111249116}
    )
    assert quote == {
        "ltp": 102.28,
        "open": None,
        "high": None,
        "low": None,
        "close": 96.75,
        "tradeVolume": 111249116,
        "percentChange": 5.71,
        "securityId": "3812",
        "quoteProvider": "dhan_scanx",
    }


def test_quote_failover_fetches_only_symbols_missing_from_nse(monkeypatch):
    monkeypatch.setattr(
        provider,
        "fetch_nse500_quotes",
        lambda symbols: {"AAA": {"ltp": 10, "quoteProvider": "nse"}},
    )
    monkeypatch.setattr(
        provider,
        "fetch_dhan_bulk_quotes",
        lambda symbols: {"BBB": {"ltp": 20, "quoteProvider": "dhan"}},
    )
    requested = []

    def angel_fetch(symbols):
        requested.extend(symbols)
        return {}

    quotes, coverage = provider.fetch_quotes_with_failover(
        ["AAA", "BBB"], angel_fetch
    )
    assert requested == []
    assert set(quotes) == {"AAA", "BBB"}
    assert quotes["BBB"]["quoteProvider"] == "dhan"
    assert coverage.selection_allowed is True
    assert coverage.providers == {"nse": 1, "dhan": 1, "angel": 0}


def test_angel_receives_only_symbols_missing_from_nse_and_dhan(monkeypatch):
    monkeypatch.setattr(
        provider,
        "fetch_nse500_quotes",
        lambda symbols: {"AAA": {"ltp": 10, "quoteProvider": "nse"}},
    )
    monkeypatch.setattr(
        provider,
        "fetch_dhan_bulk_quotes",
        lambda symbols: {"BBB": {"ltp": 20, "quoteProvider": "dhan"}},
    )
    requested = []

    def angel_fetch(symbols):
        requested.extend(symbols)
        return {"CCC": {"ltp": 30}}

    quotes, coverage = provider.fetch_quotes_with_failover(
        ["AAA", "BBB", "CCC"], angel_fetch
    )
    assert requested == ["CCC"]
    assert set(quotes) == {"AAA", "BBB", "CCC"}
    assert coverage.providers == {"nse": 1, "dhan": 1, "angel": 1}


def test_quote_coverage_fails_closed(monkeypatch):
    monkeypatch.setattr(provider, "MARKET_DATA_MIN_COVERAGE_PCT", 99.0)
    monkeypatch.setattr(provider, "fetch_nse500_quotes", lambda symbols: {})
    monkeypatch.setattr(provider, "fetch_dhan_bulk_quotes", lambda symbols: {})
    quotes, coverage = provider.fetch_quotes_with_failover(
        ["AAA", "BBB", "CCC"], lambda symbols: {"AAA": {"ltp": 10}}
    )
    assert list(quotes) == ["AAA"]
    assert coverage.selection_allowed is False
    assert coverage.missing_symbols == ["BBB", "CCC"]


def test_dhan_chart_arrays_are_normalized(monkeypatch):
    monkeypatch.setenv("DHAN_CLIENT_ID", "client")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "token")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "timestamp": [1, 2],
                "open": [10, 11],
                "high": [12, 13],
                "low": [9, 10],
                "close": [11, 12],
                "volume": [100, 200],
            }

    monkeypatch.setattr(provider.requests, "post", lambda *args, **kwargs: Response())
    rows = provider.fetch_dhan_candles(
        "123",
        "FIVE_MINUTE",
        datetime(2026, 8, 14, 9, 15),
        datetime(2026, 8, 14, 9, 45),
    )
    assert rows == [[1, 10, 12, 9, 11, 100], [2, 11, 13, 10, 12, 200]]


def test_nse_daily_bars_map_to_screener_shape(monkeypatch):
    provider._NSE_CANDLE_CIRCUIT_UNTIL = 0.0
    monkeypatch.setattr(
        provider,
        "_nse_chart_get",
        lambda _params: {
            "status": True,
            "data": [
                {
                    "time": 1786924800000,
                    "open": 1314,
                    "high": 1314.1,
                    "low": 1298.1,
                    "close": 1300,
                    "volume": 2997335,
                }
            ],
        },
    )
    rows = provider.fetch_nse_candles(
        "RELIANCE",
        "2885",
        "ONE_DAY",
        datetime(2026, 7, 3, 9, 15),
        datetime(2026, 8, 17, 11, 9),
    )
    assert len(rows) == 1
    assert rows[0][0].startswith("2026-08-17")
    assert rows[0][1:] == [1314.0, 1314.1, 1298.1, 1300.0, 2997335.0]


def test_nse_intraday_drops_bars_outside_requested_window(monkeypatch):
    provider._NSE_CANDLE_CIRCUIT_UNTIL = 0.0
    monkeypatch.setattr(
        provider,
        "_nse_chart_get",
        lambda _params: {
            "status": True,
            "data": [
                {
                    "time": int(datetime(2026, 8, 14, 15, 28, tzinfo=timezone.utc).timestamp() * 1000),
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 10,
                },
                {
                    "time": int(datetime(2026, 8, 17, 9, 20, tzinfo=timezone.utc).timestamp() * 1000),
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                    "volume": 100,
                },
            ],
        },
    )
    rows = provider.fetch_nse_candles(
        "RELIANCE",
        "2885",
        "FIVE_MINUTE",
        datetime(2026, 8, 17, 9, 15, tzinfo=provider._IST_ZONE),
        datetime(2026, 8, 17, 11, 9, tzinfo=provider._IST_ZONE),
    )
    assert len(rows) == 1
    assert rows[0][0] == "2026-08-17 09:20:00"
    assert rows[0][1:] == [10.0, 11.0, 9.0, 10.5, 100.0]
