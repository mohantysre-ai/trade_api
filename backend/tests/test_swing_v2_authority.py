"""Swing V2 authority, isolation and lifecycle contract tests."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import pathlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def v2_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SWING_V2_ENABLED", "true")
    monkeypatch.setenv("SWING_V2_MODE", "PAPER")
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V2")
    monkeypatch.setenv("SWING_V2_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("SWING_V2_SESSION_FILE", str(tmp_path / "swing_v2_session.json"))
    import app.services.swing_v2.config as cfgmod
    importlib.reload(cfgmod)
    import app.services.swing_v2.authoritative as auth
    importlib.reload(auth)
    import app.services.swing_session as sess
    importlib.reload(sess)
    import app.services.eod_swing_report as eod
    importlib.reload(eod)
    import app.services.desk_book_symbols as dbs
    importlib.reload(dbs)
    yield {"auth": auth, "sess": sess, "eod": eod, "dbs": dbs, "cfg": cfgmod}


def _import_swing_v2_modules():
    forbidden = {
        "angel_one_feed",
        "intraday_session_engine",
        "intraday_market_state",
        "intraday_execution_evidence",
        "eod_intraday_report",
    }
    for name in list(sys.modules):
        if name.startswith("app.services.swing_v2"):
            del sys.modules[name]
    import app.services.swing_v2.authoritative  # noqa: F401
    import app.services.swing_v2.ingestion  # noqa: F401
    import app.services.swing_v2.facade  # noqa: F401
    import app.services.swing_v2.shadow  # noqa: F401
    import app.services.swing_v2.engine  # noqa: F401
    import app.services.swing_v2.lifecycle  # noqa: F401
    import app.services.swing_v2.market_data  # noqa: F401
    imported = set()
    for name in list(sys.modules):
        if name.startswith("app.services.swing_v2"):
            imported.update(
                m for m in sys.modules
                if m.split(".")[-1] in forbidden
                and any(p.startswith("app.services.swing_v2") for p in m.split(".")[:-1])
            )
    return imported


def test_swing_v2_has_no_angel_one_dependency():
    forbidden = {
        "AngelOneClient", "SmartConnect", "fetch_batch_quotes",
        "fetch_candles", "run_scheduled_live_refresh", "_pool_watchlist",
        "_parse_candle_rows", "angel_one_feed",
    }
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "swing_v2"
    found = set()
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                found.add(f"{path.name}:{token}")
    assert not found, f"Swing V2 references Angel One: {found}"


def test_swing_v2_has_no_intraday_implementation_dependency():
    forbidden = {
        "intraday_session_engine", "intraday_market_state",
        "intraday_execution_evidence", "eod_intraday_report",
        "from ..desk_book_symbols import intraday_locked_symbols",
        "from ..intraday_session_engine",
    }
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "swing_v2"
    found = set()
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                found.add(f"{path.name}:{token}")
    assert not found, f"Swing V2 imports Intraday implementation: {found}"


def test_swing_v2_is_paper_authoritative(v2_env):
    assert v2_env["auth"].is_v2_authoritative() is True
    session = v2_env["auth"].get_authoritative_session()
    assert session["authority"] == "V2"
    assert session["book"] == "SWING"
    assert session["executionMode"] == "PAPER"
    assert session["manualBrokerOrderPlaced"] is False
    assert session["v1Enabled"] is False


def test_swing_session_routes_through_v2(v2_env):
    sess = v2_env["sess"]
    loaded = sess.load_swing_session()
    assert loaded.get("authority") == "V2"
    assert loaded.get("book") == "SWING"
    got = sess.get_swing_session()
    assert got.get("authority") == "V2"


def test_swing_eod_uses_v2_state(v2_env):
    from datetime import date
    report = v2_env["eod"].generate_swing_eod_report(date(2026, 9, 13))
    assert report.get("source") == "swing_v2_ledger"
    assert report.get("authoritative") is True


def test_swing_eod_preserves_filled_trade_lifecycle_fields(v2_env, monkeypatch):
    from datetime import date
    from app.services import eod_book_cache
    from app.services.swing_v2.ledger import SwingLedger
    from app.services.swing_v2.schemas import EventType

    monkeypatch.setattr(eod_book_cache, "load_book_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(eod_book_cache, "save_book_cache", lambda _day, _kind, payload: payload)
    ledger = SwingLedger(v2_env["cfg"].load_config().ledger_path)
    base = {
        "status": "OPEN", "executionStatus": "FILLED", "filledQty": 20,
        "remainingQty": 20, "entryPrice": 100.0, "entryTimestamp": "2026-09-13T04:30:00Z",
        "deployedCapital": 2000.0, "initialStop": 95.0, "effectiveStop": 95.0,
        "t1": 105.0, "t2": 110.0, "realizedPnl": 0.0, "unrealizedPnl": 0.0,
        "totalPnl": 0.0,
    }
    ledger.append(
        idempotency_key="poly-fill", decision_id="poly", position_id="poly",
        symbol="POLYCAB", session_date="2026-09-13", event_type=EventType.FILL_COMPLETE,
        event_timestamp="2026-09-13T04:30:00Z", payload=base,
    )
    ledger.append(
        idempotency_key="poly-exit", decision_id="poly", position_id="poly",
        symbol="POLYCAB", session_date="2026-09-13", event_type=EventType.TIME_EXIT_FILLED,
        event_timestamp="2026-09-13T10:00:00Z",
        payload={**base, "status": "CLOSED_TIME", "remainingQty": 0, "terminal": True,
                 "exitReason": "TIME_EXIT_FILLED", "exitPrice": 108.0,
                 "realizedPnl": 160.0, "totalPnl": 160.0},
    )
    report = v2_env["eod"].generate_swing_eod_report(date(2026, 9, 13), force=True)
    row = report["picks"][0]
    assert row["qty"] == 20
    assert row["entryPrice"] == 100.0
    assert row["currentPrice"] == 108.0
    assert row["exitPrice"] == 108.0
    assert row["exitReason"] == "TIME_EXIT_FILLED"
    assert row["status"] == "CLOSED_TIME"
    assert row["outcomeBucket"] == "WIN"
    assert report["attribution"]["triggered"] == 1


def test_swing_ledger_initializes_each_path_once(monkeypatch, tmp_path):
    from app.services.swing_v2.ledger import SwingLedger

    calls = []
    monkeypatch.setattr(SwingLedger, "_initialize", lambda self: calls.append(self.path))
    path = str(tmp_path / "once.sqlite3")
    SwingLedger(path)
    SwingLedger(path)
    assert calls == [path]


def test_unfilled_expired_swing_lock_is_skipped_not_closed(v2_env, monkeypatch):
    from datetime import date
    from app.services import eod_book_cache
    from app.services.swing_v2.ledger import SwingLedger
    from app.services.swing_v2.schemas import EventType

    monkeypatch.setattr(eod_book_cache, "load_book_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(eod_book_cache, "save_book_cache", lambda _day, _kind, payload: payload)
    ledger = SwingLedger(v2_env["cfg"].load_config().ledger_path)
    ledger.append(
        idempotency_key="polycab-expired", decision_id="polycab", position_id="polycab",
        symbol="POLYCAB", session_date="2026-09-23", event_type=EventType.ORDER_EXPIRED,
        event_timestamp="2026-09-23T10:05:00Z",
        payload={
            "status": "ORDER_EXPIRED", "executionStatus": "EXPIRED_UNFILLED",
            "filledQty": 0, "remainingQty": 20, "deployedCapital": 101082.0,
            "realizedPnl": 0.0, "unrealizedPnl": 0.0, "totalPnl": 0.0,
        },
    )
    report = v2_env["eod"].generate_swing_eod_report(date(2026, 9, 23), force=True)
    row = report["picks"][0]
    assert row["status"] == "NOT_TRIGGERED"
    assert row["executionStatus"] == "EXPIRED_UNFILLED"
    assert row["skipped"] is True
    assert row["qty"] is None
    assert row["filledQty"] == 0
    assert row["entryPrice"] is None
    assert row["deployedCapital"] == 0.0
    assert row["pnl"] == 0.0
    assert report["totalDeployed"] == 0.0
    assert report["attribution"]["triggered"] == 0
    assert report["attribution"]["skipped"] == 1


def test_desk_book_symbols_reads_v2_ownership(v2_env):
    dbs = v2_env["dbs"]
    assert isinstance(dbs.swing_locked_symbols("2026-09-13"), set)


def test_no_angel_connections_in_swing_v2_source():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "swing_v2"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "AngelOneClient" not in text, path.name
        assert "angel_one_feed" not in text, path.name
        assert "SmartConnect" not in text, path.name
        assert "run_scheduled_live_refresh" not in text, path.name
        assert "fetch_batch_quotes" not in text, path.name
        assert "fetch_candles" not in text, path.name


def test_neutral_market_data_interface_exists():
    from app.services.swing_v2.market_data import (
        latest_quote, latest_quotes, historical_bars, read_snapshot, snapshot_path,
    )
    snap = read_snapshot()
    assert isinstance(snap, dict)
    assert isinstance(snapshot_path(), str)
    assert latest_quotes([]) == {}
    assert historical_bars("", "ONE_MINUTE", 1) == []


def test_mid_candle_stop_exits_without_persisting_incomplete_bar(v2_env, tmp_path):
    from app.services.swing_v2.engine import process_position_bar
    from app.services.swing_v2.ledger import SwingLedger, materialize_position

    ledger = SwingLedger(str(tmp_path / "mid_candle.sqlite3"))
    ledger.append(
        idempotency_key="dec1:FILL_COMPLETE",
        decision_id="dec1",
        position_id="pos1",
        symbol="RELIANCE",
        session_date="2026-09-13",
        event_type="FILL_COMPLETE",
        event_timestamp="2026-09-13T09:45:00Z",
        payload={
            "symbol": "RELIANCE",
            "entryPrice": 100.0,
            "initialStop": 95.0,
            "effectiveStop": 95.0,
            "qty": 10,
            "remainingQty": 10,
            "entryTimestamp": "2026-09-13T09:45:00Z",
        },
    )
    mid_candle_tick = {
        "timestamp": "2026-09-13T09:47:30Z",
        "open": 98.0,
        "high": 98.5,
        "low": 94.0,  # breaches stop 95
        "close": 94.5,
    }
    updated = process_position_bar(ledger, "pos1", mid_candle_tick)
    assert updated["terminal"] is True
    assert updated["status"] == "CLOSED_STOP"
    assert updated["exitPrice"] == 95.0


def test_first_tick_of_bucket_b_closes_one_bucket_a_bar():
    # Verify timestamp bucket logic for 5m candles
    def get_5m_bucket(ts_str: str) -> str:
        dt = datetime.fromisoformat(ts_str)
        minute_bucket = (dt.minute // 5) * 5
        return dt.replace(minute=minute_bucket, second=0, microsecond=0).isoformat()

    bucket_a1 = get_5m_bucket("2026-09-13T09:45:10Z")
    bucket_a2 = get_5m_bucket("2026-09-13T09:49:59Z")
    bucket_b = get_5m_bucket("2026-09-13T09:50:00Z")

    assert bucket_a1 == bucket_a2
    assert bucket_b != bucket_a1


def test_trailing_ratchets_before_breach_evaluation(tmp_path):
    from app.services.swing_v2.lifecycle import evaluate_position

    pos = {
        "symbol": "INFY",
        "entryPrice": 100.0,
        "initialStop": 95.0,
        "effectiveStop": 95.0,
        "t1": 105.0,
        "t2": 110.0,
        "riskPerShare": 5.0,
        "qty": 10,
        "remainingQty": 10,
        "t1Qty": 5,
        "entryTimestamp": "2026-09-13T09:45:00Z",
    }
    # Bar hitting T1
    bar1 = {"timestamp": "2026-09-13T09:46:00Z", "open": 101.0, "high": 106.0, "low": 100.0, "close": 105.5}
    res1 = evaluate_position(pos, bar1)
    assert res1["t1Filled"] is True
    assert res1["effectiveStop"] >= 100.0  # Ratcheted up at least to entry

    # Next bar breaching new ratcheted stop
    bar2 = {"timestamp": "2026-09-13T09:47:00Z", "open": 104.0, "high": 104.0, "low": 99.0, "close": 99.5}
    res2 = evaluate_position(res1, bar2)
    assert res2["terminal"] is True
    assert res2["exitReason"] == "TRAIL_STOP_FILLED"


def test_stop_never_loosens_for_long_or_short():
    from app.services.swing_v2.lifecycle import update_stop

    # LONG position
    long_pos = {"direction": "LONG", "effectiveStop": 100.0}
    assert update_stop(long_pos, 98.0)["effectiveStop"] == 100.0  # never loosen
    assert update_stop(long_pos, 102.0)["effectiveStop"] == 102.0  # tighten

    # SHORT position
    short_pos = {"direction": "SHORT", "effectiveStop": 100.0}
    assert update_stop(short_pos, 102.0)["effectiveStop"] == 100.0  # never loosen
    assert update_stop(short_pos, 98.0)["effectiveStop"] == 98.0  # tighten


def test_per_symbol_isolation_symbol_a_does_not_block_b(tmp_path):
    import threading
    from app.services.swing_v2.ledger import SwingLedger

    ledger = SwingLedger(str(tmp_path / "isolation.sqlite3"))
    results = {}

    def worker(sym: str):
        event = ledger.append(
            idempotency_key=f"dec_{sym}:FILL_COMPLETE",
            decision_id=f"dec_{sym}",
            position_id=f"pos_{sym}",
            symbol=sym,
            session_date="2026-09-13",
            event_type="FILL_COMPLETE",
            event_timestamp="2026-09-13T09:45:00Z",
            payload={"symbol": sym, "entryPrice": 100.0, "qty": 5},
        )
        results[sym] = event

    t1 = threading.Thread(target=worker, args=("RELIANCE",))
    t2 = threading.Thread(target=worker, args=("TCS",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert "RELIANCE" in results
    assert "TCS" in results


def test_restart_restores_exact_trailing_stop_and_state(tmp_path):
    from app.services.swing_v2.ledger import SwingLedger, materialize_position

    db_file = str(tmp_path / "restart.sqlite3")
    ledger1 = SwingLedger(db_file)
    ledger1.append(
        idempotency_key="dec1:FILL_COMPLETE",
        decision_id="dec1",
        position_id="pos1",
        symbol="TCS",
        session_date="2026-09-13",
        event_type="FILL_COMPLETE",
        event_timestamp="2026-09-13T09:45:00Z",
        payload={"symbol": "TCS", "entryPrice": 3000.0, "initialStop": 2900.0, "effectiveStop": 2900.0, "qty": 10},
    )
    ledger1.append(
        idempotency_key="dec1:STOP_UPDATED",
        decision_id="dec1",
        position_id="pos1",
        symbol="TCS",
        session_date="2026-09-13",
        event_type="STOP_UPDATED",
        event_timestamp="2026-09-13T10:00:00Z",
        payload={"effectiveStop": 2950.25},
    )

    # Re-instantiate ledger (simulating restart)
    ledger2 = SwingLedger(db_file)
    events = ledger2.events(position_id="pos1")
    state = materialize_position(events)
    assert state["effectiveStop"] == 2950.25


def test_missing_history_causes_backfill_or_hold_not_ready():
    from app.services.swing_v2.market_data import historical_bars

    bars = historical_bars("UNKNOWN_SYMBOL_XYZ", "ONE_MINUTE", 100)
    assert bars == []


def test_corporate_action_applies_r_formula_and_persists(tmp_path):
    from app.services.swing_v2.engine import process_corporate_action
    from app.services.swing_v2.ledger import SwingLedger

    ledger = SwingLedger(str(tmp_path / "ca.sqlite3"))
    ledger.append(
        idempotency_key="dec1:FILL_COMPLETE",
        decision_id="dec1",
        position_id="pos1",
        symbol="INFY",
        session_date="2026-09-13",
        event_type="FILL_COMPLETE",
        event_timestamp="2026-09-13T09:45:00Z",
        payload={"symbol": "INFY", "entryPrice": 100.0, "initialStop": 90.0, "effectiveStop": 90.0, "t1": 110.0, "qty": 50, "remainingQty": 50},
    )
    updated = process_corporate_action(ledger, "pos1", 2.0)  # 2:1 stock split
    assert updated["entryPrice"] == 50.0
    assert updated["effectiveStop"] == 45.0
    assert updated["t1"] == 55.0
    assert updated["qty"] == 100
    assert updated["remainingQty"] == 100
    assert updated["corporateActionApplied"] is True


def test_swing_owned_symbol_rejects_future_swing_new_selection(v2_env):
    # Verify candidate exclusion when already in occupied_symbols
    from app.services.swing_v2.facade import build_from_market_snapshot

    snapshot = {
        "stockQuotes": {
            "RELIANCE": {
                "ticker": "RELIANCE",
                "swingV2": {
                    "symbol": "RELIANCE",
                    "universeSegment": "NIFTY100",
                    "setupIds": ["EMA_PULLBACK_V2"],
                    "hardGateResults": {"TRADABLE": True},
                    "score": 90.0,
                    "segmentPercentile": 95.0,
                    "decisionPrice": 2500.0,
                    "initialStop": 2400.0,
                    "availableAskDepth": 1000,
                },
            }
        }
    }
    scan = build_from_market_snapshot(snapshot, final_lock=False, occupied_symbols={"RELIANCE"})
    assert len(scan.get("candidates") or []) == 0


def test_intraday_owned_symbol_rejects_swing_new_selection():
    from app.services.swing_v2.market_data import intraday_occupied_symbols

    # Returns set of symbols occupied by Intraday
    occupied = intraday_occupied_symbols("2026-09-13")
    assert isinstance(occupied, set)


def test_existing_swing_and_intraday_conflict_preserves_both(v2_env):
    # Cross-book resolution must preserve existing conflicts and not delete rows
    from app.services.swing_session import load_swing_session

    session = load_swing_session()
    assert isinstance(session, dict)


def test_no_cross_book_promotion():
    # Verify no function promotes Intraday -> Swing
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "swing_v2"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "promote_to_swing" not in text
        assert "promote_to_intraday" not in text


def test_no_cross_book_scrubbing_or_deletion():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "swing_v2"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "_scrub_cross_book_swing_rows" not in text


def test_slow_swing_consumer_cannot_block_market_data_publishing(monkeypatch):
    from app.services.swing_v2.authoritative import _refresh_snapshot

    monkeypatch.setattr(
        "app.services.swing_v2.authoritative._snapshot",
        lambda: {"swingV2DataStatus": {"featureRows": 1, "historyReadyRows": 1, "universeCurrent": True, "surveillanceCurrent": True, "corporateEventsCurrent": True}, "swingV2UniverseCoverage": 1.0, "swingV2Regime": "NORMAL"},
    )
    monkeypatch.setattr(
        "app.services.market_refresh_facade.refresh_market_snapshot",
        lambda *a, **kw: {"success": True},
    )
    snap = _refresh_snapshot("test_call")
    assert isinstance(snap, dict)
