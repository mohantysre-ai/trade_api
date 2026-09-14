"""Process-local in-memory market state store.

All live market data flows through here. Strategies and UI read from this
store; they never call the broker directly on a read path.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .schemas import FeedStatus, Quote


class MarketStateStore:
    """Thread-safe, copy-on-write market state store."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._quotes: dict[str, Quote] = {}
        self._bars: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._feed_status: FeedStatus = FeedStatus.UNAVAILABLE
        self._last_tick_age: float = 0.0
        self._tick_count: int = 0
        self._started_at: float = time.time()

    def update_quote(self, quote: Quote) -> None:
        with self._lock:
            self._quotes[quote.symbol] = quote
            self._last_tick_age = 0.0
            self._tick_count += 1

    def update_quotes(self, quotes: list[Quote]) -> None:
        with self._lock:
            for quote in quotes:
                self._quotes[quote.symbol] = quote
            self._last_tick_age = 0.0
            self._tick_count += len(quotes)

    def get_quote(self, symbol: str) -> Quote | None:
        with self._lock:
            return self._quotes.get(symbol)

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        with self._lock:
            return {sym: self._quotes[sym] for sym in symbols if sym in self._quotes}

    def get_all_quotes(self) -> dict[str, Quote]:
        with self._lock:
            return dict(self._quotes)

    def upsert_bar(self, symbol: str, interval: str, bar: dict[str, Any]) -> None:
        with self._lock:
            self._bars.setdefault(symbol, {})
            self._bars[symbol][interval] = bar

    def get_bar(self, symbol: str, interval: str) -> dict[str, Any] | None:
        with self._lock:
            return self._bars.get(symbol, {}).get(interval)

    def get_bars(self, symbol: str, interval: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._bars.get(symbol, {}).get(interval, []))[-limit:]

    def set_feed_status(self, status: FeedStatus) -> None:
        with self._lock:
            self._feed_status = status

    def get_feed_status(self) -> FeedStatus:
        with self._lock:
            return self._feed_status

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tick_count": self._tick_count,
                "symbol_count": len(self._quotes),
                "feed_status": self._feed_status.value,
                "last_tick_age": self._last_tick_age,
                "uptime": time.time() - self._started_at,
            }

    def mark_tick_age(self, age: float) -> None:
        with self._lock:
            self._last_tick_age = age

    def hydrate_quotes(self, quotes: dict[str, Any]) -> None:
        with self._lock:
            for sym, q in quotes.items():
                self._quotes[sym] = Quote(
                    symbol=str(q.get("symbol") or sym),
                    ltp=q.get("ltp"),
                    bid=q.get("bid"),
                    ask=q.get("ask"),
                    volume=q.get("volume"),
                    oi=q.get("oi"),
                    source=str(q.get("source") or ""),
                    timestamp=float(q.get("updated_at") or time.time()),
                    feed_status=FeedStatus.STALE,
                )


MARKET_STATE: MarketStateStore | None = None


def get_market_state() -> MarketStateStore:
    global MARKET_STATE
    if MARKET_STATE is None:
        MARKET_STATE = MarketStateStore()
    return MARKET_STATE
