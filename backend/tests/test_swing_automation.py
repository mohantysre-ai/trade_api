from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from time import monotonic

from app.services import swing_session
from app.services.exit_plan import attach_exit_plan


def _qualified_locked_row(symbol: str = "VALID") -> dict:
    row = {
        "symbol": symbol,
        "name": symbol,
        "originalSide": "BUY",
        "deterministicSide": "BUY",
        "direction": "LONG",
        "entryPrice": 100.0,
        "stopLoss": 95.0,
        "target1": 107.5,
        "target2": 110.0,
        "riskPerShare": 5.0,
        "approxQty": 100,
        "deployedCapital": 10_000.0,
        "sessionLocked": True,
        "status": "RUNNING",
        "selectionEvidence": {
            "contract": swing_session.SWING_SELECTION_CONTRACT,
            "accepted": True,
            "originalSide": "BUY",
            "canonicalDirection": "LONG",
            "passesHardFilters": True,
            "passesQualityFilters": True,
            "vwap": 99.0,
            "ema9": 98.0,
            "rsi": 62.0,
            "oiSetup": "LONG_BUILDUP",
            "riskAuditVerdict": "APPROVE",
            "acceptanceReason": "test",
            "lockedAt": "2026-08-13T04:00:00+00:00",
            "lockSource": "test",
        },
        "acceptanceReason": "test",
        "passesHardFilters": True,
        "passesQualityFilters": True,
        "vwap": 99.0,
        "ema9": 98.0,
        "rsi": 62.0,
        "oiSetup": "LONG_BUILDUP",
        "riskAuditVerdict": "APPROVE",
        "verdict": "APPROVE",
    }
    return attach_exit_plan(row)


def test_refresh_persists_sl_hit_and_effective_stop(monkeypatch, tmp_path: Path):
    path = tmp_path / "swing_session.json"
    row = _qualified_locked_row("SLHIT")
    session = {
        "locked": True,
        "sessionDate": "2026-08-13",
        "long": [row],
        "short": [],
        "executionPolicy": "MANUAL_ONLY",
        "counts": {"long": 1, "short": 0, "total": 1},
    }
    swing_session._atomic_write(str(path), session)
    monkeypatch.setattr(swing_session, "_SWING_SESSION_PATH", str(path))
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(
        swing_session,
        "_compute_swing_session",
        lambda live=False: {
            **session,
            "long": [
                {
                    **row,
                    "ltp": 94.0,
                    "currentPrice": 94.0,
                    "closed": True,
                    "status": "INITIAL STOP HIT",
                    "effectiveStop": 95.0,
                    "realizedPnl": -500.0,
                    "unrealizedPnl": 0.0,
                    "exitState": {"closed": True, "effectiveStop": 95.0},
                    "outcome": {"label": "INITIAL STOP HIT", "hitLevel": "sl"},
                }
            ],
            "portfolio": {"totalPnl": -500.0, "realizedPnl": -500.0, "unrealizedPnl": 0.0},
        },
    )

    refreshed = swing_session.refresh_swing_session_state()
    disk = swing_session.load_swing_session()

    assert refreshed["long"][0]["closed"] is True
    assert disk["long"][0]["closed"] is True
    assert disk["long"][0]["effectiveStop"] == 95.0
    assert disk["long"][0]["status"] == "INITIAL STOP HIT"
    assert disk["automation"]["source"] == "refresh_swing_session_state"


def test_refresh_is_noop_for_prior_day_book(monkeypatch, tmp_path: Path):
    path = tmp_path / "swing_session.json"
    payload = {
        "locked": True,
        "sessionDate": "2026-08-12",
        "long": [_qualified_locked_row("OLD")],
        "short": [],
    }
    swing_session._atomic_write(str(path), payload)
    before = path.read_bytes()
    monkeypatch.setattr(swing_session, "_SWING_SESSION_PATH", str(path))
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")

    swing_session.refresh_swing_session_state()
    assert path.read_bytes() == before


def test_ensure_retry_empty_force_relocks(monkeypatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        swing_session,
        "load_swing_session",
        lambda: {
            "locked": True,
            "sessionDate": "2026-08-13",
            "cashHeld": True,
            "long": [],
            "short": [],
        },
    )
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")

    def _lock(*, force: bool = False, bypass_lock_window: bool = False):
        calls.append({"force": force, "bypass": bypass_lock_window})
        return {
            "success": True,
            "session": {
                "locked": True,
                "sessionDate": "2026-08-13",
                "cashHeld": False,
                "long": [_qualified_locked_row("NEW")],
                "short": [],
            },
        }

    monkeypatch.setattr(swing_session, "lock_swing_session", _lock)
    out = swing_session.ensure_swing_session_locked(retry_empty=True)
    assert calls == [{"force": True, "bypass": False}]
    assert out["long"][0]["symbol"] == "NEW"


def test_closed_today_book_is_not_force_relocked(monkeypatch):
    calls: list[dict] = []
    closed = _qualified_locked_row("BLS")
    closed["closed"] = True
    closed["status"] = "INITIAL STOP HIT"
    monkeypatch.setattr(
        swing_session,
        "load_swing_session",
        lambda: {
            "locked": True,
            "sessionDate": "2026-08-13",
            "cashHeld": False,
            "long": [closed],
            "short": [],
        },
    )
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")

    def _lock(*, force: bool = False, bypass_lock_window: bool = False):
        calls.append({"force": force, "bypass": bypass_lock_window})
        return {"success": True, "session": {"locked": True, "long": [closed], "short": []}}

    monkeypatch.setattr(swing_session, "lock_swing_session", _lock)
    out = swing_session.ensure_swing_session_locked(retry_empty=True)
    assert calls == [{"force": False, "bypass": False}]
    assert out["long"][0]["symbol"] == "BLS"
    assert out["long"][0]["closed"] is True


def test_live_response_archives_closed_row_instead_of_rendering_active(monkeypatch):
    closed = _qualified_locked_row("BLS")
    closed.update({
        "closed": True,
        "status": "INITIAL STOP HIT",
        "realizedPnl": -4286.0,
        "unrealizedPnl": 0.0,
    })
    monkeypatch.setattr(
        swing_session,
        "load_swing_session",
        lambda: {
            "locked": True,
            "sessionDate": "2026-08-17",
            "long": [closed],
            "short": [],
            "capital": {"swingCapital": 1_000_000},
        },
    )
    monkeypatch.setattr(swing_session, "_read_json", lambda _path: {})
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(
        "app.services.trade_outcome.fetch_live_marks_for_symbols",
        lambda _symbols: {},
    )

    out = swing_session._compute_swing_session(live=True)

    assert out["long"] == []
    assert out["counts"]["total"] == 0
    assert out["portfolio"]["lockedCount"] == 0
    assert out["portfolio"]["realizedPnl"] == -4286.0
    assert out["closedPositions"][0]["symbol"] == "BLS"


def test_stale_friday_matrix_cannot_lock_monday_pick(monkeypatch, tmp_path: Path):
    _patch_hunt(monkeypatch, tmp_path, hunt_ok=True, picks=[_raw_buy_pick("BLS")])
    monkeypatch.setattr(
        swing_session,
        "_ensure_today_matrix_snapshot",
        lambda: (False, "MATRIX_DATA_DATE_STALE:2026-08-14"),
    )

    out = swing_session.lock_swing_session()

    assert out["session"]["locked"] is False
    assert out["session"]["long"] == []
    assert out["session"]["cashReason"] == "MATRIX_DATA_DATE_STALE:2026-08-14"
    assert "MATRIX_DATA_DATE_STALE:2026-08-14" in out["session"]["skippedIncomplete"]


def _raw_buy_pick(symbol: str = "NEWBUY") -> dict:
    return {
        "ticker": symbol,
        "symbol": symbol,
        "deterministicSide": "BUY",
        "riskAuditVerdict": "APPROVE",
        "verdict": "APPROVE",
        "passes_hard_filters": True,
        "passes_quality_filters": True,
        "ltp": 100.0,
        "ltpRaw": 100.0,
        "entryPrice": 100.0,
        "stopLoss": 95.0,
        "target1": 107.5,
        "target2": 110.0,
        "score": 25.0,
        "intraday": {
            "vwap": 99.0,
            "ema9": 98.0,
            "price_above_vwap": True,
            "price_above_ema9": True,
            "rsi": 62.0,
            "oi_setup": "LONG_BUILDUP",
            "pivot_r1_breakout": True,
            "rsi_pivot_break": True,
        },
    }


def _patch_hunt(monkeypatch, tmp_path, *, hunt_ok=True, hunt_code="entry_hunt", picks=None):
    path = tmp_path / "swing_session.json"
    monkeypatch.setattr(swing_session, "_SWING_SESSION_PATH", str(path))
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")
    monkeypatch.setattr(
        swing_session,
        "swing_entry_hunt_allowed",
        lambda now=None, allow_manual_override=False: (
            True,
            "manual_override",
        )
        if allow_manual_override
        else (hunt_ok, hunt_code),
    )
    monkeypatch.setattr(swing_session, "intraday_locked_symbols_respecting_swing", lambda _day: set())
    monkeypatch.setattr(swing_session, "reconcile_cross_book", lambda *_a, **_k: {})
    monkeypatch.setattr(swing_session, "is_swing_desk_eligible", lambda *_a, **_k: True)
    monkeypatch.setattr(
        swing_session,
        "_swing_universe_diagnostics",
        lambda **_k: {
            "evaluated": 10,
            "qualified": len(picks or []),
            "crossBookExcluded": [],
            "topRejectionReasons": [],
        },
    )
    monkeypatch.setattr(
        swing_session,
        "_picks_from_asset_matrix",
        lambda exclude_symbols=None: (list(picks or []), "test"),
    )
    monkeypatch.setattr(swing_session, "_ensure_today_matrix_snapshot", lambda: (True, "READY"))
    return path


def test_empty_during_hunt_is_not_cash_locked(monkeypatch, tmp_path: Path):
    _patch_hunt(monkeypatch, tmp_path, hunt_ok=True, picks=[])
    out = swing_session.lock_swing_session()
    assert out["hunting"] is True
    assert out["cashHeld"] is False
    sess = out["session"]
    assert sess["locked"] is False
    assert sess["hunting"] is True
    assert sess["cashHeld"] is False
    assert sess["cashReason"] == "WAITING_FOR_QUALIFIED_BUY_ENTRY"
    disk = swing_session.load_swing_session()
    assert disk["locked"] is False
    assert disk["hunting"] is True


def test_empty_after_hunt_is_cash_held(monkeypatch, tmp_path: Path):
    _patch_hunt(monkeypatch, tmp_path, hunt_ok=False, hunt_code="after_hunt", picks=[])
    out = swing_session.lock_swing_session()
    assert out["cashHeld"] is True
    assert out["hunting"] is False
    sess = out["session"]
    assert sess["locked"] is True
    assert sess["cashHeld"] is True
    assert sess["hunting"] is False
    assert sess["cashReason"] == "NO_BUY_LOCKED_DURING_ENTRY_WINDOW"
    assert sess["entryHuntDiagnostics"]["qualified"] == 0
    assert sess["entryHuntDiagnostics"]["diagnosticPhase"] == "POST_HUNT_EOD"


def test_qualified_buy_locks_during_hunt_after_1015(monkeypatch, tmp_path: Path):
    _patch_hunt(monkeypatch, tmp_path, hunt_ok=True, picks=[_raw_buy_pick("ENTRY1")])
    out = swing_session.lock_swing_session()
    sess = out["session"]
    assert sess["locked"] is True
    assert sess["cashHeld"] is False
    assert sess["long"][0]["symbol"] == "ENTRY1"
    assert sess["long"][0]["slotNotional"] == round(swing_session.SWING_CAPITAL / swing_session.SWING_MATRIX_LOCK_COUNT, 2)


def test_fill_up_appends_without_dropping_locked_name(monkeypatch, tmp_path: Path):
    path = _patch_hunt(monkeypatch, tmp_path, hunt_ok=True, picks=[_raw_buy_pick("SECOND")])
    first = _qualified_locked_row("FIRST")
    swing_session._atomic_write(
        str(path),
        {
            "locked": True,
            "sessionDate": "2026-08-13",
            "cashHeld": False,
            "hunting": True,
            "long": [first],
            "short": [],
            "counts": {"long": 1, "short": 0, "total": 1},
        },
    )
    out = swing_session.lock_swing_session(force=False)
    sess = out["session"]
    symbols = [str(r.get("symbol")) for r in sess["long"]]
    assert "FIRST" in symbols
    assert "SECOND" in symbols
    assert out.get("filled") == ["SECOND"]


def test_unique_swing_rows_collapses_closed_clones_and_reentry():
    rows = [
        {"symbol": "BLS", "closed": False, "status": "RUNNING"},
        {"symbol": "MINDACORP", "closed": False, "status": "RUNNING"},
        {"symbol": "MINDACORP", "closed": True, "status": "SCALE COMPLETE"},
        {"symbol": "MINDACORP", "closed": True, "status": "INITIAL STOP HIT"},
    ]
    unique = swing_session._unique_swing_rows(rows)
    assert [r["symbol"] for r in unique] == ["BLS", "MINDACORP"]
    assert unique[1]["closed"] is True
    assert unique[1]["status"] == "INITIAL STOP HIT"


def test_fill_up_does_not_readd_closed_symbol(monkeypatch, tmp_path: Path):
    path = _patch_hunt(monkeypatch, tmp_path, hunt_ok=True, picks=[_raw_buy_pick("MINDACORP")])
    closed = _qualified_locked_row("MINDACORP")
    closed["closed"] = True
    closed["status"] = "INITIAL STOP HIT"
    open_other = _qualified_locked_row("BLS")
    swing_session._atomic_write(
        str(path),
        {
            "locked": True,
            "sessionDate": "2026-08-13",
            "cashHeld": False,
            "hunting": True,
            "long": [open_other, closed],
            "short": [],
            "counts": {"long": 2, "short": 0, "total": 2},
        },
    )
    filled = swing_session._append_new_swing_entries(swing_session.load_swing_session())
    assert filled is None
    disk = swing_session.load_swing_session()
    minda = [r for r in disk["long"] if str(r.get("symbol")) == "MINDACORP"]
    assert len(minda) == 1
    assert minda[0]["closed"] is True
    assert minda[0]["status"] == "INITIAL STOP HIT"


def test_fill_up_refreshes_matrix_before_picks(monkeypatch, tmp_path: Path):
    calls: list[str] = []
    path = _patch_hunt(monkeypatch, tmp_path, hunt_ok=True, picks=[_raw_buy_pick("SECOND")])

    def _ensure():
        calls.append("ensure")
        return True, "READY"

    monkeypatch.setattr(swing_session, "_ensure_today_matrix_snapshot", _ensure)
    first = _qualified_locked_row("FIRST")
    swing_session._atomic_write(
        str(path),
        {
            "locked": True,
            "sessionDate": "2026-08-13",
            "cashHeld": False,
            "hunting": True,
            "long": [first],
            "short": [],
            "counts": {"long": 1, "short": 0, "total": 1},
        },
    )
    out = swing_session._append_new_swing_entries(swing_session.load_swing_session())
    assert calls == ["ensure"]
    assert out is not None
    assert "SECOND" in (out.get("filled") or [])


def test_refresh_does_not_copy_closed_label_onto_open_row(monkeypatch, tmp_path: Path):
    path = tmp_path / "swing_session.json"
    open_row = _qualified_locked_row("BLS")
    closed = _qualified_locked_row("MINDACORP")
    closed["closed"] = True
    closed["status"] = "INITIAL STOP HIT"
    clone = {**closed, "status": "SCALE COMPLETE"}
    session = {
        "locked": True,
        "sessionDate": "2026-08-13",
        "long": [open_row, clone, closed],
        "short": [],
        "executionPolicy": "MANUAL_ONLY",
        "counts": {"long": 3, "short": 0, "total": 3},
    }
    swing_session._atomic_write(str(path), session)
    monkeypatch.setattr(swing_session, "_SWING_SESSION_PATH", str(path))
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(
        swing_session,
        "_compute_swing_session",
        lambda live=False: {
            **session,
            "long": [
                {**open_row, "ltp": 101.0, "currentPrice": 101.0, "unrealizedPnl": 100.0},
                {**clone, "ltp": 730.0},
                {**closed, "ltp": 730.0},
            ],
            "portfolio": {"totalPnl": -500.0, "realizedPnl": -500.0, "unrealizedPnl": 100.0},
        },
    )

    refreshed = swing_session.refresh_swing_session_state()
    minda = [r for r in refreshed["long"] if str(r.get("symbol")) == "MINDACORP"]
    assert len(minda) == 1
    assert minda[0]["status"] == "INITIAL STOP HIT"
    assert minda[0]["closed"] is True
    bls = [r for r in refreshed["long"] if str(r.get("symbol")) == "BLS"]
    assert len(bls) == 1
    assert bls[0].get("closed") is not True


def test_ensure_refreshes_when_today_quotes_stale(monkeypatch):
    swing_session._SWING_MATRIX_REFRESH_AT = 0.0
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-17")
    stale = {
        "updatedAt": "2026-08-17T04:48:00+00:00",
        "selectionMeta": {"dataDate": "2026-08-17"},
        "universeSize": 500,
        "stocks": [{"deterministicSide": "BUY"} for _ in range(8)],
        "stockQuotes": {f"T{i}": {"ltp": 100} for i in range(500)},
    }
    fresh = {**stale, "updatedAt": datetime.now(timezone.utc).isoformat()}
    reads: list[str] = []

    def _read(*_a, **_k):
        if not reads:
            reads.append("stale")
            return stale
        reads.append("fresh")
        return fresh

    monkeypatch.setattr(swing_session, "_read_json", _read)
    calls: list[str] = []
    monkeypatch.setattr(
        swing_session,
        "_run_swing_matrix_refresh",
        lambda: calls.append("refresh") or {"success": True},
    )
    ready, reason = swing_session._ensure_today_matrix_snapshot()
    assert ready is True
    assert reason == "READY"
    assert calls == ["refresh"]


def test_ensure_cooldown_does_not_fill_on_stale_quotes(monkeypatch):
    swing_session._SWING_MATRIX_REFRESH_AT = monotonic()
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: True)
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-17")
    snap = {
        "updatedAt": "2026-08-17T04:48:00+00:00",
        "selectionMeta": {"dataDate": "2026-08-17"},
        "universeSize": 500,
        "stocks": [{"deterministicSide": "BUY"} for _ in range(8)],
        "stockQuotes": {f"T{i}": {"ltp": 100} for i in range(500)},
    }
    monkeypatch.setattr(swing_session, "_read_json", lambda *_a, **_k: snap)
    calls: list[str] = []
    monkeypatch.setattr(
        swing_session,
        "_run_swing_matrix_refresh",
        lambda: calls.append("refresh") or {"success": True},
    )
    ready, reason = swing_session._ensure_today_matrix_snapshot()
    assert ready is False
    assert reason == "MATRIX_QUOTES_STALE"
    assert calls == []


def test_auto_paper_execution_records_fill(monkeypatch):
    monkeypatch.setattr(swing_session, "SWING_EXECUTION_POLICY", "AUTO_PAPER")
    normalized = swing_session._normalize_swing_row(_raw_buy_pick("PAPER1"), "2026-08-13")
    assert normalized is not None
    row = swing_session._size_new_swing_rows([normalized])[0]
    filled = swing_session._paper_execute_swing_row(row, filled_at="2026-08-13T05:00:00+00:00")
    assert filled["executionStatus"] == "FILLED"
    assert filled["executionMode"] == "PAPER"
    assert filled["triggered"] is True
    assert filled["qty"] == filled["approxQty"]
    assert filled["lineage"]["executedFills"][0]["mode"] == "PAPER"


def test_swing_refresh_ttl_defaults_to_one_minute():
    assert swing_session._SWING_MATRIX_REFRESH_TTL <= 60
