import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.services.ai_ticker_news import (
    TickerNewsArticle,
    _article_fingerprint,
    _recent_articles,
    summarize_with_llm,
)


def article(title: str, published_at: str) -> TickerNewsArticle:
    return TickerNewsArticle(
        title=title,
        source="NSE Announcements",
        url=f"https://example.test/{title}",
        summary="Evidence",
        published_at=published_at,
        relevance="high",
    )


def test_recent_articles_reject_old_and_unknown_dates():
    now = datetime.now(timezone.utc)
    recent = article("recent", (now - timedelta(days=2)).isoformat())
    old = article("old", (now - timedelta(days=9)).isoformat())
    unknown = article("unknown", "")
    assert [item.title for item in _recent_articles([old, unknown, recent])] == ["recent"]


def test_article_fingerprint_changes_with_evidence():
    now = datetime.now(timezone.utc).isoformat()
    assert _article_fingerprint([article("one", now)]) != _article_fingerprint([article("two", now)])


def test_empty_evidence_skips_llm(monkeypatch):
    monkeypatch.setattr("app.services.ai_ticker_news.tinyfish_ticker_news_failover", lambda: False)
    monkeypatch.setattr("app.services.llm_client._llm_config", lambda: (_ for _ in ()).throw(AssertionError("must not call")))
    result = asyncio.run(summarize_with_llm("TEXRAIL", "Texmaco Rail", []))
    assert result["llmUsed"] is False
    assert "No verified articles" in result["llmError"]


def test_ticker_summary_exposes_omniroute_provider_metadata(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    evidence = [article("Reliance reports a new energy update", now)]
    payload = {
        "insider_activity": "No recent news found.",
        "institutional_activity": "No recent news found.",
        "order_book_block_deals": "No recent news found.",
        "future_expansion_capex": "The company reported a new energy update.",
        "auditor_changes": "No recent news found.",
        "dividend_news": "No recent news found.",
        "new_orders_contracts": "No recent news found.",
        "earnings_results": "No recent news found.",
        "management_changes": "No recent news found.",
        "regulatory_filings": "No recent news found.",
        "sentiment_overall": "Neutral",
        "risk_flags": "None",
        "summary_headline": "Reliance reported a new energy update.",
    }
    monkeypatch.setattr("app.services.ai_ticker_news.tinyfish_ticker_news_failover", lambda: False)
    monkeypatch.setattr("app.services.ai_ticker_news.configured_llm_providers", lambda _purpose: ["omniroute"])
    monkeypatch.setattr(
        "app.services.ai_ticker_news.call_llm_with_fallback",
        lambda *_args, **_kwargs: (json.dumps(payload), "omniroute", "auto/best-free"),
    )
    result = asyncio.run(summarize_with_llm("RELIANCE", "Reliance Industries", evidence))
    assert result["llmUsed"] is True
    assert result["llmProvider"] == "omniroute"
    assert result["llmModel"] == "auto/best-free"
    assert result["summary_headline"] == "Reliance reported a new energy update."
