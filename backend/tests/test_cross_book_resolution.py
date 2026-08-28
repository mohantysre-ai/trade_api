from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import cross_book_resolution as xbook
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
    assert xbook.swing_prefers_over_intraday(
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


def test_reconcile_promotes_intraday_long_to_swing(tmp_path, monkeypatch):
    day = "2026-08-28"
    intra_path = tmp_path / "intraday_session.json"
    swing_path = tmp_path / "swing_session.json"
    intra_path.write_text(
        '{"locked":true,"sessionDate":"2026-08-28","long":[{"symbol":"GRASIM","direction":"LONG","closed":false}],"short":[],"events":[]}',
        encoding="utf-8",
    )
    swing_path.write_text(
        '{"locked":true,"sessionDate":"2026-08-28","long":[],"short":[]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(xbook, "_INTRADAY_SESSION_PATH", str(intra_path))
    monkeypatch.setattr(xbook, "_SWING_SESSION_PATH", str(swing_path))
    monkeypatch.setattr(xbook, "symbols_swing_prefers_over_intraday", lambda *_a, **_k: {"GRASIM"})
    monkeypatch.setattr(
        "app.services.intraday_session_engine.save_session",
        lambda payload: intra_path.write_text(
            __import__("json").dumps(payload),
            encoding="utf-8",
        ),
    )

    result = xbook.reconcile_cross_book(day, persist=True)
    assert result["promotedFromIntraday"] == ["GRASIM"]
    saved = __import__("json").loads(intra_path.read_text(encoding="utf-8"))
    assert saved.get("long") == []
    assert saved.get("crossBookPromotedToSwing") == ["GRASIM"]
