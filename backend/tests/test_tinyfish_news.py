from datetime import datetime, timedelta, timezone

from app.services.tinyfish_news import digest_ticker_news, search_tinyfish


def test_search_tinyfish_parses_news_rows(monkeypatch):
    monkeypatch.setenv("TINYFISH_API_KEY", "sk-tinyfish-test")

    class _Resp:
        status_code = 200
        content = b"{}"

        def json(self):
            return {
                "query": "RELIANCE NSE stock",
                "results": [
                    {
                        "position": 1,
                        "domain": "moneycontrol.com",
                        "title": "Reliance wins new order",
                        "snippet": "The company announced a contract.",
                        "url": "https://www.moneycontrol.com/news/reliance",
                        "date": "2026-08-20",
                        "publisher": "Moneycontrol",
                    },
                    {"position": 2, "title": "", "url": "https://example.com"},
                ],
                "total_results": 2,
                "page": 0,
            }

        def text(self):
            return "{}"

    captured = {}

    def _get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr("app.services.tinyfish_news.requests.get", _get)
    rows = search_tinyfish("RELIANCE NSE stock", location="IN", language="en", domain_type="news")
    assert captured["url"] == "https://api.search.tinyfish.ai"
    assert captured["params"]["domain_type"] == "news"
    assert captured["headers"]["X-API-Key"] == "sk-tinyfish-test"
    assert captured["headers"]["X-TF-Request-Origin"] == "api"
    assert captured["headers"]["X-TF-Client-Name"] == "tinyfish-api-key-page"
    assert len(rows) == 1
    assert rows[0]["title"] == "Reliance wins new order"
    assert rows[0]["source"] == "Moneycontrol"
    assert rows[0]["url"].startswith("https://www.moneycontrol.com")


def test_search_tinyfish_skips_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)

    def _get(*_a, **_k):
        raise AssertionError("must not call TinyFish without a key")

    monkeypatch.setattr("app.services.tinyfish_news.requests.get", _get)
    assert search_tinyfish("anything") == []


def test_scrape_all_sources_uses_tinyfish_when_html_skipped(monkeypatch):
    import asyncio

    from app.services.ai_ticker_news import scrape_all_sources

    monkeypatch.setattr("app.services.ai_ticker_news._dns_circuit_open", lambda: True)
    monkeypatch.setattr("app.services.ai_ticker_news.tinyfish_enabled", lambda: True)
    monkeypatch.setattr("app.services.ai_ticker_news.backup_min_articles", lambda: 3)

    def _search(query, **kwargs):
        assert "RELIANCE" in query
        assert kwargs["location"] == "IN"
        assert kwargs["domain_type"] == "news"
        return [
            {
                "title": "Reliance Q1 results",
                "source": "Moneycontrol",
                "url": "https://www.moneycontrol.com/news/r",
                "summary": "Results beat estimates.",
                "published_at": "2026-08-20",
            }
        ]

    monkeypatch.setattr("app.services.ai_ticker_news.search_tinyfish", _search)
    articles = asyncio.run(scrape_all_sources("RELIANCE", "Reliance Industries"))
    assert len(articles) == 1
    assert articles[0].title == "Reliance Q1 results"
    assert articles[0].source == "Moneycontrol"


def test_scrape_all_sources_drops_stale_and_undated_tinyfish(monkeypatch):
    import asyncio

    from app.services.ai_ticker_news import scrape_all_sources

    monkeypatch.setattr("app.services.ai_ticker_news._dns_circuit_open", lambda: True)
    monkeypatch.setattr("app.services.ai_ticker_news.tinyfish_enabled", lambda: True)
    monkeypatch.setattr("app.services.ai_ticker_news.backup_min_articles", lambda: 3)
    now = datetime.now(timezone.utc)

    def _search(_query, **_kwargs):
        return [
            {
                "title": "Stale Reliance filing",
                "source": "Moneycontrol",
                "url": "https://www.moneycontrol.com/news/old",
                "summary": "Old contract.",
                "published_at": (now - timedelta(days=9)).isoformat(),
            },
            {
                "title": "Undated Reliance headline",
                "source": "ET",
                "url": "https://economictimes.indiatimes.com/news/x",
                "summary": "No date.",
                "published_at": "",
            },
            {
                "title": "Reliance Q1 results",
                "source": "Moneycontrol",
                "url": "https://www.moneycontrol.com/news/r",
                "summary": "Results beat estimates.",
                "published_at": (now - timedelta(days=1)).isoformat(),
            },
        ]

    monkeypatch.setattr("app.services.ai_ticker_news.search_tinyfish", _search)
    articles = asyncio.run(scrape_all_sources("RELIANCE", "Reliance Industries"))
    assert [item.title for item in articles] == ["Reliance Q1 results"]


def test_tinyfish_digest_drops_stale_and_undated_rows(monkeypatch):
    import asyncio

    from app.services.ai_ticker_news import _tinyfish_ticker_digest

    now = datetime.now(timezone.utc)

    def _search(_query, **_kwargs):
        return [
            {
                "title": "Stale Reliance filing",
                "source": "Moneycontrol",
                "url": "https://www.moneycontrol.com/news/old",
                "summary": "Old contract.",
                "published_at": (now - timedelta(days=9)).isoformat(),
            },
            {
                "title": "Undated Reliance headline",
                "source": "ET",
                "url": "https://economictimes.indiatimes.com/news/x",
                "summary": "No date.",
                "published_at": "",
            },
        ]

    monkeypatch.setattr("app.services.ai_ticker_news.search_tinyfish", _search)
    digest = asyncio.run(_tinyfish_ticker_digest("RELIANCE", "Reliance Industries", []))
    assert digest["summary_headline"] == "No verified Reliance Industries (RELIANCE) news found."
    assert digest["earnings_results"] == "—"


def test_digest_routes_sourced_headlines_not_verdicts():
    out = digest_ticker_news(
        [
            {
                "title": "Reliance Q1 results beat estimates",
                "source": "Moneycontrol",
                "summary": "Revenue rose 12 percent.",
                "url": "https://www.moneycontrol.com/news/r",
                "published_at": "2026-08-20",
            }
        ],
        ticker="RELIANCE",
        company="Reliance Industries",
    )
    assert out["digestSource"] == "tinyfish"
    assert out["llmUsed"] is False
    assert "Q1 results" in str(out["earnings_results"])
    assert out["sentiment_overall"] == "—"
    assert out["insider_activity"] == "—"


def test_summarize_uses_tinyfish_not_openrouter(monkeypatch):
    import asyncio

    from app.services.ai_ticker_news import TickerNewsArticle, summarize_with_llm

    monkeypatch.setenv("TINYFISH_API_KEY", "sk-tinyfish-test")
    monkeypatch.delenv("TICKER_NEWS_LLM", raising=False)
    monkeypatch.setattr("app.services.ai_ticker_news.search_tinyfish", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "app.services.llm_client._call_openai",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not call OpenRouter")),
    )
    now = datetime.now(timezone.utc).isoformat()
    articles = [
        TickerNewsArticle(
            title="Reliance Q1 results beat estimates",
            source="Moneycontrol",
            url="https://www.moneycontrol.com/news/r",
            summary="Revenue rose 12 percent.",
            published_at=now,
        )
    ]
    result = asyncio.run(summarize_with_llm("RELIANCE", "Reliance Industries", articles))
    assert result["digestSource"] == "tinyfish"
    assert result["digestMode"] == "primary"
    assert result["llmUsed"] is False
    assert "Q1 results" in str(result["earnings_results"])


def test_quota_path_tinyfish_digest_is_not_complete(monkeypatch):
    import asyncio

    from app.services.ai_ticker_news import TickerNewsArticle, summarize_with_llm, ticker_news_report_is_llm_complete

    monkeypatch.setenv("TINYFISH_API_KEY", "sk-tinyfish-test")
    monkeypatch.setenv("TICKER_NEWS_LLM", "openrouter")
    monkeypatch.setattr(
        "app.services.ai_ticker_news.configured_llm_providers",
        lambda _purpose: ["openrouter"],
    )
    monkeypatch.setattr(
        "app.services.ai_ticker_news.call_llm_with_fallback",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("quota cooling down")),
    )
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        "app.services.ai_ticker_news.search_tinyfish",
        lambda *_a, **_k: [
            {
                "title": "Reliance Q1 results beat estimates",
                "source": "Moneycontrol",
                "url": "https://www.moneycontrol.com/news/r",
                "summary": "Revenue rose 12 percent.",
                "published_at": now,
            }
        ],
    )
    articles = [
        TickerNewsArticle(
            title="Reliance Q1 results beat estimates",
            source="Moneycontrol",
            url="https://www.moneycontrol.com/news/r",
            summary="Revenue rose 12 percent.",
            published_at=now,
        )
    ]
    result = asyncio.run(summarize_with_llm("RELIANCE", "Reliance Industries", articles))
    assert result["digestSource"] == "tinyfish"
    assert result["digestMode"] == "quota"
    assert ticker_news_report_is_llm_complete(result) is False
