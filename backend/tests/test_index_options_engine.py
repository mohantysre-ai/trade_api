from datetime import datetime, timedelta, timezone

from app.services.index_options_engine import (
    IndexOptionReEntryGovernor,
    build_index_options_radar,
    can_reenter_index_option,
)


NOW = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)


def test_missing_option_evidence_is_no_trade_not_fabricated():
    radar = build_index_options_radar({"updatedAt": NOW.isoformat()})
    assert len(radar["candidates"]) == 4
    assert radar["selected"] == []
    assert all(row["state"] == "NO_TRADE" for row in radar["candidates"])
    assert all(row["score"] is None for row in radar["candidates"])
    assert all(row["reason"].startswith("DATA_INCOMPLETE:") for row in radar["candidates"])


def _complete(direction: str, score: float = 90.0) -> dict:
    return {
        "direction": direction,
        "scores": {name: score for name in ("trend", "breakout", "futuresOi", "optionChain", "breadth", "contract", "regime")},
        "gates": {name: True for name in ("fresh", "structure", "breakout", "futuresOi", "optionChain", "breadth", "contractEconomics", "riskReward")},
        "contract": {"symbol": f"{direction}-TEST", "strike": 25000, "expiry": "2026-08-25", "delta": 0.55, "ltp": 100},
    }


def test_correlation_bucket_selects_only_best_index():
    radar = build_index_options_radar({"indexOptions": {"indices": {
        "NIFTY": _complete("CALL", 92),
        "SENSEX": _complete("CALL", 88),
        "BANKNIFTY": _complete("PUT", 90),
    }}})
    assert [row["key"] for row in radar["selected"]] == ["NIFTY", "BANKNIFTY"]


def _seller_snapshot(score: float = 95.0, *, strategy_type: str = "IRON_CONDOR", bias: str = "NEUTRAL") -> dict:
    gates = {name: True for name in (
        "fresh", "structure", "futuresRegime", "optionChain", "breadth", "volatilityEdge",
        "contractEconomics", "definedRisk", "thetaCarry", "tailBuffer", "timeWindow",
    )}
    return {
        "spot": 25000,
        "seller": {
            "scores": {name: score for name in (
                "structure", "futuresRegime", "optionChain", "breadth", "volatilityEdge", "contract", "theta",
            )},
            "gates": gates,
            "strategyType": strategy_type,
            "bias": bias,
        },
    }


def test_buy_and_sell_sleeves_select_the_same_index_independently():
    supplied = {**_complete("CALL", 92.0), **_seller_snapshot(95.0)}
    radar = build_index_options_radar({"indexOptions": {"indices": {"NIFTY": supplied}}})
    assert [row["key"] for row in radar["buySelected"]] == ["NIFTY"]
    assert [row["key"] for row in radar["sellSelected"]] == ["NIFTY"]
    assert [row["key"] for row in radar["selected"]] == ["NIFTY", "NIFTY"]
    assert radar["limits"]["maxConcurrent"] == 20
    assert radar["limits"]["maxConcurrentPerSleeve"] == 10
    assert radar["limits"]["sleeveIsolation"] == "INDEPENDENT_INDEX_AND_BUCKET_PER_SLEEVE"


def test_sell_sleeve_keeps_its_own_bucket_pick_when_the_buy_sleeve_takes_one():
    radar = build_index_options_radar({"indexOptions": {"indices": {
        "NIFTY": {**_complete("CALL", 92.0), **_seller_snapshot(95.0)},
        "SENSEX": {**_complete("CALL", 88.0), **_seller_snapshot(90.0)},
    }}})
    assert [row["key"] for row in radar["buySelected"]] == ["NIFTY"]
    assert [row["key"] for row in radar["sellSelected"]] == ["NIFTY"]


def test_profit_reentry_needs_cooldown_and_all_confirmations():
    governor = IndexOptionReEntryGovernor()
    governor.record_entry("NIFTY")
    governor.record_exit("NIFTY", "TARGET", "CALL", NOW - timedelta(minutes=25), 120.0)
    blocked = can_reenter_index_option("NIFTY", "CALL", NOW, governor, fresh_breakout_confirmed=True, oi_aligned=True)
    assert blocked["allowed"] is False
    assert blocked["reason"] == "TREND_RESUMPTION_NOT_CONFIRMED"
    allowed = can_reenter_index_option(
        "NIFTY", "CALL", NOW, governor,
        fresh_breakout_confirmed=True, oi_aligned=True, breadth_aligned=True,
    )
    assert allowed["allowed"] is True
    assert allowed["riskScale"] == 0.5


def test_same_direction_stop_has_45_minute_cooldown():
    governor = IndexOptionReEntryGovernor()
    governor.record_entry("BANKNIFTY")
    governor.record_exit("BANKNIFTY", "STOP_LOSS", "PUT", NOW - timedelta(minutes=30), 100.0)
    decision = can_reenter_index_option("BANKNIFTY", "PUT", NOW, governor)
    assert decision["reason"] == "SL_SAME_DIRECTION_COOLDOWN"
    assert decision["cooldownRemainingMin"] == 15.0


def test_twenty_daily_entries_hard_block_even_after_confirmation():
    governor = IndexOptionReEntryGovernor(trade_counts={"NIFTY": 5, "SENSEX": 5, "BANKNIFTY": 5, "FINNIFTY": 5})
    decision = can_reenter_index_option(
        "FINNIFTY", "CALL", NOW, governor,
        fresh_breakout_confirmed=True, oi_aligned=True, breadth_aligned=True,
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "MAX_DAILY_ENTRIES_REACHED"


def test_no_minimum_quota_and_hunt_remains_open_below_cap():
    radar = build_index_options_radar({})
    assert radar["limits"]["minDailyEntries"] == 0
    assert radar["limits"]["maxDailyEntries"] == 20
    assert radar["limits"]["huntMode"] == "CONTINUOUS_MARKET_SESSION"
    governor = IndexOptionReEntryGovernor(trade_counts={"NIFTY": 1, "SENSEX": 1, "BANKNIFTY": 1, "FINNIFTY": 1})
    decision = can_reenter_index_option("BANKNIFTY", "PUT", NOW, governor)
    assert decision["allowed"] is True


def test_twenty_total_daily_entries_across_indices_hard_block():
    governor = IndexOptionReEntryGovernor(trade_counts={"NIFTY": 5, "SENSEX": 5, "BANKNIFTY": 5, "FINNIFTY": 5})
    decision = can_reenter_index_option(
        "BANKNIFTY", "PUT", NOW, governor,
        fresh_breakout_confirmed=True, oi_aligned=True, breadth_aligned=True,
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "MAX_DAILY_ENTRIES_REACHED"
