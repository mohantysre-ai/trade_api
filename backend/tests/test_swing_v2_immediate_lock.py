from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.swing_v2 import authoritative as auth


IST = ZoneInfo("Asia/Kolkata")


def test_manage_open_positions_reports_terminal_exit(monkeypatch):
    state = {
        "positionId": "p1",
        "symbol": "AAA",
        "entryTimestamp": "2026-09-21T10:00:00+05:30",
        "sessionDate": "2026-09-21",
        "terminal": False,
    }
    monkeypatch.setattr(auth, "_position_groups", lambda _ledger: {"p1": [{}]})
    monkeypatch.setattr(auth, "materialize_position", lambda _events: dict(state))
    monkeypatch.setattr(auth, "_quote_observations", lambda _symbols, _now: {"AAA": {"timestamp": "x", "ask": 110.0}})
    monkeypatch.setattr(auth, "session_age", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(auth, "time_exit_due", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(auth, "process_position_bar", lambda *_args, **_kwargs: {**state, "terminal": True})
    cfg = type("Cfg", (), {"max_overnights": 2, "mandatory_exit_ist": "15:15"})()
    count = auth._manage_open_positions(object(), datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc), cfg)
    assert count == (1, ["AAA"])


def test_manage_open_positions_returns_empty_result_without_open_positions(monkeypatch):
    monkeypatch.setattr(auth, "_position_groups", lambda _ledger: {})
    cfg = type("Cfg", (), {})()
    result = auth._manage_open_positions(object(), datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc), cfg)
    assert result == (0, [])


def test_hunt_window_fills_locked_orders_before_1510(monkeypatch, tmp_path):
    calls = []
    cfg = type("Cfg", (), {
        "paper_authoritative": True,
        "ledger_path": str(tmp_path / "swing.sqlite3"),
        "decision_start_ist": "09:45",
        "decision_freeze_ist": "15:10",
        "order_expire_ist": "15:20",
    })()
    monkeypatch.setattr(auth, "load_config", lambda: cfg)
    monkeypatch.setattr(auth, "_manage_open_positions", lambda *_args, **_kwargs: (0, []))
    monkeypatch.setattr(auth, "_read_json", lambda _path: {"sessionDate": "2026-09-21", "selectionFinalized": False})
    monkeypatch.setattr(auth, "_positions", lambda _ledger: [])
    monkeypatch.setattr(auth, "_refresh_snapshot", lambda *_args, **_kwargs: {"ready": True})
    monkeypatch.setattr(auth, "_v2_snapshot_ready", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(auth, "build_from_market_snapshot", lambda *_args, **_kwargs: {"blocked": False, "candidates": [{"symbol": "AAA"}]})
    monkeypatch.setattr(auth, "_fill_locked_orders", lambda *_args, **_kwargs: calls.append("fill"))
    monkeypatch.setattr(auth, "_write_state", lambda _payload: None)
    monkeypatch.setattr(auth, "_session", lambda scan=None, now=None: {"locked": True, "scan": scan})
    import app.services.nse_trading_calendar as cal
    import app.services.swing_v2.market_data as market_data
    monkeypatch.setattr(cal, "is_nse_trading_day", lambda _day: True)
    monkeypatch.setattr(market_data, "intraday_occupied_symbols", lambda _day: set())

    now = datetime(2026, 9, 21, 10, 5, tzinfo=IST)
    auth.run_authoritative_cycle(now=now)
    assert calls == ["fill"]
    auth._SESSION_READ_CACHE = None
