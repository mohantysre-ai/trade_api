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
        "contract": {"strike": 25000, "expiry": "2026-08-25", "delta": 0.55},
    }


def test_correlation_bucket_selects_only_best_index():
    radar = build_index_options_radar({"indexOptions": {"indices": {
        "NIFTY": _complete("CALL", 92),
        "SENSEX": _complete("CALL", 88),
        "BANKNIFTY": _complete("PUT", 90),
    }}})
    assert [row["key"] for row in radar["selected"]] == ["NIFTY", "BANKNIFTY"]


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


def test_no_minimum_quota_and_hunt_remains_open_below_twenty():
    radar = build_index_options_radar({})
    assert radar["limits"]["minDailyEntries"] == 0
    assert radar["limits"]["maxDailyEntries"] == 20
    assert radar["limits"]["huntMode"] == "CONTINUOUS_MARKET_SESSION"
    governor = IndexOptionReEntryGovernor(trade_counts={"NIFTY": 5, "SENSEX": 5, "BANKNIFTY": 4, "FINNIFTY": 5})
    decision = can_reenter_index_option("BANKNIFTY", "PUT", NOW, governor)
    assert decision["allowed"] is True
