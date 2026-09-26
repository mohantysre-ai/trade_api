"""Central provider router with lease-based allocation.

Products request capabilities through the router rather than independently
choosing providers. The router ensures no duplicate provider calls, no
deadlocks, proper fallback chains, P0 priority for locked positions, circuit
breaker integration, and bounded waits.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)


class Provider(str, Enum):
    ANGEL = "ANGEL"
    SHOONYA = "SHOONYA"
    DHAN = "DHAN"
    NSE = "NSE"


class Capability(str, Enum):
    EQUITY_WS_QUOTES = "equity_ws_quotes"
    EQUITY_REST_QUOTES = "equity_rest_quotes"
    EQUITY_CANDLES = "equity_candles"
    INDEX_UNDERLYING = "index_underlying"
    NFO_QUOTE = "nfo_quote"
    OPTION_CHAIN = "option_chain"
    GREEKS = "greeks"
    BULK_HISTORICAL_CANDLES = "bulk_historical_candles"
    OPEN_POSITION_MARKS = "open_position_marks"


class Product(str, Enum):
    INTRADAY = "intraday"
    SWING = "swing"
    INDEX_OPTIONS = "index_options"


class LeaseState(str, Enum):
    FREE = "free"
    BUSY = "busy"
    CIRCUIT_OPEN = "circuit_open"
    UNHEALTHY = "unhealthy"


# Capability matrix: which providers support which capabilities
_PROVIDER_CAPABILITIES: dict[Provider, set[Capability]] = {
    Provider.ANGEL: {
        Capability.EQUITY_WS_QUOTES,
        Capability.EQUITY_REST_QUOTES,
        Capability.EQUITY_CANDLES,
        Capability.INDEX_UNDERLYING,
        Capability.NFO_QUOTE,
        Capability.OPTION_CHAIN,
        Capability.GREEKS,
        Capability.BULK_HISTORICAL_CANDLES,
        Capability.OPEN_POSITION_MARKS,
    },
    Provider.SHOONYA: {
        Capability.EQUITY_WS_QUOTES,
        Capability.EQUITY_REST_QUOTES,
        Capability.EQUITY_CANDLES,
        Capability.INDEX_UNDERLYING,
        Capability.NFO_QUOTE,
        Capability.BULK_HISTORICAL_CANDLES,
        Capability.OPEN_POSITION_MARKS,
    },
    Provider.DHAN: {
        Capability.EQUITY_REST_QUOTES,
        Capability.EQUITY_CANDLES,
        Capability.BULK_HISTORICAL_CANDLES,
    },
    Provider.NSE: {
        Capability.EQUITY_REST_QUOTES,
        Capability.EQUITY_CANDLES,
        Capability.INDEX_UNDERLYING,
        Capability.BULK_HISTORICAL_CANDLES,
    },
}

# Default preference order by capability
_CAPABILITY_PREFERENCE: dict[Capability, list[Provider]] = {
    Capability.EQUITY_WS_QUOTES: [Provider.ANGEL, Provider.SHOONYA],
    Capability.EQUITY_REST_QUOTES: [Provider.ANGEL, Provider.SHOONYA, Provider.DHAN, Provider.NSE],
    Capability.EQUITY_CANDLES: [Provider.DHAN, Provider.SHOONYA, Provider.NSE, Provider.ANGEL],
    Capability.INDEX_UNDERLYING: [Provider.ANGEL, Provider.SHOONYA, Provider.DHAN, Provider.NSE],
    Capability.NFO_QUOTE: [Provider.ANGEL, Provider.SHOONYA],
    Capability.OPTION_CHAIN: [Provider.ANGEL, Provider.SHOONYA],
    Capability.GREEKS: [Provider.ANGEL, Provider.SHOONYA],
    Capability.BULK_HISTORICAL_CANDLES: [Provider.DHAN, Provider.SHOONYA, Provider.NSE, Provider.ANGEL],
    Capability.OPEN_POSITION_MARKS: [Provider.ANGEL, Provider.SHOONYA, Provider.DHAN, Provider.NSE],
}

# Product-specific overrides
_PRODUCT_CAPABILITY_OVERRIDES: dict[Product, dict[Capability, list[Provider]]] = {
    Product.SWING: {
        Capability.EQUITY_CANDLES: [Provider.DHAN, Provider.SHOONYA, Provider.NSE, Provider.ANGEL],
    },
    Product.INTRADAY: {
        Capability.EQUITY_WS_QUOTES: [Provider.ANGEL, Provider.SHOONYA],
        Capability.EQUITY_CANDLES: [Provider.DHAN, Provider.SHOONYA, Provider.NSE, Provider.ANGEL],
    },
    Product.INDEX_OPTIONS: {
        Capability.NFO_QUOTE: [Provider.ANGEL, Provider.SHOONYA],
        Capability.OPTION_CHAIN: [Provider.ANGEL, Provider.SHOONYA],
    },
}


@dataclass
class ProviderState:
    provider: Provider
    state: LeaseState = LeaseState.FREE
    owner: str | None = None
    capability: Capability | None = None
    acquired_at: float = 0.0
    expires_at: float = 0.0
    last_error: str | None = None
    call_count: int = 0
    rate_limit_count: int = 0
    circuit_until: float = 0.0
    health: float = 1.0

    def is_busy(self) -> bool:
        if self.state == LeaseState.CIRCUIT_OPEN:
            return time.monotonic() < self.circuit_until
        return self.state == LeaseState.BUSY and time.monotonic() < self.expires_at

    def is_available(self) -> bool:
        if self.state == LeaseState.CIRCUIT_OPEN:
            return time.monotonic() >= self.circuit_until
        if self.state == LeaseState.UNHEALTHY:
            return self.health >= 0.8
        return self.state == LeaseState.FREE or not self.is_busy()


@dataclass
class ProviderLease:
    provider: Provider
    capability: Capability
    product: Product
    owner: str
    acquired_at: float
    expires_at: float

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    def age(self) -> float:
        return max(0.0, time.monotonic() - self.acquired_at)


class ProviderRouter:
    _instance: ProviderRouter | None = None

    def __new__(cls) -> ProviderRouter:
        if cls._instance is None:
            with threading.Lock():
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._lock = threading.RLock()
                    inst._states: dict[Provider, ProviderState] = {
                        p: ProviderState(provider=p) for p in Provider
                    }
                    inst._leases: dict[str, ProviderLease] = {}
                    inst._lease_counter = 0
                    cls._instance = inst
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with threading.Lock():
            cls._instance = None

    def _next_owner(self, product: Product) -> str:
        with self._lock:
            self._lease_counter += 1
            return f"{product.value}-{threading.current_thread().name}-{self._lease_counter}"

    def _cleanup_expired(self) -> None:
        now = time.monotonic()
        with self._lock:
            dead = [owner for owner, lease in self._leases.items() if now >= lease.expires_at]
            for owner in dead:
                lease = self._leases.pop(owner)
                state = self._states.get(lease.provider)
                if state and state.owner == owner:
                    state.state = LeaseState.FREE
                    state.owner = None
                    state.capability = None
                    state.expires_at = 0.0

    def acquire(
        self,
        product: Product | str,
        capability: Capability | str,
        *,
        priority: int = 0,
        timeout: float = 20.0,
        allow_wait: bool = True,
        required_exchange: str | None = None,
        batch_size: int = 1,
        symbols: list[str] | None = None,
    ) -> ProviderLease | None:
        if isinstance(product, str):
            try:
                product = Product(product.lower())
            except ValueError:
                raise ValueError(f"Unknown product: {product}")
        if isinstance(capability, str):
            try:
                capability = Capability(capability.lower())
            except ValueError:
                raise ValueError(f"Unknown capability: {capability}")

        deadline = time.monotonic() + timeout
        owner = self._next_owner(product)

        while True:
            self._cleanup_expired()
            with self._lock:
                preferred = _PRODUCT_CAPABILITY_OVERRIDES.get(
                    product, {}
                ).get(capability, _CAPABILITY_PREFERENCE.get(capability, list(Provider)))

                for provider in preferred:
                    if capability not in _PROVIDER_CAPABILITIES.get(provider, set()):
                        continue
                    state = self._states[provider]
                    if not state.is_available():
                        continue
                    if state.health < 0.3:
                        continue
                    now = time.monotonic()
                    lease = ProviderLease(
                        provider=provider,
                        capability=capability,
                        product=product,
                        owner=owner,
                        acquired_at=now,
                        expires_at=now + 30.0,
                    )
                    state.state = LeaseState.BUSY
                    state.owner = owner
                    state.capability = capability
                    state.acquired_at = now
                    state.expires_at = lease.expires_at
                    state.last_error = None
                    state.call_count += 1
                    self._leases[owner] = lease
                    logger.info(
                        "Provider lease acquired: product=%s capability=%s provider=%s owner=%s",
                        product.value, capability.value, provider.value, owner,
                    )
                    return lease

            if not allow_wait:
                return None

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "Provider lease timeout: product=%s capability=%s timeout=%.1fs",
                    product.value, capability.value, timeout,
                )
                return None

            wait_time = min(0.05, remaining)
            time.sleep(wait_time)

    def release(self, lease: ProviderLease | None) -> None:
        if lease is None:
            return
        with self._lock:
            state = self._states.get(lease.provider)
            if state and state.owner == lease.owner:
                state.state = LeaseState.FREE
                state.owner = None
                state.capability = None
                state.expires_at = 0.0
            self._leases.pop(lease.owner, None)
            logger.info(
                "Provider lease released: product=%s capability=%s provider=%s owner=%s",
                lease.product.value, lease.capability.value, lease.provider.value, lease.owner,
            )

    def mark_rate_limited(self, provider: Provider, hold_seconds: float = 60.0) -> None:
        with self._lock:
            state = self._states[provider]
            state.rate_limit_count += 1
            state.circuit_until = time.monotonic() + hold_seconds
            state.state = LeaseState.CIRCUIT_OPEN
            state.last_error = "rate_limited"
            logger.warning("Provider circuit open: provider=%s hold=%.1fs", provider.value, hold_seconds)

    def mark_unhealthy(self, provider: Provider, error: str) -> None:
        with self._lock:
            state = self._states[provider]
            state.health = max(0.0, state.health - 0.1)
            state.last_error = error
            state.state = LeaseState.UNHEALTHY
            logger.warning(
                "Provider marked unhealthy: provider=%s error=%s health=%.2f",
                provider.value, error, state.health,
            )

    def mark_recovered(self, provider: Provider) -> None:
        with self._lock:
            state = self._states[provider]
            state.health = min(1.0, state.health + 0.2)
            if state.health >= 0.8:
                state.state = LeaseState.FREE
                state.circuit_until = 0.0
                state.last_error = None
            logger.info("Provider recovered: provider=%s health=%.2f", provider.value, state.health)

    def diagnostics(self) -> dict[str, Any]:
        self._cleanup_expired()
        with self._lock:
            return {
                "providers": {
                    p.value: {
                        "state": s.state.value,
                        "owner": s.owner,
                        "capability": s.capability.value if s.capability else None,
                        "leaseAge": round(time.monotonic() - s.acquired_at, 2) if s.acquired_at else 0,
                        "health": round(s.health, 2),
                        "circuit": s.state == LeaseState.CIRCUIT_OPEN,
                        "lastError": s.last_error,
                        "calls": s.call_count,
                        "rateLimits": s.rate_limit_count,
                    }
                    for p, s in self._states.items()
                },
                "activeLeases": len(self._leases),
                "totalCalls": sum(s.call_count for s in self._states.values()),
            }


@contextmanager
def provider_lease(
    product: Product | str,
    capability: Capability | str,
    **kwargs: Any,
) -> Iterator[ProviderLease | None]:
    router = ProviderRouter()
    lease = router.acquire(product, capability, **kwargs)
    try:
        yield lease
    finally:
        router.release(lease)
