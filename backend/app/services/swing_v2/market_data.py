"""Neutral shared market-data interface for Swing V2.

Swing V2 must never create an Angel One client, authenticate, subscribe, or
call Angel REST APIs.  This module is the single approved boundary between
Swing V2 and market data.  It composes the existing neutral/shared surfaces:

* ``market_snapshot_store`` — canonical path to the last persisted snapshot
  (the same snapshot the Intraday desk consumes; unchanged).
* ``market_data_provider`` — provider-independent NSE/Dhan quote + candle
  retrieval with failover (no broker credentials required).

The Intraday implementation modules are never imported here.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

_LOCK = threading.RLock()


def snapshot_path() -> str:
    """Canonical path to the last persisted market snapshot."""
    from ..market_snapshot_store import readable_market_snapshot_path

    return str(readable_market_snapshot_path())


def read_snapshot() -> dict[str, Any]:
    """Read the persisted snapshot; empty dict on any failure (fail-closed)."""
    try:
        import json

        with open(snapshot_path(), "r", encoding="utf-8-sig") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        log.debug("swing_v2 snapshot read failed closed: %s", exc)
        return {}


def latest_quote(symbol: str) -> dict[str, Any] | None:
    """Latest canonical quote for one symbol via the neutral provider."""
    try:
        from ..market_data_provider import fetch_quotes_with_failover

        quotes, _coverage = fetch_quotes_with_failover([symbol], _no_angel_fetch)
        return quotes.get(str(symbol).upper())
    except Exception as exc:
        log.debug("swing_v2 latest_quote failed for %s: %s", symbol, exc)
        return None


def latest_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Bulk canonical quotes via the neutral provider (NSE primary)."""
    if not symbols:
        return {}
    try:
        from ..market_data_provider import fetch_quotes_with_failover

        quotes, _coverage = fetch_quotes_with_failover(list(symbols), _no_angel_fetch)
        return quotes
    except Exception as exc:
        log.debug("swing_v2 latest_quotes failed: %s", exc)
        return {}


def historical_bars(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    """Completed OHLCV bars for one symbol via the neutral provider.

    Returns canonical ``[{timestamp, open, high, low, close, volume}]`` rows.
    """
    if not symbol or limit <= 0:
        return []
    try:
        from ..market_data_provider import fetch_nse_candles
        from ..market_data_provider import load_dhan_security_ids

        now = datetime.now(timezone.utc)
        start = now
        token = ""
        ids = load_dhan_security_ids()
        token = ids.get(str(symbol).upper(), "")
        raw = fetch_nse_candles(str(symbol).upper(), token, interval, start, now)
        out: list[dict[str, Any]] = []
        for row in raw or []:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            ts, open_, high, low, close, volume = row[:6]
            try:
                out.append({
                    "timestamp": str(ts),
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume or 0),
                    "source": "NSE_CHARTING",
                })
            except (TypeError, ValueError):
                continue
        out.sort(key=lambda item: item["timestamp"])
        return out[-limit:]
    except Exception as exc:
        log.debug("swing_v2 historical_bars failed for %s: %s", symbol, exc)
        return []


def _no_angel_fetch(_symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Angel One is never a quote source for Swing V2."""
    return {}


__all__ = [
    "historical_bars",
    "intraday_occupied_symbols",
    "latest_quote",
    "latest_quotes",
    "read_snapshot",
    "snapshot_path",
]


def intraday_occupied_symbols(day: str) -> set[str]:
    """Read locked Intraday symbols for ``day`` from the neutral session artifact."""
    import json
    import os
    from pathlib import Path

    path = os.environ.get("INTRADAY_SESSION_FILE")
    if not path:
        path = str(Path(__file__).resolve().parents[3] / "intraday_session.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not data.get("locked"):
            return set()
        if str(data.get("sessionDate") or "")[:10] != str(day or "")[:10]:
            return set()
        result: set[str] = set()
        for side in ("long", "short"):
            for row in data.get(side) or []:
                if isinstance(row, dict):
                    sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
                    if sym:
                        result.add(sym)
        return result
    except Exception:
        return set()