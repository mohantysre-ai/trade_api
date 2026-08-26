"""Lemonn option-chain third fallback and dynamic expiry discovery."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.request import Request, urlopen

from .dhan_scanx_options import chain_needs_oi_enrichment, enrich_chain_fields, has_usable_option_chain, normalize_scanx_chain

LEMONN_CHAIN_URL = "https://lemonn.co.in/api/get-option-chain"
LEMONN_PAGE_TEMPLATE = os.getenv("LEMONN_OPTION_PAGE_TEMPLATE", "https://lemonn.co.in/futures-and-options/options/{slug}")
LEMONN_SLUGS = {"NIFTY": "nifty", "BANKNIFTY": "banknifty", "FINNIFTY": "finnifty", "SENSEX": "sensex"}
_EXPIRY_PATTERN = re.compile(r"\b(\d{2}\s+[A-Z]{3}\s+\d{4})\b", re.IGNORECASE)
_EXPIRY_LOCK = threading.Lock()
_EXPIRY_CACHE: tuple[float, dict[str, date]] = (0.0, {})


def parse_lemonn_expiries(html: str, *, today: date | None = None) -> list[date]:
    session_date = today or datetime.now(timezone.utc).date()
    found: set[date] = set()
    for value in _EXPIRY_PATTERN.findall(html or ""):
        try:
            parsed = datetime.strptime(" ".join(value.upper().split()), "%d %b %Y").date()
        except ValueError:
            continue
        if parsed >= session_date:
            found.add(parsed)
    return sorted(found)


def _get_page(url: str, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": "Alphix-Terminal/1.0", "Accept": "text/html"})
    with urlopen(request, timeout=timeout) as response:  # nosec - configured Lemonn HTTPS URL
        return response.read().decode("utf-8", errors="replace")


def discover_lemonn_expiries(
    keys: list[str] | None = None,
    *,
    page_fetcher: Callable[[str, float], str] = _get_page,
    timeout: float = 8.0,
    ttl_seconds: float = 21_600,
) -> dict[str, date]:
    """Nearest active expiry from each Lemonn option-page dropdown."""
    global _EXPIRY_CACHE
    wanted = [key for key in (keys or list(LEMONN_SLUGS)) if key in LEMONN_SLUGS]
    now = time.monotonic()
    with _EXPIRY_LOCK:
        cached_at, cached = _EXPIRY_CACHE
        if cached and now - cached_at < ttl_seconds and all(key in cached for key in wanted):
            return {key: cached[key] for key in wanted}
        resolved = dict(cached) if now - cached_at < ttl_seconds else {}
        for key in wanted:
            if key in resolved:
                continue
            url = LEMONN_PAGE_TEMPLATE.format(slug=LEMONN_SLUGS[key], symbol=key.lower())
            try:
                expiries = parse_lemonn_expiries(page_fetcher(url, timeout))
            except Exception:
                expiries = []
            if expiries:
                resolved[key] = expiries[0]
        _EXPIRY_CACHE = (now, resolved)
        return {key: resolved[key] for key in wanted if key in resolved}


def _post(body: bytes, timeout: float) -> Any:
    request = Request(
        LEMONN_CHAIN_URL,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Alphix-Terminal/1.0"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # nosec - fixed Lemonn HTTPS URL
        return json.loads(response.read().decode("utf-8"))


def fetch_lemonn_option_chain(
    index_key: str,
    expiry: date,
    *,
    requester: Callable[[bytes, float], Any] = _post,
    timeout: float = 8.0,
) -> dict[str, Any]:
    key = index_key.upper().strip()
    if key not in LEMONN_SLUGS:
        return {"source": "LEMONN_FALLBACK", "status": "NOT_SUPPORTED", "error": f"Unsupported Lemonn symbol {key}", "chain": []}
    expiry_text = expiry.strftime("%d%b%Y").upper()
    body = json.dumps({"symbol": key, "expiry": expiry_text}, separators=(",", ":")).encode("utf-8")
    payload = requester(body, timeout)
    spot, chain = normalize_scanx_chain(payload)
    return {
        "source": "LEMONN_FALLBACK",
        "status": "LIVE" if chain else "DATA_INCOMPLETE",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "spot": spot,
        "expiry": expiry.isoformat(),
        "chain": [{**row, "quoteSource": "LEMONN_FALLBACK"} for row in chain],
        "request": {"symbol": key, "expiry": expiry_text},
    }


def apply_lemonn_fallback(
    provider_payload: dict[str, Any],
    expiries: dict[str, date],
    *,
    fetcher: Callable[[str, date], dict[str, Any]] = fetch_lemonn_option_chain,
) -> dict[str, Any]:
    """Fill only indices still unusable after Angel and ScanX."""
    merged = {**provider_payload, "indices": dict(provider_payload.get("indices") or {})}
    used: list[str] = []
    for key in LEMONN_SLUGS:
        current = merged["indices"].get(key) if isinstance(merged["indices"].get(key), dict) else {}
        if has_usable_option_chain(current) and not chain_needs_oi_enrichment(current):
            continue
        expiry = expiries.get(key)
        if expiry is None:
            continue
        try:
            fallback = fetcher(key, expiry)
        except Exception as exc:
            fallback = {"source": "LEMONN_FALLBACK", "status": "SOURCE_UNAVAILABLE", "error": str(exc), "chain": []}
        if fallback.get("status") == "LIVE" and fallback.get("chain"):
            if has_usable_option_chain(current):
                merged["indices"][key] = {**current,
                    "chain": enrich_chain_fields(current.get("chain") or [], fallback.get("chain") or [], "LEMONN_FALLBACK"),
                    "chainEnrichmentSource": "LEMONN_FALLBACK"}
            else:
                merged["indices"][key] = {
                    **current,
                    **fallback,
                    "primarySource": "ANGEL_ONE",
                    "secondarySource": "SCANX_FALLBACK",
                    "fallbackReason": current.get("error") or current.get("status"),
                }
            used.append(key)
        else:
            merged["indices"][key] = {**current, "lemonnFallback": fallback}
    merged["thirdFallbackSource"] = "LEMONN"
    merged["thirdFallbackUsedFor"] = used
    return merged
