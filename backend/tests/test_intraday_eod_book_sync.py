from datetime import date, datetime, timezone

from app.services.eod_intraday_report import (
    _session_leg_is_triggered,
    apply_session_leg_economics,
    intraday_book_cache_stale,
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
