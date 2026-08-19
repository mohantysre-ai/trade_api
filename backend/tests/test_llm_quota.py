import app.services.llm_client as llm_client
from app.services.ai_ticker_news import ticker_news_report_is_llm_complete
from app.services.llm_client import parse_openrouter_reset_unix, quota_not_before_unix


def _reset_llm_state():
    llm_client._llm_not_before = 0.0
    llm_client._model_not_before.clear()
    llm_client._last_good_model = None


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
    assert ticker_news_report_is_llm_complete(None) is False
    assert ticker_news_report_is_llm_complete({
        "ticker": "KOTAKBANK",
        "llmUsed": False,
        "summary_headline": "LLM summary unavailable for KOTAKBANK (20 articles scraped).",
    }) is False
    assert ticker_news_report_is_llm_complete({
        "ticker": "KOTAKBANK",
        "llmUsed": True,
        "summary_headline": "Kotak reports Q1 update.",
    }) is True


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
            return _Resp(429, '{"error":{"message":"Rate limit exceeded: free-models-per-day"}}')
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


def test_account_daily_quota_locks_after_chain_exhausts(monkeypatch):
    from app.services.llm_client import _call_openai, _llm_quota_available

    _reset_llm_state()
    monkeypatch.setattr(
        "app.services.llm_client.openrouter_free_failover_models",
        lambda primary: [primary, "google/gemma-4-31b-it:free"],
    )

    def _post(url, json=None, headers=None, timeout=None):
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
    assert _llm_quota_available() is False
