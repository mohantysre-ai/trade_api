from datetime import datetime

import pytest

from app.services.angel_index_options import IST_ZONE
from app.services.index_options.runtime import (
    load_events,
    load_positions,
    load_shadows,
    process_strategy_cycle,
    strategy_eod,
)


def _leg(symbol, side, bid, ask, strike, option_type="CALL"):
    return {
        "symbol": symbol,
        "side": side,
        "bestBid": bid,
        "bestAsk": ask,
        "strike": strike,
        "optionType": option_type,
        "expiry": "2026-09-17",
        "qty": 1,
        "lotSize": 50,
        "delta": 0.4,
        "gamma": 0.01,
        "theta": -0.2,
        "vega": 0.3,
        "iv": 14.0,
    }


def _candidate(strategy="BULL_CALL_DEBIT_SPREAD", key="NIFTY"):
    legs = [
        _leg("NIFTY-A", "BUY", 99, 101, 25000),
        _leg("NIFTY-B", "SELL", 39, 41, 25200),
    ]
    return {
        "strategyId": strategy,
        "strategyType": strategy,
        "family": "DIRECTIONAL",
        "key": key,
        "eligible": True,
        "quantAuthority": "INDEX_OPTIONS_QUANT_V2",
        "expiry": "2026-09-17",
        "legs": legs,
        "maxLoss": 3100,
        "maxProfit": 6900,
        "breakevens": [25062],
        "delta": 0.1,
        "gamma": 0.0,
        "theta": 0.0,
        "vega": 0.0,
        "spot": 25000,
        "atmIv": 14.0,
        "snapshotId": "snapshot-1",
    }


def _snapshot(buy_bid=99, buy_ask=101, sell_bid=39, sell_ask=41):
    return {
        "indexOptions": {
            "indices": {
                "NIFTY": {
                    "rawChain": [
                        _leg("NIFTY-A", "BUY", buy_bid, buy_ask, 25000),
                        _leg("NIFTY-B", "SELL", sell_bid, sell_ask, 25200),
                    ]
                }
            }
        }
    }


def test_atomic_fill_restart_mtm_exit_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "shared.db"))
    candidate = _candidate()
    radar = {"modularCandidates": [candidate], "modularSelected": [candidate]}
    opened = process_strategy_cycle(radar, _snapshot(), datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE))
    assert len(opened["open"]) == 1
    position = opened["open"][0]
    assert position["legs"][0]["entryFill"] == 101
    assert position["legs"][1]["entryFill"] == 39
    assert all({"entryBid", "entryAsk", "entryFill", "entrySlippage", "entryTimestamp"} <= set(leg) for leg in position["legs"])
    position_id = position["strategyPositionId"]

    recovered = load_positions("2026-09-15")
    assert len(recovered) == 1
    assert recovered[0]["strategyPositionId"] == position_id
    assert recovered[0]["strategyId"] == "BULL_CALL_DEBIT_SPREAD"
    assert recovered[0]["legs"] == position["legs"]

    process_strategy_cycle(radar, _snapshot(), datetime(2026, 9, 15, 10, 1, tzinfo=IST_ZONE))
    assert len(load_positions("2026-09-15")) == 1

    marked = process_strategy_cycle({"modularCandidates": [], "modularSelected": []}, _snapshot(109, 111, 29, 31), datetime(2026, 9, 15, 11, 0, tzinfo=IST_ZONE))["open"][0]
    assert marked["unrealizedPnl"] == 800
    assert marked["markStatus"] == "LIVE"
    assert set(marked["netGreeks"]) == {"delta", "gamma", "theta", "vega"}

    closed = process_strategy_cycle({"modularCandidates": [], "modularSelected": []}, _snapshot(109, 111, 29, 31), datetime(2026, 9, 15, 15, 30, tzinfo=IST_ZONE))
    assert len(closed["closed"]) == 1
    process_strategy_cycle({"modularCandidates": [], "modularSelected": []}, _snapshot(109, 111, 29, 31), datetime(2026, 9, 15, 15, 31, tzinfo=IST_ZONE))
    assert [event["eventType"] for event in load_events(position_id)] == ["OPENED", "CLOSED"]
    report = strategy_eod("2026-09-15")
    assert report["realizedPnl"] == 800
    assert report["positions"][0]["strategy"] == "BULL_CALL_DEBIT_SPREAD"


def test_unpriced_mandatory_leg_blocks_entire_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "shared.db"))
    candidate = _candidate()
    candidate["legs"][1].pop("bestAsk")
    radar = {"modularCandidates": [candidate], "modularSelected": [candidate]}
    result = process_strategy_cycle(radar, _snapshot(), datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE))
    assert result["positions"] == []
    assert candidate["paperEntryState"] == "ENTRY_BLOCKED"


def test_alternative_is_shadow_only(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "shared.db"))
    selected = _candidate()
    alternative = _candidate("LONG_STRADDLE", "BANKNIFTY")
    radar = {"modularCandidates": [selected, alternative], "modularSelected": [selected]}
    result = process_strategy_cycle(radar, _snapshot(), datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE))
    assert len(result["positions"]) == 1
    shadows = load_shadows("2026-09-15")
    assert len(shadows) == 1
    assert shadows[0]["strategyId"] == "LONG_STRADDLE"


def test_two_open_buy_positions_do_not_block_sell_sleeve(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "shared.db"))
    straddle = _candidate("LONG_STRADDLE")
    straddle["strategyMode"] = "BUY_PREMIUM"
    strangle = _candidate("LONG_STRANGLE")
    strangle["strategyMode"] = "BUY_PREMIUM"
    buys = [straddle, strangle]
    process_strategy_cycle(
        {"modularCandidates": buys, "modularSelected": buys},
        _snapshot(),
        datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE),
    )

    seller = _candidate("IRON_CONDOR")
    seller["strategyMode"] = "SELL_PREMIUM"
    result = process_strategy_cycle(
        {"modularCandidates": [seller], "modularSelected": [seller]},
        _snapshot(),
        datetime(2026, 9, 15, 10, 1, tzinfo=IST_ZONE),
    )

    assert len(result["open"]) == 3
    assert seller["paperEntryState"] == "FILLED"


@pytest.mark.parametrize("strategy,family", [
    ("BULL_CALL_DEBIT_SPREAD", "DIRECTIONAL"),
    ("BEAR_PUT_DEBIT_SPREAD", "DIRECTIONAL"),
    ("LONG_STRADDLE", "VOLATILITY_EXPANSION"),
    ("LONG_STRANGLE", "VOLATILITY_EXPANSION"),
    ("IRON_BUTTERFLY", "RANGE"),
    ("LONG_CALL_BUTTERFLY", "RANGE"),
    ("LONG_PUT_BUTTERFLY", "RANGE"),
    ("CALL_CALENDAR", "TERM_STRUCTURE"),
    ("PUT_CALENDAR", "TERM_STRUCTURE"),
    ("CALL_DIAGONAL", "TERM_STRUCTURE"),
    ("PUT_DIAGONAL", "TERM_STRUCTURE"),
])
def test_every_new_strategy_reaches_atomic_durable_open(tmp_path, monkeypatch, strategy, family):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / f"{strategy}.db"))
    candidate = _candidate(strategy)
    candidate["family"] = family
    if family == "TERM_STRUCTURE":
        candidate["farExpiry"] = "2026-09-24"
        candidate["legs"][1]["expiry"] = "2026-09-24"
    result = process_strategy_cycle(
        {"modularCandidates": [candidate], "modularSelected": [candidate]},
        _snapshot(),
        datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE),
    )
    assert len(result["open"]) == 1
    stored = result["open"][0]
    assert stored["strategyId"] == strategy
    assert stored["strategyPositionId"]
    assert all(leg["entryFill"] == (leg["entryAsk"] if leg["side"] == "BUY" else leg["entryBid"]) for leg in stored["legs"])


@pytest.mark.parametrize("reason,market,when,max_loss,max_profit", [
    ("PROFIT_TARGET", _snapshot(119, 121, 19, 21), datetime(2026, 9, 15, 11, 0, tzinfo=IST_ZONE), 10000, 1000),
    ("STRUCTURE_RISK_STOP", _snapshot(79, 81, 49, 51), datetime(2026, 9, 15, 11, 0, tzinfo=IST_ZONE), 1000, 10000),
    ("TIME_EXIT", _snapshot(), datetime(2026, 9, 15, 15, 30, tzinfo=IST_ZONE), 10000, 10000),
])
def test_deterministic_exit_paths(tmp_path, monkeypatch, reason, market, when, max_loss, max_profit):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / f"{reason}.db"))
    candidate = _candidate()
    candidate.update({"maxLoss": max_loss, "maxProfit": max_profit})
    radar = {"modularCandidates": [candidate], "modularSelected": [candidate]}
    process_strategy_cycle(radar, _snapshot(), datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE))
    closed = process_strategy_cycle({"modularCandidates": [], "modularSelected": []}, market, when)["closed"]
    assert closed[0]["exitReason"] == reason
    assert closed[0]["lifecycleState"] == "EXIT_ALL"
    assert all({"exitBid", "exitAsk", "exitFill", "exitSlippage", "exitTimestamp"} <= set(leg) for leg in closed[0]["legs"])


def test_structural_invalidation_exit_and_eod_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "structure.db"))
    candidate = _candidate()
    radar = {"modularCandidates": [candidate], "modularSelected": [candidate]}
    process_strategy_cycle(radar, _snapshot(), datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE))
    market = _snapshot()
    market["indexOptions"]["indices"]["NIFTY"].update({"spot": 24900, "atmIv": 16, "structure": {"status": "INVALIDATED"}})
    closed = process_strategy_cycle({"modularCandidates": [], "modularSelected": []}, market, datetime(2026, 9, 15, 11, 0, tzinfo=IST_ZONE))["closed"][0]
    assert closed["exitReason"] == "STRUCTURAL_INVALIDATION"
    report = strategy_eod("2026-09-15")["positions"][0]
    assert report["spotMove"] == -100
    assert report["ivMove"] == 2


def test_expiry_cutoff_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "expiry.db"))
    candidate = _candidate()
    candidate["expiryState"] = "EXPIRY_CUTOFF"
    process_strategy_cycle(
        {"modularCandidates": [candidate], "modularSelected": [candidate]},
        _snapshot(),
        datetime(2026, 9, 15, 10, 0, tzinfo=IST_ZONE),
    )
    closed = process_strategy_cycle(
        {"modularCandidates": [], "modularSelected": []},
        _snapshot(),
        datetime(2026, 9, 15, 10, 1, tzinfo=IST_ZONE),
    )["closed"]
    assert closed[0]["exitReason"] == "EXPIRY_CUTOFF"
