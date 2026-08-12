from app.services import eod_swing_report, swing_session
from app.services import trade_outcome


def test_closed_swing_live_snapshot_uses_book_pnl_and_skips(monkeypatch):
    monkeypatch.setattr(
        swing_session,
        "load_swing_session",
        lambda: {
            "locked": True,
            "sessionDate": "2026-08-12",
            "long": [
                {"symbol": "LOSS", "entryPrice": 100, "approxQty": 10},
                {"symbol": "SKIP", "entryPrice": 50, "approxQty": 20},
            ],
            "short": [],
            "capital": {"swingCapital": 1_000_000},
        },
    )
    monkeypatch.setattr(swing_session, "_enforce_swing_position_cap", lambda sess: (sess, []))
    monkeypatch.setattr(swing_session, "_read_json", lambda _path: {})
    monkeypatch.setattr(swing_session, "_is_market_open", lambda: False)
    monkeypatch.setattr(trade_outcome, "fetch_live_marks_for_symbols", lambda _symbols: {})
    monkeypatch.setattr(
        swing_session,
        "_enrich_swing_row_prices",
        lambda row, *_args: {**row, "currentPrice": row["entryPrice"], "unrealizedPnl": 0},
    )
    monkeypatch.setattr(
        eod_swing_report,
        "generate_swing_eod_report",
        lambda *_args, **_kwargs: {
            "picks": [
                {
                    "symbol": "LOSS",
                    "currentPrice": 90,
                    "deployedCapital": 1000,
                    "pnl": -100,
                    "pnlPct": -10,
                    "triggered": True,
                    "executionStatus": "TRIGGERED",
                    "skipped": False,
                    "exitReason": "EOD_SQUAREOFF",
                },
                {
                    "symbol": "SKIP",
                    "currentPrice": 45,
                    "deployedCapital": 0,
                    "pnl": 0,
                    "pnlPct": 0,
                    "triggered": False,
                    "executionStatus": "NOT_TRIGGERED",
                    "skipped": True,
                    "skipReason": "SIGNAL_CONFLICT",
                    "status": "SIGNAL_CONFLICT",
                    "exitReason": "SIGNAL_CONFLICT",
                },
            ]
        },
    )

    result = swing_session._compute_swing_session(live=True)

    assert result["long"][0]["totalPnl"] == -100
    assert result["long"][1]["status"] == "SIGNAL_CONFLICT"
    assert result["long"][1]["deployedCapital"] == 0
    assert result["portfolio"] == {
        "swingCapital": 1_000_000,
        "realizedPnl": -100.0,
        "unrealizedPnl": 0.0,
        "totalPnl": -100.0,
        "lockedCount": 2,
    }
