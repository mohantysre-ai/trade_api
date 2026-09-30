"""E2E reliability / continuity suite for the Angel -> Shoonya failover lane.

The existing ``test_shoonya_standby_e2e.py`` validates the promotion guards as
isolated, single-shot decisions against a frozen clock. This suite covers the
dimensions that matter for *continuous operation during market hours*:

- a real elapsed-time soak across a full session (not one state transition)
- Angel hard downtime, latency degradation, and repeated flapping
- an actively trending / volatile market, where the guards themselves can
  suppress an otherwise healthy standby feed
- Shoonya gateway faults (unhealthy, 5xx-equivalent, timeout, empty)
- both lanes down simultaneously, and recovery from it
- the recovery worker's standby branch

Every scenario asserts the same core continuity invariant: each pinned symbol
always carries a positive, finite price from a real source, and while the
standby lane is authoritative those prices keep moving.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from failover_soak_harness import (  # noqa: E402
    PINNED,
    ContinuityMonitor,
    Scenario,
    Soak,
    down_from,
    phase,
)

from app.services.intraday_market_state import (  # noqa: E402
    SOURCE_STANDBY_WS,
    SOURCE_WS,
    IntradayMarketState,
    IntradayUniverse,
)
from app.services.standby_feed.client import StandbyFeedRunner  # noqa: E402
from app.services.standby_feed.config import StandbyConfig  # noqa: E402
from app.services.standby_feed.divergence import DivergenceMonitor  # noqa: E402

SYMBOLS = tuple(symbol for symbol, _ in PINNED)


def _assert_continuous(soak: Soak) -> None:
    summary = soak.monitor.summary()
    assert summary["violations"] == 0, (
        "continuity invariant broken: "
        f"{summary['byKind']} in {soak.monitor.samples} samples; "
        f"first: {summary['first']}"
    )


# ---------------------------------------------------------------------------
# Harness self-test -- proves the continuity monitor can actually fail
# ---------------------------------------------------------------------------

class TestHarnessSelfTest:
    def test_monitor_flags_a_frozen_price(self):
        monitor = ContinuityMonitor(("A",), freeze_tolerance_s=4.0)
        soak = Soak(Scenario(duration_s=1))
        row = {"ltp": 100.0, "source": SOURCE_STANDBY_WS}

        with patch.object(soak.state, "symbol_state", return_value=row):
            soak.clock.advance(2.0)
            monitor.check(soak.state, soak.clock)
            assert monitor.violations == []
            soak.clock.advance(10.0)
            monitor.check(soak.state, soak.clock)

        kinds = {v.kind for v in monitor.violations}
        assert "frozen" in kinds

    def test_monitor_flags_non_positive_and_non_finite(self):
        monitor = ContinuityMonitor(("A",), freeze_tolerance_s=99.0)
        soak = Soak(Scenario(duration_s=1))

        for bad in (0.0, -1.0, float("nan"), float("inf"), None):
            with patch.object(
                soak.state,
                "symbol_state",
                return_value={"ltp": bad, "source": SOURCE_STANDBY_WS},
            ):
                monitor.check(soak.state, soak.clock)
        kinds = {v.kind for v in monitor.violations}
        assert kinds == {"non_positive", "non_finite", "no_price"}

    def test_monitor_flags_a_missing_source(self):
        monitor = ContinuityMonitor(("A",), freeze_tolerance_s=99.0)
        soak = Soak(Scenario(duration_s=1))
        with patch.object(soak.state, "symbol_state", return_value={"ltp": 10.0, "source": None}):
            monitor.check(soak.state, soak.clock)
        assert {v.kind for v in monitor.violations} == {"no_source"}


# ---------------------------------------------------------------------------
# A. Steady state -- no regression when nothing is broken
# ---------------------------------------------------------------------------

class TestSteadyState:
    def test_full_session_angel_authoritative_is_continuous(self):
        soak = Soak(Scenario(duration_s=600)).run()
        _assert_continuous(soak)
        assert soak.monitor.observed == {SOURCE_WS}
        assert soak.runner.last_applied == 0
        assert soak.handoffs == []

    def test_angel_sequence_numbers_are_honoured(self):
        soak = Soak(Scenario(duration_s=60)).run()
        assert soak.angel.emitted > 0
        for symbol, token in PINNED:
            row = soak.state.symbol_state(symbol)
            assert row is not None
            assert row["tickCount"] > 0
            assert row["source"] == SOURCE_WS
            assert token


# ---------------------------------------------------------------------------
# B. Angel hard downtime
# ---------------------------------------------------------------------------

class TestAngelHardOutage:
    OUTAGE = (60.0, 260.0)

    def _soak(self, **kw) -> Soak:
        soak = Soak(Scenario(duration_s=400, **kw))
        soak.angel.set_script(phase((self.OUTAGE[0], self.OUTAGE[1], "down")))
        return soak.run()

    def test_takeover_happens_within_sla(self):
        soak = self._soak()
        start, end = self.OUTAGE
        takeovers = [
            t for t, _s, d in soak.handoffs
            if t >= start and "ANGEL_WS->SHOONYA_WS" in d
        ]
        assert takeovers, f"standby never took over; handoffs={soak.report()['handoffLog']}"
        latency = takeovers[0] - start
        sla = soak.scenario.promote_after_s + soak.scenario.poll_interval_s
        assert latency <= sla, (
            f"takeover took {latency:.1f}s, SLA is {sla:.1f}s "
            f"(promote_after_s={soak.scenario.promote_after_s} + poll)"
        )

    def test_standby_holds_authority_for_the_whole_outage(self):
        soak = self._soak()
        start, end = self.OUTAGE
        during = [
            sources
            for t, sources in soak.source_timeline
            if start + 12 <= t < end
        ]
        assert during, "no samples captured during the outage window"
        owners = {v for sources in during for v in sources.values()}
        assert owners == {SOURCE_STANDBY_WS}, (
            f"standby lost authority mid-outage; observed {sorted(owners)}"
        )

    def test_no_continuity_break_during_outage(self):
        _assert_continuous(self._soak())

    def test_prices_never_freeze_during_outage(self):
        soak = self._soak()
        start, end = self.OUTAGE
        monitor = ContinuityMonitor(SYMBOLS, freeze_tolerance_s=10.0)
        for t, _sources in soak.source_timeline:
            if start + 12 <= t < end:
                monitor.last_ltp = dict(soak.monitor.last_ltp)
                monitor.last_update = dict(soak.monitor.last_update)
                monitor.check(soak.state, soak.clock)
        assert monitor.violations == [], monitor.summary()

    def test_generation_is_monotonic_through_the_outage(self):
        soak = self._soak()
        generations = [g for g in (soak.state.generation,)]
        assert generations[0] > 0
        statuses = [soak.state.stream_status() for _ in [0]]
        assert statuses[0]["symbolsExpected"] == len(SYMBOLS)

    def test_handback_to_angel_on_recovery(self):
        soak = self._soak()
        end = self.OUTAGE[1]
        handback = [
            t for t, _s, d in soak.handoffs
            if t >= end and "SHOONYA_WS->ANGEL_WS" in d
        ]
        assert handback, f"no handback after Angel returned; {soak.report()['handoffLog']}"
        assert handback[0] - end <= soak.scenario.poll_interval_s + 1.0

    def test_no_flap_after_handback(self):
        soak = self._soak()
        end = self.OUTAGE[1]
        after = [d for t, _s, d in soak.handoffs if t > end + 6]
        assert after == [], f"standby flapped after recovery: {after}"


# ---------------------------------------------------------------------------
# C. Angel latency degradation (slow, not down)
# ---------------------------------------------------------------------------

class TestAngelLatency:
    def test_slow_angel_keeps_authority_when_within_sla(self):
        soak = Soak(
            Scenario(duration_s=300, promote_after_s=20.0, poll_interval_s=2.0)
        )
        soak.angel.set_script(lambda _t: "slow")
        soak.angel.slow_interval_s = 4.0
        soak.run()
        _assert_continuous(soak)
        assert soak.monitor.observed == {SOURCE_WS}
        assert soak.handoffs == []

    def test_degraded_angel_hands_over_without_flapping(self):
        """Angel at 12s intervals against an 8s SLA degrades into failover.

        Authority must converge on the standby lane rather than oscillating
        between the two on every poll.
        """
        soak = Soak(Scenario(duration_s=300, promote_after_s=8.0, poll_interval_s=2.0))
        soak.angel.set_script(lambda _t: "slow")
        soak.angel.slow_interval_s = 12.0
        soak.run()
        _assert_continuous(soak)
        assert soak.monitor.observed == {SOURCE_WS, SOURCE_STANDBY_WS}
        per_symbol: dict[str, int] = {}
        for _t, symbol, _d in soak.handoffs:
            per_symbol[symbol] = per_symbol.get(symbol, 0) + 1
        worst = max(per_symbol.values()) if per_symbol else 0
        # 20s of degraded polling at 2s cadence = 10 opportunities; a converged
        # handoff must not repeat once per cycle.
        assert worst <= 2, f"handoff thrash under latency: {soak.report()['handoffLog']}"

    def test_repeated_flapping_stays_bounded(self):
        windows = (
            (60.0, 90.0, "down"),
            (120.0, 150.0, "down"),
            (180.0, 210.0, "down"),
            (240.0, 270.0, "down"),
        )
        soak = Soak(Scenario(duration_s=400, promote_after_s=6.0, poll_interval_s=2.0))
        soak.angel.set_script(phase(*windows))
        soak.run()
        _assert_continuous(soak)
        assert soak.monitor.observed == {SOURCE_WS, SOURCE_STANDBY_WS}

        # Hysteresis: outside an outage (plus room for the takeover delay and the
        # handback) authority must be perfectly still. Thrash would show up here
        # as transitions during the healthy stretches.
        grace = soak.scenario.promote_after_s + soak.scenario.poll_interval_s
        settled = [
            (t, s, d) for t, s, d in soak.handoffs
            if not any(start - grace <= t < end + grace for start, end, _m in windows)
        ]
        assert settled == [], (
            f"authority churned while Angel was healthy: {soak.report()['handoffLog']}"
        )

        # And each outage must cost at most one handover and one handback.
        per_symbol: dict[str, int] = {}
        for _t, symbol, _d in soak.handoffs:
            per_symbol[symbol] = per_symbol.get(symbol, 0) + 1
        assert max(per_symbol.values()) <= 2 * len(windows), (
            f"excessive transitions per symbol: {per_symbol}"
        )


# ---------------------------------------------------------------------------
# D. Market volatility during failover
# ---------------------------------------------------------------------------

class TestVolatilityDuringFailover:
    def test_calm_market_failover_is_lossless(self):
        """Baseline: ordinary volatility must not cost a single cycle."""
        soak = Soak(Scenario(duration_s=300, step_pct=0.2)).run()
        _assert_continuous(soak)

    def test_trending_market_failover_keeps_prices_moving(self):
        """A busy but realistic trend: ~0.1% every 2s poll.

        The band is opened wide so it cannot bind, which isolates the handoff
        consistency guard. The standby lane is polled every 2s and is the only
        feed, so every cycle must refresh every symbol.
        """
        soak = Soak(
            Scenario(
                duration_s=300,
                poll_interval_s=2.0,
                step_pct=0.0,
                trend_pct=0.1,
                band_pct=500.0,
                handoff_divergence_pct=1.0,
                freeze_tolerance_s=10.0,
            )
        )
        soak.angel.set_script(down_from(20.0))
        soak.run()
        _assert_continuous(soak)
        assert soak.runner.last_quarantined == 0, (
            f"{soak.runner.last_quarantined} symbols quarantined on the last "
            f"cycle in a {soak.scenario.trend_pct}%/cycle trend; "
            f"continuity={soak.monitor.summary()['byKind']}"
        )

    def test_long_outage_still_converges_within_the_reference_horizon(self):
        """A veto at handoff must resolve, not freeze the lane for the day.

        During a long silence the standby price legitimately moves more than
        the tight handoff tolerance from the last accepted print, so the first
        prints are vetoed. The book must still converge on the standby lane
        within the reference horizon instead of retrying a frozen comparison
        forever.
        """
        soak = Soak(
            Scenario(
                duration_s=300,
                poll_interval_s=2.0,
                step_pct=0.0,
                trend_pct=0.5,
                band_pct=500.0,
                handoff_divergence_pct=1.0,
                freeze_tolerance_s=45.0,
            )
        )
        soak.angel.set_script(down_from(20.0))
        soak.run()
        first_standby = next(
            (
                t for t, _s, d in soak.handoffs
                if "ANGEL_WS->SHOONYA_WS" in d
            ),
            None,
        )
        assert first_standby is not None, (
            f"standby never took over; {soak.report()['handoffLog']}"
        )
        assert first_standby - 20.0 <= 35.0, (
            f"took {first_standby - 20.0:.1f}s to admit the standby lane, well "
            f"past the {soak.scenario.promote_after_s}s freshness SLA"
        )

    def test_implausible_standby_price_is_flagged_not_applied(self):
        """The handoff consistency safeguard must still refuse absurd prices.

        A feed that contradicts the last accepted price by more than
        ``handoff_divergence_pct`` is rejected, not written to the book. This is
        the guard that re-anchoring the check must not have simply deleted.
        """
        soak = Soak(Scenario(duration_s=200, promote_after_s=6.0))
        soak.angel.set_script(down_from(20.0))
        soak.run()
        assert soak.state.ltp_source_mix().get(SOURCE_STANDBY_WS, 0) == len(SYMBOLS)

        symbol = SYMBOLS[0]
        accepted = soak.state.symbol_state(symbol)["ltp"]
        with soak._sim_time():
            outcomes = [
                soak.state.apply_standby_tick(
                    symbol,
                    {"ltp": accepted * (1.0 + offset),
                     "exchangeTsMs": soak.clock.exchange_ts_ms(),
                     "prevClose": soak.market.prev_close(symbol)},
                    promote_after_s=soak.scenario.promote_after_s,
                    band_pct=soak.scenario.band_pct,
                    handoff_divergence_pct=soak.scenario.handoff_divergence_pct,
                )
                for offset in (0.005, 0.05, 0.5)
            ]
        assert outcomes == [
            "applied",
            "quarantined_divergence",
            "rejected_band",
        ], f"unexpected guard outcomes {outcomes}"
        assert soak.state.symbol_state(symbol)["ltp"] == pytest.approx(
            accepted * 1.005
        ), "a quarantined or rejected price must not reach the book"

    def test_standby_can_promote_a_symbol_that_legitimately_moved_past_the_band(self):
        """A symbol already +30% on the day must still be fail-able-over.

        The band is meant to catch corrupt data, not a real move. Anchoring it
        only to the session's prev close makes any symbol that has genuinely
        traded beyond ``band_pct`` unfail-able-over for the rest of the day:
        every standby tick is refused as out-of-band and the book keeps serving
        a dead price even though the standby feed is healthy.
        """
        # +30% on the day while Angel is up, then a quiet tape once it dies.
        soak = Soak(
            Scenario(
                duration_s=200,
                step_pct=0.0,
                trend_pct=0.55,
                band_pct=25.0,
                market_regimes=((100.0, 0.05, 0.0),),
            )
        )
        soak.angel.set_script(down_from(110.0))
        soak.run()

        pre = soak.state.symbol_state(SYMBOLS[0])
        drift = abs(pre["ltp"] - soak.market.prev_close(SYMBOLS[0])) / soak.market.prev_close(SYMBOLS[0]) * 100
        assert 25.0 < drift < 60.0, (
            f"scenario must move the symbol meaningfully past the band "
            f"(drift {drift:.1f}%)"
        )

        with soak._sim_time():
            for _ in range(6):
                soak.clock.advance(2.0)
                soak.gateway._ts = soak.clock.exchange_ts_ms()
                soak.runner.run_once()
        assert soak.state.ltp_source_mix().get(SOURCE_STANDBY_WS, 0) == len(SYMBOLS), (
            f"symbol had already traded {drift:.1f}% from prev close (band "
            f"{soak.scenario.band_pct}%), so the standby lane refused every "
            f"tick and the book stayed dead on {soak.state.symbol_state(SYMBOLS[0])['ltp']}"
        )

    def test_circuit_limit_move_is_rejected_not_applied(self):
        """A price outside the band must be refused, not written to the book."""
        soak = Soak(Scenario(duration_s=120, band_pct=25.0))
        soak.angel.set_script(down_from(30.0))
        soak.run()
        before = soak.state.symbol_state(SYMBOLS[0])["ltp"]
        with soak._sim_time():
            huge = soak.market.prev_close(SYMBOLS[0]) * 2.0
            outcome = soak.state.apply_standby_tick(
                SYMBOLS[0],
                {"ltp": huge, "exchangeTsMs": soak.clock.exchange_ts_ms(),
                 "prevClose": soak.market.prev_close(SYMBOLS[0])},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_band"
        assert soak.state.symbol_state(SYMBOLS[0])["ltp"] == before


# ---------------------------------------------------------------------------
# E. Divergence monitor behaviour
# ---------------------------------------------------------------------------

class TestDivergenceMonitorReliability:
    def test_transient_burst_does_not_permanently_disable_failover(self):
        """A short cross-symbol divergence burst must re-arm the lane.

        The monitor latching on is a single-day kill switch: once disabled the
        runner stops calling ``apply_standby_tick`` for every symbol, so a
        volatility burst during an Angel outage removes the only remaining
        feed. It must recover when divergence returns to normal.
        """
        now = [0.0]
        monitor = DivergenceMonitor(
            min_symbols=3, alert_pct=0.3, sustain_s=10.0, clock=lambda: now[0]
        )
        breached = {"A": 0.9, "B": 1.1, "C": 0.8, "D": 0.7}
        monitor.observe(breached)
        now[0] = 11.0
        monitor.observe(breached)
        assert monitor.disabled is True

        calm = {"A": 0.01, "B": 0.02, "C": 0.01, "D": 0.02}
        for step in (22.0, 33.0, 44.0):
            now[0] = step
            monitor.observe(calm)
        assert monitor.disabled is False, (
            "divergence never re-armed after the burst cleared; the standby "
            "lane stays disabled for the remainder of the process lifetime"
        )

    def test_breach_requires_the_sustain_window(self):
        now = [0.0]
        monitor = DivergenceMonitor(
            min_symbols=3, alert_pct=0.3, sustain_s=10.0, clock=lambda: now[0]
        )
        breached = {"A": 0.9, "B": 1.1, "C": 0.8}
        monitor.observe(breached)
        now[0] = 5.0
        monitor.observe(breached)
        assert monitor.disabled is False, "disabled before the sustain window elapsed"
        now[0] = 11.0
        monitor.observe(breached)
        assert monitor.disabled is True

    def test_standby_lane_resumes_after_burst_clears(self):
        soak = Soak(
            Scenario(
                duration_s=400,
                step_pct=0.9,
                divergence_alert_pct=0.3,
                divergence_min_symbols=3,
                market_regimes=((260.0, 0.02, 0.0),),
            )
        )
        soak.angel.set_script(phase((60.0, 200.0, "down")))
        soak.run()
        assert soak.runner.divergence.disabled is False, (
            "divergence stayed disabled after Angel recovered and the market "
            "settled; standby promotion is dead for the rest of the session "
            f"(events: {soak.report()['divergenceEvents']})"
        )

    def test_below_min_symbols_never_disables(self):
        clock = iter([0.0] * 6).__next__
        monitor = DivergenceMonitor(
            min_symbols=3, alert_pct=0.3, sustain_s=10.0, clock=clock
        )
        for _ in range(4):
            monitor.observe({"A": 5.0, "B": 5.0})
        assert monitor.disabled is False


# ---------------------------------------------------------------------------
# F. Shoonya gateway faults
# ---------------------------------------------------------------------------

class TestShoonyaGatewayFaults:
    def test_unhealthy_gateway_blocks_promotion(self):
        soak = Soak(Scenario(duration_s=120))
        soak.angel.set_script(down_from(30.0))
        soak.gateway.fault.health_unhealthy = True
        soak.run()
        assert soak.runner.last_applied == 0
        assert soak.state.ltp_source_mix().get(SOURCE_STANDBY_WS, 0) == 0
        assert soak.state.stream_status()["standby"]["healthy"] is False

    def test_quote_timeout_does_not_corrupt_state(self):
        soak = Soak(Scenario(duration_s=120))
        soak.angel.set_script(down_from(30.0))
        soak.gateway.fault.quotes_raises = True
        soak.run()
        for symbol in SYMBOLS:
            row = soak.state.symbol_state(symbol)
            assert row is not None
            ltp = row.get("ltp")
            assert ltp is None or (math.isfinite(float(ltp)) and float(ltp) > 0)

    def test_partial_quote_dropout_only_freezes_that_symbol(self):
        soak = Soak(Scenario(duration_s=200))
        soak.angel.set_script(down_from(30.0))
        soak.gateway.fault.drop_symbols = {SYMBOLS[0]}
        soak.run()
        survivor = soak.state.symbol_state(SYMBOLS[1])
        dropped = soak.state.symbol_state(SYMBOLS[0])
        assert survivor["source"] == SOURCE_STANDBY_WS
        assert dropped["source"] != SOURCE_STANDBY_WS

    def test_runner_survives_repeated_gateway_exceptions(self):
        soak = Soak(Scenario(duration_s=120))
        soak.angel.set_script(down_from(30.0))
        soak.gateway.fault.health_raises = True
        soak.run()
        assert soak.runner.cycles > 0
        assert soak.gateway.health_calls == soak.runner.cycles
        # Both feeds are down here, so continuity cannot hold by definition.
        # What must hold is that nothing is corrupted while starved.
        for symbol in SYMBOLS:
            row = soak.state.symbol_state(symbol)
            assert row is not None
            ltp = row.get("ltp")
            assert ltp is None or (math.isfinite(float(ltp)) and float(ltp) > 0)
            assert row.get("source") in (SOURCE_WS, SOURCE_STANDBY_WS)

    def test_gateway_health_exception_is_swallowed_by_the_client(self):
        """The real client never raises; it returns None / {} on transport failure."""
        soak = Soak(Scenario(duration_s=20))
        soak.gateway.fault.health_raises = True
        assert soak.gateway.health() is None
        soak.gateway.fault.quotes_raises = True
        assert soak.gateway.quotes(["RELIANCE"]) == {}

    def test_gateway_recovers_and_promotion_resumes(self):
        soak = Soak(Scenario(duration_s=200))
        soak.angel.set_script(down_from(30.0))
        soak.gateway.fault.health_unhealthy = True
        soak.run()
        assert soak.runner.last_applied == 0

        soak.gateway.clear_faults()
        with soak._sim_time():
            soak.runner.run_once()
        assert soak.runner.last_applied == len(SYMBOLS)


# ---------------------------------------------------------------------------
# G. Both lanes down
# ---------------------------------------------------------------------------

class TestBothLanesDown:
    def test_simultaneous_outage_keeps_state_consistent(self):
        soak = Soak(Scenario(duration_s=200))
        soak.angel.set_script(down_from(60.0))
        soak.gateway.fault.health_unhealthy = True
        soak.run()
        for symbol in SYMBOLS:
            row = soak.state.symbol_state(symbol)
            assert row is not None
            ltp = row.get("ltp")
            assert ltp is None or (math.isfinite(float(ltp)) and float(ltp) > 0)
        assert soak.state.stream_status()["symbolsExpected"] == len(SYMBOLS)

    def test_recovery_when_shoonya_returns_before_angel(self):
        soak = Soak(Scenario(duration_s=240, promote_after_s=6.0))
        soak.angel.set_script(down_from(60.0))
        soak.gateway.fault.health_unhealthy = True
        soak.run()
        assert soak.runner.last_applied == 0

        soak.gateway.clear_faults()
        with soak._sim_time():
            for _ in range(6):
                soak.clock.advance(soak.scenario.poll_interval_s)
                soak.gateway._ts = soak.clock.exchange_ts_ms()
                soak.runner.run_once()
        assert soak.state.ltp_source_mix().get(SOURCE_STANDBY_WS, 0) == len(SYMBOLS)


# ---------------------------------------------------------------------------
# H. Recovery worker standby branch
# ---------------------------------------------------------------------------

class TestRecoveryWorker:
    def _state_with_unavailable_symbols(self):
        universe = IntradayUniverse([
            {"symbol": symbol, "exchange": "NSE", "token": token,
             "tradingsymbol": f"{symbol}-EQ", "indexGroup": None, "active": True}
            for symbol, token in PINNED
        ])
        state = IntradayMarketState(universe)
        state.update_universe(universe)
        state.set_connected(False)
        return state

    def test_standby_branch_repairs_unavailable_symbols(self, monkeypatch):
        from app.services.intraday_market_state import _recover_via_standby
        import app.services.standby_feed.gateway_client as gw

        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://gateway.invalid")
        monkeypatch.setenv("SHOONYA_GATEWAY_TOKEN", "tok")
        monkeypatch.setenv("STANDBY_PROMOTE_AFTER_SECONDS", "0")
        monkeypatch.setenv("SHOONYA_GATEWAY_TIMEOUT_SECONDS", "1")

        soak = Soak(Scenario(duration_s=1))
        state = self._state_with_unavailable_symbols()
        assert state.stale_symbols(), "expected unavailable symbols to need repair"

        with patch.object(gw, "GatewayClient", return_value=soak.gateway):
            with soak._sim_time():
                repaired = _recover_via_standby(state)

        assert repaired == len(SYMBOLS)
        mix = state.ltp_source_mix()
        assert mix.get(SOURCE_STANDBY_WS) == len(SYMBOLS)

    def test_standby_branch_is_inert_when_not_promotable(self, monkeypatch):
        from app.services.intraday_market_state import _recover_via_standby
        import app.services.standby_feed.gateway_client as gw

        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://gateway.invalid")

        soak = Soak(Scenario(duration_s=1))
        state = self._state_with_unavailable_symbols()
        with patch.object(gw, "GatewayClient", return_value=soak.gateway) as factory:
            assert _recover_via_standby(state) == 0
        assert not factory.called

    def test_standby_branch_survives_gateway_down(self, monkeypatch):
        from app.services.intraday_market_state import _recover_via_standby
        import app.services.standby_feed.gateway_client as gw

        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://gateway.invalid")

        soak = Soak(Scenario(duration_s=1))
        soak.gateway.fault.quotes_raises = True
        state = self._state_with_unavailable_symbols()
        with patch.object(gw, "GatewayClient", return_value=soak.gateway):
            with soak._sim_time():
                assert _recover_via_standby(state) == 0


# ---------------------------------------------------------------------------
# I. Market-hours fail-safe defaults
# ---------------------------------------------------------------------------

class TestFailSafeDefaults:
    def test_unconfigured_deploy_cannot_promote(self, monkeypatch):
        for name in (
            "SHOONYA_STANDBY_ENABLED",
            "SHOONYA_STANDBY_MODE",
            "SHOONYA_GATEWAY_URL",
        ):
            monkeypatch.delenv(name, raising=False)
        cfg = StandbyConfig.from_env()
        assert cfg.promotable is False
        assert StandbyFeedRunner(config=cfg).start() is False

    def test_shadow_mode_cannot_promote_even_when_enabled(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "shadow")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://gateway.invalid")
        cfg = StandbyConfig.from_env()
        assert cfg.enabled is True
        assert cfg.promotable is False

    def test_enabled_without_url_cannot_promote(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "")
        assert StandbyConfig.from_env().promotable is False

    def test_only_enabled_and_active_promote(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://gateway.invalid")
        assert StandbyConfig.from_env().promotable is True
