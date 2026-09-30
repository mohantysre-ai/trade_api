"""Deterministic failover soak harness for the Angel -> Shoonya standby lane.

Provides a virtual clock, a seeded volatile market, an injectable Angel lane
(downtime / latency / flapping) and a fake Shoonya gateway with fault
injection, so reliability behaviour can be exercised across a full trading
session without waiting for real elapsed time.
"""
from __future__ import annotations

import math
import random
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHOONYA_GATEWAY_DIR = _REPO_ROOT / "shoonya-gateway"
if str(_SHOONYA_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_SHOONYA_GATEWAY_DIR))

IST = timezone(timedelta(hours=5, minutes=30))
# 2026-09-25 is a Friday; the market-date guards compare against "today" in IST.
TRADING_DAY = datetime(2026, 9, 25, 9, 15, tzinfo=IST)

PINNED: tuple[tuple[str, str], ...] = (
    ("RELIANCE", "2885"),
    ("TCS", "11536"),
    ("HDFCBANK", "1333"),
    ("INFY", "1595"),
    ("ICICIBANK", "4963"),
)


# ---------------------------------------------------------------------------
# Virtual clock
# ---------------------------------------------------------------------------

class VirtualClock:
    """Monotonic + wall clock advanced explicitly by the driver.

    Backed by the real monotonic clock so the value never moves backwards and
    stays near real time, which keeps pytest internals happy while the test
    fast-forwards a whole session.
    """

    def __init__(self, epoch: datetime = TRADING_DAY) -> None:
        self._real_mono = time.monotonic
        self._real0 = self._real_mono()
        self._wall0 = epoch.astimezone(timezone.utc)
        self._offset = 0.0

    def advance(self, seconds: float) -> None:
        self._offset += float(seconds)

    @property
    def elapsed(self) -> float:
        return self._offset + (self._real_mono() - self._real0)

    def monotonic(self) -> float:
        return self._real0 + (self._real_mono() - self._real0) + self._offset

    def now_utc(self) -> datetime:
        return self._wall0 + timedelta(seconds=self.elapsed)

    def exchange_ts_ms(self) -> int:
        return int(self.now_utc().timestamp() * 1000)


# ---------------------------------------------------------------------------
# Volatile market
# ---------------------------------------------------------------------------

@dataclass
class SymbolSpec:
    symbol: str
    token: str
    base: float
    prev_close: float


class VolatileMarket:
    """Seeded random walk with switchable volatility regimes.

    ``step_pct`` is the per-cycle move magnitude, so a scenario is expressed in
    market terms ("a 2% candle every poll") rather than in arbitrary numbers.
    """

    def __init__(
        self,
        specs: tuple[SymbolSpec, ...],
        seed: int = 20260925,
        step_pct: float = 0.15,
        trend_pct: float = 0.0,
    ) -> None:
        self._rng = random.Random(seed)
        self._specs = specs
        self.step_pct = step_pct
        self.trend_pct = trend_pct
        self.price: dict[str, float] = {s.symbol: s.base for s in specs}
        self.cycle = 0

    def tick(self) -> dict[str, float]:
        self.cycle += 1
        out: dict[str, float] = {}
        for spec in self._specs:
            drift = self._rng.gauss(0.0, self.step_pct) + self.trend_pct
            price = self.price[spec.symbol] * (1.0 + drift / 100.0)
            price = max(0.05, round(price, 2))
            self.price[spec.symbol] = price
            out[spec.symbol] = price
        return out

    def prev_close(self, symbol: str) -> float:
        return next(s.prev_close for s in self._specs if s.symbol == symbol)

    def ltp(self, symbol: str) -> float:
        return self.price[symbol]


# ---------------------------------------------------------------------------
# Angel lane
# ---------------------------------------------------------------------------

class AngelLane:
    """Angel One feed simulator with programmable availability.

    ``script`` is a callable ``(elapsed_seconds) -> str`` returning one of
    ``up`` / ``slow`` / ``down``.
    """

    def __init__(
        self,
        state: Any,
        market: VolatileMarket,
        *,
        slow_interval_s: float = 10.0,
        normal_interval_s: float = 1.0,
    ) -> None:
        self.state = state
        self.market = market
        self.slow_interval_s = slow_interval_s
        self.normal_interval_s = normal_interval_s
        self.script: Callable[[float], str] = lambda _elapsed: "up"
        self._seq: dict[str, int] = {}
        self._last_emit: dict[str, float] = {}
        self.emitted = 0
        self.connected = True

    def set_script(self, script: Callable[[float], str]) -> None:
        self.script = script

    def mode(self, elapsed: float) -> str:
        return self.script(elapsed)

    def poll(self, clock: VirtualClock) -> None:
        """Emit Angel ticks for any symbol whose lane is due."""
        mode = self.mode(clock.elapsed)
        self.connected = mode != "down"
        if mode == "down":
            return
        interval = self.slow_interval_s if mode == "slow" else self.normal_interval_s
        prices = self.market.price
        for symbol, token in PINNED:
            last = self._last_emit.get(token)
            if last is not None and clock.elapsed - last < interval:
                continue
            price = prices[symbol]
            seq = self._seq.get(token, 0) + 1
            self._seq[token] = seq
            self._last_emit[token] = clock.elapsed
            self.state.apply_tick(
                token,
                1,
                {
                    "last_traded_price": int(price * 100),
                    "sequenceNumber": seq,
                    "closed_price": int(self.market.prev_close(symbol) * 100),
                },
            )
            self.emitted += 1


# ---------------------------------------------------------------------------
# Fake Shoonya gateway
# ---------------------------------------------------------------------------

@dataclass
class GatewayFault:
    """Fault injection for the Shoonya gateway."""

    health_unhealthy: bool = False
    health_raises: bool = False
    quotes_raises: bool = False
    quotes_empty: bool = False
    drop_symbols: set[str] = field(default_factory=set)

    @property
    def any_active(self) -> bool:
        return (
            self.health_unhealthy
            or self.health_raises
            or self.quotes_raises
            or self.quotes_empty
            or bool(self.drop_symbols)
        )


class FakeShoonyaGateway:
    """Stands in for :class:`GatewayClient` with the same call surface.

    ``strict=False`` (the default) mirrors the real client, which swallows
    every transport error and returns a safe empty value. ``strict=True``
    raises instead, which is used to prove the runner's own error handling
    rather than the client's.
    """

    def __init__(self, market: VolatileMarket, strict: bool = False) -> None:
        self.market = market
        self.fault = GatewayFault()
        self.strict = strict
        self.pins: list[tuple[str, list[str], float | None]] = []
        self.health_calls = 0
        self.quote_calls = 0
        self.configured = True

    def clear_faults(self) -> None:
        self.fault = GatewayFault()

    def health(self) -> dict[str, Any] | None:
        self.health_calls += 1
        if self.fault.health_raises:
            if self.strict:
                raise ConnectionError("gateway down")
            return None
        if self.fault.health_unhealthy:
            return {"healthy": False, "auth": {"state": "EXPIRED"}}
        return {"healthy": True, "auth": {"state": "AUTHENTICATED"}}

    def pin(self, owner: str, symbols: list[str], ttl_seconds: float | None = None) -> bool:
        self.pins.append((owner, list(symbols), ttl_seconds))
        return not self.fault.health_raises

    def unpin(self, owner: str) -> bool:
        return True

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        self.quote_calls += 1
        if self.fault.quotes_raises:
            if self.strict:
                raise ConnectionError("quotes timeout")
            return {}
        if self.fault.quotes_empty:
            return {}
        out: dict[str, dict[str, Any]] = {}
        ts = self._ts
        for symbol in symbols:
            if symbol in self.fault.drop_symbols:
                continue
            out[symbol] = {
                "ltp": self.market.ltp(symbol),
                "prevClose": self.market.prev_close(symbol),
                "exchangeTsMs": ts,
                "volume": 1000 + hash(symbol) % 500,
            }
        return out

    def candles(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ERROR", "rows": []}

    _ts: int = 0


# ---------------------------------------------------------------------------
# Continuity monitor
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    elapsed: float
    symbol: str
    kind: str
    detail: str


class ContinuityMonitor:
    """Invariants that must hold at every simulation step.

    These encode "maintains continuous operation" concretely: every pinned
    symbol always carries a positive finite price from a real source, and while
    a lane is authoritative its prices keep moving.
    """

    def __init__(self, symbols: tuple[str, ...], freeze_tolerance_s: float) -> None:
        self.symbols = symbols
        self.freeze_tolerance_s = freeze_tolerance_s
        self.violations: list[Violation] = []
        self.last_ltp: dict[str, float] = {}
        self.last_update: dict[str, float] = {}
        self.observed: set[str] = set()
        self.samples = 0

    def check(self, state: Any, clock: VirtualClock) -> None:
        self.samples += 1
        elapsed = clock.elapsed
        for symbol in self.symbols:
            row = state.symbol_state(symbol)
            if row is None:
                self.violations.append(
                    Violation(elapsed, symbol, "row_missing", "no row for pinned symbol")
                )
                continue
            ltp = row.get("ltp")
            self.observed.add(row.get("source") or "UNKNOWN")
            if ltp is None:
                self.violations.append(
                    Violation(elapsed, symbol, "no_price", "ltp is None")
                )
                continue
            if not isinstance(ltp, (int, float)) or not math.isfinite(float(ltp)):
                self.violations.append(
                    Violation(elapsed, symbol, "non_finite", f"ltp={ltp!r}")
                )
                continue
            if float(ltp) <= 0.0:
                self.violations.append(
                    Violation(elapsed, symbol, "non_positive", f"ltp={ltp!r}")
                )
                continue
            if not row.get("source"):
                self.violations.append(
                    Violation(elapsed, symbol, "no_source", "row has no source")
                )
                continue
            previous = self.last_ltp.get(symbol)
            if previous is None or abs(float(ltp) - previous) > 1e-9:
                self.last_update[symbol] = elapsed
                self.last_ltp[symbol] = float(ltp)
            elif elapsed - self.last_update.get(symbol, elapsed) > self.freeze_tolerance_s:
                self.violations.append(
                    Violation(
                        elapsed,
                        symbol,
                        "frozen",
                        f"ltp pinned at {ltp} for "
                        f"{elapsed - self.last_update.get(symbol, elapsed):.1f}s",
                    )
                )

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for v in self.violations:
            by_kind[v.kind] = by_kind.get(v.kind, 0) + 1
        return {
            "samples": self.samples,
            "violations": len(self.violations),
            "byKind": by_kind,
            "sources": sorted(self.observed),
            "first": [
                f"{v.elapsed:.1f}s {v.symbol} {v.kind}: {v.detail}"
                for v in self.violations[:5]
            ],
        }


# ---------------------------------------------------------------------------
# Simulation driver
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    duration_s: float
    poll_interval_s: float = 2.0
    step_pct: float = 0.15
    trend_pct: float = 0.0
    promote_after_s: float = 8.0
    band_pct: float = 25.0
    handoff_divergence_pct: float = 1.0
    divergence_alert_pct: float = 0.3
    divergence_min_symbols: int = 3
    freeze_tolerance_s: float = 12.0
    # Optional regime schedule: elapsed -> (step_pct, trend_pct). Lets a single
    # scenario drive a busy open and then a quiet afternoon without splitting
    # the run in two.
    market_regimes: tuple[tuple[float, float, float], ...] = ()


class Soak:
    """Drives StandbyFeedRunner cycles against the simulated market."""

    def __init__(self, scenario: Scenario, *, seed: int = 20260925) -> None:
        from app.services.intraday_market_state import IntradayMarketState, IntradayUniverse
        from app.services.standby_feed.client import StandbyFeedRunner
        from app.services.standby_feed.config import StandbyConfig
        from app.services.standby_feed.divergence import DivergenceMonitor

        self.scenario = scenario
        self.clock = VirtualClock()
        specs = tuple(
            SymbolSpec(
                symbol=symbol,
                token=token,
                base=1000.0 + 137.0 * i,
                prev_close=1000.0 + 137.0 * i,
            )
            for i, (symbol, token) in enumerate(PINNED)
        )
        self.market = VolatileMarket(
            specs, seed=seed, step_pct=scenario.step_pct, trend_pct=scenario.trend_pct
        )
        rows = [
            {
                "symbol": s.symbol,
                "exchange": "NSE",
                "token": s.token,
                "tradingsymbol": f"{s.symbol}-EQ",
                "indexGroup": None,
                "active": True,
            }
            for s in specs
        ]
        universe = IntradayUniverse(rows)
        self.state = IntradayMarketState(universe)
        self.state.update_universe(universe)
        self.gateway = FakeShoonyaGateway(self.market)
        self.angel = AngelLane(self.state, self.market)
        self.monitor = ContinuityMonitor(
            tuple(s.symbol for s in specs), scenario.freeze_tolerance_s
        )
        self.outcomes: list[str] = []
        self.source_timeline: list[tuple[float, dict[str, str]]] = []
        self.handoffs: list[tuple[float, str, str]] = []
        self.divergence_events: list[tuple[float, bool]] = []
        self.runner = StandbyFeedRunner(
            config=StandbyConfig(
                enabled=True,
                mode="active",
                gateway_url="http://gateway.invalid",
                gateway_token="tok",
                poll_interval_s=scenario.poll_interval_s,
                pin_ttl_s=600.0,
                promote_after_s=scenario.promote_after_s,
                band_pct=scenario.band_pct,
                handoff_divergence_pct=scenario.handoff_divergence_pct,
                divergence_alert_pct=scenario.divergence_alert_pct,
                divergence_min_symbols=scenario.divergence_min_symbols,
                candles_enabled=False,
                request_timeout_s=1.0,
            ),
            client=self.gateway,
        )
        # DivergenceMonitor captures time.monotonic as a default argument at
        # definition time, so it must be rebuilt explicitly against the virtual
        # clock or the driver would observe real elapsed time.
        self.runner.divergence = DivergenceMonitor(
            scenario.divergence_min_symbols,
            scenario.divergence_alert_pct,
            sustain_s=10.0,
            clock=self.clock.monotonic,
        )
        self._last_sources: dict[str, str] = {}
        self._last_disabled = False
        self.gateway._ts = self.clock.exchange_ts_ms()

    @contextmanager
    def _sim_time(self) -> Iterator[None]:
        # StandbyFeedRunner.run_once resolves state through the module-level
        # singleton rather than an injected reference, so the scenario state has
        # to be published into that global for the runner to drive it.
        with patch("time.monotonic", new=self.clock.monotonic), patch(
            "app.services.intraday_market_state._now_utc", new=self.clock.now_utc
        ), patch(
            "app.services.intraday_market_state.INTRADAY_MARKET_STATE", self.state
        ), patch(
            "app.services.standby_feed.client.compute_p0_symbols",
            new=lambda _day: [symbol for symbol, _ in PINNED],
        ):
            yield

    def _record(self) -> None:
        sources: dict[str, str] = {}
        for symbol in self.monitor.symbols:
            row = self.state.symbol_state(symbol)
            source = (row or {}).get("source") or "NONE"
            sources[symbol] = source
            previous = self._last_sources.get(symbol)
            if previous is not None and previous != source:
                self.handoffs.append((self.clock.elapsed, symbol, f"{previous}->{source}"))
        self._last_sources = sources
        self.source_timeline.append((self.clock.elapsed, dict(sources)))
        disabled = self.runner.divergence.disabled
        if disabled != self._last_disabled:
            self.divergence_events.append((self.clock.elapsed, disabled))
            self._last_disabled = disabled
        self.gateway._ts = self.clock.exchange_ts_ms()

    def _apply_market_regime(self) -> None:
        elapsed = self.clock.elapsed
        step, trend = self.scenario.step_pct, self.scenario.trend_pct
        for change_at, new_step, new_trend in self.scenario.market_regimes:
            if elapsed >= change_at:
                step, trend = new_step, new_trend
        self.market.step_pct = step
        self.market.trend_pct = trend

    def run(self) -> Soak:
        cycles = max(1, int(self.scenario.duration_s / self.scenario.poll_interval_s))
        with self._sim_time():
            for _ in range(cycles):
                self.clock.advance(self.scenario.poll_interval_s)
                self._apply_market_regime()
                self.gateway._ts = self.clock.exchange_ts_ms()
                self.angel.poll(self.clock)
                self.market.tick()
                self.gateway._ts = self.clock.exchange_ts_ms()
                self.runner.run_once()
                self.monitor.check(self.state, self.clock)
                self._record()
        return self

    def report(self) -> dict[str, Any]:
        status = self.state.stream_status()
        return {
            "elapsed": round(self.clock.elapsed, 1),
            "cycles": self.runner.cycles,
            "angelTicks": self.angel.emitted,
            "handoffs": len(self.handoffs),
            "handoffLog": [f"{t:.1f}s {s} {d}" for t, s, d in self.handoffs[:12]],
            "divergenceDisabled": self.runner.divergence.disabled,
            "divergenceEvents": [f"{t:.1f}s disabled={d}" for t, d in self.divergence_events],
            "lastApplied": self.runner.last_applied,
            "lastQuarantined": self.runner.last_quarantined,
            "feedStatus": status.get("feedStatus"),
            "symbolsLive": status.get("symbolsLive"),
            "sourceMix": self.state.ltp_source_mix(),
            "continuity": self.monitor.summary(),
        }


def down_from(start: float) -> Callable[[float], str]:
    """Angel unavailable from ``start`` onward, for the remainder of the run.

    Preferred over an explicit end time so an outage window can never land
    exactly on the final simulated cycle and hand authority back by accident.
    """
    return lambda t: "down" if t >= start else "up"


def phase(*windows: tuple[float, float, str]) -> Callable[[float], str]:
    """Script Angel availability from ``(start, end, mode)`` windows."""

    def _script(elapsed: float) -> str:
        for start, end, mode in windows:
            if start <= elapsed < end:
                return mode
        return "up"

    return _script
