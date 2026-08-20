import asyncio
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
