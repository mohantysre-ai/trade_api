from datetime import datetime, timezone

import app.services.intraday_session_engine as eng
from app.services.angel_index_options import option_data_to_strategy_inputs
from app.services.angel_one_feed import (
    _snapshot_needs_live_refresh,
    build_market_payload,
    kick_background_live_refresh,
)


def test_prefer_cache_preserves_snapshot_updated_at(monkeypatch):
    original = "2026-08-27T04:30:00+00:00"
    snap = {
        "success": True,
        "updatedAt": original,
        "selectionMeta": {"dataDate": "2026-08-27", "mode": "live"},
        "stockQuotes": {},
        "stocks": [],
    }
    monkeypatch.setattr("app.services.angel_one_feed._load_last_snapshot", lambda: snap)
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: False)
    monkeypatch.setattr(
        "app.services.angel_one_feed._hydrate_dhan_swing_picks",
        lambda payload, **kwargs: payload,
    )
    monkeypatch.setattr(
        "app.services.angel_one_feed._hydrate_ticker_intelligence_map",
        lambda payload: payload,
    )
    out = build_market_payload(None, prefer_cache=True)  # type: ignore[arg-type]
    assert out["updatedAt"] == original
    assert out["snapshotDataDate"] == "2026-08-27"
    assert out.get("liveRefreshPending") is False


def test_snapshot_needs_live_refresh_when_data_date_stale(monkeypatch):
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: True)
    monkeypatch.setattr(
        "app.services.angel_one_feed._ist_now",
        lambda: datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )
    snap = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "selectionMeta": {"dataDate": "2026-08-27"},
    }
    assert _snapshot_needs_live_refresh(snap) is True


def test_structure_gate_warming_is_incomplete_not_hard_fail():
    option_data = {
        "indices": {
            "NIFTY": {
                "source": "ANGEL_ONE",
                "status": "LIVE",
                "spot": 25000,
                "spotClose": 24900,
                "chain": [],
                "structure": {"status": "NO_BREAKOUT", "direction": None, "barCount": 6},
                "future": {},
            }
        }
    }
    converted = option_data_to_strategy_inputs(option_data, {"stockQuotes": {}})
    row = converted["indices"]["NIFTY"]
    assert row["gates"]["structure"] is None
    assert row["gates"]["breakout"] is None


def test_read_path_proposes_replacement_hunt_without_persist(monkeypatch):
    session = {
        "locked": True,
        "sessionDate": "2026-08-28",
        "long": [{"symbol": "AAA", "status": "RUNNING", "closed": False, "deployedCapital": 100000}],
        "short": [],
        "capital": {
            "longCapital": eng.LONG_CAPITAL,
            "shortCapital": eng.SHORT_CAPITAL,
            "riskFraction": eng.RISK_FRACTION,
            "basketSize": eng.BASKET_SIZE,
        },
    }
    monkeypatch.setattr("app.services.trade_outcome._is_market_open", lambda: True)
    monkeypatch.setattr(eng, "load_session", lambda: session)
    monkeypatch.setattr(
        eng,
        "load_market_snapshot",
        lambda: {"updatedAt": "2026-08-28T04:30:00+00:00", "stockQuotes": {}},
    )
    monkeypatch.setattr(eng, "_maybe_refresh_live_snapshot", lambda **kwargs: eng.load_market_snapshot())
    monkeypatch.setattr(eng, "detect_regime", lambda _snap: {"label": "NEUTRAL"})
    monkeypatch.setattr(eng, "replacement_window_open", lambda **kwargs: (True, None))
    monkeypatch.setattr(eng, "rotation_window_allowed", lambda: (True, "OPEN"))
    monkeypatch.setattr(eng, "rotation_window_config", lambda: {})
    monkeypatch.setattr(
        eng,
        "_replacement_source_pools",
        lambda *_args: ([{"symbol": "BBB", "direction": "LONG"}], [], "live_universe_hunt"),
    )
    proposals = [{"symbol": "BBB", "direction": "LONG", "entryState": eng.ENTRY_QUALIFIED}]
    monkeypatch.setattr(eng, "propose_replacements", lambda *_args, **_kwargs: proposals)
    monkeypatch.setattr(eng, "apply_replacements", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not apply")))
    out = eng._compute_session(include_live=True, persist=False)
    assert out.get("replacementCandidates")
    assert out["replacementCandidates"][0]["proposalOnly"] is True


def test_kick_background_live_refresh_coalesced(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr("app.services.angel_one_feed._load_last_snapshot", lambda: {"selectionMeta": {"dataDate": "2026-08-27"}})
    monkeypatch.setattr("app.services.angel_one_feed._snapshot_needs_live_refresh", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "app.services.angel_one_feed.run_scheduled_live_refresh",
        lambda **kwargs: calls.append(kwargs["reason"]) or {"success": True},
    )
    monkeypatch.setattr(
        "app.services.angel_one_feed.threading.Thread",
        lambda target, **kwargs: type("ImmediateThread", (), {"start": lambda self: target()})(),
    )
    kick_background_live_refresh(reason="test")
    kick_background_live_refresh(reason="test")
    assert calls == ["test"]
