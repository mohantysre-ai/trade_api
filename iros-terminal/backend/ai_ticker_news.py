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
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx
import requests
from bs4 import BeautifulSoup

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


async def scrape_rss_feeds(ticker: str, session: httpx.AsyncClient) -> list[TickerNewsArticle]:
    """Scrape RSS feeds from financial news aggregators."""
    articles: list[TickerNewsArticle] = []
    company = _company_name(ticker)
    rss_urls = [
        f"https://news.google.com/rss/search?q={quote_plus(f'{company} {ticker} stock market')}&hl=en-IN&gl=IN&ceid=IN:en",
        f"https://feeds.content.dowjones.io/public/rss/mw_topstories",
    ]

    for rss_url in rss_urls:
        try:
            resp = await session.get(rss_url, headers=HEADERS, timeout=15.0)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "xml")
            for item in soup.select("item"):
                title = item.find("title")
                link = item.find("link")
                desc = item.find("description")
                pub_date = item.find("pubDate")

                if not title or not link:
                    continue
                title_text = title.get_text(strip=True)
                if len(title_text) < 15:
                    continue

                articles.append(TickerNewsArticle(
                    title=title_text[:300],
                    source="Google News RSS",
                    url=(link.get_text(strip=True) or link.get("href", ""))[:500],
                    summary=(desc.get_text(strip=True) if desc else "")[:500],
                    published_at=(pub_date.get_text(strip=True) if pub_date else datetime.now(timezone.utc).isoformat()),
                ))
                if len(articles) >= 10:
                    break
        except Exception as e:
            logger.warning("RSS scrape failed: %s", e)

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
            scrape_rss_feeds(ticker, session),
            scrape_nse_announcements(ticker, session),
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


async def summarize_with_gemini(ticker: str, company: str, articles: list[TickerNewsArticle]) -> dict:
    """Use Google Gemini to produce a structured news summary with model fallback on 429."""
    gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not gemini_api_key:
        logger.warning("No GEMINI_API_KEY or GOOGLE_API_KEY set — falling back to rule-based summary")
        return _rule_based_summary(ticker, company, articles)

    try:
        from google import genai
    except ImportError:
        logger.warning("google-genai not installed — falling back to rule-based summary")
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

            result = json.loads(text)
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
) -> AITickerNewsReport:
    """Full pipeline: scrape → dedup → LLM summarize → return structured report."""
    ticker = ticker.upper().strip()
    company = company_name or _company_name(ticker)

    # Step 1: Scrape
    articles = await scrape_all_sources(ticker)
    if len(articles) > max_articles:
        articles = articles[:max_articles]

    # Step 2: LLM Summarize
    llm_result = summarize_with_gemini(ticker, company, articles)

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