from datetime import datetime, timedelta

from app.services.angel_index_options import IST_ZONE
from app.services.index_options_paper import (
    LONG_PREMIUM_MARK_INTERVAL_SECONDS,
    LONG_PREMIUM_RISK_REWARD,
    LONG_PREMIUM_STOP_POINTS,
    LONG_PREMIUM_TARGET_POINTS,
    reconcile_paper_book,
)


def _candidate(mark=100.0, *, key="BANKNIFTY", bucket="FINANCIAL", lot=30):
    contract = {"symbol": f"{key}TESTPE", "strike": 57000, "expiry": "2026-08-25", "ltp": mark, "lotSize": lot,
                "token": "12345", "exchange": "NFO"}
    return {
        "key": key, "bucket": bucket, "direction": "PUT", "state": "ELIGIBLE", "score": 95.0,
        "contract": contract, "chain": [contract], "dataSource": "ANGEL_ONE",
        "gateEvidence": {"riskReward": {"expectedR": 9.0, "projectedOptionLoss": 3.0, "projectedOptionGain": 27.0}},
    }


def _radar(mark=100.0):
    row = _candidate(mark)
    return {"candidates": [row], "selected": [row]}


def test_long_premium_policy_is_fixed_one_minute_20_40_one_to_two():
    assert LONG_PREMIUM_MARK_INTERVAL_SECONDS == 60
    assert LONG_PREMIUM_STOP_POINTS == 20.0
    assert LONG_PREMIUM_TARGET_POINTS == 40.0
    assert LONG_PREMIUM_RISK_REWARD == 2.0


def test_eligible_contract_auto_locks_one_lot_with_fixed_20_40_risk(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    entered = reconcile_paper_book(_radar(), now=now)
    assert entered["entryCount"] == 1
    position = entered["open"][0]
    assert position["quantity"] == 30
    assert position["entryPremium"] == 100
    assert position["initialStopPremium"] == 80
    assert position["effectiveStopPremium"] == 80
    assert position["targetPremium"] == 140
    assert position["expectedR"] == 2.0
    assert position["riskModel"] == "FIXED_OPTION_PREMIUM_POINTS_1_TO_2"
    assert position["markIntervalSeconds"] == 60
    assert position["minuteMarks"] == [{"at": now.isoformat(), "premium": 100.0, "pnl": 0.0, "source": "ENTRY_LOCK"}]
    assert entered["longPremiumRiskPolicy"] == {
        "markIntervalSeconds": 60,
        "stopPoints": 20.0,
        "targetPoints": 40.0,
        "riskReward": 2.0,
    }


def test_price_does_not_reprice_before_one_minute_then_persists_minute_mark(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(100), now=now)

    early = reconcile_paper_book(_radar(111), now=now + timedelta(seconds=59))
    assert early["open"][0]["currentPremium"] == 100
    assert early["open"][0]["unrealizedPnl"] == 0
    assert len(early["open"][0]["minuteMarks"]) == 1

    marked = reconcile_paper_book(_radar(111), now=now + timedelta(seconds=60))
    position = marked["open"][0]
    assert position["currentPremium"] == 111
    assert position["unrealizedPnl"] == 330
    assert position["effectiveStopPremium"] == 80
    assert len(position["minuteMarks"]) == 2
    assert position["minuteMarks"][-1]["premium"] == 111
    assert position["minuteMarks"][-1]["pnl"] == 330


def test_fixed_20_point_stop_closes_on_one_minute_mark(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(100), now=now)
    closed = reconcile_paper_book(_radar(80), now=now + timedelta(minutes=1))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "INITIAL_STOP"
    assert closed["closed"][0]["exitPremium"] == 80
    assert closed["closed"][0]["pnl"] == -600


def test_fixed_40_point_target_closes_and_cooldown_prevents_immediate_reentry(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(), now=now)
    closed = reconcile_paper_book(_radar(140), now=now + timedelta(minutes=1))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "TARGET"
    assert closed["closed"][0]["exitPremium"] == 140
    assert closed["closed"][0]["pnl"] == 1200
    assert closed["entryCount"] == 1


def test_premium_too_low_for_true_20_point_stop_is_not_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    row = _candidate(mark=20.0)
    book = reconcile_paper_book({"candidates": [row], "selected": [row]},
                                now=datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE))
    assert book["open"] == []
    assert book["entryCount"] == 0


def test_missing_exchange_lot_never_fabricates_quantity(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    row = _candidate(lot=None)
    book = reconcile_paper_book({"candidates": [row], "selected": [row]},
                                now=datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE))
    assert book["open"] == []
    assert book["entryCount"] == 0


def test_open_position_squares_off_before_session_end_even_if_minute_not_elapsed(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    reconcile_paper_book(_radar(), now=datetime(2026, 8, 24, 15, 28, 30, tzinfo=IST_ZONE))
    closed = reconcile_paper_book(_radar(105), now=datetime(2026, 8, 24, 15, 29, tzinfo=IST_ZONE))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "EOD_SQUAREOFF"


def test_open_position_uses_direct_locked_contract_quote_on_one_minute_mark(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))

    class Client:
        def fetch_batch_quotes(self, instruments):
            assert instruments[0].tradingsymbol == "BANKNIFTYTESTPE"
            return {instruments[0].key: {"ltp": 111}}

    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(100), client=Client(), now=now)
    early = reconcile_paper_book(_radar(100), client=Client(), now=now + timedelta(seconds=15))
    assert early["open"][0]["currentPremium"] == 100

    marked = reconcile_paper_book(_radar(100), client=Client(), now=now + timedelta(minutes=1))
    position = marked["open"][0]
    assert position["currentPremium"] == 111
    assert position["unrealizedPnl"] == 330
    assert position["markSource"] == "ANGEL_DIRECT_LOCKED_CONTRACT"
    assert position["minuteMarks"][-1]["source"] == "ANGEL_DIRECT_LOCKED_CONTRACT"
