from app.services.quant_desk_exit_policy import (
    R_RATCHET,
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
    assert locked_r_for_mfe(0.25) == -0.25
    assert locked_r_for_mfe(0.50) == 0.0
    assert locked_r_for_mfe(0.75) == 0.25
    assert locked_r_for_mfe(1.00) == 0.50
    assert locked_r_for_mfe(1.50) == 1.0
    assert locked_r_for_mfe(2.00) == 1.25
    assert locked_r_for_mfe(3.00) == 2.0
    assert locked_r_for_mfe(4.00) == 3.0
    assert locked_r_for_mfe(5.00) == 4.0


def test_exit_labels_separate_execution_from_diagnostic_miss():
    assert desk_exit_label("TRAIL_SL_HIT", -100) == "TRAIL_STOP"
    assert desk_exit_label("TRAIL_SL_HIT", 500) == "TRAIL_STOP"
    assert desk_exit_label("EOD_SQUAREOFF", 500) == "EOD_SQUAREOFF"
    assert desk_exit_label("EOD_SQUAREOFF", -100) == "EOD_SQUAREOFF"
