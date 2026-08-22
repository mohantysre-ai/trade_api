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
    assert report["active_risk_calc"]["risk_flag"] == "NOT_CALCULATED"
    assert "score INSUFFICIENT" in report["current_model"]
    assert "score 0.0" not in str(report)


def test_unsupported_claims_are_evidence_gated() -> None:
    report = build_ticker_intelligence_report(_texrail_payload(), "TEXRAIL")
    gates = report["active_seven_ic_gates"]

    assert report["insider_insti_activity_card"].startswith("SOURCE_UNAVAILABLE")
    assert report["macro_anchors_card"].startswith("SOURCE_UNAVAILABLE")
    assert report["future_revenue_model"].startswith("SOURCE_UNAVAILABLE")
    assert gates["q1_fund_buying"].startswith("SOURCE_UNAVAILABLE")
    assert gates["q2_liquidity_delivery"].startswith("FAIL")
    assert gates["q3_catalyst_validation"].startswith("SOURCE_UNAVAILABLE")
    assert gates["q5_risk_reward"].startswith("NOT_APPLICABLE")
    assert gates["q7_governance_gate"].startswith("SOURCE_UNAVAILABLE")
    assert "historically sound" not in str(report)
    assert report["dataQuality"] == "partial-live-metrics"


def test_financial_ratios_are_not_estimated_from_price_and_volume() -> None:
    report = build_ticker_intelligence_report(_texrail_payload(), "TEXRAIL")

    for value in report["active_scoring_matrix"].values():
        assert value.startswith("SOURCE_UNAVAILABLE")


def test_unscoped_terminal_matrix_is_not_reused_for_every_ticker() -> None:
    payload = _texrail_payload()
    payload["terminalIntelligence"]["active_scoring_matrix"] = {
        "beneish_m_score": "-2.10",
        "altman_z_score": "3.10",
        "ocf_ebitda_ratio": "0.90x",
        "mansfield_relative_strength": "+5.00%",
    }

    report = build_ticker_intelligence_report(payload, "TEXRAIL")

    assert report["active_scoring_matrix"]["beneish_m_score"].startswith("SOURCE_UNAVAILABLE")


def test_existing_snapshot_evidence_is_wired_into_ticker_report() -> None:
    payload = _texrail_payload()
    stock = payload["stocks"][0]
    stock["alpha_score"] = 36.65
    stock["promoter_holding_pct"] = 71.97
    stock["intraday"]["promoter_holding_pct"] = 71.97
    payload["terminalIntelligence"]["active_risk_calc"] = {
        "win_loss_ratio": "1.0:1",
        "kelly_policy_max": "5.0%",
    }
    payload["macroDataStrip"] = {
        "morning": [
            {"label": "Nifty 50", "val": "24,196.20", "delta": "-0.38%", "source": "angel_one_live"},
            {"label": "India VIX", "val": "11.63", "delta": "+2.67%", "source": "yahoo_finance_live"},
            {"label": "USD / INR Spot", "val": "95.66", "delta": "+0.07%", "source": "yahoo_finance_live"},
        ]
    }
    payload["tickerNewsByTicker"] = {
        "TEXRAIL": {
            "summary_headline": "TEXRAIL files a dated exchange update.",
            "regulatory_filings": "Exchange filing recorded on 21 Aug 2026.",
            "evidence_status": "VERIFIED_RECENT",
            "sources_checked": ["NSE Announcements", "BSE Announcements"],
            "latest_verified_headlines": [
                {
                    "title": "Exchange filing recorded",
                    "source": "NSE Announcements",
                    "published_at": "2026-08-21T10:00:00+05:30",
                }
            ],
        }
    }
    payload["tickerEvidenceByTicker"] = {
        "TEXRAIL": {
            "status": "READY",
            "metrics": {
                "beneish_m_score": "-1.92",
                "altman_z_score": "2.41",
                "ocf_ebitda_ratio": "0.88x",
                "mansfield_relative_strength": "+4.25% vs NIFTY 50",
            },
            "financialSnapshot": {
                "reportedRevenueCr": 4822.5,
                "reportedRevenueGrowthPct": 12.4,
                "forwardPe": 18.2,
                "priceToBook": 3.1,
            },
        }
    }

    report = build_ticker_intelligence_report(payload, "TEXRAIL")
    gates = report["active_seven_ic_gates"]

    assert report["active_risk_calc"]["ticker_score"] == 36.65
    assert report["active_risk_calc"]["risk_flag"] != "INSUFFICIENT"
    assert "Nifty 50" in report["macro_anchors_card"]
    assert "TEXRAIL files a dated exchange update" in report["news_catalysts_card"]
    assert report["active_scoring_matrix"]["beneish_m_score"] == "-1.92"
    assert report["active_factor_hub"]["value_factor"].startswith("Yahoo Finance")
    assert report["future_revenue_model"].startswith("REPORTED_BASE")
    assert gates["q3_catalyst_validation"].startswith("EVIDENCE_PRESENT")
    assert gates["q5_risk_reward"].startswith("NOT_APPLICABLE")
    assert gates["q6_quantitative_milestone"].startswith("FAIL")
    assert "score 36.6" in gates["q6_quantitative_milestone"]
    assert gates["q7_governance_gate"].startswith("PARTIAL")
    assert report["evidenceReadiness"]["financials"] == "READY"


def test_no_recent_news_is_distinct_from_source_failure() -> None:
    payload = _texrail_payload()
    payload["tickerNewsByTicker"] = {
        "TEXRAIL": {
            "evidence_status": "NO_RECENT_EVIDENCE",
            "lookback_days": 7,
            "sources_checked": ["NSE Announcements", "BSE Announcements", "Moneycontrol"],
            "summary_headline": "No verified TEXRAIL news found in the last 7 days.",
        }
    }

    report = build_ticker_intelligence_report(payload, "TEXRAIL")

    assert report["evidenceReadiness"]["news"] == "NO_RECENT_EVIDENCE"
    assert "returned no verified ticker-specific item in 7 days" in report["news_catalysts_card"]
