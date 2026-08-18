from datetime import date, datetime, timezone, timedelta

from app.services.desk_clock import cash_session_phase
from app.services.eod_intraday_report import _exit_reason_from_scale_eval, _leg_pnl


IST = timezone(timedelta(hours=5, minutes=30))


def test_current_session_applies_scale_trail_without_eod_squareoff():
    pick = {
        "symbol": "TEST",
        "direction": "LONG",
        "entryPrice": 100.0,
        "currentPrice": 101.0,
        "stopLoss": 99.5,
        "target1": 100.75,
        "target2": 101.5,
        "approxQty": 10,
    }
    reason, _, pnl, _ = _leg_pnl(pick, after_close=False)
    assert reason == "OPEN"
    # 0.5% 1R; at +2R scale legs are booked and the 40% runner stays MTM.
    assert pnl == 8.5


def test_cash_session_phase_is_open_before_cash_close():
    now = datetime(2026, 8, 12, 12, 0, tzinfo=IST)
    assert cash_session_phase(date(2026, 8, 12), now) == "OPEN"


def test_cash_session_phase_is_closed_after_cash_close():
    now = datetime(2026, 8, 12, 15, 31, tzinfo=IST)
    assert cash_session_phase(date(2026, 8, 12), now) == "CLOSED"


def test_initial_stop_and_activated_trail_are_not_conflated():
    assert _exit_reason_from_scale_eval({
        "hitLevel": "sl",
        "stopKind": "INITIAL",
        "label": "INITIAL STOP HIT",
        "exitState": {"legsFilled": [{"r": "INITIAL_SL"}]},
    }) == "SL_HIT"
    assert _exit_reason_from_scale_eval({
        "hitLevel": "sl",
        "stopKind": "TRAIL",
        "label": "TRAIL STOP HIT",
        "exitState": {"legsFilled": [{"r": "TRAIL_SL"}]},
    }) == "TRAIL_SL_HIT"
