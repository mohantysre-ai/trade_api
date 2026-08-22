from datetime import datetime, timedelta, timezone

import app.services.llm_client as llm_client
from app.services.ai_ticker_news import (
    _EMPTY_CACHE_MINUTES,
    _LLM_CACHE_HOURS,
    NEWS_SCHEMA_VERSION,
    _article_fingerprint,
    _ticker_news_cache_ttl,
    get_cached_summary,
    ticker_news_report_is_llm_complete,
)
from app.services.llm_client import parse_openrouter_reset_unix, quota_not_before_unix


def _reset_llm_state():
    llm_client._llm_not_before = 0.0
    llm_client._model_not_before.clear()
    llm_client._last_good_model = None
    llm_client._provider_not_before.clear()
    llm_client._last_good_provider = None


class _Resp:
    def __init__(self, status: int, text: str, payload: dict | None = None):
        self.status_code = status
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


def _ok_payload(body: str = '{"ok":true}'):
    return {"choices": [{"message": {"content": body}, "finish_reason": "stop"}]}


def test_parse_openrouter_reset_ms():
    msg = (
        'OpenAI request failed (429): {"error":{"message":"Rate limit exceeded: '
        'free-models-per-day","metadata":{"headers":{"X-RateLimit-Reset":"1787184000000"}}}}'
    )
    assert parse_openrouter_reset_unix(msg) == 1787184000.0


def test_quota_not_before_honors_reset(monkeypatch):
    now = 1787100000.0
    msg = 'X-RateLimit-Reset: 1787184000000'
    until = quota_not_before_unix(msg, now=now)
    assert until == 1787184000.0


def test_ticker_news_incomplete_not_cacheable():
    fresh = {
        "news_schema_version": NEWS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    assert ticker_news_report_is_llm_complete(None) is False
    assert ticker_news_report_is_llm_complete({
        **fresh,
        "ticker": "KOTAKBANK",
        "llmUsed": False,
        "summary_headline": "LLM summary unavailable for KOTAKBANK (20 articles scraped).",
    }) is False
    assert ticker_news_report_is_llm_complete({
        **fresh,
        "ticker": "KOTAKBANK",
        "llmUsed": True,
        "summary_headline": "Kotak reports Q1 update.",
    }) is True
    assert ticker_news_report_is_llm_complete({
        **fresh,
        "ticker": "RELIANCE",
        "llmUsed": False,
        "digestSource": "tinyfish",
        "digestMode": "primary",
        "summary_headline": "Reliance wins new order",
    }) is True
    assert ticker_news_report_is_llm_complete({
        **fresh,
        "ticker": "RELIANCE",
        "llmUsed": False,
        "digestSource": "tinyfish",
        "digestMode": "primary",
        "summary_headline": "No verified Reliance Industries (RELIANCE) news found.",
    }) is False
    assert ticker_news_report_is_llm_complete({
        **fresh,
        "ticker": "RELIANCE",
        "llmUsed": False,
        "digestSource": "tinyfish",
        "digestMode": "quota",
        "summary_headline": "Reliance wins new order",
    }) is False


def test_tinyfish_cache_ttl_empty_and_quota_are_short():
    empty_ttl = _ticker_news_cache_ttl({
        "digestSource": "tinyfish",
        "digestMode": "primary",
        "llmUsed": False,
        "summary_headline": "No verified Reliance Industries (RELIANCE) news found.",
    })
    assert empty_ttl == timedelta(minutes=_EMPTY_CACHE_MINUTES)
    quota_ttl = _ticker_news_cache_ttl({
        "digestSource": "tinyfish",
        "digestMode": "quota",
        "llmUsed": False,
        "summary_headline": "Reliance wins new order",
    })
    assert quota_ttl == timedelta(minutes=_EMPTY_CACHE_MINUTES)
    durable = _ticker_news_cache_ttl({
        "digestSource": "tinyfish",
        "digestMode": "primary",
        "llmUsed": False,
        "summary_headline": "Reliance wins new order",
    })
    assert durable == timedelta(hours=_LLM_CACHE_HOURS)


def test_all_empty_llm_categories_use_short_cache_ttl():
    report = {
        "llmUsed": True,
        "articles_scraped": 3,
        **{
            key: "No recent news found."
            for key in (
                "insider_activity",
                "institutional_activity",
                "order_book_block_deals",
                "future_expansion_capex",
                "auditor_changes",
                "dividend_news",
                "new_orders_contracts",
                "earnings_results",
                "management_changes",
                "regulatory_filings",
            )
        },
    }
    assert _ticker_news_cache_ttl(report) == timedelta(minutes=_EMPTY_CACHE_MINUTES)


def test_old_news_schema_is_invalidated():
    assert ticker_news_report_is_llm_complete({
        "ticker": "RELIANCE",
        "llmUsed": True,
        "summary_headline": "Old cached summary",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "news_schema_version": NEWS_SCHEMA_VERSION - 1,
    }) is False
    assert ticker_news_report_is_llm_complete({
        "ticker": "RELIANCE",
        "llmUsed": True,
        "summary_headline": "Malformed cached summary",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "news_schema_version": "not-a-version",
    }) is False


def test_quota_tinyfish_cache_released_when_quota_available(monkeypatch):
    from app.services import ai_ticker_news as news

    monkeypatch.setattr(news, "_llm_quota_available", lambda: True)
    monkeypatch.setattr(
        news,
        "_llm_cache",
        {
            "RELIANCE": {
                "digestSource": "tinyfish",
                "digestMode": "quota",
                "llmUsed": False,
                "summary_headline": "Reliance wins new order",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "articleFingerprint": _article_fingerprint([]),
                "news_schema_version": NEWS_SCHEMA_VERSION,
            }
        },
    )
    assert get_cached_summary("RELIANCE", [], 8) is None


def test_quota_tinyfish_cache_held_during_cooldown(monkeypatch):
    from app.services import ai_ticker_news as news

    monkeypatch.setattr(news, "_llm_quota_available", lambda: False)
    monkeypatch.setattr(
        news,
        "_llm_cache",
        {
            "RELIANCE": {
                "digestSource": "tinyfish",
                "digestMode": "quota",
                "llmUsed": False,
                "summary_headline": "Reliance wins new order",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "articleFingerprint": _article_fingerprint([]),
                "news_schema_version": NEWS_SCHEMA_VERSION,
            }
        },
    )
    cached = get_cached_summary("RELIANCE", [], 8)
    assert cached is not None
    assert cached["digestMode"] == "quota"


def test_openrouter_free_failover_puts_primary_then_router(monkeypatch):
    from app.services.llm_client import OPENROUTER_FREE_ROUTER, openrouter_free_failover_models

    _reset_llm_state()
    monkeypatch.setattr(
        "app.services.llm_client._list_openrouter_free_models",
        lambda: [OPENROUTER_FREE_ROUTER, "google/gemma-4-31b-it:free", "openai/gpt-oss-20b:free"],
    )
    chain = openrouter_free_failover_models("nvidia/nemotron-3-ultra-550b-a55b:free")
    assert chain[0] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert OPENROUTER_FREE_ROUTER in chain
    assert "google/gemma-4-31b-it:free" in chain


def test_openrouter_free_failover_merges_env_and_catalog(monkeypatch):
    from app.services.llm_client import OPENROUTER_FREE_ROUTER, openrouter_free_failover_models

    _reset_llm_state()
    monkeypatch.setenv("LLM_FREE_FALLBACK_MODELS", "openai/gpt-oss-20b:free")
    monkeypatch.setattr(
        "app.services.llm_client._list_openrouter_free_models",
        lambda: [OPENROUTER_FREE_ROUTER, "google/gemma-4-31b-it:free"],
    )
    chain = openrouter_free_failover_models("nvidia/nemotron-3-nano-30b-a3b:free")
    assert chain[0] == "nvidia/nemotron-3-nano-30b-a3b:free"
    assert "openai/gpt-oss-20b:free" in chain
    assert "google/gemma-4-31b-it:free" in chain


def test_openrouter_retries_next_free_model_on_429(monkeypatch):
    from app.services.llm_client import _call_openai

    _reset_llm_state()
    monkeypatch.setattr(
        "app.services.llm_client.openrouter_free_failover_models",
        lambda primary: [primary, "openrouter/free", "google/gemma-4-31b-it:free"],
    )
    seen: list[str] = []

    def _post(url, json=None, headers=None, timeout=None):
        model = (json or {}).get("model")
        seen.append(model)
        if model != "google/gemma-4-31b-it:free":
            return _Resp(429, '{"error":{"message":"Rate limit exceeded"}}')
        return _Resp(200, "{}", _ok_payload())

    monkeypatch.setattr("app.services.llm_client.requests.post", _post)
    text = _call_openai(
        "prompt",
        "sk-or-test",
        "https://openrouter.ai/api/v1/chat/completions",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
    )
    assert text == '{"ok":true}'
    assert seen[0] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert "google/gemma-4-31b-it:free" in seen
    assert llm_client._llm_quota_available() is True
    assert llm_client._last_good_model == "google/gemma-4-31b-it:free"


def test_per_model_429_does_not_lock_all_llms(monkeypatch):
    from app.services.llm_client import _call_openai, _llm_quota_available, _record_quota_error

    _reset_llm_state()
    _record_quota_error('OpenAI request failed (429): {"error":{"message":"Rate limit exceeded"}}')
    assert _llm_quota_available() is True

    monkeypatch.setattr(
        "app.services.llm_client.openrouter_free_failover_models",
        lambda primary: [primary, "google/gemma-4-31b-it:free"],
    )
    seen: list[str] = []

    def _post(url, json=None, headers=None, timeout=None):
        model = (json or {}).get("model")
        seen.append(model)
        if model == "nvidia/nemotron-3-nano-30b-a3b:free":
            return _Resp(429, '{"error":{"message":"Rate limit exceeded"}}')
        return _Resp(200, "{}", _ok_payload())

    monkeypatch.setattr("app.services.llm_client.requests.post", _post)
    text = _call_openai(
        "prompt",
        "sk-or-test",
        "https://openrouter.ai/api/v1/chat/completions",
        "nvidia/nemotron-3-nano-30b-a3b:free",
    )
    assert text == '{"ok":true}'
    assert seen == ["nvidia/nemotron-3-nano-30b-a3b:free", "google/gemma-4-31b-it:free"]
    assert _llm_quota_available() is True

    seen.clear()
    text = _call_openai(
        "prompt",
        "sk-or-test",
        "https://openrouter.ai/api/v1/chat/completions",
        "nvidia/nemotron-3-nano-30b-a3b:free",
    )
    assert text == '{"ok":true}'
    assert seen[0] == "google/gemma-4-31b-it:free"
    assert "nvidia/nemotron-3-nano-30b-a3b:free" not in seen


def test_paid_openrouter_primary_still_failsover_to_free(monkeypatch):
    from app.services.llm_client import _call_openai

    _reset_llm_state()
    monkeypatch.setattr(
        "app.services.llm_client.openrouter_free_failover_models",
        lambda primary: [primary, "openrouter/free", "openai/gpt-oss-20b:free"],
    )
    seen: list[str] = []

    def _post(url, json=None, headers=None, timeout=None):
        model = (json or {}).get("model")
        seen.append(model)
        if model != "openai/gpt-oss-20b:free":
            return _Resp(429, '{"error":{"message":"Rate limit exceeded"}}')
        return _Resp(200, "{}", _ok_payload())

    monkeypatch.setattr("app.services.llm_client.requests.post", _post)
    text = _call_openai(
        "prompt",
        "sk-or-test",
        "https://openrouter.ai/api/v1/chat/completions",
        "gpt-4o-mini",
    )
    assert text == '{"ok":true}'
    assert seen[0] == "gpt-4o-mini"
    assert "openai/gpt-oss-20b:free" in seen


def test_account_daily_quota_stops_failover_immediately(monkeypatch):
    from app.services.llm_client import _call_openai, _llm_quota_available

    _reset_llm_state()
    monkeypatch.setattr(
        "app.services.llm_client.openrouter_free_failover_models",
        lambda primary: [primary, "google/gemma-4-31b-it:free"],
    )
    seen: list[str] = []

    def _post(url, json=None, headers=None, timeout=None):
        seen.append((json or {}).get("model"))
        return _Resp(429, '{"error":{"message":"Rate limit exceeded: free-models-per-day"}}')

    monkeypatch.setattr("app.services.llm_client.requests.post", _post)
    try:
        _call_openai(
            "prompt",
            "sk-or-test",
            "https://openrouter.ai/api/v1/chat/completions",
            "nvidia/nemotron-3-nano-30b-a3b:free",
        )
    except RuntimeError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    assert seen == ["nvidia/nemotron-3-nano-30b-a3b:free"]
    assert _llm_quota_available() is False


def _clear_provider_env(monkeypatch):
    for name in (
        "LLM_PROVIDER", "LLM_API_KEY", "LLM_API_URL", "LLM_MODEL",
        "NVIDIA_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
        "SAMBANOVA_API_KEY", "HUGGINGFACE_API_KEY", "GEMINI_API_KEY",
        "OMNIROUTE_ENABLED", "OMNIROUTE_API_KEY", "OMNIROUTE_API_URL",
        "OMNIROUTE_MODEL", "OMNIROUTE_NEWS_MODEL", "OMNIROUTE_REASONING_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_provider_router_discovers_configured_open_model_endpoints(monkeypatch):
    _reset_llm_state()
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "groq,nvidia,cerebras")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test")
    monkeypatch.setenv("NVIDIA_NEWS_MODEL", "nvidia/news-small")
    providers = llm_client.configured_llm_providers("news")
    assert [item.name for item in providers] == ["groq", "nvidia", "cerebras"]
    assert providers[1].model == "nvidia/news-small"
    assert providers[1].api_url == "https://integrate.api.nvidia.com/v1/chat/completions"


def test_provider_router_discovers_opt_in_omniroute(monkeypatch):
    _reset_llm_state()
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "omniroute")
    monkeypatch.setenv("OMNIROUTE_ENABLED", "1")
    monkeypatch.setenv("OMNIROUTE_NEWS_MODEL", "auto/best-free")
    providers = llm_client.configured_llm_providers("news")
    assert [item.name for item in providers] == ["omniroute"]
    assert providers[0].api_url == "http://127.0.0.1:20128/v1/chat/completions"
    assert providers[0].model == "auto/best-free"


def test_openrouter_daily_quota_does_not_block_other_provider(monkeypatch):
    _reset_llm_state()
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "openrouter,nvidia")
    monkeypatch.setenv("LLM_PROVIDER_ATTEMPTS", "2")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    llm_client._llm_not_before = 9999999999.0
    seen: list[str] = []

    def fake_call(prompt, api_key, api_url, model, timeout, max_tokens=None):
        seen.append(api_url)
        return '{"summary":"ok"}'

    monkeypatch.setattr(llm_client, "_call_openai", fake_call)
    text, provider, _model = llm_client.call_llm_with_fallback(
        "facts", "json only", purpose="news", max_tokens=300
    )
    assert text == '{"summary":"ok"}'
    assert provider == "nvidia"
    assert seen == ["https://integrate.api.nvidia.com/v1/chat/completions"]


def test_openrouter_daily_quota_falls_through_to_omniroute(monkeypatch):
    _reset_llm_state()
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "openrouter,omniroute")
    monkeypatch.setenv("LLM_PROVIDER_ATTEMPTS", "2")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    monkeypatch.setenv("OMNIROUTE_ENABLED", "1")
    seen: list[str] = []

    def fake_call(prompt, api_key, api_url, model, timeout, max_tokens=None):
        seen.append(api_url)
        if "openrouter.ai" in api_url:
            raise RuntimeError("429 free-models-per-day")
        return '{"summary_headline":"Reliance evidence summarized"}'

    monkeypatch.setattr(llm_client, "_call_openai", fake_call)
    text, provider, model = llm_client.call_llm_with_fallback(
        "RELIANCE evidence", "json only", purpose="news", max_tokens=300
    )
    assert text == '{"summary_headline":"Reliance evidence summarized"}'
    assert provider == "omniroute"
    assert model == "auto/best-free"
    assert seen == [
        "https://openrouter.ai/api/v1/chat/completions",
        "http://127.0.0.1:20128/v1/chat/completions",
    ]


def test_provider_router_is_sequential_and_stops_after_success(monkeypatch):
    _reset_llm_state()
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER_ORDER", "nvidia,groq,cerebras")
    monkeypatch.setenv("LLM_PROVIDER_ATTEMPTS", "3")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk-test")
    seen: list[str] = []

    def fake_call(prompt, api_key, api_url, model, timeout, max_tokens=None):
        seen.append(api_url)
        if "nvidia" in api_url:
            raise RuntimeError("429 rate limit")
        return "{}"

    monkeypatch.setattr(llm_client, "_call_openai", fake_call)
    text, provider, _model = llm_client.call_llm_with_fallback("facts", "json only")
    assert text == "{}"
    assert provider == "groq"
    assert seen == [
        "https://integrate.api.nvidia.com/v1/chat/completions",
        "https://api.groq.com/openai/v1/chat/completions",
    ]
