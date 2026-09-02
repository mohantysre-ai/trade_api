import pytest

from app.services import llm_client as llm


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr(llm, "_retired_models", set())
    monkeypatch.setattr(llm, "_model_not_before", {})
    monkeypatch.setattr(llm, "_provider_not_before", {})
    monkeypatch.setattr(llm, "_last_good_provider", None)
    monkeypatch.setattr(llm, "_last_good_model", None)
    monkeypatch.setattr(llm, "_llm_not_before", 0)


@pytest.mark.parametrize("variable", ["NVIDIA_MODEL", "NVIDIA_REASONING_MODEL", "NVIDIA_NEWS_MODEL"])
def test_retired_hosted_nvidia_env_override_is_migrated(monkeypatch, variable):
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    monkeypatch.setenv(variable, "nvidia/llama-3.3-nemotron-super-49b-v1")
    configs = llm.configured_llm_providers("news" if variable.endswith("NEWS_MODEL") else "reasoning")
    config = next(c for c in configs if c.name == "nvidia")
    assert config.model == "nvidia/nemotron-3-super-120b-a12b"
    monkeypatch.setenv("NVIDIA_API_URL", "http://custom-nim/v1/chat/completions")
    config = next(c for c in llm.configured_llm_providers("news" if variable.endswith("NEWS_MODEL") else "reasoning") if c.name == "nvidia")
    assert config.model == "nvidia/llama-3.3-nemotron-super-49b-v1"


def test_410_fails_over_and_is_not_retried_after_sixty_seconds(monkeypatch, caplog):
    configs = [llm.LLMProviderConfig("nvidia", "test", "https://nvidia/v1", "old"),
               llm.LLMProviderConfig("groq", "test", "https://groq/v1", "good")]
    monkeypatch.setattr(llm, "configured_llm_providers", lambda purpose: configs)
    calls = []

    def once(prompt, key, url, model, timeout, max_tokens):
        calls.append((url, model))
        if model == "old":
            raise RuntimeError('OpenAI request failed (410): {"status":410,"detail":"model end of life"}')
        return '{"ok":true}'

    monkeypatch.setattr(llm, "_openai_chat_once", once)
    assert llm.call_llm_with_fallback("test", "system")[1] == "groq"
    monkeypatch.setattr(llm._time, "time", lambda: 9999999999)
    monkeypatch.setattr(llm, "_last_good_provider", None)
    monkeypatch.setenv("LLM_PROVIDER_ATTEMPTS", "1")
    assert llm.call_llm_with_fallback("test", "system")[1] == "groq"
    assert calls == [("https://nvidia/v1", "old"), ("https://groq/v1", "good"), ("https://groq/v1", "good")]
    assert "OpenRouter model old cooling" not in caplog.text
    # The same ID at another endpoint is not globally disabled.
    monkeypatch.setattr(llm, "_openai_chat_once", lambda *a: "ok")
    assert llm._call_openai("test", "test", "https://other/v1", "old") == "ok"
    assert llm._call_openai("test", "test", "https://nvidia/v1", "replacement") == "ok"


def test_openrouter_410_continues_to_next_free_model(monkeypatch):
    monkeypatch.setattr(llm, "openrouter_free_failover_models", lambda model: ["old:free", "good:free"])
    calls = []

    def once(prompt, key, url, model, timeout, max_tokens):
        calls.append(model)
        if model == "old:free":
            raise RuntimeError("OpenAI request failed (410): Gone")
        return "ok"

    monkeypatch.setattr(llm, "_openai_chat_once", once)
    for _ in range(2):
        assert llm._call_openai("test", "test", "https://openrouter.ai/api/v1/chat/completions", "old:free") == "ok"
    assert calls == ["old:free", "good:free", "good:free"]


def test_nvidia_replacement_requests_content_without_reasoning_only_budget(monkeypatch):
    captured = []

    class Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    def post(url, **kwargs):
        captured.append(kwargs["json"])
        return Response()

    monkeypatch.setattr(llm.requests, "post", post)
    assert llm._openai_chat_once("test", "test", "https://integrate.api.nvidia.com/v1/chat/completions",
                                 "nvidia/nemotron-3-super-120b-a12b", 10) == '{"ok":true}'
    assert captured[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_blank_success_response_is_not_accepted(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": None, "reasoning_content": "internal"}}]}

    monkeypatch.setattr(llm.requests, "post", lambda *a, **kw: Response())
    with pytest.raises(RuntimeError, match="missing expected content"):
        llm._openai_chat_once("test", "test", "https://test/v1", "model", 10)
