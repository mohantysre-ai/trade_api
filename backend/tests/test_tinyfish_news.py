from app.services.tinyfish_news import search_tinyfish


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
