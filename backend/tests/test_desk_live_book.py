from unittest.mock import patch

from app.services.trade_outcome import load_desk_live_book, save_fixed_trade_plan, _session_date_str


def test_live_book_prefers_today_session_over_stale_plan():
    session = {
        "locked": True,
        "sessionDate": "2026-08-13",
        "updatedAt": "2026-08-13T05:00:00+00:00",
        "long": [{"symbol": "NTPC", "entryPrice": 340.75, "approxQty": 586}],
        "short": [{"symbol": "PFC", "entryPrice": 374.80, "approxQty": 500}],
    }
    stale_plan = {
        "sessionDate": "2026-08-11",
        "long": [{"symbol": "TECHM", "entryPrice": 1500, "approxQty": 10}],
        "short": [],
    }
    with patch("app.services.trade_outcome._today_ist", return_value="2026-08-13"):
        with patch("app.services.intraday_session_engine.load_session", return_value=session):
            with patch("app.services.trade_outcome.load_fixed_trade_plan", return_value=stale_plan):
                book, source = load_desk_live_book()
    assert source == "intraday_session"
    assert [r["symbol"] for r in book["long"]] == ["NTPC"]
    assert [r["symbol"] for r in book["short"]] == ["PFC"]


def test_save_fixed_plan_refuses_older_payload_when_today_locked():
    writes = []
    with patch("app.services.trade_outcome._today_ist", return_value="2026-08-13"):
        with patch(
            "app.services.intraday_session_engine.load_session",
            return_value={"locked": True, "sessionDate": "2026-08-13"},
        ):
            with patch("app.services.trade_outcome.load_fixed_trade_plan", return_value={"sessionDate": "2026-08-13"}):
                with patch("app.services.trade_outcome._atomic_write", side_effect=lambda *_a, **_k: writes.append(True)):
                    save_fixed_trade_plan({
                        "sessionDate": "2026-08-11",
                        "long": [{"symbol": "TECHM"}],
                        "short": [],
                    })
    assert writes == []


def test_market_snapshot_path_honors_env(tmp_path, monkeypatch):
    from app.services.market_snapshot_store import market_snapshot_path, readable_market_snapshot_path

    target = tmp_path / "last_market_snapshot.json"
    monkeypatch.setenv("MARKET_SNAPSHOT_FILE", str(target))
    assert market_snapshot_path() == target
    assert readable_market_snapshot_path().name == "last_market_snapshot.json"


def test_session_date_str_reads_entry_date_fallback():
    assert _session_date_str({"long": [{"entryDate": "2026-08-11"}]}) == "2026-08-11"
    assert _session_date_str({"sessionDate": "2026-08-13"}) == "2026-08-13"


def test_dummy_quote_stub_is_not_reused_as_candle_cache():
    from datetime import datetime, timezone

    from app.services.angel_one_feed import _snapshot_intraday_cache

    snap = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "stockQuotes": {
            "REAL": {"intraday": {"vwap": 100.0, "rsi": 60.0}},
            "DUMMY": {
                "intraday": {
                    "vwap": 0.0,
                    "rsi": 0.0,
                    "hard_filter_reasons": ["not in intraday candidate set"],
                }
            },
        },
    }
    cache = _snapshot_intraday_cache(snap)
    assert "REAL" in cache
    assert "DUMMY" not in cache
