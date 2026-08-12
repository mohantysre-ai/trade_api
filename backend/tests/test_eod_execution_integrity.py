from datetime import date, datetime, timezone, timedelta

from app.services.desk_clock import cash_session_phase
from app.services.eod_intraday_report import _exit_reason_from_scale_eval, _leg_pnl


IST = timezone(timedelta(hours=5, minutes=30))


def test_current_session_applies_scale_trail_without_eod_squareoff():
    pick = {
        "symbol": "TEST",
        "direction": "LONG",
        "entryPrice": 100.0,
        "currentPrice": 110.0,
        "stopLoss": 95.0,
        "target1": 115.0,
        "target2": 120.0,
        "approxQty": 10,
    }
    reason, _, pnl, _ = _leg_pnl(pick, after_close=False)
    assert reason == "OPEN"
    # At +2R, configured scale legs are booked and the remainder stays MTM.
    assert pnl == 85.0


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
