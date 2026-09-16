from app.services.index_options.quant_v2 import infer_regime_probabilities, score_candidate, select_quant_portfolio


def candidate(strategy="IRON_CONDOR", max_profit=1000, max_loss=1000, eligible=True):
    return {
        "strategyId": strategy,
        "key": "NIFTY",
        "eligible": eligible,
        "maxProfit": max_profit,
        "maxLoss": max_loss,
        "delta": 0.02,
        "gamma": 0.001,
        "vega": -2,
        "legs": [{"spreadPct": 1.0}] * 4,
        "gateEvidence": {
            "breadth": {"directionalScore": 0},
            "futuresOi": {"state": "NEUTRAL"},
            "volatilityEdge": {"ivEdgePoints": 8},
        },
    }


def test_regime_is_probability_simplex():
    p = infer_regime_probabilities(candidate())
    assert abs(sum((p.trend_up, p.trend_down, p.range, p.vol_expansion, p.vol_compression)) - 1.0) < 1e-9


def test_no_trade_is_real_competitor():
    weak = candidate(max_profit=100, max_loss=5000)
    result = select_quant_portfolio([weak])
    assert result["decision"] == "NO_TRADE"
    assert result["selected"] == []
    assert result["noTradeUtility"] == 0.0


def test_defined_risk_candidate_can_be_admitted_when_utility_positive():
    strong = candidate(max_profit=3000, max_loss=1000)
    decision = score_candidate(strong)
    assert decision.utility > 0
    assert decision.decision == "ADMIT"


def test_missing_defined_loss_is_rejected():
    row = candidate(max_profit=1000, max_loss=0)
    decision = score_candidate(row)
    assert decision.decision == "REJECT"
    assert "DEFINED_MAX_LOSS_REQUIRED" in decision.reasons


def test_upstream_ineligible_never_admitted():
    decision = score_candidate(candidate(eligible=False))
    assert decision.decision == "REJECT"
    assert decision.reasons == ("UPSTREAM_INELIGIBLE",)
