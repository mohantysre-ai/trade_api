from app.services.exit_plan import RUNNER_FRAC, TRAIL_RATCHET, build_exit_plan
from app.services.desk_clock import rotation_window_allowed
from datetime import datetime, timedelta, timezone


def test_r_ladder_and_runner_are_preserved():
    assert set((0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)).issubset(TRAIL_RATCHET)
    assert RUNNER_FRAC == 0.40
    plan = build_exit_plan(100, 10, "LONG", 100, initial_stop=90)
    assert plan["target1"] == 115.0
    assert plan["target2"] == 130.0
    assert plan["runnerQty"] == 40


def test_replacements_remain_open_after_noon_and_in_afternoon():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert rotation_window_allowed(datetime(2026, 8, 12, 12, 0, tzinfo=ist)) == (True, "continuation")
    assert rotation_window_allowed(datetime(2026, 8, 12, 14, 0, tzinfo=ist)) == (True, "afternoon")
    assert rotation_window_allowed(datetime(2026, 8, 12, 14, 46, tzinfo=ist))[0] is False
