"""Diagnostics for EOD/Index Options discrepancy and Angel feed health."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_angel_circuit_state_returns_json() -> None:
    resp = client.get("/api/diagnostics/angel-circuit-state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "circuitOpen" in body
    assert "callsAllowed" in body
    assert "configuredCircuitSeconds" in body


def test_eod_warm_caches_returns_success(monkeypatch) -> None:
    called: dict[str, Any] = {}

    def fake_warm(for_date) -> dict[str, Any]:
        called["date"] = for_date
        return {"intraday": True, "swing": True, "indexOptions": True}

    monkeypatch.setattr("app.services.eod_book_cache.warm_book_caches", fake_warm)
    resp = client.post("/api/eod/warm-caches?date=2026-09-17")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["date"] == "2026-09-17"
    assert called["date"].isoformat() == "2026-09-17"


def test_angel_option_chain_diagnostic_falls_back_on_error() -> None:
    with patch("app.services.angel_one_feed.AngelOneClient", side_effect=RuntimeError("no creds")):
        resp = client.get("/api/diagnostics/angel-option-chain")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "error" in body


def test_index_options_force_refresh_bypasses_cache() -> None:
    with (
        patch("app.services.index_options_live.compose_live_index_options_radar") as mock_compose,
        patch("app.services.angel_one_feed.ensure_fresh_market_snapshot", return_value={}),
        patch("app.services.angel_one_feed.AngelOneClient", return_value=object()),
    ):
        mock_compose.return_value = {"success": True, "cacheStatus": "FORCED"}
        resp = client.get("/api/index-options?force=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["cacheStatus"] == "FORCED"
    assert mock_compose.called


def test_eod_warm_caches_defaults_to_today() -> None:
    today = datetime.now(tz=timezone.utc).date()
    with patch("app.services.eod_book_cache.warm_book_caches") as mock_warm:
        mock_warm.return_value = {"intraday": True, "swing": True, "indexOptions": True}
        resp = client.post("/api/eod/warm-caches")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["date"] == today.isoformat()
    assert mock_warm.called
    assert mock_warm.call_args[0][0].isoformat() == today.isoformat()
