from app.services.desk_ic_criteria import _f, build_fact_pack
from app.services.intelligence_engine import (
    _apply_wl_policy_from_llm,
    _build_dynamic_selection_reason,
    _build_ticker_reason_prompt,
    _ticker_factor_hub,
    _ticker_intraday_text,
    _ticker_risk_calc,
)
from app.services.llm_client import _call_openai, _llm_config


def test_fact_pack_parses_formatted_inr_ltp(monkeypatch):
    pack = build_fact_pack(
        "PVRINOX",
        {
            "ticker": "PVRINOX",
            "ltp": "₹1,412.30",
            "ltpRaw": 1412.3,
            "intraday": {
                "data_source": "candles",
                "turnover_cr": 88.2,
                "atr_pct": 2.1,
                "volume_multiplier": 1.4,
            },
            "promoter_holding_pct": 71.2,
            "score": 62,
        },
    )
    assert pack["ltp"] == 1412.3
    assert pack["turnover_cr"] == 88.2
    assert pack["atr_pct"] == 2.1
    assert pack["promoter_holding_pct"] == 71.2


def test_f_parses_inr_string():
    assert _f("₹1,234.50") == 1234.5
    assert _f("—") is None


def test_risk_calc_uses_daily_candles():
    out = _ticker_risk_calc(
        {
            "delta": "-2.16%",
            "intraday": {
                "data_source": "daily_candles",
                "atr_pct": 2.41,
                "turnover_cr": 45.1,
                "volume_multiplier": 0.82,
            },
        },
        {},
        {},
        0.0,
    )
    assert out["atr_pct"] == 2.41
    assert out["turnover_cr"] == 45.1
    assert out["volume_multiplier"] == 0.82
    assert out["signal_quality"] == "daily-candles"
    assert out["delta_pct"] == -2.16


def test_factor_hub_dashes_when_dummy_intraday():
    out = _ticker_factor_hub(
        {"delta": "-2.16%", "intraday": {"atr_pct": 0.0, "turnover_cr": 0.0, "volume_multiplier": 0.0}},
        0.0,
    )
    assert out["liquidity_factor"] == "—"
    assert out["quality_factor"] == "—"
    assert "0.00 Cr" not in out["liquidity_factor"]


def test_daily_candles_prompt_omits_stale_trigger():
    stock = {
        "delta": "-2.16%",
        "ltp": "₹2,301.00",
        "intraday": {
            "data_source": "daily_candles",
            "atr_pct": 2.4,
            "turnover_cr": 41.2,
            "volume_multiplier": 0.8,
            "trigger_point": "VWAP Bounce",
            "price_above_vwap": False,
            "price_above_ema9": False,
        },
    }
    prompt = _build_ticker_reason_prompt("BALKRISIND", stock, None)
    assert "VWAP Bounce" not in prompt
    assert '"data_source": "daily_candles"' in prompt
    assert '"trigger_point": null' in prompt


def test_daily_candles_do_not_claim_vwap_bounce():
    stock = {
        "delta": "-2.16%",
        "intraday": {
            "data_source": "daily_candles",
            "atr_pct": 2.4,
            "turnover_cr": 41.2,
            "volume_multiplier": 0.8,
            "vwap": 0.0,
            "ema9": 0.0,
            "trigger_point": "VWAP Bounce",
        },
    }
    text = _ticker_intraday_text(stock)
    assert "VWAP Bounce" not in text
    assert "no 5m trigger" in text
    reason = _build_dynamic_selection_reason(stock, 0.0)
    assert "VWAP Bounce" not in reason
    assert "5m trigger unavailable" in reason


def test_selection_reason_allows_missing_score():
    stock = {
        "delta": "-2.16%",
        "intraday": {
            "data_source": "daily_candles",
            "atr_pct": 2.4,
            "turnover_cr": 41.2,
            "volume_multiplier": 0.8,
            "trigger_point": None,
        },
    }
    reason = _build_dynamic_selection_reason(stock, None)
    assert "score unavailable" in reason
    assert "5m trigger unavailable" in reason


def test_five_minute_vwap_bounce_is_kept():
    stock = {
        "delta": "1.20%",
        "intraday": {
            "data_source": "candles",
            "atr_pct": 2.1,
            "turnover_cr": 88.2,
            "volume_multiplier": 1.4,
            "vwap": 103.38,
            "ema9": 102.58,
            "price_above_vwap": True,
            "trigger_point": "VWAP Bounce",
        },
    }
    reason = _build_dynamic_selection_reason(stock, 62.0)
    assert "trigger VWAP Bounce" in reason
    assert "5m trigger unavailable" not in reason
    text = _ticker_intraday_text(stock)
    assert "VWAP Bounce" in text


def test_intraday_text_does_not_fabricate_zero_atr_or_volume():
    stock = {
        "intraday": {
            "data_source": "candles",
            "vwap": 103.38,
            "ema9": 102.58,
            "trigger_point": "VWAP Bounce",
        },
    }
    text = _ticker_intraday_text(stock)
    assert "ATR 0%" not in text
    assert "volume multiplier 0x" not in text
    assert "ATR unavailable" in text
    assert "volume multiplier unavailable" in text


def test_wl_policy_does_not_invent_kelly(monkeypatch):
    monkeypatch.setattr(
        "app.services.intelligence_engine._analyze_forensic_wl_policy",
        lambda *_a, **_k: None,
    )
    analysis = _apply_wl_policy_from_llm({"active_risk_calc": {}, "ledger_stocks": []}, {}, None)
    assert analysis["active_risk_calc"]["win_loss_ratio"] == "—"
    assert analysis["active_risk_calc"]["kelly_policy_max"] == "—"


def test_openrouter_url_selects_openai_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-or-v1-test")
    monkeypatch.setenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    monkeypatch.setenv("LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    provider, key, url, model, _ = _llm_config()
    assert provider == "openai"
    assert key.startswith("sk-or-")
    assert "openrouter.ai" in url
    assert "nemotron" in model


def test_openrouter_defaults_to_free_router(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_API_KEY", "sk-or-v1-test")
    monkeypatch.delenv("LLM_API_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    provider, _key, url, model, _ = _llm_config()
    assert provider == "openai"
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert model == "openrouter/free"


def test_openrouter_uses_compact_budget_across_fallbacks(monkeypatch):
    import app.services.llm_client as llm_client

    llm_client._llm_not_before = 0.0
    llm_client._model_not_before.clear()
    llm_client._last_good_model = None
    sent = []

    class Response:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {
                "model": "meta-llama/llama:free",
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            }

    def fake_post(_url, json, headers, timeout):
        sent.append(dict(json))
        if len(sent) == 1:
            return Response(429, "provider rate limit")
        return Response(200, "")

    monkeypatch.setattr(
        "app.services.llm_client.openrouter_free_failover_models",
        lambda _primary: ["qwen/qwen3:free", "meta-llama/llama:free"],
    )
    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)
    _call_openai(
        "test",
        "sk-or-test",
        "https://openrouter.ai/api/v1/chat/completions",
        "qwen/qwen3:free",
        max_tokens=321,
    )
    assert [request["model"] for request in sent] == [
        "qwen/qwen3:free",
        "meta-llama/llama:free",
    ]
    assert all(request["max_tokens"] == 321 for request in sent)
