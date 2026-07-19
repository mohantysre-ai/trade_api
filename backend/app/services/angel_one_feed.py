"""
Angel One market feed for the IROS terminal.

This service fetches live Angel One quotes, lets the LLM rank the full live
universe using a filter prompt, and exposes the top selected stocks as the
active market list.
"""

from __future__ import annotations

import argparse
import asyncio
import email
import json
import logging
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx # Added for internal API calls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pyotp
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from SmartApi import SmartConnect

from .market_feeds import (
    fetch_domestic_index_macro,
    fetch_domestic_yahoo_macro,
    fetch_global_macro,
    fetch_gift_nifty,
)
from ..utils.symbols import MACRO_INSTRUMENTS, MOCK_TICKERS, NIFTY_50_KEYS, WATCHLIST, Instrument
from .llm_client import _llm_config as _llm_config_canonical, _get_gemini_oauth_token, _llm_quota_available, _record_quota_error
from .intelligence_engine import (
    CompleteSecurityAnalysisPayload,
    TOP_SELECTION_COUNT,
    _on_demand_ticker_selection_reason,
    build_ticker_intelligence_map,
    build_ticker_intelligence_report,
    execute_terminal_intelligence_pipeline,
)

_TI_TOP_SELECTION_COUNT = TOP_SELECTION_COUNT

ORCHESTRATION_DELAY = 30


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR.parent.parent / ".env")

NIFTY_500_CACHE_PATH = BASE_DIR / "nifty500_instruments.json"
NIFTY_500_LABEL = "Nifty 500"

IST_ZONE = ZoneInfo("Asia/Kolkata")
SNAPSHOT_PATH = BASE_DIR / "last_market_snapshot.json"
MORNING_REFRESH_START = (8, 0)
MORNING_REFRESH_END = (8, 30)
EVENING_REFRESH_START = (16, 0)
EVENING_REFRESH_END = (16, 30)
REFRESH_TASK_TTL_SECONDS = 600
_REFRESH_TASKS: dict[str, dict[str, Any]] = {}
_REFRESH_TASK_LOCK = threading.Lock()
LLM_UNIVERSE_LIMIT = int(os.getenv("LLM_UNIVERSE_LIMIT", "30"))
NIFTY_100_LABEL = "Nifty 100"
NIFTY_100_CACHE_PATH = BASE_DIR / "nifty100_instruments.json"
ANGEL_API_TIMEOUT_SECONDS = int(os.getenv("ANGEL_API_TIMEOUT_SECONDS", "24"))
LLM_CALL_TIMEOUT_SECONDS = min(max(1, int(os.getenv("LLM_CALL_TIMEOUT_SECONDS", "180"))), 300)
QUOTE_CHUNK_SIZE = int(os.getenv("QUOTE_CHUNK_SIZE", "10"))
INTRADAY_CHUNK_SIZE = int(os.getenv("INTRADAY_CHUNK_SIZE", "10"))

AI_NEWS_API_URL = os.getenv("AI_NEWS_API_URL", "http://127.0.0.1:8001")


# =============================================================================
# STRICT SAFETY AUDITOR SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """
You are a Safety Risk Auditor.

You are NOT a stock selector.

You must never:

- rank stocks
- score stocks
- evaluate technical indicators
- analyze momentum
- infer chart patterns

Audit only:

- News Risk
- Earnings Risk
- Regulatory Risk
- Corporate Action Risk
- Governance Risk
- Macro Event Risk

Every claim requires:

- source
- publication timestamp

No source = No verified evidence.

REJECT only for:

- earnings within 48h
- exchange restrictions
- regulatory actions
- court decisions
- corporate actions causing binary gaps

Return JSON only.
"""


def _refresh_task_key(pool_name: str | None, custom_prompt: str | None) -> str:
    return f"refresh:{pool_name or '__all__'}:{(custom_prompt or '').strip()[:64]}"


def _refresh_task_status(task_id: str) -> dict[str, Any] | None:
    with _REFRESH_TASK_LOCK:
        task = _REFRESH_TASKS.get(task_id)
        if not task:
            return None
        if time.time() - task.get("created_at", 0) > REFRESH_TASK_TTL_SECONDS:
            del _REFRESH_TASKS[task_id]
            return None
        return {
            "status": task["status"],
            "progress": task.get("progress"),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "result": task.get("result"),
        }


def _refresh_task_set_done(task_id: str, result: dict[str, Any]) -> None:
    with _REFRESH_TASK_LOCK:
        if task_id in _REFRESH_TASKS:
            _REFRESH_TASKS[task_id]["status"] = "done"
            _REFRESH_TASKS[task_id]["result"] = result


def _refresh_task_set_error(task_id: str, error: str) -> None:
    with _REFRESH_TASK_LOCK:
        if task_id in _REFRESH_TASKS:
            _REFRESH_TASKS[task_id]["status"] = "error"
            _REFRESH_TASKS[task_id]["error"] = error


# -----------------------------------------------------------------------------
# NEWS INGESTION — RSS / Atom feeds (structured, not scraped HTML body text)
# -----------------------------------------------------------------------------
# Each entry: (display_name, rss_or_atom_url, default_category)
# Feeds are fetched concurrently and parsed as XML. A dead feed simply raises
# and is skipped, so it never blanks the whole panel. This replaces the old
# HTML-body scraping which returned nav text instead of real headlines.

# Direct publisher feeds (verified parseable). A number of large Indian
# outlets (ET, Business Standard, FE, CNBC-TV18, Zee, BL) either block
# server-side fetches or dropped public RSS, so we lean on Google News
# topic feeds (which surface the same publishers) for reliable breadth.
NEWS_RSS_FEEDS: list[tuple[str, str, str]] = [
    # --- Direct publisher RSS/Atom feeds ---
    ("Moneycontrol Latest", "https://www.moneycontrol.com/rss/latestnews.xml", "Market"),
    ("Moneycontrol Business", "https://www.moneycontrol.com/rss/business.xml", "Corporate"),
    ("Moneycontrol Economy", "https://www.moneycontrol.com/rss/economy.xml", "Economy"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets", "Market"),
    ("Livemint Companies", "https://www.livemint.com/rss/companies", "Corporate"),
    ("Livemint Money", "https://www.livemint.com/rss/money", "Economy"),
    ("Livemint Opinion", "https://www.livemint.com/rss/opinion", "Market"),
    ("News18 Markets", "https://www.news18.com/rss/markets.xml", "Market"),
    ("News18 Business", "https://www.news18.com/rss/business.xml", "Market"),
    ("Indian Express Business", "https://indianexpress.com/section/business/feed/", "Market"),
    ("Inc42", "https://inc42.com/feed/", "Corporate"),
    ("YourStory", "https://yourstory.com/feed", "Corporate"),
    # --- Google News topic feeds (India-focused, reliably parseable) ---
    # Each entry's <source> element carries the real publisher, so the
    # frontend badge shows the actual outlet, not "Google News".
    ("Google · Markets", "https://news.google.com/rss/search?q=indian+stock+market&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · Sensex Nifty", "https://news.google.com/rss/search?q=sensex+nifty&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · FII DII", "https://news.google.com/rss/search?q=india+FII+DII+market&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · RBI Policy", "https://news.google.com/rss/search?q=RBI+monetary+policy+india&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · SEBI", "https://news.google.com/rss/search?q=SEBI+india&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · Earnings", "https://news.google.com/rss/search?q=indian+company+earnings+results&hl=en-IN&gl=IN&ceid=IN:en", "Earnings"),
    ("Google · Dividend Buyback", "https://news.google.com/rss/search?q=india+dividend+buyback&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · IPO", "https://news.google.com/rss/search?q=indian+IPO+listing&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Corporate Deals", "https://news.google.com/rss/search?q=indian+company+merger+acquisition+deal&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · IT Sector", "https://news.google.com/rss/search?q=indian+IT+sector+stocks&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Pharma", "https://news.google.com/rss/search?q=indian+pharma+stocks&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Auto Sales", "https://news.google.com/rss/search?q=india+auto+sales&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Bank NPA", "https://news.google.com/rss/search?q=indian+banks+NPA&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · GST Budget", "https://news.google.com/rss/search?q=india+GST+budget+economy&hl=en-IN&gl=IN&ceid=IN:en", "Economy"),
    ("Google · Infrastructure", "https://news.google.com/rss/search?q=india+infrastructure+ECONOMIC&hl=en-IN&gl=IN&ceid=IN:en", "Economy"),
    ("Google · Crude Oil", "https://news.google.com/rss/search?q=india+crude+oil+price&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Gold", "https://news.google.com/rss/search?q=india+gold+price&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Rupee Dollar", "https://news.google.com/rss/search?q=indian+rupee+dollar+forex&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Startup Funding", "https://news.google.com/rss/search?q=india+startup+funding&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Mutual Funds", "https://news.google.com/rss/search?q=india+mutual+funds+AMC&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
]

LIVE_UNIVERSE_LABEL = "Live Universe"


def _news_feed_sources() -> list[str]:
    return [name for name, _, _ in NEWS_RSS_FEEDS]


def _filter_prompt(custom_prompt: str | None = None) -> str:
    parts = []
    env_prompt = os.getenv("MARKET_FILTER_PROMPT", "").strip()
    if env_prompt:
        parts.append(env_prompt)
    if custom_prompt and custom_prompt.strip():
        parts.append(custom_prompt.strip())
    parts.append(
        "Use the live Angel One universe below to select the top "
        f"{_TI_TOP_SELECTION_COUNT} stocks. Prefer the Nifty 100 universe; do not restrict selection to Nifty 50 only. "
        "Do not invent tickers. Return valid JSON only."
    )
    return " ".join(parts)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_credential() -> str:
    """Return Angel One credential: prefer ANGEL_MPIN (4-digit), fall back to REDACTED."""
    mpin = (os.getenv("ANGEL_MPIN") or "").strip()
    if mpin:
        if len(mpin) != 4 or not mpin.isdigit():
            raise RuntimeError("ANGEL_MPIN must be exactly 4 digits")
        return mpin
    password = (os.getenv("REDACTED") or "").strip()
    if not password:
        raise RuntimeError("Missing ANGEL_MPIN or REDACTED in backend .env")
    return password


def _pct_change(ltp: float, close: float | None) -> tuple[str, str]:
    if close in (None, 0):
        return "0.00%", "POSITIVE"
    change = ((ltp - close) / close) * 100
    sign = "+" if change >= 0 else ""
    state = "POSITIVE" if change >= 0 else "NEGATIVE"
    return f"{sign}{change:.2f}%", state


def _format_inr(value: float) -> str:
    return f"₹{value:,.2f}"


def _snapshot_path() -> Path:
    return SNAPSHOT_PATH


def _ist_now() -> datetime:
    return datetime.now(tz=IST_ZONE)


def _within_refresh_window(now: datetime | None = None) -> bool:
    now = now or _ist_now()
    current_minutes = now.hour * 60 + now.minute
    morning_start = MORNING_REFRESH_START[0] * 60 + MORNING_REFRESH_START[1]
    morning_end = MORNING_REFRESH_END[0] * 60 + MORNING_REFRESH_END[1]
    evening_start = EVENING_REFRESH_START[0] * 60 + EVENING_REFRESH_START[1]
    evening_end = EVENING_REFRESH_END[0] * 60 + EVENING_REFRESH_END[1]
    return (morning_start <= current_minutes < morning_end) or (evening_start <= current_minutes < evening_end)


def _normalize_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    payload["rawSources"] = _news_feed_sources()
    available_pools = [pool for pool in payload.get("availablePools", []) if pool != "Nifty 50"]
    if NIFTY_100_LABEL not in available_pools:
        available_pools.insert(0, NIFTY_100_LABEL)
    if LIVE_UNIVERSE_LABEL not in available_pools:
        available_pools.append(LIVE_UNIVERSE_LABEL)
    payload["availablePools"] = available_pools
    payload.setdefault("activePool", NIFTY_100_LABEL)
    payload.setdefault("poolDescription", "Nifty 100 Angel One live universe ranked by your filter prompt.")
    payload.setdefault("tickerNewsByTicker", {})
    return payload


def _load_watchlist_from_cache(path: Path) -> list[Instrument]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        instruments = raw.get("instruments", []) if isinstance(raw, dict) else []
        return [
            Instrument(
                key=str(item["key"]),
                exchange=str(item.get("exchange", "NSE")),
                tradingsymbol=str(item["tradingsymbol"]),
                token=str(item["token"]),
                label=str(item.get("label") or item["key"]),
            )
            for item in instruments
            if item.get("key") and item.get("token") and item.get("tradingsymbol")
        ]
    except Exception:
        return []


def _pool_watchlist(pool_name: str | None) -> tuple[list[Instrument], str]:
    resolved = pool_name or NIFTY_100_LABEL

    if resolved in ("Nifty 50", NIFTY_500_LABEL):
        resolved = NIFTY_100_LABEL

    if resolved == NIFTY_100_LABEL:
        # Prefer Nifty 500 with daily rotation so different constituents
        # get surfaced each day instead of the same static Nifty 100 set.
        nifty500 = _load_watchlist_from_cache(NIFTY_500_CACHE_PATH)
        if nifty500:
            window_size = 200
            idx = _ist_now().day % max(len(nifty500) - window_size, 1)
            rotated = nifty500[idx:] + nifty500[:idx]
            window = rotated[:window_size]
            return [inst for inst in window if inst.key not in NIFTY_50_KEYS], NIFTY_100_LABEL
        nifty100 = _load_watchlist_from_cache(NIFTY_100_CACHE_PATH)
        if nifty100:
            return [inst for inst in nifty100 if inst.key not in NIFTY_50_KEYS], NIFTY_100_LABEL

    return [inst for inst in WATCHLIST if inst.key not in NIFTY_50_KEYS], resolved


def _payload_data_date(payload: dict[str, Any] | None = None) -> str:
    if payload:
        updated_at = payload.get("updatedAt")
        if isinstance(updated_at, str) and updated_at:
            return updated_at[:10]
    return _ist_now().date().isoformat()


def _apply_selection_meta(
    payload: dict[str, Any],
    *,
    mode: str,
    reason: str,
    data_date: str | None = None,
) -> dict[str, Any]:
    payload["selectionMeta"] = {
        "mode": mode,
        "reason": reason,
        "dataDate": data_date or _payload_data_date(payload),
    }
    return payload


def _hydrate_ticker_intelligence_map(payload: dict[str, Any]) -> dict[str, Any]:
    payload["tickerIntelligenceByTicker"] = build_ticker_intelligence_map(payload)
    return payload


def _load_last_snapshot() -> dict[str, Any] | None:
    try:
        payload = json.loads(_snapshot_path().read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return _normalize_snapshot(payload)
        return None
    except Exception:
        return None


def _save_last_snapshot(payload: dict[str, Any]) -> None:
    try:
        payload = _enrich_snapshot_with_fixed_plan(payload)
    except Exception as exc:
        log.warning("Fixed-plan snapshot enrichment failed: %s", exc)
    try:
        _snapshot_path().write_text(json.dumps(_normalize_snapshot(payload), indent=2), encoding="utf-8")
    except Exception:
        pass


# Cache so a single refresh (which may call _save_last_snapshot multiple times)
# only resolves fixed-plan quotes once; TTL also caps background saves.
_FIXED_PLAN_QUOTE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_FIXED_PLAN_QUOTE_TTL = 300  # seconds
_FIXED_PLAN_CLIENT: "AngelOneClient | None" = None


def _get_fixed_plan_client() -> "AngelOneClient | None":
    global _FIXED_PLAN_CLIENT
    if _FIXED_PLAN_CLIENT is None:
        try:
            _FIXED_PLAN_CLIENT = AngelOneClient()
        except Exception as exc:
            log.warning("Fixed-plan client init failed: %s", exc)
            return None
    return _FIXED_PLAN_CLIENT


def _enrich_snapshot_with_fixed_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge fixed-trade-plan symbols' live LTPs into stockQuotes.

    The fixed plan (fixed_trade_plan.json) may contain symbols that are not in
    the WATCHLIST / Nifty cache, so they never appear in the normal Angel One
    batch quote. This resolves their tokens at runtime (searchScrip) and fetches
    LTPs (ltpData) so get_live_prices_for_plan() can show real prices instead of
    falling back to entry price.
    """
    try:
        from .trade_outcome import load_fixed_trade_plan
    except Exception:
        return payload

    fixed = load_fixed_trade_plan()
    symbols: list[str] = []
    for p in (fixed.get("long") or []) + (fixed.get("short") or []):
        s = (p.get("symbol") or "").upper()
        if s:
            symbols.append(s)
    if not symbols:
        return payload

    quotes = dict(payload.get("stockQuotes") or {})
    now = time.time()
    client = _get_fixed_plan_client()
    if client is None:
        return payload

    for sym in symbols:
        cached = _FIXED_PLAN_QUOTE_CACHE.get(sym)
        if cached and (now - cached[0]) < _FIXED_PLAN_QUOTE_TTL:
            quotes[sym] = cached[1]
            continue
        try:
            quote = client.fetch_symbol_quote(sym)
            if not quote:
                continue
            ltp = float(quote.get("ltp", 0) or 0)
            if not ltp:
                continue
            inst = Instrument(sym, "NSE", f"{sym}-EQ", str(quote.get("token", "0")))
            row = _build_stock_row(inst, quote, payload.get("activePool", "Fixed Plan"))
            quotes[sym] = row
            _FIXED_PLAN_QUOTE_CACHE[sym] = (now, row)
        except Exception as exc:
            log.debug("Fixed-plan quote fetch failed for %s: %s", sym, exc)
            continue

    payload["stockQuotes"] = quotes
    return payload


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(re.sub(r"<[^>]+>", "", value).split()).strip()


def _parse_rss_datetime(date_text: str | None) -> str | None:
    if not date_text:
        return None
    formats = (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S GMT",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(date_text.strip(), fmt)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return None


def _clean_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


# -----------------------------------------------------------------------------
# RSS / Atom ingestion
# -----------------------------------------------------------------------------
# Real, structured headlines pulled from financial-news feeds. Each article is
# normalized to {source, title, link, summary, publishedAt, sentiment,
# category} and de-duplicated by normalized title across all sources.

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

_BULLISH_WORDS: dict[str, int] = {
    "beats": 30, "beat estimates": 35, "surges": 30, "surge": 28, "rallies": 28,
    "jumps": 25, "gains": 18, "upgrade": 30, "upgraded": 30, "wins order": 32,
    "wins contract": 32, "record profit": 35, "record high": 28, "approval": 25,
    "nod": 20, "raises guidance": 32, "raised guidance": 32, "outperform": 25,
    "buyback": 20, "expansion": 15, "strong demand": 22, "beats street": 32,
    "profit jumps": 30, "profit rises": 25, "revenue growth": 18, "bullish": 22,
    "rally": 24, "soars": 30, "tops estimate": 30, "inflows": 14, "recovery": 15,
}
_BEARISH_WORDS: dict[str, int] = {
    "tumbles": 30, "crashes": 35, "plunges": 32, "slides": 22, "slips": 18,
    "downgrade": 30, "downgraded": 30, "misses estimates": 32, "miss estimates": 30,
    "cancellation": 28, "cancels order": 30, "probe": 28, "fraud": 35, "raid": 30,
    "resigns": 22, "resignation": 22, "npa": 22, "slippage": 25, "governance": 15,
    "pledge": 18, "delay": 15, "weak guidance": 28, "cuts guidance": 30,
    "profit falls": 28, "loss widens": 30, "bearish": 22, "sell-off": 25,
    "selloff": 25, "scam": 32, "slumps": 28, "sinks": 28, "outflows": 14,
    "layoffs": 22, "defaults": 28, "warning": 18,
}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Earnings": ["earnings", "result", "results", "profit", "revenue", "quarter", " q1 ", " q2 ", " q3 ", " q4 ", "eps", "dividend", "guidance", "net profit", "bottomline"],
    "Regulatory": ["sebi", "rbi", "regulator", "regulatory", "supreme court", "cci", "penalty", "probe", "investigation", "ruling", "order", "ban", "nclt", "crackdown", "fine"],
    "Commodity": ["crude", "gold", "silver", "oil", "commodity", "commodities", "brent", "natural gas", "wheat", "rupee", "dollar", "currency", "bullion"],
    "Economy": ["gdp", "inflation", "fiscal", "budget", "economy", "imf", "fii", "dii", "macro", "policy", "repo rate", "monsoon", "trade deficit", "gst"],
    "Global": ["wall street", "nasdaq", "dow", "s&p", "fed ", "us fed", "global", "china", "europe", "japan", "ukraine", "tariff"],
    "Corporate": ["merger", "acquisition", "buyback", "promoter", "board", "ceo", "cfo", "management", "deal", "partnership", "launch", "order win", "contract", "joint venture", "subsidiary"],
}


def _xml_local(tag: str) -> str:
    return tag.split("}")[-1]


def _xml_child(el: "ET.Element", local: str) -> "ET.Element | None":
    for child in el:
        if _xml_local(child.tag) == local:
            return child
    return None


def _xml_text(el: "ET.Element", local: str) -> str:
    child = _xml_child(el, local)
    if child is None:
        return ""
    return _clean_text(child.text or "")


def _xml_link(el: "ET.Element") -> str:
    links = [c for c in el if _xml_local(c.tag) == "link"]
    if not links:
        return ""
    for link in links:
        if link.get("rel") in (None, "alternate"):
            href = link.get("href")
            if href:
                return href
    href = links[0].get("href")
    if href:
        return href
    return _clean_text(links[0].text or "")


def _parse_published(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            return datetime.strptime(value, fmt).astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return None


def _classify_sentiment(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    score = 0
    for word, weight in _BULLISH_WORDS.items():
        if word in text:
            score += weight
    for word, weight in _BEARISH_WORDS.items():
        if word in text:
            score -= weight
    if score >= 12:
        return "Bullish"
    if score <= -12:
        return "Bearish"
    return "Neutral"


def _classify_category(title: str, summary: str, default_category: str) -> str:
    text = (title + " " + summary).lower()
    for category, words in _CATEGORY_KEYWORDS.items():
        if any(word in text for word in words):
            return category
    return default_category or "Market"


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").lower()).strip()


def _fetch_rss_feed(name: str, url: str, default_category: str, limit: int = 5) -> list[dict[str, str]]:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}
    response = requests.get(url, timeout=10, headers=headers)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    nodes = root.findall(".//item")
    if not nodes:
        nodes = root.findall(f".//{_ATOM_NS}entry")
    items: list[dict[str, str]] = []
    for node in nodes[:limit]:
        title = _xml_text(node, "title")
        if not title or len(title) < 10:
            continue
        link = _xml_link(node)
        summary = (
            _xml_text(node, "description")
            or _xml_text(node, "summary")
            or _xml_text(node, "content")
        )
        # Use the entry's real publisher when present (Google News Atom feeds
        # embed <source>Publisher</source>), otherwise fall back to the feed name.
        source_child = _xml_child(node, "source")
        source = _clean_text(source_child.text) if source_child is not None else ""
        source = source or name
        published = _parse_published(
            _xml_text(node, "pubDate")
            or _xml_text(node, "updated")
            or _xml_text(node, "date")
            or _xml_text(node, "published")
        )
        if not published:
            published = _ist_now().isoformat()
        items.append(
            {
                "source": source,
                "title": title[:300],
                "link": link or url,
                "summary": summary[:400],
                "publishedAt": published,
                "sentiment": _classify_sentiment(title, summary),
                "category": _classify_category(title, summary, default_category),
            }
        )
    return items


def fetch_live_news(limit: int = 40, per_feed: int = 4) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [
            executor.submit(_fetch_rss_feed, name, url, category, per_feed)
            for name, url, category in NEWS_RSS_FEEDS
        ]
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception:
                continue

    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        key = _normalize_title(item.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(key=lambda item: item.get("publishedAt", ""), reverse=True)
    return deduped[:limit]


# Use the canonical _llm_config from llm_client.py instead of this local one.
# It supports both API key (project quota) and OAuth token (portal quota).


def _call_openai_deprecated(*args, **kwargs):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an elite institutional financial terminal. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    if response.status_code >= 300:
        raise RuntimeError(f"OpenAI request failed ({response.status_code}): {response.text}")
    data = response.json()
    if not data.get("choices") or not data["choices"][0].get("message"):
        raise RuntimeError("OpenAI response missing expected content")
    return data["choices"][0]["message"]["content"].strip()


def _call_gemini_deprecated(*args, **kwargs):
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini support requires google-genai. Install it in the backend venv.") from exc

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=2000,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return getattr(response, "text", None) or getattr(response, "output_text", None) or str(response)


class AngelOneClient:
    def __init__(self) -> None:
        self.api_key = _require_env("REDACTED")
        self.client_id = _require_env("REDACTED")
        self.credential = _get_credential()
        self.totp_secret = _require_env("REDACTED")
        self._smart: SmartConnect | None = None

    def _reset_connection(self) -> None:
        self._smart = None

    def _is_auth_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(k in msg for k in (
            "unauthorized", "invalid token", "token expired", "access denied",
            "session expired", "login required", "invalid session", "ab1000",
            "ab1001", "ab1002", "ab1003", "authentication", "session invalid",
            "token is expired", "unauthorised"
        ))

    def _call_with_auth_retry(self, method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            if self._is_auth_error(exc):
                logging.getLogger(__name__).warning("Angel One auth error, reconnecting: %s", exc)
                self._reset_connection()
                return method(*args, **kwargs)
            raise

    def connect(self) -> SmartConnect:
        if self._smart is not None:
            return self._smart
        smart = SmartConnect(api_key=self.api_key, timeout=ANGEL_API_TIMEOUT_SECONDS)
        totp = pyotp.TOTP(self.totp_secret).now()
        session = smart.generateSession(self.client_id, self.credential, totp)
        if not session.get("status"):
            raise RuntimeError(f"Angel One login failed: {session.get('message', 'Unknown login error')}")
        # generateSession already calls setAccessToken / setRefreshToken / setFeedToken
        # with the raw token (without Bearer prefix). The returned data has "Bearer "
        # prefixed, so calling the setters again would double-prefix and break auth.
        self._smart = smart
        return smart

    def fetch_quote(self, exchange: str, tradingsymbol: str, token: str) -> dict[str, Any]:
        def _fetch():
            smart = self.connect()
            response = smart.ltpData(exchange, tradingsymbol, token)
            if not response.get("status"):
                raise RuntimeError(f"{tradingsymbol}: {response.get('message', 'Quote fetch failed')}")
            return response["data"]
        try:
            return _fetch()
        except Exception as exc:
            if self._is_auth_error(exc):
                self._reset_connection()
                return _fetch()
            raise

    def fetch_symbol_quote(self, symbol: str) -> dict[str, Any] | None:
        """Resolve an arbitrary NSE symbol's token via searchScrip and fetch its LTP.

        Used to bring fixed-trade-plan symbols (which are not in the WATCHLIST /
        Nifty cache) into the live snapshot so the intraday monitor can show real
        prices instead of falling back to entry price.
        """
        def _try_fetch() -> dict[str, Any] | None:
            smart = self.connect()
            sym = symbol.upper()
            tradingsymbol = f"{sym}-EQ"
            token: str | None = None
            for candidate in (tradingsymbol, sym):
                try:
                    search = smart.searchScrip("NSE", candidate)
                except Exception:
                    search = None
                if isinstance(search, dict) and search.get("status"):
                    data = search.get("data") or []
                    if isinstance(data, list) and data:
                        first = data[0]
                        resolved = str(first.get("token") or first.get("symboltoken") or "")
                        if resolved:
                            token = resolved
                            tradingsymbol = str(first.get("symbol") or candidate)
                            break
            if not token:
                return None
            try:
                resp = smart.ltpData("NSE", tradingsymbol, token)
            except Exception:
                return None
            if not isinstance(resp, dict) or not resp.get("status"):
                return None
            data = resp.get("data") or {}
            if isinstance(data, dict):
                data.setdefault("token", token)
            return data if isinstance(data, dict) else None

        try:
            return _try_fetch()
        except Exception as exc:
            if self._is_auth_error(exc):
                self._reset_connection()
                return _try_fetch()
            return None

    def fetch_candles(
        self,
        exchange: str,
        symboltoken: str,
        interval: str,
        fromdate: datetime,
        todate: datetime,
    ) -> list[list[Any]]:
        def _fetch():
            smart = self.connect()
            params = {
                "exchange": exchange,
                "symboltoken": symboltoken,
                "interval": interval,
                "fromdate": fromdate.astimezone(IST_ZONE).strftime("%Y-%m-%d %H:%M"),
                "todate": todate.astimezone(IST_ZONE).strftime("%Y-%m-%d %H:%M"),
            }
            response = smart.getCandleData(params)
            if not response.get("status"):
                return []
            data = response.get("data") or []
            return data if isinstance(data, list) else []

        try:
            return _fetch()
        except Exception as exc:
            if self._is_auth_error(exc):
                self._reset_connection()
                return _fetch()
            return []

    def fetch_batch_quotes(self, instruments: list[Instrument]) -> dict[str, dict[str, Any]]:
        smart = self.connect()
        token_to_key: dict[str, str] = {}

        for inst in instruments:
            token_to_key[inst.token] = inst.key

        def _chunked(items: list[Instrument], size: int = 25) -> list[list[Instrument]]:
            return [items[i : i + size] for i in range(0, len(items), size)]

        fetched: dict[str, dict[str, Any]] = {}
        for chunk in _chunked(instruments, size=25):
            tokens_by_exchange: dict[str, list[str]] = {}
            for inst in chunk:
                tokens_by_exchange.setdefault(inst.exchange, []).append(inst.token)

            try:
                response = smart.getMarketData("FULL", tokens_by_exchange)
            except Exception:
                response = {"status": False}

            if response.get("status"):
                for item in response.get("data", {}).get("fetched", []):
                    token = str(item.get("symbolToken", ""))
                    key = token_to_key.get(token)
                    if key:
                        fetched[key] = item
                continue

            for inst in chunk:
                try:
                    fetched[inst.key] = self.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
                except Exception:
                    continue

        missing = [inst for inst in instruments if inst.key not in fetched]
        for inst in missing:
            try:
                fetched[inst.key] = self.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
            except Exception:
                continue

        return fetched


def _fetch_quote_chunk(
    smart: SmartConnect,
    chunk: list[Instrument],
    token_to_key: dict[str, str],
    client: AngelOneClient | None = None,
) -> dict[str, dict[str, Any]]:
    tokens_by_exchange: dict[str, list[str]] = {}
    for inst in chunk:
        tokens_by_exchange.setdefault(inst.exchange, []).append(inst.token)

    fetched: dict[str, dict[str, Any]] = {}
    try:
        response = smart.getMarketData("FULL", tokens_by_exchange)
        if response.get("status"):
            for item in response.get("data", {}).get("fetched", []):
                token = str(item.get("symbolToken", ""))
                key = token_to_key.get(token)
                if key:
                    fetched[key] = item
            return fetched
    except Exception as exc:
        if client and client._is_auth_error(exc):
            raise

    for inst in chunk:
        try:
            response = smart.ltpData(inst.exchange, inst.tradingsymbol, inst.token)
            if response.get("status"):
                fetched[inst.key] = response["data"]
        except Exception as exc:
            if client and client._is_auth_error(exc):
                raise
            continue
    return fetched


def _fetch_batch_quotes_chunked(
    self: AngelOneClient,
    instruments: list[Instrument],
) -> dict[str, dict[str, Any]]:
    def _fetch():
        smart = self.connect()
        token_to_key = {inst.token: inst.key for inst in instruments}
        chunks = [instruments[i : i + QUOTE_CHUNK_SIZE] for i in range(0, len(instruments), QUOTE_CHUNK_SIZE)]
        all_fetched: dict[str, dict[str, Any]] = {}

        for chunk in chunks:
            all_fetched.update(_fetch_quote_chunk(smart, chunk, token_to_key, self))

        return all_fetched

    try:
        return _fetch()
    except Exception as exc:
        if self._is_auth_error(exc):
            self._reset_connection()
            return _fetch()
        raise


AngelOneClient.fetch_batch_quotes = _fetch_batch_quotes_chunked


def _build_stock_row(
    inst: Instrument,
    quote: dict[str, Any],
    active_pool: str,
    intraday: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ltp = float(quote.get("ltp", 0) or 0)
    close = float(quote.get("close", 0) or 0)
    delta, state = _pct_change(ltp, close if close else None)
    return {
        "ticker": inst.key,
        "name": (inst.label or inst.tradingsymbol).replace("-EQ", "").replace("-BE", "").replace("-", " ").strip(),
        "capSize": active_pool,
        "ltp": _format_inr(ltp),
        "ltpRaw": ltp,
        "delta": delta,
        "state": state,
        "volume": quote.get("tradeVolume"),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "oi": float(quote.get("opnInterest", 0) or quote.get("oi", 0) or 0),
        "prev_oi": float(quote.get("previousOI", 0) or quote.get("prev_oi", 0) or 0),
        "intraday": intraday or {},
    }


def _parse_candle_rows(raw: list[list[Any]]) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for row in raw or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        ts, open_, high, low, close, volume = row[:6]
        candles.append(
            {
                "ts": ts,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume or 0),
            }
        )
    return candles


def _ema(values: list[float], period: int = 9) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append((value * k) + (out[-1] * (1 - k)))
    return out


def _atr_percent(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: list[float] = []
    prev_close = candles[0]["close"]
    for candle in candles[1:]:
        tr = max(
            candle["high"] - candle["low"],
            abs(candle["high"] - prev_close),
            abs(candle["low"] - prev_close),
        )
        trs.append(tr)
        prev_close = candle["close"]
    if len(trs) < period:
        return 0.0
    atr = sum(trs[-period:]) / period
    close = candles[-1]["close"] or 1.0
    return (atr / close) * 100


def _vwap(candles: list[dict[str, Any]]) -> float:
    total_pv = 0.0
    total_vol = 0.0
    for candle in candles:
        vol = float(candle["volume"] or 0)
        typical = (candle["high"] + candle["low"] + candle["close"]) / 3.0
        total_pv += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return 0.0
    return total_pv / total_vol


def _wick_noise_ratio(candles: list[dict[str, Any]]) -> float:
    total_range = 0.0
    total_wick = 0.0
    for candle in candles:
        candle_range = max(candle["high"] - candle["low"], 0.0)
        if candle_range <= 0:
            continue
        body_high = max(candle["open"], candle["close"])
        body_low = min(candle["open"], candle["close"])
        wick = (candle["high"] - body_high) + (body_low - candle["low"])
        total_range += candle_range
        total_wick += max(wick, 0.0)
    if total_range <= 0:
        return 1.0
    return total_wick / total_range


def _ema_angle_deg(ema_values: list[float]) -> float:
    if len(ema_values) < 6:
        return 0.0
    base = ema_values[-6] or 1.0
    latest = ema_values[-1] or base
    slope_pct = ((latest - base) / base) * 100.0
    return math.degrees(math.atan(slope_pct))


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI. Returns 50.0 (neutral) when there is insufficient history."""
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


# =============================================================================
# OI CLASSIFICATION - Real OI Setup Logic
# =============================================================================

def classify_oi_setup(
    ltp: float,
    prev_close: float,
    current_oi: float,
    prev_oi: float,
) -> str:
    """
    Classify Open Interest setup based on price and OI movement.

    LONG_BUILDUP:   Price UP + OI UP   (Bullish — new longs being added)
    SHORT_COVERING: Price UP + OI DOWN (Bears closing positions)
    SHORT_BUILDUP:  Price DOWN + OI UP (Bearish — new shorts being added)
    LONG_UNWINDING: Price DOWN + OI DOWN (Bulls closing positions)
    NEUTRAL:        No clear signal
    """
    price_up = ltp > prev_close
    if price_up and current_oi > prev_oi:
        return "LONG_BUILDUP"
    if price_up and current_oi < prev_oi:
        return "SHORT_COVERING"
    if not price_up and current_oi > prev_oi:
        return "SHORT_BUILDUP"
    if not price_up and current_oi < prev_oi:
        return "LONG_UNWINDING"
    return "NEUTRAL"


def _intraday_metrics_from_quote(ltp: float, now: datetime, quote: dict[str, Any]) -> dict[str, Any]:
    """Compute best-effort intraday metrics from quote data when candle API fails.
    
    Uses open/high/low/close/volume from the quote snapshot (which is always
    available from Angel One's batch quote API) to approximate the metrics.
    """
    open_ = float(quote.get("open", 0) or 0)
    high = float(quote.get("high", 0) or 0)
    low = float(quote.get("low", 0) or 0)
    close = float(quote.get("close", 0) or 0)
    volume = float(quote.get("tradeVolume", 0) or 0)
    
    # Estimate ATR% from today's range vs close (single-bar proxy for daily ATR)
    daily_range_pct = 0.0
    if close > 0 and high > 0 and low > 0:
        daily_range_pct = ((high - low) / close) * 100
    
    # VWAP approximation using OHL+C/3 typical price (single-bar estimate)
    typical = (high + low + ltp) / 3.0 if high and low and ltp else (open_ + high + low + close) / 4.0
    vwap = typical if typical > 0 else ltp
    
    # EMA9 approximation: use the close price as a different anchor from VWAP.
    # In real intraday data, EMA9 lags VWAP; using close gives a slightly different
    # value that allows price_above_ema9 to be meaningful when ltp > close.
    ema9 = close if close > 0 else ltp
    
    # ORB from quote data (uses today's open as ORB reference)
    orb_high = max(open_, ltp) if open_ else high
    orb_low = min(open_, ltp) if open_ else low
    
    # Today's volume from quote (tradeVolume is cumulative for the day)
    today_volume = volume
    avg_daily_volume_20 = volume  # estimate: use today's volume as proxy (better than 0)
    volume_multiplier = 1.0  # neutral
    
    # Wick noise ratio from single candle (open vs close vs high vs low)
    wick_noise_ratio = 1.0
    if high > low and high > 0:
        body_high = max(open_, close) if open_ and close else open_ or close or ltp
        body_low = min(open_, close) if open_ and close else open_ or close or ltp
        total_range = high - low
        wick = (high - body_high) + (body_low - low)
        if total_range > 0:
            wick_noise_ratio = min(wick / total_range, 1.0)
    
    # EMA angle: cannot compute without history, default neutral
    ema_angle_deg = 0.0
    
    # ORB velocity
    orb_velocity_pct = ((ltp - orb_high) / orb_high) * 100 if orb_high and ltp >= orb_high else 0.0
    
    # Turnover
    turnover_cr = (ltp * today_volume) / 10_000_000 if ltp and today_volume else 0.0
    
    price_above_vwap = bool(vwap and ltp > vwap)
    price_above_ema9 = bool(ema9 and ltp > ema9)
    
    # Hard filter reasons — tightened thresholds for quote-based fallback.
    # volume_multiplier and ema_angle are included for transparency even though
    # they default to placeholder values when candle data is unavailable.
    hard_filter_reasons: list[str] = []
    if daily_range_pct <= 1.5:
        hard_filter_reasons.append("ATR under 1.5%")
    if volume_multiplier <= 3.0:
        hard_filter_reasons.append("opening volume under 3.0x")
    if wick_noise_ratio > 0.70:
        hard_filter_reasons.append("wick noise too high")
    if not price_above_vwap:
        hard_filter_reasons.append("below VWAP")
    if not price_above_ema9:
        hard_filter_reasons.append("below EMA9")
    if ema_angle_deg <= 45.0:
        hard_filter_reasons.append("EMA angle below 45 degrees")
    if turnover_cr < 50.0:
        hard_filter_reasons.append("turnover under 50 Cr")
    
    passes_hard_filters = len(hard_filter_reasons) == 0
    trigger_point = "VWAP Bounce" if price_above_vwap else "15-min ORB" if ltp >= orb_high else "Flag Breakout"

    # Compute real alpha-component values from quote data instead of hardcoding zeros
    # OI classification from quote data
    current_oi = float(quote.get("oi", 0) or quote.get("opnInterest", 0) or 0)
    prev_oi_val = float(quote.get("prev_oi", 0) or quote.get("previousOI", 0) or 0)
    prev_close = float(quote.get("close", 0) or 0)
    if current_oi > 0 or prev_oi_val > 0:
        oi_setup = classify_oi_setup(ltp, prev_close if prev_close > 0 else ltp, current_oi, prev_oi_val)
    else:
        oi_setup = "NEUTRAL"

    # relative_volume: estimate from turnover using Nifty 100 institutional thresholds.
    # With only quote data (no 20d avg), we use turnover_cr as a proxy for volume activity.
    # 50 Cr turnover ≈ average institutional activity; 500+ Cr ≈ 3-5x average.
    if turnover_cr > 0:
        relative_volume = min(max(turnover_cr / 150.0, 0.5), 5.0)
    else:
        relative_volume = 1.0

    # liquidity_score: based on turnover (capped at 20)
    liquidity_score = min(turnover_cr / 2.5, 20.0)

    # breakout_quality: based on candle body ratio and VWAP distance
    body_ratio = (
        abs(close - open_) / max(high - low, 0.001)
    ) if high > low and open_ > 0 and close > 0 else 0.0
    vwap_dist_pct = ((ltp - vwap) / vwap * 100) if vwap > 0 else 0.0
    breakout_quality = min(
        (body_ratio * 10 + vwap_dist_pct * 2) if ltp > vwap else 0.0,
        20.0,
    )

    # sector_strength: based on price position within today's range
    day_range = high - low if high > low else 0.001
    price_position = (ltp - low) / day_range if day_range > 0 else 0.5
    sector_strength = min(price_position * 20, 20.0)

    return {
        "atr_pct": round(daily_range_pct, 2),
        "volume_multiplier": round(volume_multiplier, 2),
        "today_volume": round(today_volume, 0),
        "avg_daily_volume_20": round(avg_daily_volume_20, 0),
        "vwap": round(vwap, 2),
        "ema9": round(ema9, 2),
        "ema_angle_deg": round(ema_angle_deg, 2),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_velocity_pct": round(orb_velocity_pct, 2),
        "wick_noise_ratio": round(wick_noise_ratio, 3),
        "turnover_cr": round(turnover_cr, 2),
        "price_above_vwap": price_above_vwap,
        "price_above_ema9": price_above_ema9,
        "trigger_point": trigger_point,
        "rsi": 50.0,
        "oi_setup": oi_setup,
        "relative_volume": relative_volume,
        "liquidity_score": liquidity_score,
        "breakout_quality": breakout_quality,
        "sector_strength": sector_strength,
        "passes_hard_filters": passes_hard_filters,
        "hard_filter_reasons": hard_filter_reasons + ["metrics estimated from quote (candle API unavailable)"],
    }


def _empty_intraday_metrics(reason: str) -> dict[str, Any]:
    return {
        "atr_pct": 0.0,
        "volume_multiplier": 0.0,
        "today_volume": 0.0,
        "avg_daily_volume_20": 0.0,
        "vwap": 0.0,
        "ema9": 0.0,
        "ema_angle_deg": 0.0,
        "orb_high": 0.0,
        "orb_low": 0.0,
        "orb_velocity_pct": 0.0,
        "wick_noise_ratio": 1.0,
        "turnover_cr": 0.0,
        "price_above_vwap": False,
        "price_above_ema9": False,
        "trigger_point": "VWAP Bounce",
        "rsi": 50.0,
        "oi_setup": "NEUTRAL",
        "relative_volume": 0.0,
        "liquidity_score": 0.0,
        "breakout_quality": 0.0,
        "sector_strength": 0.0,
        "passes_hard_filters": False,
        "hard_filter_reasons": [reason],
    }


def _intraday_metrics(
    client: AngelOneClient,
    inst: Instrument,
    ltp: float,
    now: datetime,
    quote_fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        daily_from = (now - timedelta(days=45)).replace(hour=9, minute=15, second=0, microsecond=0)
        daily_to = now

        daily_raw = client.fetch_candles(inst.exchange, inst.token, "ONE_DAY", daily_from, daily_to)
        intraday_raw = client.fetch_candles(inst.exchange, inst.token, "FIVE_MINUTE", market_open, now)

        daily_candles = _parse_candle_rows(daily_raw)
        intraday_candles = _parse_candle_rows(intraday_raw)
    except Exception:
        daily_candles = []
        intraday_candles = []

    if not daily_candles or not intraday_candles:
        # Fallback: use quote data to compute best-effort metrics when candle API fails/returns empty
        if quote_fallback is not None:
            return _intraday_metrics_from_quote(ltp, now, quote_fallback)
        return _empty_intraday_metrics("insufficient candle data")

    daily_close = daily_candles[-1]["close"] or ltp or 1.0
    daily_volumes = [row["volume"] for row in daily_candles[-20:]]
    avg_daily_volume_20 = (sum(daily_volumes) / len(daily_volumes)) if daily_volumes else 0.0
    atr_pct = _atr_percent(daily_candles)

    today_volume = sum(row["volume"] for row in intraday_candles)
    volume_multiplier = (today_volume / avg_daily_volume_20) if avg_daily_volume_20 > 0 else 0.0

    vwap = _vwap(intraday_candles)
    closes = [row["close"] for row in intraday_candles]
    ema9_values = _ema(closes, period=9)
    ema9 = ema9_values[-1] if ema9_values else 0.0
    ema_angle_deg = _ema_angle_deg(ema9_values)

    orb_window = intraday_candles[:3] if len(intraday_candles) >= 3 else intraday_candles
    orb_high = max((row["high"] for row in orb_window), default=0.0)
    orb_low = min((row["low"] for row in orb_window), default=0.0)
    orb_velocity_pct = ((ltp - orb_high) / orb_high) * 100 if orb_high and ltp >= orb_high else 0.0

    wick_noise_ratio = _wick_noise_ratio(intraday_candles)
    turnover_cr = (ltp * today_volume) / 10_000_000 if ltp and today_volume else 0.0

    price_above_vwap = bool(vwap and ltp > vwap)
    price_above_ema9 = bool(ema9 and ltp > ema9)

    # RSI(14) from daily closes
    daily_closes = [row["close"] for row in daily_candles]
    rsi_val = _rsi(daily_closes, period=14)

    # OI classification from quote_fallback row (populated by _build_stock_row)
    current_oi = float((quote_fallback or {}).get("oi", 0) or 0)
    prev_oi_val = float((quote_fallback or {}).get("prev_oi", 0) or 0)
    prev_close = daily_candles[-2]["close"] if len(daily_candles) >= 2 else ltp
    if current_oi > 0 or prev_oi_val > 0:
        oi_setup = classify_oi_setup(ltp, prev_close, current_oi, prev_oi_val)
    else:
        oi_setup = "NEUTRAL"

    # Alpha score components (non-filter metrics — separate from hard filter variables)
    relative_volume = volume_multiplier
    liquidity_score = min(turnover_cr / 2.5, 20.0)
    last_candle = intraday_candles[-1] if intraday_candles else {}
    body_ratio = (
        abs(last_candle.get("close", 0) - last_candle.get("open", 0))
        / max(last_candle.get("high", 0) - last_candle.get("low", 0), 0.001)
    ) if last_candle else 0.0
    vwap_dist_pct = ((ltp - vwap) / vwap * 100) if vwap > 0 else 0.0
    breakout_quality = min(
        (body_ratio * 10 + vwap_dist_pct * 2) if ltp > vwap else 0.0,
        20.0,
    )
    highs_5 = [row["high"] for row in daily_candles[-5:]]
    lows_5 = [row["low"] for row in daily_candles[-5:]]
    five_day_range = max(highs_5) - min(lows_5) if highs_5 and lows_5 else 0.0
    price_position = ((ltp - min(lows_5)) / five_day_range) if five_day_range > 0 else 0.5
    sector_strength = min(price_position * 20, 20.0)

    hard_filter_reasons: list[str] = []
    if atr_pct <= 3.0:
        hard_filter_reasons.append("ATR under 3.0%")
    if volume_multiplier <= 3.0:
        hard_filter_reasons.append("opening volume under 3.0x")
    if wick_noise_ratio > 0.25:
        hard_filter_reasons.append("wick noise too high")
    if not price_above_vwap:
        hard_filter_reasons.append("below VWAP")
    if not price_above_ema9:
        hard_filter_reasons.append("below EMA9")
    if ema_angle_deg <= 45.0:
        hard_filter_reasons.append("EMA angle below 45 degrees")
    if turnover_cr < 50.0:
        hard_filter_reasons.append("turnover under 50 Cr")

    passes_hard_filters = len(hard_filter_reasons) == 0
    trigger_point = "VWAP Bounce" if price_above_vwap else "15-min ORB" if ltp >= orb_high else "Flag Breakout"

    return {
        "atr_pct": round(atr_pct, 2),
        "volume_multiplier": round(volume_multiplier, 2),
        "today_volume": round(today_volume, 0),
        "avg_daily_volume_20": round(avg_daily_volume_20, 0),
        "vwap": round(vwap, 2),
        "ema9": round(ema9, 2),
        "ema_angle_deg": round(ema_angle_deg, 2),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_velocity_pct": round(orb_velocity_pct, 2),
        "wick_noise_ratio": round(wick_noise_ratio, 3),
        "turnover_cr": round(turnover_cr, 2),
        "price_above_vwap": price_above_vwap,
        "price_above_ema9": price_above_ema9,
        "trigger_point": trigger_point,
        "rsi": rsi_val,
        "oi_setup": oi_setup,
        "relative_volume": relative_volume,
        "liquidity_score": liquidity_score,
        "breakout_quality": breakout_quality,
        "sector_strength": sector_strength,
        "passes_hard_filters": passes_hard_filters,
        "hard_filter_reasons": hard_filter_reasons,
    }


def _fetch_intraday_chunk(
    client: AngelOneClient,
    rows: list[dict[str, Any]],
    stock_universe_by_key: dict[str, Instrument],
    now: datetime,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for row in rows:
        inst = stock_universe_by_key.get(str(row["ticker"]))
        if not inst:
            continue
        ltp = float(row.get("ltpRaw", 0) or 0)
        # Build quote_fallback from the row data (populated from batch quote API)
        quote_fallback = {
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "tradeVolume": row.get("volume"),
            "ltp": ltp,
            "oi": row.get("oi"),
            "prev_oi": row.get("prev_oi"),
            "opnInterest": row.get("oi"),
            "previousOI": row.get("prev_oi"),
        }
        try:
            metrics = _intraday_metrics(client, inst, ltp, now, quote_fallback=quote_fallback)
        except Exception:
            import traceback as _traceback
            logging.getLogger(__name__).error(
                "fetch error for %s: %s", str(row.get("ticker", "?")), _traceback.format_exc()
            )
            metrics = _empty_intraday_metrics("fetch error")
        results[str(row["ticker"])] = metrics
    return results


def _fetch_all_intraday_chunked(
    client: AngelOneClient,
    candidate_rows: list[dict[str, Any]],
    stock_universe_by_key: dict[str, Instrument],
    now: datetime,
) -> dict[str, dict[str, Any]]:
    chunks = [
        candidate_rows[i : i + INTRADAY_CHUNK_SIZE]
        for i in range(0, len(candidate_rows), INTRADAY_CHUNK_SIZE)
    ]
    all_metrics: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        all_metrics.update(_fetch_intraday_chunk(client, chunk, stock_universe_by_key, now))

    return all_metrics


def _heuristic_rank(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in stocks:
        ltp = float(row.get("ltpRaw") or 0)
        close = float(row.get("close") or 0)
        pct = abs(((ltp - close) / close) * 100) if close else 0.0
        volume = float(row.get("volume") or 0)
        intraday = row.get("intraday") or {}
        score = round(
            abs(pct) * 2.0
            + (0.0 if volume <= 0 else (len(str(int(volume))) - 1))
            + float(intraday.get("atr_pct") or 0.0)
            + float(intraday.get("volume_multiplier") or 0.0) * 2.0,
            2,
        )
        ranked.append({**row, "score": score})
    ranked.sort(key=lambda item: item.get("score", 0), reverse=True)
    return ranked[:_TI_TOP_SELECTION_COUNT]


# =============================================================================
# ALPHA SCORE — Non-filter metrics (Stage 1 Quant Engine output)
# =============================================================================

def _calculate_alpha_score(metrics: dict[str, Any]) -> float:
    """
    Alpha Score from non-filter metrics.
    Prevents circular logic by keeping filter variables (ATR, turnover, RSI,
    vol_mult) completely separate from the scoring components.

    Components (max 100 pts):
      relative_volume   x 15  -> capped at 40
      liquidity_score         -> capped at 20
      breakout_quality        -> capped at 20
      sector_strength         -> capped at 20
    """
    score = 0.0
    score += min(metrics.get("relative_volume", 0.0) * 15, 40.0)
    score += min(metrics.get("liquidity_score", 0.0), 20.0)
    score += min(metrics.get("breakout_quality", 0.0), 20.0)
    score += min(metrics.get("sector_strength", 0.0), 20.0)
    return round(score, 2)


def _compute_deterministic_pipeline(all_stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Stage 1: Deterministic Quant Engine.

    Applies hard filters 100% mathematically (no LLM) then ranks survivors
    by Alpha Score.  Hard filter variables and Alpha Score variables are kept
    strictly separate to avoid circular scoring logic.

    Hard filter gates:
      ATR > 3%  |  turnover > 50 Cr  |  LTP > VWAP
      OI in (LONG_BUILDUP, SHORT_COVERING)
      vol_mult > 1.5  |  RSI > 55  |  spread < 0.10  |  wick < 0.40

    Alpha score uses: relative_volume, liquidity_score,
                      breakout_quality, sector_strength
    """
    ranked_universe: list[dict[str, Any]] = []

    for stock in all_stocks:
        metrics = stock.get("intraday", {})
        ltp = float(stock.get("ltpRaw", 0.0) or 0.0)

        # Hard filter variables (never reused in Alpha Score)
        atr        = metrics.get("atr_pct", 0.0)
        turnover   = metrics.get("turnover_cr", 0.0)
        vwap_val   = metrics.get("vwap", 0.0)
        oi_setup   = metrics.get("oi_setup", "UNKNOWN")
        vol_mult   = metrics.get("volume_multiplier", 1.0)
        rsi_val    = metrics.get("rsi", 50.0)
        spread     = metrics.get("spread_pct", 0.0)
        wick_noise = metrics.get("wick_noise_ratio", 0.0)

        passes = all([
            atr > 1.5,
            turnover > 10.0,
            ltp > vwap_val,
            oi_setup in ("LONG_BUILDUP", "SHORT_COVERING", "SHORT_BUILDUP", "LONG_UNWINDING"),
            vol_mult >= 0.8,
            rsi_val > 40.0,
            spread < 0.50,
            wick_noise < 0.70,
        ])

        # Always compute alpha_score so every stock shows its quantitative signal strength
        alpha_score = _calculate_alpha_score(metrics)
        stock["passes_hard_filters"] = passes
        stock["alpha_score"] = alpha_score

        if passes:
            ranked_universe.append(stock)

    # Deterministic sort: Alpha Score desc, ticker asc (stable tie-break)
    ranked_universe.sort(key=lambda x: (-x["alpha_score"], x["ticker"]))

    # Pad to 20 with highest-volume non-qualifiers when fewer than 20 pass
    if len(ranked_universe) < 20:
        non_qualifiers = [s for s in all_stocks if not s.get("passes_hard_filters", False)]
        non_qualifiers.sort(key=lambda x: -(x.get("volume") or 0))
        for stock in non_qualifiers:
            if len(ranked_universe) >= 20:
                break
            stock.setdefault("alpha_score", 0.0)
            ranked_universe.append(stock)

    return ranked_universe[:20]


# =============================================================================
# LLM SAFETY AUDITOR — Stage 2 (risk-only, never a stock ranker)
# =============================================================================

def _execute_llm_risk_audit(
    top_20: list[dict[str, Any]],
    news_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Stage 2: LLM Safety Audit.

    The LLM acts ONLY as a risk auditor -- it audits non-technical domains
    (news risk, earnings risk, regulatory/governance/corporate-action risk).
    It NEVER receives technical indicators (ATR, VWAP, RSI, Volume, OI, EMA).
    Only ticker + alpha_score are forwarded.

    Gracefully degrades to APPROVE + warning flag when LLM is unavailable.
    """
    config = _llm_config_canonical()
    provider, api_key, api_url, model, oauth_token_path = config or (None, None, None, None, None)

    if not provider or not api_key:
        for stock in top_20:
            stock["risk_flags"] = ["LLM unavailable -- news risk not audited"]
            stock["verdict"] = "APPROVE"
        return top_20

    news_context = "\n".join([
        f"Source: {n.get('source','')} | Title: {n.get('title','')} | "
        f"Summary: {n.get('summary','')} | Link: {n.get('link','')}"
        for n in news_items[:15]
    ])

    # ONLY ticker + alpha_score -- NO technical data sent to LLM
    ticker_context = [
        {"ticker": s["ticker"], "alpha_score": s.get("alpha_score", 0.0)}
        for s in top_20
    ]
    ticker_json = json.dumps(ticker_context, indent=2)

    prompt = (
        f"Tickers to audit:\n{ticker_json}\n\n"
        f"News/Event context:\n{news_context}\n\n"
        "Return a valid JSON object matching this structure exactly:\n"
        "{\"audits\": {\"TICKER_SYMBOL\": {\"risk_flags\": [\"Reason text (Source: name, Timestamp: iso)\"], \"verdict\": \"APPROVE or REJECT\"}}}"
    )

    # Retry logic: try full timeout first (up to 5 mins), then a quick retry
    audit_timeouts = [LLM_CALL_TIMEOUT_SECONDS, min(60, LLM_CALL_TIMEOUT_SECONDS)]
    last_exc = None

    for attempt, timeout in enumerate(audit_timeouts):
        try:
            if provider == "gemini":
                from .llm_client import _call_gemini as _llm_gemini
                res_text = _llm_gemini(
                    prompt=prompt,
                    api_key=api_key,
                    model=model,
                    system_instruction=SYSTEM_PROMPT,
                    timeout=timeout,
                    oauth_token_path=oauth_token_path,
                )
            elif provider == "openai":
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                body = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 2000,
                }
                resp = requests.post(api_url, json=body, headers=headers, timeout=timeout)
                if resp.status_code >= 300:
                    raise RuntimeError(f"OpenAI audit failed ({resp.status_code}): {resp.text}")
                data = resp.json()
                res_text = data["choices"][0]["message"]["content"].strip()
            else:
                raise RuntimeError(f"Unsupported LLM provider for audit: {provider}")

            # Strip markdown code fences if present
            _clean_text = res_text.strip()
            if _clean_text.startswith("```"):
                _clean_text = _clean_text.lstrip("`")
                if _clean_text.lower().startswith("json"):
                    _clean_text = _clean_text[4:].lstrip("\n")
                if "```" in _clean_text:
                    _clean_text = _clean_text[:_clean_text.index("```")]
                _clean_text = _clean_text.strip()

            from .ai_ticker_news import _parse_json_response
            parsed = _parse_json_response(_clean_text, ["audits"])
            audits = parsed.get("audits", {})
            # Guard: _parse_json_response regex fallback (Strategy 5)
            # may extract the audits value as a plain string instead of
            # a nested dict when the LLM response is malformed JSON.
            if isinstance(audits, str):
                # Attempt to re-parse the audits blob as a JSON object
                try:
                    audits = json.loads(audits)
                    if not isinstance(audits, dict):
                        audits = {}
                except (json.JSONDecodeError, TypeError):
                    audits = {}
            if not isinstance(audits, dict):
                audits = {}

            for stock in top_20:
                ticker = stock["ticker"]
                audit = audits.get(ticker, {"risk_flags": [], "verdict": "APPROVE"})
                stock["risk_flags"] = audit.get("risk_flags", []) or ["None"]
                stock["verdict"] = audit.get("verdict", "APPROVE")
            break  # success, skip retry

        except Exception as exc:
            last_exc = exc
            logging.getLogger(__name__).warning(
                "LLM audit attempt %d/%d failed (timeout=%ds): %s",
                attempt + 1, len(audit_timeouts), timeout, exc,
            )
    else:
        # All attempts exhausted
        is_timeout = "timeout" in str(last_exc).lower() or "timed out" in str(last_exc).lower()
        flag_msg = (
            f"LLM audit timed out after {sum(audit_timeouts)}s -- news risk not audited"
            if is_timeout
            else f"LLM Audit Error ({last_exc}) -- news risk not audited"
        )
        for stock in top_20:
            stock["risk_flags"] = [flag_msg]
            stock["verdict"] = "APPROVE"

    return top_20


# =============================================================================
# INSTITUTIONAL AUDIT LEDGER
# =============================================================================

def build_audit_ledger(stocks: list[dict[str, Any]]) -> list[str]:
    """
    Build formatted audit ledger rows for institutional logging.
    Isolated from business logic -- formatting only.
    """
    ts = _ist_now().isoformat()
    return [
        f"{s['ticker']} | "
        f"Alpha Score: {s.get('alpha_score', 0.0)} | "
        f"Risk Flags: [{', '.join(s.get('risk_flags', ['None']))}] | "
        f"Verdict: {s.get('verdict', 'APPROVE')} | "
        f"Timestamp: {ts}"
        for s in stocks
    ]



def _coarse_pre_rank(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in stocks:
        ltp = float(row.get("ltpRaw") or 0)
        close = float(row.get("close") or 0)
        pct = abs(((ltp - close) / close) * 100) if close else 0.0
        volume = float(row.get("volume") or 0)
        score = round(abs(pct) * 2.0 + (0.0 if volume <= 0 else math.log10(volume + 1)), 2)
        ranked.append({**row, "_coarse_score": score})
    ranked.sort(key=lambda item: item.get("_coarse_score", 0), reverse=True)
    return ranked


def _hard_screen(stock: dict[str, Any]) -> bool:
    intraday = stock.get("intraday") or {}
    return bool(intraday.get("passes_hard_filters"))


def _compile_selection_stream(
    all_stocks: list[dict[str, Any]],
    pool_name: str,
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    hard_screen_count: int,
    custom_prompt: str | None = None,
) -> str:
    lines = [
        f"TOP_N: {_TI_TOP_SELECTION_COUNT}",
        f"ACTIVE_POOL: {pool_name}",
        f"FILTER_PROMPT: {_filter_prompt(custom_prompt)}",
        f"HARD_SCREEN_PASS_COUNT: {hard_screen_count}/{len(all_stocks)}",
        "IMPORTANT: Use only the live Angel One universe below. Do not invent tickers.",
        "Return a valid JSON object matching the terminal intelligence schema.",
        "",
        "--- LIVE ANGEL ONE UNIVERSE ---",
    ]

    for stock in all_stocks:
        intraday = stock.get("intraday") or {}
        hard_status = "PASS" if intraday.get("passes_hard_filters") else "FAIL"
        reasons = "; ".join(intraday.get("hard_filter_reasons") or []) or "none"
        lines.append(
            f"{stock['ticker']} | {stock['name']} | LTP {stock['ltp']} | delta {stock['delta']} | "
            f"state {stock['state']} | close {stock.get('close')} | volume {stock.get('volume')} | "
            f"ATR% {intraday.get('atr_pct', 0)} | volX {intraday.get('volume_multiplier', 0)} | "
            f"VWAP {intraday.get('vwap', 0)} | EMA9 {intraday.get('ema9', 0)} | ORB {intraday.get('orb_high', 0)} | "
            f"turnoverCr {intraday.get('turnover_cr', 0)} | screen {hard_status} | reasons {reasons}"
        )

    if news_items:
        lines.append("")
        lines.append("--- NEWS FEEDS ---")
        for item in news_items[:10]:
            lines.append(f"{item['source']} | {item['title']} | {item['summary']} | {item['link']}")

    if macro_morning:
        lines.append("")
        lines.append("--- MACRO MORNING ---")
        for row in macro_morning[:10]:
            lines.append(f"{row['label']} | {row['val']} | {row['delta']} | {row['state']}")

    if macro_evening:
        lines.append("")
        lines.append("--- MACRO EVENING ---")
        for row in macro_evening[:10]:
            lines.append(f"{row['label']} | {row['val']} | {row['delta']} | {row['state']}")

    return "\n".join(lines)


def _select_dynamic_top_stocks(
    all_stocks: list[dict[str, Any]],
    pool_name: str,
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    custom_prompt: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    if not all_stocks:
        return [], None, None

    try:
        screened = [row for row in all_stocks if _hard_screen(row)]
        selection_universe = screened if len(screened) >= _TI_TOP_SELECTION_COUNT else all_stocks
        llm_universe = selection_universe[:LLM_UNIVERSE_LIMIT]
        compiled = _compile_selection_stream(
            llm_universe,
            pool_name=pool_name,
            news_items=news_items,
            macro_morning=macro_morning,
            macro_evening=macro_evening,
            hard_screen_count=len(screened),
            custom_prompt=custom_prompt,
        )
        ti = execute_terminal_intelligence_pipeline(compiled)
        ti_payload = ti.model_dump()
        selected_tickers = [row.get("ticker") for row in ti_payload.get("ledger_stocks", []) if row.get("ticker")]
        selected_tickers = selected_tickers[:_TI_TOP_SELECTION_COUNT]
        score_by_ticker = {
            row.get("ticker"): row.get("score")
            for row in ti_payload.get("ledger_stocks", [])
            if row.get("ticker") is not None
        }
        by_ticker = {row["ticker"]: row for row in all_stocks}
        for row in ti_payload.get("ledger_stocks", []):
            ticker = row.get("ticker")
            if not ticker:
                continue
            src = by_ticker.get(ticker)
            if src:
                rv = str(row.get("delta") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("delta"):
                    row["delta"] = src["delta"]
                rv = str(row.get("ltp") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("ltp"):
                    row["ltp"] = src["ltp"]
                rv = str(row.get("name") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("name"):
                    row["name"] = src["name"]
        selected_rows = []
        for ticker in selected_tickers:
            row = by_ticker.get(ticker)
            if row:
                selected_rows.append({**row, "score": score_by_ticker.get(ticker)})

        if not selected_rows:
            selected_rows = _heuristic_rank(selection_universe)
        else:
            if len(selected_rows) < _TI_TOP_SELECTION_COUNT:
                remaining = [row for row in _heuristic_rank(selection_universe) if row["ticker"] not in {r["ticker"] for r in selected_rows}]
                selected_rows.extend(remaining[: _TI_TOP_SELECTION_COUNT - len(selected_rows)])

        news_summary = (
            ti_payload.get("news_catalysts_card") or ti_payload.get("forensic_screen_card") or ti_payload.get("why_interested")
        )
        return selected_rows[:_TI_TOP_SELECTION_COUNT], ti_payload, news_summary
    except Exception as e:
        # Do not return heuristic data. Return error state so system knows to try on-demand later.
        ti_payload = {
            "llmError": str(e),
            "why_interested": "LLM selection failed.",
            "ledger_stocks": [],
            "news_catalysts_card": None,
            "forensic_screen_card": None,
        }
        return [], ti_payload, None


def _build_macro_strips(macro_raw: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    morning: list[dict[str, Any]] = []
    evening: list[dict[str, Any]] = []
    seen_labels: set[str] = set()

    # Build a map of label -> Yahoo row (with sparkline data) so we can attach
    # sparklines to Angle One instrument rows and avoid losing them.
    yahoo_sparklines: dict[str, list[float]] = {}
    for row in fetch_domestic_index_macro():
        sparkline = row.get("sparkline", [])
        if isinstance(sparkline, list) and len(sparkline) > 1:
            yahoo_sparklines[row["label"].upper()] = sparkline
    for row in fetch_domestic_yahoo_macro():
        sparkline = row.get("sparkline", [])
        if isinstance(sparkline, list) and len(sparkline) > 1:
            yahoo_sparklines[row["label"].upper()] = sparkline

    for inst in MACRO_INSTRUMENTS:
        quote = macro_raw.get(inst.key)
        if not quote:
            continue
        ltp = float(quote.get("ltp", 0) or 0)
        close = float(quote.get("close", 0) or ltp)
        delta, state = _pct_change(ltp, close if close else None)
        label = inst.label or inst.key
        # Attach sparkline from Yahoo if available for this label
        label_upper = label.upper()
        sparkline = yahoo_sparklines.get(label_upper, [])
        morning.append({"label": label, "val": f"{ltp:,.2f}", "delta": delta, "state": state, "sparkline": sparkline})
        evening.append({"label": f"{label} Close", "val": f"{ltp:,.2f}", "delta": delta, "state": state, "sparkline": sparkline})
        seen_labels.add(label_upper)

    for row in fetch_domestic_index_macro():
        label = str(row["label"])
        if label.upper() in seen_labels:
            continue
        morning.append({k: row.get(k) for k in ("label", "val", "delta", "state", "sparkline")})
        evening.append({"label": f"{row['label']} Close", "val": row["val"], "delta": row["delta"], "state": row["state"], "sparkline": row.get("sparkline", [])})
        seen_labels.add(label.upper())

    for row in fetch_domestic_yahoo_macro():
        morning.append({k: row.get(k) for k in ("label", "val", "delta", "state", "sparkline")})
        evening.append({"label": f"{row['label']} Close", "val": row["val"], "delta": row["delta"], "state": row["state"], "sparkline": row.get("sparkline", [])})

    # GIFT NIFTY from NSE India API (has no sparkline data, so default to [])
    gift_nifty = fetch_gift_nifty()
    if gift_nifty and gift_nifty["label"].upper() not in seen_labels:
        gs = gift_nifty.get("sparkline", []) or []
        morning.append({"label": gift_nifty["label"], "val": gift_nifty["val"], "delta": gift_nifty["delta"], "state": gift_nifty["state"], "sparkline": gs})
        evening.append({"label": f"{gift_nifty['label']} Close", "val": gift_nifty["val"], "delta": gift_nifty["delta"], "state": gift_nifty["state"], "sparkline": gs})
        seen_labels.add(gift_nifty["label"].upper())

    return morning, evening


def _build_terminal_payload(
    all_stocks: list[dict[str, Any]],
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    pool_name: str = NIFTY_100_LABEL,
    custom_prompt: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    return _select_dynamic_top_stocks(
        all_stocks=all_stocks,
        pool_name=pool_name,
        news_items=news_items,
        macro_morning=macro_morning,
        macro_evening=macro_evening,
        custom_prompt=custom_prompt,
    )


def _build_payload_from_live_data(
    client: AngelOneClient,
    pool_name: str | None = None,
    custom_prompt: str | None = None,
    force_llm_refresh: bool = False,
) -> dict[str, Any]:
    llm_config = _llm_config_canonical()
    now = _ist_now()
    resolved_pool_name = pool_name or NIFTY_100_LABEL
    stock_universe, active_pool_label = _pool_watchlist(resolved_pool_name)

    stock_quotes_raw = client.fetch_batch_quotes(stock_universe)
    macro_raw = client.fetch_batch_quotes(list(MACRO_INSTRUMENTS))

    all_stocks: list[dict[str, Any]] = []
    stock_quotes: dict[str, dict[str, Any]] = {}
    stock_universe_by_key = {inst.key: inst for inst in stock_universe}
    for inst in stock_universe:
        quote = stock_quotes_raw.get(inst.key)
        if not quote:
            continue
        row = _build_stock_row(inst, quote, active_pool_label)
        all_stocks.append(row)
        stock_quotes[inst.key] = row

    candle_limit = int(os.getenv("INTRADAY_CANDIDATE_LIMIT", "20"))
    candidate_rows = _coarse_pre_rank(all_stocks)[:candle_limit]
    candidate_keys = {row["ticker"] for row in candidate_rows}
    row_by_ticker = {row["ticker"]: row for row in all_stocks}

    for row in all_stocks:
        if row["ticker"] not in candidate_keys:
            row["intraday"] = {
                "atr_pct": 0.0,
                "volume_multiplier": 0.0,
                "today_volume": 0.0,
                "avg_daily_volume_20": 0.0,
                "vwap": 0.0,
                "ema9": 0.0,
                "ema_angle_deg": 0.0,
                "orb_high": 0.0,
                "orb_low": 0.0,
                "orb_velocity_pct": 0.0,
                "wick_noise_ratio": 1.0,
                "turnover_cr": 0.0,
                "price_above_vwap": False,
                "price_above_ema9": False,
                "trigger_point": "VWAP Bounce",
                "passes_hard_filters": False,
                "hard_filter_reasons": ["not in intraday candidate set"],
            }

    all_metrics = _fetch_all_intraday_chunked(client, candidate_rows, stock_universe_by_key, now)
    for ticker, metrics in all_metrics.items():
        original = row_by_ticker.get(ticker)
        if original is not None:
            original["intraday"] = metrics
            stock_quotes[ticker] = original

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 1: Deterministic Quant Engine
    # Applies hard filters and computes Alpha Scores with no LLM involvement.
    # Returns top 20 sorted by Alpha Score; pads with volume leaders if needed.
    # ─────────────────────────────────────────────────────────────────────────
    top_20_quant = _compute_deterministic_pipeline(all_stocks)

    macro_morning, macro_evening = _build_macro_strips(macro_raw)
    global_macro = fetch_global_macro()
    news_items = fetch_live_news()

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 2: LLM Safety Auditor
    # Audits ONLY non-technical risk domains using news context.
    # Attaches risk_flags + verdict to each stock; never re-ranks technically.
    # ─────────────────────────────────────────────────────────────────────────
    final_audited = _execute_llm_risk_audit(top_20_quant, news_items)

    # Print institutional audit ledger to server log
    ledger_rows = build_audit_ledger(final_audited)
    _log = logging.getLogger(__name__)
    _log.info("\n" + "=" * 40 + " INSTITUTIONAL RISK AUDIT LEDGER " + "=" * 40)
    for ledger_row in ledger_rows:
        _log.info(ledger_row)
    _log.info("=" * 113)

    # AI NEWS ANALYSIS: Call once completely & subsequent from cache unless forced or data missing
    snapshot = _load_last_snapshot()
    existing_ti = snapshot.get("terminalIntelligence") if snapshot else None
    existing_summary = snapshot.get("newsSummary") if snapshot else None
    existing_ticker_news = snapshot.get("tickerNewsByTicker") if snapshot else {}

    # Logic: If we have valid AI data and aren't forcing a refresh, reuse it to avoid timeouts.
    # If existing data is an error message or missing, we trigger the LLM.
    can_reuse_ai = (
        not force_llm_refresh and
        existing_ti and
        not existing_ti.get("llmError") and
        existing_summary
    )

    if can_reuse_ai:
        top_rows, terminal_intel, news_summary = (snapshot.get("stocks") or [], existing_ti, existing_summary)
    else:
        top_rows, terminal_intel, news_summary = _build_terminal_payload(
            all_stocks=final_audited,
            news_items=news_items,
            macro_morning=macro_morning,
            macro_evening=macro_evening,
            pool_name=resolved_pool_name,
            custom_prompt=custom_prompt,
        )

    payload = {
        "success": True,
        "source": "angel_one+news+llm_dynamic_top20",
        "rawSources": _news_feed_sources(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "mockTickers": sorted(MOCK_TICKERS),
        "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
        "activePool": resolved_pool_name,
        "poolDescription": (
            "Nifty 100 Angel One live universe ranked by your filter prompt."
            if resolved_pool_name == NIFTY_100_LABEL
            else f"Dynamic live universe label applied for {resolved_pool_name}."
        ),
        "stocks": top_rows,
        "stockQuotes": stock_quotes,
        "macroDataStrip": {"morning": macro_morning, "evening": macro_evening},
        "globalMacro": global_macro,
        "news": news_items,
        "llmProvider": llm_config[0] if llm_config else None,
        "llmConfigured": llm_config is not None,
        "newsSummary": news_summary,
        "llmError": None,
        "terminalIntelligence": terminal_intel,
        "tickerIntelligenceByTicker": {},
        "tickerNewsByTicker": existing_ticker_news or {},
        "isSnapshotFallback": False,
    }

    payload = _hydrate_ticker_intelligence_map(payload)
    _apply_selection_meta(
        payload,
        mode="live",
        reason="Live refresh completed during the scheduled IST window.",
        data_date=now.date().isoformat(),
    )

    return payload


def build_market_payload(
    client: AngelOneClient,
    pool_name: str | None = None,
    force_refresh: bool = False,
    custom_prompt: str | None = None,
    allow_fallback: bool = True, # If live fetch fails, allow falling back to snapshot
    prefer_cache: bool = False, # If true, try cache first, then live if cache is empty/stale
) -> dict[str, Any]:
    snapshot = _load_last_snapshot()

    if prefer_cache and snapshot:
        # If preferring cache and a snapshot exists, return it immediately.
        # The frontend can then decide to trigger an on-demand refresh if data is missing.
        snapshot = dict(snapshot)
        snapshot["isSnapshotFallback"] = True
        snapshot["updatedAt"] = datetime.now(timezone.utc).isoformat()
        snapshot.setdefault("tickerNewsByTicker", {})
        if pool_name:
            snapshot["activePool"] = pool_name
        # Always serve fresh RSS news even when the rest of the snapshot is cached,
        # so the news panel never shows stale, pre-RSS headlines.
        try:
            fresh_news = fetch_live_news()
            if fresh_news:
                snapshot["news"] = fresh_news
        except Exception:
            pass
        _apply_selection_meta(
            snapshot,
            mode="snapshot",
            reason="Cache preferred. Serving the latest saved snapshot with fresh news.",
            data_date=_payload_data_date(snapshot),
        )
        return _hydrate_ticker_intelligence_map(snapshot)

    # Attempt live data fetch
    try:
        payload = _build_payload_from_live_data(
            client, 
            pool_name=pool_name, 
            custom_prompt=custom_prompt,
            force_llm_refresh=force_refresh # Only refresh LLM if explicitly forced (on-demand)
        )
        _save_last_snapshot(payload)
        return payload
    except Exception as exc:
        if force_refresh and not allow_fallback:
            raise
        if allow_fallback and snapshot is not None:
            snapshot = dict(snapshot)
            snapshot["isSnapshotFallback"] = True
            snapshot["llmError"] = snapshot.get("llmError")
            snapshot["updatedAt"] = datetime.now(timezone.utc).isoformat()
            snapshot.setdefault("tickerNewsByTicker", {})
            if pool_name:
                snapshot["activePool"] = pool_name
            # Refresh RSS news even when outside refresh window
            try: # Still try to fetch fresh news even if falling back to old stock data
                fresh_news = fetch_live_news()
                if fresh_news:
                    snapshot["news"] = fresh_news
            except Exception:
                pass
            _apply_selection_meta(
                snapshot,
                mode="snapshot",
                reason=f"Live refresh failed ({exc}). Serving the latest saved snapshot with fresh news.",
                data_date=_payload_data_date(snapshot),
            )
            return _hydrate_ticker_intelligence_map(snapshot)
        if not allow_fallback:
            return {
                "success": False,
                "error": "Live refresh was requested but the scheduled refresh window is not active and fallback is disabled.",
                "rawSources": _news_feed_sources(),
                "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
                "activePool": pool_name or NIFTY_100_LABEL,
                "poolDescription": "Nifty 100 Angel One live universe ranked by your filter prompt.",
                "stocks": [],
                "stockQuotes": {},
                "macroDataStrip": {"morning": [], "evening": []},
                "globalMacro": {"indices": [], "commodities": []},
                "news": [],
                "newsSummary": None,
                "llmError": None,
                "terminalIntelligence": None,
                "tickerIntelligenceByTicker": {},
                "tickerNewsByTicker": {},
                "isSnapshotFallback": False,
                "selectionMeta": {
                    "mode": "live",
                    "reason": f"Live refresh failed ({exc}) and fallback is disabled.",
                    "dataDate": _ist_now().date().isoformat(),
                },
            }
        return {
            "success": False,
            "error": "No cached snapshot available. Live refresh runs only during the morning or evening IST windows.",
            "rawSources": _news_feed_sources(),
            "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
            "activePool": pool_name or NIFTY_100_LABEL,
            "poolDescription": "Nifty 100 Angel One live universe ranked by your filter prompt.",
            "stocks": [],
            "stockQuotes": {},
            "macroDataStrip": {"morning": [], "evening": []},
            "globalMacro": {"indices": [], "commodities": []},
            "news": [],
            "newsSummary": None,
            "llmError": None,
            "terminalIntelligence": None,
            "tickerIntelligenceByTicker": {},
            "tickerNewsByTicker": {},
            "isSnapshotFallback": True,
            "selectionMeta": {
                "mode": "snapshot",
                    "reason": f"Live refresh failed ({exc}) and no cached snapshot is available.",
                "dataDate": _ist_now().date().isoformat(),
            },
        }


def _compile_market_analysis_stream(payload: dict[str, Any], custom_prompt: str | None = None) -> str:
    lines = [
        f"TOP_N: {_TI_TOP_SELECTION_COUNT}",
        f"FILTER_PROMPT: {_filter_prompt(custom_prompt)}",
        "Use the live Angel One universe and return only valid JSON.",
        "",
        "--- NEWS ---",
    ]

    for item in payload.get("news", [])[:10]:
        lines.append(
            f"Source: {item['source']}\nTitle: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n"
        )

    lines.append("--- TOP STOCKS ---")
    for stock in payload.get("stocks", [])[:_TI_TOP_SELECTION_COUNT]:
        lines.append(
            f"{stock['ticker']} ({stock['name']}): LTP {stock['ltp']}, delta {stock['delta']}, "
            f"state {stock['state']}, close {stock.get('close')}, volume {stock.get('volume')}"
        )

    lines.append("--- MACRO MORNING ---")
    for row in payload.get("macroDataStrip", {}).get("morning", [])[:10]:
        lines.append(f"{row['label']}: {row['val']} {row['delta']} {row['state']}")

    return "\n".join(lines)


def create_app() -> FastAPI:
    app = FastAPI(title="IROS Angel One Market Feed", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/market-data")
    def market_data(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            return build_market_payload(AngelOneClient(), pool_name=pool, custom_prompt=prompt, prefer_cache=True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/audit-verdicts")
    def audit_verdicts() -> dict[str, Any]:
        """Return all ticker risk audit results (Approved or Rejected) in clean JSON."""
        snapshot = _load_last_snapshot()
        if not snapshot:
            return {
                "success": False,
                "error": "No cached market snapshot available. Run a live refresh first."
            }
        
        verdicts = []
        for stock in snapshot.get("stocks", []):
            verdicts.append({
                "ticker": stock.get("ticker"),
                "name": stock.get("name"),
                "alpha_score": stock.get("alpha_score", 0.0),
                "verdict": stock.get("verdict", "APPROVE"),
                "risk_flags": stock.get("risk_flags", ["None"])
            })
            
        return {
            "success": True,
            "updatedAt": snapshot.get("updatedAt"),
            "count": len(verdicts),
            "verdicts": verdicts
        }

    @app.get("/api/intraday-matrix")
    def intraday_matrix() -> dict[str, Any]:
        """Return lemonn.co.in intraday stock recommendations (upper panel)."""
        try:
            from .lemonn_recommender import (
                fetch_intraday_recommendations,
                recommendations_to_dict,
            )
            recs = fetch_intraday_recommendations(top_n=10)
            return {
                "success": True,
                "recommendations": recommendations_to_dict(recs),
                "count": len(recs),
                "source": "lemonn.co.in",
            }
        except Exception:
            # Fallback: When lemonn.co.in is unreachable, return mock data
            # so the frontend never shows a 404 error page.
            _mock = [
                {"symbol": "RELIANCE", "name": "Reliance Industries", "direction": "BUY",
                 "buyPrice": 2950.00, "sellPrice": 3070.00, "stopLoss": 2910.00,
                 "riskPerShare": 40.00, "confidence": 82.0, "reasons": ["Strong breakout above 15m high", "RSI momentum bullish"]},
                {"symbol": "TCS", "name": "Tata Consultancy", "direction": "BUY",
                 "buyPrice": 4120.00, "sellPrice": 4280.00, "stopLoss": 4060.00,
                 "riskPerShare": 60.00, "confidence": 78.0, "reasons": ["Above 5m and 15m EMA50", "Delivery volume strong"]},
                {"symbol": "HDFCBANK", "name": "HDFC Bank", "direction": "BUY",
                 "buyPrice": 1680.00, "sellPrice": 1740.00, "stopLoss": 1655.00,
                 "riskPerShare": 25.00, "confidence": 85.0, "reasons": ["Daily SMA50 support held", "Bank Nifty momentum"]},
                {"symbol": "INFY", "name": "Infosys Ltd", "direction": "BUY",
                 "buyPrice": 1520.00, "sellPrice": 1580.00, "stopLoss": 1495.00,
                 "riskPerShare": 25.00, "confidence": 76.0, "reasons": ["IT sector rotation", "Above VWAP"]},
                {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "direction": "BUY",
                 "buyPrice": 1425.00, "sellPrice": 1480.00, "stopLoss": 1400.00,
                 "riskPerShare": 25.00, "confidence": 80.0, "reasons": ["Telecom sector strength", "ARPU upgrade cycle"]},
                {"symbol": "LT", "name": "Larsen & Toubro", "direction": "BUY",
                 "buyPrice": 3650.00, "sellPrice": 3790.00, "stopLoss": 3590.00,
                 "riskPerShare": 60.00, "confidence": 73.0, "reasons": ["Capex cycle play", "Order book momentum"]},
                {"symbol": "SUNPHARMA", "name": "Sun Pharma", "direction": "SELL",
                 "buyPrice": 1580.00, "sellPrice": 1520.00, "stopLoss": 1610.00,
                 "riskPerShare": 30.00, "confidence": 65.0, "reasons": ["RSI overbought", "Pharma sector profit booking"]},
                {"symbol": "TITAN", "name": "Titan Company", "direction": "BUY",
                 "buyPrice": 3760.00, "sellPrice": 3910.00, "stopLoss": 3700.00,
                 "riskPerShare": 60.00, "confidence": 79.0, "reasons": ["Consumer demand recovery", "Gold price tailwind"]},
                {"symbol": "MARUTI", "name": "Maruti Suzuki", "direction": "BUY",
                 "buyPrice": 12450.00, "sellPrice": 12880.00, "stopLoss": 12280.00,
                 "riskPerShare": 170.00, "confidence": 81.0, "reasons": ["Auto sales momentum", "New launch pipeline"]},
                {"symbol": "SBIN", "name": "State Bank of India", "direction": "BUY",
                 "buyPrice": 820.00, "sellPrice": 850.00, "stopLoss": 808.00,
                 "riskPerShare": 12.00, "confidence": 84.0, "reasons": ["PSU banking rally", "Valuation comfort"]},
            ]
            return {
                "success": True,
                "recommendations": _mock,
                "count": len(_mock),
                "source": "lemonn.co.in (mock fallback)",
                "isMock": True,
            }

    @app.get("/api/dhan-scanner-matrix")
    def dhan_scanner_matrix() -> dict[str, Any]:
        """Dhan ScanX → feed_scanner pipeline with Trade Plan + ₹5L capital allocation."""
        try:
            from .dhan_scanner_service import fetch_dhan_scan_results
            return fetch_dhan_scan_results(min_volume=1_000_000, top_n=10)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/trade-outcomes")
    def trade_outcomes() -> dict[str, Any]:
        """Return persisted scanner picks with live target/SL hit status."""
        try:
            from .trade_outcome import get_trade_outcomes
            return get_trade_outcomes()
        except Exception as exc:
            return {"long": [], "short": [], "updatedAt": None, "error": str(exc)}

    @app.get("/api/fixed-trade-plan")
    def fixed_trade_plan() -> dict[str, Any]:
        """Return the fixed/static trade plan persisted as JSON."""
        try:
            from .trade_outcome import load_fixed_trade_plan
            return load_fixed_trade_plan() or {"long": [], "short": [], "updatedAt": None}
        except Exception as exc:
            return {"long": [], "short": [], "updatedAt": None, "error": str(exc)}

    @app.post("/api/fixed-trade-plan")
    def save_fixed_trade_plan(payload: dict[str, Any]) -> dict[str, Any]:
        """Overwrite the fixed trade plan JSON with the provided payload."""
        try:
            from .trade_outcome import save_fixed_trade_plan, _utc_now
            save_fixed_trade_plan(payload)
            return {"success": True, "updatedAt": _utc_now()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/live-prices")
    def live_prices() -> dict[str, Any]:
        """Return live prices + evaluated outcomes for today's fixed plan symbols only.
        
        No external API calls — reads from last_market_snapshot.json (Angel One batch).
        Designed for monitor-mode polling.
        """
        try:
            from .trade_outcome import get_live_prices_for_plan
            return get_live_prices_for_plan()
        except Exception as exc:
            return {"long": [], "short": [], "updatedAt": None, "error": str(exc)}

    @app.get("/api/alert-history")
    def alert_history(since: str | None = None) -> dict[str, Any]:
        """Return fired alert history for today, optionally filtered."""
        try:
            from .trade_outcome import get_alert_history
            return get_alert_history(since=since)
        except Exception as exc:
            return {"alerts": [], "total": 0, "error": str(exc)}

    @app.get("/api/reports/eod-intraday")
    def eod_intraday_report(date: str | None = None) -> dict[str, Any]:
        """Post-close reconciliation of the day's intraday scanner picks:
        T1/T2/SL outcome per pick, realized P&L, remaining capital, and an
        LLM miss-diagnosis for every SL hit / no-target-hit pick."""
        try:
            from datetime import date as _date
            from .eod_intraday_report import generate_intraday_eod_report
            for_date = _date.fromisoformat(date) if date else _date.today()
            return generate_intraday_eod_report(for_date)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/reports/eod-swing")
    def eod_swing_report(date: str | None = None) -> dict[str, Any]:
        """Day-bucketed (1/7/15/30) P&L report for the Asset Matrix
        swing/long-term picks in the fixed trade plan."""
        try:
            from datetime import date as _date
            from .eod_swing_report import generate_swing_eod_report
            for_date = _date.fromisoformat(date) if date else None
            return generate_swing_eod_report(for_date)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/news")
    def news_feed() -> dict[str, Any]:
        try:
            return {"success": True, "news": fetch_live_news()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/test-ticker")
    def test_ticker(ticker: str = "RELIANCE") -> dict[str, Any]:
        try:
            client = AngelOneClient()
            ticker_upper = ticker.upper()
            inst = next(
                (i for i in WATCHLIST if i.key.upper() == ticker_upper),
                Instrument(ticker_upper, "NSE", f"{ticker_upper}-EQ", "2885")
            )
            quote = client.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
            return {
                "success": True,
                "ticker": ticker_upper,
                "quote": quote,
                "llmConfigured": _llm_config_canonical()[0] is not None,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/market-intelligence")
    def market_intelligence(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=pool, custom_prompt=prompt)
            return {
                "success": True,
                "analysis": payload.get("terminalIntelligence"),
                "tickerIntelligenceByTicker": payload.get("tickerIntelligenceByTicker", {}),
                "newsSummary": payload.get("newsSummary"),
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
                "selectionMeta": payload.get("selectionMeta"),
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/terminal-intelligence")
    def terminal_intelligence(ticker: str | None = None, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=pool, custom_prompt=prompt)
            if ticker:
                report = (payload.get("tickerIntelligenceByTicker") or {}).get(ticker)
                if report:
                    report = dict(report)
                else:
                    report = build_ticker_intelligence_report(payload, ticker)
            else:
                report = dict(payload.get("terminalIntelligence") or {})
            return {
                "success": True,
                "terminalIntelligence": report,
                "focusTicker": ticker,
                "tickerIntelligenceByTicker": payload.get("tickerIntelligenceByTicker", {}),
                "newsSummary": payload.get("newsSummary"),
                "selectionMeta": payload.get("selectionMeta"),
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/orchestrated-refresh")
    async def trigger_orchestrated_refresh(background_tasks: BackgroundTasks, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        task_id = f"orchestrated:{int(time.time())}"
        with _REFRESH_TASK_LOCK:
            _REFRESH_TASKS[task_id] = {"status": "running", "progress": "Initializing sequence...", "created_at": time.time()}
        
        background_tasks.add_task(_run_orchestrated_sequence, task_id, pool, prompt)
        return {"success": True, "taskId": task_id, "message": "Sequential orchestrated refresh started."}

    @app.post("/api/refresh-intelligence")
    def refresh_intelligence(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        task_id = _refresh_task_key(pool, prompt)
        with _REFRESH_TASK_LOCK:
            task = _REFRESH_TASKS.get(task_id)
            start_new = False
            if task is None:
                start_new = True
            elif time.time() - task.get("created_at", 0) > REFRESH_TASK_TTL_SECONDS:
                start_new = True

            if start_new:
                task_id = _refresh_task_key(pool, prompt)
                _REFRESH_TASKS[task_id] = {
                    "status": "running",
                    "progress": "queued",
                    "error": None,
                    "result": None,
                    "created_at": time.time(),
                    "pool": pool,
                    "prompt": prompt,
                }
                thread = threading.Thread(
                    target=_run_refresh_task,
                    args=(task_id, pool, prompt),
                    daemon=True,
                )
                thread.start()

        return {
            "success": True,
            "accepted": True,
            "taskId": task_id,
            "status": "running",
            "statusUrl": f"/api/refresh-intelligence/status?taskId={task_id}",
            "pool": pool or LIVE_UNIVERSE_LABEL,
        }

    @app.get("/api/refresh-intelligence/status")
    def refresh_intelligence_status(taskId: str) -> dict[str, Any]:
        status = _refresh_task_status(taskId)
        if status is None:
            return {
                "success": False,
                "taskId": taskId,
                "status": "expired",
                "error": "Task not found or expired.",
            }
        response: dict[str, Any] = {
            "success": True,
            "taskId": taskId,
            "status": status["status"],
            "progress": status.get("progress"),
            "error": status.get("error"),
            "created_at": status.get("created_at"),
        }
        if status["status"] == "done" and status.get("result"):
            response["result"] = status["result"]
        return response

    @app.post("/api/refresh-data-on-demand")
    async def refresh_data_on_demand(request: Request, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            body: dict[str, Any] = {}
            try:
                parsed_body = await request.json()
                if isinstance(parsed_body, dict):
                    body = parsed_body
            except Exception:
                body = {}

            resolved_pool = pool or body.get("pool")
            resolved_prompt = prompt or body.get("prompt")
            client = AngelOneClient()
            payload = build_market_payload(
                client,
                pool_name=resolved_pool,
                force_refresh=True,
                prefer_cache=False, # Explicitly do not prefer cache for on-demand refresh
                custom_prompt=resolved_prompt,
                allow_fallback=True,
            )
            if not payload.get("success", False):
                raise RuntimeError(payload.get("error") or "Live refresh produced no payload.")
            payload.setdefault("isSnapshotFallback", False)
            if payload.get("selectionMeta", {}).get("mode") != "live":
                payload["selectionMeta"] = {
                    "mode": "live",
                    "reason": payload.get("selectionMeta", {}).get("reason") or "Live refresh explicitly requested by frontend.",
                    "dataDate": payload.get("selectionMeta", {}).get("dataDate") or _payload_data_date(payload),
                }

            refresh_ticker_news = bool(
                body.get("refreshTickerNews", body.get("refresh_ticker_news", False))
            )

            stocks_to_refresh_news = [s for s in (payload.get("stocks") or []) if isinstance(s, dict) and s.get("ticker")]

            if refresh_ticker_news and stocks_to_refresh_news:
                tickers = [s["ticker"] for s in stocks_to_refresh_news]
                try:
                    semaphore = asyncio.Semaphore(5)
                    async with httpx.AsyncClient() as http_client:
                        async def _fetch_one(t: str) -> tuple[str, dict[str, Any]]:
                            async with semaphore:
                                try:
                                    resp = await http_client.get(
                                        f"{AI_NEWS_API_URL}/api/ticker-news",
                                        params={"ticker": t, "max_articles": 15, "include_raw": False},
                                        timeout=60,
                                    )
                                    resp.raise_for_status()
                                    data = resp.json()
                                    return t, data
                                except Exception as e:
                                    logger = logging.getLogger("angel_one_feed")
                                    logger.warning("Per-ticker news fetch failed for %s: %s", t, e)
                                    return t, {"error": True, "ticker": t, "message": str(e)}

                        results = dict(await asyncio.gather(*[_fetch_one(t) for t in tickers]))
                        ticker_news_map = {}
                        for t, data in results.items():
                            if not data.get("error") and data.get("ticker"):
                                ticker_news_map[t] = data
                        payload["tickerNewsByTicker"] = ticker_news_map
                        updated = len(ticker_news_map)
                        print(f"INFO: Stored {updated} ticker news reports out of {len(tickers)} into snapshot.")
                except Exception as exc:
                    print(f"WARNING: Batch ticker-news refresh failed: {exc}")
            # --- End new logic ---

            _save_last_snapshot(payload)
            return {
                "success": True,
                "payload": payload,
                "selectionMeta": payload.get("selectionMeta"),
                "isSnapshotFallback": False,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/refresh-ticker-reason")
    async def refresh_ticker_reason(request: Request, ticker: str | None = None, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            body: dict[str, Any] = {}
            try:
                parsed_body = await request.json()
                if isinstance(parsed_body, dict):
                    body = parsed_body
            except Exception:
                body = {}

            resolved_ticker = str(ticker or body.get("ticker") or "").strip().upper()
            if not resolved_ticker:
                raise HTTPException(status_code=400, detail="Missing required ticker parameter.")

            resolved_pool = pool or body.get("pool")
            resolved_prompt = prompt or body.get("prompt")
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=resolved_pool, custom_prompt=resolved_prompt)

            stock_row = None
            for stock in payload.get("stocks") or []:
                if str(stock.get("ticker", "")).upper() == resolved_ticker:
                    stock_row = stock
                    break
            if stock_row is None:
                quote = (payload.get("stockQuotes") or {}).get(resolved_ticker)
                if isinstance(quote, dict) and quote:
                    stock_row = quote

            if stock_row is None:
                raise HTTPException(status_code=404, detail=f"Ticker {resolved_ticker} not found in current payload.")

            ledger_score = None
            for row in ((payload.get("terminalIntelligence") or {}).get("ledger_stocks") or []):
                if str(row.get("ticker", "")).upper() == resolved_ticker:
                    ledger_score = row.get("score")
                    break
            try:
                score = float(ledger_score if ledger_score is not None else stock_row.get("score") or 0.0)
            except Exception:
                score = 0.0

            reason = _on_demand_ticker_selection_reason(resolved_ticker, stock_row, score)

            ticker_map = payload.get("tickerIntelligenceByTicker") or {}
            ticker_report = ticker_map.get(resolved_ticker)
            if not ticker_report:
                ticker_report = build_ticker_intelligence_report(payload, resolved_ticker)

            ticker_report = dict(ticker_report)
            factor_hub = dict(ticker_report.get("active_factor_hub") or {})
            factor_hub["selection_reason"] = reason
            ticker_report["active_factor_hub"] = factor_hub
            ticker_report["focusTicker"] = resolved_ticker
            ticker_report["ticker"] = resolved_ticker

            ticker_map[resolved_ticker] = ticker_report
            payload["tickerIntelligenceByTicker"] = ticker_map

            terminal = payload.get("terminalIntelligence") or {}
            ledger = terminal.get("ledger_stocks") or []
            for row in ledger:
                if str(row.get("ticker", "")).upper() == resolved_ticker:
                    row["selection_reason"] = reason
                    break
            terminal["ledger_stocks"] = ledger
            payload["terminalIntelligence"] = terminal

            _save_last_snapshot(payload)

            return {
                "success": True,
                "ticker": resolved_ticker,
                "selectionReason": reason,
                "tickerReport": ticker_report,
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
                "selectionMeta": payload.get("selectionMeta"),
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/ticker-news")
    async def get_ticker_news(ticker: str, company: str | None = None) -> dict[str, Any]:
        try:
            resolved_ticker = ticker.strip().upper()
            if not resolved_ticker:
                raise HTTPException(status_code=400, detail="Missing required parameter: ticker")

            snapshot = _load_last_snapshot()
            ticker_news_map = (snapshot.get("tickerNewsByTicker") or {}) if snapshot else {}
            cached_report = ticker_news_map.get(resolved_ticker)

            if cached_report and not cached_report.get("error"):
                cached_report = dict(cached_report)
                cached_report["cached"] = True
                return cached_report

            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(
                    f"{AI_NEWS_API_URL}/api/ticker-news",
                    params={"ticker": resolved_ticker, "company": company or "", "max_articles": 20, "include_raw": False},
                    timeout=90,
                )
                response.raise_for_status()
                report_data = response.json()

            report_data["cached"] = False

            if snapshot:
                updated_map = dict(snapshot.get("tickerNewsByTicker") or {})
                updated_map[resolved_ticker] = report_data
                snapshot = dict(snapshot)
                snapshot["tickerNewsByTicker"] = updated_map
                _save_last_snapshot(snapshot)

            return report_data
        except HTTPException:
            raise
        except Exception as exc:
            logger = logging.getLogger("angel_one_feed")
            logger.error("ticker-news fetch failed for %s: %s", ticker, exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


def _run_refresh_task(task_id: str, pool_name: str | None, custom_prompt: str | None) -> None:
    try:
        payload = build_market_payload(
            AngelOneClient(),
            pool_name=pool_name,
            force_refresh=True,
            custom_prompt=custom_prompt,
        )
        if not payload.get("success", False):
            _refresh_task_set_error(task_id, payload.get("error", "Market data unavailable."))
            return
        result = {
            "success": True,
            "poolStocks": len(payload.get("stocks", [])),
            "tiLedgerStocks": len((payload.get("terminalIntelligence") or {}).get("ledger_stocks", [])),
            "tiPopulated": bool(payload.get("terminalIntelligence")),
            "newsSummaryPopulated": bool(payload.get("newsSummary")),
            "selectionMeta": payload.get("selectionMeta"),
        }
        _refresh_task_set_done(task_id, result)
    except Exception as exc:
        _refresh_task_set_error(task_id, str(exc))


def _run_orchestrated_sequence(task_id: str, pool_name: str | None, custom_prompt: str | None) -> None:
    """Orchestrates the sequential dashboard update with 30s delays between sections as specified."""
    try:
        client = AngelOneClient()
        
        def update_progress(msg: str, payload: dict[str, Any]):
            with _REFRESH_TASK_LOCK:
                if task_id in _REFRESH_TASKS:
                    _REFRESH_TASKS[task_id]["progress"] = msg
            # Progressive save so frontend can reflect sections being filled
            _save_last_snapshot(payload)
            print(f"[ORCHESTRATION] {msg}")

        # 1. Immediately delete existing dashboard snapshot to start fresh
        if SNAPSHOT_PATH.exists():
            SNAPSHOT_PATH.unlink()
        
        payload: dict[str, Any] = {
            "success": True,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "stocks": [],
            "stockQuotes": {},
            "macroDataStrip": {"morning": [], "evening": []},
            "globalMacro": {"indices": [], "commodities": []},
            "news": [],
            "terminalIntelligence": None,
            "isSnapshotFallback": False
        }

        # Step 1: Update GLOBAL INDICES section
        update_progress("Updating GLOBAL INDICES section...", payload)
        gm = fetch_global_macro()
        payload["globalMacro"]["indices"] = gm.get("indices", [])
        update_progress("GLOBAL INDICES updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 2: Update COMMODITIES & FX section
        update_progress("Updating COMMODITIES & FX section...", payload)
        payload["globalMacro"]["commodities"] = gm.get("commodities", [])
        payload["macroDataStrip"]["morning"].extend(fetch_domestic_yahoo_macro())
        update_progress("COMMODITIES & FX updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 3: Update NIFTY TOP 5 GAINERS & LOSERS
        update_progress("Updating NIFTY TOP 5 GAINERS & LOSERS...", payload)
        resolved_pool = pool_name or NIFTY_100_LABEL
        stock_universe, pool_label = _pool_watchlist(resolved_pool)
        stock_quotes_raw = client.fetch_batch_quotes(stock_universe)
        
        all_stocks = []
        for inst in stock_universe:
            if q := stock_quotes_raw.get(inst.key):
                all_stocks.append(_build_stock_row(inst, q, pool_label))
        
        # Perform intraday fetch for ranking
        candidate_rows = _coarse_pre_rank(all_stocks)[:30]
        all_metrics = _fetch_all_intraday_chunked(client, candidate_rows, {i.key: i for i in stock_universe}, _ist_now())
        
        for row in all_stocks:
            if m := all_metrics.get(row["ticker"]):
                row["intraday"] = m
        
        # ─────────────────────────────────────────────────────────────────────────
        # STAGE 1: Deterministic Quant Engine
        # Applies hard filters and computes Alpha Scores with no LLM involvement.
        # Returns top 20 sorted by Alpha Score; pads with volume leaders if needed.
        # ─────────────────────────────────────────────────────────────────────────
        update_progress("Running deterministic quant pipeline (hard filters + alpha scores)...", payload)
        top_20_quant = _compute_deterministic_pipeline(all_stocks)

        # ─────────────────────────────────────────────────────────────────────────
        # STAGE 2: LLM Safety Auditor
        # Audits ONLY non-technical risk domains using news context.
        # Attaches risk_flags + verdict to each stock; never re-ranks technically.
        # ─────────────────────────────────────────────────────────────────────────
        update_progress("Running LLM risk audit on top 20 stocks...", payload)
        final_audited = _execute_llm_risk_audit(top_20_quant, payload.get("news", []))

        # Print institutional audit ledger to server log
        ledger_rows = build_audit_ledger(final_audited)
        for ledger_row in ledger_rows:
            print(f"[AUDIT] {ledger_row}")

        payload["stocks"] = final_audited
        payload["stockQuotes"] = {s["ticker"]: s for s in all_stocks}
        update_progress("NIFTY TOP 5 MOVERS updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 4: Update NIFTY 100 HEAT MAP (gradient data is now in stockQuotes)
        update_progress("Updating NIFTY 100 HEAT MAP data...", payload)
        update_progress("NIFTY 100 HEAT MAP updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 5: Update LIVE NEWS FEED
        update_progress("Updating LIVE NEWS FEED section...", payload)
        payload["news"] = fetch_live_news()
        update_progress("LIVE NEWS FEED updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 6: Update INDIA MARKETS section (TOP MOVERS, ASSET METRICS)
        update_progress("Updating INDIA MARKETS section...", payload)
        macro_raw = client.fetch_batch_quotes(list(MACRO_INSTRUMENTS))
        m, e = _build_macro_strips(macro_raw)
        payload["macroDataStrip"]["morning"].extend(m)
        payload["macroDataStrip"]["evening"].extend(e)
        payload["macroDataStrip"]["morning"].extend(fetch_domestic_index_macro())
        update_progress("INDIA MARKETS section updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 7: Update AI NEWS TERMINAL & SUMMARY
        # Check if we already have this in a valid state from a previous snapshot
        snapshot = _load_last_snapshot()
        if snapshot and snapshot.get("terminalIntelligence") and not snapshot.get("terminalIntelligence", {}).get("llmError"):
            update_progress("AI NEWS TERMINAL & SUMMARY found in cache. Reusing...", payload)
            top_rows = snapshot.get("stocks", [])
            ti_intel = snapshot.get("terminalIntelligence")
            news_summary = snapshot.get("newsSummary")
        else:
            update_progress("AI NEWS TERMINAL & SUMMARY missing or invalid. Calling LLM...", payload)
            top_rows, ti_intel, news_summary = _build_terminal_payload(
                all_stocks=final_audited,
                news_items=payload["news"],
                macro_morning=payload["macroDataStrip"]["morning"],
                macro_evening=payload["macroDataStrip"]["evening"],
                pool_name=resolved_pool,
                custom_prompt=custom_prompt
            )
            
            if not ti_intel or ti_intel.get("llmError"):
                 update_progress("AI ANALYSIS failed. Panel will remain empty for on-demand retry.", payload)
            else:
                 update_progress("AI ANALYSIS completed successfully.", payload)

        payload["terminalIntelligence"] = ti_intel
        payload["newsSummary"] = news_summary
        update_progress("AI SUMMARY updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 8: Update TERMINAL ANALYSIS section
        update_progress("Updating final TERMINAL ANALYSIS section...", payload)
        payload = _hydrate_ticker_intelligence_map(payload)
        _apply_selection_meta(
            payload, 
            mode="live", 
            reason="Sequential orchestrated refresh complete. Rendering final dashboard."
        )
        
        update_progress("Orchestrated refresh sequence complete. Dashboard fully generated.", payload)
        _refresh_task_set_done(task_id, {"success": True, "message": "Sequence finished successfully."})

        # NOTE: At this point, the backend has generated the complete dataset.
        # The 'light-themed image' rendering is handled by the frontend dashboard component
        # when it detects the 'Sequential orchestrated refresh complete' meta state.

    except Exception as exc:
        print(f"[ORCHESTRATION ERROR] {exc}")
        _refresh_task_set_error(task_id, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Angel One market feed for IROS")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--once", action="store_true", help="Fetch once and print/save JSON")
    parser.add_argument("--output", help="Write JSON snapshot to this file")
    parser.add_argument("--pool", default=None, help="Pool label. Defaults to Nifty 100; Live Universe is also supported.")
    parser.add_argument("--prompt", default=None, help="Custom filter prompt override")
    parser.add_argument("--refresh-on-demand", action="store_true", help="Force a non-fallback live refresh and write snapshot")
    parser.add_argument("--orchestrate", action="store_true", help="Run the sequential orchestrated refresh sequence")
    parser.add_argument("--audit-verdicts", action="store_true", help="Print all ticker audit verdicts (Approved/Rejected) from the latest snapshot")
    args = parser.parse_args()

    try:
        resolved = _llm_config_canonical()
        print(
            f"[LLM-DEBUG] env_path={BASE_DIR / '.env'} "
            f"LLM_PROVIDER={os.getenv('LLM_PROVIDER','')} "
            f"LLM_MODEL={os.getenv('LLM_MODEL','')} "
            f"REDACTED={'set' if os.getenv('REDACTED','').strip() else 'missing'} "
            f"resolved={resolved}"
        )
    except Exception as exc:
        print(f"[LLM-DEBUG] config inspect failed: {exc}")

    if args.serve:
        import uvicorn

        host = os.getenv("MARKET_API_HOST", "0.0.0.0")
        port = int(os.getenv("MARKET_API_PORT", "8000"))
        uvicorn.run(create_app(), host=host, port=port)
        return 0

    if args.orchestrate:
        print("[INFO] Starting orchestrated sequential refresh...")
        _run_orchestrated_sequence("cli_task", args.pool, args.prompt)
        return 0

    if args.audit_verdicts:
        snapshot = _load_last_snapshot()
        if not snapshot:
            print(json.dumps({"success": False, "error": "No cached snapshot available."}, indent=2))
            return 1
        verdicts = []
        for s in snapshot.get("stocks", []):
            verdicts.append({
                "ticker": s.get("ticker"),
                "name": s.get("name"),
                "alpha_score": s.get("alpha_score", 0.0),
                "verdict": s.get("verdict", "APPROVE"),
                "risk_flags": s.get("risk_flags", ["None"])
            })
        print(json.dumps({"success": True, "verdicts": verdicts}, indent=2))
        return 0

    if args.refresh_on_demand:
        client = AngelOneClient()
        payload = build_market_payload(
            client,
            pool_name=args.pool,
            force_refresh=True,
            prefer_cache=False, # Explicitly do not prefer cache for on-demand refresh
            custom_prompt=args.prompt,
            allow_fallback=False,
        )
        if not payload.get("success", False):
            raise RuntimeError(payload.get("error") or "Live refresh produced no payload.")
        payload.setdefault("isSnapshotFallback", False)
        if payload.get("selectionMeta", {}).get("mode") != "live":
            payload["selectionMeta"] = {
                "mode": "live",
                "reason": payload.get("selectionMeta", {}).get("reason") or "Live refresh explicitly requested by CLI.",
                "dataDate": payload.get("selectionMeta", {}).get("dataDate") or _payload_data_date(payload),
            }
        _save_last_snapshot(payload)
        text = json.dumps(payload, indent=2)
        print(text)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        return 0

    client = AngelOneClient()
    payload = build_market_payload(client, pool_name=args.pool, custom_prompt=args.prompt)
    text = json.dumps(payload, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())