from app.services.ai_ticker_news import (
    TickerNewsArticle,
    _enforce_evidence_contract,
    _verified_headlines,
)


def test_verified_articles_always_produce_headlines():
    articles = [
        TickerNewsArticle(
            title="Infosys wins a new digital transformation contract",
            source="Example Wire",
            url="https://example.com/infy",
            summary="",
            published_at="2026-08-28T08:00:00+00:00",
            relevance="high",
        )
    ]
    headlines = _verified_headlines(articles)
    assert headlines
    assert headlines[0]["title"] == articles[0].title


def test_substantive_summary_is_suppressed_without_current_evidence():
    stale = {
        "summary_headline": "Infosys rallies on strong demand",
        "sentiment_overall": "Bullish",
        "institutional_activity": "Funds are accumulating shares",
        "risk_flags": "Low risk",
        "llmUsed": True,
    }
    cleaned = _enforce_evidence_contract(stale, [], "NO_RECENT_EVIDENCE", "INFY")
    assert cleaned["summary_headline"].startswith("No verified recent headline found for INFY")
    assert cleaned["sentiment_overall"] == "Neutral"
    assert cleaned["institutional_activity"] == ""
    assert cleaned["risk_flags"] == ""
    assert cleaned["llmUsed"] is False


def test_source_failure_is_explicit_without_current_evidence():
    cleaned = _enforce_evidence_contract(
        {"summary_headline": "Old cached headline", "sentiment_overall": "Bearish"},
        [],
        "SOURCE_UNAVAILABLE",
        "INFY",
    )
    assert "sources unavailable" in cleaned["summary_headline"].lower()
    assert cleaned["sentiment_overall"] == "Neutral"
