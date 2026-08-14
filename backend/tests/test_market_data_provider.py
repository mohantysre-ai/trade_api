from datetime import datetime

from app.services import market_data_provider as provider


def test_dhan_quote_is_normalized_to_existing_market_shape():
    quote = provider._dhan_quote_to_canonical(
        {
            "last_price": 123.45,
            "volume": 999,
            "oi": 42,
            "ohlc": {"open": 120, "high": 125, "low": 119, "close": 121},
        }
    )
    assert quote == {
        "ltp": 123.45,
        "open": 120,
        "high": 125,
        "low": 119,
        "close": 121,
        "tradeVolume": 999,
        "opnInterest": 42,
        "previousOI": 0,
        "quoteProvider": "dhan",
    }


def test_quote_failover_fetches_only_symbols_missing_from_dhan(monkeypatch):
    monkeypatch.setattr(
        provider,
        "fetch_dhan_bulk_quotes",
        lambda symbols: {"AAA": {"ltp": 10, "quoteProvider": "dhan"}},
    )
    requested = []

    def angel_fetch(symbols):
        requested.extend(symbols)
        return {"BBB": {"ltp": 20}}

    quotes, coverage = provider.fetch_quotes_with_failover(
        ["AAA", "BBB"], angel_fetch
    )
    assert requested == ["BBB"]
    assert set(quotes) == {"AAA", "BBB"}
    assert quotes["BBB"]["quoteProvider"] == "angel"
    assert coverage.selection_allowed is True
    assert coverage.providers == {"dhan": 1, "angel": 1}


def test_quote_coverage_fails_closed(monkeypatch):
    monkeypatch.setattr(provider, "MARKET_DATA_MIN_COVERAGE_PCT", 99.0)
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
