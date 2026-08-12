from datetime import date

from app.services.eod_archive import pick_session_date


def test_pick_session_date_prefers_explicit_session_date():
    pick = {
        "sessionDate": "2026-08-11",
        "updatedAt": "2026-08-12T04:00:00+00:00",
    }
    assert pick_session_date(pick) == date(2026, 8, 11)


def test_pick_session_date_uses_persisted_timestamp_for_legacy_rows():
    pick = {"updatedAt": "2026-07-22T11:47:19.238471+00:00"}
    assert pick_session_date(pick) == date(2026, 7, 22)
