"""TinyFish Search API — backup news fetch when HTML scrapers / RSS are thin."""

from __future__ import annotations

import logging
import os

import requests

_log = logging.getLogger(__name__)

TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"
_DEFAULT_MIN_BACKUP = 3


def tinyfish_api_key() -> str:
    return os.getenv("TINYFISH_API_KEY", "").strip()


def tinyfish_enabled() -> bool:
    return bool(tinyfish_api_key())


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": tinyfish_api_key(),
        "X-TF-Request-Origin": os.getenv("TINYFISH_REQUEST_ORIGIN", "api"),
        "X-TF-Client-Name": os.getenv("TINYFISH_CLIENT_NAME", "tinyfish-api-key-page"),
        "Accept": "application/json",
    }


def search_tinyfish(
    query: str,
    *,
    location: str = "IN",
    language: str = "en",
    domain_type: str = "news",
    recency_minutes: int | None = None,
    timeout: float = 20.0,
) -> list[dict[str, str]]:
    """Return title/snippet/url rows from TinyFish. Empty list if unconfigured or the API fails."""
    key = tinyfish_api_key()
    q = (query or "").strip()
    if not key or not q:
        return []
    params: dict[str, str | int] = {
        "query": q,
        "location": location,
        "language": language,
        "domain_type": domain_type,
    }
    if recency_minutes is not None:
        params["recency_minutes"] = max(1, min(int(recency_minutes), 5256000))
    try:
        response = requests.get(
            TINYFISH_SEARCH_URL,
            params=params,
            headers=_headers(),
            timeout=timeout,
        )
        if response.status_code >= 300:
            _log.warning("TinyFish search failed (%s): %s", response.status_code, (response.text or "")[:160])
            return []
        payload = response.json() if response.content else {}
    except Exception as exc:
        _log.warning("TinyFish search error: %s", exc)
        return []
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url:
            continue
        snippet = str(row.get("snippet") or row.get("summary") or "").strip()
        source = str(row.get("publisher") or row.get("domain") or "TinyFish").strip() or "TinyFish"
        published = str(row.get("date") or row.get("published_at") or "").strip()
        out.append(
            {
                "title": title[:300],
                "url": url,
                "summary": snippet[:500],
                "source": source[:80],
                "published_at": published,
            }
        )
    return out


def backup_min_articles() -> int:
    raw = os.getenv("TINYFISH_BACKUP_MIN_ARTICLES", str(_DEFAULT_MIN_BACKUP)).strip()
    try:
        return max(0, min(int(raw), 20))
    except ValueError:
        return _DEFAULT_MIN_BACKUP
