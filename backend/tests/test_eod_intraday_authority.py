from app.services.eod_intraday_authority import reconcile_report


def _base(symbol, direction="LONG", entry=100.0, qty=100):
    return {
        "symbol": symbol,
        "direction": direction,
        "entryPrice": entry,
        "exitPrice": entry,
        "qty": qty,
        "deployedCapital": entry * qty,
        "pnl": 0.0,
        "exitReason": "EOD_SQUAREOFF",
    }


def test_closed_stop_uses_intraday_realized_not_eod_mark():
    report = {"capital": 100000, "totalPnl": -1800, "trades": [_base("STOPPED")]}
    session = {
        "long": [{
            "symbol": "STOPPED", "direction": "LONG", "entryPrice": 100,
            "approxQty": 100, "deployedCapital": 10000, "triggered": True,
            "executionStatus": "TRIGGERED", "closed": True, "status": "STOP LOSS HIT",
            "realizedPnl": -500.0, "ltp": 94.0,
            "exitState": {"legsFilled": [{"r": "INITIAL_SL", "qty": 100, "price": 95.0, "pnl": -500.0}]},
            "remainingQty": 0,
        }],
        "short": [],
    }
    out = reconcile_report(report, session)
    row = out["trades"][0]
    assert row["pnl"] == -500.0
    assert row["realizedPnl"] == -500.0
    assert row["unrealizedPnl"] == 0.0
    assert row["exitPrice"] == 95.0
    assert row["exitReason"] == "STOP LOSS HIT"
    assert out["totalPnl"] == -500.0


def test_partial_preserves_booked_tranche_plus_remaining_mtm():
    report = {"capital": 100000, "totalPnl": 0, "trades": [_base("PARTIAL", entry=100, qty=100)]}
    session = {
        "long": [{
            "symbol": "PARTIAL", "direction": "LONG", "entryPrice": 100,
            "approxQty": 100, "deployedCapital": 10000, "triggered": True,
            "executionStatus": "TRIGGERED", "closed": False, "status": "PARTIAL 1.5R",
            "realizedPnl": 75.0, "unrealizedPnl": 100.0, "totalPnl": 175.0,
            "ltp": 102.0, "remainingQty": 50,
            "exitState": {"legsFilled": [{"r": 1.5, "qty": 50, "price": 101.5, "pnl": 75.0}]},
        }],
        "short": [],
    }
    row = reconcile_report(report, session)["trades"][0]
    assert row["exitReason"] == "PARTIAL_SCALE"
    assert row["closed"] is False
    assert row["remainingQty"] == 50
    assert row["realizedPnl"] == 75.0
    assert row["unrealizedPnl"] == 100.0
    assert row["pnl"] == 175.0
    assert row["pnlKind"] == "mixed"


def test_open_position_is_eod_mtm_not_zero_binary_close():
    report = {"capital": 100000, "totalPnl": 0, "trades": [_base("OPEN", entry=200, qty=10)]}
    session = {
        "long": [{
            "symbol": "OPEN", "direction": "LONG", "entryPrice": 200,
            "approxQty": 10, "deployedCapital": 2000, "triggered": True,
            "executionStatus": "TRIGGERED", "closed": False, "status": "SESSION CLOSED",
            "realizedPnl": None, "unrealizedPnl": 50.0, "totalPnl": 50.0,
            "ltp": 205.0, "remainingQty": 10,
        }],
        "short": [],
    }
    row = reconcile_report(report, session)["trades"][0]
    assert row["exitReason"] == "OPEN_EOD_MTM"
    assert row["closed"] is False
    assert row["exitPrice"] == 205.0
    assert row["pnl"] == 50.0
    assert row["pnlKind"] == "unrealised"


def test_not_triggered_is_always_zero():
    report = {"capital": 100000, "totalPnl": -999, "trades": [_base("SKIP")]}
    session = {
        "long": [{"symbol": "SKIP", "direction": "LONG", "executionStatus": "NOT_TRIGGERED", "skipped": True}],
        "short": [],
    }
    row = reconcile_report(report, session)["trades"][0]
    assert row["pnl"] == 0.0
    assert row["executionStatus"] == "NOT_TRIGGERED"
    assert row["pnlKind"] == "skipped"
