from app import config


def test_runtime_config_reports_partial_dhan_credentials(monkeypatch):
    monkeypatch.setenv("DHAN_CLIENT_ID", "client")
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    issues = config.runtime_config_issues()
    assert any("DHAN_ACCESS_TOKEN" in issue for issue in issues)


def test_runtime_config_reports_partial_angel_credentials(monkeypatch):
    for name in ("ANGEL_CLIENT_ID", "ANGEL_TOTP_SECRET", "ANGEL_MPIN", "ANGEL_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANGEL_API_KEY", "key")
    issues = config.runtime_config_issues()
    assert any("ANGEL_CLIENT_ID" in issue for issue in issues)


def test_runtime_config_reports_llm_provider_without_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_API_URL", "https://api.openai.com/v1/chat/completions")
    for name in (
        "LLM_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "NVIDIA_API_KEY",
        "GROQ_API_KEY",
        "CEREBRAS_API_KEY",
        "SAMBANOVA_API_KEY",
        "HUGGINGFACE_API_KEY",
        "OMNIROUTE_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    issues = config.runtime_config_issues()
    assert "LLM_PROVIDER is set but no supported LLM API key is configured" in issues


def test_int_env_rejects_invalid_and_out_of_range_values(monkeypatch):
    monkeypatch.setenv("TEST_LIMIT", "not-a-number")
    try:
        config._int_env("TEST_LIMIT", 5, minimum=1, maximum=10)
        raise AssertionError("invalid integer was accepted")
    except RuntimeError as exc:
        assert "must be an integer" in str(exc)

    monkeypatch.setenv("TEST_LIMIT", "11")
    try:
        config._int_env("TEST_LIMIT", 5, minimum=1, maximum=10)
        raise AssertionError("out-of-range integer was accepted")
    except RuntimeError as exc:
        assert "between 1 and 10" in str(exc)
