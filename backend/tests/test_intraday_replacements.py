"""Auto-apply free-slot replacements after SL / complete."""
from __future__ import annotations

from unittest.mock import patch

from app.services import intraday_session_engine as eng


def _closed_long(sym: str = "LOSER") -> dict:
    return {
        "symbol": sym,
        "direction": "LONG",
        "closed": True,
        "status": "STOP LOSS HIT",
        "slotFreed": True,
        "slotStatus": "REPLACEABLE",
        "sector": "AUTO",
        "entryPrice": 100.0,
        "approxQty": 10,
    }


def _open_long(sym: str, sector: str = "IT") -> dict:
    return {
        "symbol": sym,
        "direction": "LONG",
        "closed": False,
        "status": "RUNNING",
        "sector": sector,
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
        with patch("app.services.trade_outcome.emit_replacement_alerts", return_value=[]):
            applied = eng.apply_replacements(
                session, proposals, {}, {}, bypass_window=True
            )
    assert len(applied) == 1
    assert applied[0]["symbol"] == "NEWONE"
    assert applied[0]["source"] == "REPLACEMENT"
    assert applied[0]["replacedFrom"] == "LOSER"
    free = eng.compute_free_slots(session["long"], session["short"])
    assert free["openLong"] == 3
    assert free["long"] == max(0, eng.LOCK_SIZE - 3)
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
