import asyncio
from datetime import datetime, timezone

from app.services.ai_ticker_news import (
    NEWS_SCHEMA_VERSION,
    NewsScrapeBundle,
    NewsSourceDiagnostic,
    TickerNewsArticle,
    _article_matches_symbol,
    generate_ticker_news_report,
    scrape_bse_announcements,
    scrape_nse_announcements,
)


class Response:
    def __init__(self, status: int, *, text: str = "", payload=None):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self._payload = payload

    def json(self):
        return self._payload


def test_bse_resolves_exact_symbol_from_peer_search():
    calls = []

    class Session:
        async def get(self, url, **kwargs):
            calls.append((url, kwargs.get("params") or {}))
            if "PeerSmartSearch" in url:
                return Response(200, text="<strong>RELIANCE</strong> INE002A01018 500325")
            return Response(
                200,
                payload={
                    "Table": [
                        {
                            "HEADLINE": "News clarification",
                            "ATTACHMENTNAME": "reliance-clarification.pdf",
                            "NEWS_DT": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S"),
                        }
                    ]
                },
            )

    articles = asyncio.run(scrape_bse_announcements("RELIANCE", Session(), "Reliance Industries"))
    assert len(articles) == 1
    assert articles[0].source == "BSE Announcements"
    assert calls[0][1] == {"Type": "SS", "text": "RELIANCE"}
    assert calls[1][1]["strscrip"] == "500325"


def test_nse_bootstraps_cookie_and_retries_403():
    calls = []
    api_calls = 0

    class Session:
        async def get(self, url, **kwargs):
            nonlocal api_calls
            calls.append(url)
            if "api/corporate-announcements" in url:
                api_calls += 1
                if api_calls == 1:
                    return Response(403, payload={"message": "Forbidden"})
                return Response(
                    200,
                    payload=[
                        {
                            "symbol": "RELIANCE",
                            "desc": "Update on institutional investors meeting",
                            "attchmntText": "No unpublished price-sensitive information was shared.",
                            "an_dt": datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S"),
                            "attchmntFile": "reliance-investor-meeting.pdf",
                        }
                    ],
                )
            return Response(200, text="ok")

    articles = asyncio.run(scrape_nse_announcements("RELIANCE", Session()))
    assert api_calls == 2
    assert "https://www.nseindia.com/" in calls
    assert "https://www.nseindia.com/companies-listing/corporate-filings-announcements" in calls
    assert len(articles) == 1
    assert articles[0].source == "NSE Announcements"


def test_ambiguous_company_name_requires_exact_india_context():
    australia = TickerNewsArticle(
        title="Reliance Worldwide receives takeover bid",
        source="The Australian",
        url="https://example.test/australia",
        summary="Reliance Worldwide is listed in Australia.",
        published_at=datetime.now(timezone.utc).isoformat(),
    )
    india = TickerNewsArticle(
        title="Reliance Industries files exchange clarification",
        source="BSE Announcements",
        url="https://example.test/india",
        summary="Reliance Industries Limited filing.",
        published_at=datetime.now(timezone.utc).isoformat(),
    )
    assert _article_matches_symbol(australia, "RELIANCE", "Reliance Industries") is False
    assert _article_matches_symbol(india, "RELIANCE", "Reliance Industries") is True


def test_report_exposes_headline_diagnostics_and_official_filing(monkeypatch):
    article = TickerNewsArticle(
        title="Update on institutional investors meeting",
        source="NSE Announcements",
        url="https://nsearchives.nseindia.com/corporate/reliance.pdf",
        summary="No unpublished price-sensitive information was shared.",
        published_at=datetime.now(timezone.utc).isoformat(),
        relevance="high",
    )
    bundle = NewsScrapeBundle(
        [article],
        [NewsSourceDiagnostic("NSE Announcements", "SUCCESS", fetched=1, accepted=1)],
    )

    async def fake_scrape(_ticker, _company):
        return bundle

    async def fake_summary(_ticker, _company, _articles):
        return {
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
            "summary_headline": article.title,
            "llmUsed": True,
        }

    monkeypatch.setattr("app.services.ai_ticker_news._scrape_all_sources_bundle", fake_scrape)
    monkeypatch.setattr("app.services.ai_ticker_news.summarize_with_llm", fake_summary)
    monkeypatch.setattr("app.services.ai_ticker_news.set_cached_summary", lambda *_args, **_kwargs: None)
    report = asyncio.run(
        generate_ticker_news_report(
            "RELIANCE",
            "Reliance Industries",
            max_articles=8,
            include_raw=True,
            force_refresh=True,
        )
    ).to_dict()

    assert report["news_schema_version"] == NEWS_SCHEMA_VERSION
    assert report["evidence_status"] == "VERIFIED_RECENT"
    assert report["latest_verified_headlines"][0]["title"] == article.title
    assert report["source_diagnostics"][0]["status"] == "SUCCESS"
    assert "NSE Announcements" in report["regulatory_filings"]

