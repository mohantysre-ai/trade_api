from __future__ import annotations

from app.services import intraday_session_engine as eng
from app.services import sector_rotation


def _qualified_swing_raw(**overrides) -> dict:
    intraday = {
        "vwap": 99.0,
        "ema9": 98.0,
        "price_above_vwap": True,
        "price_above_ema9": True,
        "rsi": 62.0,
        "oi_setup": "LONG_BUILDUP",
        "pivot_r1_breakout": True,
        "rsi_pivot_break": True,
    }
    raw = {
        "symbol": "GOOD",
        "deterministicSide": "BUY",
        "riskAuditVerdict": "APPROVE",
        "passes_hard_filters": True,
        "passes_quality_filters": True,
        "ltp": 100.0,
        "entryPrice": 100.0,
        "stopLoss": 95.0,
        "target1": 107.5,
        "target2": 110.0,
        "intraday": intraday,
    }
    raw.update(overrides)
    return raw


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


def test_nse_sector_payload_normalization_accepts_nested_shapes():
    rows = sector_rotation.normalize_sector_payload(
        {"data": [{"indexName": "NIFTY IT", "percentChange": "1.25%", "lastPrice": "42,100"}]}
    )
    assert rows == [{"index": "NIFTY IT", "pChange": 1.25, "last": 42100.0}]


def test_nse_sector_payload_normalization_accepts_index_val():
    rows = sector_rotation.normalize_sector_payload(
        {"data": [{"index": "NIFTY METAL", "pChange": "0.86", "indexVal": "10,245.30"}]}
    )
    assert rows == [{"index": "NIFTY METAL", "pChange": 0.86, "last": 10245.3}]


def test_nse_sector_levels_fill_from_official_all_indices_without_estimation():
    sectors = [
        {"index": "NIFTY METAL", "pChange": 0.86, "last": None},
        {"index": "NIFTY BANK", "pChange": 0.46, "last": 55991.2},
        {"index": "NIFTY MEDIA", "pChange": -0.54, "last": None},
    ]
    levels = [
        {"index": "NIFTY METAL", "pChange": 0.86, "last": 10245.3},
        {"index": "NIFTY BANK", "pChange": 0.46, "last": 56001.1},
    ]
    merged = sector_rotation.merge_sector_levels(sectors, levels)
    assert merged[0]["last"] == 10245.3
    assert merged[1]["last"] == 55991.2
    assert merged[2]["last"] is None


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
