"""Shoonya candle-backup coverage for Swing V2 and index-options structure.

The hot-standby gateway must be consumable as a candle backup by:
- ``swing_v2.market_data.historical_bars`` (neutral Swing boundary), and
- ``angel_index_options`` index-spot structure candles.

Both fallbacks fail closed: an unconfigured gateway or an unresolvable symbol
yields no bars, never fabricated data.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Allow gateway.* imports when running from backend/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHOONYA_GATEWAY_DIR = _REPO_ROOT / "shoonya-gateway"
if str(_SHOONYA_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_SHOONYA_GATEWAY_DIR))


def _enable_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "1")
    monkeypatch.setenv("SHOONYA_CANDLES_ENABLED", "1")
    monkeypatch.setenv("SHOONYA_GATEWAY_URL", "http://gateway.internal")


_CANDLES = [
    ["2026-09-11 09:20:00", 100.0, 101.0, 99.5, 100.5, 1200.0],
    ["2026-09-11 09:25:00", 100.5, 102.0, 100.0, 101.5, 1400.0],
]


# ---------------------------------------------------------------------------
# swing_v2.market_data.historical_bars
# ---------------------------------------------------------------------------

def test_swing_historical_bars_falls_back_to_shoonya(monkeypatch):
    from app.services.swing_v2 import market_data as md

    monkeypatch.setattr(
        "app.services.market_data_provider.fetch_nse_candles",
        lambda *args, **kwargs: [],
    )
    captured: dict[str, Any] = {}

    def fake_shoonya(symbol, interval, fromdate, todate, exchange="NSE"):
        captured["symbol"] = symbol
        captured["interval"] = interval
        captured["exchange"] = exchange
        return [list(row) for row in _CANDLES]

    monkeypatch.setattr(
        "app.services.market_data_provider.fetch_shoonya_candles", fake_shoonya
    )

    bars = md.historical_bars("RELIANCE", "FIVE_MINUTE", 50)
    assert len(bars) == 2
    assert bars[0]["source"] == "SHOONYA_GATEWAY"
    assert bars[-1]["close"] == 101.5
    assert captured["symbol"] == "RELIANCE"
    assert captured["exchange"] == "NSE"


def test_swing_historical_bars_prefers_nse_charting(monkeypatch):
    from app.services.swing_v2 import market_data as md

    calls: dict[str, int] = {"shoonya": 0}

    monkeypatch.setattr(
        "app.services.market_data_provider.fetch_nse_candles",
        lambda *args, **kwargs: [list(row) for row in _CANDLES],
    )

    def fail_shoonya(*args, **kwargs):
        calls["shoonya"] += 1
        return []

    monkeypatch.setattr(
        "app.services.market_data_provider.fetch_shoonya_candles", fail_shoonya
    )

    bars = md.historical_bars("RELIANCE", "FIVE_MINUTE", 50)
    assert len(bars) == 2
    assert bars[0]["source"] == "NSE_CHARTING"
    assert calls["shoonya"] == 0


def test_swing_historical_bars_fail_closed_without_providers(monkeypatch):
    from app.services.swing_v2 import market_data as md

    monkeypatch.setattr(
        "app.services.market_data_provider.fetch_nse_candles",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
    monkeypatch.setenv("SHOONYA_CANDLES_ENABLED", "0")
    monkeypatch.delenv("SHOONYA_GATEWAY_URL", raising=False)

    assert md.historical_bars("RELIANCE", "FIVE_MINUTE", 50) == []


# ---------------------------------------------------------------------------
# angel_index_options structure candles
# ---------------------------------------------------------------------------

def _index_config() -> dict[str, Any]:
    from app.services.angel_index_options import INDEXES

    return dict(INDEXES[0])


def test_options_structure_uses_official_spot_symbol(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.services import angel_index_options as aio

    config = _index_config()
    captured: dict[str, list[str]] = {}

    def fake_shoonya(symbol, interval, fromdate, todate, exchange="NSE"):
        captured.setdefault("symbols", []).append(symbol)
        return []

    monkeypatch.setattr(
        "app.services.market_data_provider.fetch_shoonya_candles", fake_shoonya
    )
    ist = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 9, 11, 9, 15, tzinfo=ist)
    end = datetime(2026, 9, 11, 9, 30, tzinfo=ist)

    rows, error = aio._fetch_shoonya_index_candles(config, start, end)
    assert rows == []
    assert error == "SHOONYA_EMPTY"
    assert captured["symbols"] == ["Nifty 50"]


def test_options_structure_shoonya_backup_used_when_angel_empty(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.services import angel_index_options as aio
    from app.services.market_data_provider import fetch_shoonya_candles as _unused

    config = _index_config()
    ist = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 9, 11, 9, 15, tzinfo=ist)
    end = datetime(2026, 9, 11, 9, 30, tzinfo=ist)
    captured: dict[str, Any] = {}

    def fake_shoonya(symbol, interval, fromdate, todate, exchange="NSE"):
        captured["symbol"] = symbol
        captured["exchange"] = exchange
        return [list(row) for row in _CANDLES]

    monkeypatch.setattr(
        "app.services.market_data_provider.fetch_shoonya_candles", fake_shoonya
    )

    rows, error = aio._fetch_shoonya_index_candles(config, start, end)
    assert error is None
    assert rows == _CANDLES
    assert captured["symbol"] == "Nifty 50"
    assert captured["exchange"] == "NFO"


def test_options_structure_shoonya_backup_fails_closed(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.services import angel_index_options as aio

    config = _index_config()
    ist = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 9, 11, 9, 15, tzinfo=ist)
    end = datetime(2026, 9, 11, 9, 30, tzinfo=ist)
    monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
    monkeypatch.setenv("SHOONYA_CANDLES_ENABLED", "0")
    monkeypatch.delenv("SHOONYA_GATEWAY_URL", raising=False)

    rows, error = aio._fetch_shoonya_index_candles(config, start, end)
    assert rows == []
    assert error == "SHOONYA_EMPTY"


# ---------------------------------------------------------------------------
# market_data_provider / gateway client plumbing
# ---------------------------------------------------------------------------

def test_fetch_shoonya_candles_forwards_exchange(monkeypatch):
    from datetime import datetime, timedelta, timezone

    import app.services.market_data_provider as mdp

    _enable_gateway(monkeypatch)
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, _config):
            pass

        def candles(self, symbol, interval, start_ts, end_ts, *, exchange="NSE"):
            captured.update(symbol=symbol, interval=interval, exchange=exchange)
            return {"status": "OK", "rows": [list(row) for row in _CANDLES]}

    monkeypatch.setattr(
        "app.services.standby_feed.gateway_client.GatewayClient", FakeClient
    )
    ist = timezone(timedelta(hours=5, minutes=30))
    rows = mdp.fetch_shoonya_candles(
        "nifty 50",
        "FIVE_MINUTE",
        datetime(2026, 9, 11, 9, 15, tzinfo=ist),
        datetime(2026, 9, 11, 9, 30, tzinfo=ist),
        exchange="NFO",
    )
    assert rows == _CANDLES
    assert captured["symbol"] == "NIFTY 50"
    assert captured["exchange"] == "NFO"


def test_fetch_shoonya_candles_unconfigured_returns_empty(monkeypatch):
    import app.services.market_data_provider as mdp

    monkeypatch.setenv("SHOONYA_STANDBY_ENABLED", "0")
    monkeypatch.setenv("SHOONYA_CANDLES_ENABLED", "0")
    monkeypatch.delenv("SHOONYA_GATEWAY_URL", raising=False)

    assert mdp.fetch_shoonya_candles("RELIANCE", "FIVE_MINUTE", 0, 0) == []


# ---------------------------------------------------------------------------
# Gateway-side: exchange-aware registry + broker
# ---------------------------------------------------------------------------

def _nfo_master_csv() -> str:
    return (
        "Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument\n"
        "NFO,26000,1,Nifty 50,Nifty 50,,INDEX\n"
        "NFO,49680,75,NIFTY,NIFTY28OCT24500CE,28-10-2026,OPTIDX\n"
        "NFO,49681,75,NIFTY,NIFTY28OCT24500PE,28-10-2026,OPTIDX\n"
    )


def test_registry_set_resolves_option_contracts():
    from gateway.registry import RegistrySet

    registry_set = RegistrySet()
    assert registry_set.nfo.load_text(_nfo_master_csv(), today=None) == 3
    assert registry_set.token_for("NFO", "NIFTY28OCT24500CE") == "49680"
    assert registry_set.token_for("NFO", "Nifty 50") == "26000"
    assert registry_set.token_for("NSE", "NIFTY28OCT24500CE") is None


def test_registry_set_stale_covers_all_masters():
    from datetime import date

    from gateway.registry import RegistrySet

    def _equity_master() -> str:
        return (
            "Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument\n"
            "NSE,2885,1,RELIANCE,RELIANCE-EQ,,EQ\n"
        )

    def _deriv_master(exch: str, token: str, symbol: str) -> str:
        return (
            "Exchange,Token,LotSize,Symbol,TradingSymbol,Expiry,Instrument\n"
            f"{exch},{token},75,{symbol},{symbol},28-10-2026,OPTIDX\n"
        )

    registry_set = RegistrySet()
    assert registry_set.nse.load_text(_equity_master(), today=date(2026, 9, 10)) == 1
    assert registry_set.nfo.load_text(_deriv_master("NFO", "49680", "NIFTY"), today=date(2026, 9, 10)) == 1
    assert registry_set.bfo.load_text(_deriv_master("BFO", "36", "SENSEX"), today=date(2026, 9, 10)) == 1
    # Every master fresh -> not stale; an empty/unloaded master is stale.
    assert registry_set.is_stale(today=date(2026, 9, 11), max_age_days=1) is False
    assert registry_set.is_stale(today=date(2026, 9, 16), max_age_days=1) is True
    empty_set = RegistrySet()
    assert empty_set.is_stale(today=date(2026, 9, 11), max_age_days=1) is True


def test_candle_broker_unsupported_exchange():
    import asyncio
    from types import SimpleNamespace

    from gateway.candles import CandleBroker
    from gateway.registry import RegistrySet

    settings = SimpleNamespace(rest_rps=2.0, rest_burst=5)
    broker = CandleBroker(settings, None, None, RegistrySet())
    result = asyncio.run(broker.fetch("RELIANCE", "FIVE_MINUTE", 0, 0, "MCX"))
    assert result["status"] == "UNSUPPORTED_EXCHANGE"
