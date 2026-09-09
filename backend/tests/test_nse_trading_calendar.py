from datetime import date, datetime

from app.services import nse_trading_calendar as calendar
from app.services.desk_clock import basket_lock_allowed, cash_session_phase
from app.services.swing_v2.calendar import session_age


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"CM": [{"tradingDate": "14-Sep-2026"}, {"tradingDate": "25-Dec-2026"}]}


class _Session:
    def __init__(self):
        self.headers = {}

    def get(self, *_args, **_kwargs):
        return _Response()

    def close(self):
        return None


def test_official_cm_calendar_parser():
    assert calendar._fetch_official(_Session) == {date(2026, 9, 14), date(2026, 12, 25)}


def test_holiday_blocks_desk_and_does_not_age_swing():
    holiday_noon = datetime.fromisoformat("2026-09-14T12:00:00+05:30")
    assert calendar.is_nse_trading_day(holiday_noon.date()) is False
    assert basket_lock_allowed(holiday_noon)[0] is False
    assert cash_session_phase(now=holiday_noon) == "CLOSED"
    assert session_age(date(2026, 9, 11), date(2026, 9, 15)) == 1
