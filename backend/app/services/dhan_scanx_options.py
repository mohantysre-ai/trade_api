"""Unauthenticated ScanX option-chain fallback for Angel One outages."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time, timezone
from typing import Any, Callable
from urllib.request import Request, urlopen

SCANX_OPTION_URL = "https://open-web-scanx.dhan.co/scanx/optchainactive"
SCANX_SIDS = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51}


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def expiry_epoch(expiry: date) -> int:
    """Use the actual master expiry at 18:30 IST; never infer weekday rules."""
    return int(datetime.combine(expiry, time(13, 0), tzinfo=timezone.utc).timestamp())


def _pick(row: dict[str, Any], *keys: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _side(strike: float | None, raw: dict[str, Any], side: str) -> dict[str, Any]:
    option_type = "CALL" if side == "CE" else "PUT"
    return {
        "symbol": _pick(raw, "symbol", "DispSym", "TradingSymbol"),
        "strike": strike,
        "optionType": option_type,
        "ltp": _number(_pick(raw, "ltp", "LastPrice", "LastTradedPrice", "Price")),
        "close": _number(_pick(raw, "close", "PrevClose", "PreviousClose")),
        "volume": _number(_pick(raw, "volume", "Vol", "TradeVolume")),
        "oi": _number(_pick(raw, "oi", "OpenInterest")),
        "previousOi": _number(_pick(raw, "previousOi", "PrevOI", "PreviousOpenInterest")),
        "oiChange": _number(_pick(raw, "oiChange", "ChangeInOI", "ChgOI")),
        "bestBid": _number(_pick(raw, "bestBid", "BidPrice", "Bid")),
        "bestAsk": _number(_pick(raw, "bestAsk", "AskPrice", "Ask")),
        "delta": _number(_pick(raw, "delta")),
        "gamma": _number(_pick(raw, "gamma")),
        "theta": _number(_pick(raw, "theta")),
        "vega": _number(_pick(raw, "vega")),
        "iv": _number(_pick(raw, "iv", "ImpliedVolatility")),
        "greeksSource": "SCANX_FALLBACK" if _pick(raw, "delta") is not None else None,
        "quoteSource": "SCANX_FALLBACK",
    }


def normalize_scanx_chain(payload: Any) -> tuple[float | None, list[dict[str, Any]]]:
    root = payload.get("data") or payload.get("Data") or payload if isinstance(payload, dict) else payload
    spot = None
    if isinstance(root, dict):
        spot = _number(_pick(root, "spot", "spotPrice", "underlyingValue", "Ltp"))
        rows = _pick(root, "chain", "optionChain", "oc", "list", "data")
    else:
        rows = root
    if isinstance(rows, dict):
        rows = [{"strike": key, **(value if isinstance(value, dict) else {})} for key, value in rows.items()]
    if not isinstance(rows, list):
        return spot, []
    chain: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        strike = _number(_pick(row, "strike", "strikePrice", "StrikePrice", "Stk"))
        ce = _pick(row, "ce", "call", "CallData")
        pe = _pick(row, "pe", "put", "PutData")
        if isinstance(ce, dict):
            chain.append(_side(strike, ce, "CE"))
        if isinstance(pe, dict):
            chain.append(_side(strike, pe, "PE"))
        if not isinstance(ce, dict) and not isinstance(pe, dict):
            kind = str(_pick(row, "optionType", "OptType", "type") or "").upper()
            if kind in {"CE", "CALL"}:
                chain.append(_side(strike, row, "CE"))
            elif kind in {"PE", "PUT"}:
                chain.append(_side(strike, row, "PE"))
    return spot, [row for row in chain if row.get("strike") is not None]


def _post(payload: bytes, timeout: float) -> Any:
    request = Request(SCANX_OPTION_URL, data=payload, headers={"Content-Type": "text/plain", "User-Agent": "Alphix-Terminal/1.0"}, method="POST")
    with urlopen(request, timeout=timeout) as response:  # nosec - fixed ScanX URL
        return json.loads(response.read().decode("utf-8"))


def fetch_scanx_option_chain(index_key: str, expiry: date, *, requester: Callable[[bytes, float], Any] = _post, timeout: float = 8.0) -> dict[str, Any]:
    key = index_key.upper().strip()
    if key not in SCANX_SIDS:
        return {"source": "SCANX_FALLBACK", "status": "NOT_SUPPORTED", "error": f"No ScanX SID configured for {key}", "chain": []}
    body = json.dumps({"Data": {"Seg": 0, "Sid": SCANX_SIDS[key], "Exp": expiry_epoch(expiry)}}, separators=(",", ":")).encode("utf-8")
    payload = requester(body, timeout)
    spot, chain = normalize_scanx_chain(payload)
    return {"source": "SCANX_FALLBACK", "status": "LIVE" if chain else "DATA_INCOMPLETE", "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "spot": spot, "expiry": expiry.isoformat(), "chain": chain, "request": {"sid": SCANX_SIDS[key], "expiryEpoch": expiry_epoch(expiry)}}


def apply_scanx_fallback(angel_payload: dict[str, Any], expiries: dict[str, date], *, fetcher: Callable[[str, date], dict[str, Any]] = fetch_scanx_option_chain) -> dict[str, Any]:
    merged = {**angel_payload, "indices": dict(angel_payload.get("indices") or {})}
    used: list[str] = []
    needed = []
    for key in SCANX_SIDS:
        angel = merged["indices"].get(key) if isinstance(merged["indices"].get(key), dict) else {}
        usable = angel.get("status") == "LIVE" and bool(angel.get("chain"))
        if usable or key not in expiries:
            continue
        needed.append(key)

    def _one(key: str) -> tuple[str, dict[str, Any]]:
        try:
            return key, fetcher(key, expiries[key])
        except Exception as exc:
            return key, {"source": "SCANX_FALLBACK", "status": "SOURCE_UNAVAILABLE", "error": str(exc), "chain": []}

    fetched: dict[str, dict[str, Any]] = {}
    if needed:
        with ThreadPoolExecutor(max_workers=len(needed)) as pool:
            futures = [pool.submit(_one, key) for key in needed]
            for future in as_completed(futures):
                key, fallback = future.result()
                fetched[key] = fallback
    for key, fallback in fetched.items():
        angel = merged["indices"].get(key) if isinstance(merged["indices"].get(key), dict) else {}
        if fallback.get("status") == "LIVE" and fallback.get("chain"):
            merged["indices"][key] = {**angel, **fallback, "primarySource": "ANGEL_ONE", "fallbackReason": angel.get("error") or angel.get("status")}
            used.append(key)
        else:
            merged["indices"][key] = {**angel, "fallback": fallback}
    merged["fallbackSource"] = "SCANX"
    merged["fallbackUsedFor"] = used
    return merged
