from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.swing_v2.calendar import next_session, session_age, time_exit_due
from app.services.swing_v2.calibration import shrunk_expectancy
from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.data_quality import evaluate_freshness
from app.services.swing_v2.execution import simulate_paper_fill
from app.services.swing_v2.engine import execute_paper_order, process_position_bar
from app.services.swing_v2.features import momentum_prior_raw, oi_treatment
from app.services.swing_v2.facade import attach_shadow_v2
from app.services.swing_v2.ledger import (
    IdempotencyConflict,
    SwingLedger,
    TerminalStateConflict,
    materialize_position,
)
from app.services.swing_v2.lifecycle import evaluate_position, thesis_break, update_stop
from app.services.swing_v2.portfolio import construct_portfolio
from app.services.swing_v2.ranking import rank_score
from app.services.swing_v2.regime import classify_regime
from app.services.swing_v2.schemas import EventType
from app.services.swing_v2.setups import evaluate_setups
from app.services.swing_v2.shadow import build_shadow_v2
from app.services.swing_v2.tradability import evaluate_tradability
from app.services.swing_v2.universe import angel_resolution_coverage, refresh_official_membership
from app.services.swing_v2.validation import research_to_shadow_gates, shadow_to_paper_gates, walk_forward_windows


NOW = datetime(2026, 9, 8, 9, 40, tzinfo=timezone.utc)  # 15:10 IST


def candidate(symbol: str = "ALPHA", sector: str = "IT") -> dict:
    stamp = NOW.isoformat()
    return {
        "symbol": symbol,
        "sector": sector,
        "universeSegment": "NIFTY_MIDCAP150",
        "decisionPrice": 105.0,
        "prior20dHigh": 104.0,
        "trendPriorPctile": 80.0,
        "residualStrengthPctile": 80.0,
        "setupQualityPctile": 80.0,
        "rvolPctile": 80.0,
        "clvPctile": 90.0,
        "sectorStrengthPctile": 70.0,
        "liquidityPctile": 90.0,
        "clv": .90,
        "rvolPaced": 1.8,
        "breakoutDistanceAtr": .4,
        "extensionAtr": 1.2,
        "upsideCapacityR": 2.0,
        "plannedMaxBlendedR": 1.5,
        "expectedNetR": None,
        "expectedNetRStatus": "UNRATED",
        "atr14": 2.0,
        "structureStop": 103.4,
        "mdtv20": 4_000_000_000.0,
        "modeledRoundTripCostPct": .20,
        "spreadPct": .05,
        "availableAskDepth": 10_000,
        "dailyObservationCount": 300,
        "dailyBarsThroughPreviousClose": True,
        "corporateEventsCurrent": True,
        "surveillanceCurrent": True,
        "universeCurrent": True,
        "sourceTimestamps": {"quote": stamp, "depth": stamp, "bars5m": stamp},
    }


def cfg(**changes) -> SwingV2Config:
    values = {**SwingV2Config().__dict__, "enabled": True}
    values.update(changes)
    value = SwingV2Config(**values)
    value.validate()
    return value


def test_config_fails_closed_for_live_or_excess_risk():
    with pytest.raises(ValueError, match="LIVE_PROMOTION"):
        SwingV2Config(live_promotion=True).validate()
    with pytest.raises(ValueError, match="initial-risk"):
        SwingV2Config(max_portfolio_risk_bps=101).validate()


def test_freshness_contract_scan_and_final_lock():
    row = candidate()
    old = (NOW - timedelta(seconds=20)).isoformat()
    row["sourceTimestamps"] = {"quote": old, "depth": old, "bars5m": old}
    assert evaluate_freshness(row, final_lock=False, now=NOW)[0] is True
    ok, reasons = evaluate_freshness(row, final_lock=True, now=NOW)
    assert ok is False
    assert {"STALE_QUOTE", "STALE_DEPTH"} <= set(reasons)


def test_missing_spread_or_depth_fails_closed():
    row = candidate()
    row["spreadPct"] = None
    ok, reasons = evaluate_tradability(row)
    assert ok is False
    assert "MISSING_SPREAD_OR_DEPTH" in reasons


def test_cash_only_oi_is_not_applicable_and_promoter_holding_is_irrelevant():
    assert oi_treatment(is_fno=False, current_oi=None, previous_oi=None)["oiStatus"] == "NOT_APPLICABLE"
    low = candidate()
    low["promoter_holding_pct"] = 1.0
    high = {**low, "promoter_holding_pct": 99.0}
    assert evaluate_setups(low)["eligible"] == evaluate_setups(high)["eligible"] is True


def test_momentum_prior_skips_last_five_sessions():
    closes = [100 + i for i in range(260)]
    baseline = momentum_prior_raw(closes)
    closes[-5:] = [10_000] * 5
    assert momentum_prior_raw(closes) == baseline


def test_rank_requires_every_factor_and_applies_exhaustion_penalty():
    row = candidate()
    rated = rank_score(row)
    assert rated["status"] == "RATED"
    exhausted = rank_score({**row, "extensionAtr": 2.1})
    assert exhausted["score"] == rated["score"] - 10
    assert rank_score({**row, "rvolPctile": None})["status"] == "UNRATED"


def test_champion_setups_are_independent_and_catalyst_stays_shadow():
    row = candidate()
    result = evaluate_setups(row)
    assert result["passedSetupIds"] == ["BREAKOUT_CLOSE_V1"]
    catalyst = {
        **row,
        "structuredAnnouncementId": "NSE-1",
        "announcementKnownBeforeDecision": True,
        "gapPct": 2.0,
        "gapFillPct": 20.0,
        "decisionAboveVwap": True,
        "rvolPaced": 2.2,
    }
    result = evaluate_setups(catalyst)
    assert "CATALYST_GAP_HOLD_V1" in result["shadowSetupIds"]
    assert "CATALYST_GAP_HOLD_V1" not in result["passedSetupIds"]


def test_uncalibrated_candidate_can_collect_shadow_fill_but_not_promote():
    result = build_shadow_v2([candidate()], universe_coverage=1.0, regime="NORMAL", now=NOW, config=cfg())
    assert result["selectedCount"] == 1
    assert result["candidates"][0]["promotionEligible"] is False
    assert result["validationState"] == "RESEARCH_HYPOTHESIS"
    assert result["authoritative"] is False
    assert result["liveCapitalApproved"] is False


def test_low_coverage_and_unrated_regime_fail_closed():
    assert build_shadow_v2([candidate()], universe_coverage=.989, regime="NORMAL", now=NOW, config=cfg())["blockReason"] == "UNIVERSE_COVERAGE_BELOW_99PCT"
    assert build_shadow_v2([candidate()], universe_coverage=1, regime="REGIME_UNRATED", now=NOW, config=cfg())["blockReason"] == "REGIME_UNRATED"


def test_regime_uses_four_transparent_stress_points():
    normal = classify_regime({"nifty500Close": 101, "nifty500Ema20": 100, "breadthAboveEma20Pct": 60, "nifty500Return5dPct": 1, "vixPercentile": 40, "vixChange1dPct": 1})
    defensive = classify_regime({"nifty500Close": 99, "nifty500Ema20": 100, "breadthAboveEma20Pct": 39, "nifty500Return5dPct": 1, "vixPercentile": 40, "vixChange1dPct": 1})
    halt = classify_regime({"nifty500Close": 99, "nifty500Ema20": 100, "breadthAboveEma20Pct": 39, "nifty500Return5dPct": -3, "vixPercentile": 40, "vixChange1dPct": 1})
    assert (normal["state"], defensive["state"], halt["state"]) == ("NORMAL", "DEFENSIVE", "HALT_NEW_LONGS")
    assert classify_regime({})["state"] == "REGIME_UNRATED"


def test_defensive_regime_caps_positions_and_halves_new_risk():
    rows = [candidate(f"S{i}", f"SEC{i}") for i in range(4)]
    correlations = {(f"S{i}", f"S{j}"): .2 for i in range(4) for j in range(4) if i != j}
    result = build_shadow_v2(rows, universe_coverage=1, regime="DEFENSIVE", now=NOW, config=cfg(), correlations=correlations)
    assert result["selectedCount"] == 2
    assert result["riskScale"] == .5
    assert all(row["initialRiskRupees"] <= 1_250.01 for row in result["candidates"])


def test_portfolio_caps_sector_correlation_cross_book_and_total_risk():
    rows = [candidate("A", "IT"), candidate("B", "IT"), candidate("C", "IT"), candidate("D", "BANK")]
    for index, row in enumerate(rows):
        row["expectedNetR"] = .4 - index * .01
    correlations = {("B", "A"): .8}
    out = construct_portfolio(rows, cfg(), correlations=correlations, occupied_symbols={"D"})
    reasons = {row["symbol"]: row["portfolioRejectReason"] for row in out["rejected"]}
    assert reasons["B"] == "EXCESS_PORTFOLIO_CORRELATION"
    assert reasons["D"] == "CROSS_BOOK_CONFLICT"
    assert out["portfolioInitialRisk"] <= 10_000
    assert all(row["deployedCapital"] <= 200_000 for row in out["selected"])


def test_only_one_microcap_satellite_can_enter():
    rows = [candidate("M1", "A"), candidate("M2", "B")]
    for row in rows:
        row["universeSegment"] = "NIFTY_MICROCAP250"
        row["mdtv20"] = 2_000_000_000
    out = construct_portfolio(rows, cfg(), correlations={("M1", "M2"): .2})
    assert len(out["selected"]) == 1
    assert out["rejected"][0]["portfolioRejectReason"] == "MAX_ONE_MICROCAP_SATELLITE"


def test_paper_fill_requires_post_decision_executable_observation():
    order = {"decisionTimestamp": NOW.isoformat(), "limitPrice": 101.0, "qty": 10}
    before = {"timestamp": (NOW - timedelta(seconds=1)).isoformat(), "ask": 100, "askDepth": 100}
    after = {"timestamp": (NOW + timedelta(seconds=1)).isoformat(), "ask": 100.5, "askDepth": 6}
    expiry = NOW + timedelta(minutes=10)
    result = simulate_paper_fill(order, [before, after], expiry=expiry)
    assert result["executionStatus"] == "PARTIAL_FILL"
    assert result["filledQty"] == 6
    expired = simulate_paper_fill(order, [before], expiry=expiry)
    assert expired["executionStatus"] == "EXPIRED_UNFILLED"
    assert expired["realizedPnl"] == 0


def test_lifecycle_t1_trail_t2_and_stop_never_loosen():
    pos = {"entryPrice": 100, "entryTimestamp": NOW.isoformat(), "initialStop": 98, "effectiveStop": 98, "riskPerShare": 2, "t1": 102, "t2": 104, "qty": 10, "remainingQty": 10, "t1Qty": 5}
    t1 = evaluate_position(pos, {"timestamp": (NOW + timedelta(minutes=1)).isoformat(), "open": 100, "low": 99, "high": 102.1, "close": 101})
    assert t1["remainingQty"] == 5 and t1["effectiveStop"] == 100
    trail = evaluate_position(t1, {"timestamp": (NOW + timedelta(minutes=2)).isoformat(), "open": 101, "low": 100.5, "high": 103.1, "close": 103})
    assert trail["trailArmed"] is True and trail["effectiveStop"] == 101.5
    assert update_stop(trail, 100)["effectiveStop"] == 101.5
    t2 = evaluate_position(trail, {"timestamp": (NOW + timedelta(minutes=3)).isoformat(), "open": 103, "low": 102, "high": 104.1, "close": 104})
    assert t2["exitReason"] == "T2_FILLED" and t2["remainingQty"] == 0


def test_gap_through_stop_uses_first_executable_price_and_costs_net_pnl():
    pos = {"entryPrice": 100, "initialStop": 98, "effectiveStop": 98, "riskPerShare": 2, "qty": 10, "remainingQty": 10, "roundTripCostPerShare": .1}
    out = evaluate_position(pos, {"open": 95, "low": 94, "high": 96, "close": 95})
    assert out["exitPrice"] == 95
    assert out["realizedPnl"] == -51


def test_d2_time_exit_can_be_small_gain_or_loss_and_holiday_is_skipped():
    holiday = date(2026, 9, 9)
    assert next_session(date(2026, 9, 8), {holiday}) == date(2026, 9, 10)
    assert session_age(date(2026, 9, 8), date(2026, 9, 11), {holiday}) == 2
    ist = ZoneInfo("Asia/Kolkata")
    assert time_exit_due(datetime(2026, 9, 11, 15, 15, tzinfo=ist), 2)
    base = {"entryPrice": 100, "initialStop": 98, "effectiveStop": 98, "riskPerShare": 2, "qty": 10, "remainingQty": 10}
    assert evaluate_position(base, {"open": 100, "low": 99, "high": 101, "close": 100.1}, is_d2_exit=True)["exitReason"] == "TIME_EXIT_FILLED"
    assert evaluate_position(base, {"open": 100, "low": 98.5, "high": 100, "close": 99.9}, is_d2_exit=True)["realizedPnl"] == -1


def test_thesis_break_requires_two_closes_and_weak_residual():
    bars = [{"close": 99}, {"close": 98}]
    assert thesis_break(bars, vwap=100, locked_level=100, residual_percentile=29)
    assert not thesis_break(bars, vwap=100, locked_level=100, residual_percentile=30)


def test_ledger_is_idempotent_terminal_and_reconciled(tmp_path):
    ledger = SwingLedger(str(tmp_path / "events.sqlite3"))
    args = dict(idempotency_key="d1:lock", decision_id="d1", position_id="d1", symbol="ABC", session_date="2026-09-08", event_type=EventType.POSITION_LOCKED, event_timestamp=NOW.isoformat(), payload={"qty": 10, "remainingQty": 10})
    first = ledger.append(**args)
    assert ledger.append(**args)["eventId"] == first["eventId"]
    with pytest.raises(IdempotencyConflict):
        ledger.append(**{**args, "payload": {"qty": 11}})
    ledger.append(idempotency_key="d1:time", decision_id="d1", position_id="d1", symbol="ABC", session_date="2026-09-08", event_type=EventType.TIME_EXIT_FILLED, event_timestamp=(NOW + timedelta(days=2)).isoformat(), payload={"remainingQty": 0, "realizedPnl": 10, "unrealizedPnl": 0, "totalPnl": 10})
    with pytest.raises(TerminalStateConflict):
        ledger.append(idempotency_key="d1:reopen", decision_id="d1", position_id="d1", symbol="ABC", session_date="2026-09-08", event_type=EventType.FILL_COMPLETE, event_timestamp=(NOW + timedelta(days=2, minutes=1)).isoformat(), payload={"remainingQty": 10})
    state = materialize_position(ledger.events(position_id="d1"))
    assert state["terminal"] is True and state["remainingQty"] == 0


def test_integrated_paper_order_and_chronological_ledger_lifecycle(tmp_path):
    ledger = SwingLedger(str(tmp_path / "engine.sqlite3"))
    order = {
        **candidate(),
        "decisionId": "paper-1",
        "sessionDate": "2026-09-08",
        "decisionTimestamp": NOW.isoformat(),
        "limitPrice": 105.2,
        "qty": 10,
        "initialStop": 103.0,
    }
    fill = execute_paper_order(
        ledger,
        order,
        [{"timestamp": (NOW + timedelta(seconds=1)).isoformat(), "ask": 105.1, "askDepth": 10, "source": "ANGEL_ONE"}],
        expiry=NOW + timedelta(minutes=10),
    )
    assert fill["eventType"] == "FILL_COMPLETE"
    t1_price = fill["payload"]["t1"]
    t1 = process_position_bar(ledger, "paper-1", {"timestamp": (NOW + timedelta(minutes=1)).isoformat(), "open": 105.1, "low": 104, "high": t1_price + .01, "close": t1_price})
    assert t1["t1Filled"] is True and t1["remainingQty"] == 5
    time_exit = process_position_bar(ledger, "paper-1", {"timestamp": (NOW + timedelta(days=2)).isoformat(), "open": 106, "low": 105.3, "high": 106, "close": 105.5}, is_d2_exit=True)
    assert time_exit["lastEventType"] == "TIME_EXIT_FILLED"
    assert time_exit["terminal"] is True


def test_calibration_requires_100_bucket_fills():
    small = shrunk_expectancy([.2] * 99, [.1] * 200)
    large = shrunk_expectancy([.2] * 100, [.1] * 200)
    assert small["expectedNetRStatus"] == "SHRUNK_INSUFFICIENT_SAMPLES"
    assert large["expectedNetRStatus"] == "CALIBRATED"


def test_promotion_gates_are_all_or_nothing_and_walk_forward_is_frozen():
    research = {
        "oosFills": 300, "fillsByChampionSetup": {"BREAKOUT_CLOSE_V1": 150, "PULLBACK_RECLAIM_V1": 150},
        "meanNetR": .12, "profitFactor": 1.25, "bootstrapLowerBoundR": .01,
        "positiveRollingWindowsPct": 70, "finalHoldoutNetReturn": .01,
        "twiceCostProfitFactor": 1.05, "maxProfitContributionPct": 50,
        "maxDrawdownPct": -8, "unresolvedLeakage": False,
    }
    assert research_to_shadow_gates(research)["passed"] is True
    assert research_to_shadow_gates({**research, "oosFills": 299})["passed"] is False
    paper = {"paperSessions": 60, "paperFills": 40, "falseFills": 0, "observedNetR": .01, "p75SlippageMultiple": 1.5, "duplicateEvents": 0, "staleLocks": 0, "eodLedgerMismatchRupees": 1, "insideBacktestConfidenceBand": True}
    assert shadow_to_paper_gates(paper)["passed"] is True
    windows = walk_forward_windows(date(2020, 1, 1), date(2025, 1, 1))
    assert windows[0]["trainEndExclusive"] == date(2023, 1, 1)
    assert windows[0]["validationEndExclusive"] == date(2023, 7, 1)


def test_llm_fields_cannot_change_decision_or_event_hash():
    base = candidate()
    a = build_shadow_v2([{**base, "llmVerdict": "APPROVE"}], universe_coverage=1, regime="NORMAL", now=NOW, config=cfg())
    b = build_shadow_v2([{**base, "llmVerdict": "REJECT", "llmError": "HTTP 410"}], universe_coverage=1, regime="NORMAL", now=NOW, config=cfg())
    comparable = ("symbol", "score", "qty", "entryPrice", "initialStop", "t1", "t2")
    assert {key: a["candidates"][0][key] for key in comparable} == {key: b["candidates"][0][key] for key in comparable}


def test_compatibility_facade_is_invisible_when_disabled_and_versioned_when_enabled(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"universeSize": 0, "stocks": []}', encoding="utf-8")
    session = {"locked": False, "long": [], "short": []}
    monkeypatch.setenv("SWING_V2_ENABLED", "false")
    assert attach_shadow_v2(session, str(snapshot)) == session
    monkeypatch.setenv("SWING_V2_ENABLED", "true")
    attached = attach_shadow_v2(session, str(snapshot))
    assert attached["shadowV2"]["strategyId"] == "SWING_2S_MOMENTUM_V2"
    assert attached["shadowV2"]["blockReason"] == "UNIVERSE_COVERAGE_BELOW_99PCT"


def test_official_750_universe_is_exact_date_stamped_and_angel_coverage_is_explicit(tmp_path):
    counts = {"nifty100": ("L", 100), "midcap150": ("M", 150), "smallcap250": ("S", 250), "microcap250": ("X", 250)}

    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    def fetcher(url, timeout):
        prefix, count = next(value for key, value in counts.items() if key in url.replace("_", "").lower())
        body = "Company Name,Industry,Symbol\n" + "\n".join(f"{prefix}{i},TEST,{prefix}{i}" for i in range(count))
        return Response(body)

    payload = refresh_official_membership(str(tmp_path), effective_date=date(2026, 9, 8), fetcher=fetcher)
    assert payload["constituentCount"] == 750
    assert (tmp_path / "2026-09-08.json").exists()
    master = [{"symbol": f"L{i}-EQ", "token": str(i)} for i in range(99)]
    resolved = angel_resolution_coverage(payload["constituents"], master)
    assert resolved["expected"] == 750
    assert resolved["resolved"] == 99
    assert resolved["coverage"] == 99 / 750
