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
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time as _time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx
import requests
from bs4 import BeautifulSoup

from .tinyfish_news import backup_min_articles, search_tinyfish, tinyfish_enabled

# Cap concurrent outbound scrapes (batch × 7 sources was melting DNS).
_SCRAPE_CONCURRENCY = int(os.getenv("NEWS_SCRAPE_CONCURRENCY", "3"))
_SCRAPE_SEMAPHORE: asyncio.Semaphore | None = None
_DNS_CIRCUIT_UNTIL = 0.0
_DNS_CIRCUIT_SECONDS = float(os.getenv("NEWS_DNS_CIRCUIT_SECONDS", "45"))
_DNS_FAIL_STREAK = 0
_DNS_FAIL_THRESHOLD = int(os.getenv("NEWS_DNS_FAIL_THRESHOLD", "4"))
_LAST_DNS_WARN_MONO = 0.0


def _scrape_semaphore() -> asyncio.Semaphore:
    global _SCRAPE_SEMAPHORE
    if _SCRAPE_SEMAPHORE is None:
        _SCRAPE_SEMAPHORE = asyncio.Semaphore(_SCRAPE_CONCURRENCY)
    return _SCRAPE_SEMAPHORE


def _is_dns_or_connect_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        k in msg
        for k in (
            "getaddrinfo",
            "name or service not known",
            "nodename nor servname",
            "temporary failure in name resolution",
            "all connection attempts failed",
            "connecterror",
            "network is unreachable",
        )
    )


def _trip_dns_circuit(exc: BaseException) -> None:
    global _DNS_CIRCUIT_UNTIL, _DNS_FAIL_STREAK, _LAST_DNS_WARN_MONO
    if not _is_dns_or_connect_error(exc):
        _DNS_FAIL_STREAK = 0
        return
    _DNS_FAIL_STREAK += 1
    if _DNS_FAIL_STREAK < _DNS_FAIL_THRESHOLD:
        return
    now = _time.monotonic()
    _DNS_CIRCUIT_UNTIL = now + _DNS_CIRCUIT_SECONDS
    if now - _LAST_DNS_WARN_MONO >= 15:
        _LAST_DNS_WARN_MONO = now
        logger.warning(
            "News scrape DNS/connect circuit open for %.0fs after %d failures (%s)",
            _DNS_CIRCUIT_SECONDS,
            _DNS_FAIL_STREAK,
            str(exc)[:120],
        )


def _dns_circuit_open() -> bool:
    return _time.monotonic() < _DNS_CIRCUIT_UNTIL


def _note_scrape_success() -> None:
    global _DNS_FAIL_STREAK
    _DNS_FAIL_STREAK = 0


def _warn_scrape_failure(source: str, exc: BaseException, ticker: str | None = None) -> None:
    """Log scrape failure once per burst; trip DNS circuit on connect errors."""
    global _LAST_DNS_WARN_MONO
    _trip_dns_circuit(exc)
    if _is_dns_or_connect_error(exc):
        now = _time.monotonic()
        if now - _LAST_DNS_WARN_MONO < 15 and _dns_circuit_open():
            return
        _LAST_DNS_WARN_MONO = now
    if ticker:
        logger.warning("%s scrape failed for %s: %s", source, ticker, exc)
    else:
        logger.warning("%s scrape failed: %s", source, exc)


def _reraise_if_dns(exc: BaseException) -> None:
    """Let _guarded_scrape own DNS circuit + logging after inner scrapers trip once."""
    if _is_dns_or_connect_error(exc):
        raise exc


async def _guarded_scrape(name: str, coro):
    """Limit concurrency + skip when DNS circuit is open."""
    if _dns_circuit_open():
        return []
    async with _scrape_semaphore():
        if _dns_circuit_open():
            return []
        try:
            result = await coro
            _note_scrape_success()
            return result
        except Exception as exc:
            _warn_scrape_failure(name, exc)
            return []


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
    lookback_days: int = 7
    evidence_status: str = "NO_RECENT_EVIDENCE"
    sources_checked: list[str] | None = None

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
    llmUsed: bool = False
    llmError: str = ""

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
        # First, attempt to extract a nested object value (for keys like "audits")
        # by locating "{ ... }" after the key rather than treating it as a plain string.
        nested_pattern = rf'"{re.escape(key)}"\s*:\s*({{)'
        m_nested = re.search(nested_pattern, text)
        if m_nested:
            brace_start = m_nested.start(1)
            depth = 0
            in_string = False
            escaped = False
            brace_end = -1
            for i in range(brace_start, len(text)):
                ch = text[i]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        brace_end = i
                        break
            if brace_end > brace_start:
                nested_blob = text[brace_start:brace_end + 1]
                try:
                    result[key] = json.loads(nested_blob)
                    continue
                except (json.JSONDecodeError, TypeError):
                    pass  # fall through to string extraction

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
    Returns a valid JSON *string* (not a parsed dict) so the caller can json.loads() it.
    """
    # Try parsing character by character from the end, removing trailing content
    for end_idx in range(len(text), -1, -1):
        candidate = text[:end_idx].rstrip(",").rstrip()
        if not candidate.endswith("}"):
            candidate += "}"
        try:
            json.loads(candidate)  # validate only
            return candidate       # return the repaired string
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
    "TEXRAIL": "Texmaco Rail & Engineering",
}

NEWS_LOOKBACK_DAYS = max(1, min(int(os.getenv("NEWS_LOOKBACK_DAYS", "7")), 30))
NEWS_LLM_ARTICLE_LIMIT = max(1, min(int(os.getenv("NEWS_LLM_ARTICLE_LIMIT", "8")), 15))


TRENDLYNE_TICKER_ID_MAP = {
    "WIPRO": "12799",
    "RELIANCE": "1127",
    "TCS": "630",
    "INFY": "630",
    "HDFCBANK": "533",
    "ICICIBANK": "584",
    "KOTAKBANK": "1887",
    "SBIN": "1193",
    "BHARTIARTL": "276825",
    "ITC": "1198",
    "HINDUNILVR": "561",
    "LT": "1199",
}


def _get_trendlyne_equity_url(ticker: str) -> str | None:
    """Get Trendlyne equity page URL for a ticker if ID is known."""
    equity_id = TRENDLYNE_TICKER_ID_MAP.get(ticker.upper())
    if equity_id:
        slug = TICKER_MAP.get(ticker.upper(), ticker.lower()).lower().replace(" ", "-")
        return f"https://trendlyne.com/equity/{equity_id}/{ticker.upper()}/{slug}/"
    return None


def _company_name(ticker: str) -> str:
    return TICKER_MAP.get(ticker.upper(), ticker)


def _clean_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _parse_published_at(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    relative = re.search(r"\b(\d+)\s*(minute|hour|day)s?\s+ago\b", raw, re.IGNORECASE)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        return datetime.now(timezone.utc) - timedelta(**{f"{unit}s": amount})
    try:
        parsed = parsedate_to_datetime(raw)
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _recent_articles(articles: list[TickerNewsArticle]) -> list[TickerNewsArticle]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
    recent: list[tuple[datetime, TickerNewsArticle]] = []
    for article in articles:
        published = _parse_published_at(article.published_at)
        if published is None or published < cutoff:
            continue
        article.published_at = published.isoformat()
        recent.append((published, article))
    relevance_order = {"high": 0, "medium": 1, "general": 2}
    recent.sort(key=lambda pair: (relevance_order.get(pair[1].relevance, 3), -pair[0].timestamp()))
    return [article for _, article in recent]


async def scrape_google_news(
    ticker: str,
    session: httpx.AsyncClient,
    company_name: str | None = None,
) -> list[TickerNewsArticle]:
    """Search seven-day publisher coverage and retain the originating publication."""
    company = company_name or _company_name(ticker)
    query = quote_plus(f'("{ticker}" OR "{company}") stock when:{NEWS_LOOKBACK_DAYS}d')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        response = await session.get(url, headers=HEADERS, timeout=15.0, follow_redirects=True)
        if response.status_code != 200:
            return []
        root = ElementTree.fromstring(response.content)
        articles: list[TickerNewsArticle] = []
        for item in root.findall(".//item")[:20]:
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            source_node = item.find("source")
            source = (source_node.text or "Google News").strip() if source_node is not None else "Google News"
            articles.append(TickerNewsArticle(
                title=title[:300],
                source=source[:100],
                url=(item.findtext("link") or url)[:500],
                summary=_clean_html(item.findtext("description") or "")[:500],
                published_at=(item.findtext("pubDate") or "").strip(),
                relevance="medium",
            ))
        return articles
    except Exception as exc:
        _reraise_if_dns(exc)
        _warn_scrape_failure("Google News", exc, ticker)
        return []


async def scrape_bse_announcements(
    ticker: str,
    session: httpx.AsyncClient,
    company_name: str | None = None,
) -> list[TickerNewsArticle]:
    """Resolve the BSE scrip code, then fetch exact-company announcements."""
    try:
        headers = {**HEADERS, "Accept": "application/json", "Origin": "https://www.bseindia.com", "Referer": "https://www.bseindia.com/"}
        suggest = await session.get(
            "https://api.bseindia.com/BseIndiaAPI/api/Suggest/w",
            params={"text": ticker},
            headers=headers,
            timeout=15.0,
        )
        if suggest.status_code != 200:
            return []
        suggestions = suggest.json()
        rows = suggestions if isinstance(suggestions, list) else suggestions.get("Table") or suggestions.get("Data") or suggestions.get("data") or []
        exact = next(
            (
                row for row in rows
                if isinstance(row, dict)
                and str(row.get("scrip_id") or row.get("symbol") or row.get("ScripID") or "").upper() == ticker.upper()
            ),
            None,
        )
        if exact is None:
            company_prefix = (company_name or _company_name(ticker)).split(" ")[0].upper()
            exact = next((row for row in rows if company_prefix in str(row).upper()), None)
        if isinstance(exact, dict):
            scrip = exact.get("scrip_cd") or exact.get("ScripCode") or exact.get("code") or exact.get("id")
        else:
            code_match = re.search(r"\b\d{6}\b", str(exact or ""))
            scrip = code_match.group(0) if code_match else None
        if not scrip:
            return []
        now = datetime.now(timezone.utc)
        response = await session.get(
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
            params={
                "pageno": 1,
                "strCat": -1,
                "strPrevDate": (now - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%Y%m%d"),
                "strScrip": str(scrip),
                "strSearch": "P",
                "strToDate": now.strftime("%Y%m%d"),
                "strType": "C",
                "subcategory": -1,
            },
            headers=headers,
            timeout=15.0,
        )
        if response.status_code != 200:
            return []
        payload = response.json()
        announcements = payload.get("Table") or payload.get("data") or []
        result: list[TickerNewsArticle] = []
        for item in announcements[:20]:
            title = item.get("HEADLINE") or item.get("NEWSSUB") or item.get("CATEGORYNAME") or "BSE corporate filing"
            attachment = item.get("ATTACHMENTNAME") or item.get("NSURL") or ""
            if attachment and not str(attachment).startswith("http"):
                attachment = f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attachment}"
            result.append(TickerNewsArticle(
                title=str(title)[:300],
                source="BSE Announcements",
                url=str(attachment or "https://www.bseindia.com/corporates/ann.html")[:500],
                summary=str(item.get("MORE") or item.get("NEWS_DT") or "")[:500],
                published_at=str(item.get("NEWS_DT") or item.get("DT_TM") or ""),
                relevance="high",
            ))
        return result
    except Exception as exc:
        _reraise_if_dns(exc)
        _warn_scrape_failure("BSE announcements", exc, ticker)
        return []


async def scrape_moneycontrol(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Moneycontrol news for the given ticker."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    search_q = quote_plus(f"{company} {ticker}")
    urls = [
        f"https://www.moneycontrol.com/news/business/stocks/page-1/?search={search_q}",
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
                    published_at=published,
                ))
                count += 1
        except Exception as e:
            _reraise_if_dns(e)
            _warn_scrape_failure("Moneycontrol", e, ticker)

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
            time_tag = p_tag.find("time") if p_tag else None
            if time_tag is None and p_tag:
                time_tag = p_tag.find("span", class_=re.compile(r"date|time", re.IGNORECASE))
            published = (time_tag.get("datetime") or time_tag.get_text(" ", strip=True)) if time_tag else ""

            if not any(kw.lower() in title.lower() for kw in [ticker.lower(), company[:10].lower()]):
                if summary and not any(kw.lower() in summary.lower() for kw in [ticker.lower(), company[:10].lower()]):
                    continue

            articles.append(TickerNewsArticle(
                title=title[:300],
                source="Economic Times",
                url=href[:500],
                summary=summary[:500],
                published_at=published,
            ))
            if len(articles) >= 15:
                break
    except Exception as e:
        _reraise_if_dns(e)
        _warn_scrape_failure("ET", e, ticker)

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
                published_at=published,
            ))
            if len(articles) >= 10:
                break
    except Exception as e:
        _reraise_if_dns(e)
        _warn_scrape_failure("Yahoo Finance", e, ticker)

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
        _reraise_if_dns(e)
        _warn_scrape_failure("NSE NIFTY 100", e)

    return articles


class PulseNewsCollector:
    def __init__(self, session: httpx.AsyncClient | None = None):
        self.base_url = "https://pulse.zerodha.com/"
        self.session = session
        self.cache: dict[tuple[str, ...], tuple[float, list[TickerNewsArticle]]] = {}
        self.cache_ttl = 300  # 5 minutes

    async def fetch_latest_news(self, symbols: list[str] | None = None) -> list[TickerNewsArticle]:
        """Fetch latest Zerodha Pulse news and filter by ticker/company relevance."""
        symbols = [s.strip() for s in symbols if s and s.strip()] if symbols else []
        cache_key = tuple(sorted(s.upper() for s in symbols))
        now = _time.monotonic()

        cached = self.cache.get(cache_key)
        if cached:
            cached_at, articles = cached
            if now - cached_at <= self.cache_ttl:
                return articles

        client = self.session or httpx.AsyncClient()
        should_close_client = self.session is None
        articles: list[TickerNewsArticle] = []

        try:
            response = await client.get(self.base_url, headers=HEADERS, timeout=15.0, follow_redirects=True)
            if response.status_code != 200:
                return articles

            soup = BeautifulSoup(response.text, "html.parser")
            seen_titles: set[str] = set()

            for article in soup.find_all("div", recursive=True)[:30]:
                title_tag = article.find(["h2", "h3", "a"])
                title = title_tag.get_text(" ", strip=True) if title_tag else None
                if not title or len(title) < 15:
                    continue

                link_tag = article.find("a", href=True)
                href = link_tag.get("href", "") if link_tag else ""
                if href and not href.startswith("http"):
                    href = f"{self.base_url.rstrip('/')}{href}" if href.startswith("/") else href

                timestamp_tag = article.find("span")
                timestamp = timestamp_tag.get_text(" ", strip=True) if timestamp_tag else ""

                if symbols:
                    title_upper = title.upper()
                    if not any(symbol.upper() in title_upper for symbol in symbols):
                        continue

                key = re.sub(r"\s+", " ", title.lower())[:60]
                if key in seen_titles:
                    continue
                seen_titles.add(key)

                articles.append(TickerNewsArticle(
                    title=title[:300],
                    source="Zerodha Pulse",
                    url=href[:500] if href else self.base_url,
                    summary=title[:500],
                    published_at=timestamp,
                    relevance="medium" if symbols else "general",
                ))

                if len(articles) >= 10:
                    break

            self.cache[cache_key] = (now, articles)
            return articles
        except Exception as e:
            _reraise_if_dns(e)
            _warn_scrape_failure("Zerodha Pulse", e)
            return []
        finally:
            if should_close_client:
                await client.aclose()


async def _scrape_zerodha_pulse(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Zerodha Pulse for market news."""
    company = _company_name(ticker)
    collector = PulseNewsCollector(session=session)
    return await collector.fetch_latest_news([ticker, company])


async def _scrape_trendlyne(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape Trendlyne for stock news and analysis."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    equity_url = _get_trendlyne_equity_url(ticker)
    urls = [equity_url] if equity_url else []
    
    for url in urls:
        try:
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
                if len(articles) >= 30:
                    break
        except Exception as e:
            _reraise_if_dns(e)
            _warn_scrape_failure("Trendlyne", e)

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
            if len(articles) >= 30:
                break
    except Exception as e:
        _reraise_if_dns(e)
        _warn_scrape_failure("Finshots", e)

    return articles


async def scrape_nse_announcements(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape NSE corporate announcements via announcements API."""
    articles: list[TickerNewsArticle] = []
    url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
    
    try:
        headers = {
            **HEADERS,
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        now = datetime.now(timezone.utc)
        resp = await session.get(
            url,
            params={
                "index": "equities",
                "symbol": ticker.upper(),
                "from_date": (now - timedelta(days=NEWS_LOOKBACK_DAYS)).strftime("%d-%m-%Y"),
                "to_date": now.strftime("%d-%m-%Y"),
            },
            headers=headers,
            timeout=15.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            # Filter by ticker symbol
            ticker_upper = ticker.upper()
            for item in items:
                sym = (item.get("symbol") or "").upper()
                if sym and sym != ticker_upper:
                    continue
                title = item.get("desc") or item.get("heading") or item.get("subject", "")
                if not title:
                    continue
                desc = item.get("attchmntText") or item.get("details") or item.get("description", "")
                dt = item.get("an_dt") or item.get("dt") or item.get("date", "")
                attachment_url = item.get("attchmntFile", "")
                if attachment_url and not str(attachment_url).startswith("http"):
                    attachment_url = f"https://nsearchives.nseindia.com/corporate/{attachment_url}"

                articles.append(TickerNewsArticle(
                    title=str(title)[:300],
                    source="NSE Announcements",
                    url=str(attachment_url) if attachment_url else "https://www.nseindia.com/",
                    summary=str(desc)[:500],
                    published_at=str(dt) if dt else "",
                    relevance="high",
                ))
                if len(articles) >= 15:
                    break
    except Exception as e:
        _reraise_if_dns(e)
        _warn_scrape_failure("NSE announcements", e)

    return articles


async def scrape_all_sources(ticker: str, company_name: str | None = None) -> list[TickerNewsArticle]:
    """Run scrapers with shared concurrency limit; TinyFish Search backs up a thin scrape."""
    all_articles: list[TickerNewsArticle] = []
    results: list = []
    if _dns_circuit_open():
        logger.warning("Skipping HTML news scrapers for %s — DNS/connect circuit open", ticker)
    else:
        async with httpx.AsyncClient(
            verify=False,
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://www.google.com/",
            },
        ) as session:
            tasks = [
                _guarded_scrape("Moneycontrol", scrape_moneycontrol(ticker, session)),
                _guarded_scrape("ET", scrape_economic_times(ticker, session)),
                _guarded_scrape("Google News", scrape_google_news(ticker, session, company_name)),
                _guarded_scrape("NSE announcements", scrape_nse_announcements(ticker, session)),
                _guarded_scrape("BSE announcements", scrape_bse_announcements(ticker, session, company_name)),
                _guarded_scrape("Yahoo Finance", scrape_yahoo_finance(ticker, session)),
                _guarded_scrape("Zerodha Pulse", _scrape_zerodha_pulse(ticker, session)),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, list):
                all_articles.extend(r)
            elif isinstance(r, Exception):
                _trip_dns_circuit(r)
                logger.error("Scraper error: %s", r)

    # Deduplicate by title similarity
    seen_titles: set[str] = set()
    deduped: list[TickerNewsArticle] = []
    for art in _recent_articles(all_articles):
        # Simple dedup: normalize and compare first 60 chars
        key = re.sub(r"\s+", " ", art.title.lower())[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            deduped.append(art)

    if tinyfish_enabled() and len(deduped) < backup_min_articles():
        query = f'("{company_name or _company_name(ticker)}" OR {ticker}) NSE stock'
        extra = await asyncio.to_thread(
            search_tinyfish,
            query,
            location="IN",
            language="en",
            domain_type="news",
            recency_minutes=NEWS_LOOKBACK_DAYS * 24 * 60,
        )
        added = 0
        for row in extra:
            key = re.sub(r"\s+", " ", row["title"].lower())[:60]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            added += 1
            deduped.append(
                TickerNewsArticle(
                    title=row["title"],
                    source=row["source"],
                    url=row["url"],
                    summary=row["summary"],
                    published_at=row["published_at"],
                    relevance="general",
                )
            )
        if added:
            logger.info("TinyFish backup added %d news items for %s (now %d articles)", added, ticker, len(deduped))

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
_CACHE_WRITE_LOCK = threading.RLock()
_LLM_CACHE_HOURS = max(1, int(os.getenv("NEWS_LLM_CACHE_HOURS", "6")))
_EMPTY_CACHE_MINUTES = max(5, int(os.getenv("NEWS_EMPTY_CACHE_MINUTES", "30")))


def _load_llm_cache() -> None:
    """Load cached LLM summaries from trade_api_snapshot.json -> tickerNewsByTicker.
    Uses utf-8-sig to handle files with a UTF-8 BOM (Byte Order Mark)."""
    global _llm_cache
    try:
        if os.path.exists(_SNAPSHOT_FILE):
            with open(_SNAPSHOT_FILE, "r", encoding="utf-8-sig") as f:
                snapshot = json.load(f)
            _llm_cache = snapshot.get("tickerNewsByTicker", {})
            logger.info("Loaded %d cached LLM summaries from snapshot", len(_llm_cache))
    except Exception as e:
        logger.warning("Failed to load LLM cache from snapshot: %s", e)
        _llm_cache = {}


def _save_llm_cache() -> None:
    """Persist LLM summary into trade_api_snapshot.json -> tickerNewsByTicker.
    Uses utf-8-sig for reading (handles BOM) and utf-8 for writing (no BOM)."""
    try:
        with _CACHE_WRITE_LOCK:
            snapshot = {}
            if os.path.exists(_SNAPSHOT_FILE):
                with open(_SNAPSHOT_FILE, "r", encoding="utf-8-sig") as f:
                    snapshot = json.load(f)
            snapshot["tickerNewsByTicker"] = _llm_cache
            parent = os.path.dirname(_SNAPSHOT_FILE) or "."
            os.makedirs(parent, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="ticker-news-", suffix=".json", dir=parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary, _SNAPSHOT_FILE)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        logger.debug("Saved LLM cache to snapshot (%d tickers)", len(_llm_cache))
    except Exception as e:
        logger.warning("Failed to save LLM cache to snapshot: %s", e)


def _cache_key(ticker: str, articles: list[TickerNewsArticle], max_articles: int) -> str:
    """Simple per-ticker cache key — one LLM summary per ticker."""
    return ticker.upper()


def ticker_news_report_is_llm_complete(report: dict | None) -> bool:
    """Accept completed LLM reports or explicit no-evidence reports, never quota/error shells."""
    if not isinstance(report, dict) or report.get("error"):
        return False
    if report.get("llmUsed") is True:
        return True
    if report.get("llmUsed") is False:
        return report.get("evidence_status") == "NO_RECENT_EVIDENCE" and not report.get("articles_scraped")
    headline = str(report.get("summary_headline") or "")
    if "LLM summary unavailable" in headline:
        return False
    return bool(headline.strip())


def _article_fingerprint(articles: list[TickerNewsArticle]) -> str:
    evidence = [f"{a.source}|{a.published_at}|{a.title}|{a.url}" for a in articles]
    return hashlib.sha256("\n".join(sorted(evidence)).encode("utf-8")).hexdigest()[:20]


def get_cached_summary(
    ticker: str,
    articles: list[TickerNewsArticle],
    max_articles: int,
    force_refresh: bool = False,
) -> dict | None:
    """Return cached summary while its evidence fingerprint and TTL remain valid."""
    if force_refresh:
        return None
    key = _cache_key(ticker, articles, max_articles)
    entry = _llm_cache.get(key)
    if not entry:
        return None
    if articles and entry.get("articleFingerprint") != _article_fingerprint(articles):
        return None
    generated_at = entry.get("generated_at")
    if generated_at:
        try:
            dt = datetime.fromisoformat(generated_at)
            dt = dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc)
            ttl = timedelta(hours=_LLM_CACHE_HOURS) if entry.get("llmUsed") is True else timedelta(minutes=_EMPTY_CACHE_MINUTES)
            if datetime.now(timezone.utc) - dt > ttl:
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
    entry["articleFingerprint"] = _article_fingerprint(articles)
    entry["lookbackDays"] = NEWS_LOOKBACK_DAYS
    _llm_cache[key] = entry
    _save_llm_cache()


# Load cache at import time
_load_llm_cache()


async def summarize_with_llm(ticker: str, company: str, articles: list[TickerNewsArticle]) -> dict:
    """OpenRouter / OpenAI-compatible summary. Does not invent Neutral/heuristic copy."""
    from .llm_client import _call_openai, _llm_config, _llm_quota_available, _record_quota_error

    missing = _llm_unavailable_summary(ticker, company, articles, "LLM not configured")
    if not articles:
        return _llm_unavailable_summary(ticker, company, articles, f"No verified articles in the last {NEWS_LOOKBACK_DAYS} days")
    provider, api_key, api_url, model, _oauth = _llm_config()
    if not provider or not api_key:
        logger.warning("LLM not configured for ticker news (%s) — no heuristic summary", ticker)
        return missing
    if not _llm_quota_available():
        logger.warning("LLM quota cooling down — no heuristic summary for %s", ticker)
        return _llm_unavailable_summary(ticker, company, articles, _quota_cooldown_message())

    compact_articles = [
        {
            "title": a.title[:220],
            "source": a.source[:80],
            "published": a.published_at[:32],
            "snippet": a.summary[:240],
        }
        for a in articles[:NEWS_LLM_ARTICLE_LIMIT]
    ]
    article_text = json.dumps(compact_articles, ensure_ascii=False, separators=(",", ":"))
    prompt = f"""You are a financial news analyst. Analyze the following news articles for the company "{company}" (ticker: {ticker}) on the Indian stock market.

For each category, provide at most one short sentence based ONLY on the supplied evidence. If absent, write "No recent news found."

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
        "regulatory_filings", "sentiment_overall", "risk_flags", "summary_headline",
    ]
    try:
        async with _LLM_SEMAPHORE:
            if provider == "gemini":
                from .llm_client import _call_gemini

                text = await asyncio.to_thread(
                    _call_gemini,
                    prompt,
                    api_key,
                    model,
                    "You are an elite institutional financial terminal. Return valid JSON only.",
                )
            else:
                text = await asyncio.to_thread(
                    _call_openai,
                    prompt,
                    api_key,
                    api_url,
                    model,
                    max_tokens=1400,
                )
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        result = _parse_json_response(text, expected_keys)
        for key in expected_keys:
            result.setdefault(key, "No recent news found.")
        result["llmUsed"] = True
        logger.info("LLM ticker-news summary complete for %s via %s/%s", ticker, provider, model)
        return result
    except Exception as exc:
        err = str(exc)
        if "429" in err:
            _record_quota_error(err)
            gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
            gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
            if gemini_key:
                try:
                    from .llm_client import _call_gemini

                    text = await asyncio.to_thread(
                        _call_gemini,
                        prompt,
                        gemini_key,
                        gemini_model,
                        "You are an elite institutional financial terminal. Return valid JSON only.",
                    )
                    if "```json" in text:
                        text = text.split("```json")[1].split("```")[0].strip()
                    elif "```" in text:
                        text = text.split("```")[1].split("```")[0].strip()
                    result = _parse_json_response(text, expected_keys)
                    for key in expected_keys:
                        result.setdefault(key, "No recent news found.")
                    result["llmUsed"] = True
                    logger.info(
                        "LLM ticker-news summary complete for %s via gemini/%s (OpenRouter 429 fallback)",
                        ticker,
                        gemini_model,
                    )
                    return result
                except Exception as gemini_exc:
                    logger.error("Gemini fallback failed for %s: %s", ticker, gemini_exc)
                    err = f"{err}; gemini fallback: {gemini_exc}"
        logger.error("LLM ticker-news failed for %s: %s", ticker, exc)
        return _llm_unavailable_summary(ticker, company, articles, err)


async def summarize_with_gemini(ticker: str, company: str, articles: list[TickerNewsArticle]) -> dict:
    """Compat alias — OpenRouter/OpenAI path, not Gemini-only."""
    return await summarize_with_llm(ticker, company, articles)


def _quota_cooldown_message() -> str:
    from .llm_client import llm_quota_resume_unix

    until = llm_quota_resume_unix()
    try:
        from zoneinfo import ZoneInfo

        stamp = datetime.fromtimestamp(until, tz=ZoneInfo("Asia/Kolkata")).strftime("%H:%M IST")
    except Exception:
        stamp = datetime.fromtimestamp(until, tz=timezone.utc).strftime("%H:%M UTC")
    return f"OpenRouter free-model daily quota exhausted until {stamp}."


def _short_llm_error(error: str) -> str:
    text = str(error or "")
    lowered = text.lower()
    if "quota cooling down" in lowered or "quota exhausted" in lowered:
        return text[:280]
    if "free-models-per-day" in text:
        return _quota_cooldown_message()
    return text[:280]


def _llm_unavailable_summary(ticker: str, company: str, articles: list[TickerNewsArticle], error: str) -> dict:
    """Honest empty summary. Never invent Neutral/keyword buckets."""
    headline = (
        f"No verified {ticker} news found in the last {NEWS_LOOKBACK_DAYS} days."
        if not articles and "No verified articles" in error
        else f"LLM summary unavailable for {company} ({len(articles)} articles scraped)."
    )
    return {
        "insider_activity": "—",
        "institutional_activity": "—",
        "order_book_block_deals": "—",
        "future_expansion_capex": "—",
        "auditor_changes": "—",
        "dividend_news": "—",
        "new_orders_contracts": "—",
        "earnings_results": "—",
        "management_changes": "—",
        "regulatory_filings": "—",
        "sentiment_overall": "—",
        "risk_flags": "—",
        "summary_headline": headline,
        "llmUsed": False,
        "llmError": _short_llm_error(error),
    }

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
    articles = await scrape_all_sources(ticker, company)
    if len(articles) > max_articles:
        articles = articles[:max_articles]

    # Step 2: LLM Summarize (with snapshot cache to preserve quota)
    cached = get_cached_summary(ticker, articles, max_articles, force_refresh=force_refresh)
    if cached is not None:
        logger.info("Using cached LLM summary for %s (max_articles=%d)", ticker, max_articles)
        llm_result = cached
    else:
        llm_result = await summarize_with_llm(ticker, company, articles)
        # Cache successful summaries and honest no-evidence results. Quota/error
        # shells remain retryable and are governed by the shared model cooldowns.
        if llm_result.get("llmUsed") is True or not articles:
            set_cached_summary(
                ticker,
                articles,
                max_articles,
                {
                    **llm_result,
                    "company_name": company,
                    "articles_scraped": len(articles),
                    "articles_after_dedup": len(articles),
                    "lookback_days": NEWS_LOOKBACK_DAYS,
                    "evidence_status": "VERIFIED_RECENT" if articles else "NO_RECENT_EVIDENCE",
                    "sources_checked": [
                        "NSE Announcements", "BSE Announcements", "Moneycontrol",
                        "Economic Times", "Google News publishers", "Yahoo Finance", "Zerodha Pulse",
                        "TinyFish Search",
                    ],
                },
            )

    # Step 3: Build report
    llm_fields = {k: v for k, v in llm_result.items() if k in AITickerNewsReport.__dataclass_fields__ and k not in ("generated_at", "ticker")}
    report = AITickerNewsReport(
        ticker=ticker,
        company_name=company,
        articles_scraped=len(articles),
        articles_after_dedup=len(articles),
        generated_at=str(llm_result.get("generated_at") or datetime.now(timezone.utc).isoformat()),
        lookback_days=NEWS_LOOKBACK_DAYS,
        evidence_status="VERIFIED_RECENT" if articles else "NO_RECENT_EVIDENCE",
        sources_checked=[
            "NSE Announcements", "BSE Announcements", "Moneycontrol",
            "Economic Times", "Google News publishers", "Yahoo Finance", "Zerodha Pulse",
            "TinyFish Search",
        ],
        **llm_fields,
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
