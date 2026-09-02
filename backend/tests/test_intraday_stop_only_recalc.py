from datetime import date
from unittest.mock import patch

import pytest

from app.services.eod_intraday_report import _replay_triggered_row
from app.services.intraday_execution_evidence import post_entry_ohlc_events

DAY = date(2026, 9, 2)

def candles(*rows):
    return {"candles": [
        {"ts": ts, "open": close, "high": high, "low": low, "close": close}
        for ts, high, low, close in rows
    ]}

def row(direction="LONG", qty=100):
    return {
        "symbol": "TEST", "direction": direction, "entryPrice": 100.0,
        "approxQty": qty, "triggered": True, "executionStatus": "TRIGGERED",
        "triggeredAt": "2026-09-02T10:00:00+05:30",
        "closed": True, "status": "TRAIL STOP HIT", "realizedPnl": 10,
        "exitPrice": 100.1, "exitReason": "TRAIL_SL_HIT",
    }

def replay(raw, payload):
    with patch("app.services.eod_engine.ingestion.load_persisted_candles", return_value=payload):
        return _replay_triggered_row(raw, for_date=DAY, after_close=True)

def test_pre_entry_stop_is_ignored_and_small_profit_remains_running():
    out = replay(row(), candles(
        ("2026-09-02T09:59:00+05:30", 100.1, 99.0, 99.2),
        ("2026-09-02T10:00:00+05:30", 100.4, 99.7, 100.1),
        ("2026-09-02T15:30:00+05:30", 100.3, 100.0, 100.1),
    ))
    assert out["status"] == "RUNNING"
    assert out["closed"] is False
    assert out["exitReason"] == "OPEN"
    assert out["realizedPnl"] == 0
    assert out["unrealizedPnl"] == 10
    assert out["pnlKind"] == "unrealised"
    assert out["exitPlan"] is None
    assert out["entryEvaluatedFrom"] == "2026-09-02T10:00:00+05:30"

@pytest.mark.parametrize("direction,hit_high,hit_low", [
    ("LONG", 100.0, 99.49),
    ("SHORT", 100.51, 100.0),
])
def test_post_entry_half_percent_stop_closes_and_records_hit_time(direction, hit_high, hit_low):
    out = replay(row(direction), candles(
        ("2026-09-02T10:00:00+05:30", 100.1, 99.9, 100.0),
        ("2026-09-02T10:17:00+05:30", hit_high, hit_low, 100.0),
        ("2026-09-02T15:30:00+05:30", 103.0, 97.0, 102.0),
    ))
    assert out["status"] == "STOP LOSS HIT"
    assert out["closed"] is True
    assert out["exitReason"] == "SL_HIT"
    assert out["realizedPnl"] == -50
    assert out["stopHitAt"] == "2026-09-02T10:17:00+05:30"
    assert out["exitState"]["legsFilled"][-1]["at"] == out["stopHitAt"]

@pytest.mark.parametrize("direction,entry,expected", [
    ("LONG", 993.80, 988.84),
    ("SHORT", 993.80, 998.76),
])
def test_paise_rounding_never_exceeds_half_percent_loss(direction, entry, expected):
    raw = row(direction, qty=1)
    raw["entryPrice"] = entry
    out = replay(raw, candles(
        ("2026-09-02T10:00:00+05:30", 1100, 900, entry),
    ))
    assert out["stopLoss"] == expected
    assert abs(out["realizedPnl"]) <= round(entry * 0.005, 6)

def test_timestamped_events_stop_at_cash_close():
    result = post_entry_ohlc_events(
        candles(
            ("2026-09-02T09:59:00+05:30", 101, 99, 100),
            ("2026-09-02T10:00:00+05:30", 101, 99, 100),
            ("2026-09-02T15:31:00+05:30", 101, 99, 100),
        )["candles"],
        entry_at="2026-09-02T10:00:00+05:30", session_date=DAY,
    )
    assert [x["at"] for x in result] == ["2026-09-02T10:00:00+05:30"]
