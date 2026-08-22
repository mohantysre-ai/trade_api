"""Cached NSE sectoral-index context for deterministic intraday ranking."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

NSE_SECTOR_URL = "https://www.nseindia.com/api/heatmap-index?type=Sectoral%20Indices"
NSE_ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
_CACHE_TTL = float(os.environ.get("NSE_SECTOR_CACHE_TTL", "60"))
_STALE_TTL = float(os.environ.get("NSE_SECTOR_STALE_TTL", "21600"))
_CACHE_FILE = Path(__file__).resolve().parents[1] / "data" / "nse_sector_heatmap.json"
_LOCK = threading.Lock()
_MEMORY: dict[str, Any] | None = None
_MEMORY_AT = 0.0

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/live-market-indices/heatmap",
}

SECTOR_TO_INDEX = {
    "AUTO": "NIFTY AUTO",
    "BANK": "NIFTY BANK",
    "BANKING": "NIFTY BANK",
    "PSU BANK": "NIFTY PSU BANK",
    "FINANCE": "NIFTY FINANCIAL SERVICES",
    "FINANCIAL SERVICES": "NIFTY FINANCIAL SERVICES",
    "FMCG": "NIFTY FMCG",
    "FAST MOVING CONSUMER GOODS": "NIFTY FMCG",
    "IT": "NIFTY IT",
    "INFORMATION TECHNOLOGY": "NIFTY IT",
    "MEDIA": "NIFTY MEDIA",
    "METAL": "NIFTY METAL",
    "METALS": "NIFTY METAL",
    "PHARMA": "NIFTY PHARMA",
    "PHARMACEUTICALS": "NIFTY PHARMA",
    "HEALTHCARE": "NIFTY HEALTHCARE INDEX",
    "REALTY": "NIFTY REALTY",
    "ENERGY": "NIFTY ENERGY",
    "OIL & GAS": "NIFTY OIL & GAS",
    "OIL AND GAS": "NIFTY OIL & GAS",
    "CONSUMER DURABLES": "NIFTY CONSUMER DURABLES",
}


def _number(value: Any) -> float | None:
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def normalize_sector_payload(raw: Any) -> list[dict[str, Any]]:
    """Normalize NSE response variants without depending on one fragile schema."""
    rows: dict[str, dict[str, Any]] = {}
    for item in _walk(raw):
        name = next(
            (item.get(k) for k in ("index", "indexName", "name", "symbol", "key") if item.get(k)),
            None,
        )
        if not isinstance(name, str) or "NIFTY" not in name.upper():
            continue
        change = next(
            (_number(item.get(k)) for k in ("pChange", "percentChange", "changePercent", "perChange", "change") if item.get(k) is not None),
            None,
        )
        if change is None:
            continue
        key = " ".join(name.upper().split())
        rows[key] = {
            "index": key,
            "pChange": round(change, 3),
            "last": next(
                (
                    _number(item.get(k))
                    for k in (
                        "last",
                        "lastPrice",
                        "indexValue",
                        "indexVal",
                        "index_value",
                        "currentValue",
                        "current",
                        "ltp",
                        "close",
                        "value",
                    )
                    if item.get(k) is not None
                ),
                None,
            ),
        }
    return sorted(rows.values(), key=lambda row: (-float(row["pChange"]), row["index"]))


def merge_sector_levels(
    sectors: list[dict[str, Any]], index_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill missing heat-map levels from NSE's all-indices response.

    The heat-map endpoint has changed its price-field name more than once and
    can omit the level while retaining percentage change.  The all-indices
    endpoint is an independent official NSE source for the same index level.
    Never estimate a level from percentage change.
    """
    levels = {
        str(row.get("index") or "").upper(): row.get("last")
        for row in index_rows
        if row.get("last") is not None
    }
    return [
        {
            **row,
            "last": row.get("last")
            if row.get("last") is not None
            else levels.get(str(row.get("index") or "").upper()),
        }
        for row in sectors
    ]


def _read_disk() -> dict[str, Any] | None:
    try:
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _write_disk(payload: dict[str, Any]) -> None:
    try:
        from .json_atomic import atomic_write_json

        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_CACHE_FILE, payload)
    except Exception as exc:
        log.debug("Sector cache write failed: %s", exc)


def _fetch() -> dict[str, Any]:
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.get("https://www.nseindia.com/market-data/live-market-indices/heatmap", timeout=8)
    response = session.get(NSE_SECTOR_URL, timeout=8)
    response.raise_for_status()
    rows = normalize_sector_payload(response.json())
    if not rows:
        raise ValueError("NSE sector heatmap returned no recognizable sector rows")
    if any(row.get("last") is None for row in rows):
        try:
            levels_response = session.get(NSE_ALL_INDICES_URL, timeout=8)
            levels_response.raise_for_status()
            rows = merge_sector_levels(rows, normalize_sector_payload(levels_response.json()))
        except Exception as exc:
            log.debug("NSE all-indices level enrichment failed: %s", exc)
    return {
        "success": True,
        "source": "NSE_SECTORAL_INDICES",
        "sourceUrl": NSE_SECTOR_URL,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "stale": False,
        "sectors": rows,
    }


def get_sector_heatmap() -> dict[str, Any]:
    global _MEMORY, _MEMORY_AT
    now = time.monotonic()
    if _MEMORY is not None and now - _MEMORY_AT < _CACHE_TTL:
        return _MEMORY
    with _LOCK:
        now = time.monotonic()
        if _MEMORY is not None and now - _MEMORY_AT < _CACHE_TTL:
            return _MEMORY
        try:
            _MEMORY = _fetch()
            _MEMORY_AT = now
            _write_disk(_MEMORY)
            return _MEMORY
        except Exception as exc:
            cached = _MEMORY or _read_disk()
            if cached:
                try:
                    age = time.time() - datetime.fromisoformat(str(cached.get("updatedAt")).replace("Z", "+00:00")).timestamp()
                except Exception:
                    age = _STALE_TTL + 1
                if age <= _STALE_TTL:
                    _MEMORY = {**cached, "stale": True, "warning": str(exc)}
                    _MEMORY_AT = now
                    return _MEMORY
            return {
                "success": False,
                "source": "NSE_SECTORAL_INDICES",
                "sourceUrl": NSE_SECTOR_URL,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "stale": True,
                "sectors": [],
                "error": str(exc),
            }


def sector_signal(sector: str, direction: str, stock_change_pct: float | None) -> dict[str, Any]:
    payload = get_sector_heatmap()
    sector_key = " ".join(str(sector or "").upper().replace("&", "AND").split())
    index_name = SECTOR_TO_INDEX.get(sector_key)
    if index_name is None:
        index_name = next(
            (index for alias, index in SECTOR_TO_INDEX.items() if alias in sector_key or sector_key in alias),
            None,
        )
    row = next((r for r in payload.get("sectors") or [] if r.get("index") == index_name), None)
    if not row:
        return {"rated": False, "score": 50.0, "index": index_name, "stale": payload.get("stale", True)}
    sector_change = float(row.get("pChange") or 0.0)
    stock_change = float(stock_change_pct) if stock_change_pct is not None else sector_change
    relative = stock_change - sector_change
    sign = -1.0 if str(direction).upper() == "SHORT" else 1.0
    # Sector trend is the anchor; stock-vs-sector leadership confirms it.
    score = max(0.0, min(100.0, 50.0 + sign * sector_change * 10.0 + sign * relative * 5.0))
    return {
        "rated": True,
        "score": round(score, 1),
        "index": index_name,
        "sectorChangePct": round(sector_change, 3),
        "stockVsSectorPct": round(relative, 3),
        "leader": relative > 0 if sign > 0 else relative < 0,
        "stale": bool(payload.get("stale")),
        "updatedAt": payload.get("updatedAt"),
    }
