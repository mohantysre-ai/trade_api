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


def test_scale_legs_sum_with_40pct_runner():
    leg_sum = sum(pct for _, pct in SCALE_LEGS) + RUNNER_FRACTION
    assert abs(leg_sum - 1.0) < 1e-9
    assert RUNNER_FRACTION == 0.40
    assert SCALE_LEGS == tuple(EXIT_SCALE_LEGS)
    assert RUNNER_FRACTION == RUNNER_FRAC
    assert abs(PROFIT_GUARD_LOCK_R - 0.0) < 1e-9
    assert abs(PROFIT_GUARD_TRIGGER_R - 0.25) < 1e-9
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
    assert skip["economicR"] is None
    assert skip["pathR"] is None

    forced = classify_desk_outcome(
        triggered=False,
        realized_pnl=-999.34,
        exit_reason="TRAIL_SL_HIT",
        current_r=-0.4,
        exit_state={"rMultiple": -0.4, "economicR": -0.4, "effectiveStop": 100.0, "legsFilled": []},
        entry=105.0,
        exit_price=100.0,
        risk_per_share=5.0,
        qty=50,
        direction="LONG",
        effective_stop=100.0,
    )
    assert forced["executionStatus"] == "TRIGGERED"
    assert forced["pnl"] == -999.34
    assert forced["outcomeBucket"] == "LOSS"
    assert forced["deskExitLabel"] == "TRAIL_STOP"
    assert forced["deskProgress"]
    assert "MFE" in forced["deskProgress"]
    # economicR = -999.34 / (5 * 50) = -3.997
    assert forced["economicR"] is not None
    assert forced["economicR"] < 0
    assert forced["rMultiple"] == forced["economicR"]
    assert outcome_bucket(execution_status="TRIGGERED", pnl=10) == "WIN"


def test_build_trade_outcome_splits_economic_and_path_r():
    from app.services.quant_desk_exit_policy import build_trade_outcome

    # Negative Book P&L with positive path exit (scale / qty mismatch case)
    out = build_trade_outcome(
        triggered=True,
        realized_pnl=-399.84,
        exit_reason="EOD_SQUAREOFF",
        entry=100.0,
        exit_price=100.5,  # path slightly positive
        risk_per_share=2.0,
        qty=200,
        direction="LONG",
        day_high=101.0,
        day_low=99.0,
    )
    assert out["outcomeBucket"] == "LOSS"
    assert out["economicR"] is not None and out["economicR"] < 0
    assert out["pathR"] is not None and out["pathR"] > 0
    assert out["rMultiple"] == out["economicR"]


def test_hindzinc_entry_failure_taxonomy():
    from app.services.quant_desk_exit_policy import build_trade_outcome

    out = build_trade_outcome(
        triggered=True,
        realized_pnl=-1531.0,
        exit_reason="SL_HIT",
        entry=100.0,
        exit_price=98.0,
        risk_per_share=2.0,
        qty=765,
        direction="LONG",
        day_high=99.5,  # never greened meaningfully
        day_low=98.0,
        stop_utilization=1.0,
    )
    assert out["outcomeBucket"] == "LOSS"
    assert out["mfeR"] is not None and out["mfeR"] < 0.10
    assert out["rootCause"] == "ENTRY_FAILURE"
    assert "NO_FAVOURABLE_EXCURSION" in out["factors"]


def test_positive_eod_is_win_with_partial_followthrough():
    from app.services.quant_desk_exit_policy import build_trade_outcome

    out = build_trade_outcome(
        triggered=True,
        realized_pnl=500.0,
        exit_reason="EOD_SQUAREOFF",
        entry=100.0,
        exit_price=101.0,
        risk_per_share=2.0,
        qty=100,
        direction="LONG",
        day_high=102.0,
        day_low=99.5,
    )
    assert out["outcomeBucket"] == "WIN"
    assert out["economicR"] > 0
    assert out["rootCause"] == "PARTIAL_FOLLOWTHROUGH"
    assert "EOD_FORCED_EXIT" in out["factors"]


def test_exit_plan_emits_path_and_economic_r():
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
    result = evaluate_scale_trail(pick, ltp=102.0, after_close=False)
    assert result["economicR"] == result["rMultiple"] == 1.0
    assert result["pathR"] == 1.0
    assert result["exitState"]["economicR"] == 1.0
    assert result["exitState"]["pathR"] == 1.0


def test_inverted_long_stop_is_repaired():
    pick = attach_exit_plan(
        {
            "symbol": "ABFRL",
            "direction": "LONG",
            "entryPrice": 59.29,
            "riskPerShare": 1.11,
            "stopLoss": 60.40,
            "approxQty": 1686,
        }
    )
    assert pick["riskModelValid"] is True
    assert pick["stopRepaired"] is True
    assert pick["stopLoss"] < pick["entryPrice"]
    assert pick["exitPlan"]["initialStop"] < pick["entryPrice"]


def test_economic_r_matches_book_pnl_after_scale():
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
    result = evaluate_scale_trail(pick, ltp=102.0, after_close=False)
    # Only the 1R leg is crossed; 20 shares are booked at 102 and 80 remain at 102.
    # Economic P&L = 100 * (102-100) = ₹200, hence +1.00R.
    assert result["economicPnl"] == 200.0
    assert result["rMultiple"] == 1.0
    assert result["exitState"]["rMultiple"] == 1.0


def test_cold_path_full_stop_then_be_after_025r():
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
    cold = evaluate_scale_trail(pick, ltp=98.0, after_close=False)
    assert cold.get("hitLevel") == "sl"
    assert cold.get("stopKind") == "INITIAL"
    assert cold.get("label") == "INITIAL STOP HIT"
    assert cold["exitState"]["legsFilled"][-1]["r"] == "INITIAL_SL"
    assert cold["exitState"]["mfeR"] == 0.0
    assert cold["exitState"]["effectiveStop"] == 98.0
    assert cold["economicPnl"] == -200.0
    assert cold["rMultiple"] == -1.0

    greened = evaluate_scale_trail(pick, ltp=100.5, after_close=False)
    assert greened["exitState"]["mfeR"] >= 0.25
    assert greened["exitState"]["effectiveStop"] == 100.0
    assert greened["exitState"]["profitGuardActive"] is True

    pulled = dict(pick)
    pulled["exitState"] = greened["exitState"]
    hit = evaluate_scale_trail(pulled, ltp=99.99, after_close=False)
    assert hit.get("hitLevel") == "sl"
    assert hit.get("stopKind") == "TRAIL"
    assert hit["exitState"]["legsFilled"][-1]["r"] == "TRAIL_SL"
    assert hit["economicPnl"] == 0.0
    assert hit["rMultiple"] == 0.0


def test_excursions_never_use_the_wrong_sign():
    from app.services.quant_desk_exit_policy import build_trade_outcome

    losing = build_trade_outcome(
        triggered=True,
        realized_pnl=-200.0,
        exit_reason="SL_HIT",
        entry=100.0,
        exit_price=98.0,
        risk_per_share=2.0,
        qty=100,
        direction="LONG",
        day_high=99.5,
        day_low=98.0,
    )
    assert losing["mfeR"] == 0.0
    assert losing["maeR"] == -1.0

    winning = build_trade_outcome(
        triggered=True,
        realized_pnl=100.0,
        exit_reason="EOD_SQUAREOFF",
        entry=100.0,
        exit_price=101.0,
        risk_per_share=2.0,
        qty=100,
        direction="LONG",
    )
    assert winning["mfeR"] == 0.5
    assert winning["maeR"] == 0.0
