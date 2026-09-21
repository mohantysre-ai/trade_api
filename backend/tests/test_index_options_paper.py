import time
from datetime import datetime, timedelta

from app.services.angel_index_options import IST_ZONE
from app.services.angel_index_stream import ANGEL_INDEX_STREAM
from app.services.index_options_paper import (
    LONG_PREMIUM_MARK_INTERVAL_SECONDS,
    LONG_PREMIUM_RISK_REWARD,
    LONG_PREMIUM_STOP_POINTS,
    LONG_PREMIUM_TARGET_POINTS,
    hydrate_open_position_subscriptions,
    reconcile_paper_book,
)

SESSION_DATE = datetime(2027, 6, 15, 11, 0, tzinfo=IST_ZONE)


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


def test_reentry_after_cooldown_requires_current_candidate_confirmations(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(), now=now)
    reconcile_paper_book(_radar(140), now=now + timedelta(minutes=1))
    blocked = reconcile_paper_book(_radar(100), now=now + timedelta(minutes=22))
    assert blocked["open"] == []
    row = _candidate(100)
    row["gates"] = {
        "fresh": True,
        "structure": True,
        "breakout": True,
        "futuresOi": True,
        "breadth": True,
    }
    allowed = reconcile_paper_book(
        {"candidates": [row], "selected": [row]},
        now=now + timedelta(minutes=23),
    )
    assert len(allowed["open"]) == 1
    assert allowed["entryCount"] == 2


def test_cross_book_owner_blocks_new_paper_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setattr(
        "app.services.index_options_paper._cross_book_owner",
        lambda row, session_date: "SWING",
    )
    radar = _radar()
    book = reconcile_paper_book(radar, now=datetime(2026, 8, 24, 11, 0, tzinfo=IST_ZONE))
    assert book["entryCount"] == 0
    assert book["open"] == []
    assert radar["selected"][0]["ownershipBlockedBy"] == "SWING"


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


def _seller_row(*, key="NIFTY", bucket="BROAD", score=90.0, credit=4.38, max_loss_lot=206.5):
    short = {"action": "SELL", "symbol": f"{key}SHORTPE", "token": "S1", "exchange": "NFO", "strike": 95,
             "lotSize": 75, "currentPrice": 2.8, "bestBid": 2.80, "bestAsk": 2.82}
    hedge = {"action": "BUY", "symbol": f"{key}LONGPE", "token": "L1", "exchange": "NFO", "strike": 90,
             "lotSize": 75, "currentPrice": 0.6, "bestBid": 0.60, "bestAsk": 0.61}
    return {
        "key": key, "bucket": bucket, "state": "ELIGIBLE", "score": score, "scoreFloor": 82.0,
        "direction": "CALL", "strategyMode": "SELL_PREMIUM", "strategyType": "BULL_PUT_CREDIT_SPREAD",
        "legs": [short, hedge], "expiry": "2027-06-24", "spot": 100.0, "chain": [],
        "risk": {"entryCredit": credit, "maxLossPerUnit": 2.75, "maxLossPerLot": max_loss_lot,
                 "estimatedRoundTripCosts": 160.0, "maxProfitPerLot": 168.5,
                 "shortPutStrike": 95, "shortCallStrike": None},
        "dataSource": "ANGEL_ONE", "gates": {},
    }


def _inject_tick(token, ltp, *, bid=None, ask=None, age_seconds=0.0):
    message = {"exchange_type": 2, "token": str(token), "last_traded_price": ltp * 100}
    if bid is not None:
        message["best_5_buy_data"] = [{"price": bid * 100}]
    if ask is not None:
        message["best_5_sell_data"] = [{"price": ask * 100}]
    ANGEL_INDEX_STREAM._on_data(message)
    if age_seconds:
        ANGEL_INDEX_STREAM._quotes[str(token)]["receivedEpoch"] = time.time() - age_seconds


def _clear_tick(token):
    with ANGEL_INDEX_STREAM._lock:
        ANGEL_INDEX_STREAM._quotes.pop(str(token), None)


def test_buy_and_sell_sleeves_lock_the_same_index_independently(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    buy = _candidate(100.0, key="NIFTY", bucket="BROAD")
    sell = _seller_row(key="NIFTY", bucket="BROAD")
    book = reconcile_paper_book(
        {"candidates": [buy], "sellerCandidates": [sell], "selected": [buy, sell]}, now=SESSION_DATE,
    )
    assert book["entryCount"] == 2
    assert sorted(row["strategyMode"] for row in book["open"]) == ["BUY_PREMIUM", "SELL_PREMIUM"]
    assert book["sleeveLocks"]["BUY_PREMIUM"]["indexes"] == ["NIFTY"]
    assert book["sleeveLocks"]["SELL_PREMIUM"]["indexes"] == ["NIFTY"]


def test_sell_sleeve_keeps_its_own_bucket_when_the_buy_sleeve_owns_it(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    buy = _candidate(100.0, key="NIFTY", bucket="BROAD")
    reconcile_paper_book({"candidates": [buy], "selected": [buy]}, now=SESSION_DATE)

    sell = _seller_row(key="SENSEX", bucket="BROAD")
    book = reconcile_paper_book(
        {"candidates": [], "sellerCandidates": [sell], "selected": [sell]},
        now=SESSION_DATE + timedelta(minutes=1),
    )
    assert book["entryCount"] == 2
    assert [row["index"] for row in book["open"]] == ["NIFTY", "SENSEX"]
    assert book["sleeveLocks"]["BUY_PREMIUM"]["buckets"] == ["BROAD"]
    assert book["sleeveLocks"]["SELL_PREMIUM"]["buckets"] == ["BROAD"]


def test_second_buy_in_a_locked_bucket_is_blocked_within_its_own_sleeve(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    first = _candidate(100.0, key="NIFTY", bucket="BROAD")
    reconcile_paper_book({"candidates": [first], "selected": [first]}, now=SESSION_DATE)

    second = _candidate(100.0, key="SENSEX", bucket="BROAD")
    book = reconcile_paper_book(
        {"candidates": [second], "selected": [second]}, now=SESSION_DATE + timedelta(minutes=1),
    )
    assert book["entryCount"] == 1
    assert second["entryBlockedBy"] == "SLEEVE_CORRELATION_BUCKET_LOCKED"


def test_portfolio_concurrency_is_applied_after_both_sleeves_select(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    buy = _candidate(100.0, key="NIFTY", bucket="BROAD")
    sell = _seller_row(key="NIFTY", bucket="BROAD")
    book = reconcile_paper_book(
        {"candidates": [buy], "sellerCandidates": [sell], "selected": [buy, sell]}, now=SESSION_DATE,
    )
    assert len(book["open"]) == 2  # one per sleeve: 1 BUY + 1 defined-risk SELL

    extra_buy = _candidate(100.0, key="BANKNIFTY", bucket="FINANCIAL")
    extra_sell = _seller_row(key="BANKNIFTY", bucket="FINANCIAL")
    expanded = reconcile_paper_book(
        {
            "candidates": [extra_buy], "sellerCandidates": [extra_sell],
            "selected": [extra_buy, extra_sell], "modularSelected": [extra_buy, extra_sell],
        },
        now=SESSION_DATE + timedelta(minutes=1),
    )
    # The portfolio-wide cap is 8; the independent BROAD/FINANCIAL sleeve
    # buckets currently bound this fixture to four simultaneous positions.
    assert expanded["entryCount"] == 4
    assert extra_buy.get("entryBlockedBy") is None
    assert extra_sell.get("entryBlockedBy") is None
    assert sorted(row["index"] for row in expanded["open"]) == [
        "BANKNIFTY", "BANKNIFTY", "NIFTY", "NIFTY"
    ]


def test_duplicate_strategy_is_never_locked_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    sell = _seller_row()
    reconcile_paper_book({"sellerCandidates": [sell], "selected": [sell]}, now=SESSION_DATE)
    repeat = _seller_row()
    book = reconcile_paper_book(
        {"sellerCandidates": [repeat], "selected": [repeat]}, now=SESSION_DATE + timedelta(minutes=1),
    )
    assert book["entryCount"] == 1
    assert repeat["entryBlockedBy"] in {"DUPLICATE_STRATEGY_OPEN", "SLEEVE_INDEX_ALREADY_LOCKED"}


def test_score_below_lock_threshold_is_not_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    row = _candidate(100.0, key="NIFTY", bucket="BROAD")
    row["score"] = 69.5
    row["scoreFloor"] = 70.0
    book = reconcile_paper_book({"candidates": [row], "selected": [row]}, now=SESSION_DATE)
    assert book["entryCount"] == 0
    assert row["entryBlockedBy"] == "SCORE_BELOW_LOCK_THRESHOLD"


def test_locked_contract_is_marked_from_websocket_cache_without_rest_quote(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2027, 6, 15, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(), now=now)

    class Client:
        def fetch_batch_quotes(self, instruments):
            raise AssertionError("live WebSocket depth must not trigger a REST quote")

    _inject_tick("12345", 111.0, bid=110.5, ask=111.5)
    try:
        marked = reconcile_paper_book(_radar(), client=Client(), now=now + timedelta(minutes=1))
    finally:
        _clear_tick("12345")

    position = marked["open"][0]
    assert position["currentPremium"] == 111
    assert position["markSource"] == "ANGEL_WEBSOCKET_LOCKED_CONTRACT"
    assert position["markQuality"] == "FRESH_WEBSOCKET"
    assert position["executableBid"] == 110.5
    assert position["executableAsk"] == 111.5
    assert marked["markPipeline"]["streamMarks"] == 1
    assert marked["markPipeline"]["restRequested"] == 0


def test_stale_websocket_tick_falls_back_to_a_single_rest_quote(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2027, 6, 15, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(), now=now)

    calls = []

    class Client:
        def fetch_batch_quotes(self, instruments):
            calls.append([instrument.tradingsymbol for instrument in instruments])
            return {instrument.key: {"ltp": 111} for instrument in instruments}

    _inject_tick("12345", 105.0, age_seconds=600.0)
    try:
        marked = reconcile_paper_book(_radar(), client=Client(), now=now + timedelta(minutes=1))
    finally:
        _clear_tick("12345")

    position = marked["open"][0]
    assert calls == [["BANKNIFTYTESTPE"]]
    assert position["currentPremium"] == 111
    assert position["markSource"] == "ANGEL_DIRECT_LOCKED_CONTRACT"
    assert position["markQuality"] == "REST_FALLBACK"
    assert marked["markPipeline"]["staleContracts"] == 1


def test_buy_entry_locks_at_the_streamed_ask_when_live_depth_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    _inject_tick("12345", 100.0, bid=99.5, ask=100.5)
    try:
        book = reconcile_paper_book(_radar(100), now=datetime(2027, 6, 15, 11, 0, tzinfo=IST_ZONE))
    finally:
        _clear_tick("12345")

    position = book["open"][0]
    assert position["entryPremium"] == 100.5
    assert position["entryPricingSource"] == "ANGEL_WEBSOCKET_ASK"
    assert position["initialStopPremium"] == 80.5
    assert position["targetPremium"] == 140.5


def test_open_position_keeps_its_stream_subscription_and_releases_it_on_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2027, 6, 15, 11, 0, tzinfo=IST_ZONE)

    class Client:
        def connect(self):
            return self

    monkeypatch.setattr(
        "app.services.angel_index_stream.ANGEL_INDEX_STREAM.retain",
        lambda client, instruments, owner=None: len(instruments),
    )
    released = []
    monkeypatch.setattr(
        "app.services.angel_index_stream.ANGEL_INDEX_STREAM.release_owner",
        lambda owner: released.append(owner) or 0,
    )
    book = reconcile_paper_book(_radar(100), client=Client(), now=now)
    assert book["subscriptions"]["contracts"] == 1
    assert ANGEL_INDEX_STREAM.retained_owners() == {}

    closed = reconcile_paper_book(_radar(140), client=Client(), now=now + timedelta(minutes=1))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "TARGET"
    assert released == [f"paper:{book['open'][0]['id']}"]


def test_subscription_hydration_reads_the_paper_book_without_radar_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    now = datetime(2027, 6, 15, 11, 0, tzinfo=IST_ZONE)
    reconcile_paper_book(_radar(100), now=now)

    class Client:
        def connect(self):
            return self

    class LiveWorker:
        def is_alive(self):
            return True

    # Keep the reference-counting path real while preventing a real socket worker.
    monkeypatch.setattr(ANGEL_INDEX_STREAM, "_thread", LiveWorker())
    monkeypatch.setattr(ANGEL_INDEX_STREAM, "_socket", None)

    summary = hydrate_open_position_subscriptions(Client(), now=now)
    assert summary["openPositions"] == 1
    assert summary["retainedContracts"] == 1
    assert summary["stream"]["retainedContracts"] == 1
    assert summary["stream"]["wanted"] == 1
    ANGEL_INDEX_STREAM.release_owner(f"paper:{_load_open_position_id(tmp_path)}")
    assert ANGEL_INDEX_STREAM.retained_owners() == {}
    assert ANGEL_INDEX_STREAM.status()["wanted"] == 0


def _load_open_position_id(tmp_path) -> str:
    import json

    with open(tmp_path / "paper.json", "r", encoding="utf-8") as handle:
        return str(json.load(handle)["open"][0]["id"])


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
