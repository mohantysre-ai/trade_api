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

# Load environment variables from the main backend .env (which contains GEMINI_API_KEY)
# so the AI News server can use LLM-powered summaries instead of rule-based fallback.
_env_path = Path(__file__).resolve().parent.parent.parent / "backend" / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
        logger = logging.getLogger("ai_news_server")
        logger.info("Loaded environment from %s", _env_path)
    except ImportError:
        pass
elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
    pass
else:
    logger = logging.getLogger("ai_news_server")
    logger.warning("No .env found at %s — LLM summarization disabled", _env_path)

try:
    from ai_ticker_news import generate_ticker_news_report
except ImportError:
    # Fallback if running from project root
    from backend.ai_ticker_news import generate_ticker_news_report

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
# Cache layer to avoid re-scraping the same ticker too often
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[str, dict]] = {}  # ticker -> (generated_at, report)
_CACHE_TTL_SECONDS = 600  # 10 minutes


def _get_cached(ticker: str) -> dict | None:
    entry = _cache.get(ticker.upper())
    if not entry:
        return None
    from datetime import datetime, timezone
    generated_at = entry[0]
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(generated_at.replace("Z", "+00:00"))).total_seconds()
    if age > _CACHE_TTL_SECONDS:
        del _cache[ticker.upper()]
        return None
    return entry[1]


def _set_cache(ticker: str, report_dict: dict):
    from datetime import datetime, timezone
    _cache[ticker.upper()] = (report_dict.get("generated_at", datetime.now(timezone.utc).isoformat()), report_dict)


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
                    _set_cache(t, report_dict)
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
        report = await generate_ticker_news_report(
            ticker=ticker,
            company_name=company,
            max_articles=max_articles,
            include_raw=include_raw,
        )
        report_dict = report.to_dict()

        from datetime import datetime, timezone
        generated_at = report_dict.get("generated_at", datetime.now(timezone.utc).isoformat())
        report_dict["generated_at"] = generated_at

        _set_cache(ticker, report_dict)
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