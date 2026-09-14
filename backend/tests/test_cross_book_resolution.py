from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import cross_book_resolution as xbook
from app.services import desk_book_symbols as desk
from app.services import swing_session as swing


def _swing_row(symbol: str, *, score: float = 90.0, rsi: float = 62.0) -> dict:
    return {
        "symbol": symbol,
        "ticker": symbol,
        "direction": "BUY",
        "deterministicSide": "BUY",
        "score": score,
        "confidence": 85.0,
        "rsi": rsi,
        "passes_hard_filters": True,
        "passes_quality_filters": True,
        "priceAboveVwap": True,
        "priceAboveEma9": True,
        "vwap": 100.0,
        "ema9": 99.0,
        "ltp": 101.0,
        "oiSetup": "LONG_BUILDUP",
        "oi": 1000.0,
        "prev_oi": 900.0,
        "breakoutPass": True,
        "pivotR1Breakout": True,
        "rsiPivotBreak": True,
        "riskAuditVerdict": "APPROVE",
    }


def _intraday_row(symbol: str, *, score: float = 55.0, qer: float = 1.1) -> dict:
    return {
        "symbol": symbol,
        "direction": "LONG",
        "entryState": "QUALIFIED",
        "score": score,
        "qualityAdjustedExpectedR": qer,
    }


def test_swing_prefers_when_contract_passes_and_score_higher(monkeypatch):
    snap = {"stocks": [_swing_row("APOLLOHOSP")], "stockQuotes": {}}
    monkeypatch.setattr(xbook, "_load_matrix_snapshot", lambda: snap)
    monkeypatch.setattr(
        swing,
        "_evaluate_swing_buy_contract",
        lambda row, **kwargs: (True, {}, []),
    )
    monkeypatch.setattr(swing, "_hydrate_swing_contract_row", lambda row: row)
    # Swing-first promotion is DISABLED: always returns False
    assert not xbook.swing_prefers_over_intraday(
        "APOLLOHOSP",
        _intraday_row("APOLLOHOSP", score=20.0, qer=0.5),
        snapshot=snap,
    )


def test_intraday_keeps_when_swing_contract_fails(monkeypatch):
    snap = {"stocks": [_swing_row("BHEL")], "stockQuotes": {}}
    monkeypatch.setattr(xbook, "_load_matrix_snapshot", lambda: snap)
    monkeypatch.setattr(
        swing,
        "_evaluate_swing_buy_contract",
        lambda row, **kwargs: (False, {}, ["HARD_FILTERS_NOT_PASSED"]),
    )
    monkeypatch.setattr(swing, "_hydrate_swing_contract_row", lambda row: row)
    assert not xbook.swing_prefers_over_intraday(
        "BHEL",
        _intraday_row("BHEL"),
        snapshot=snap,
    )


def test_reconcile_swing_untouched_intraday_blocks_on_conflict(tmp_path, monkeypatch):
    day = "2026-08-28"
    intra_path = tmp_path / "intraday_session.json"
    swing_path = tmp_path / "swing_session.json"
    # Swing owns RELIANCE (locked)
    swing_path.write_text(
        '{"locked":true,"sessionDate":"2026-08-28","long":[{"symbol":"RELIANCE","direction":"BUY","closed":false}],"short":[]}',
        encoding="utf-8",
    )
    # Intraday does not own it
    intra_path.write_text(
        '{"locked":true,"sessionDate":"2026-08-28","long":[],"short":[],"events":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(xbook, "_INTRADAY_SESSION_PATH", str(intra_path))
    monkeypatch.setattr(xbook, "_SWING_SESSION_PATH", str(swing_path))

    result = xbook.reconcile_cross_book(day, persist=True)
    # No promotion from intraday to swing
    assert result["promotedFromIntraday"] == []
    assert result["swingPreferred"] == []
    # No scrubbing - Swing remains untouched
    assert result["scrubbedFromSwing"] == []
    # Swing reports its owned symbols
    assert result["swingOwned"] == ["RELIANCE"]
    # Intraday blocks empty (no intraday symbols)
    assert result["intradayBlocksSwing"] == []
    # Swing file unchanged
    saved_swing = __import__("json").loads(swing_path.read_text(encoding="utf-8"))
    assert any(r.get("symbol") == "RELIANCE" for r in saved_swing.get("long", []))


def test_v2_swing_ownership_survives_same_day_exit(monkeypatch):
    monkeypatch.setenv("SWING_STRATEGY_AUTHORITY", "V2")
    monkeypatch.setattr(
        "app.services.swing_v2.authoritative.get_authoritative_session",
        lambda live=False: {
            "sessionDate": "2026-08-28",
            "long": [{"symbol": "TCS", "sessionDate": "2026-08-27", "terminal": False}],
            "closedPositions": [{"symbol": "RELIANCE", "sessionDate": "2026-08-28", "terminal": True, "lastEventAt": "2026-08-28T12:00:00+05:30"}],
        },
    )
    assert desk.swing_locked_symbols("2026-08-28") == {"RELIANCE", "TCS"}
