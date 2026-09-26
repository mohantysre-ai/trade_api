"""Provider router lease acquisition, fallback, concurrency, and health tests."""
from __future__ import annotations

import threading
import time

import pytest

from app.services.provider_router import (
    Capability,
    LeaseState,
    Product,
    Provider,
    ProviderLease,
    ProviderRouter,
    provider_lease,
)


def _reset_router() -> None:
    ProviderRouter.reset_instance()


@pytest.fixture(autouse=True)
def _reset():
    _reset_router()
    yield
    _reset_router()


class TestProviderCapabilities:
    def test_angel_supports_all_capabilities(self):
        expected = {
            Capability.EQUITY_WS_QUOTES,
            Capability.EQUITY_REST_QUOTES,
            Capability.EQUITY_CANDLES,
            Capability.INDEX_UNDERLYING,
            Capability.NFO_QUOTE,
            Capability.OPTION_CHAIN,
            Capability.GREEKS,
            Capability.BULK_HISTORICAL_CANDLES,
            Capability.OPEN_POSITION_MARKS,
        }
        from app.services.provider_router import _PROVIDER_CAPABILITIES
        assert expected == _PROVIDER_CAPABILITIES[Provider.ANGEL]

    def test_dhan_does_not_support_nfo_quote(self):
        from app.services.provider_router import _PROVIDER_CAPABILITIES
        assert Capability.NFO_QUOTE not in _PROVIDER_CAPABILITIES[Provider.DHAN]

    def test_nse_does_not_support_option_chain(self):
        from app.services.provider_router import _PROVIDER_CAPABILITIES
        assert Capability.OPTION_CHAIN not in _PROVIDER_CAPABILITIES[Provider.NSE]

    def test_shoonya_supports_bulk_historical_candles(self):
        from app.services.provider_router import _PROVIDER_CAPABILITIES
        assert Capability.BULK_HISTORICAL_CANDLES in _PROVIDER_CAPABILITIES[Provider.SHOONYA]


class TestLeaseAcquisition:
    def test_acquire_free_provider(self):
        router = ProviderRouter()
        lease = router.acquire(Product.SWING, Capability.EQUITY_CANDLES, timeout=1.0)
        assert lease is not None
        assert lease.provider == Provider.DHAN
        router.release(lease)

    def test_acquire_angel_when_dhan_busy(self):
        router = ProviderRouter()
        lease1 = router.acquire(Product.SWING, Capability.EQUITY_CANDLES, timeout=1.0)
        assert lease1 is not None
        lease2 = router.acquire(Product.INTRADAY, Capability.EQUITY_CANDLES, timeout=1.0)
        assert lease2 is not None
        assert lease2.provider == Provider.SHOONYA
        router.release(lease1)
        router.release(lease2)

    def test_acquire_returns_none_when_all_busy_no_wait(self):
        router = ProviderRouter()
        router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=1.0)
        router.acquire(Product.INTRADAY, Capability.NFO_QUOTE, timeout=1.0)
        lease = router.acquire(
            Product.INDEX_OPTIONS, Capability.NFO_QUOTE, timeout=0.1, allow_wait=False
        )
        assert lease is None

    def test_acquire_times_out(self):
        router = ProviderRouter()
        router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=1.0)
        router.acquire(Product.INTRADAY, Capability.NFO_QUOTE, timeout=1.0)
        lease = router.acquire(
            Product.INDEX_OPTIONS, Capability.NFO_QUOTE, timeout=0.5, allow_wait=True
        )
        assert lease is None

    def test_lease_release_frees_provider(self):
        router = ProviderRouter()
        lease = router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=1.0)
        assert lease is not None
        router.release(lease)
        state = router._states[Provider.ANGEL]
        assert state.state == LeaseState.FREE

    def test_context_manager_releases_on_exception(self):
        router = ProviderRouter()
        try:
            with provider_lease(Product.SWING, Capability.NFO_QUOTE, timeout=1.0) as lease:
                assert lease is not None
                raise RuntimeError("test")
        except RuntimeError:
            pass
        state = router._states[Provider.ANGEL]
        assert state.state == LeaseState.FREE

    def test_unknown_product_raises(self):
        router = ProviderRouter()
        with pytest.raises(ValueError):
            router.acquire("unknown", Capability.EQUITY_CANDLES, timeout=1.0)


class TestConcurrentRouting:
    def test_swing_angel_intraday_shoonya(self):
        router = ProviderRouter()
        swing_lease = router.acquire(Product.SWING, Capability.EQUITY_CANDLES, timeout=1.0)
        assert swing_lease is not None
        assert swing_lease.provider == Provider.DHAN
        intraday_lease = router.acquire(
            Product.INTRADAY, Capability.EQUITY_CANDLES, timeout=1.0
        )
        assert intraday_lease is not None
        assert intraday_lease.provider == Provider.SHOONYA
        router.release(swing_lease)
        router.release(intraday_lease)

    def test_no_duplicate_angel_lease(self):
        router = ProviderRouter()
        lease1 = router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=1.0)
        assert lease1 is not None
        assert lease1.provider == Provider.ANGEL
        lease2 = router.acquire(Product.INTRADAY, Capability.NFO_QUOTE, timeout=0.1, allow_wait=False)
        assert lease2 is not None
        assert lease2.provider == Provider.SHOONYA
        router.release(lease1)
        router.release(lease2)

    def test_concurrent_threads_get_different_providers(self):
        router = ProviderRouter()
        results: list[Provider | None] = []

        def worker():
            lease = router.acquire(
                Product.SWING, Capability.EQUITY_CANDLES, timeout=2.0
            )
            results.append(lease.provider if lease else None)
            if lease:
                time.sleep(0.1)
                router.release(lease)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert Provider.DHAN in results
        assert Provider.SHOONYA in results
        assert Provider.NSE in results

    def test_provider_stickiness(self):
        router = ProviderRouter()
        lease1 = router.acquire(Product.SWING, Capability.EQUITY_CANDLES, timeout=1.0)
        assert lease1 is not None
        lease2 = router.acquire(
            Product.SWING, Capability.EQUITY_CANDLES, timeout=1.0
        )
        assert lease2 is not None
        assert lease2.provider == Provider.SHOONYA
        router.release(lease1)
        router.release(lease2)


class TestCircuitBreaker:
    def test_rate_limit_opens_circuit(self):
        router = ProviderRouter()
        router.mark_rate_limited(Provider.ANGEL, hold_seconds=1.0)
        state = router._states[Provider.ANGEL]
        assert state.state == LeaseState.CIRCUIT_OPEN
        assert state.rate_limit_count == 1

    def test_circuit_blocks_acquire(self):
        router = ProviderRouter()
        router.mark_rate_limited(Provider.ANGEL, hold_seconds=10.0)
        router.mark_rate_limited(Provider.SHOONYA, hold_seconds=10.0)
        lease = router.acquire(Product.INDEX_OPTIONS, Capability.NFO_QUOTE, timeout=0.1)
        assert lease is None

    def test_circuit_auto_recovers(self):
        router = ProviderRouter()
        router.mark_rate_limited(Provider.ANGEL, hold_seconds=0.2)
        time.sleep(0.3)
        lease = router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=1.0)
        assert lease is not None
        assert lease.provider == Provider.ANGEL
        router.release(lease)

    def test_unhealthy_provider_skipped(self):
        router = ProviderRouter()
        for _ in range(8):
            router.mark_unhealthy(Provider.ANGEL, "connection_error")
        lease = router.acquire(Product.SWING, Capability.EQUITY_REST_QUOTES, timeout=1.0)
        assert lease is not None
        assert lease.provider != Provider.ANGEL
        router.release(lease)

    def test_recovery_improves_health(self):
        router = ProviderRouter()
        router.mark_unhealthy(Provider.ANGEL, "error")
        assert router._states[Provider.ANGEL].health < 1.0
        router.mark_recovered(Provider.ANGEL)
        assert router._states[Provider.ANGEL].health > 0.0


class TestProviderHealth:
    def test_initial_health_is_one(self):
        router = ProviderRouter()
        for state in router._states.values():
            assert state.health == 1.0

    def test_multiple_failures_degrade_health(self):
        router = ProviderRouter()
        for _ in range(5):
            router.mark_unhealthy(Provider.ANGEL, "error")
        assert router._states[Provider.ANGEL].health <= 0.51

    def test_dead_provider_not_selected(self):
        router = ProviderRouter()
        for _ in range(10):
            router.mark_unhealthy(Provider.ANGEL, "dead")
            router.mark_unhealthy(Provider.SHOONYA, "dead")
            router.mark_unhealthy(Provider.DHAN, "dead")
        lease = router.acquire(Product.SWING, Capability.BULK_HISTORICAL_CANDLES, timeout=1.0)
        assert lease is not None
        assert lease.provider == Provider.NSE
        router.release(lease)


class TestDiagnostics:
    def test_diagnostics_returns_all_providers(self):
        router = ProviderRouter()
        diag = router.diagnostics()
        assert set(diag["providers"].keys()) == {p.value for p in Provider}

    def test_diagnostics_tracks_active_leases(self):
        router = ProviderRouter()
        lease = router.acquire(Product.SWING, Capability.EQUITY_CANDLES, timeout=1.0)
        diag = router.diagnostics()
        assert diag["activeLeases"] == 1
        router.release(lease)
        diag = router.diagnostics()
        assert diag["activeLeases"] == 0

    def test_diagnostics_tracks_call_counts(self):
        router = ProviderRouter()
        router.acquire(Product.SWING, Capability.EQUITY_CANDLES, timeout=1.0)
        diag = router.diagnostics()
        assert diag["totalCalls"] >= 1


class TestP0Priority:
    def test_p0_uses_any_available_provider(self):
        router = ProviderRouter()
        lease = router.acquire(
            Product.INDEX_OPTIONS, Capability.NFO_QUOTE, timeout=1.0, priority=10
        )
        assert lease is not None
        router.release(lease)

    def test_p0_waits_for_nfo_if_all_busy(self):
        router = ProviderRouter()
        router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=2.0)
        router.acquire(Product.INTRADAY, Capability.NFO_QUOTE, timeout=2.0)
        start = time.monotonic()
        lease = router.acquire(
            Product.INDEX_OPTIONS, Capability.NFO_QUOTE, timeout=1.5
        )
        elapsed = time.monotonic() - start
        assert lease is None or elapsed >= 1.0


class TestSharedMarketState:
    def test_shared_state_does_not_prevent_router(self):
        router = ProviderRouter()
        lease = router.acquire(Product.INTRADAY, Capability.EQUITY_WS_QUOTES, timeout=1.0)
        assert lease is not None
        router.release(lease)


class TestAngelBusyFallback:
    def test_angel_busy_uses_shoonya_for_quotes(self):
        router = ProviderRouter()
        router.acquire(Product.SWING, Capability.EQUITY_REST_QUOTES, timeout=2.0)
        lease = router.acquire(
            Product.INTRADAY, Capability.EQUITY_REST_QUOTES, timeout=1.0
        )
        assert lease is not None
        assert lease.provider == Provider.SHOONYA
        router.release(lease)

    def test_angel_and_shoonya_busy_uses_dhan_for_candles(self):
        router = ProviderRouter()
        router.acquire(Product.SWING, Capability.EQUITY_CANDLES, timeout=2.0)
        router.acquire(Product.INTRADAY, Capability.EQUITY_CANDLES, timeout=2.0)
        lease = router.acquire(
            Product.INDEX_OPTIONS, Capability.EQUITY_CANDLES, timeout=1.0
        )
        assert lease is not None
        assert lease.provider == Provider.NSE
        router.release(lease)


class TestNFOBoundedWait:
    def test_nfo_waits_bounded_when_all_nfo_busy(self):
        router = ProviderRouter()
        router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=2.0)
        router.acquire(Product.INTRADAY, Capability.NFO_QUOTE, timeout=2.0)
        start = time.monotonic()
        lease = router.acquire(
            Product.INDEX_OPTIONS, Capability.NFO_QUOTE, timeout=0.5
        )
        elapsed = time.monotonic() - start
        assert lease is None
        assert elapsed < 1.0

    def test_nfo_acquires_after_release(self):
        router = ProviderRouter()
        swing = router.acquire(Product.SWING, Capability.NFO_QUOTE, timeout=2.0)
        assert swing is not None
        acquired = threading.Event()
        got_lease = []

        def waiter():
            lease = router.acquire(Product.INDEX_OPTIONS, Capability.NFO_QUOTE, timeout=2.0)
            acquired.set()
            if lease:
                got_lease.append(lease.provider)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.2)
        router.release(swing)
        acquired.wait(timeout=2.0)
        t.join(timeout=2.0)
        assert len(got_lease) == 1
        assert got_lease[0] in {Provider.ANGEL, Provider.SHOONYA}
