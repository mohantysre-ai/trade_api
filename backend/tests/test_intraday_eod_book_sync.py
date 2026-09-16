from datetime import date, datetime, timezone
from unittest.mock import patch

from app.services.eod_intraday_report import (
    _load_canonical_intraday_picks,
    _session_leg_is_triggered,
    apply_session_leg_economics,
    generate_intraday_eod_report,
    intraday_book_cache_stale,
    project_session_live,
    session_realized_pnl,
)


def _session(*, pnl: float, locked: bool = True, day: str = "2026-08-18") -> dict:
    return {
        "locked": locked,
        "sessionDate": day,
        "long": [
            {
                "symbol": "AAA",
                "direction": "LONG",
                "realizedPnl": pnl,
                "exitReason": "EOD_SQUAREOFF",
                "executionStatus": "TRIGGERED",
            }
        ],
        "short": [],
    }


def _cached(*, pnl: float, source: str = "intraday_session") -> dict:
    return {
        "isMock": False,
        "symbolSource": source,
        "totalPnl": pnl,
        "cachedAt": datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc).isoformat(),
        "trades": [{"symbol": "AAA", "pnl": pnl}],
    }


def test_session_realized_excludes_skips():
    session = _session(pnl=37503.08)
    session["long"].append(
        {
            "symbol": "BBB",
            "direction": "LONG",
            "realizedPnl": 999,
            "skipped": True,
            "executionStatus": "NOT_TRIGGERED",
            "outcomeBucket": "SKIPPED",
        }
    )
    assert session_realized_pnl(session) == 37503.08


def test_session_realized_excludes_pending_entry():
    session = _session(pnl=37503.08)
    session["long"].append(
        {
            "symbol": "CCC",
            "direction": "LONG",
            "triggered": False,
            "executionStatus": "PENDING_ENTRY",
            "realizedPnl": 8888.0,
            "pnl": 8888.0,
        }
    )
    assert session_realized_pnl(session) == 37503.08
    pending = session["long"][-1]
    assert _session_leg_is_triggered(pending) is False
    reason, _ep, pnl, _meta = apply_session_leg_economics(
        pending, reason="ARCHIVE", exit_price=1.0, pnl=10.0, scale_meta=None
    )
    assert pnl == 10.0
    assert reason == "ARCHIVE"


def test_cache_stale_on_pnl_mismatch():
    day = date(2026, 8, 18)
    reason = intraday_book_cache_stale(
        for_date=day,
        cached=_cached(pnl=131000.0),
        picks=[{"symbol": "AAA"}],
        is_mock=False,
        symbol_source="intraday_session",
        session=_session(pnl=37503.08),
    )
    assert reason == "pnl_mismatch"


def test_cache_fresh_when_pnl_matches():
    day = date(2026, 8, 18)
    reason = intraday_book_cache_stale(
        for_date=day,
        cached=_cached(pnl=37503.08),
        picks=[{"symbol": "AAA"}],
        is_mock=False,
        symbol_source="intraday_session",
        session=_session(pnl=37503.08),
    )
    assert reason is None


def test_cache_stale_when_eod_scorecards_newer():
    day = date(2026, 8, 18)
    cached = _cached(pnl=37503.08)
    cache_ts = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc).timestamp()
    reason = intraday_book_cache_stale(
        for_date=day,
        cached=cached,
        picks=[{"symbol": "AAA"}],
        is_mock=False,
        symbol_source="intraday_session",
        session=_session(pnl=37503.08),
        scorecards_mtime=cache_ts + 120,
    )
    assert reason == "eod_scorecards_newer"


def test_apply_session_leg_overrides_candle_walk():
    reason, exit_price, pnl, meta = apply_session_leg_economics(
        {
            "symbol": "AAA",
            "realizedPnl": 120.5,
            "exitReason": "SL_HIT",
            "exitPrice": 99.0,
            "exitState": {"closed": True, "remainingQty": 0},
            "executionStatus": "TRIGGERED",
        },
        reason="EOD_SQUAREOFF",
        exit_price=110.0,
        pnl=400.0,
        scale_meta=None,
    )
    assert reason == "SL_HIT"
    assert exit_price == 99.0
    assert pnl == 120.5
    assert meta["exitState"]["closed"] is True


def test_project_session_live_mirrors_open_unrealized_and_closed_realized_pnl():
    session = {
        "locked": True,
        "sessionDate": "2026-08-18",
        "long": [
            {
                "symbol": "OPEN",
                "direction": "LONG",
                "entryPrice": 100.0,
                "ltp": 125.0,
                "approxQty": 1,
                "realizedPnl": 0.0,
                "unrealizedPnl": 25.0,
                "executionStatus": "TRIGGERED",
                "status": "RUNNING",
                "closed": False,
            },
            {
                "symbol": "CLOSED",
                "direction": "LONG",
                "entryPrice": 100.0,
                "ltp": 80.0,
                "approxQty": 1,
                "realizedPnl": -10.0,
                "unrealizedPnl": 0.0,
                "executionStatus": "TRIGGERED",
                "status": "STOP LOSS HIT",
                "closed": True,
            },
        ],
        "short": [],
    }
    report = project_session_live(session, date(2026, 8, 18), 1000.0)
    assert report["totalPnl"] == 15.0
    assert {row["symbol"]: row["pnl"] for row in report["trades"]} == {
        "OPEN": 25.0,
        "CLOSED": -10.0,
    }


def test_canonical_picks_include_session_names_missing_levels():
    day = date(2026, 8, 20)
    session = {
        "locked": True,
        "sessionDate": "2026-08-20",
        "long": [
            {
                "symbol": "AAA",
                "direction": "LONG",
                "entryPrice": 100.0,
                "stopLoss": 95.0,
                "target1": 110.0,
            },
            {"symbol": "BBB", "direction": "LONG"},
        ],
        "short": [{"symbol": "CCC", "direction": "SHORT"}],
    }
    day_picks = {
        "deskCounts": {"swing": 2, "intradayLong": 1, "intradayShort": 0, "total": 3},
        "sources": {"intradayDateParity": True},
        "picks": [
            {
                "symbol": "AAA",
                "book": "INTRADAY",
                "entryPrice": 100.0,
                "stopLoss": 95.0,
                "target1": 110.0,
            },
        ],
    }
    with (
        patch("app.services.eod_engine.ingestion.load_intraday_session", return_value=session),
        patch("app.services.eod_engine.ingestion.load_day_picks", return_value=day_picks),
        patch("app.services.eod_engine.ingestion.load_fixed_trade_plan", return_value={}),
    ):
        rows, is_mock, source, counts = _load_canonical_intraday_picks(day)
    assert is_mock is False
    assert source == "intraday_session"
    assert {r["symbol"] for r in rows} == {"AAA", "BBB", "CCC"}
    assert counts["intradayLong"] == 2
    assert counts["intradayShort"] == 1


def test_open_book_serves_cache_on_pnl_mismatch():
    day = date(2026, 8, 20)
    cached = {
        "isMock": False,
        "symbolSource": "intraday_session",
        "marketPhase": "OPEN",
        "totalPnl": 100.0,
        "cachedAt": datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc).isoformat(),
        "trades": [{"symbol": "AAA", "pnl": 100.0}],
    }
    session = {
        "locked": True,
        "sessionDate": "2026-08-20",
        "long": [
            {
                "symbol": "AAA",
                "direction": "LONG",
                "realizedPnl": 250.0,
                "exitReason": "EOD_SQUAREOFF",
                "executionStatus": "TRIGGERED",
            }
        ],
        "short": [],
    }
    with (
        patch(
            "app.services.eod_intraday_report._load_canonical_intraday_picks",
            return_value=(
                [{"symbol": "AAA"}],
                False,
                "intraday_session",
                {"swing": 0, "intradayLong": 1, "intradayShort": 0, "total": 1},
            ),
        ),
        patch("app.services.desk_clock.cash_session_phase", return_value="OPEN"),
        patch("app.services.eod_engine.ingestion.load_intraday_session", return_value=session),
        patch("app.services.eod_book_cache.load_book_cache", return_value=cached),
        patch("app.services.eod_book_cache.save_book_cache") as save,
        patch("app.services.eod_reference.prefetch_close_marks") as prefetch,
    ):
        out = generate_intraday_eod_report(day, force=False)
    assert out is cached
    save.assert_not_called()
    prefetch.assert_not_called()


def test_open_book_never_serves_stale_symbol_set_when_session_is_locked():
    day = date(2026, 8, 20)
    cached = {
        "isMock": False,
        "symbolSource": "intraday_session",
        "marketPhase": "OPEN",
        "totalPnl": 0.0,
        "cachedAt": datetime(2026, 8, 20, 4, 0, tzinfo=timezone.utc).isoformat(),
        "trades": [{"symbol": "OLD", "pnl": 0.0}],
    }
    session = {
        "locked": True,
        "sessionDate": "2026-08-20",
        "long": [{"symbol": "NEW", "direction": "LONG", "entryPrice": 100.0, "currentPrice": 101.0, "approxQty": 1}],
        "short": [],
    }
    with (
        patch(
            "app.services.eod_intraday_report._load_canonical_intraday_picks",
            return_value=([{"symbol": "NEW"}], False, "intraday_session", {"swing": 0, "intradayLong": 1, "intradayShort": 0, "total": 1}),
        ),
        patch("app.services.desk_clock.cash_session_phase", return_value="OPEN"),
        patch("app.services.eod_engine.ingestion.load_intraday_session", return_value=session),
        patch("app.services.eod_book_cache.load_book_cache", return_value=cached),
        patch("app.services.eod_intraday_report.project_session_live", return_value={"trades": [{"symbol": "NEW"}]}) as project,
    ):
        out = generate_intraday_eod_report(day, force=False)
    assert out["trades"][0]["symbol"] == "NEW"
    project.assert_called_once()
