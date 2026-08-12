from __future__ import annotations

from pathlib import Path

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
