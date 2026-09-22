from datetime import datetime

from app.services.angel_index_options import IST_ZONE
from app.services.index_options_live_authority import _rebalance_radar
from app.services.index_options_paper import reconcile_paper_book


def _buy(key="NIFTY", bucket="BROAD", score=80.0, premium=100.0):
    contract = {"symbol": f"{key}TESTCE", "ltp": premium, "lotSize": 25, "token": "101", "exchange": "NFO"}
    return {"key": key, "bucket": bucket, "direction": "CALL", "state": "ELIGIBLE", "eligible": True,
            "score": score, "strategyMode": "BUY_PREMIUM", "strategyType": "LONG_CALL",
            "contract": contract, "chain": [contract], "dataSource": "ANGEL_ONE"}


def _seller(key="SENSEX", bucket="BROAD", score=82.0):
    legs = [
        {"symbol": "SENSEXSHORTPE", "action": "SELL", "lotSize": 10, "token": "201", "exchange": "BFO"},
        {"symbol": "SENSEXLONGPE", "action": "BUY", "lotSize": 10, "token": "202", "exchange": "BFO"},
    ]
    return {"key": key, "bucket": bucket, "direction": "BULLISH", "state": "ELIGIBLE", "eligible": True,
            "score": score, "strategyMode": "SELL_PREMIUM", "strategyType": "BULL_PUT_SPREAD", "legs": legs,
            "risk": {"entryCredit": 10, "maxLossPerUnit": 40, "maxLossPerLot": 400,
                     "estimatedRoundTripCosts": 0}, "dataSource": "ANGEL_ONE"}


def test_selection_reserves_one_slot_for_each_safe_sleeve():
    buy1, buy2, seller = _buy(score=99), _buy("BANKNIFTY", "FINANCIAL", 98), _seller(score=75)
    radar = {"candidates": [buy1, buy2], "sellerCandidates": [seller], "selected": [buy1, buy2]}
    out = _rebalance_radar(radar, 2)
    assert len(out["selected"]) == 2
    assert {row["strategyMode"] for row in out["selected"]} == {"BUY_PREMIUM", "SELL_PREMIUM"}


def test_buy_and_sell_same_correlation_bucket_do_not_block_each_other(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    buy, seller = _buy(), _seller()
    radar = {"candidates": [buy], "sellerCandidates": [seller], "selected": [buy, seller]}
    book = reconcile_paper_book(radar, now=datetime(2026, 9, 16, 11, 0, tzinfo=IST_ZONE))
    assert len(book["open"]) == 2
    assert {row.get("strategyMode") for row in book["open"]} == {"BUY_PREMIUM", "SELL_PREMIUM"}
    assert [row["outcome"] for row in book["entryAudit"][-2:]] == ["LOCKED", "LOCKED"]


def test_score_qualified_low_premium_buy_uses_positive_adaptive_one_to_two_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    buy = _buy(premium=10.0)
    book = reconcile_paper_book({"candidates": [buy], "sellerCandidates": [], "selected": [buy]},
                                now=datetime(2026, 9, 16, 11, 0, tzinfo=IST_ZONE))
    position = book["open"][0]
    assert position["initialStopPremium"] > 0
    assert position["stopDistancePoints"] == 5.0
    assert position["targetDistancePoints"] == 10.0
    assert position["riskRewardRatio"] == 2.0
    assert position["riskModel"] == "ADAPTIVE_OPTION_PREMIUM_POINTS_1_TO_2"


def test_rejection_reason_is_durable_instead_of_silent(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    bad = _buy(premium=0)
    book = reconcile_paper_book({"candidates": [bad], "sellerCandidates": [], "selected": [bad]},
                                now=datetime(2026, 9, 16, 11, 0, tzinfo=IST_ZONE))
    assert book["entryCount"] == 0
    assert book["entryAudit"][-1]["reason"] == "BUY_PREMIUM_INVALID_PRICE"
