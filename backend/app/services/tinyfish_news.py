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


def tinyfish_ticker_news_failover() -> bool:
    """Ticker-news uses TinyFish Search instead of OpenRouter when a key is set."""
    if not tinyfish_enabled():
        return False
    override = os.getenv("TICKER_NEWS_LLM", "").strip().lower()
    return override not in ("openrouter", "openai", "gemini")


_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("insider_activity", ("insider", "promoter", "pledged", "wilful")),
    ("institutional_activity", (" fii", " dii", "mutual fund", "qip", "fpo", "institutional")),
    ("order_book_block_deals", ("block deal", "bulk deal", "block/bulk", "order book")),
    ("future_expansion_capex", ("capex", "expansion", "greenfield", "brownfield", "acquisition")),
    ("auditor_changes", ("auditor", "statutory audit")),
    ("dividend_news", ("dividend", "buyback", "bonus issue", "stock split")),
    ("new_orders_contracts", ("order win", "bagged", "contract", "letter of award", "loa")),
    ("earnings_results", ("earnings", "results", "revenue", "profit", "guidance", "q1 ", "q2 ", "q3 ", "q4 ")),
    ("management_changes", ("ceo", "cfo", "appointed", "resign", "managing director", "board")),
    ("regulatory_filings", ("sebi", "regulatory", "compliance", "penalty", "show cause")),
)

_RISK_KEYWORDS = ("sebi", "penalty", "fraud", "default", "pledged", "downgrade")


def _evidence_line(title: str, source: str, summary: str) -> str:
    head = title.strip()[:220]
    src = source.strip()[:40]
    snippet = summary.strip()[:180]
    if src and snippet:
        return f"{head} ({src}) — {snippet}"
    if src:
        return f"{head} ({src})"
    return head or "—"


def digest_ticker_news(
    rows: list[dict[str, str]],
    *,
    ticker: str,
    company: str,
) -> dict[str, str | bool]:
    """Source-routed Intelligence Categories from search/scrape rows. Does not invent verdicts."""
    buckets: dict[str, str] = {key: "—" for key, _kws in _CATEGORY_KEYWORDS}
    buckets["sentiment_overall"] = "—"
    buckets["risk_flags"] = "—"
    buckets["summary_headline"] = (
        f"No verified {company} ({ticker}) news found."
        if not rows
        else str(rows[0].get("title") or "").strip()[:300]
    )
    for row in rows:
        title = str(row.get("title") or "").strip()
        summary = str(row.get("summary") or "").strip()
        source = str(row.get("source") or "").strip()
        if not title:
            continue
        hay = f" {title} {summary} ".lower()
        line = _evidence_line(title, source, summary)
        for key, keywords in _CATEGORY_KEYWORDS:
            if buckets[key] != "—":
                continue
            if any(token in hay for token in keywords):
                buckets[key] = line
        if buckets["risk_flags"] == "—" and any(token in hay for token in _RISK_KEYWORDS):
            buckets["risk_flags"] = line
    return {
        **buckets,
        "llmUsed": False,
        "digestSource": "tinyfish",
        "llmError": "",
    }
