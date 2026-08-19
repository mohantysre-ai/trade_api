from app.services.intelligence_engine import build_ticker_intelligence_report


def _texrail_payload() -> dict:
    return {
        "stocks": [
            {
                "ticker": "TEXRAIL",
                "ltp": "₹102.65",
                "delta": "2.07 (-1.98%)",
                "intraday": {
                    "data_source": "candles",
                    "trigger_point": "Flag Breakout",
                    "vwap": 103.38,
                    "ema9": 102.58,
                    "atr_pct": 2.73,
                    "volume_multiplier": 1.02,
                    "turnover_cr": 13.27,
                    "price_above_vwap": False,
                    "price_above_ema9": True,
                    "passes_hard_filters": False,
                },
            }
        ],
        "terminalIntelligence": {
            "active_risk_calc": {},
            "active_scoring_matrix": {},
            "ledger_stocks": [],
        },
    }


def test_missing_score_and_research_are_not_imputed() -> None:
    report = build_ticker_intelligence_report(_texrail_payload(), "TEXRAIL")

    assert report["active_risk_calc"]["ticker_score"] is None
    assert report["active_risk_calc"]["risk_flag_score"] is None
    assert report["active_risk_calc"]["risk_flag"] == "INSUFFICIENT"
    assert "score INSUFFICIENT" in report["current_model"]
    assert "score 0.0" not in str(report)


def test_unsupported_claims_are_evidence_gated() -> None:
    report = build_ticker_intelligence_report(_texrail_payload(), "TEXRAIL")
    gates = report["active_seven_ic_gates"]

    assert report["insider_insti_activity_card"].startswith("INSUFFICIENT")
    assert report["macro_anchors_card"].startswith("INSUFFICIENT")
    assert report["future_revenue_model"].startswith("INSUFFICIENT")
    assert gates["q1_fund_buying"].startswith("INSUFFICIENT")
    assert gates["q2_liquidity_delivery"].startswith("FAIL")
    assert gates["q3_catalyst_validation"].startswith("INSUFFICIENT")
    assert gates["q5_risk_reward"].startswith("INSUFFICIENT")
    assert gates["q7_governance_gate"].startswith("INSUFFICIENT")
    assert "historically sound" not in str(report)
    assert report["dataQuality"] == "partial-live-metrics"


def test_financial_ratios_are_not_estimated_from_price_and_volume() -> None:
    report = build_ticker_intelligence_report(_texrail_payload(), "TEXRAIL")

    for value in report["active_scoring_matrix"].values():
        assert value.startswith("INSUFFICIENT")
