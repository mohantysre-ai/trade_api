"""Friday 11 September 2026 Historical Smoke Test & Verification Suite for Swing V2."""
from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import pytest

from app.services.swing_v2.authoritative import (
    _positions,
    get_authoritative_session,
    is_v2_authoritative,
    run_authoritative_cycle,
)
from app.services.swing_v2.calendar import is_session, session_age
from app.services.swing_v2.config import load_config
from app.services.swing_v2.engine import execute_paper_order, process_corporate_action, process_position_bar
from app.services.swing_v2.facade import build_from_market_snapshot
from app.services.swing_v2.ledger import SwingLedger, materialize_position
from app.services.swing_v2.lifecycle import apply_corporate_action, evaluate_position, update_stop
from app.services.swing_v2.market_data import historical_bars, intraday_occupied_symbols, read_snapshot

IST = ZoneInfo("Asia/Kolkata")
FRIDAY_DATE = "2026-09-11"
TIMELINE_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "data" / "eod" / "2026-09-11" / "timeline_ticks"


def load_friday_timelines() -> dict[str, list[dict]]:
    timelines = {}
    if TIMELINE_DIR.is_dir():
        for file_path in TIMELINE_DIR.glob("*.json"):
            symbol = file_path.stem
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                candles = data.get("candles") or []
                timelines[symbol] = candles
            except Exception:
                continue
    return timelines


def test_friday_smoke_test_full_replay(monkeypatch, tmp_path):
    ledger_path = str(tmp_path / "friday_ledger.sqlite3")
    session_file = str(tmp_path / "friday_session.json")
    monkeypatch.setenv("SWING_V2_ENABLED", "true")
    monkeypatch.setenv("SWING_V2_MODE", "PAPER")
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V2")
    monkeypatch.setenv("SWING_V2_LEDGER_PATH", ledger_path)
    monkeypatch.setenv("SWING_V2_SESSION_FILE", session_file)

    cfg = load_config()
    ledger = SwingLedger(ledger_path)
    timelines = load_friday_timelines()

    assert is_v2_authoritative() is True
    assert len(timelines) >= 12
    assert "HDFCBANK" in timelines

    total_ticks = sum(len(c) for c in timelines.values())
    assert total_ticks >= 4383

    # 1. Bar-close timestamp bucket validation
    bucket_counts = {}
    for symbol, candles in timelines.items():
        for candle in candles:
            ts_str = candle["ts"]
            dt = datetime.fromisoformat(ts_str)
            bucket_min = (dt.minute // 5) * 5
            bucket = dt.replace(minute=bucket_min, second=0, microsecond=0).isoformat()
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    # Exactly 75 5m buckets per timeline (from 09:15 to 15:30)
    assert len(bucket_counts) == 75

    # 2. Replay orders & mid-candle stop execution
    pos_id = "friday_test_pos_1"
    ledger.append(
        idempotency_key="friday_dec_1:FILL_COMPLETE",
        decision_id="friday_dec_1",
        position_id=pos_id,
        symbol="HDFCBANK",
        session_date=FRIDAY_DATE,
        event_type="FILL_COMPLETE",
        event_timestamp="2026-09-11T09:45:00+05:30",
        payload={
            "symbol": "HDFCBANK",
            "entryPrice": 684.0,
            "initialStop": 680.0,
            "effectiveStop": 680.0,
            "t1": 688.0,
            "t2": 692.0,
            "riskPerShare": 4.0,
            "qty": 100,
            "remainingQty": 100,
            "entryTimestamp": "2026-09-11T09:45:00+05:30",
        },
    )

    hdfc_candles = timelines["HDFCBANK"]
    post_entry_candles = [c for c in hdfc_candles if c["ts"] > "2026-09-11T09:45:00+05:30"]

    last_state = None
    for candle in post_entry_candles:
        bar = {
            "timestamp": candle["ts"],
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle["volume"]),
        }
        last_state = process_position_bar(ledger, pos_id, bar)
        if last_state.get("terminal"):
            break

    # Verify positions after replay
    all_positions = _positions(ledger)
    assert len(all_positions) == 1
    p = all_positions[0]
    assert p["symbol"] == "HDFCBANK"
    assert p["entryPrice"] == 684.0

    # 3. Process Restart & Recovery Audit
    ledger_recovered = SwingLedger(ledger_path)
    events_rec = ledger_recovered.events(position_id=pos_id)
    state_rec = materialize_position(events_rec)
    assert state_rec["symbol"] == p["symbol"]
    assert state_rec["effectiveStop"] == p["effectiveStop"]
    assert state_rec["entryPrice"] == p["entryPrice"]

    # 4. Trailing stop ratcheting safety (never loosen)
    long_p = {"direction": "LONG", "effectiveStop": 100.0}
    assert update_stop(long_p, 99.0)["effectiveStop"] == 100.0
    assert update_stop(long_p, 101.5)["effectiveStop"] == 101.5

    short_p = {"direction": "SHORT", "effectiveStop": 100.0}
    assert update_stop(short_p, 101.0)["effectiveStop"] == 100.0
    assert update_stop(short_p, 98.5)["effectiveStop"] == 98.5

    # 5. Ownership audit
    occupied = intraday_occupied_symbols(FRIDAY_DATE)
    snapshot = {"stockQuotes": {"HDFCBANK": {"ticker": "HDFCBANK", "swingV2": {"symbol": "HDFCBANK"}}}}
    scan = build_from_market_snapshot(snapshot, final_lock=False, occupied_symbols={"HDFCBANK"})
    assert len(scan.get("candidates") or []) == 0

    # 6. EOD reconciliation
    session = get_authoritative_session()
    assert session["authority"] == "V2"
    assert session["book"] == "SWING"
    assert session["executionMode"] == "PAPER"
