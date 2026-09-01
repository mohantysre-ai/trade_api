from datetime import datetime, timedelta

from app.services.angel_index_options import IST_ZONE
from app.services.index_options_paper import reconcile_paper_book
from app.services.index_options_paper_supervisor import (
    _next_minute_boundary,
    _session_active,
    run_paper_supervisor_cycle,
)


def _candidate(mark=100.0):
    contract = {
        "symbol": "BANKNIFTYTESTPE",
        "strike": 57000,
        "expiry": "2026-09-01",
        "ltp": mark,
        "lotSize": 30,
        "token": "12345",
        "exchange": "NFO",
    }
    return {
        "key": "BANKNIFTY",
        "bucket": "FINANCIAL",
        "direction": "PUT",
        "state": "ELIGIBLE",
        "score": 95.0,
        "contract": contract,
        "chain": [contract],
        "dataSource": "ANGEL_ONE",
        "gateEvidence": {"riskReward": {"expectedR": 2.0}},
    }


def test_supervisor_cycle_never_creates_new_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))

    class Client:
        def fetch_batch_quotes(self, instruments):
            raise AssertionError("no locked positions means no quote request is required")

    book = run_paper_supervisor_cycle(
        Client(), now=datetime(2026, 9, 1, 11, 0, tzinfo=IST_ZONE),
    )
    assert book["entryCount"] == 0
    assert book["open"] == []
    assert book["closed"] == []


def test_supervisor_marks_already_locked_trade_without_dashboard_request(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 9, 1, 11, 0, tzinfo=IST_ZONE)
    row = _candidate(100)
    entered = reconcile_paper_book({"candidates": [row], "selected": [row]}, now=now)
    assert entered["entryCount"] == 1
    assert entered["open"][0]["entryPremium"] == 100
    assert entered["open"][0]["initialStopPremium"] == 80
    assert entered["open"][0]["targetPremium"] == 140

    class Client:
        def fetch_batch_quotes(self, instruments):
            return {instruments[0].key: {"ltp": 115}}

    marked = run_paper_supervisor_cycle(Client(), now=now + timedelta(minutes=1))
    assert marked["entryCount"] == 1
    assert marked["open"][0]["entryPremium"] == 100
    assert marked["open"][0]["currentPremium"] == 115
    assert marked["open"][0]["unrealizedPnl"] == 450
    assert marked["open"][0]["markSource"] == "ANGEL_DIRECT_LOCKED_CONTRACT"
    assert len(marked["open"][0]["minuteMarks"]) == 1


def test_supervisor_applies_existing_target_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 9, 1, 11, 0, tzinfo=IST_ZONE)
    row = _candidate(100)
    reconcile_paper_book({"candidates": [row], "selected": [row]}, now=now)

    class Client:
        def fetch_batch_quotes(self, instruments):
            return {instruments[0].key: {"ltp": 140}}

    closed = run_paper_supervisor_cycle(Client(), now=now + timedelta(minutes=1))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "TARGET"
    assert closed["closed"][0]["exitPremium"] == 140
    assert closed["closed"][0]["pnl"] == 1200


def test_supervisor_session_window_includes_eod_squareoff_minute():
    assert _session_active(datetime(2026, 9, 1, 9, 15, tzinfo=IST_ZONE)) is True
    assert _session_active(datetime(2026, 9, 1, 15, 29, tzinfo=IST_ZONE)) is True
    assert _session_active(datetime(2026, 9, 1, 15, 30, tzinfo=IST_ZONE)) is True
    assert _session_active(datetime(2026, 9, 1, 15, 31, tzinfo=IST_ZONE)) is False


def test_next_cycle_aligns_to_wall_clock_minute():
    now = datetime(2026, 9, 1, 11, 7, 43, 250000, tzinfo=IST_ZONE)
    assert _next_minute_boundary(now) == datetime(2026, 9, 1, 11, 8, tzinfo=IST_ZONE)
