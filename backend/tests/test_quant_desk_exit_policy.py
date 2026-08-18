from app.services.exit_plan import (
    PROFIT_GUARD_LOCK_R,
    PROFIT_GUARD_TRIGGER_R,
    RUNNER_FRAC,
    SCALE_LEGS as EXIT_SCALE_LEGS,
    TRAIL_RATCHET,
    attach_exit_plan,
    evaluate_scale_trail,
    evaluate_scale_trail_path,
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


def test_refresh_exit_policy_rewrites_notes_keeps_booked_state():
    from app.services.exit_plan import EXIT_POLICY_VERSION, refresh_exit_policy

    pick = attach_exit_plan(
        {
            "symbol": "NTPC",
            "direction": "LONG",
            "entryPrice": 100.0,
            "riskPerShare": 2.0,
            "stopLoss": 98.0,
            "approxQty": 50,
        }
    )
    pick["exitPlan"]["notes"] = ["40pct_runner", "be_at_0p25r"]
    pick["exitPlan"]["trailRatchet"] = {"0.25": 0.0, "0.5": 0.25}
    pick["exitState"] = {"mfeR": 0.277, "effectiveStop": 100.0, "closed": True, "realizedPnl": 0.0}
    pick["closed"] = True
    pick["status"] = "CLOSED"
    out = refresh_exit_policy(pick, keep_exit_state=True)
    assert "be_at_0p5r" in (out["exitPlan"]["notes"] or [])
    assert "max_stop_0p5pct" in (out["exitPlan"]["notes"] or [])
    assert out["exitPlan"]["policyVersion"] == EXIT_POLICY_VERSION
    assert out["exitState"]["effectiveStop"] == 100.0
    assert out["bookedExitPlan"]["notes"] == ["40pct_runner", "be_at_0p25r"]


def test_overwrite_booked_path_with_0p5r_policy():
    from app.services.exit_plan import EXIT_POLICY_VERSION, overwrite_row_with_current_policy

    row = {
        "symbol": "AARTIIND",
        "direction": "LONG",
        "entryPrice": 534.0,
        "stopLoss": 521.7,
        "approxQty": 374,
        "ltp": 538.30,
        "sessionHigh": 540.4,
        "sessionLow": 529.2,
        "executionStatus": "TRIGGERED",
        "status": "CLOSED",
        "totalPnl": 1151.92,
        "outcome": {"label": "TRAIL STOP HIT"},
        "exitState": {"mfeR": 0.52, "economicPnl": 1151.92, "initialStop": 521.7},
    }
    out = overwrite_row_with_current_policy(row, after_close=False, force=True)
    assert out["exitPlan"]["policyVersion"] == EXIT_POLICY_VERSION
    assert "be_at_0p5r" in (out["exitPlan"]["notes"] or [])
    assert out["exitState"]["policyVersion"] == EXIT_POLICY_VERSION
    assert out["totalPnl"] != 1151.92
    assert out["pnl"] == out["totalPnl"]
    assert out["mfeR"] is not None


def test_refresh_exit_policy_keeps_open_book_stop():
    from app.services.exit_plan import refresh_exit_policy

    pick = attach_exit_plan(
        {
            "symbol": "NESTLEIND",
            "direction": "LONG",
            "entryPrice": 1514.10,
            "stopLoss": 1471.95,
            "approxQty": 10,
        }
    )
    pick["exitPlan"]["notes"] = ["40pct_runner", "be_at_0p25r"]
    out = refresh_exit_policy(pick, keep_exit_state=True)
    assert out["stopLoss"] == 1471.95
    assert out["exitPlan"]["initialStop"] == 1471.95
    assert "be_at_0p5r" in (out["exitPlan"]["notes"] or [])
    assert "max_stop_0p5pct" in (out["exitPlan"]["notes"] or [])


def test_not_triggered_is_always_zero_pnl():
    assert canonical_pnl(execution_status="NOT_TRIGGERED", realized_pnl=-2500) == 0.0
    assert execution_truth(triggered=False, realized_pnl=0.0) == "NOT_TRIGGERED"


def test_realized_book_pnl_overrides_forensic_trigger_flag():
    assert execution_truth(triggered=False, realized_pnl=-999.34) == "TRIGGERED"
    assert execution_truth(triggered=False, realized_pnl=2525.66) == "TRIGGERED"


def test_r_ratchet_is_monotonic_and_break_even_then_profit():
    assert locked_r_for_mfe(0.10) == -1.0
    assert locked_r_for_mfe(0.25) == -1.0
    assert locked_r_for_mfe(0.49) == -1.0
    assert locked_r_for_mfe(0.50) == 0.0
    assert locked_r_for_mfe(0.99) == 0.0
    assert locked_r_for_mfe(1.00) == 0.0
    assert locked_r_for_mfe(1.50) == 0.0
    assert locked_r_for_mfe(2.00) == 0.50
    assert locked_r_for_mfe(3.00) == 1.50
    assert locked_r_for_mfe(4.00) == 2.50
    assert locked_r_for_mfe(5.00) == 3.50


def test_scale_legs_sum_with_40pct_runner():
    leg_sum = sum(pct for _, pct in SCALE_LEGS) + RUNNER_FRACTION
    assert abs(leg_sum - 1.0) < 1e-9
    assert RUNNER_FRACTION == 0.40
    assert SCALE_LEGS == tuple(EXIT_SCALE_LEGS)
    assert RUNNER_FRACTION == RUNNER_FRAC
    assert abs(PROFIT_GUARD_LOCK_R - 0.0) < 1e-9
    assert abs(PROFIT_GUARD_TRIGGER_R - 0.5) < 1e-9
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


def test_cold_path_full_stop_then_be_after_0p5r():
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

    noise = evaluate_scale_trail(pick, ltp=100.8, after_close=False)
    assert noise["exitState"]["mfeR"] == 0.4
    assert noise["exitState"]["effectiveStop"] == 98.0
    assert noise["exitState"]["profitGuardActive"] is False
    assert noise.get("hitLevel") is None

    greened = evaluate_scale_trail(pick, ltp=101.0, after_close=False)
    assert greened["exitState"]["mfeR"] >= 0.5
    assert greened["exitState"]["profitGuardActive"] is True
    # 0.5R BE plus 0.5% trail from MFE 101 → 100.50 (tighter than BE).
    assert greened["exitState"]["effectiveStop"] == 100.50

    pulled = dict(pick)
    pulled["exitState"] = greened["exitState"]
    hit = evaluate_scale_trail(pulled, ltp=100.49, after_close=False)
    assert hit.get("hitLevel") == "sl"
    assert hit.get("stopKind") == "TRAIL"
    assert hit["exitState"]["legsFilled"][-1]["r"] == "TRAIL_SL"


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


def test_aartiind_0p52r_trails_to_pct_stop():
    pick = attach_exit_plan({
        "symbol": "AARTIIND",
        "direction": "LONG",
        "entryPrice": 534.0,
        "stopLoss": 521.7,
        "riskPerShare": 12.3,
        "approxQty": 374,
        "target1": 552.45,
        "target2": 570.9,
    })
    bogus = evaluate_scale_trail(dict(pick), 487.9, after_close=False)
    assert bogus["exitState"]["legsFilled"][0]["r"] == "INITIAL_SL"
    assert bogus["exitState"]["mfeR"] == 0.0
    assert bogus["pathR"] == -3.748

    # Session high 540.40 = +0.52R — 0.5R guard + 0.5% trail from high.
    path = evaluate_scale_trail_path(dict(pick), 533.15, 540.40, 529.20, after_close=False)
    assert path["exitState"]["profitGuardActive"] is True
    assert path["exitState"]["mfeR"] == 0.52
    assert path.get("stopKind") == "TRAIL"
    assert path.get("hitLevel") == "sl"


def test_live_scale_rejects_one_poll_crash_tick():
    from app.services.trade_outcome import _evaluate_live_scale_trail, _plausible_live_mark

    assert _plausible_live_mark(entry=534.0, risk=12.3, last_mark=539.0, new_mark=487.9, direction="LONG") is False
    pick = attach_exit_plan({
        "symbol": "TESTCRASH",
        "direction": "LONG",
        "entryPrice": 534.0,
        "stopLoss": 521.7,
        "riskPerShare": 12.3,
        "approxQty": 374,
        "ltp": 539.0,
        "sessionHigh": 539.0,
        "sessionLow": 535.0,
    })
    live = _evaluate_live_scale_trail(pick, 487.9, after_close=False)
    assert live.get("closed") is not True
    assert live.get("exitState", {}).get("legsFilled") == []


def test_half_pct_stop_gap_print_is_a_real_hit():
    from app.services.exit_plan import apply_max_stop_cap, overwrite_row_with_current_policy
    from app.services.trade_outcome import _evaluate_live_scale_trail, _plausible_live_mark

    assert _plausible_live_mark(
        entry=1253.8, risk=6.27, last_mark=1253.8, new_mark=1202.0, direction="LONG"
    ) is True
    pick = attach_exit_plan({
        "symbol": "GODREJIND",
        "direction": "LONG",
        "entryPrice": 1253.8,
        "stopLoss": 1247.53,
        "riskPerShare": 6.27,
        "approxQty": 159,
        "ltp": 1253.8,
    })
    live = _evaluate_live_scale_trail(pick, 1202.0, after_close=False)
    assert live.get("closed") is True
    assert live.get("hitLevel") == "sl"

    wide = apply_max_stop_cap({
        "symbol": "GODREJIND",
        "direction": "LONG",
        "entryPrice": 1253.8,
        "stopLoss": 1276.68,
        "approxQty": 159,
        "ltp": 1253.8,
    })
    assert wide["stopLoss"] == 1247.53
    replayed = overwrite_row_with_current_policy(
        wide,
        quotes={"GODREJIND": {"high": 1263.4, "low": 1199.0}},
        force=True,
    )
    assert replayed.get("closed") is True


def test_corrupt_current_policy_state_is_replayed_not_trusted():
    from app.services.exit_plan import (
        EXIT_POLICY_VERSION,
        _exit_state_is_sane,
        attach_exit_plan,
        overwrite_row_with_current_policy,
    )

    pick = attach_exit_plan({
        "symbol": "PPLPHARMA",
        "direction": "LONG",
        "entryPrice": 212.84,
        "stopLoss": 211.78,
        "riskPerShare": 1.06,
        "approxQty": 939,
        "ltp": 210.0,
        "sessionHigh": 214.0,
        "sessionLow": 209.5,
        "closed": True,
        "status": "CLOSED",
    })
    pick["exitState"] = {
        "policyVersion": EXIT_POLICY_VERSION,
        "mfeR": 14_102_287_123.0,
        "effectiveStop": 14_949_334_8377.70,
        "realizedPnl": 56_060_005_562_719.27,
        "legsFilled": [{
            "r": "TRAIL_SL",
            "qty": 939,
            "price": 14_949_334_8377.70,
            "pnl": 56_060_005_562_719.27,
        }],
    }

    assert _exit_state_is_sane(pick, pick["exitState"]) is False
    replayed = overwrite_row_with_current_policy(
        pick,
        quotes={"PPLPHARMA": {"high": 214.0, "low": 209.5}},
        after_close=False,
    )

    assert replayed["effectiveStop"] < pick["entryPrice"] * 1.5
    assert abs(replayed["realizedPnl"]) <= pick["entryPrice"] * pick["approxQty"] * 0.5
    assert replayed["exitState"]["mfeR"] <= 40.0


def test_evaluator_discards_corrupt_prior_mfe_and_stop():
    from app.services.exit_plan import EXIT_POLICY_VERSION, attach_exit_plan, evaluate_scale_trail_path

    pick = attach_exit_plan({
        "symbol": "UNOMINDA",
        "direction": "LONG",
        "entryPrice": 1247.0,
        "stopLoss": 1240.77,
        "riskPerShare": 6.23,
        "approxQty": 160,
    })
    pick["exitState"] = {
        "policyVersion": EXIT_POLICY_VERSION,
        "mfeR": 999_999.0,
        "effectiveStop": 4668.87,
        "realizedPnl": 219_896.96,
        "legsFilled": [],
    }

    result = evaluate_scale_trail_path(
        pick, 1247.0, day_high=1255.0, day_low=1239.0, after_close=False,
    )

    assert result["effectiveStop"] < 1300.0
    assert abs(result["realizedPnl"]) < 10_000.0
    assert result["exitState"]["mfeR"] < 10.0


def test_candle_walk_stops_before_later_high():
    from app.services.exit_plan import attach_exit_plan, evaluate_scale_trail_candles

    pick = attach_exit_plan({
        "symbol": "STOPFIRST",
        "direction": "LONG",
        "entryPrice": 100.0,
        "stopLoss": 99.5,
        "riskPerShare": 0.5,
        "approxQty": 200,
    })
    result = evaluate_scale_trail_candles(
        pick,
        [
            (102.0, 99.4, 99.6),
            (110.0, 100.0, 109.0),
        ],
        after_close=True,
    )
    assert result["closed"] is True
    assert result["exitState"]["mfeR"] < 2.0
    assert abs(float(result["realizedPnl"])) <= 200 * 0.5 + 1.0
    fill = result["exitState"]["legsFilled"][-1]
    assert fill["r"] in ("INITIAL_SL", "TRAIL_SL")
    assert fill["price"] < 101.0


def test_ghost_mfe_does_not_invent_session_high():
    from app.services.exit_plan import EXIT_POLICY_VERSION, attach_exit_plan, overwrite_row_with_current_policy

    pick = attach_exit_plan({
        "symbol": "GRSE",
        "direction": "LONG",
        "entryPrice": 2644.8,
        "stopLoss": 2631.58,
        "riskPerShare": 13.224,
        "approxQty": 75,
        "ltp": 2677.0,
        "sessionHigh": 2677.0,
        "sessionLow": 2630.0,
        "closed": True,
    })
    pick["exitState"] = {
        "policyVersion": EXIT_POLICY_VERSION,
        "mfeR": 84.0,
        "effectiveStop": 3735.64,
        "realizedPnl": 80_000.0,
        "legsFilled": [{"r": "TRAIL_SL", "qty": 75, "price": 3735.64, "pnl": 80_000.0}],
    }
    replayed = overwrite_row_with_current_policy(
        pick,
        quotes={"GRSE": {"high": 2677.0, "low": 2630.0}},
        after_close=True,
        force=True,
    )
    assert replayed["effectiveStop"] < 2700.0
    assert float(replayed["realizedPnl"] or 0) < 20_000.0
    ohlc = overwrite_row_with_current_policy(
        pick,
        after_close=True,
        force=True,
        ohlc_bars=[(3735.64, 2600.0, 2640.0), (2677.0, 2630.0, 2677.0)],
    )
    # First bar adverse 2600 hits 0.5% SL; 3735 is implausible vs 1.50 ratio anyway.
    assert ohlc["effectiveStop"] < 2700.0
    assert float(ohlc["realizedPnl"] or 0) < 5_000.0
    legs = (ohlc.get("exitState") or {}).get("legsFilled") or []
    assert all(float(leg.get("price") or 0) < 2700.0 for leg in legs if isinstance(leg, dict))


def test_post_entry_bars_drop_pre_fill_spike():
    from datetime import date

    from app.services.intraday_execution_evidence import post_entry_ohlc_bars

    candles = [
        {"ts": "2026-08-18T09:30:00+05:30", "high": 3735.64, "low": 2600.0, "close": 2640.0},
        {"ts": "2026-08-18T12:09:00+05:30", "high": 2677.0, "low": 2630.0, "close": 2677.0},
        {"ts": "2026-08-18T15:31:00+05:30", "high": 4000.0, "low": 2000.0, "close": 3000.0},
    ]
    bars = post_entry_ohlc_bars(
        candles,
        entry_at="2026-08-18T12:09:00+05:30",
        session_date=date(2026, 8, 18),
    )
    assert bars == [(2677.0, 2630.0, 2677.0)]
