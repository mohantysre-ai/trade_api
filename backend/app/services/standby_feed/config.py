from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class StandbyConfig:
    enabled: bool
    mode: str
    gateway_url: str
    gateway_token: str
    poll_interval_s: float
    pin_ttl_s: float
    promote_after_s: float
    band_pct: float
    handoff_divergence_pct: float
    divergence_alert_pct: float
    divergence_min_symbols: int
    candles_enabled: bool
    request_timeout_s: float

    @classmethod
    def from_env(cls) -> "StandbyConfig":
        return cls(
            enabled=_bool("SHOONYA_STANDBY_ENABLED", "0"),
            mode=os.getenv("SHOONYA_STANDBY_MODE", "shadow").strip().lower(),
            gateway_url=os.getenv("SHOONYA_GATEWAY_URL", "").rstrip("/"),
            gateway_token=os.getenv("SHOONYA_GATEWAY_TOKEN", ""),
            poll_interval_s=_f("SHOONYA_STANDBY_POLL_INTERVAL_SECONDS", 2.0),
            pin_ttl_s=_f("SHOONYA_STANDBY_PIN_TTL_SECONDS", 600.0),
            promote_after_s=_f("STANDBY_PROMOTE_AFTER_SECONDS", 8.0),
            band_pct=_f("STANDBY_BAND_PCT", 25.0),
            handoff_divergence_pct=_f("STANDBY_HANDOFF_MAX_DIVERGENCE_PCT", 1.0),
            divergence_alert_pct=_f("STANDBY_DIVERGENCE_ALERT_PCT", 0.3),
            divergence_min_symbols=int(_f("STANDBY_DIVERGENCE_MIN_SYMBOLS", 3)),
            candles_enabled=_bool("SHOONYA_CANDLES_ENABLED", "0"),
            request_timeout_s=_f("SHOONYA_GATEWAY_TIMEOUT_SECONDS", 3.0),
        )

    @property
    def promotable(self) -> bool:
        return self.enabled and self.mode == "active" and bool(self.gateway_url)
