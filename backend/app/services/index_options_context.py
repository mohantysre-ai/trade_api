"""Independent market context owned exclusively by the Index Options book."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .angel_index_options import INDEX_LEADER_WEIGHTS, IST_ZONE, load_angel_scrip_master
from .json_atomic import atomic_write_json, load_json_with_fallback
from .market_snapshot_store import market_snapshot_path
from ..utils.symbols import Instrument

INDIA_VIX = Instrument("indiavix", "NSE", "India VIX", "99926017", "India VIX")


def context_path() -> Path:
    override = os.getenv("INDEX_OPTIONS_MARKET_CONTEXT_FILE", "").strip()
    return Path(override) if override else market_snapshot_path().with_name("index_options_market_context.json")


def _equity_instruments() -> list[Instrument]:
    required = {symbol for rows in INDEX_LEADER_WEIGHTS.values() for symbol, _ in rows}
    resolved: dict[str, Instrument] = {}
    for row in load_angel_scrip_master():
        if str(row.get("exch_seg") or "").upper() != "NSE":
            continue
        name = str(row.get("name") or "").upper().strip()
        trading = str(row.get("symbol") or "").upper().strip()
        token = str(row.get("token") or "").strip()
        if name in required and trading in {name, f"{name}-EQ"} and token:
            resolved[name] = Instrument(name, "NSE", trading, token, name)
    return [resolved[symbol] for symbol in sorted(required) if symbol in resolved]


def refresh_index_options_context(client: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Fetch only option-breadth leaders and VIX; never touch the stock snapshot."""
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    required = {symbol for rows in INDEX_LEADER_WEIGHTS.values() for symbol, _ in rows}
    try:
        instruments = _equity_instruments()
        quotes = client.fetch_batch_quotes([*instruments, INDIA_VIX])
        rows: dict[str, dict[str, Any]] = {}
        for instrument in instruments:
            quote = quotes.get(instrument.key)
            if not isinstance(quote, dict):
                continue
            rows[instrument.key] = {
                "ticker": instrument.key,
                "ltpRaw": quote.get("ltp"),
                "open": quote.get("open"),
                "close": quote.get("close"),
                "quoteProvider": "ANGEL_INDEX_OPTIONS_CONTEXT",
            }
        vix_quote = quotes.get(INDIA_VIX.key) if isinstance(quotes, dict) else None
        vix = vix_quote.get("ltp") if isinstance(vix_quote, dict) else None
        coverage = len(rows) / len(required) * 100.0 if required else 0.0
        payload = {
            "schemaVersion": "index_options_market_context_v1",
            "book": "INDEX_OPTIONS",
            "updatedAt": clock.astimezone(timezone.utc).isoformat(),
            "sessionDate": clock.date().isoformat(),
            "stockQuotes": rows,
            "macroDataStrip": {"morning": ([{"label": "India VIX", "val": vix}] if vix else [])},
            "indexOptionsContext": {
                "status": "LIVE" if coverage >= 90.0 and vix else "INCOMPLETE",
                "expectedLeaders": len(required),
                "receivedLeaders": len(rows),
                "coveragePct": round(coverage, 2),
                "vixAvailable": bool(vix),
                "source": "ANGEL_ONE_DEDICATED_BATCH",
            },
        }
        atomic_write_json(context_path(), payload)
        return payload
    except Exception as exc:
        payload = {
            "schemaVersion": "index_options_market_context_v1",
            "book": "INDEX_OPTIONS",
            "updatedAt": clock.astimezone(timezone.utc).isoformat(),
            "sessionDate": clock.date().isoformat(),
            "stockQuotes": {},
            "macroDataStrip": {"morning": []},
            "indexOptionsContext": {"status": "UNAVAILABLE", "error": str(exc), "source": "ANGEL_ONE_DEDICATED_BATCH"},
        }
        try:
            atomic_write_json(context_path(), payload)
        except Exception:
            pass
        return payload


def load_index_options_context(*, max_age_seconds: float = 150.0) -> dict[str, Any]:
    try:
        value = load_json_with_fallback(context_path())
        if not isinstance(value, dict):
            return {}
        stamp = datetime.fromisoformat(str(value.get("updatedAt") or "").replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
        if age <= max_age_seconds:
            return value
        return {
            **value,
            "stockQuotes": {},
            "macroDataStrip": {"morning": []},
            "indexOptionsContext": {**(value.get("indexOptionsContext") or {}), "status": "STALE", "ageSeconds": round(age, 1)},
        }
    except (FileNotFoundError, ValueError, TypeError):
        return {}


__all__ = ["context_path", "load_index_options_context", "refresh_index_options_context"]
