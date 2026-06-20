"""
AI-Powered Ticker News Scraper & LLM Summarizer
=================================================
Scrapes financial news from multiple sources for a given ticker,
then uses Google Gemini to produce structured summaries covering:
  - Insider activity
  - Institutional buying
  - Order book / block deals
  - Future expansion / capex
  - Auditor changes
  - Dividend news
  - New orders / contracts
  - Earnings / results
  - Management changes
  - Regulatory filings
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time as _time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx
import requests
from bs4 import BeautifulSoup

_llm_not_before: float = 0.0
_LLM_COOLDOWN_SECONDS = 60


def _llm_quota_available() -> bool:
    return _time.monotonic() >= _llm_not_before


def _record_quota_error(message: str) -> None:
    global _llm_not_before
    _llm_not_before = _time.monotonic() + _LLM_COOLDOWN_SECONDS
    logger.warning("LLM quota cooldown activated for %.0fs due to: %s", _LLM_COOLDOWN_SECONDS, message[:120])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_ticker_news")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TickerNewsArticle:
    title: str
    source: str
    url: str
    summary: str
    published_at: str  # ISO datetime
    relevance: str = "general"  # high / medium / general

@dataclass
class AITickerNewsReport:
    ticker: str
    company_name: str
    articles_scraped: int
    articles_after_dedup: int
    generated_at: str

    # LLM-generated structured fields
    insider_activity: str = ""
    institutional_activity: str = ""
    order_book_block_deals: str = ""
    future_expansion_capex: str = ""
    auditor_changes: str = ""
    dividend_news: str = ""
    new_orders_contracts: str = ""
    earnings_results: str = ""
    management_changes: str = ""
    regulatory_filings: str = ""
    sentiment_overall: str = ""
    risk_flags: str = ""
    summary_headline: str = ""

    raw_articles: list[dict] | None = None

    def to_dict(self):
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}

# ---------------------------------------------------------------------------
# JSON repair helper
# ---------------------------------------------------------------------------

def _parse_json_response(text: str, expected_keys: list[str]) -> dict:
    """
    Parse a JSON response from the LLM, with repair strategies for
    common malformations (unterminated strings, trailing commas, etc.).
    Raises ValueError if parsing definitively fails after all repair attempts.
    """
    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: try to locate the JSON object boundaries and fix unterminated strings
    # Find the outermost { ... } block
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        candidate = text[brace_start:brace_end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Strategy 3: try to salvage by repairing unterminated strings
        # An unterminated string means the last string value wasn't closed.
        # The error "Unterminated string starting at: line X column Y" means
        # there's a string that never got its closing quote.
        repaired = _repair_unterminated_json(candidate)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Strategy 4: try stripping trailing unclosed content after last valid key-value
        repaired2 = _strip_trailing_garbage(candidate)
        try:
            return json.loads(repaired2)
        except json.JSONDecodeError:
            pass

    # Strategy 5: last resort — extract individual key-value pairs via regex
    result = {}
    for key in expected_keys:
        # Try to find "key": "value" or "key": value patterns
        pattern = rf'"{re.escape(key)}"\s*:\s*"((?:[^"\\]|\\.)*)"'
        m = re.search(pattern, text)
        if m:
            result[key] = m.group(1)
            continue
        # Try non-string values (bool, number, null)
        pattern2 = rf'"{re.escape(key)}"\s*:\s*(\btrue\b|\bfalse\b|\bnull\b|\d+(?:\.\d+)?)'
        m2 = re.search(pattern2, text, re.IGNORECASE)
        if m2:
            val = m2.group(1).lower()
            result[key] = {"true": "Bullish", "false": "Bearish"}.get(val, val)
            continue
        # Try to grab anything after the key colon until comma or closing brace
        pattern3 = rf'"{re.escape(key)}"\s*:\s*([^,}}]+)'
        m3 = re.search(pattern3, text)
        if m3:
            val = m3.group(1).strip().strip('"').strip("'")
            result[key] = val

    return result


def _repair_unterminated_json(text: str) -> str:
    """
    Attempt to fix an unterminated string at the end of a JSON object.
    Adds a closing quote and fills in missing value placeholders if needed.
    """
    # Count quotes to determine if the last string is unterminated
    # Walk backwards from the end to find the opening quote of an unterminated string
    in_string = False
    escaped = False
    last_string_start = -1
    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            if in_string:
                in_string = False
            else:
                in_string = True
                last_string_start = i

    # If we ended inside a string, the JSON is unterminated
    if in_string:
        # Add a closing quote
        text += '"'
        # Ensure the object is properly closed
        if not text.rstrip().endswith("}"):
            text += "\n}"
        return text

    return text


def _strip_trailing_garbage(text: str) -> str:
    """
    If text after the last complete key-value pair is garbled (e.g. unclosed string),
    try to find the last valid comma-separated entry and truncate there.
    """
    # Try parsing character by character from the end, removing trailing content
    for end_idx in range(len(text), -1, -1):
        candidate = text[:end_idx].rstrip(",").rstrip()
        if not candidate.endswith("}"):
            candidate += "}"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    # If nothing works, return original
    return text


# ---------------------------------------------------------------------------
# Scraper implementations
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

TICKER_MAP = {
    # Map common tickers to search-friendly names for Indian markets
    "RELIANCE": "Reliance Industries",
    "TCS": "Tata Consultancy Services",
    "HDFCBANK": "HDFC Bank",
    "INFY": "Infosys",
    "ICICIBANK": "ICICI Bank",
    "KOTAKBANK": "Kotak Mahindra Bank",
    "SBIN": "State Bank of India",
    "BHARTIARTL": "Bharti Airtel",
    "ITC": "ITC Limited",
    "WIPRO": "Wipro",
    "HINDUNILVR": "Hindustan Unilever",
    "LT": "Larsen & Toubro",
    "TITAN": "Titan Company",
    "ASIANPAINT": "Asian Paints",
    "MARUTI": "Maruti Suzuki",
    "BAJFINANCE": "Bajaj Finance",
    "NTPC": "NTPC",
    "POWERGRID": "Power Grid Corporation",
    "AXISBANK": "Axis Bank",
    "SUNPHARMA": "Sun Pharmaceutical",
}


def _company_name(ticker: str) -> str:
    return TICKER_MAP.get(ticker.upper(), ticker)


def _clean_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


async def scrape_moneycontrol(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Moneycontrol news for the given ticker."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    search_q = quote_plus(f"{company} {ticker}")
    urls = [
        f"https://www.moneycontrol.com/news/tags/{ticker.lower()}.html",
        f"https://www.moneycontrol.com/news/business/stocks/page-1?search={search_q}",
    ]

    for url in urls:
        try:
            resp = await session.get(url, headers=HEADERS, timeout=15.0)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select("li.clearfix") or soup.select("li.grp_list") or soup.select("li a")
            count = 0
            for item in items:
                if count >= 15:
                    break
                link_tag = item.find("a") if not item.name == "a" else item
                if not link_tag or not link_tag.get("href"):
                    continue
                href = link_tag.get("href", "")
                if not href.startswith("http"):
                    href = f"https://www.moneycontrol.com{href}" if href.startswith("/") else href

                title_tag = item.find("h2") or item.find("h3") or item.find("h1")
                title = title_tag.get_text(strip=True) if title_tag else link_tag.get_text(strip=True)
                if not title or len(title) < 15:
                    continue

                summary_tag = item.find("p")
                summary = summary_tag.get_text(strip=True) if summary_tag else ""

                time_tag = item.find("time") or item.find("span", class_=re.compile(r"date|time"))
                published = time_tag.get("datetime", "") if time_tag else ""

                if not any(kw.lower() in title.lower() for kw in [ticker.lower(), company[:10].lower()]):
                    if summary and not any(kw.lower() in summary.lower() for kw in [ticker.lower(), company[:10].lower()]):
                        continue

                articles.append(TickerNewsArticle(
                    title=title[:300],
                    source="Moneycontrol",
                    url=href[:500],
                    summary=summary[:500],
                    published_at=published or datetime.now(timezone.utc).isoformat(),
                ))
                count += 1
        except Exception as e:
            logger.warning("Moneycontrol scrape failed for %s: %s", ticker, e)

    return articles


async def scrape_economic_times(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Economic Times news."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    search_q = quote_plus(f"{ticker} stock")
    url = f"https://economictimes.indiatimes.com/topic/{ticker.lower()}"

    try:
        resp = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            url = f"https://economictimes.indiatimes.com/search?q={search_q}"
            resp = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        for link_tag in soup.select("a[href*='articleshow']"):
            title = link_tag.get_text(strip=True)
            if not title or len(title) < 20:
                continue
            href = link_tag.get("href", "")
            if href.startswith("/"):
                href = f"https://economictimes.indiatimes.com{href}"

            p_tag = link_tag.find_parent("div")
            summary = ""
            if p_tag:
                p_text = p_tag.find("p")
                if p_text:
                    summary = p_text.get_text(strip=True)

            if not any(kw.lower() in title.lower() for kw in [ticker.lower(), company[:10].lower()]):
                if summary and not any(kw.lower() in summary.lower() for kw in [ticker.lower(), company[:10].lower()]):
                    continue

            articles.append(TickerNewsArticle(
                title=title[:300],
                source="Economic Times",
                url=href[:500],
                summary=summary[:500],
                published_at=datetime.now(timezone.utc).isoformat(),
            ))
            if len(articles) >= 15:
                break
    except Exception as e:
        logger.warning("ET scrape failed for %s: %s", ticker, e)

    return articles


async def scrape_yahoo_finance(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Yahoo Finance for news."""
    articles: list[TickerNewsArticle] = []
    # For Indian stocks, Yahoo uses .NS suffix
    yahoo_ticker = f"{ticker}.NS" if not ticker.endswith(".NS") else ticker
    url = f"https://finance.yahoo.com/quote/{yahoo_ticker}/"

    try:
        resp = await session.get(url, headers=HEADERS, timeout=15.0)
        if resp.status_code != 200:
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        # Yahoo finance news stream
        for item in soup.select("li.stream-item") or soup.select("[data-test='news-stream'] li"):
            link_tag = item.find("a")
            if not link_tag:
                continue
            title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")
            if href.startswith("/"):
                href = f"https://finance.yahoo.com{href}"

            summary_tag = item.find("p")
            summary = summary_tag.get_text(strip=True) if summary_tag else ""

            time_tag = item.find("time")
            published = time_tag.get("datetime", "") if time_tag else ""

            articles.append(TickerNewsArticle(
                title=title[:300],
                source="Yahoo Finance",
                url=href[:500],
                summary=summary[:500],
                published_at=published or datetime.now(timezone.utc).isoformat(),
            ))
            if len(articles) >= 10:
                break
    except Exception as e:
        logger.warning("Yahoo Finance scrape failed for %s: %s", ticker, e)

    return articles


async def scrape_nse_nifty100(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape NSE NIFTY 100 index tracker page for relevant headlines."""
    articles: list[TickerNewsArticle] = []
    url = "https://www.nseindia.com/index-tracker/NIFTY%20100"
    try:
        headers = {
            **HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.nseindia.com/",
        }
        resp = await session.get(url, headers=headers, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()
        for tag in soup.find_all(["h2", "h3", "a", "p"])[:80]:
            text = tag.get_text(strip=True)
            if not text or len(text) < 25:
                continue
            key = re.sub(r"\s+", " ", text.lower())[:60]
            if key in seen:
                continue
            seen.add(key)

            articles.append(TickerNewsArticle(
                title=text[:300],
                source="NSE NIFTY 100",
                url=url,
                summary=text[:300],
                published_at=datetime.now(timezone.utc).isoformat(),
            ))
            if len(articles) >= 12:
                break
    except Exception as e:
        logger.warning("NSE NIFTY 100 scrape failed: %s", e)

    return articles


async def _scrape_zerodha_pulse(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Zerodha Pulse for market news."""
    articles: list[TickerNewsArticle] = []
    url = "https://pulse.zerodha.com/"
    try:
        resp = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()
        for tag in soup.find_all(["h2", "h3", "a", "p", "span"])[:100]:
            text = tag.get_text(strip=True)
            if not text or len(text) < 25:
                continue
            key = re.sub(r"\s+", " ", text.lower())[:60]
            if key in seen:
                continue
            seen.add(key)

            articles.append(TickerNewsArticle(
                title=text[:300],
                source="Zerodha Pulse",
                url=url,
                summary=text[:300],
                published_at=datetime.now(timezone.utc).isoformat(),
            ))
            if len(articles) >= 10:
                break
    except Exception as e:
        logger.warning("Zerodha Pulse scrape failed: %s", e)

    return articles


async def _scrape_trendlyne(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Trendlyne for stock news and analysis."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    url = f"https://trendlyne.com/stock/{quote_plus(ticker)}/{quote_plus(company)}"
    try:
        resp = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            url = f"https://trendlyne.com/news?q={quote_plus(f'{company} {ticker}')}"
            resp = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()
        for tag in soup.find_all(["h2", "h3", "a", "p"])[:80]:
            text = tag.get_text(strip=True)
            if not text or len(text) < 25:
                continue
            key = re.sub(r"\s+", " ", text.lower())[:60]
            if key in seen:
                continue
            seen.add(key)

            articles.append(TickerNewsArticle(
                title=text[:300],
                source="Trendlyne",
                url=url,
                summary=text[:300],
                published_at=datetime.now(timezone.utc).isoformat(),
            ))
            if len(articles) >= 10:
                break
    except Exception as e:
        logger.warning("Trendlyne scrape failed: %s", e)

    return articles


async def _scrape_finshots(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Finshots for financial news and analysis."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    url = f"https://finshots.in/?s={quote_plus(company)}"
    try:
        resp = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            url = "https://finshots.in/"
            resp = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return articles

        soup = BeautifulSoup(resp.text, "html.parser")
        seen: set[str] = set()
        for tag in soup.find_all(["h2", "h3", "a", "p", "article"])[:80]:
            text = tag.get_text(strip=True)
            if not text or len(text) < 25:
                continue
            key = re.sub(r"\s+", " ", text.lower())[:60]
            if key in seen:
                continue
            seen.add(key)

            articles.append(TickerNewsArticle(
                title=text[:300],
                source="Finshots",
                url=url,
                summary=text[:300],
                published_at=datetime.now(timezone.utc).isoformat(),
            ))
            if len(articles) >= 10:
                break
    except Exception as e:
        logger.warning("Finshots scrape failed: %s", e)

    return articles


async def scrape_nse_announcements(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape NSE corporate announcements."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    url = "https://www.nseindia.com/api/corporates/corporateAnnouncements"
    params = {
        "index": quote_plus(company),
        "market": "equities",
    }

    try:
        headers = {
            **HEADERS,
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        resp = await session.get(url, params=params, headers=headers, timeout=15.0)
        if resp.status_code == 200:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            for item in items[:15]:
                title = item.get("heading") or item.get("desc") or item.get("subject", "")
                if not title:
                    continue
                desc = item.get("details") or item.get("description", "")
                dt = item.get("dt") or item.get("date", "")

                articles.append(TickerNewsArticle(
                    title=str(title)[:300],
                    source="NSE Announcements",
                    url="https://www.nseindia.com/",
                    summary=str(desc)[:500],
                    published_at=str(dt) if dt else datetime.now(timezone.utc).isoformat(),
                    relevance="high",
                ))
    except Exception as e:
        logger.warning("NSE announcements scrape failed: %s", e)

    return articles


async def scrape_all_sources(ticker: str) -> list[TickerNewsArticle]:
    """Run all scrapers concurrently and return deduplicated articles."""
    async with httpx.AsyncClient(verify=False, timeout=30.0) as session:
        tasks = [
            scrape_moneycontrol(ticker, session),
            scrape_economic_times(ticker, session),
            scrape_yahoo_finance(ticker, session),
            scrape_nse_announcements(ticker, session),
            scrape_nse_nifty100(ticker, session),
            _scrape_zerodha_pulse(ticker, session),
            _scrape_trendlyne(ticker, session),
            _scrape_finshots(ticker, session),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles: list[TickerNewsArticle] = []
    for r in results:
        if isinstance(r, list):
            all_articles.extend(r)
        elif isinstance(r, Exception):
            logger.error("Scraper error: %s", r)

    # Deduplicate by title similarity
    seen_titles: set[str] = set()
    deduped: list[TickerNewsArticle] = []
    for art in all_articles:
        # Simple dedup: normalize and compare first 60 chars
        key = re.sub(r"\s+", " ", art.title.lower())[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            deduped.append(art)

    logger.info(
        "Scraped %d articles from %d sources for %s (after dedup: %d)",
        len(all_articles),
        len(results),
        ticker,
        len(deduped),
    )
    return deduped

# ---------------------------------------------------------------------------
# LLM Summarizer
# ---------------------------------------------------------------------------

_LLM_SEMAPHORE = asyncio.Semaphore(1)
# Snapshot file path — stores tickerNewsByTicker alongside market data
_SNAPSHOT_FILE = os.environ.get(
    "SNAPSHOT_FILE",
    os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "trade_api_snapshot.json",
        )
    ),
)
_llm_cache: dict[str, dict] = {}


def _load_llm_cache() -> None:
    """Load cached LLM summaries from trade_api_snapshot.json -> tickerNewsByTicker."""
    global _llm_cache
    try:
        if os.path.exists(_SNAPSHOT_FILE):
            with open(_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
            _llm_cache = snapshot.get("tickerNewsByTicker", {})
            logger.info("Loaded %d cached LLM summaries from snapshot", len(_llm_cache))
    except Exception as e:
        logger.warning("Failed to load LLM cache from snapshot: %s", e)
        _llm_cache = {}


def _save_llm_cache() -> None:
    """Persist LLM summary into trade_api_snapshot.json -> tickerNewsByTicker."""
    try:
        snapshot = {}
        if os.path.exists(_SNAPSHOT_FILE):
            with open(_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
        snapshot["tickerNewsByTicker"] = _llm_cache
        with open(_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        logger.debug("Saved LLM cache to snapshot (%d tickers)", len(_llm_cache))
    except Exception as e:
        logger.warning("Failed to save LLM cache to snapshot: %s", e)


def _cache_key(ticker: str, articles: list[TickerNewsArticle], max_articles: int) -> str:
    """Simple per-ticker cache key — one LLM summary per ticker."""
    return ticker.upper()


def get_cached_summary(
    ticker: str,
    articles: list[TickerNewsArticle],
    max_articles: int,
    force_refresh: bool = False,
) -> dict | None:
    """Return cached summary if available and fresh (24h TTL), unless force_refresh=True."""
    if force_refresh:
        return None
    key = _cache_key(ticker, articles, max_articles)
    entry = _llm_cache.get(key)
    if not entry:
        return None
    generated_at = entry.get("generated_at")
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at)
            if datetime.now(timezone.utc) - dt > __import__("datetime").timedelta(hours=24):
                return None
        except Exception:
            pass
    return entry


def set_cached_summary(
    ticker: str,
    articles: list[TickerNewsArticle],
    max_articles: int,
    llm_result: dict,
) -> None:
    key = _cache_key(ticker, articles, max_articles)
    entry = dict(llm_result)
    entry["generated_at"] = datetime.now(timezone.utc).isoformat()
    entry["ticker"] = ticker.upper()
    _llm_cache[key] = entry
    _save_llm_cache()


# Load cache at import time
_load_llm_cache()


async def summarize_with_gemini(ticker: str, company: str, articles: list[TickerNewsArticle]) -> dict:
    """Use Google Gemini to produce a structured news summary with model fallback on 429."""
    gemini_api_key = os.environ.get("REDACTED") or os.environ.get("GOOGLE_API_KEY")
    if not gemini_api_key:
        logger.warning("No REDACTED or GOOGLE_API_KEY set — falling back to rule-based summary")
        return _rule_based_summary(ticker, company, articles)

    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai not installed — falling back to rule-based summary")
        return _rule_based_summary(ticker, company, articles)

    if not _llm_quota_available():
        logger.warning("LLM quota exhausted, using rule-based summary for %s", ticker)
        return _rule_based_summary(ticker, company, articles)

    primary_model = os.environ.get("LLM_MODEL", "gemini-2.5-flash")
    fallback_models = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro","gemini-3.0-flash","gemini-3.5-flash","gemini-3.1-flash-lite"]
    model_list = [primary_model]
    for m in fallback_models:
        if m not in model_list:
            model_list.append(m)

    article_text = "\n\n".join(
        f"Title: {a.title}\nSource: {a.source}\nSummary: {a.summary}\nPublished: {a.published_at}\nURL: {a.url}"
        for a in articles[:30]
    )

    prompt = f"""You are a financial news analyst. Analyze the following news articles for the company "{company}" (ticker: {ticker}) on the Indian stock market.

For each of the categories below, provide a concise 1-3 sentence summary based ONLY on information present in the articles. If no information is found for a category, write "No recent news found."

Categories to analyze:
1. insider_activity - Insider trading, promoter buying/selling, pledged shares
2. institutional_activity - FII/DII buying/selling, mutual fund activity, QIP, FPO
3. order_book_block_deals - Order book updates, block deals, bulk deals
4. future_expansion_capex - Capacity expansion, new projects, capex plans, acquisitions
5. auditor_changes - Auditor resignations, changes, qualifications
6. dividend_news - Dividend announcements, buybacks, bonuses, splits
7. new_orders_contracts - New order wins, contract announcements, government approvals
8. earnings_results - Quarterly/annual results, revenue, profit margins, guidance
9. management_changes - CEO/CFO changes, board appointments, key management moves
10. regulatory_filings - SEBI filings, regulatory approvals, compliance issues

Also provide:
- sentiment_overall: Bullish / Neutral / Bearish (single word)
- risk_flags: Any red flags or risks mentioned (comma separated, or "None")
- summary_headline: One-line summary of the most important news

Here are the articles:
{article_text}

Respond ONLY in valid JSON format with these exact keys: insider_activity, institutional_activity, order_book_block_deals, future_expansion_capex, auditor_changes, dividend_news, new_orders_contracts, earnings_results, management_changes, regulatory_filings, sentiment_overall, risk_flags, summary_headline
"""

    expected_keys = [
        "insider_activity", "institutional_activity", "order_book_block_deals",
        "future_expansion_capex", "auditor_changes", "dividend_news",
        "new_orders_contracts", "earnings_results", "management_changes",
        "regulatory_filings", "sentiment_overall", "risk_flags", "summary_headline"
    ]

    for model in model_list:
        try:
            client = genai.Client(api_key=gemini_api_key)

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 2048,
                },
            )

            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = _parse_json_response(text, expected_keys)
            for key in expected_keys:
                result.setdefault(key, "No recent news found.")

            logger.info("Gemini analysis complete for %s using model %s", ticker, model)
            return result

        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "429" in str(e) or "rate limit" in err_str or "quota" in err_str or "resource exhausted" in err_str
            if is_rate_limit:
                logger.warning("Model %s hit rate limit for %s, trying next model...", model, ticker)
                continue
            logger.error("Gemini summarization with model %s failed for %s: %s — falling back to rule-based summary", model, ticker, e)
            return _rule_based_summary(ticker, company, articles)

    _record_quota_error("All models exhausted for " + ticker)
    logger.warning("All Gemini models exhausted for %s, using rule-based summary", ticker)
    return _rule_based_summary(ticker, company, articles)


def _rule_based_summary(ticker: str, company: str, articles: list[TickerNewsArticle]) -> dict:
    """Fallback rule-based categorization when LLM is unavailable."""
    result = {
        "insider_activity": "No recent news found.",
        "institutional_activity": "No recent news found.",
        "order_book_block_deals": "No recent news found.",
        "future_expansion_capex": "No recent news found.",
        "auditor_changes": "No recent news found.",
        "dividend_news": "No recent news found.",
        "new_orders_contracts": "No recent news found.",
        "earnings_results": "No recent news found.",
        "management_changes": "No recent news found.",
        "regulatory_filings": "No recent news found.",
        "sentiment_overall": "Neutral",
        "risk_flags": "None",
        "summary_headline": f"{len(articles)} articles found for {company}.",
    }

    keywords_map = {
        "insider_activity": ["insider", "promoter", "pledge", "shareholding pattern", "buyback"],
        "institutional_activity": ["fii", "dii", "mutual fund", "qip", "fpo", "institutional", "bulk deal"],
        "order_book_block_deals": ["order book", "block deal", "bulk deal", "order inflow"],
        "future_expansion_capex": ["expansion", "capex", "new project", "acquisition", "subsidiary"],
        "auditor_changes": ["auditor", "audit", "delloite", "pwc", "kpmg", "ernst", "resignation"],
        "dividend_news": ["dividend", "bonus", "stock split", "buyback"],
        "new_orders_contracts": ["order", "contract", "approval", "government", "deal worth"],
        "earnings_results": ["result", "quarter", "revenue", "profit", "margin", "EBITDA", "PAT"],
        "management_changes": ["CEO", "CFO", "appointed", "resigned", "board", "director"],
        "regulatory_filings": ["SEBI", "regulatory", "compliance", "filing", "ROC", "RBI"],
    }

    for article in articles:
        text = f"{article.title} {article.summary}".lower()
        for category, keywords in keywords_map.items():
            for kw in keywords:
                if kw.lower() in text:
                    if result[category] == "No recent news found.":
                        result[category] = f"Related: {article.title[:200]}"
                    break

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_ticker_news_report(
    ticker: str,
    company_name: str | None = None,
    max_articles: int = 50,
    include_raw: bool = False,
    force_refresh: bool = False,
) -> AITickerNewsReport:
    """Full pipeline: scrape → dedup → LLM summarize → return structured report."""
    ticker = ticker.upper().strip()
    company = company_name or _company_name(ticker)

    # Step 1: Scrape
    articles = await scrape_all_sources(ticker)
    if len(articles) > max_articles:
        articles = articles[:max_articles]

    # Step 2: LLM Summarize (with snapshot cache to preserve quota)
    cached = get_cached_summary(ticker, articles, max_articles, force_refresh=force_refresh)
    if cached is not None:
        logger.info("Using cached LLM summary for %s (max_articles=%d)", ticker, max_articles)
        llm_result = cached
    else:
        llm_result = await summarize_with_gemini(ticker, company, articles)
        set_cached_summary(ticker, articles, max_articles, llm_result)

    # Step 3: Build report
    report = AITickerNewsReport(
        ticker=ticker,
        company_name=company,
        articles_scraped=len(articles),
        articles_after_dedup=len(articles),
        generated_at=datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in llm_result.items() if k in AITickerNewsReport.__dataclass_fields__},
    )

    if include_raw:
        report.raw_articles = [
            {
                "title": a.title,
                "source": a.source,
                "url": a.url,
                "summary": a.summary,
                "published_at": a.published_at,
                "relevance": a.relevance,
            }
            for a in articles
        ]

    return report


# CLI entry point
async def main():
    parser = argparse.ArgumentParser(description="AI Ticker News Scraper & Summarizer")
    parser.add_argument("ticker", help="Stock ticker symbol (e.g., RELIANCE, TCS)")
    parser.add_argument("--company", help="Company name (optional, auto-resolved if not given)")
    parser.add_argument("--max-articles", type=int, default=50, help="Max articles to analyze")
    parser.add_argument("--include-raw", action="store_true", help="Include raw article list in output")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    args = parser.parse_args()

    report = await generate_ticker_news_report(
        ticker=args.ticker,
        company_name=args.company,
        max_articles=args.max_articles,
        include_raw=args.include_raw,
    )

    output = json.dumps(report.to_dict(), indent=2 if args.pretty else None, default=str)
    print(output)


if __name__ == "__main__":
    asyncio.run(main())