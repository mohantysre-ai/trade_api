"""Fail-soft derivative OI enrichment from the configured research endpoint.

This source may fill missing OI facts but never overwrites the primary option
providers and never participates directly in contract selection.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timezone
from typing import Any

import requests


ENDPOINT = os.getenv(
    "SIGQ_OI_ENRICHMENT_URL",
    "https://smartoptions.trendlyne.com/phoenix/api/fno/derivative/",
)
TTL_SECONDS = float(os.getenv("SIGQ_OI_ENRICHMENT_TTL_SECONDS", "30"))
TIMEOUT_SECONDS = float(os.getenv("SIGQ_OI_ENRICHMENT_TIMEOUT_SECONDS", "8"))
INDEX_CODES = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY",
    "SENSEX": "SENSEX",
}
_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_LOCK = threading.Lock()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _first(row: dict[str, Any], *names: str) -> Any:
    lowered = {str(key).lower().replace("_", ""): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower().replace("_", ""))
        if value not in (None, ""):
            return value
    return None


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _option_type(value: Any) -> str | None:
    text = str(value or "").upper().strip()
    if text in {"CE", "CALL", "C"} or "CALL" in text:
        return "CALL"
    if text in {"PE", "PUT", "P"} or "PUT" in text:
        return "PUT"
    return None


def _oi_record(row: dict[str, Any], *, option_type: str | None = None) -> dict[str, Any] | None:
    strike = _number(_first(row, "strikePrice", "strike", "strike_price"))
    kind = option_type or _option_type(_first(row, "optionType", "type", "right", "instrumentType"))
    if strike is None or kind is None:
        return None
    oi = _number(_first(row, "oi", "openInterest", "open_int", "open_interest"))
    previous = _number(_first(row, "previousOi", "prevOi", "previousOpenInterest", "prev_open_interest"))
    change = _number(_first(row, "oiChange", "changeInOi", "changeOI", "chgInOi"))
    if previous is None and oi is not None and change is not None:
        previous = oi - change
    return {
        "strike": strike,
        "optionType": kind,
        "oi": oi,
        "previousOi": previous,
        "oiChange": change if change is not None else (oi - previous if oi is not None and previous is not None else None),
        "volume": _number(_first(row, "volume", "tradedVolume", "totalTradedVolume")),
    }


def normalize_derivative_payload(payload: dict[str, Any]) -> dict[str, Any]:
    records: dict[tuple[float, str], dict[str, Any]] = {}
    pcr = None
    future: dict[str, Any] = {}
    for row in _walk(payload):
        if pcr is None:
            pcr = _number(_first(row, "pcr", "putCallRatio", "put_call_ratio"))
        strike = _number(_first(row, "strikePrice", "strike", "strike_price"))
        if strike is not None:
            for aliases, kind in ((('ce', 'call', 'callOption'), 'CALL'), (('pe', 'put', 'putOption'), 'PUT')):
                nested = next((row.get(name) for name in aliases if isinstance(row.get(name), dict)), None)
                if isinstance(nested, dict):
                    rec = _oi_record({**nested, "strike": strike}, option_type=kind)
                    if rec:
                        records[(strike, kind)] = rec
            rec = _oi_record(row)
            if rec:
                records[(strike, rec["optionType"])] = rec
        instrument = str(_first(row, "instrumentType", "instrument", "segment") or "").upper()
        if "FUT" in instrument:
            for target, aliases in {
                "oi": ("oi", "openInterest", "open_interest"),
                "previousOi": ("previousOi", "prevOi", "previousOpenInterest"),
                "oiChange": ("oiChange", "changeInOi", "changeOI"),
            }.items():
                value = _number(_first(row, *aliases))
                if value is not None:
                    future[target] = value
    if future.get("previousOi") is None and future.get("oi") is not None and future.get("oiChange") is not None:
        future["previousOi"] = future["oi"] - future["oiChange"]
    return {"chain": list(records.values()), "future": future or None, "pcr": pcr}


def fetch_oi_enrichment(stock_code: str, expiry: date, *, session: Any = requests) -> dict[str, Any]:
    key = (stock_code, expiry.isoformat())
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < TTL_SECONDS:
            return dict(cached[1])
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://smartoptions.trendlyne.com/",
        "User-Agent": "Mozilla/5.0 SIGQ-OI-Enrichment/1.0",
    }
    cookie = os.getenv("SIGQ_OI_ENRICHMENT_COOKIE", "").strip()
    if cookie:
        headers["Cookie"] = cookie
    response = session.get(
        ENDPOINT,
        params={"stockCode": stock_code, "expDate": expiry.isoformat()},
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, dict):
        raise ValueError("OI enrichment response is not an object")
    result = {**normalize_derivative_payload(raw), "fetchedAt": datetime.now(timezone.utc).isoformat()}
    with _LOCK:
        _CACHE[key] = (now, result)
    return dict(result)


def apply_oi_enrichment(option_data: dict[str, Any], expiries: dict[str, date]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for key, stock_code in INDEX_CODES.items():
        row = (option_data.get("indices") or {}).get(key)
        expiry = expiries.get(key)
        if not isinstance(row, dict) or expiry is None:
            continue
        try:
            enrichment = fetch_oi_enrichment(stock_code, expiry)
            matches = {
                (round(float(item["strike"]), 4), str(item["optionType"])): item
                for item in enrichment.get("chain") or []
                if item.get("strike") is not None and item.get("optionType")
            }
            filled = 0
            for contract in row.get("chain") or []:
                if not isinstance(contract, dict) or contract.get("strike") is None:
                    continue
                match = matches.get((round(float(contract["strike"]), 4), str(contract.get("optionType"))))
                if not match:
                    continue
                changed = False
                for field in ("oi", "previousOi", "oiChange", "volume"):
                    if contract.get(field) is None and match.get(field) is not None:
                        contract[field] = match[field]
                        changed = True
                if changed:
                    contract["oiEnrichmentSource"] = "SIGQ_RESEARCH"
                    filled += 1
            future = row.get("future")
            if isinstance(future, dict) and isinstance(enrichment.get("future"), dict):
                for field in ("oi", "previousOi", "oiChange"):
                    if future.get(field) is None and enrichment["future"].get(field) is not None:
                        future[field] = enrichment["future"][field]
                        future["oiEnrichmentSource"] = "SIGQ_RESEARCH"
            if enrichment.get("pcr") is not None:
                row["pcr"] = enrichment["pcr"]
            evidence[key] = {"status": "LIVE", "contractsEnriched": filled, "pcr": enrichment.get("pcr"), "fetchedAt": enrichment.get("fetchedAt")}
        except Exception as exc:
            evidence[key] = {"status": "UNAVAILABLE", "error": str(exc)}
    option_data["oiEnrichment"] = {"source": "SIGQ_RESEARCH", "indices": evidence}
    return option_data
