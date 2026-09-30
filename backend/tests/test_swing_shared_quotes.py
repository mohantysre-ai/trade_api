import time

from app.services.shared_state import market_state as shared_market_state
from app.services.shared_state.market_state import MarketStateStore
from app.services.shared_state.schemas import FeedStatus, Quote
from app.services.swing_v2 import market_data


def test_latest_quotes_use_shared_live_feed_without_external_fetch(monkeypatch):
    store = MarketStateStore()
    store.update_quote(
        Quote(
            symbol="RELIANCE",
            ltp=2500.0,
            source="SHOONYA_WS",
            timestamp=time.time(),
            feed_status=FeedStatus.DEGRADED,
        )
    )
    monkeypatch.setattr(shared_market_state, "MARKET_STATE", store)

    def fail_external(*_args, **_kwargs):
        raise AssertionError("external quote provider must not run for a fresh shared quote")

    monkeypatch.setattr("app.services.market_data_provider.fetch_quotes_with_failover", fail_external)
    quotes = market_data.latest_quotes(["RELIANCE"])
    assert quotes["RELIANCE"]["ltp"] == 2500.0
    assert quotes["RELIANCE"]["quoteProvider"] == "SHOONYA_WS"


def test_latest_quotes_fetch_only_missing_shared_symbols(monkeypatch):
    store = MarketStateStore()
    store.update_quote(
        Quote(
            symbol="RELIANCE",
            ltp=2500.0,
            source="SHOONYA_WS",
            timestamp=time.time(),
            feed_status=FeedStatus.DEGRADED,
        )
    )
    monkeypatch.setattr(shared_market_state, "MARKET_STATE", store)
    requested = []

    def external(symbols, _angel):
        requested.extend(symbols)
        return {"TCS": {"ltp": 4000.0, "quoteProvider": "nse"}}, object()

    monkeypatch.setattr("app.services.market_data_provider.fetch_quotes_with_failover", external)
    quotes = market_data.latest_quotes(["RELIANCE", "TCS"])
    assert requested == ["TCS"]
    assert set(quotes) == {"RELIANCE", "TCS"}


def test_hydrated_stale_quote_is_not_used_for_swing(monkeypatch):
    store = MarketStateStore()
    store.hydrate_quotes({"RELIANCE": {"ltp": 2400.0, "source": "SHOONYA_WS", "updated_at": time.time()}})
    monkeypatch.setattr(shared_market_state, "MARKET_STATE", store)
    requested = []

    def external(symbols, _angel):
        requested.extend(symbols)
        return {}, object()

    monkeypatch.setattr("app.services.market_data_provider.fetch_quotes_with_failover", external)
    assert market_data.latest_quotes(["RELIANCE"]) == {}
    assert requested == ["RELIANCE"]
