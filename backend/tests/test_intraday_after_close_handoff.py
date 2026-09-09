from datetime import date

from app.services import eod_intraday_report as report


def test_live_recalculation_forwards_after_close_to_cached_book(monkeypatch):
    day = date(2026, 9, 9)
    session = {
        "sessionDate": day.isoformat(), "locked": True,
        "committedAt": "2026-09-09T04:30:00+00:00",
        "long": [], "short": [],
    }
    captured = {}

    monkeypatch.setattr("app.services.intraday_session_engine.load_session", lambda: session)
    monkeypatch.setattr("app.services.intraday_session_engine.save_session", lambda _value: None)
    monkeypatch.setattr("app.services.intraday_session_engine.sync_fixed_plan_from_session", lambda _value: None)
    monkeypatch.setattr("app.services.eod_book_cache.load_book_cache", lambda *_args, **_kwargs: {"trades": []})
    monkeypatch.setattr("app.services.eod_engine.ingestion.fetch_and_persist_candles", lambda *_args, **_kwargs: {})

    def _book(_day, *, after_close=None):
        captured["after_close"] = after_close
        return {"totalPnl": 0, "totalDeployed": 0}

    monkeypatch.setattr(report, "recalculate_cached_intraday_book", _book)
    result = report.recalculate_live_intraday_from_candles(day, after_close=True)
    assert result["ok"] is True
    assert captured["after_close"] is True
