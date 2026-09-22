"""Issue 3 E2E smoke: Intraday vs. EOD reconciliation parity.

Simulated flow:
  1. Ingest a market snapshot with <99% universe coverage (75-name universe,
     one quote missing) — the feed-integrity guard must refuse to lock.
  2. Re-ingest with healthy coverage and 19 LONG scanner candidates — the
     desk locks LOCK_SIZE names (incl. the INFY candidate trade) and keeps
     the rest in candidatePoolLong (slot caps, not a pipeline failure).
  3. Paper-trade a multi-leg index-option strategy (BULL_CALL_DEBIT_SPREAD)
     and a single-leg paper contract — open positions must register.
  4. Assert 100% parity between the live Intraday execution state and the
     EOD snapshots (intraday Book + index-options Book), including the
     status-drift staleness detector.
"""
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.services.eod_index_options_report import generate_index_options_eod_report
from app.services.eod_intraday_report import (
    generate_intraday_eod_report,
    intraday_book_cache_stale,
    intraday_eod_parity,
    project_session_live,
)
from app.services.eod_engine import ingestion
from app.services.index_options.runtime import (
    load_positions,
    process_strategy_cycle,
)
from app.services import intraday_session_engine as engine
from app.services.angel_index_options import IST_ZONE


UNIVERSE = 75  # 74/75 quotes present == 98.67% coverage (<99%)
SCANNER_LONGS = 19


def _scanner_row(symbol: str, px: float, score: float) -> dict:
    return {
        "symbol": symbol,
        "direction": "LONG",
        "entryPrice": px,
        "ltp": px,
        "ltpRaw": px,
        "currentPrice": px,
        "stopLoss": round(px * 0.99, 2),
        "target1": round(px * 1.01, 2),
        "target2": round(px * 1.02, 2),
        "deployedCapital": 50_000.0,
        "approxQty": 10,
        "score": score,
    }


@pytest.fixture()
def isolated_desk(tmp_path: Path, monkeypatch):
    session_file = tmp_path / "intraday_session.json"
    monkeypatch.setattr(ingestion, "_INTRADAY_SESSION_PATH", str(session_file))
    monkeypatch.setattr(engine, "_SESSION_FILE", session_file)
    monkeypatch.setattr(ingestion, "EOD_DATA_ROOT", str(tmp_path / "eod"))
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper_book.json"))
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "strategy.db"))
    monkeypatch.setattr(engine, "reconcile_cross_book", lambda *a, **k: {})
    monkeypatch.setattr(engine, "_maybe_refresh_live_snapshot", lambda *a, **k: {})
    with (
        patch("app.services.intraday_session_engine.basket_lock_allowed", return_value=(True, "")),
        patch("app.services.intraday_session_engine.sync_fixed_plan_from_session", lambda *a, **k: None),
        patch("app.services.trade_outcome.emit_book_lock_alerts", lambda *a, **k: None),
        patch(
            "app.services.intraday_market_state.get_intraday_market_state",
            side_effect=RuntimeError("guard_skipped_in_smoke"),
        ),
    ):
        yield tmp_path


def _healthy_candidates() -> dict:
    # INFY ranks inside the top LOCK_SIZE of the 19-LONG scanner results.
    symbols = ["INFY"] + [f"SCAN{i:02d}" for i in range(SCANNER_LONGS - 1)]
    pool = [_scanner_row(s, 1000.0 + i, 70.0 - i) for i, s in enumerate(symbols)]
    adopt = [dict(r) for r in pool[: engine.LOCK_SIZE]]
    assert "INFY" in {r["symbol"] for r in adopt}
    return {
        "proposedLong": pool,
        "proposedShort": [],
        "adoptLong": adopt,
        "adoptShort": [],
        "dataStale": False,
        "regime": {"label": "RISK_ON", "niftyChangePct": 0.4},
        "capital": {"longCapital": 500_000.0, "shortCapital": 500_000.0},
        "funnel": {"universe": UNIVERSE},
        "weights": {},
        "meanRevWeights": {},
        "snapshotUpdatedAt": datetime.now(IST_ZONE).isoformat(),
        "marketGeneration": 1,
    }


def _leg(symbol, side, bid, ask, strike):
    return {
        "symbol": symbol,
        "side": side,
        "bestBid": bid,
        "bestAsk": ask,
        "strike": strike,
        "optionType": "CALL",
        "expiry": "2026-09-17",
        "qty": 1,
        "lotSize": 50,
        "delta": 0.4,
        "gamma": 0.01,
        "theta": -0.2,
        "vega": 0.3,
        "iv": 14.0,
    }


def _multileg_candidate():
    legs = [
        _leg("NIFTY-A", "BUY", 99, 101, 25000),
        _leg("NIFTY-B", "SELL", 39, 41, 25200),
    ]
    return {
        "strategyId": "BULL_CALL_DEBIT_SPREAD",
        "strategyType": "BULL_CALL_DEBIT_SPREAD",
        "family": "DIRECTIONAL",
        "key": "NIFTY",
        "eligible": True,
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
        "snapshotId": "smoke-1",
        "quantAuthority": "INDEX_OPTIONS_QUANT_V2",
    }


def _option_snapshot():
    return {
        "indexOptions": {
            "indices": {
                "NIFTY": {
                    "rawChain": [
                        _leg("NIFTY-A", "BUY", 99, 101, 25000),
                        _leg("NIFTY-B", "SELL", 39, 41, 25200),
                    ]
                }
            }
        }
    }


def test_issue3_e2e_low_coverage_lock_multileg_options_and_full_parity(isolated_desk, monkeypatch):
    tmp_path = isolated_desk
    today = datetime.now(IST_ZONE).date()

    # ---- Step 1: ingest with <99% universe coverage -> commit must refuse ----
    broken = _healthy_candidates()
    broken["dataStale"] = True  # feed pipeline marks stale below coverage floor
    with patch.object(engine, "generate_candidates", return_value=broken):
        result = engine.commit_session()
    assert result.get("success") is False
    assert "STALE_SNAPSHOT" in str(result.get("error"))
    assert not engine.load_session().get("locked")

    # ---- Step 2: healthy 19-LONG scanner universe -> candidate trade locks ----
    with patch.object(engine, "generate_candidates", return_value=_healthy_candidates()):
        session = engine.commit_session()
    assert session.get("locked") is True
    assert session.get("sessionDate") == today.isoformat()
    locked_syms = {r["symbol"] for r in session["long"]}
    assert "INFY" in locked_syms
    assert len(locked_syms) <= engine.LOCK_SIZE
    # Scanner names beyond the slot caps stay in the pool — why a scanner
    # symbol is NOT locked (slots/caps, not a pipeline failure).
    assert len(session["candidatePoolLong"]) == SCANNER_LONGS
    unlocked = {r["symbol"] for r in session["candidatePoolLong"]} - locked_syms
    assert len(unlocked) == SCANNER_LONGS - len(locked_syms)
    infy = next(r for r in session["long"] if r["symbol"] == "INFY")
    assert infy["triggered"] is True
    assert infy["executionStatus"] == "TRIGGERED"
    assert infy["entryPrice"] == infy["lockObservedPrice"]

    # Intraday desk marks the trade to market and squares off at close.
    infy["realizedPnl"] = 1250.0
    infy["exitReason"] = "EOD_SQUAREOFF"
    infy["closed"] = True
    engine.save_session(session, force=True)

    # ---- Step 3: paper multi-leg option strategy registers open positions ----
    now = datetime.now(IST_ZONE).replace(hour=10, minute=0, second=0, microsecond=0)
    candidate = _multileg_candidate()
    radar = {"modularCandidates": [candidate], "modularSelected": [candidate]}
    opened = process_strategy_cycle(radar, _option_snapshot(), now)
    assert len(opened["open"]) == 1
    position = opened["open"][0]
    assert position["status"] == "OPEN"
    assert len(position["legs"]) == 2
    assert position["legs"][0]["entrySlippage"] >= 0
    assert load_positions(today.isoformat())[0]["strategyPositionId"] == position["strategyPositionId"]

    paper_book = tmp_path / "paper_book.json"
    paper_book.write_text(
        '{"sessionDate": "%s", "mode": "AUTO_PAPER_ONLY", "open": '
        '[{"symbol": "NIFTY-SINGLE", "unrealizedPnl": 60.0}], "closed": []}' % today.isoformat(),
        encoding="utf-8",
    )

    # ---- Step 4: 100% parity between Intraday state and EOD snapshots ----
    with patch("app.services.desk_clock.cash_session_phase", return_value="CLOSED"):
        report = generate_intraday_eod_report(today, force=True)

    assert report["symbolSource"] == "intraday_session"
    row = next(t for t in report["trades"] if t["symbol"] == "INFY")
    assert row["pnl"] == 1250.0
    assert row["executionStatus"] == "TRIGGERED"
    parity = report["parity"]
    assert parity["parity"] is True, parity
    assert parity["driftCount"] == 0
    assert parity["sessionLegs"] == parity["eodRows"] == len(session["long"]) + len(session["short"])

    # Projection parity is identical (read-only path).
    projected = project_session_live(engine.load_session(), for_date=today, capital=1_000_000.0)
    assert projected["parity"]["parity"] is True

    # Drift injection: mutating one EOD row must break parity loudly.
    drifted = {**report, "trades": [dict(report["trades"][0], pnl=1.0)] + report["trades"][1:]}
    broken_parity = intraday_eod_parity(engine.load_session(), drifted)
    assert broken_parity["parity"] is False
    assert any(d["kind"] == "PNL_MISMATCH" for d in broken_parity["drifts"])

    # Cache staleness detector: a cache written pre-fill must not hide a
    # locked trade that triggered afterwards (Issue 3 "locked trades missing").
    cached = {
        "isMock": False,
        "symbolSource": "intraday_session",
        "totalPnl": 0.0,
        "cachedAt": datetime.now(IST_ZONE).isoformat(),
        "trades": [
            {"symbol": r["symbol"], "direction": "LONG", "executionStatus": "NOT_TRIGGERED", "pnl": 0.0}
            for r in session["long"]
        ],
    }
    assert (
        intraday_book_cache_stale(
            for_date=today,
            cached=cached,
            picks=[{"symbol": r["symbol"]} for r in session["long"]],
            is_mock=False,
            symbol_source="intraday_session",
            session=engine.load_session(),
        )
        == "status_drift"
    )

    # Index-options EOD book mirrors the live paper book + modular multi-leg
    # positions even though the cache was written before the strategy entry.
    options_report = generate_index_options_eod_report(today)
    assert options_report["archiveStatus"] == "ARCHIVED"
    assert any(p["symbol"] == "NIFTY-SINGLE" for p in options_report["positions"])
    assert options_report["strategyEntryCount"] == 1
    strategy_row = options_report["strategyPositions"][0]
    assert strategy_row["strategy"] == "BULL_CALL_DEBIT_SPREAD"
    assert options_report["strategyUnrealizedPnl"] == pytest.approx(800.0)
    assert options_report["totalPnl"] == pytest.approx(60.0 + 800.0)


def test_issue3_parity_helper_detects_missing_and_extra_rows():
    session = {
        "locked": True,
        "sessionDate": "2026-09-16",
        "long": [{"symbol": "AAA", "direction": "LONG", "realizedPnl": 100.0, "closed": True,
                  "exitReason": "EOD_SQUAREOFF", "executionStatus": "TRIGGERED", "triggered": True}],
        "short": [],
    }
    # Missing EOD row -> parity False with MISSING_IN_EOD.
    result = intraday_eod_parity(session, {"trades": [], "totalPnl": 0.0})
    assert result["parity"] is False
    assert result["drifts"][0]["kind"] == "MISSING_IN_EOD"

    # Exact mirror -> parity True.
    mirrored = {
        "trades": [{"symbol": "AAA", "direction": "LONG", "executionStatus": "TRIGGERED", "pnl": 100.0}],
        "totalPnl": 100.0,
    }
    assert intraday_eod_parity(session, mirrored)["parity"] is True

    # Extra EOD row -> parity False with EXTRA_IN_EOD.
    extra = {
        "trades": mirrored["trades"] + [{"symbol": "GHOST", "direction": "LONG", "pnl": 5.0}],
        "totalPnl": 105.0,
    }
    result = intraday_eod_parity(session, extra)
    assert result["parity"] is False
    assert any(d["kind"] == "EXTRA_IN_EOD" for d in result["drifts"])

