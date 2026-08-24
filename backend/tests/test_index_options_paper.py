from datetime import datetime, timedelta

from app.services.angel_index_options import IST_ZONE
from app.services.index_options_paper import reconcile_paper_book


def _candidate(mark=100.0, *, key="BANKNIFTY", bucket="FINANCIAL", lot=30):
    contract = {"symbol": f"{key}TESTPE", "strike": 57000, "expiry": "2026-08-25", "ltp": mark, "lotSize": lot}
    return {
        "key": key, "bucket": bucket, "direction": "PUT", "state": "ELIGIBLE", "score": 95.0,
        "contract": contract, "chain": [contract], "dataSource": "ANGEL_ONE",
        "gateEvidence": {"riskReward": {"expectedR": 2.0, "projectedOptionLoss": 10.0, "projectedOptionGain": 20.0}},
    }


def _radar(mark=100.0):
    row = _candidate(mark)
    return {"candidates": [row], "selected": [row]}


def test_eligible_contract_auto_locks_one_lot_and_marks_pnl(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    entered = reconcile_paper_book(_radar(), now=now)
    assert entered["entryCount"] == 1
    assert entered["open"][0]["quantity"] == 30
    assert entered["open"][0]["entryPremium"] == 100
    assert entered["open"][0]["initialStopPremium"] == 90
    assert entered["open"][0]["targetPremium"] == 120

    marked = reconcile_paper_book(_radar(111), now=now + timedelta(minutes=1))
    assert marked["open"][0]["unrealizedPnl"] == 330
    assert marked["open"][0]["effectiveStopPremium"] == 100


def test_target_closes_and_cooldown_prevents_immediate_reentry(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(), now=now)
    closed = reconcile_paper_book(_radar(121), now=now + timedelta(minutes=2))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "TARGET"
    assert closed["closed"][0]["pnl"] == 630
    assert closed["entryCount"] == 1


def test_missing_exchange_lot_never_fabricates_quantity(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    row = _candidate(lot=None)
    book = reconcile_paper_book({"candidates": [row], "selected": [row]},
                                now=datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE))
    assert book["open"] == []
    assert book["entryCount"] == 0


def test_open_position_squares_off_before_session_end(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    reconcile_paper_book(_radar(), now=datetime(2026, 8, 24, 15, 20, tzinfo=IST_ZONE))
    closed = reconcile_paper_book(_radar(105), now=datetime(2026, 8, 24, 15, 29, tzinfo=IST_ZONE))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "EOD_SQUAREOFF"
