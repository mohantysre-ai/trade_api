from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.swing_v2.engine import execute_paper_order
from app.services.swing_v2.execution import simulate_paper_fill
from app.services.swing_v2.ledger import SwingLedger


IST = ZoneInfo("Asia/Kolkata")


def test_unmatched_quote_stays_pending_before_expiry():
    result = simulate_paper_fill(
        {"decisionTimestamp": "2026-09-29T09:45:00+05:30", "limitPrice": 100.0, "qty": 10},
        [{"timestamp": "2026-09-29T09:46:00+05:30", "ask": 101.0, "askDepth": 100}],
        expiry=datetime(2026, 9, 29, 15, 20, tzinfo=IST),
    )
    assert result["executionStatus"] == "PENDING_UNFILLED"


def test_unmatched_quote_expires_at_actual_expiry():
    result = simulate_paper_fill(
        {"decisionTimestamp": "2026-09-29T09:45:00+05:30", "limitPrice": 100.0, "qty": 10},
        [{"timestamp": "2026-09-29T15:20:00+05:30", "ask": 101.0, "askDepth": 100}],
        expiry=datetime(2026, 9, 29, 15, 20, tzinfo=IST),
    )
    assert result["executionStatus"] == "EXPIRED_UNFILLED"


def test_pending_order_does_not_append_future_expiry_event(tmp_path):
    ledger = SwingLedger(str(tmp_path / "swing.sqlite3"))
    candidate = {
        "decisionId": "decision-1",
        "symbol": "TEST",
        "sessionDate": "2026-09-29",
        "decisionTimestamp": "2026-09-29T09:45:00+05:30",
        "limitPrice": 100.0,
        "decisionPrice": 99.0,
        "qty": 10,
        "initialStop": 95.0,
    }
    result = execute_paper_order(
        ledger,
        candidate,
        [{"timestamp": "2026-09-29T09:46:00+05:30", "ask": 101.0, "askDepth": 100}],
        expiry=datetime(2026, 9, 29, 15, 20, tzinfo=IST),
    )
    assert result["executionStatus"] == "PENDING_UNFILLED"
    assert ledger.events() == []


def test_quote_volume_supplies_paper_fill_depth(monkeypatch):
    from app.services.swing_v2 import authoritative

    monkeypatch.setattr(
        "app.services.swing_v2.market_data.latest_quotes",
        lambda _symbols: {"TEST": {"ltp": 99.5, "volume": 500, "quoteProvider": "NSE"}},
    )
    rows = authoritative._quote_observations(["TEST"], datetime(2026, 9, 29, 10, 0, tzinfo=IST))
    assert rows["TEST"]["ask"] == 99.5
    assert rows["TEST"]["askDepth"] == 500
