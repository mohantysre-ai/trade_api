from app.services.desk_ic_criteria import _f, build_fact_pack
from app.services.intelligence_engine import (
    _apply_wl_policy_from_llm,
    _build_dynamic_selection_reason,
    _ticker_factor_hub,
    _ticker_intraday_text,
    _ticker_risk_calc,
)
from app.services.llm_client import _llm_config


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
