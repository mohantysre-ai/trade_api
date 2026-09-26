"""Thin, defensive requests-based client for the shoonya-gateway internal API."""
from __future__ import annotations

import logging
from typing import Any

import requests

from .config import StandbyConfig

LOGGER = logging.getLogger(__name__)


class GatewayClient:
    def __init__(self, config: StandbyConfig) -> None:
        self._cfg = config

    @property
    def configured(self) -> bool:
        return bool(self._cfg.gateway_url)

    def _headers(self) -> dict[str, str]:
        if self._cfg.gateway_token:
            return {"Authorization": f"Bearer {self._cfg.gateway_token}"}
        return {}

    def health(self) -> dict[str, Any] | None:
        if not self.configured:
            return None
        try:
            resp = requests.get(f"{self._cfg.gateway_url}/v1/health", timeout=self._cfg.request_timeout_s)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            LOGGER.debug("shoonya gateway health check failed: %s", type(exc).__name__)
            return None

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not self.configured or not symbols:
            return {}
        try:
            resp = requests.get(
                f"{self._cfg.gateway_url}/v1/quotes",
                params={"symbols": ",".join(symbols)},
                headers=self._headers(),
                timeout=self._cfg.request_timeout_s,
            )
            resp.raise_for_status()
            return (resp.json() or {}).get("quotes") or {}
        except Exception as exc:
            LOGGER.debug("shoonya gateway quotes fetch failed: %s", type(exc).__name__)
            return {}

    def pin(self, owner: str, symbols: list[str], ttl_seconds: float | None = None) -> bool:
        if not self.configured:
            return False
        try:
            resp = requests.post(
                f"{self._cfg.gateway_url}/v1/pin",
                json={"owner": owner, "symbols": symbols, "ttlSeconds": ttl_seconds},
                headers=self._headers(),
                timeout=self._cfg.request_timeout_s,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            LOGGER.debug("shoonya gateway pin failed: %s", type(exc).__name__)
            return False

    def unpin(self, owner: str) -> bool:
        if not self.configured:
            return False
        try:
            resp = requests.post(
                f"{self._cfg.gateway_url}/v1/unpin",
                json={"owner": owner},
                headers=self._headers(),
                timeout=self._cfg.request_timeout_s,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            LOGGER.debug("shoonya gateway unpin failed: %s", type(exc).__name__)
            return False

    def candles(self, symbol: str, interval: str, start_ts: int, end_ts: int) -> dict[str, Any]:
        if not self.configured:
            return {"status": "UNCONFIGURED", "rows": []}
        try:
            resp = requests.get(
                f"{self._cfg.gateway_url}/v1/candles",
                params={"symbol": symbol, "interval": interval, "from": start_ts, "to": end_ts},
                headers=self._headers(),
                timeout=self._cfg.request_timeout_s,
            )
            resp.raise_for_status()
            return resp.json() or {"status": "ERROR", "rows": []}
        except Exception as exc:
            LOGGER.debug("shoonya gateway candles fetch failed: %s", type(exc).__name__)
            return {"status": "ERROR", "rows": [], "error": type(exc).__name__}
