from __future__ import annotations

from app.services import intraday_session_engine as eng
from app.services import swing_session
from app.services import sector_rotation


def _candidate(symbol: str, direction: str, expected_r: float, *, sector: str = "OTHER", score: float = 75) -> dict:
    entry = 100.0
    risk = 2.0
    return {
        "symbol": symbol,
        "direction": direction,
        "sector": sector,
        "entryState": eng.ENTRY_QUALIFIED,
        "qualityAdjustedExpectedR": expected_r,
        "score": score,
        "entryPrice": entry,
        "ltp": entry,
        "riskPerShare": risk,
        "entryFlags": ["IN_PLAY"],
        "components": {k: {"score": score} for k in ("trend", "vwap", "volume", "momentum", "sector")},
    }


def test_top_five_is_total_not_per_side():
    longs = [_candidate(f"L{i}", "LONG", 2.2 - i / 20) for i in range(6)]
    shorts = [_candidate(f"S{i}", "SHORT", 2.1 - i / 20) for i in range(6)]
    selected_l, selected_s = eng._select_total_portfolio(longs, shorts, 1_000_000)
    assert len(selected_l) + len(selected_s) <= eng.LOCK_SIZE == 5


def test_fewer_candidates_and_no_forced_fill():
    selected_l, selected_s = eng._select_total_portfolio(
        [_candidate("ONLY", "LONG", 1.6)], [], 1_000_000
    )
    assert [r["symbol"] for r in selected_l] == ["ONLY"]
    assert selected_s == []


def test_one_sided_market_can_use_all_five_slots():
    rows = [_candidate(f"L{i}", "LONG", 2.0, sector=f"SEC{i}") for i in range(5)]
    selected_l, selected_s = eng._select_total_portfolio(rows, [], 1_000_000)
    assert len(selected_l) == 5
    assert selected_s == []


def test_no_eligible_candidates_returns_cash():
    weak = _candidate("WEAK", "LONG", 0.5)
    weak["entryState"] = eng.ENTRY_NO_EDGE
    assert eng._select_total_portfolio([weak], [], 1_000_000) == ([], [])


def test_duplicate_and_sector_caps_are_deterministic():
    rows = [
        _candidate("DUP", "LONG", 2.2, sector="IT"),
        _candidate("DUP", "SHORT", 2.1, sector="IT"),
        _candidate("IT2", "LONG", 2.0, sector="IT"),
        _candidate("IT3", "LONG", 1.9, sector="IT"),
        _candidate("BANK", "SHORT", 1.8, sector="BANK"),
    ]
    longs, shorts = eng._select_total_portfolio(rows, [], 1_000_000)
    selected = longs + shorts
    assert len({r["symbol"] for r in selected}) == len(selected)
    assert sum(r["sector"] == "IT" for r in selected) <= eng.MAX_PER_SECTOR


def test_capital_and_risk_never_exceed_configuration():
    rows = [_candidate(f"N{i}", "LONG", 2.5, sector=f"SEC{i}") for i in range(5)]
    longs, shorts = eng._select_total_portfolio(rows, [], 10_000)
    selected = longs + shorts
    assert sum(r["deployedCapital"] for r in selected) <= 10_000
    assert sum(r["maxLoss"] for r in selected) <= 10_000 * eng.MAX_PORTFOLIO_RISK
    assert all(r["approxQty"] * r["entryPrice"] == r["deployedCapital"] for r in selected)


def test_swing_gate_rejects_expected_r_below_minimum(monkeypatch):
    monkeypatch.setattr(swing_session, "is_swing_desk_eligible", lambda *_: True)
    raw = {"symbol": "LOWR", "entryPrice": 100, "stopLoss": 95, "target1": 104, "target2": 106}
    assert swing_session._normalize_swing_row(raw, "2026-08-12") is None


def test_swing_grade_and_expected_r(monkeypatch):
    monkeypatch.setattr(swing_session, "is_swing_desk_eligible", lambda *_: True)
    raw = {"symbol": "GOOD", "entryPrice": 100, "stopLoss": 95, "target1": 107.5, "target2": 110}
    row = swing_session._normalize_swing_row(raw, "2026-08-12")
    assert row is not None
    assert row["expectedR"] == 2.0
    assert row["entryQuality"] == "ENTRY_A"


def test_persisted_swing_book_is_migrated_to_five_with_capital_recomputed():
    rows = [
        {
            "symbol": f"S{i}",
            "deployedCapital": 100_000.0,
            "maxLoss": 2_000.0,
        }
        for i in range(8)
    ]
    migrated, dropped = swing_session._enforce_swing_position_cap(
        {"locked": True, "long": rows, "short": [], "capital": {"swingCapital": 1_000_000}}
    )
    assert [r["symbol"] for r in migrated["long"]] == ["S0", "S1", "S2", "S3", "S4"]
    assert dropped == ["S5", "S6", "S7"]
    assert migrated["counts"] == {"long": 5, "short": 0, "total": 5}
    assert migrated["capital"]["deployedCapital"] == 500_000.0
    assert migrated["capital"]["remainingCapital"] == 500_000.0


def test_swing_cap_migration_is_idempotent():
    session = {"locked": True, "long": [{"symbol": f"S{i}"} for i in range(5)], "short": []}
    migrated, dropped = swing_session._enforce_swing_position_cap(session)
    assert migrated is session
    assert dropped == []


def test_nse_sector_payload_normalization_accepts_nested_shapes():
    rows = sector_rotation.normalize_sector_payload(
        {"data": [{"indexName": "NIFTY IT", "percentChange": "1.25%", "lastPrice": "42,100"}]}
    )
    assert rows == [{"index": "NIFTY IT", "pChange": 1.25, "last": 42100.0}]


def test_sector_signal_rewards_directional_sector_leader(monkeypatch):
    monkeypatch.setattr(
        sector_rotation,
        "get_sector_heatmap",
        lambda: {
            "stale": False,
            "updatedAt": "2026-08-13T04:30:00+00:00",
            "sectors": [{"index": "NIFTY IT", "pChange": 1.0}],
        },
    )
    signal = sector_rotation.sector_signal("IT", "LONG", 2.0)
    assert signal["rated"] is True
    assert signal["leader"] is True
    assert signal["stockVsSectorPct"] == 1.0
    assert signal["score"] > 50
