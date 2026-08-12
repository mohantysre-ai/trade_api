from datetime import date

from app.services.intraday_execution_evidence import candle_entry_evidence, mark_not_triggered


def test_crossing_before_lock_is_not_a_fill():
    pick = {"symbol": "X", "direction": "LONG", "entryPrice": 100, "deployedCapital": 1000}
    candles = [
        {"ts": "2026-08-12T11:47:00+05:30", "low": 99, "high": 101},
        {"ts": "2026-08-12T11:49:00+05:30", "low": 95, "high": 99},
    ]
    ev = candle_entry_evidence(
        pick, candles, session_date=date(2026, 8, 12),
        committed_at="2026-08-12T06:18:06+00:00",
    )
    assert ev["triggered"] is False
    fixed = mark_not_triggered(pick, ev)
    assert fixed["deployedCapital"] == 0
    assert fixed["plannedCapital"] == 1000
    assert fixed["totalPnl"] == 0


def test_crossing_after_cutoff_is_not_a_fill():
    ev = candle_entry_evidence(
        {"direction": "LONG", "entryPrice": 100},
        [{"ts": "2026-08-12T14:50:00+05:30", "low": 99, "high": 101}],
        session_date=date(2026, 8, 12), committed_at="2026-08-12T06:18:06+00:00",
    )
    assert ev["triggered"] is False


def test_valid_post_lock_crossing_records_timestamp():
    ev = candle_entry_evidence(
        {"direction": "LONG", "entryPrice": 100},
        [
            {"ts": "2026-08-12T12:00:00+05:30", "low": 99, "high": 101},
            {"ts": "2026-08-12T12:01:00+05:30", "low": 98, "high": 103},
            {"ts": "2026-08-12T15:31:00+05:30", "low": 90, "high": 110},
        ],
        session_date=date(2026, 8, 12), committed_at="2026-08-12T06:18:06+00:00",
    )
    assert ev["triggered"] is True
    assert ev["triggeredAt"] == "2026-08-12T12:00:00+05:30"
    assert ev["postEntryHigh"] == 103
    assert ev["postEntryLow"] == 98
