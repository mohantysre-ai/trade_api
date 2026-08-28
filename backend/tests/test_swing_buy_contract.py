from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import swing_session


def qualified_row(symbol: str = "VALID", **overrides) -> dict:
    intraday = {
        "vwap": 99.0,
        "ema9": 98.0,
        "price_above_vwap": True,
        "price_above_ema9": True,
        "rsi": 62.0,
        "oi_setup": "LONG_BUILDUP",
        "pivot_r1_breakout": True,
        "rsi_pivot_break": True,
        "atr_pct": 2.0,
        "turnover_cr": 80.0,
        "volume_multiplier": 1.8,
        "volume_pace_adjusted": True,
        "spread_pct": 0.05,
        "wick_noise_ratio": 0.20,
        "ema_angle_deg": 25.0,
        "promoter_holding_pct": 72.0,
    }
    intraday.update(overrides.pop("intraday", {}))
    row = {
        "ticker": symbol,
        "symbol": symbol,
        "deterministicSide": "BUY",
        "riskAuditVerdict": "APPROVE",
        "verdict": "APPROVE",
        "passes_hard_filters": True,
        "passes_quality_filters": True,
        "ltp": 100.0,
        "ltpRaw": 100.0,
        "entryPrice": 100.0,
        "stopLoss": 95.0,
        "target1": 107.5,
        "target2": 110.0,
        "score": 25.0,
        "volume": 1_000_000,
        "promoter_holding_pct": 72.0,
        "intraday": intraday,
    }
    row.update(overrides)
    return row


def rejection_reasons(row: dict) -> list[str]:
    eligible, _evidence, reasons = swing_session._evaluate_swing_buy_contract(row)
    assert eligible is False
    return reasons


def test_metrics_replay_sets_buy_when_hard_filters_compute():
    row = {
        "ticker": "REPLAY",
        "symbol": "REPLAY",
        "ltp": 120.0,
        "ltpRaw": 120.0,
        "riskAuditVerdict": "APPROVE",
        "verdict": "APPROVE",
        "passes_quality_filters": True,
        "intraday": {
            "atr_pct": 2.0,
            "turnover_cr": 80.0,
            "vwap": 118.0,
            "ema9": 117.0,
            "price_above_vwap": True,
            "price_above_ema9": True,
            "rsi": 62.0,
            "oi_setup": "LONG_BUILDUP",
            "volume_multiplier": 1.8,
            "spread_pct": 0.05,
            "wick_noise_ratio": 0.20,
            "pivot_r1_breakout": True,
            "rsi_pivot_break": True,
            "ema_angle_deg": 25.0,
            "promoter_holding_pct": 72.0,
            "passes_quality_filters": True,
        },
    }
    eligible, evidence, reasons = swing_session._evaluate_swing_buy_contract(row)
    assert evidence.get("deterministicSide") == "BUY"
    assert eligible is True
    assert reasons == []


def test_stale_snapshot_triggers_hunt_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(swing_session, "_read_json", lambda _p: {
        "selectionMeta": {"dataDate": "2026-08-03", "mode": "snapshot"},
        "isSnapshotFallback": True,
        "stocks": [{"ticker": "X"}],
    })
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")
    monkeypatch.setattr(swing_session, "_SWING_MATRIX_REFRESH_AT", 0.0)
    monkeypatch.setattr(
        swing_session,
        "_run_swing_matrix_refresh",
        lambda: calls.append("swing_entry_hunt") or {"success": True},
    )
    swing_session._ensure_today_matrix_snapshot()
    assert calls == ["swing_entry_hunt"]


def test_undersized_snapshot_triggers_nifty500_hunt_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(swing_session, "_read_json", lambda _p: {
        "selectionMeta": {"dataDate": "2026-08-13", "mode": "live"},
        "activePool": "Nifty 100",
        "universeSize": 189,
        "stockQuotes": {f"T{i}": {"ticker": f"T{i}"} for i in range(189)},
        "stocks": [{"ticker": "X", "deterministicSide": "BUY", "passes_hard_filters": True}],
    })
    monkeypatch.setattr(swing_session, "_ist_today", lambda: "2026-08-13")
    monkeypatch.setattr(swing_session, "_SWING_MATRIX_REFRESH_AT", 0.0)
    monkeypatch.setattr(
        swing_session,
        "_run_swing_matrix_refresh",
        lambda: calls.append("swing_entry_hunt") or {"success": True},
    )
    swing_session._ensure_today_matrix_snapshot()
    assert calls == ["swing_entry_hunt"]


def test_approve_without_explicit_buy_is_rejected():
    row = qualified_row()
    row.pop("deterministicSide")
    row["intraday"] = {"vwap": 99.0}
    reasons = rejection_reasons(row)
    assert "EXPLICIT_BUY_SIDE_REQUIRED:MISSING" in reasons


def test_high_score_without_explicit_buy_is_rejected():
    row = qualified_row(score=99.0)
    row.pop("deterministicSide")
    row["intraday"] = {"rsi": 62.0}
    assert swing_session._stock_is_matrix_buy(row) is False


def test_failed_hard_or_quality_filters_are_rejected():
    spread_fail = qualified_row(intraday={"spread_pct": 0.80})
    assert "HARD_FILTERS_NOT_PASSED" in rejection_reasons(spread_fail)
    promoter_fail = qualified_row(promoter_holding_pct=40.0)
    promoter_fail["intraday"]["promoter_holding_pct"] = 40.0
    assert "QUALITY_FILTERS_NOT_PASSED" in rejection_reasons(promoter_fail)


def test_bearish_side_oi_and_trend_anchors_are_rejected():
    assert "EXPLICIT_BUY_SIDE_REQUIRED:SELL" in rejection_reasons(
        qualified_row(deterministicSide="SELL")
    )
    assert "BULLISH_OI_REQUIRED:SHORT_BUILDUP" in rejection_reasons(
        qualified_row(intraday={"oi_setup": "SHORT_BUILDUP"})
    )
    assert "ABOVE_VWAP_REQUIREMENT_FAILED" in rejection_reasons(
        qualified_row(intraday={"price_above_vwap": False, "vwap": 101.0})
    )
    assert "ABOVE_EMA9_REQUIREMENT_FAILED" in rejection_reasons(
        qualified_row(intraday={"price_above_ema9": False, "ema9": 101.0})
    )


def test_risk_approval_is_only_a_veto_pass_not_direction():
    row = qualified_row(deterministicSide="SELL", riskAuditVerdict="APPROVE", verdict="APPROVE")
    assert swing_session._stock_is_matrix_buy(row) is False
    assert swing_session._stock_is_matrix_buy(
        qualified_row(riskAuditVerdict="HOLD_FOR_DATA", verdict="HOLD_FOR_DATA")
    ) is True
    assert any(reason.startswith("RISK_AUDIT_VETO") for reason in rejection_reasons(
        qualified_row(riskAuditVerdict="REJECT", verdict="REJECT")
    ))


def test_hunt_uses_volume_screen_beyond_display_50():
    display = []
    quotes: dict = {}
    for i in range(50):
        row = qualified_row(f"PAD{i}")
        row.pop("deterministicSide")
        row["passes_hard_filters"] = False
        row["passes_quality_filters"] = False
        row["intraday"] = {**row["intraday"], "rsi": 40.0, "price_above_vwap": False}
        row["ticker"] = f"PAD{i}"
        row["symbol"] = f"PAD{i}"
        display.append(row)
        quotes[row["ticker"]] = row
    overflow = qualified_row("OVERFLOW")
    quotes["OVERFLOW"] = overflow
    beyond = qualified_row("BEYOND200")
    beyond["intraday"] = {
        **overflow["intraday"],
        "hard_filter_reasons": ["not in intraday candidate set"],
    }
    quotes["BEYOND200"] = beyond
    outside = qualified_row("OUTSIDE500")
    outside["intraday"] = {
        **overflow["intraday"],
        "vwap": 0.0,
        "rsi": 0.0,
        "hard_filter_reasons": ["not in intraday candidate set"],
    }
    quotes["OUTSIDE500"] = outside
    snapshot = {
        "universeSize": 500,
        "volumeScreenedCount": 200,
        "stocks": display,
        "stockQuotes": quotes,
    }
    selected, source = swing_session._picks_from_asset_matrix(snapshot)
    assert {row["symbol"] for row in selected} == {"OVERFLOW", "BEYOND200"}
    assert source == "asset_matrix_deterministic_buy"
    diag = swing_session._swing_universe_diagnostics(snapshot=snapshot)
    assert diag["displayPool"] == 50
    assert diag["evaluated"] == 53
    assert diag["candleMetrics"] == 52
    assert diag["swingUniverse"] == "Nifty 500"
    assert diag["qualified"] == 2
    assert diag["universeSize"] == 500
    assert diag["volumeScreened"] == 200


def test_only_explicit_fully_qualified_buy_rows_enter_candidate_set():
    approve_only = qualified_row("APPROVE_ONLY")
    approve_only.pop("deterministicSide")
    approve_only["intraday"] = {"vwap": 99.0}
    high_score = qualified_row("HIGH_SCORE", score=99.0)
    high_score.pop("deterministicSide")
    high_score["intraday"] = {"rsi": 99.0}
    failed = qualified_row("FAILED", promoter_holding_pct=40.0)
    failed["intraday"]["promoter_holding_pct"] = 40.0
    sell = qualified_row("SELLER", deterministicSide="SELL")
    valid = qualified_row("VALID")
    snapshot = {
        "stocks": [approve_only, high_score, failed, sell, valid],
        "terminalIntelligence": {
            "ledger_stocks": [
                {"ticker": "APPROVE_ONLY", "score": 100, "action": "BUY"},
                {"ticker": "VALID", "score": 1, "action": "HOLD"},
            ]
        },
    }
    selected, source = swing_session._picks_from_asset_matrix(snapshot)
    assert [row["symbol"] for row in selected] == ["VALID"]
    assert source == "asset_matrix_deterministic_buy"


def test_invalid_locked_rows_are_scrubbed_but_audit_and_execution_are_preserved(monkeypatch):
    rhim = {
        "symbol": "RHIM",
        "direction": "LONG",
        "verdict": "APPROVE",
        "entryPrice": 398.1,
        "approxQty": 502,
        "deployedCapital": 199_846.2,
    }
    godrej = {
        "symbol": "GODREJCP",
        "direction": "LONG",
        "verdict": "APPROVE",
        "entryPrice": 927.2,
    }
    session = {
        "locked": True,
        "sessionDate": "2026-08-12",
        "long": [rhim, godrej],
        "short": [],
        "capital": {"swingCapital": 1_000_000},
    }
    monkeypatch.setattr(swing_session, "intraday_locked_symbols_respecting_swing", lambda _day: set())
    monkeypatch.setattr(swing_session, "is_swing_desk_eligible", lambda *_args: True)
    monkeypatch.setattr(
        swing_session,
        "_booked_execution_record",
        lambda _day, symbol: {
            "symbol": symbol,
            "sessionDate": "2026-08-12",
            "executionStatus": "TRIGGERED",
            "triggered": True,
            "realizedPnl": -6124.4,
            "source": "test_book",
        }
        if symbol == "RHIM"
        else None,
    )

    scrubbed, removed = swing_session._scrub_ineligible_swing_rows(session)

    assert removed == ["RHIM", "GODREJCP"]
    assert scrubbed["long"] == []
    assert scrubbed["counts"]["total"] == 0
    assert scrubbed["cashHeld"] is True
    audit = {row["symbol"]: row for row in scrubbed["excludedInvalidSelections"]}
    assert set(audit) == {"RHIM", "GODREJCP"}
    assert audit["RHIM"]["originalSelection"] == rhim
    assert audit["RHIM"]["preservedExecution"]["realizedPnl"] == -6124.4
    assert scrubbed["preservedExecutionHistory"][0]["symbol"] == "RHIM"


def test_concurrent_gets_cannot_alter_persisted_portfolio(monkeypatch, tmp_path: Path):
    path = tmp_path / "swing_session.json"
    payload = {
        "locked": True,
        "sessionDate": "2026-08-12",
        "long": [qualified_row()],
        "short": [],
        "counts": {"long": 1, "short": 0, "total": 1},
    }
    swing_session._atomic_write(str(path), payload)
    before = path.read_bytes()
    monkeypatch.setattr(swing_session, "_SWING_SESSION_PATH", str(path))

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: swing_session.get_swing_session(live=False), range(40)))

    assert path.read_bytes() == before
    assert all(result == payload for result in results)
    results[0]["long"][0]["symbol"] = "MUTATED"
    assert results[1]["long"][0]["symbol"] == "VALID"


def test_day_move_over_6pct_is_hard_rejected():
    row = qualified_row(delta="8.10 (+6.20%)")
    reasons = rejection_reasons(row)
    assert any(r.startswith("DAY_MOVE_OVER_MAX") for r in reasons)


def test_day_move_between_3_and_6pct_still_qualifies():
    row = qualified_row(delta="5.40 (+4.80%)")
    eligible, evidence, reasons = swing_session._evaluate_swing_buy_contract(row)
    assert eligible is True
    assert reasons == []
    assert evidence["dayChangePct"] == 4.8
    assert evidence["maxDayMovePct"] == 6.0


def test_locked_position_contains_complete_selection_evidence(monkeypatch):
    monkeypatch.setattr(swing_session, "is_swing_desk_eligible", lambda *_args: True)
    row = swing_session._normalize_swing_row(qualified_row(), "2026-08-12")
    assert row is not None
    evidence = row["selectionEvidence"]
    assert evidence["originalSide"] == "BUY"
    assert evidence["passesHardFilters"] is True
    assert evidence["passesQualityFilters"] is True
    assert evidence["vwap"] == 99.0
    assert evidence["ema9"] == 98.0
    assert evidence["rsi"] == 62.0
    assert evidence["oiSetup"] == "LONG_BUILDUP"
    assert evidence["riskAuditVerdict"] == "APPROVE"
    assert evidence["acceptanceReason"] == row["acceptanceReason"]
    assert evidence["lockedAt"]
    assert evidence["lockSource"]


def test_stale_false_flags_are_recomputed_from_metrics():
    row = qualified_row("FLUOROCHEM")
    row.pop("deterministicSide")
    row["passes_hard_filters"] = False
    row["passes_quality_filters"] = False
    row["intraday"] = {
        **row["intraday"],
        "passes_hard_filters": False,
        "passes_quality_filters": False,
        "ema_angle_deg": 12.5,
        "wick_noise_ratio": 0.54,
        "volume_multiplier": 1.15,
        "quality_filter_reasons": ["EMA angle below 45 degrees"],
    }
    eligible, evidence, reasons = swing_session._evaluate_swing_buy_contract(row)
    assert evidence.get("deterministicSide") == "BUY"
    assert eligible is True
    assert reasons == []


def test_cash_neutral_oi_qualifies_when_metrics_pass():
    row = qualified_row("NETWEB", intraday={"oi_setup": "NEUTRAL", "oi": 0, "prev_oi": 0})
    eligible, evidence, reasons = swing_session._evaluate_swing_buy_contract(row)
    assert eligible is True
    assert reasons == []
    assert evidence["oiSetup"] == "NEUTRAL"


def test_quote_universe_keeps_nifty500_names_on_nifty100_pool(monkeypatch):
    from app.services import angel_one_feed
    from app.utils.symbols import Instrument

    def inst(key: str) -> Instrument:
        return Instrument(key, "NSE", f"{key}-EQ", "1", key)

    display = [inst("RELIANCE"), inst("TCS")]
    swing = [inst("RELIANCE"), inst("NETWEB"), inst("SOLARINDS"), inst("SARDAEN")]

    def fake_pool(name, _client=None):
        if name == "Nifty 500":
            return swing, "Nifty 500"
        return display, "Nifty 100"

    monkeypatch.setattr(angel_one_feed, "_pool_watchlist", fake_pool)
    universe, label = angel_one_feed._quote_universe("Nifty 100")
    keys = {row.key for row in universe}
    assert label == "Nifty 100"
    assert keys == {"RELIANCE", "TCS", "NETWEB", "SOLARINDS", "SARDAEN"}


def test_dhan_long_without_matrix_buy_does_not_enter():
    scanner_flags = {
        "ticker": "SCANXLONG",
        "symbol": "SCANXLONG",
        "passes_hard_filters": True,
        "passes_quality_filters": True,
        "ltp": 100.0,
        "ltpRaw": 100.0,
        "intraday": {
            "vwap": 99.0,
            "ema9": 98.0,
            "price_above_vwap": True,
            "price_above_ema9": True,
            "rsi": 62.0,
            "oi_setup": "LONG_BUILDUP",
            "pivot_r1_breakout": True,
            "rsi_pivot_break": True,
            "passes_hard_filters": True,
            "passes_quality_filters": True,
        },
    }
    snapshot = {
        "stocks": [scanner_flags],
        "stockQuotes": {"SCANXLONG": scanner_flags},
        "dhanSwingPicks": {
            "source": "scannerPicks-persisted",
            "picks": [
                {
                    "symbol": "SCANXLONG",
                    "direction": "LONG",
                    "buyAbove": 101.0,
                    "stopLoss": 95.0,
                    "target1": 110.0,
                }
            ],
        },
    }
    selected, source = swing_session._picks_from_asset_matrix(snapshot)
    assert selected == []
    assert source == "asset_matrix_deterministic_buy"


def test_dhan_recommended_matrix_buy_enters_when_score_rank_would_miss_it():
    display = []
    quotes: dict = {}
    for i in range(50):
        row = qualified_row(f"PAD{i}")
        row.pop("deterministicSide")
        row["passes_hard_filters"] = False
        row["passes_quality_filters"] = False
        row["intraday"] = {**row["intraday"], "rsi": 40.0, "price_above_vwap": False}
        row["ticker"] = f"PAD{i}"
        row["symbol"] = f"PAD{i}"
        display.append(row)
        quotes[row["ticker"]] = row
    gated = qualified_row("DHANBUY", score=1.0)
    quotes["DHANBUY"] = gated
    snapshot = {
        "stocks": display,
        "stockQuotes": quotes,
        "dhanSwingPicks": {
            "picks": [
                {
                    "symbol": "DHANBUY",
                    "direction": "LONG",
                    "buyAbove": 999.0,
                    "stopLoss": 1.0,
                    "target1": 2000.0,
                }
            ],
        },
    }
    selected, source = swing_session._picks_from_asset_matrix(snapshot)
    assert [row["symbol"] for row in selected] == ["DHANBUY"]
    assert selected[0]["_candidateSource"] == "dhan_recommendation_gated"
    assert selected[0].get("buyAbove") != 999.0
    assert source == "asset_matrix_deterministic_buy"


def test_dhan_pick_missing_from_matrix_is_ignored():
    valid = qualified_row("VALID")
    snapshot = {
        "stocks": [valid],
        "stockQuotes": {"VALID": valid},
        "dhanSwingPicks": {
            "picks": [{"symbol": "STYLEBAAZA", "direction": "LONG", "buyAbove": 50.0}],
        },
    }
    selected, _source = swing_session._picks_from_asset_matrix(snapshot)
    assert [row["symbol"] for row in selected] == ["VALID"]
    assert selected[0]["_candidateSource"] == "asset_matrix_deterministic_buy"
