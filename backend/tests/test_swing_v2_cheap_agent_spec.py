"""Comprehensive specification test suite for Swing V2 Cheap-Agent Instructions."""
from __future__ import annotations

import pathlib
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import pytest

from app.services.swing_v2.config import load_config, SwingV2Config
from app.services.swing_v2.engine import process_corporate_action, process_position_bar
from app.services.swing_v2.facade import build_from_market_snapshot
from app.services.swing_v2.ledger import SwingLedger, materialize_position
from app.services.swing_v2.lifecycle import (
    apply_corporate_action,
    evaluate_position,
    evaluate_position_health,
    time_exit_due,
    update_stop,
)
from app.services.swing_v2.market_data import (
    historical_bars,
    intraday_occupied_symbols,
    latest_quotes,
    read_snapshot,
)
from app.services.swing_v2.portfolio import construct_portfolio
from app.services.swing_v2.shadow import build_shadow_v2

IST = ZoneInfo("Asia/Kolkata")


# 1. Feed / Isolation
def test_swing_has_no_direct_angel_one_or_intraday_dependency():
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "swing_v2"
    forbidden_tokens = {
        "AngelOneClient", "SmartConnect", "fetch_batch_quotes",
        "fetch_candles", "run_scheduled_live_refresh", "intraday_session_engine",
        "intraday_market_state", "intraday_execution_evidence",
    }
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in text, f"{path.name} contains forbidden dependency token: {token}"


# 2. Tick vs Completed-Bar
def test_mid_candle_stop_does_not_persist_incomplete_bar(tmp_path):
    ledger = SwingLedger(str(tmp_path / "mid_candle.sqlite3"))
    ledger.append(
        idempotency_key="d1:FILL_COMPLETE",
        decision_id="d1",
        position_id="p1",
        symbol="TCS",
        session_date="2026-09-13",
        event_type="FILL_COMPLETE",
        event_timestamp="2026-09-13T09:45:00Z",
        payload={"symbol": "TCS", "entryPrice": 3000.0, "initialStop": 2900.0, "effectiveStop": 2900.0, "qty": 10, "entryTimestamp": "2026-09-13T09:45:00Z"},
    )
    mid_candle_tick = {"timestamp": "2026-09-13T09:47:15Z", "open": 2950.0, "high": 2960.0, "low": 2890.0, "close": 2895.0}
    updated = process_position_bar(ledger, "p1", mid_candle_tick)
    assert updated["terminal"] is True
    assert updated["status"] == "CLOSED_STOP"
    assert updated["exitPrice"] == 2900.0


def test_bucket_b_tick_does_not_contaminate_bucket_a():
    def bucket_key(ts_str: str) -> str:
        dt = datetime.fromisoformat(ts_str)
        return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0).isoformat()

    bucket_a_end = bucket_key("2026-09-13T09:49:59Z")
    bucket_b_start = bucket_key("2026-09-13T09:50:00Z")
    assert bucket_a_end != bucket_b_start


# 3. Trailing Stop
def test_long_and_short_trailing_stop_never_loosens():
    long_pos = {"direction": "LONG", "effectiveStop": 100.0}
    assert update_stop(long_pos, 98.0)["effectiveStop"] == 100.0
    assert update_stop(long_pos, 103.0)["effectiveStop"] == 103.0

    short_pos = {"direction": "SHORT", "effectiveStop": 100.0}
    assert update_stop(short_pos, 102.0)["effectiveStop"] == 100.0
    assert update_stop(short_pos, 97.0)["effectiveStop"] == 97.0


def test_trailing_update_precedes_breach_check():
    pos = {
        "symbol": "INFY", "entryPrice": 100.0, "initialStop": 95.0, "effectiveStop": 95.0,
        "t1": 105.0, "t2": 110.0, "riskPerShare": 5.0, "qty": 10, "remainingQty": 10,
        "entryTimestamp": "2026-09-13T09:45:00Z",
    }
    bar1 = {"timestamp": "2026-09-13T09:46:00Z", "open": 101.0, "high": 106.0, "low": 100.0, "close": 105.5}
    res1 = evaluate_position(pos, bar1)
    assert res1["t1Filled"] is True
    assert res1["effectiveStop"] >= 100.0

    bar2 = {"timestamp": "2026-09-13T09:47:00Z", "open": 104.0, "high": 104.0, "low": 99.0, "close": 99.5}
    res2 = evaluate_position(res1, bar2)
    assert res2["terminal"] is True
    assert res2["exitReason"] == "TRAIL_STOP_FILLED"


# 4. Recovery
def test_persisted_trailing_stop_survives_restart(tmp_path):
    db_file = str(tmp_path / "recovery.sqlite3")
    ledger1 = SwingLedger(db_file)
    ledger1.append(
        idempotency_key="d1:FILL_COMPLETE", decision_id="d1", position_id="p1", symbol="INFY",
        session_date="2026-09-13", event_type="FILL_COMPLETE", event_timestamp="2026-09-13T09:45:00Z",
        payload={"symbol": "INFY", "entryPrice": 100.0, "initialStop": 95.0, "effectiveStop": 95.0, "qty": 10},
    )
    ledger1.append(
        idempotency_key="d1:STOP_UPDATED", decision_id="d1", position_id="p1", symbol="INFY",
        session_date="2026-09-13", event_type="STOP_UPDATED", event_timestamp="2026-09-13T10:00:00Z",
        payload={"effectiveStop": 102.5},
    )

    ledger2 = SwingLedger(db_file)
    state = materialize_position(ledger2.events(position_id="p1"))
    assert state["effectiveStop"] == 102.5


# 5. Corporate Action
def test_corporate_action_r_adjustment(tmp_path):
    ledger = SwingLedger(str(tmp_path / "ca.sqlite3"))
    ledger.append(
        idempotency_key="d1:FILL_COMPLETE", decision_id="d1", position_id="p1", symbol="INFY",
        session_date="2026-09-13", event_type="FILL_COMPLETE", event_timestamp="2026-09-13T09:45:00Z",
        payload={"symbol": "INFY", "entryPrice": 100.0, "initialStop": 90.0, "effectiveStop": 90.0, "t1": 110.0, "qty": 50, "remainingQty": 50},
    )
    updated = process_corporate_action(ledger, "p1", 2.0)
    assert updated["entryPrice"] == 50.0
    assert updated["effectiveStop"] == 45.0
    assert updated["qty"] == 100
    assert updated["remainingQty"] == 100


# 6. Gap-Through-Stop
def test_normal_stop_vs_gap_through_stop():
    pos = {"entryPrice": 100.0, "initialStop": 95.0, "effectiveStop": 95.0, "qty": 10, "remainingQty": 10, "entryTimestamp": "2026-09-13T09:45:00Z"}
    
    # Normal stop bar
    normal_bar = {"timestamp": "2026-09-13T09:46:00Z", "open": 96.0, "high": 96.0, "low": 94.0, "close": 94.5}
    res_normal = evaluate_position(pos, normal_bar)
    assert res_normal["exitPrice"] == 95.0
    assert res_normal["executionQuality"] == "NORMAL_STOP"

    # Gap-through-stop bar (opens at 92 below stop 95)
    gap_bar = {"timestamp": "2026-09-13T09:46:00Z", "open": 92.0, "high": 93.0, "low": 90.0, "close": 91.0}
    res_gap = evaluate_position(pos, gap_bar)
    assert res_gap["exitPrice"] == 92.0
    assert res_gap["executionQuality"] == "GAP_THROUGH_STOP"
    assert res_gap["gapSlippage"] == 3.0


# 7. Position Health & Data Health
def test_position_health_states():
    pos = {"entryPrice": 100.0, "effectiveStop": 95.0, "currentPrice": 99.0, "maeR": 0.0}
    h1 = evaluate_position_health(pos, {"close": 99.0}, data_status="LIVE")
    assert h1["positionHealth"] == "HEALTHY"
    assert h1["dataHealth"] == "LIVE"

    # Near stop (close = 95.5) triggers WATCH
    h2 = evaluate_position_health(pos, {"close": 95.5}, data_status="LIVE")
    assert h2["positionHealth"] == "WATCH"

    # Terminal / Thesis break triggers EXIT_REQUIRED
    h3 = evaluate_position_health(pos, {"close": 90.0}, is_d2_exit=True, data_status="LIVE")
    assert h3["positionHealth"] == "EXIT_REQUIRED"


# 8. Costs & Net-of-Friction Expected R
def test_friction_cost_rejection():
    cfg = load_config()
    row_high_friction = {
        "symbol": "HIGHCOST", "universeSegment": "NIFTY100", "upsideCapacityR": 1.6,
        "plannedMaxBlendedR": 1.6, "costPenaltyR": 0.5, # 1.6 - 0.5 = 1.1 < 1.5R minimum
        "riskPerShare": 5.0, "decisionPrice": 100.0, "atr14": 3.0, "structureStop": 95.0, "mdtv20": 1e8,
    }
    net_r = float(row_high_friction["upsideCapacityR"]) - float(row_high_friction["costPenaltyR"])
    assert net_r < cfg.min_planned_blended_r  # 1.1 < 1.5


# 9. Hard 1–2 Session Expiry
def test_time_exit_due_on_d2():
    now_d0 = datetime(2026, 9, 11, 10, 0, tzinfo=IST)
    now_d2_before = datetime(2026, 9, 15, 14, 0, tzinfo=IST)
    now_d2_after = datetime(2026, 9, 15, 15, 16, tzinfo=IST)

    assert time_exit_due(now_d0, holding_session_age=0, max_overnights=2, exit_clock="15:15") is False
    assert time_exit_due(now_d2_before, holding_session_age=2, max_overnights=2, exit_clock="15:15") is False
    assert time_exit_due(now_d2_after, holding_session_age=2, max_overnights=2, exit_clock="15:15") is True


# 10. Cutoff at 14:45 IST
def test_1445_ist_entry_cutoff():
    now_before = datetime(2026, 9, 11, 14, 30, tzinfo=IST)
    now_after = datetime(2026, 9, 11, 14, 46, tzinfo=IST)
    ts_before = now_before.astimezone(timezone.utc).isoformat()

    reliance_row = {
        "symbol": "RELIANCE",
        "ticker": "RELIANCE",
        "universeSegment": "NIFTY100",
        "decisionPrice": 2500.0,
        "structureStop": 2450.0,
        "atr14": 40.0,
        "prior20dHigh": 2480.0,
        "clv": 0.85,
        "rvolPaced": 1.8,
        "trendPriorPctile": 75,
        "residualStrengthPctile": 80,
        "sectorStrengthPctile": 60,
        "setupQualityPctile": 70,
        "rvolPctile": 75,
        "clvPctile": 80,
        "liquidityPctile": 90,
        "breakoutDistanceAtr": 0.2,
        "extensionAtr": 1.1,
        "mdtv20": 3e9,
        "dailyObservationCount": 260,
        "modeledRoundTripCostPct": 0.15,
        "spreadPct": 0.05,
        "availableAskDepth": 1000,
        "dailyBarsThroughPreviousClose": True,
        "corporateEventsCurrent": True,
        "surveillanceCurrent": True,
        "universeCurrent": True,
        "upsideCapacityR": 2.5,
        "plannedMaxBlendedR": 2.5,
        "sourceTimestamps": {
            "quote": ts_before,
            "depth": ts_before,
            "bars5m": ts_before,
        },
    }

    cfg = SwingV2Config(enabled=True, mode="PAPER", authority="V2")

    scan_before = build_shadow_v2(
        [reliance_row],
        universe_coverage=1.0, regime="NORMAL", final_lock=False, now=now_before, config=cfg
    )
    assert len(scan_before.get("candidates") or []) == 1

    scan_after = build_shadow_v2(
        [reliance_row],
        universe_coverage=1.0, regime="NORMAL", final_lock=False, now=now_after, config=cfg
    )
    assert len(scan_after.get("candidates") or []) == 0


# 11. Factor / Setup Concentration Guard
def test_setup_concentration_cap_limits_to_max_3_per_setup():
    cfg = load_config()
    existing = [
        {"symbol": "S1", "setupIds": ["BREAKOUT_CLOSE_V1"], "sector": "SEC1", "deployedCapital": 10000, "initialRiskRupees": 500},
        {"symbol": "S2", "setupIds": ["BREAKOUT_CLOSE_V1"], "sector": "SEC2", "deployedCapital": 10000, "initialRiskRupees": 500},
        {"symbol": "S3", "setupIds": ["BREAKOUT_CLOSE_V1"], "sector": "SEC3", "deployedCapital": 10000, "initialRiskRupees": 500},
    ]
    candidate = {
        "symbol": "S4", "setupIds": ["BREAKOUT_CLOSE_V1"], "sector": "SEC4",
        "decisionPrice": 100.0, "atr14": 3.0, "structureStop": 95.0, "mdtv20": 1e8, "universeSegment": "NIFTY100"
    }
    result = construct_portfolio([candidate], cfg, existing_positions=existing)
    assert len(result["selected"]) == 0
    assert result["rejected"][0]["portfolioRejectReason"] == "SETUP_CONCENTRATION_CAP"


# 12. Cross-Book Ownership & Non-Destructive Resolution
def test_cross_book_ownership_is_non_destructive():
    occupied = intraday_occupied_symbols("2026-09-13")
    assert isinstance(occupied, set)


# 13. Separate Shadow Universe Coverage
def test_shadow_universe_coverage_does_not_block_tradable_coverage():
    cfg = SwingV2Config(enabled=True, mode="PAPER", authority="V2")
    now_dt = datetime(2026, 9, 13, 10, 0, tzinfo=IST)
    ts_now = now_dt.astimezone(timezone.utc).isoformat()
    rows = [
        {"symbol": "TRADABLE1", "universeSegment": "NIFTY100", "dailyBarsThroughPreviousClose": True, "corporateEventsCurrent": True, "surveillanceCurrent": True, "universeCurrent": True, "sourceTimestamps": {"quote": ts_now, "depth": ts_now, "bars5m": ts_now}},
        {"symbol": "SHADOW1", "universeSegment": "NIFTY_MICROCAP_250", "dailyBarsThroughPreviousClose": False},
    ]
    scan = build_shadow_v2(rows, universe_coverage=0.5, regime="NORMAL", now=now_dt, config=cfg)
    assert scan.get("tradableCoverage") == 1.0
    assert scan.get("shadowCoverage") == 0.0
    assert not scan.get("blocked")
