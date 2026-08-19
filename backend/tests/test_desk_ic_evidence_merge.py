from backend.app.services.desk_ic_criteria import (
    _merge_llm_over_hard,
    build_deterministic_desk_ic,
    build_fact_pack,
)


def _angelone_fact_pack() -> dict:
    return build_fact_pack(
        "ANGELONE",
        {
            "ticker": "ANGELONE",
            "ltp": 289.50,
            "turnover_cr": 17.87,
            "volume_multiplier": 0.13,
            "rsi": 33.3,
            "atr_pct": 2.6,
            "promoter_holding_pct": 28.59,
            "sector": None,
        },
        ticker_news=None,
    )


def test_missing_news_and_rsi_alone_never_become_pass() -> None:
    result = build_deterministic_desk_ic(_angelone_fact_pack())
    criteria = {row["id"]: row for row in result["criteria"]}

    assert criteria["news_event_risk"]["status"] == "INSUFFICIENT"
    assert criteria["technical_alignment"]["status"] == "INSUFFICIENT"
    assert criteria["portfolio_fit"]["status"] == "INSUFFICIENT"


def test_llm_cannot_override_status_scores_or_decision() -> None:
    llm_payload = {
        "deskDecision": "APPROVE",
        "oneLiner": "Clean event backdrop and oversold bounce.",
        "criteria": [
            {"id": "technical_alignment", "status": "PASS", "detail": "RSI suggests a bounce"},
            {"id": "news_event_risk", "status": "PASS", "detail": "No news means no risk"},
            {"id": "liquidity_turnover", "status": "PASS", "detail": "Liquidity acceptable"},
        ],
        "categoryScores": {
            "liquidity": 30,
            "technical": 60,
            "governance": 20,
            "eventRisk": 80,
            "portfolioFit": 0,
        },
    }

    result = _merge_llm_over_hard(_angelone_fact_pack(), llm_payload)
    criteria = {row["id"]: row for row in result["criteria"]}

    assert result["deskDecision"] == "REJECT"
    assert result["conviction"] == 28
    assert criteria["liquidity_turnover"]["status"] == "FAIL"
    assert criteria["governance_promoter"]["status"] == "FAIL"
    assert criteria["technical_alignment"]["status"] == "INSUFFICIENT"
    assert criteria["news_event_risk"]["status"] == "INSUFFICIENT"
    assert result["categoryScores"] == {
        "liquidity": 50,
        "technical": None,
        "governance": 50,
        "eventRisk": None,
        "portfolioFit": None,
    }
    assert result["oneLiner"].startswith("Evidence-gated Desk IC: REJECT")
    assert "oversold bounce" not in result["oneLiner"]
