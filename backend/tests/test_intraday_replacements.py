"""Auto-apply free-slot replacements and evidence-gated re-entries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services import intraday_session_engine as eng


IST = timezone(timedelta(hours=5, minutes=30))


def _closed_long(sym: str = "LOSER") -> dict:
    return {
        "symbol": sym,
        "direction": "LONG",
        "closed": True,
        "status": "STOP LOSS HIT",
        "slotFreed": True,
        "slotStatus": "REPLACEABLE",
        "sector": "AUTO",
        "sleeve": "MOMENTUM",
        "entryPrice": 100.0,
        "approxQty": 10,
    }


def _closed_target_long(sym: str = "WINNER") -> dict:
    return {
        "symbol": sym,
        "direction": "LONG",
        "closed": True,
        "status": "CLOSED",
        "slotFreed": True,
        "slotStatus": "REPLACEABLE",
        "sector": "PHARMA",
        "sleeve": "MOMENTUM",
        "entryPrice": 100.0,
        "riskPerShare": 2.0,
        "target1": 103.0,
        "target2": 106.0,
        "approxQty": 400,
        "deployedCapital": 40_000.0,
        "exitState": {
            "legsFilled": [
                {"r": 1.5, "price": 103.0},
                {"r": 3.0, "price": 106.0},
            ],
            "economicR": 2.4,
            "mfeR": 3.0,
        },
        "outcome": {
            "label": "SCALE COMPLETE",
            "closed": True,
            "resolvedAt": "2026-08-11T04:30:00+00:00",
        },
    }


def _closed_profit_trail(sym: str = "RUNNER") -> dict:
    return {
        "symbol": sym,
        "direction": "LONG",
        "closed": True,
        "status": "CLOSED",
        "slotFreed": True,
        "slotStatus": "REPLACEABLE",
        "sector": "PHARMA",
        "sleeve": "MOMENTUM",
        "entryPrice": 100.0,
        "riskPerShare": 2.0,
        "approxQty": 100,
        "exitState": {
            "legsFilled": [{"r": "TRAIL_SL", "price": 102.0}],
            "economicR": 0.6,
            "mfeR": 1.5,
        },
        "outcome": {
            "label": "TRAIL STOP HIT",
            "closed": True,
            "resolvedAt": "2026-08-11T04:30:00+00:00",
        },
    }


def _open_long(sym: str, sector: str = "IT") -> dict:
    return {
        "symbol": sym,
        "direction": "LONG",
        "closed": False,
        "status": "RUNNING",
        "sector": sector,
        "sleeve": "MOMENTUM",
        "entryPrice": 100.0,
        "riskPerShare": 2.0,
        "approxQty": 10,
        "deployedCapital": 1000.0,
    }


def _pool_cand(sym: str, *, score: float = 70.0) -> dict:
    return {
        "symbol": sym,
        "direction": "LONG",
        "sector": "PHARMA",
        "sleeve": "MOMENTUM",
        "score": score,
        "entryPrice": 200.0,
        "ltp": 200.0,
        "riskPerShare": 4.0,
        "atrPct": 2.0,
        "rewardRisk": 2.0,
        "inPlay": True,
        "oiAligned": True,
        "oiSetup": "LONG_BUILDUP",
    }


def _qualified_gate(*_a, **_k) -> dict:
    return {
        "entryState": eng.ENTRY_QUALIFIED,
        "qualityAdjustedExpectedR": 1.2,
        "flags": [],
        "oiSetup": "LONG_BUILDUP",
        "oiAligned": True,
    }


def _reentry_qualified_gate(*_a, **_k) -> dict:
    return {
        "entryState": eng.ENTRY_QUALIFIED,
        "qualityAdjustedExpectedR": 1.6,
        "flags": ["IN_PLAY", "OI_PREFERRED"],
        "oiSetup": "LONG_BUILDUP",
        "oiAligned": True,
    }


def _reentry_cand(sym: str, *, ltp: float = 107.0, score: float = 70.0) -> dict:
    return {
        **_pool_cand(sym, score=score),
        "entryPrice": ltp,
        "ltp": ltp,
        "ltpRaw": ltp,
        "riskPerShare": 2.0,
    }


def test_apply_replacement_restores_open_count():
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_long("LOSER"), _open_long("KEEP1"), _open_long("KEEP2", "BANK")],
        "short": [],
        "candidatePoolLong": [_pool_cand("NEWONE")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [
        {
            "symbol": "NEWONE",
            "direction": "LONG",
            "score": 70,
            "entryState": eng.ENTRY_QUALIFIED,
            "ltp": 200.0,
            "proposalOnly": True,
        }
    ]
    with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
        with patch.object(eng, "sync_fixed_plan_from_session"):
            with patch("app.services.trade_outcome.emit_replacement_alerts", return_value=[]):
                applied = eng.apply_replacements(
                    session, proposals, {}, {}, bypass_window=True
                )
    assert len(applied) == 1
    assert applied[0]["symbol"] == "NEWONE"
    assert applied[0]["source"] == "REPLACEMENT"
    assert applied[0]["replacedFrom"] == "LOSER"
    assert applied[0]["triggered"] is True
    assert applied[0]["executionStatus"] == "TRIGGERED"
    assert applied[0]["lockObservedPrice"] == 200.0
    free = eng.compute_free_slots(session["long"], session["short"])
    assert free["openLong"] == 3
    assert free["long"] == max(0, eng.MAX_LONG_POSITIONS - 3)
    assert any(e.get("type") == "REPLACEMENT_APPLIED" for e in session["events"])


def test_sl_symbol_excluded_from_reentry():
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_long("LOSER")],
        "short": [],
        "candidatePoolLong": [_pool_cand("LOSER")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "LOSER", "direction": "LONG", "score": 80, "ltp": 200.0}]
    with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
        with patch("app.services.trade_outcome.emit_replacement_alerts", return_value=[]):
            applied = eng.apply_replacements(session, proposals, {}, {}, bypass_window=True)
    assert applied == []
    assert eng.compute_free_slots(session["long"], session["short"])["openLong"] == 0


def test_target_reentry_requires_cooldown_and_fresh_breakout():
    prior = _closed_target_long()
    gate = _reentry_qualified_gate()
    before_cooldown = eng._reentry_decision(
        [prior],
        _reentry_cand("WINNER", ltp=107.0),
        "LONG",
        gate,
        now=datetime(2026, 8, 11, 10, 10, tzinfo=IST),
    )
    assert before_cooldown["allowed"] is False
    assert before_cooldown["reason"] == "reentry_cooldown"

    no_new_break = eng._reentry_decision(
        [prior],
        _reentry_cand("WINNER", ltp=106.0),
        "LONG",
        gate,
        now=datetime(2026, 8, 11, 10, 25, tzinfo=IST),
    )
    assert no_new_break["allowed"] is False
    assert no_new_break["reason"] == "reentry_fresh_breakout_not_confirmed"

    allowed = eng._reentry_decision(
        [prior],
        _reentry_cand("WINNER", ltp=107.0),
        "LONG",
        gate,
        now=datetime(2026, 8, 11, 10, 25, tzinfo=IST),
    )
    assert allowed["allowed"] is True
    assert allowed["isReentry"] is True
    assert allowed["reason"] == "REENTRY_AFTER_TARGET"
    assert allowed["riskScale"] == eng.REENTRY_PROFIT_RISK_SCALE
    assert allowed["sameLogicConfirmed"] is True
    assert allowed["currentLogic"] == "MOMENTUM"


def test_reentry_requires_same_deterministic_sleeve():
    prior = _closed_target_long()
    changed_logic = eng._reentry_decision(
        [prior],
        {**_reentry_cand("WINNER", ltp=107.0), "sleeve": "MEAN_REVERSION"},
        "LONG",
        _reentry_qualified_gate(),
        now=datetime(2026, 8, 11, 10, 25, tzinfo=IST),
    )
    assert changed_logic["allowed"] is False
    assert changed_logic["reason"] == "reentry_logic_changed"
    assert changed_logic["priorLogic"] == "MOMENTUM"
    assert changed_logic["currentLogic"] == "MEAN_REVERSION"


def test_reentry_requires_full_current_entry_gate():
    prior = _closed_target_long()
    decision = eng._reentry_decision(
        [prior],
        _reentry_cand("WINNER", ltp=107.0),
        "LONG",
        {**_reentry_qualified_gate(), "entryState": eng.ENTRY_WAIT_RETEST},
        now=datetime(2026, 8, 11, 10, 25, tzinfo=IST),
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "reentry_base_logic_not_qualified"


def test_profitable_trail_reentry_requires_new_high_beyond_prior_mfe():
    prior = _closed_profit_trail()
    gate = _reentry_qualified_gate()
    no_reclaim = eng._reentry_decision(
        [prior],
        _reentry_cand("RUNNER", ltp=102.9),
        "LONG",
        gate,
        now=datetime(2026, 8, 11, 10, 35, tzinfo=IST),
    )
    assert no_reclaim["allowed"] is False
    assert no_reclaim["reason"] == "reentry_fresh_breakout_not_confirmed"

    allowed = eng._reentry_decision(
        [prior],
        _reentry_cand("RUNNER", ltp=103.2),
        "LONG",
        gate,
        now=datetime(2026, 8, 11, 10, 35, tzinfo=IST),
    )
    assert allowed["allowed"] is True
    assert allowed["exitKind"] == "PROFIT_TRAIL"
    assert allowed["referencePrice"] == 103.0


def test_initial_stop_reentry_stays_disabled_by_default():
    prior = {
        **_closed_long("STOPPED"),
        "riskPerShare": 2.0,
        "closedAt": "2026-08-11T04:30:00+00:00",
        "outcome": {"label": "INITIAL STOP HIT", "closed": True},
        "exitState": {"legsFilled": [{"r": "INITIAL_SL", "price": 98.0}]},
    }
    decision = eng._reentry_decision(
        [prior],
        _reentry_cand("STOPPED", ltp=108.0, score=90.0),
        "LONG",
        {**_reentry_qualified_gate(), "qualityAdjustedExpectedR": 2.2},
        now=datetime(2026, 8, 11, 12, 0, tzinfo=IST),
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "initial_stop_reentry_disabled"


def test_propose_target_reentry_exposes_auditable_policy_fields():
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_target_long("WINNER")],
        "short": [],
        "candidatePoolLong": [],
        "candidatePoolShort": [],
        "events": [],
    }
    now = datetime(2026, 8, 11, 10, 25, tzinfo=IST)
    with patch.object(eng, "replacement_window_open", return_value=(True, None)):
        with patch.object(eng, "swing_locked_symbols", return_value=set()):
            with patch.object(eng, "_ist_now", return_value=now):
                with patch.object(eng, "entry_quality_gate", side_effect=_reentry_qualified_gate):
                    proposed = eng.propose_replacements(
                        session,
                        {},
                        {},
                        hunt_pools=([_reentry_cand("WINNER")], []),
                    )
    assert len(proposed) == 1
    assert proposed[0]["isReentry"] is True
    assert proposed[0]["replaceReason"] == "REENTRY_AFTER_TARGET"
    assert proposed[0]["reentryExitKind"] == "TARGET_COMPLETE"
    assert proposed[0]["reentryReferencePrice"] == 106.0
    assert proposed[0]["reentrySameLogicConfirmed"] is True
    assert proposed[0]["reentryLogic"] == "MOMENTUM"


def test_apply_target_reentry_is_tagged_and_smaller():
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_target_long("WINNER")],
        "short": [],
        "candidatePoolLong": [_reentry_cand("WINNER")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "WINNER", "direction": "LONG", "score": 70, "ltp": 107.0}]
    with patch.object(eng, "entry_quality_gate", side_effect=_reentry_qualified_gate):
        with patch.object(eng, "sync_fixed_plan_from_session"):
            with patch("app.services.trade_outcome.emit_replacement_alerts", return_value=[]):
                applied = eng.apply_replacements(session, proposals, {}, {}, bypass_window=True)
    assert len(applied) == 1
    assert applied[0]["symbol"] == "WINNER"
    assert applied[0]["source"] == "REENTRY"
    assert applied[0]["adoptReason"] == "REENTRY_AFTER_TARGET"
    assert applied[0]["replacedFrom"] == "WINNER"
    assert applied[0]["reentryExitKind"] == "TARGET_COMPLETE"
    assert applied[0]["reentrySameLogicConfirmed"] is True
    assert applied[0]["reentryLogic"] == "MOMENTUM"
    assert applied[0]["riskScale"] <= 0.5
    assert any(event.get("type") == "REENTRY_APPLIED" for event in session["events"])


def test_daily_replacement_cap_blocks_further_rotation():
    used = [
        {**_closed_long(f"OLD{i}"), "source": "REPLACEMENT"}
        for i in range(eng.MAX_DAILY_REPLACEMENTS)
    ]
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_long("LOSER"), *used],
        "short": [],
        "candidatePoolLong": [_pool_cand("NEWONE")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "NEWONE", "direction": "LONG", "score": 70, "ltp": 200.0}]
    with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
        assert eng.apply_replacements(session, proposals, {}, {}, bypass_window=True) == []


def test_daily_position_count_includes_reentry_but_not_pending_rows():
    rows = [
        {**_open_long("LOCKED"), "adopted": True, "triggered": True},
        {
            **_closed_target_long("REPEAT"),
            "source": "REENTRY",
            "adoptReason": "REENTRY_AFTER_TARGET",
        },
        {
            **_open_long("PENDING"),
            "adopted": True,
            "triggered": False,
            "executionStatus": "PENDING_ENTRY",
        },
    ]
    assert eng._daily_position_count(rows) == 2


def test_twenty_entry_session_cap_blocks_replacements_and_reentries():
    used = [
        {
            **_closed_target_long(f"USED{i}"),
            "source": "LOCK" if i < 5 else "ROTATION",
            "triggered": True,
            "executionStatus": "TRIGGERED",
        }
        for i in range(20)
    ]
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": used,
        "short": [],
        "candidatePoolLong": [_pool_cand("NEWONE")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "NEWONE", "direction": "LONG", "score": 70, "ltp": 200.0}]
    with patch.object(eng, "MAX_DAILY_POSITIONS", 20):
        with patch.object(eng, "MAX_DAILY_REPLACEMENTS", 50):
            with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
                applied = eng.apply_replacements(
                    session, proposals, {}, {}, bypass_window=True
                )
    assert applied == []


def test_outside_rotation_window_no_apply():
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_long("LOSER")],
        "short": [],
        "candidatePoolLong": [_pool_cand("NEWONE")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "NEWONE", "direction": "LONG", "score": 70, "ltp": 200.0}]
    with patch.object(eng, "replacement_window_open", return_value=(False, "after_rotation")):
        with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
            applied = eng.apply_replacements(session, proposals, {}, {}, bypass_window=False)
    assert applied == []
    assert len(session["long"]) == 1


def test_no_qualified_leaves_session_unchanged():
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_long("LOSER")],
        "short": [],
        "candidatePoolLong": [_pool_cand("WEAK")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "WEAK", "direction": "LONG", "score": 70, "ltp": 200.0}]

    def _reject(*_a, **_k):
        return {"entryState": eng.ENTRY_NO_EDGE, "qualityAdjustedExpectedR": 0.2, "flags": []}

    with patch.object(eng, "entry_quality_gate", side_effect=_reject):
        applied = eng.apply_replacements(session, proposals, {}, {}, bypass_window=True)
    assert applied == []
    assert [r["symbol"] for r in session["long"]] == ["LOSER"]


def test_replacement_source_pools_live_ignores_lock_pool(monkeypatch):
    eng._HUNT_POOL_CACHE.update({"key": "", "at": 0.0, "long": [], "short": []})
    monkeypatch.setattr(
        "app.services.trade_outcome._is_market_open",
        lambda: True,
    )

    def _hunt(snap, *, include_full_hunt=False):
        assert include_full_hunt is True
        return {
            "replacementHuntLong": [_pool_cand("FRESH")],
            "replacementHuntShort": [],
        }

    monkeypatch.setattr(eng, "generate_candidates", _hunt)
    session = {"candidatePoolLong": [_pool_cand("STALE")], "candidatePoolShort": []}
    long_p, _short_p, src = eng._replacement_source_pools(session, {"updatedAt": "live-1"})
    assert src == "live_universe_hunt"
    assert long_p[0]["symbol"] == "FRESH"


def test_replacement_source_pools_closed_uses_lock_pool(monkeypatch):
    eng._HUNT_POOL_CACHE.update({"key": "", "at": 0.0, "long": [], "short": []})
    monkeypatch.setattr(
        "app.services.trade_outcome._is_market_open",
        lambda: False,
    )
    session = {"candidatePoolLong": [_pool_cand("STALE")], "candidatePoolShort": []}
    long_p, _short_p, src = eng._replacement_source_pools(session, {"updatedAt": "x"})
    assert src == "lock_pool"
    assert long_p[0]["symbol"] == "STALE"


def test_apply_uses_hunt_pools_not_lock_pool():
    session = {
        "locked": True,
        "sessionDate": "2026-08-11",
        "long": [_closed_long("LOSER"), _open_long("KEEP1"), _open_long("KEEP2", "BANK")],
        "short": [],
        "candidatePoolLong": [_pool_cand("STALE")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [
        {
            "symbol": "FRESH",
            "direction": "LONG",
            "score": 70,
            "entryState": eng.ENTRY_QUALIFIED,
            "ltp": 200.0,
            "proposalOnly": True,
        }
    ]
    hunt = [_pool_cand("FRESH")]
    with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
        with patch.object(eng, "sync_fixed_plan_from_session"):
            with patch("app.services.trade_outcome.emit_replacement_alerts", return_value=[]):
                applied = eng.apply_replacements(
                    session,
                    proposals,
                    {},
                    {},
                    bypass_window=True,
                    hunt_pools=(hunt, []),
                )
    assert len(applied) == 1
    assert applied[0]["symbol"] == "FRESH"
    lock_syms = {str(c.get("symbol")) for c in session["candidatePoolLong"]}
    assert "FRESH" not in lock_syms


def test_no_apply_when_open_book_at_capital_cap():
    session = {
        "locked": True,
        "sessionDate": "2026-08-18",
        "long": [
            {**_closed_long("LOSER"), "deployedCapital": 50_000.0},
            {**_open_long("KEEP1"), "deployedCapital": eng.INTRADAY_CAPITAL},
        ],
        "short": [],
        "candidatePoolLong": [_pool_cand("NEWONE")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "NEWONE", "direction": "LONG", "score": 70, "ltp": 200.0}]
    with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
        with patch("app.services.trade_outcome.emit_replacement_alerts", return_value=[]):
            applied = eng.apply_replacements(session, proposals, {}, {}, bypass_window=True)
    assert applied == []
    assert [r["symbol"] for r in session["long"] if not r.get("closed")] == ["KEEP1"]


def test_replacement_sized_to_freed_slot_not_full_book():
    session = {
        "locked": True,
        "sessionDate": "2026-08-18",
        "long": [
            {
                **_closed_long("LOSER"),
                "deployedCapital": 40_000.0,
                "entryPrice": 100.0,
                "approxQty": 400,
            },
            {**_open_long("KEEP1"), "deployedCapital": 200_000.0},
        ],
        "short": [],
        "candidatePoolLong": [_pool_cand("NEWONE")],
        "candidatePoolShort": [],
        "events": [],
    }
    proposals = [{"symbol": "NEWONE", "direction": "LONG", "score": 70, "ltp": 200.0}]
    with patch.object(eng, "entry_quality_gate", side_effect=_qualified_gate):
        with patch.object(eng, "sync_fixed_plan_from_session"):
            with patch("app.services.trade_outcome.emit_replacement_alerts", return_value=[]):
                applied = eng.apply_replacements(session, proposals, {}, {}, bypass_window=True)
    assert len(applied) == 1
    assert float(applied[0]["deployedCapital"]) <= 40_000.01
    open_notional = sum(
        float(r.get("deployedCapital") or 0)
        for r in session["long"]
        if not r.get("closed")
    )
    assert open_notional <= eng.INTRADAY_CAPITAL + 0.01


def _stale_snap() -> dict:
    return {"updatedAt": "2020-01-01T00:00:00+00:00", "stockQuotes": {}}


def test_maybe_refresh_does_not_stamp_gap_on_failure(monkeypatch):
    eng._SNAP_REFRESH_LAST = 0.0
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: True)
    monkeypatch.setattr(eng, "load_market_snapshot", _stale_snap)
    monkeypatch.setattr(
        "app.services.angel_one_feed.run_scheduled_live_refresh",
        lambda **_k: {"success": False, "error": "angel down"},
    )
    eng._maybe_refresh_live_snapshot(reason="test")
    assert eng._SNAP_REFRESH_LAST == 0.0


def test_maybe_refresh_does_not_stamp_gap_on_exception(monkeypatch):
    eng._SNAP_REFRESH_LAST = 0.0
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: True)
    monkeypatch.setattr(eng, "load_market_snapshot", _stale_snap)

    def _boom(**_k):
        raise RuntimeError("angel timeout")

    monkeypatch.setattr("app.services.angel_one_feed.run_scheduled_live_refresh", _boom)
    eng._maybe_refresh_live_snapshot(reason="test")
    assert eng._SNAP_REFRESH_LAST == 0.0


def test_maybe_refresh_stamps_gap_only_after_success(monkeypatch):
    eng._SNAP_REFRESH_LAST = 0.0
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: True)
    monkeypatch.setattr(eng, "load_market_snapshot", _stale_snap)
    monkeypatch.setattr(
        "app.services.angel_one_feed.run_scheduled_live_refresh",
        lambda **_k: {"success": True},
    )
    eng._maybe_refresh_live_snapshot(reason="test")
    assert eng._SNAP_REFRESH_LAST > 0.0


def test_get_poll_skips_snapshot_refresh(monkeypatch):
    refreshes: list[str] = []
    session = {"locked": False, "regime": {"label": "LOCK"}}
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: True)
    monkeypatch.setattr(eng, "load_session", lambda: session)
    monkeypatch.setattr(eng, "load_market_snapshot", _stale_snap)

    def _refresh(*, reason: str):
        refreshes.append(reason)
        return {"updatedAt": "2026-08-17T09:07:00+00:00", "stockQuotes": {}}

    monkeypatch.setattr(eng, "_maybe_refresh_live_snapshot", _refresh)
    monkeypatch.setattr(eng, "detect_regime", lambda _snap: {"label": "LIVE"})
    out = eng._compute_session(include_live=False, persist=False)
    assert refreshes == []
    assert out["regime"]["label"] == "LIVE"
    assert session["regime"]["label"] == "LIVE"


def test_persist_refreshes_snapshot_and_stamps_live_regime(monkeypatch):
    refreshes: list[str] = []
    session = {"locked": False, "regime": {"label": "LOCK"}}
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: True)
    monkeypatch.setattr(eng, "load_session", lambda: session)
    monkeypatch.setattr(eng, "load_market_snapshot", _stale_snap)

    def _refresh(*, reason: str):
        refreshes.append(reason)
        return {"updatedAt": "2026-08-17T09:07:00+00:00", "stockQuotes": {}}

    monkeypatch.setattr(eng, "_maybe_refresh_live_snapshot", _refresh)
    monkeypatch.setattr(eng, "detect_regime", lambda _snap: {"label": "LIVE"})
    out = eng._compute_session(include_live=False, persist=True)
    assert refreshes == ["intraday_replacement_hunt"]
    assert out["regime"]["label"] == "LIVE"
    assert session["regime"]["label"] == "LIVE"


def test_closed_row_keeps_session_pnl_not_live_ghost():
    pos = {
        "symbol": "GRSE",
        "direction": "LONG",
        "closed": True,
        "status": "TRAIL STOP HIT",
        "entryPrice": 2644.8,
        "approxQty": 75,
        "realizedPnl": 990.3,
        "effectiveStop": 2645.31,
        "exitState": {"mfeR": 1.2, "realizedPnl": 990.3, "effectiveStop": 2645.31},
    }
    live = {
        "symbol": "GRSE",
        "realizedPnl": 33617.55,
        "effectiveStop": 3735.64,
        "exitState": {"mfeR": 83.9, "realizedPnl": 33617.55, "effectiveStop": 3735.64},
        "ltp": 2677.0,
    }
    out = eng._enrich_position(pos, {}, live)
    assert out["realizedPnl"] == 990.3
    assert out["effectiveStop"] == 2645.31
    assert out["exitState"]["mfeR"] == 1.2
    assert out["closed"] is True


def test_get_applies_current_exit_policy_without_writing(monkeypatch):
    session = {
        "locked": False,
        "long": [{
            "symbol": "NTPC",
            "direction": "LONG",
            "entryPrice": 100.0,
            "stopLoss": 99.5,
            "riskPerShare": 0.5,
            "approxQty": 50,
            "closed": False,
            "status": "RUNNING",
            "exitPlan": {
                "mode": "SCALE_TRAIL",
                "notes": ["40pct_runner", "be_at_0p25r"],
                "trailRatchet": {"0.25": 0.0},
                "entry": 100.0,
                "direction": "LONG",
                "riskPerShare": 0.5,
                "initialStop": 99.5,
            },
        }],
        "short": [],
    }
    saves: list = []
    path_calls: list = []
    monkeypatch.setattr(eng, "load_session", lambda: session)
    monkeypatch.setattr(eng, "save_session", lambda payload: saves.append(payload))
    monkeypatch.setattr(eng, "load_market_snapshot", _stale_snap)
    monkeypatch.setattr(eng, "detect_regime", lambda _snap: {"label": "LOCK"})
    monkeypatch.setattr(
        eng,
        "overwrite_rows_with_current_policy",
        lambda *a, **k: path_calls.append(True) or (a[0], False),
    )
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: False)
    out = eng._compute_session(include_live=False, persist=False)
    assert saves == []
    assert path_calls == []
    notes = ((out.get("long") or [{}])[0].get("exitPlan") or {}).get("notes") or []
    assert "be_at_0p5r" in notes
    assert "max_stop_0p5pct" in notes
