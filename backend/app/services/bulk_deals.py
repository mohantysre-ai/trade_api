"""NSE bulk and block deal fetcher with file cache."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
BULK_DEALS_CACHE_PATH = BASE_DIR.parent / "data" / "bulk_deals_cache.json"
IST_ZONE = ZoneInfo("Asia/Kolkata")

BULK_DEAL_CACHE_TTL_SECONDS = int(os.getenv("BULK_DEAL_CACHE_TTL_SECONDS", "3600"))
BULK_DEAL_LOOKBACK_HOURS = int(os.getenv("BULK_DEAL_LOOKBACK_HOURS", "24"))
MIN_BULK_DEAL_VALUE_CR = float(os.getenv("MIN_BULK_DEAL_VALUE_CR", "5"))
REQUIRE_BULK_DEAL = os.getenv("REQUIRE_BULK_DEAL", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}

NSE_LARGE_DEAL_URL = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
NSE_BLOCK_DEAL_URL = "https://www.nseindia.com/api/block-deal"


def _nse_session(referer: str = "https://www.nseindia.com/market-data/bulk-deal-data") -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
        }
    )
    session.get("https://www.nseindia.com", timeout=20)
    return session


def _parse_deal_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw.strip(), fmt)
            # NSE publishes date-only stamps; treat as end-of-day IST for lookback windows.
            return parsed.replace(hour=23, minute=59, second=59, tzinfo=IST_ZONE)
        except ValueError:
            continue
    return None


def _deal_value_cr(qty: Any, price: Any) -> float:
    try:
        quantity = float(str(qty).replace(",", "").strip())
        watp = float(str(price).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0
    if quantity <= 0 or watp <= 0:
        return 0.0
    return (quantity * watp) / 1e7


def _within_lookback(deal_dt: datetime | None, lookback_hours: int) -> bool:
    if deal_dt is None:
        return False
    cutoff = datetime.now(IST_ZONE) - timedelta(hours=lookback_hours)
    return deal_dt >= cutoff


def _aggregate_deal_rows(
    rows: list[dict[str, Any]],
    deal_type: str,
    lookback_hours: int,
) -> dict[str, dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        deal_dt = _parse_deal_date(str(row.get("date") or ""))
        if not _within_lookback(deal_dt, lookback_hours):
            continue

        qty_raw = row.get("qty")
        try:
            qty = float(str(qty_raw).replace(",", "").strip())
        except (TypeError, ValueError):
            qty = 0.0
        value_cr = _deal_value_cr(qty_raw, row.get("watp"))
        latest_time = deal_dt.isoformat() if deal_dt else str(row.get("date") or "")

        entry = aggregated.setdefault(
            symbol,
            {
                "deal_count": 0,
                "total_value_cr": 0.0,
                "total_qty": 0.0,
                "deal_types": set(),
                "latest_time": "",
                "buy_count": 0,
                "sell_count": 0,
            },
        )
        entry["deal_count"] += 1
        entry["total_value_cr"] += value_cr
        entry["total_qty"] += qty
        entry["deal_types"].add(deal_type)
        if str(row.get("buySell") or "").upper() == "BUY":
            entry["buy_count"] += 1
        elif str(row.get("buySell") or "").upper() == "SELL":
            entry["sell_count"] += 1
        if latest_time and latest_time > entry["latest_time"]:
            entry["latest_time"] = latest_time

    normalized: dict[str, dict[str, Any]] = {}
    for symbol, entry in aggregated.items():
        deal_types = entry.pop("deal_types")
        if deal_types == {"BULK", "BLOCK"}:
            deal_type_label = "BOTH"
        elif "BLOCK" in deal_types:
            deal_type_label = "BLOCK"
        else:
            deal_type_label = "BULK"
        entry["deal_type"] = deal_type_label
        entry["total_value_cr"] = round(float(entry["total_value_cr"]), 4)
        entry["total_qty"] = round(float(entry["total_qty"]), 2)
        normalized[symbol] = entry
    return normalized


def _merge_deal_maps(*maps: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for deal_map in maps:
        for symbol, info in deal_map.items():
            if symbol not in merged:
                merged[symbol] = dict(info)
                merged[symbol]["deal_types"] = {info.get("deal_type", "BULK")}
                continue
            target = merged[symbol]
            target["deal_count"] += info.get("deal_count", 0)
            target["total_value_cr"] = round(
                float(target.get("total_value_cr", 0.0)) + float(info.get("total_value_cr", 0.0)),
                4,
            )
            target["total_qty"] = round(
                float(target.get("total_qty", 0.0)) + float(info.get("total_qty", 0.0)),
                2,
            )
            target["buy_count"] = int(target.get("buy_count", 0)) + int(info.get("buy_count", 0))
            target["sell_count"] = int(target.get("sell_count", 0)) + int(info.get("sell_count", 0))
            target["deal_types"].add(info.get("deal_type", "BULK"))
            if str(info.get("latest_time") or "") > str(target.get("latest_time") or ""):
                target["latest_time"] = info.get("latest_time", "")

    for symbol, entry in merged.items():
        deal_types = entry.pop("deal_types", {"BULK"})
        if deal_types == {"BULK", "BLOCK"} or deal_types == {"BOTH", "BULK", "BLOCK"}:
            entry["deal_type"] = "BOTH"
        elif "BLOCK" in deal_types:
            entry["deal_type"] = "BLOCK"
        else:
            entry["deal_type"] = "BULK"
    return merged


def fetch_nse_bulk_block_deals(lookback_hours: int | None = None) -> dict[str, dict[str, Any]]:
    """Fetch today's bulk + block deals from NSE and aggregate by symbol."""
    lookback = lookback_hours if lookback_hours is not None else BULK_DEAL_LOOKBACK_HOURS
    session = _nse_session()
    bulk_rows: list[dict[str, Any]] = []
    block_rows: list[dict[str, Any]] = []

    try:
        response = session.get(NSE_LARGE_DEAL_URL, params={"mode": "bulk_deals"}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        bulk_rows = list(payload.get("BULK_DEALS_DATA") or [])
        block_rows = list(payload.get("BLOCK_DEALS_DATA") or [])
    except Exception as exc:
        log.warning("NSE large-deal snapshot fetch failed: %s", exc)

    # Fallback: intraday block-deal endpoint when snapshot has no block rows.
    if not block_rows:
        try:
            session.headers["Referer"] = "https://www.nseindia.com/market-data/block-deal-watch"
            response = session.get(NSE_BLOCK_DEAL_URL, timeout=30)
            if response.status_code == 200:
                payload = response.json()
                block_rows = list(payload.get("data") or [])
        except Exception as exc:
            log.debug("NSE block-deal fallback fetch failed: %s", exc)

    bulk_map = _aggregate_deal_rows(bulk_rows, "BULK", lookback)
    block_map = _aggregate_deal_rows(block_rows, "BLOCK", lookback)
    return _merge_deal_maps(bulk_map, block_map)


def _load_cache() -> dict[str, Any] | None:
    try:
        return json.loads(BULK_DEALS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(deals: dict[str, dict[str, Any]], lookback_hours: int) -> None:
    BULK_DEALS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BULK_DEALS_CACHE_PATH.write_text(
        json.dumps(
            {
                "refreshedAt": datetime.now(timezone.utc).isoformat(),
                "lookbackHours": lookback_hours,
                "minValueCr": MIN_BULK_DEAL_VALUE_CR,
                "count": len(deals),
                "deals": deals,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_bulk_deals(force_refresh: bool = False, lookback_hours: int | None = None) -> dict[str, dict[str, Any]]:
    """Return symbol -> bulk/block deal aggregate map, using cache when fresh."""
    lookback = lookback_hours if lookback_hours is not None else BULK_DEAL_LOOKBACK_HOURS
    if not force_refresh:
        cached = _load_cache()
        if cached:
            refreshed_at = cached.get("refreshedAt")
            if refreshed_at:
                try:
                    age = time.time() - datetime.fromisoformat(str(refreshed_at)).timestamp()
                    if age < BULK_DEAL_CACHE_TTL_SECONDS and int(cached.get("lookbackHours") or lookback) == lookback:
                        deals = cached.get("deals") or {}
                        if isinstance(deals, dict):
                            return deals
                except Exception:
                    pass

    try:
        deals = fetch_nse_bulk_block_deals(lookback_hours=lookback)
        _save_cache(deals, lookback)
        return deals
    except Exception as exc:
        log.warning("Bulk deal refresh failed, using cache if available: %s", exc)
        cached = _load_cache()
        if cached and isinstance(cached.get("deals"), dict):
            return cached["deals"]
        return {}


def qualifies_bulk_deal(info: dict[str, Any] | None, min_value_cr: float | None = None) -> bool:
    """True when aggregated deal value meets the configured threshold."""
    if not info:
        return False
    threshold = MIN_BULK_DEAL_VALUE_CR if min_value_cr is None else min_value_cr
    return float(info.get("total_value_cr") or 0.0) >= threshold


def attach_bulk_deal_metrics(
    metrics: dict[str, Any],
    deal_info: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach bulk/block deal fields used by quality gates and alpha scoring."""
    has_signal = qualifies_bulk_deal(deal_info)
    metrics["bulk_deal_signal"] = has_signal
    metrics["bulk_deal_value_cr"] = round(float((deal_info or {}).get("total_value_cr") or 0.0), 4)
    metrics["bulk_deal_count"] = int((deal_info or {}).get("deal_count") or 0)
    metrics["bulk_deal_type"] = str((deal_info or {}).get("deal_type") or "")
    metrics["bulk_deal_latest_time"] = str((deal_info or {}).get("latest_time") or "")
    metrics["bulk_deal_boost"] = 10.0 if has_signal else 0.0
    return metrics
