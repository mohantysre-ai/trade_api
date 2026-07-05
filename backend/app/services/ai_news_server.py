"""
FastAPI HTTP server for AI Ticker News Scraper
===============================================
Exposes a REST endpoint that scrapes financial news for a ticker
and returns LLM-structured summaries.

Run:  python backend/ai_news_server.py  (starts on port 8001)
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# Add parent path so we can import ai_ticker_news
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables from the main backend .env (which contains REDACTED)
# so the AI News server can use LLM-powered summaries instead of rule-based fallback.
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
        logger = logging.getLogger("ai_news_server")
        logger.info("Loaded environment from %s", _env_path)
    except ImportError:
        pass
elif os.environ.get("REDACTED") or os.environ.get("GOOGLE_API_KEY"):
    pass
else:
    logger = logging.getLogger("ai_news_server")
    logger.warning("No .env found at %s — LLM summarization disabled", _env_path)

try:
    from .ai_ticker_news import generate_ticker_news_report, PulseNewsCollector
except ImportError:
    # Fallback if running from project root
    from app.services.ai_ticker_news import generate_ticker_news_report, PulseNewsCollector

try:
    from ..utils.symbols import WATCHLIST
except ImportError:
    from app.utils.symbols import WATCHLIST

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_news_server")

try:
    from fastapi import FastAPI, Query
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    logger.error("FastAPI not installed. Run: pip install fastapi uvicorn")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Cache layer — backed by trade_api_snapshot.json -> tickerNewsByTicker
# ---------------------------------------------------------------------------

# Re-use the same snapshot-backed cache as ai_ticker_news.
# Import here to avoid circular imports; the module-level _load_llm_cache()
# in ai_ticker_news.py populates this at import time.
from app.services.ai_ticker_news import get_cached_summary, set_cached_summary  # noqa: E402

_CACHE_TTL_SECONDS = 600  # 10 minutes (server-side memory TTL for fast path)


def _get_cached(ticker: str, force_refresh: bool = False) -> dict | None:
    """
    Try snapshot cache first (24h TTL enforced inside ai_ticker_news).
    If force_refresh=True, always return None to trigger a fresh LLM call.
    """
    if force_refresh:
        return None
    try:
        # We only have the ticker here, not articles, so pass empty list / 0
        # and let get_cached_summary handle the lookup by key alone.
        entry = get_cached_summary(ticker, [], 0, force_refresh=False)
        if entry:
            return entry
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AI News Server starting on port 8001")
    yield
    logger.info("AI News Server shutting down")


app = FastAPI(
    title="AI Ticker News Server",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-ticker-news"}


def _check_ticker_news_fresh(ticker: str) -> dict:
    cached = _get_cached(ticker)
    if cached and not cached.get("error"):
        cached["cached"] = True
        return {"ticker": ticker.upper(), "cached": True, "error": False}
    return {"ticker": ticker.upper(), "cached": False, "error": False, "needs_refresh": True}


@app.post("/api/ticker-news/batch-check")
async def ticker_news_batch_check(payload: dict[str, Any]):  # type: ignore[misc]
    tickers = payload.get("tickers", [])
    max_articles = payload.get("max_articles", 50)
    include_raw = payload.get("include_raw", False)

    statuses = []
    for ticker in tickers:
        if not ticker:
            continue
        cached = _get_cached(ticker)
        if cached and not cached.get("error"):
            entry = dict(cached)
            entry["cached"] = True
            entry["needs_refresh"] = False
            statuses.append(entry)
        else:
            statuses.append({"ticker": ticker.upper(), "cached": False, "needs_refresh": True})

    missing = [item["ticker"] for item in statuses if item.get("needs_refresh")]

    fetched: dict[str, Any] = {}
    if missing:
        semaphore = asyncio.Semaphore(5)

        async def _fetch_one(t: str) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                try:
                    report = await generate_ticker_news_report(
                        ticker=t,
                        company_name=None,
                        max_articles=max_articles,
                        include_raw=include_raw,
                    )
                    report_dict = report.to_dict()
                    set_cached_summary(t, report_dict)
                    report_dict["cached"] = False
                    report_dict["needs_refresh"] = False
                    return t.upper(), report_dict
                except Exception as e:
                    logger.error("Failed in batch fetch for %s: %s", t, e)
                    return (
                        t.upper(),
                        {
                            "error": True,
                            "ticker": t.upper(),
                            "message": str(e),
                            "needs_refresh": False,
                            "generated_at": __import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc
                            ).isoformat(),
                        },
                    )

        fetched = dict(await asyncio.gather(*[_fetch_one(t) for t in missing]))

    results = []
    for item in statuses:
        ticker = item["ticker"]
        data = fetched.get(ticker, item)
        results.append(data)

    return {"results": results}


@app.get("/api/ticker-news")
async def ticker_news(
    ticker: str = Query(..., description="Stock ticker symbol (e.g., RELIANCE, TCS, INFY)"),
    company: str | None = Query(None, description="Company name (optional)"),
    max_articles: int = Query(50, description="Max articles to analyze"),
    include_raw: bool = Query(False, description="Include raw article list"),
    force_refresh: bool = Query(False, description="Bypass cache"),
):
    """Scrape news for a ticker and return LLM-structured summary."""
    # Check cache
    if not force_refresh:
        cached = _get_cached(ticker)
        if cached:
            logger.info("Returning cached report for %s", ticker)
            cached["cached"] = True
            return cached

    try:
        try:
            report = await generate_ticker_news_report(
                ticker=ticker,
                company_name=company,
                max_articles=max_articles,
                include_raw=include_raw,
                force_refresh=force_refresh,
            )
        except TypeError as exc:
            if "multiple values for keyword argument 'generated_at'" not in str(exc):
                raise
            logger.warning("Retrying report generation for %s without cache after generated_at collision", ticker)
            report = await generate_ticker_news_report(
                ticker=ticker,
                company_name=company,
                max_articles=max_articles,
                include_raw=include_raw,
                force_refresh=True,
            )
        report_dict = report.to_dict()

        from datetime import datetime, timezone
        generated_at = report_dict.get("generated_at", datetime.now(timezone.utc).isoformat())
        report_dict["generated_at"] = generated_at

        # Cache is automatically persisted inside generate_ticker_news_report via set_cached_summary
        report_dict["cached"] = False

        return {
            **report_dict,
            "generated_at": generated_at,
            "generated_by": "backend.ai_ticker_news.generate_ticker_news_report",
        }
    except Exception as e:
        logger.error("Failed to generate report for %s: %s", ticker, e)
        return {
            "error": True,
            "ticker": ticker.upper(),
            "message": str(e),
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "company_name": company or ticker.upper(),
            "articles_scraped": 0,
            "articles_after_dedup": 0,
            "insider_activity": "Error fetching news.",
            "institutional_activity": "Error fetching news.",
            "order_book_block_deals": "Error fetching news.",
            "future_expansion_capex": "Error fetching news.",
            "auditor_changes": "Error fetching news.",
            "dividend_news": "Error fetching news.",
            "new_orders_contracts": "Error fetching news.",
            "earnings_results": "Error fetching news.",
            "management_changes": "Error fetching news.",
            "regulatory_filings": "Error fetching news.",
            "sentiment_overall": "Neutral",
            "risk_flags": "Scraper error — check server logs.",
            "summary_headline": f"Failed to fetch news for {ticker}.",
            "error_detail": str(e),
        }


# ---------------------------------------------------------------------------
# Pulse feed — general market news for NewsWire.jsx (not per-ticker)
# ---------------------------------------------------------------------------
# NewsWire.jsx was previously rendering a hardcoded SEED_STORIES array.
# This endpoint replaces that with real Zerodha Pulse headlines, reusing
# the same PulseNewsCollector the per-ticker report already relies on
# (symbols=None => no ticker filter => general market feed instead of
# one company's news).
#
# Sentiment/impact here are RULE-BASED (keyword scoring), not an LLM
# call per headline. That's a deliberate choice: NewsWire polls this
# endpoint every ~30s for a live-feed feel, and running Gemini on every
# headline on every poll would be slow and burn quota for what's meant
# to be a fast scanning tape. The per-ticker /api/ticker-news endpoint
# above already does the deeper LLM-structured analysis when the user
# drills into a specific stock -- this feed is the fast triage layer,
# not a replacement for it.

_BULLISH_WORDS = {
    "beats": 30, "beat estimates": 35, "surges": 30, "surge": 28, "rallies": 28,
    "jumps": 25, "gains": 18, "upgrade": 30, "upgraded": 30, "wins order": 32,
    "wins contract": 32, "record profit": 35, "record high": 28, "approval": 25,
    "nod": 20, "raises guidance": 32, "raised guidance": 32, "outperform": 25,
    "buyback": 20, "expansion": 15, "strong demand": 22, "beats street": 32,
    "profit jumps": 30, "profit rises": 25, "revenue growth": 18, "bullish": 22,
}
_BEARISH_WORDS = {
    "tumbles": 30, "crashes": 35, "plunges": 32, "slides": 22, "slips": 18,
    "downgrade": 30, "downgraded": 30, "misses estimates": 32, "miss estimates": 30,
    "cancellation": 28, "cancels order": 30, "probe": 28, "fraud": 35, "raid": 30,
    "resigns": 22, "resignation": 22, "npa": 22, "slippage": 25, "governance": 15,
    "pledge": 18, "delay": 15, "weak guidance": 28, "cuts guidance": 30,
    "profit falls": 28, "loss widens": 30, "bearish": 22, "sell-off": 25,
    "selloff": 25, "scam": 32,
}

_TICKER_PATTERN_CACHE: dict[str, "re.Pattern"] = {}


def _ticker_regex(sym: str):
    import re as _re
    pat = _TICKER_PATTERN_CACHE.get(sym)
    if pat is None:
        pat = _re.compile(rf"\b{_re.escape(sym)}\b", _re.IGNORECASE)
        _TICKER_PATTERN_CACHE[sym] = pat
    return pat


# Headlines say "HCL Technologies", not "HCLTECH" -- matching WATCHLIST
# ticker symbols alone misses most real-world Pulse headlines. This maps
# common company display names to the WATCHLIST key so extraction
# actually fires. NOT exhaustive -- covers the current WATCHLIST universe
# only; extend as you add instruments. A headline mentioning a company
# not in WATCHLIST or not in this alias map simply won't get a ticker
# chip, same as before -- this narrows the gap, it doesn't close it.
_COMPANY_ALIASES: dict[str, str] = {
    "reliance industries": "RELIANCE", "tata consultancy": "TCS",
    "hcl technologies": "HCLTECH", "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK", "kotak mahindra": "KOTAKBANK",
    "state bank of india": "SBIN", "larsen & toubro": "LT",
    "larsen and toubro": "LT", "bharti airtel": "BHARTIARTL",
    "hindustan unilever": "HINDUNILVR", "maruti suzuki": "MARUTI",
    "bajaj finance": "BAJFINANCE", "bajaj finserv": "BAJAJFINSV",
    "nestle india": "NESTLEIND", "sun pharma": "SUNPHARMA",
    "hindustan aeronautics": "HAL", "bharat electronics": "BEL",
    "coal india": "COALINDIA", "dr reddy": "DRREDDY", "dr. reddy": "DRREDDY",
    "asian paints": "ASIANPAINT", "ultratech cement": "ULTRACEMCO",
    "tech mahindra": "TECHM", "godrej properties": "GODREJPROP",
    "tata elxsi": "TATAELXSI", "power grid": "POWERGRID",
}


def _classify_sentiment(text: str) -> tuple[str, int]:
    """Keyword-weighted sentiment score in [-100, 100]. Returns
    (bucket, score) where bucket is bullish/bearish/neutral."""
    lowered = text.lower()
    score = 0
    for phrase, weight in _BULLISH_WORDS.items():
        if phrase in lowered:
            score += weight
    for phrase, weight in _BEARISH_WORDS.items():
        if phrase in lowered:
            score -= weight
    score = max(-100, min(100, score))
    if score >= 12:
        bucket = "bullish"
    elif score <= -12:
        bucket = "bearish"
    else:
        bucket = "neutral"
    return bucket, score


def _classify_impact(num_tickers: int, score: int) -> str:
    if abs(score) >= 55 or num_tickers >= 3:
        return "high"
    if abs(score) >= 22 or num_tickers >= 1:
        return "medium"
    return "low"


def _load_snapshot_deltas() -> dict[str, float]:
    """Best-effort read of the live snapshot cache written by
    angel_one_feed.py, so ticker chips can show a real intraday delta%
    instead of a placeholder. Returns {} if the snapshot is missing or
    stale-format -- callers must handle empty deltas gracefully."""
    snapshot_path = Path(__file__).resolve().parent / "last_market_snapshot.json"
    deltas: dict[str, float] = {}
    try:
        with open(snapshot_path, "r") as f:
            data = json.load(f)
        quotes = data.get("stockQuotes", {})
        items = quotes.items() if isinstance(quotes, dict) else []
        for sym, q in items:
            raw = str(q.get("delta", "")).replace("%", "").replace("+", "").strip()
            try:
                deltas[sym.upper()] = float(raw)
            except ValueError:
                continue
    except Exception:
        logger.debug("No usable snapshot at %s for pulse-feed ticker deltas", snapshot_path)
    return deltas


def _extract_tickers(headline: str, deltas: dict[str, float]) -> list[dict[str, Any]]:
    found_keys: list[str] = []
    lowered = headline.lower()

    # 1. Raw ticker symbol appearing literally (SBIN, TCS, ITC, etc.)
    for inst in WATCHLIST:
        if _ticker_regex(inst.key).search(headline):
            found_keys.append(inst.key)

    # 2. Full company name appearing instead of the ticker (the common case)
    for alias, key in _COMPANY_ALIASES.items():
        if alias in lowered and key not in found_keys:
            found_keys.append(key)

    hits = [
        {"sym": key, "delta": deltas.get(key.upper(), 0.0)}
        for key in found_keys[:4]
    ]
    return hits


def _clean_time_label(raw: str) -> str:
    """Pulse's scraped timestamp text is whatever was in the nearest
    <span> on the page (often already 'X mins ago' / 'X hours ago' /
    a date). Strip a trailing ' ago' so NewsWire's own '... AGO' suffix
    doesn't double up; fall back to 'recent' if the field is unusable
    (e.g. it grabbed an ISO string or empty text)."""
    if not raw:
        return "recent"
    cleaned = raw.strip()
    if cleaned.lower().endswith(" ago"):
        cleaned = cleaned[: -len(" ago")].strip()
    if len(cleaned) > 24 or "T" in cleaned and ":" in cleaned and "-" in cleaned:
        return "recent"  # looks like a raw ISO timestamp, not a display string
    return cleaned or "recent"


@app.get("/api/pulse-feed")
async def pulse_feed(
    limit: int = Query(30, ge=1, le=50, description="Max stories to return"),
):
    """General market news feed for NewsWire.jsx, sourced from Zerodha
    Pulse via the existing PulseNewsCollector (symbols=None => no
    ticker filter, i.e. the general tape rather than one company)."""
    try:
        collector = PulseNewsCollector()
        articles = await collector.fetch_latest_news(symbols=None)
    except Exception as e:
        logger.error("Pulse feed fetch failed: %s", e)
        return {"stories": [], "count": 0, "error": True, "message": str(e)}

    deltas = _load_snapshot_deltas()
    stories = []
    for a in articles[:limit]:
        sentiment, score = _classify_sentiment(f"{a.title} {a.summary}")
        tickers = _extract_tickers(a.title, deltas)
        impact = _classify_impact(len(tickers), score)
        stories.append({
            "id": f"pulse-{abs(hash(a.url or a.title)) % (10 ** 10)}",
            "time": _clean_time_label(a.published_at),
            "source": a.source,
            "sentiment": sentiment,
            "impact": impact,
            "score": score,
            "headline": a.title,
            "snippet": a.summary,
            "url": a.url,
            "tickers": tickers,
        })

    return {
        "stories": stories,
        "count": len(stories),
        "error": False,
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("AI_NEWS_PORT", "8001"))
    uvicorn.run(
        "ai_news_server:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
    )