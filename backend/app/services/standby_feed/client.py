"""Background poller for the Shoonya standby lane."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import StandbyConfig
from .divergence import DivergenceMonitor
from .gateway_client import GatewayClient
from .subscription_planner import compute_p0_symbols

LOGGER = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
PIN_OWNER = "iros-p0"


class StandbyFeedRunner:
    def __init__(self, config: StandbyConfig | None = None, client: GatewayClient | None = None) -> None:
        self.config = config or StandbyConfig.from_env()
        self.client = client or GatewayClient(self.config)
        self.divergence = DivergenceMonitor(self.config.divergence_min_symbols, self.config.divergence_alert_pct)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.cycles = 0
        self.last_applied = 0
        self.last_quarantined = 0

    def start(self) -> bool:
        if not self.config.enabled:
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return True
            self._thread = threading.Thread(target=self._run, name="shoonya-standby-feed", daemon=True)
            self._thread.start()
            return True

    def _run(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                LOGGER.exception("shoonya standby feed cycle failed")
            time.sleep(max(0.5, self.config.poll_interval_s))

    def run_once(self) -> None:
        from ..intraday_market_state import get_intraday_market_state
        self.cycles += 1
        state = get_intraday_market_state()
        health = self.client.health()
        state.set_standby_health({**(health or {"healthy": False}), "mode": self.config.mode, "cycles": self.cycles})
        healthy = bool(health and health.get("healthy"))
        day = datetime.now(IST).date().isoformat()
        symbols = compute_p0_symbols(day)
        if symbols:
            self.client.pin(PIN_OWNER, symbols, ttl_seconds=self.config.pin_ttl_s)
        if not healthy or not symbols:
            return
        quotes = self.client.quotes(symbols)
        snapshot = state.capture_snapshot(symbols)
        primary = snapshot.get("quotes") or {}
        deltas: dict[str, float] = {}
        applied = 0
        quarantined = 0
        for symbol, wire in quotes.items():
            if not isinstance(wire, dict) or wire.get("status") == "NOT_SUBSCRIBED":
                continue
            ltp = wire.get("ltp")
            prim = primary.get(symbol) or {}
            prim_ltp = prim.get("ltp")
            prim_age = prim.get("dataAge")
            if isinstance(ltp, (int, float)) and isinstance(prim_ltp, (int, float)) and prim_ltp and prim_age is not None and prim_age <= 120.0:
                deltas[symbol] = abs(ltp - prim_ltp) / prim_ltp * 100.0
            if self.config.promotable and not self.divergence.disabled:
                outcome = state.apply_standby_tick(
                    symbol, wire,
                    promote_after_s=self.config.promote_after_s,
                    band_pct=self.config.band_pct,
                    handoff_divergence_pct=self.config.handoff_divergence_pct,
                )
                if outcome == "applied":
                    applied += 1
                elif outcome == "quarantined_divergence":
                    quarantined += 1
        self.divergence.observe(deltas)
        self.last_applied = applied
        self.last_quarantined = quarantined

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled, "mode": self.config.mode, "cycles": self.cycles,
            "lastApplied": self.last_applied, "lastQuarantined": self.last_quarantined,
            "divergence": self.divergence.snapshot(),
        }


_RUNNER: StandbyFeedRunner | None = None
_RUNNER_LOCK = threading.Lock()


def get_standby_feed_runner() -> StandbyFeedRunner:
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = StandbyFeedRunner()
        return _RUNNER


def start_standby_feed() -> bool:
    return get_standby_feed_runner().start()
