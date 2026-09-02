import copy

import pytest

from app.services.exit_plan import (
    attach_exit_plan, evaluate_scale_trail, refresh_exit_policy,
    overwrite_row_with_current_policy,
)
from app.services.eod_intraday_report import _leg_pnl


def position(direction="LONG", qty=100):
    return attach_exit_plan({
        "symbol": "TEST", "direction": direction, "entryPrice": 100.0,
        "riskPerShare": 0.5, "stopLoss": 100.5 if direction == "SHORT" else 99.5,
        "approxQty": qty, "executionStatus": "TRIGGERED",
    })


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("peak", [1.0, 1.5])
def test_partial_scale_does_not_close_remainder_at_breakeven(direction, peak):
    row = position(direction)
    sign = -1 if direction == "SHORT" else 1
    partial = evaluate_scale_trail(row, 100 + sign * peak * 0.5)
    assert partial["realizedPnl"] > 0
    assert partial["remainingQty"] == (80 if peak == 1.0 else 60)
    assert not partial["exitState"]["profitGuardActive"]
    row["exitState"] = partial["exitState"]
    back = evaluate_scale_trail(row, 100)
    assert not back["closed"]
    assert back["effectiveStop"] == row["stopLoss"]
    stopped = evaluate_scale_trail(row, row["stopLoss"])
    assert stopped["stopKind"] == "INITIAL"


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
@pytest.mark.parametrize("qty", [1, 2, 3, 4, 7, 28, 30, 52, 100, 114])
def test_two_r_trailing_exit_locks_full_position_one_r_after_rounding(direction, qty):
    row = position(direction, qty)
    armed = evaluate_scale_trail(row, 99 if direction == "SHORT" else 101)
    assert not armed["closed"]
    row["exitState"] = armed["exitState"]
    closed = evaluate_scale_trail(row, armed["effectiveStop"])
    assert closed["closed"]
    assert closed["stopKind"] == "TRAIL"
    assert closed["realizedPnl"] >= 0.5 * qty
    assert closed["economicR"] >= 1.0
    assert sum(x["qty"] for x in closed["exitState"]["legsFilled"]) == qty


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_initial_stop_and_eod_exit_still_work(direction):
    row = position(direction)
    stopped = evaluate_scale_trail(row, row["stopLoss"])
    assert stopped["realizedPnl"] == -50
    sign = -1 if direction == "SHORT" else 1
    eod = evaluate_scale_trail(row, 100 + sign * 0.1, after_close=True)
    assert eod["closed"]
    assert eod["exitState"]["legsFilled"][-1]["r"] == "EOD_SQUAREOFF"
    assert eod["realizedPnl"] == 10


def test_open_legacy_breakeven_migration_keeps_tranche_fills():
    row = position()
    row["exitState"] = evaluate_scale_trail(row, 100.5)["exitState"]
    row["exitPlan"]["notes"] = ["be_after_1r_scale", "max_stop_0p5pct"]
    row["exitState"]["profitGuardActive"] = True
    row["exitState"]["effectiveStop"] = 100
    fills = copy.deepcopy(row["exitState"]["legsFilled"])
    migrated = refresh_exit_policy(row)
    assert migrated["exitState"]["legsFilled"] == fills
    assert migrated["exitState"]["effectiveStop"] == 99.5
    assert not migrated["exitState"]["profitGuardActive"]
    assert not evaluate_scale_trail(migrated, 100)["closed"]


def test_completed_legacy_fills_are_not_repriced_in_book_or_eod():
    row = position()
    row["exitPlan"]["notes"] = ["be_after_1r_scale", "max_stop_0p5pct"]
    row.update(closed=True, status="CLOSED", realizedPnl=10.0, currentPrice=103)
    row["exitState"] = {
        "closed": True, "remainingQty": 0, "effectiveStop": 100,
        "realizedPnl": 10.0, "mfeR": 1.0, "economicR": 0.2,
        "legsFilled": [
            {"r": 1.0, "qty": 20, "price": 100.5, "pnl": 10.0},
            {"r": "TRAIL_SL", "qty": 80, "price": 100.0, "pnl": 0.0},
        ],
    }
    assert refresh_exit_policy(row) == row
    assert overwrite_row_with_current_policy(row, force=True, after_close=True) == row
    reason, avg, pnl, meta = _leg_pnl(row, after_close=True)
    assert reason == "TRAIL_SL_HIT"
    assert avg == 100.1
    assert pnl == 10
    assert meta["exitState"] == row["exitState"]


def test_swing_retains_its_existing_breakeven_policy():
    row = attach_exit_plan({**position(), "exitPolicyScope": "SWING"})
    row = refresh_exit_policy(row)
    partial = evaluate_scale_trail(row, 100.5)
    assert partial["exitState"]["profitGuardActive"]
    assert partial["effectiveStop"] == 100
    row["exitState"] = partial["exitState"]
    closed = evaluate_scale_trail(row, 100)
    assert closed["closed"]
    assert closed["realizedPnl"] == 10


@pytest.mark.parametrize("kind,price,pnl,reason", [
    ("INITIAL_SL", 99.5, -50, "SL_HIT"),
    ("EOD_SQUAREOFF", 100.1, 10, "EOD_SQUAREOFF"),
])
def test_eod_preserves_completed_stop_and_squareoff_reasons(kind, price, pnl, reason):
    row = position()
    row["closed"] = True
    row["exitState"] = {"closed": True, "realizedPnl": pnl, "remainingQty": 0,
                        "legsFilled": [{"r": kind, "qty": 100, "price": price, "pnl": pnl}]}
    actual, avg, result_pnl, _ = _leg_pnl(row, after_close=True)
    assert (actual, avg, result_pnl) == (reason, price, pnl)
