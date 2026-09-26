"""Shoonya/Finvasia standby market-data feature end-to-end validation.

Covers:
- Case A: Disabled mode (inert)
- Case B: Shadow mode (queries only, no promotion)
- Case C: Active failover with all guards
- Friday 2026-09-11 E2E replay
- Failure-path tests
- Runtime safety checks
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Allow shoonya_gateway imports when running from backend/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHOONYA_GATEWAY_DIR = _REPO_ROOT / "shoonya-gateway"
if str(_SHOONYA_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_SHOONYA_GATEWAY_DIR))

from app.services.intraday_market_state import (
    DEGRADED,
    LIVE,
    SOURCE_STANDBY_WS,
    SOURCE_WS,
    STALE,
    UNAVAILABLE,
    IntradayMarketState,
    IntradayUniverse,
)
from app.services.standby_feed.config import StandbyConfig
from app.services.standby_feed.divergence import DivergenceMonitor
from app.services.standby_feed.gateway_client import GatewayClient
from app.services.standby_feed.client import StandbyFeedRunner
from app.services.market_data_provider import (
    fetch_shoonya_candles,
    shoonya_gateway_configured,
)

IST = timezone(timedelta(hours=5, minutes=30))
FRIDAY_DATE = "2026-09-11"
FRIDAY_TS = datetime(2026, 9, 11, 9, 30, tzinfo=IST)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def universe() -> IntradayUniverse:
    rows = [
        {"symbol": "RELIANCE", "exchange": "NSE", "token": "2885",
         "tradingsymbol": "RELIANCE-EQ", "indexGroup": None, "active": True},
        {"symbol": "TCS", "exchange": "NSE", "token": "11536",
         "tradingsymbol": "TCS-EQ", "indexGroup": None, "active": True},
        {"symbol": "HDFCBANK", "exchange": "NSE", "token": "1333",
         "tradingsymbol": "HDFCBANK-EQ", "indexGroup": None, "active": True},
    ]
    return IntradayUniverse(rows)


@pytest.fixture()
def state(universe: IntradayUniverse) -> IntradayMarketState:
    s = IntradayMarketState(universe)
    s.update_universe(universe)
    return s


def _tick(ltp: float, seq: int | None = None, close: float | None = None):
    message = {"last_traded_price": int(ltp * 100)}
    if seq is not None:
        message["sequenceNumber"] = seq
    if close is not None:
        message["closed_price"] = int(close * 100)
    return message


# ---------------------------------------------------------------------------
# Case A — Disabled mode
# ---------------------------------------------------------------------------

class TestCaseADisabled:
    def test_config_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SHOONYA_STANDBY_ENABLED", raising=False)
        cfg = StandbyConfig.from_env()
        assert cfg.enabled is False
        assert cfg.mode == "shadow"
        assert cfg.promotable is False

    def test_disabled_runner_does_not_start(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        runner = StandbyFeedRunner()
        assert runner.start() is False

    def test_disabled_no_thread_spawned(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
        runner = StandbyFeedRunner()
        runner.start()
        assert runner._thread is None

    def test_disabled_angel_behavior_unchanged(self, state):
        assert state.apply_tick("2885", 1, _tick(2432.25, seq=10)) == "new"
        row = state.symbol_state("2885")
        assert row["source"] == SOURCE_WS
        assert row["ltp"] == 2432.25

    def test_disabled_no_standby_source_in_mix(self, state):
        state.apply_tick("2885", 1, _tick(100.0))
        mix = state.ltp_source_mix()
        assert mix.get(SOURCE_WS) == 1
        assert mix.get(SOURCE_STANDBY_WS, 0) == 0


# ---------------------------------------------------------------------------
# Case B — Shadow mode
# ---------------------------------------------------------------------------

class TestCaseBShadow:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "shadow")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://localhost:8080")
        monkeypatch.setenv("SHOONYA_GATEWAY_TOKEN", "tok")

    def test_shadow_config_promotable_false(self):
        cfg = StandbyConfig.from_env()
        assert cfg.enabled is True
        assert cfg.mode == "shadow"
        assert cfg.promotable is False

    def test_shadow_no_standby_ws_in_source_mix(self, state):
        state.apply_tick("2885", 1, _tick(100.0))
        mix = state.ltp_source_mix()
        assert mix.get(SOURCE_STANDBY_WS, 0) == 0


# ---------------------------------------------------------------------------
# Case C — Active failover
# ---------------------------------------------------------------------------

class TestCaseCActive:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://localhost:8080")
        monkeypatch.setenv("SHOONYA_GATEWAY_TOKEN", "tok")
        monkeypatch.setenv("STANDBY_PROMOTE_AFTER_SECONDS", "2")
        monkeypatch.setenv("STANDBY_BAND_PCT", "25")
        monkeypatch.setenv("STANDBY_HANDOFF_MAX_DIVERGENCE_PCT", "1.0")

    def test_active_config_promotable(self):
        cfg = StandbyConfig.from_env()
        assert cfg.enabled is True
        assert cfg.mode == "active"
        assert cfg.promotable is True

    def test_fresh_angel_wins_over_shoonya(self, state):
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        mono = time.monotonic()
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = mono
        with patch("time.monotonic", return_value=mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "rejected_primary_fresh"
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_WS
        assert row["ltp"] == 2432.25

    def test_stale_angel_promotes_shoonya(self, state):
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "applied"
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_STANDBY_WS
        assert row["ltp"] == 2433.0
        assert row["failover"] is True

    def test_angel_recovery_regains_authority(self, state):
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        fresh_mono = time.monotonic()
        with patch("time.monotonic", return_value=fresh_mono):
            result = state.apply_tick("2885", 1, _tick(2435.0, seq=11))
        assert result == "new"
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_WS
        assert row["ltp"] == 2435.0

    def test_stale_date_rejected(self, state):
        friday = datetime(2026, 9, 11, 10, 0, tzinfo=IST)
        sunday = datetime(2026, 9, 13, 10, 0, tzinfo=IST)
        with patch("app.services.intraday_market_state._now_utc", return_value=sunday):
            outcome = state.apply_standby_tick(
                "RELIANCE",
                {"ltp": 100.0, "exchangeTsMs": int(friday.timestamp() * 1000)},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_date"

    def test_negative_price_rejected(self, state):
        with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
            outcome = state.apply_standby_tick(
                "RELIANCE",
                {"ltp": -10.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_invalid"

    def test_zero_price_rejected(self, state):
        with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
            outcome = state.apply_standby_tick(
                "RELIANCE",
                {"ltp": 0.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_invalid"

    def test_abnormal_band_rejected(self, state):
        state.apply_tick("2885", 1, _tick(100.0, close=100.0))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        with patch("time.monotonic", return_value=time.monotonic()):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 200.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=0.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "rejected_band"

    def test_divergence_guard_quarantines(self, state):
        state.apply_tick("2885", 1, _tick(100.0))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 200.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=0.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "quarantined_divergence"
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_WS

    def test_no_promotion_before_threshold(self, state):
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 1.5
        mono = time.monotonic()
        with patch("time.monotonic", return_value=mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "rejected_primary_fresh"

    def test_provenance_shoonya_ws(self, state):
        with state._lock:
            state._state["RELIANCE"] = {
                "symbol": "RELIANCE", "token": "2885", "ltp": None,
                "prevClose": None, "exchangeTimestamp": None, "receivedAt": None,
                "receivedMonotonic": time.monotonic() - 10.0, "sequence": None,
                "source": SOURCE_WS, "connected": False, "stale": True,
                "oi": None, "tradeVolume": None, "tickCount": 0, "bar5m": None,
            }
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=0.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_STANDBY_WS

    def test_rest_quote_does_not_override_shoonya_without_fresh_ws(self, state):
        with state._lock:
            state._state["RELIANCE"] = {
                "symbol": "RELIANCE", "token": "2885", "ltp": None,
                "prevClose": None, "exchangeTimestamp": None, "receivedAt": None,
                "receivedMonotonic": time.monotonic() - 10.0, "sequence": None,
                "source": SOURCE_WS, "connected": False, "stale": True,
                "oi": None, "tradeVolume": None, "tickCount": 0, "bar5m": None,
            }
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=0.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        state.apply_rest_quote("RELIANCE", {"ltp": 2400.0}, source="ANGEL_REST_RECOVERY")
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_STANDBY_WS


# ---------------------------------------------------------------------------
# DivergenceMonitor tests
# ---------------------------------------------------------------------------

class TestDivergenceMonitor:
    def test_not_disabled_initially(self):
        dm = DivergenceMonitor(min_symbols=3, alert_pct=0.3)
        assert dm.disabled is False

    def test_disabled_after_sustained_breach(self):
        dm = DivergenceMonitor(min_symbols=3, alert_pct=0.3, sustain_s=0.0)
        clock = iter([0.0, 0.0]).__next__
        dm = DivergenceMonitor(min_symbols=3, alert_pct=0.3, sustain_s=0.0, clock=clock)
        dm.observe({"A": 0.5, "B": 0.6, "C": 0.7})
        dm.observe({"A": 0.5, "B": 0.6, "C": 0.7})
        assert dm.disabled is True

    def test_clears_on_recovery(self):
        clock = iter([0.0, 0.0, 1.0]).__next__
        dm = DivergenceMonitor(min_symbols=3, alert_pct=0.3, sustain_s=0.0, clock=clock)
        dm.observe({"A": 0.5, "B": 0.6, "C": 0.7})
        dm.observe({"A": 0.5, "B": 0.6, "C": 0.7})
        assert dm.disabled is True
        dm.clear()
        assert dm.disabled is False

    def test_snapshot_returns_state(self):
        clock = iter([0.0, 0.0]).__next__
        dm = DivergenceMonitor(min_symbols=2, alert_pct=0.3, sustain_s=0.0, clock=clock)
        dm.observe({"A": 0.5, "B": 0.6})
        dm.observe({"A": 0.5, "B": 0.6})
        snap = dm.snapshot()
        assert snap["disabled"] is True
        assert "A" in snap["offenders"]


# ---------------------------------------------------------------------------
# GatewayClient tests
# ---------------------------------------------------------------------------

class TestGatewayClient:
    def test_unconfigured_returns_none_or_empty(self):
        cfg = StandbyConfig.from_env()
        client = GatewayClient(cfg)
        assert client.health() is None
        assert client.quotes(["X"]) == {}
        assert client.pin("o", ["X"]) is False
        assert client.unpin("o") is False
        assert client.candles("X", "1", 0, 1) == {"status": "UNCONFIGURED", "rows": []}

    def test_health_failure_returns_none(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://localhost:8080")
        cfg = StandbyConfig.from_env()
        client = GatewayClient(cfg)
        with patch("requests.get", side_effect=ConnectionError("down")):
            assert client.health() is None

    def test_quotes_failure_returns_empty(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://localhost:8080")
        cfg = StandbyConfig.from_env()
        client = GatewayClient(cfg)
        with patch("requests.get", side_effect=ConnectionError("down")):
            assert client.quotes(["X"]) == {}


# ---------------------------------------------------------------------------
# Friday E2E replay
# ---------------------------------------------------------------------------

class TestFridayE2E:
    FRIDAY = "2026-09-11"

    def _make_state(self):
        universe = IntradayUniverse([
            {"symbol": "RELIANCE", "exchange": "NSE", "token": "2885",
             "tradingsymbol": "RELIANCE-EQ", "indexGroup": None, "active": True},
        ])
        state = IntradayMarketState(universe)
        state.update_universe(universe)
        return state

    def test_t0_angel_ws_is_authoritative(self):
        state = self._make_state()
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_WS
        assert row["ltp"] == 2432.25
        assert row["freshness"] == LIVE

    def test_t1_shoonya_does_not_promote_before_threshold(self):
        state = self._make_state()
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 1.0
        mono = time.monotonic()
        with patch("time.monotonic", return_value=mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "rejected_primary_fresh"
        assert state.symbol_state("RELIANCE")["source"] == SOURCE_WS

    def test_t2_shoonya_promotes_after_stale_threshold(self):
        state = self._make_state()
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "applied"
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_STANDBY_WS
        assert row["ltp"] == 2433.0
        assert row["dataStale"] is False

    def test_t3_locked_position_uses_shoonya_mark(self):
        state = self._make_state()
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        row = state.symbol_state("RELIANCE")
        assert row["ltp"] == 2433.0
        assert row["source"] == SOURCE_STANDBY_WS
        assert row["dataStale"] is False

    def test_t4_angel_recovery_handback_no_duplicate_transitions(self):
        state = self._make_state()
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        gen_before = state.generation
        fresh_mono = time.monotonic()
        with patch("time.monotonic", return_value=fresh_mono):
            result = state.apply_tick("2885", 1, _tick(2435.0, seq=11))
        assert result == "new"
        row = state.symbol_state("RELIANCE")
        assert row["source"] == SOURCE_WS
        assert row["ltp"] == 2435.0
        assert state.generation == gen_before + 1

    def test_t5_eod_reconciliation_consistency(self):
        state = self._make_state()
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        snap = state.capture_snapshot()
        assert "RELIANCE" in snap["quotes"]
        q = snap["quotes"]["RELIANCE"]
        assert q["source"] == SOURCE_STANDBY_WS


# ---------------------------------------------------------------------------
# Failure-path tests
# ---------------------------------------------------------------------------

class TestFailurePaths:
    def test_shoonya_gateway_unavailable(self, monkeypatch, state):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://localhost:8080")
        cfg = StandbyConfig.from_env()
        client = GatewayClient(cfg)
        with patch("requests.get", side_effect=ConnectionError("down")):
            health = client.health()
            assert health is None

    def test_shoonya_health_unhealthy(self, monkeypatch, state):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_STANDBY_MODE", "active")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://localhost:8080")
        cfg = StandbyConfig.from_env()
        client = GatewayClient(cfg)

        class FakeResp:
            status_code = 200
            def raise_for_status(self):
                return None
            def json(self):
                return {"healthy": False, "auth": {}}

        with patch("requests.get", return_value=FakeResp()):
            health = client.health()
            assert health is not None
            assert health.get("healthy") is False

    def test_shoonya_quote_missing_ltp(self, state):
        with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
            stale_mono = time.monotonic() - 10.0
            with patch("time.monotonic", return_value=stale_mono):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"status": "OK", "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=0.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "rejected_invalid"

    def test_shoonya_negative_price(self, state):
        with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
            outcome = state.apply_standby_tick(
                "RELIANCE",
                {"ltp": -5.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_invalid"

    def test_shoonya_zero_price(self, state):
        with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
            outcome = state.apply_standby_tick(
                "RELIANCE",
                {"ltp": 0.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_invalid"

    def test_shoonya_stale_date(self, state):
        friday = datetime(2026, 9, 11, 10, 0, tzinfo=IST)
        sunday = datetime(2026, 9, 13, 10, 0, tzinfo=IST)
        with patch("app.services.intraday_market_state._now_utc", return_value=sunday):
            outcome = state.apply_standby_tick(
                "RELIANCE",
                {"ltp": 100.0, "exchangeTsMs": int(friday.timestamp() * 1000)},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_date"

    def test_shoonya_weekend_replay_rejected(self, state):
        saturday = datetime(2026, 9, 12, 10, 0, tzinfo=IST)
        friday = datetime(2026, 9, 11, 10, 0, tzinfo=IST)
        with patch("app.services.intraday_market_state._now_utc", return_value=saturday):
            outcome = state.apply_standby_tick(
                "RELIANCE",
                {"ltp": 100.0, "exchangeTsMs": int(friday.timestamp() * 1000)},
                promote_after_s=0.0,
                band_pct=25.0,
                handoff_divergence_pct=1.0,
            )
        assert outcome == "rejected_date"

    def test_shoonya_price_outside_band(self, state):
        state.apply_tick("2885", 1, _tick(100.0, close=100.0))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        with patch("time.monotonic", return_value=time.monotonic()):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 200.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=0.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "rejected_band"

    def test_divergence_above_threshold_quarantines(self, state):
        state.apply_tick("2885", 1, _tick(100.0))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                outcome = state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 200.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=0.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        assert outcome == "quarantined_divergence"

    def test_token_not_in_registry(self, state):
        outcome = state.apply_standby_tick(
            "UNKNOWN",
            {"ltp": 100.0},
            promote_after_s=0.0,
            band_pct=25.0,
            handoff_divergence_pct=1.0,
        )
        row = state.symbol_state("UNKNOWN")
        assert row is not None
        assert row["ltp"] == 100.0

    def test_candle_fallback_disabled(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
        monkeypatch.setenv("SHOONYA_CANDLES_ENABLED", "0")
        assert shoonya_gateway_configured() is False

    def test_candle_fallback_enabled_but_gateway_missing(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_CANDLES_ENABLED", "1")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "")
        assert shoonya_gateway_configured() is False

    def test_rest_circuit_open_behavior(self, monkeypatch):
        from app.services.intraday_market_state import _RecoveryCircuit
        circuit = _RecoveryCircuit(threshold=2, cooldown=10.0)
        circuit.record_failure()
        assert circuit.allow() is True
        circuit.record_failure()
        assert circuit.allow() is False

    def test_rest_circuit_half_open_after_cooldown(self, monkeypatch):
        from app.services.intraday_market_state import _RecoveryCircuit
        circuit = _RecoveryCircuit(threshold=2, cooldown=10.0)
        circuit.record_failure()
        circuit.record_failure()
        assert circuit.allow() is False
        with patch("time.monotonic", return_value=time.monotonic() + 11.0):
            assert circuit.allow() is True

    def test_angel_recovery_no_duplicate_exit(self, state):
        state.apply_tick("2885", 1, _tick(2432.25, seq=10))
        with state._lock:
            state._state["2885"]["receivedMonotonic"] = time.monotonic() - 10.0
        stale_mono = time.monotonic()
        with patch("time.monotonic", return_value=stale_mono):
            with patch("app.services.intraday_market_state._now_utc", return_value=FRIDAY_TS):
                state.apply_standby_tick(
                    "RELIANCE",
                    {"ltp": 2433.0, "exchangeTsMs": int(FRIDAY_TS.timestamp() * 1000)},
                    promote_after_s=2.0,
                    band_pct=25.0,
                    handoff_divergence_pct=1.0,
                )
        gen_before = state.generation
        fresh_mono = time.monotonic()
        with patch("time.monotonic", return_value=fresh_mono):
            state.apply_tick("2885", 1, _tick(2435.0, seq=11))
        assert state.generation == gen_before + 1


# ---------------------------------------------------------------------------
# Runtime safety tests
# ---------------------------------------------------------------------------

class TestRuntimeSafety:
    def test_no_secrets_in_config_strings(self):
        cfg = StandbyConfig.from_env()
        s = str(cfg)
        assert "password" not in s.lower()
        assert "secret" not in s.lower()

    def test_backend_imports_standby_modules(self):
        from app.services.standby_feed import client, config, divergence, gateway_client, subscription_planner
        assert client is not None
        assert config is not None
        assert divergence is not None
        assert gateway_client is not None
        assert subscription_planner is not None

    def test_main_starts_without_gateway(self, monkeypatch):
        monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
        monkeypatch.setenv("SHOONYA_GATEWAY_URL", "")
        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)
        assert main_mod.STANDBY_FEED_STARTED is False

class TestGatewayAllowlist:
    def test_allowed_quotes_path(self):
        from gateway.allowlist import assert_allowed
        assert assert_allowed("/NorenWClientAPI/GetQuotes") == "/NorenWClientAPI/GetQuotes"

    def test_allowed_tpseries_path(self):
        from gateway.allowlist import assert_allowed
        assert assert_allowed("/NorenWClientAPI/TPSeries") == "/NorenWClientAPI/TPSeries"

    def test_allowed_searchscrip_path(self):
        from gateway.allowlist import assert_allowed
        assert assert_allowed("/NorenWClientAPI/SearchScrip") == "/NorenWClientAPI/SearchScrip"

    def test_forbidden_place_order(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/PlaceOrder")

    def test_forbidden_modify_order(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/ModifyOrder")

    def test_forbidden_cancel_order(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/CancelOrder")

    def test_forbidden_exit_order(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/ExitOrder")

    def test_forbidden_orderbook(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/OrderBook")

    def test_forbidden_tradebook(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/TradeBook")

    def test_forbidden_positionbook(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/PositionBook")

    def test_forbidden_holdings(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/Holdings")

    def test_forbidden_limits(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/Limits")

    def test_forbidden_gtt(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/GTT")

    def test_forbidden_product_conversion(self):
        from gateway.allowlist import assert_allowed, EndpointNotAllowed
        with pytest.raises(EndpointNotAllowed):
            assert_allowed("/NorenWClientAPI/ProductConversion")


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_registry_load_text(self):
        from gateway.registry import InstrumentRegistry
        reg = InstrumentRegistry()
        count = reg.load_text("token,tradingsymbol\n12345,RELIANCE-EQ\n")
        assert count >= 1
        assert reg.token_for("RELIANCE") == "12345"
        assert reg.symbol_for("NSE", "12345") == "RELIANCE"

    def test_registry_stale_check(self):
        from gateway.registry import InstrumentRegistry
        from datetime import date
        reg = InstrumentRegistry()
        reg._by_symbol = {"RELIANCE": "12345"}
        reg.loaded_on = date(2026, 1, 1)
        assert reg.is_stale(today=date(2026, 1, 2), max_age_days=1) is False
        assert reg.is_stale(today=date(2026, 1, 3), max_age_days=1) is True


# ---------------------------------------------------------------------------
# Mapper tests
# ---------------------------------------------------------------------------

class TestMapper:
    def test_norm_symbol_strips_suffixes(self):
        from gateway.mapper import norm_symbol
        assert norm_symbol("RELIANCE-EQ") == "RELIANCE"
        assert norm_symbol("TCS-BE") == "TCS"
        assert norm_symbol("INFY-BZ") == "INFY"

    def test_positive_rejects_zero_and_negative(self):
        from gateway.mapper import positive
        assert positive(0.0) is None
        assert positive(-1.0) is None
        assert positive(10.0) == 10.0

    def test_positive_rejects_non_finite(self):
        from gateway.mapper import positive
        import math
        assert positive(float("inf")) is None
        assert positive(float("-inf")) is None
        assert positive(float("nan")) is None
