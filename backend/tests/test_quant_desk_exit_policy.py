from app.services.exit_plan import (
    PROFIT_GUARD_LOCK_R,
    PROFIT_GUARD_TRIGGER_R,
    RUNNER_FRAC,
    SCALE_LEGS as EXIT_SCALE_LEGS,
    TRAIL_RATCHET,
    attach_exit_plan,
    evaluate_scale_trail,
)
from app.services.quant_desk_exit_policy import (
    R_RATCHET,
    RUNNER_FRACTION,
    SCALE_LEGS,
    canonical_pnl,
    desk_exit_label,
    execution_truth,
    locked_r_for_mfe,
)


def test_not_triggered_is_always_zero_pnl():
    assert canonical_pnl(execution_status="NOT_TRIGGERED", realized_pnl=-2500) == 0.0
    assert execution_truth(triggered=False, realized_pnl=0.0) == "NOT_TRIGGERED"


def test_realized_book_pnl_overrides_forensic_trigger_flag():
    assert execution_truth(triggered=False, realized_pnl=-999.34) == "TRIGGERED"
    assert execution_truth(triggered=False, realized_pnl=2525.66) == "TRIGGERED"


def test_r_ratchet_is_monotonic_and_break_even_then_profit():
    assert locked_r_for_mfe(0.10) == -1.0
    assert locked_r_for_mfe(0.25) == 0.0
    assert locked_r_for_mfe(0.50) == 0.25
    assert locked_r_for_mfe(0.75) == 0.50
    assert locked_r_for_mfe(1.00) == 0.75
    assert locked_r_for_mfe(1.25) == 1.0
    assert locked_r_for_mfe(1.50) == 1.25
    assert locked_r_for_mfe(2.00) == 1.50
    assert locked_r_for_mfe(3.00) == 2.25
    assert locked_r_for_mfe(4.00) == 3.25
    assert locked_r_for_mfe(5.00) == 4.25


def test_scale_legs_sum_with_runner():
    leg_sum = sum(pct for _, pct in SCALE_LEGS) + RUNNER_FRACTION
    assert abs(leg_sum - 1.0) < 1e-9
    assert RUNNER_FRACTION == 0.30
    assert SCALE_LEGS == tuple(EXIT_SCALE_LEGS)
    assert RUNNER_FRACTION == RUNNER_FRAC
    assert abs(PROFIT_GUARD_LOCK_R - 0.0) < 1e-9
    assert abs(PROFIT_GUARD_TRIGGER_R - 0.25) < 1e-9
    # Policy ratchet mirrors live TRAIL_RATCHET
    assert tuple(R_RATCHET) == tuple(TRAIL_RATCHET.items())


def test_exit_labels_separate_execution_from_diagnostic_miss():
    assert desk_exit_label("TRAIL_SL_HIT", -100) == "TRAIL_STOP"
    assert desk_exit_label("TRAIL_SL_HIT", 500) == "TRAIL_STOP"
    assert desk_exit_label("EOD_SQUAREOFF", 500) == "EOD_SQUAREOFF"
    assert desk_exit_label("EOD_SQUAREOFF", -100) == "EOD_SQUAREOFF"


def test_classify_desk_outcome_chain_order():
    from app.services.quant_desk_exit_policy import classify_desk_outcome, outcome_bucket

    skip = classify_desk_outcome(triggered=False, realized_pnl=0.0, exit_reason="NOT_TRIGGERED")
    assert skip["executionStatus"] == "NOT_TRIGGERED"
    assert skip["pnl"] == 0.0
    assert skip["outcomeBucket"] == "SKIPPED"
    assert skip["deskExitLabel"] == "SKIPPED"
    assert skip["chain"][0] == "execution_truth"

    forced = classify_desk_outcome(
        triggered=False,
        realized_pnl=-999.34,
        exit_reason="TRAIL_SL_HIT",
        current_r=-0.4,
        exit_state={"rMultiple": -0.4, "effectiveStop": 100.0, "legsFilled": []},
        entry=105.0,
        risk_per_share=5.0,
        direction="LONG",
        effective_stop=100.0,
    )
    assert forced["executionStatus"] == "TRIGGERED"
    assert forced["pnl"] == -999.34
    assert forced["outcomeBucket"] == "LOSS"
    assert forced["deskExitLabel"] == "TRAIL_STOP"
    assert forced["deskProgress"]
    assert "MFE" in forced["deskProgress"]
    assert outcome_bucket(execution_status="TRIGGERED", pnl=10) == "WIN"


def test_r_ratchet_tuple_nonempty():
    assert len(R_RATCHET) >= 5


def test_cold_path_full_stop_then_be_after_025r():
    """Cold loser still −1R; after +0.25R MFE stop is BE not initial SL."""
    pick = attach_exit_plan(
        {
            "symbol": "TEST",
            "direction": "LONG",
            "entryPrice": 100.0,
            "riskPerShare": 2.0,
            "stopLoss": 98.0,
            "approxQty": 100,
        }
    )
    plan = pick["exitPlan"]
    assert plan["runnerFrac"] == 0.30
    assert [leg["r"] for leg in plan["legs"]] == [1.0, 1.5, 2.0]

    cold = evaluate_scale_trail(pick, ltp=98.0, after_close=False)
    assert cold.get("hitLevel") == "sl"
    assert cold["exitState"]["effectiveStop"] == 98.0
    assert cold["realizedPnl"] == -200.0  # 100 * (98-100)

    greened = evaluate_scale_trail(pick, ltp=100.5, after_close=False)  # +0.25R
    assert greened["exitState"]["mfeR"] >= 0.25
    assert greened["exitState"]["effectiveStop"] == 100.0  # BE
    assert greened["exitState"]["profitGuardActive"] is True

    # Pullback after green should trail at BE, not reopen −1R
    pulled = dict(pick)
    pulled["exitState"] = greened["exitState"]
    be_stop = evaluate_scale_trail(pulled, ltp=100.0, after_close=False)
    assert be_stop["exitState"]["effectiveStop"] == 100.0
    hit = evaluate_scale_trail(pulled, ltp=99.99, after_close=False)
    assert hit.get("hitLevel") == "sl"
    assert hit["realizedPnl"] == 0.0
