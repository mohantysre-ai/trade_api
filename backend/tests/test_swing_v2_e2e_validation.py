"""E2E Swing V2 immediate-lock / refill validation.

Covers:
- 15:10 decision freeze (not entry start)
- Immediate POSITION_LOCKED + FILL_COMPLETE within the same cycle
- Entry price immutability across mark updates
- Terminal exit frees slot immediately, no 300s wait for refill
- Runner behavior (partial T1 does NOT free slot)
- Hard max-5 cap, no forced trades
- Two-tier risk invariants
- Regime caps (NORMAL/DEFENSIVE/HALT)
- Coverage tier behavior
- Holiday/session clock
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.services.desk_clock import (
    rotation_window_allowed,
    swing_entry_hunt_allowed,
    basket_lock_allowed,
)
from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.engine import process_position_bar
from app.services.swing_v2.ledger import SwingLedger, materialize_position
from app.services.swing_v2.shadow import build_shadow_v2


IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def _ist(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 21, hour, minute, tzinfo=IST)


def _cfg(**overrides) -> SwingV2Config:
    return SwingV2Config(
        entry_cutoff_ist="23:59",
        decision_start_ist="09:45",
        decision_freeze_ist="15:10",
        order_expire_ist="15:20",
        mandatory_exit_ist="15:15",
        **overrides,
    )


# ============================================================
# 3. PROVE 15:10 IS A FREEZE, NOT AN ENTRY START
# ============================================================

class TestDecisionFreeze:
    def test_0944_swing_cannot_enter(self):
        assert swing_entry_hunt_allowed(_ist(9, 44)) == (False, "pre_lock")

    @pytest.mark.parametrize(
        "hour,minute",
        [(9, 45), (10, 5), (12, 0), (14, 44), (14, 59), (15, 9)],
    )
    def test_entry_hunt_open_before_freeze(self, hour, minute):
        ok, code = swing_entry_hunt_allowed(_ist(hour, minute))
        assert ok is True
        assert code == "entry_hunt"

    @pytest.mark.parametrize("hour,minute", [(15, 10), (15, 15), (15, 20)])
    def test_entry_hunt_closed_at_and_after_freeze(self, hour, minute):
        ok, code = swing_entry_hunt_allowed(_ist(hour, minute))
        assert ok is False
        assert code == "after_hunt"

    def test_rotation_window_closes_at_1445_not_1510(self):
        assert rotation_window_allowed(_ist(14, 44))[0] is True
        assert rotation_window_allowed(_ist(14, 46))[0] is False
        assert rotation_window_allowed(_ist(15, 9))[0] is False


# ============================================================
# 6. ENTRY PRICE IMMUTABILITY
# ============================================================

class TestEntryPriceImmutability:
    def test_entry_price_never_overwritten_by_marks(self, tmp_path: Path):
        db = str(tmp_path / "immut.sqlite3")
        ledger = SwingLedger(db)
        ledger.append(
            idempotency_key="dec-ep1:FILL_COMPLETE",
            decision_id="dec-ep1",
            position_id="pos-ep1",
            symbol="IMMUT1",
            session_date="2026-09-21",
            event_type="FILL_COMPLETE",
            event_timestamp="2026-09-21T10:05:00+05:30",
            payload={
                "symbol": "IMMUT1",
                "entryPrice": 100.0,
                "initialStop": 98.0,
                "effectiveStop": 98.0,
                "qty": 10,
                "remainingQty": 10,
                "entryTimestamp": "2026-09-21T10:05:00+05:30",
            },
        )

        marks = [100.20, 101.00, 102.50, 99.80]
        for idx, mark in enumerate(marks):
            updated = process_position_bar(
                ledger,
                "pos-ep1",
                {
                    "timestamp": f"2026-09-21T10:06:{idx:02d}+05:30",
                    "open": mark,
                    "high": mark,
                    "low": mark,
                    "close": mark,
                },
            )
            assert updated["entryPrice"] == 100.0
            assert updated["unrealizedPnl"] == round(10 * (mark - 100.0), 2)


# ============================================================
# 7. TARGET / STOP EXIT -> SLOT REFILL
# ============================================================

class TestTerminalExitRefill:
    def test_terminal_exit_frees_slot(self, tmp_path: Path):
        db = str(tmp_path / "refill.sqlite3")
        ledger = SwingLedger(db)

        for i in range(4):
            sym = f"POS{i:02d}"
            ledger.append(
                idempotency_key=f"dec-{sym}:FILL_COMPLETE",
                decision_id=f"dec-{sym}",
                position_id=f"pos-{sym}",
                symbol=sym,
                session_date="2026-09-21",
                event_type="FILL_COMPLETE",
                event_timestamp="2026-09-21T10:00:00+05:30",
                payload={
                    "symbol": sym,
                    "entryPrice": 100.0,
                    "initialStop": 98.0,
                    "effectiveStop": 98.0,
                    "t1": 105.0,
                    "t2": 110.0,
                    "qty": 10,
                    "remainingQty": 10,
                    "entryTimestamp": "2026-09-21T10:00:00+05:30",
                },
            )

        ledger.append(
            idempotency_key="dec-POS01:STOP_FILLED",
            decision_id="dec-POS01",
            position_id="pos-POS01",
            symbol="POS01",
            session_date="2026-09-21",
            event_type="STOP_FILLED",
            event_timestamp="2026-09-21T14:50:00+05:30",
            payload={
                "symbol": "POS01",
                "closed": True,
                "terminal": True,
                "status": "CLOSED_STOP",
                "remainingQty": 0,
                "exitReason": "STOP_LOSS_FILLED",
                "exitPrice": 98.0,
                "realizedPnl": -20.0,
                "unrealizedPnl": 0.0,
                "totalPnl": -20.0,
            },
        )

        positions = [materialize_position(ledger.events(position_id=f"pos-POS{i:02d}")) for i in range(4)]
        active = [p for p in positions if not p.get("terminal")]
        assert len(active) == 3

    def test_partial_t1_does_not_free_slot(self, tmp_path: Path):
        db = str(tmp_path / "runner.sqlite3")
        ledger = SwingLedger(db)
        ledger.append(
            idempotency_key="dec-RUN1:FILL_COMPLETE",
            decision_id="dec-RUN1",
            position_id="pos-RUN1",
            symbol="RUN1",
            session_date="2026-09-21",
            event_type="FILL_COMPLETE",
            event_timestamp="2026-09-21T10:00:00+05:30",
            payload={
                "symbol": "RUN1",
                "entryPrice": 100.0,
                "initialStop": 98.0,
                "effectiveStop": 98.0,
                "t1": 105.0,
                "t2": 110.0,
                "riskPerShare": 2.0,
                "t1Qty": 5,
                "trailArmR": 1.5,
                "trailLockR": 0.75,
                "qty": 10,
                "remainingQty": 10,
                "entryTimestamp": "2026-09-21T10:00:00+05:30",
            },
        )

        bar = {
            "timestamp": "2026-09-21T10:05:00+05:30",
            "open": 104.0,
            "high": 106.0,
            "low": 103.0,
            "close": 105.5,
        }
        updated = process_position_bar(ledger, "pos-RUN1", bar)
        assert updated["t1Filled"] is True
        assert updated["remainingQty"] == 5
        assert updated["terminal"] is False


# ============================================================
# 9. MAX-5 / NO-FORCED-TRADE
# ============================================================

class TestMaxPositionsNoForce:
    @pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 5])
    def test_selects_exactly_available_candidates(self, count):
        cfg = _cfg(max_positions=5, core_risk_bps=15)
        symbols = [f"SAFE{i:02d}" for i in range(count)]
        rows = [
            {
                "symbol": sym,
                "ticker": sym,
                "universeSegment": "NIFTY100",
                "sector": f"SEC{i}",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 1_000_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 70.0,
                "residualStrengthPctile": 70.0,
                "setupQualityPctile": 70.0,
                "rvolPctile": 70.0,
                "clvPctile": 70.0,
                "sectorStrengthPctile": 70.0,
                "liquidityPctile": 90.0,
                "upsideCapacityR": 1.45,
                "plannedMaxBlendedR": 1.45,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
            for i, sym in enumerate(symbols)
        ]
        correlations = {(a, b): 0.1 for i, a in enumerate(symbols) for b in symbols[i + 1:]}
        result = build_shadow_v2(
            rows,
            universe_coverage=1.0,
            regime="NORMAL",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            correlations=correlations,
            apply_coverage_hysteresis=False,
        )
        assert result["selectedCount"] == count

    def test_sixth_candidate_does_not_enter_when_full(self):
        cfg = _cfg(max_positions=5, core_risk_bps=15)

        def _row(sym: str, sector: str) -> dict:
            return {
                "symbol": sym,
                "ticker": sym,
                "universeSegment": "NIFTY100",
                "sector": sector,
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 1_000_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 72.0,
                "residualStrengthPctile": 72.0,
                "setupQualityPctile": 72.0,
                "rvolPctile": 70.0,
                "clvPctile": 72.0,
                "sectorStrengthPctile": 72.0,
                "liquidityPctile": 90.0,
                "upsideCapacityR": 1.45,
                "plannedMaxBlendedR": 1.45,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }

        symbols = [f"FULL{i:02d}" for i in range(6)]
        rows = [_row(sym, f"SEC{i}") for i, sym in enumerate(symbols)]
        correlations = {(a, b): 0.1 for i, a in enumerate(symbols) for b in symbols[i + 1:]}
        result = build_shadow_v2(
            rows,
            universe_coverage=1.0,
            regime="NORMAL",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            correlations=correlations,
            apply_coverage_hysteresis=False,
        )
        assert result["selectedCount"] == 5


# ============================================================
# 10. TWO-TIER RISK BEHAVIOR
# ============================================================

class TestTwoTierRisk:
    def test_tier_a_thresholds(self):
        cfg = _cfg(
            max_positions=5,
            setup_score_override=65.0,
            min_upside_capacity_r=1.25,
            min_planned_blended_r=1.25,
            min_expected_net_r=0.08,
        )
        row = {
            "symbol": "TIER_A",
            "ticker": "TIER_A",
            "universeSegment": "NIFTY100",
            "sector": "SEC1",
            "decisionPrice": 100.0,
            "structureStop": 98.5,
            "atr14": 1.5,
            "mdtv20": 1_000_000_000.0,
            "dailyObservationCount": 180,
            "modeledRoundTripCostPct": 0.05,
            "spreadPct": 0.05,
            "availableAskDepth": 1000,
            "dailyBarsThroughPreviousClose": True,
            "corporateEventsCurrent": True,
            "surveillanceCurrent": True,
            "universeCurrent": True,
            "sourceTimestamps": {
                "quote": datetime.now(UTC).isoformat(),
                "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            },
            "trendPriorPctile": 72.0,
            "residualStrengthPctile": 72.0,
            "setupQualityPctile": 72.0,
            "rvolPctile": 70.0,
            "clvPctile": 72.0,
            "sectorStrengthPctile": 72.0,
            "liquidityPctile": 90.0,
            "upsideCapacityR": 1.45,
            "plannedMaxBlendedR": 1.45,
            "costPenaltyR": 0.05,
            "gapRiskPenaltyR": 0.0,
            "extensionAtr": 1.0,
            "unexplainedGapPct": 0.0,
            "score": 68.0,
            "expectedNetR": 0.10,
            "expectedNetRStatus": "CALIBRATED",
        }
        result = build_shadow_v2(
            [row],
            universe_coverage=1.0,
            regime="NORMAL",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            apply_coverage_hysteresis=False,
        )
        assert result["selectedCount"] == 1
        assert result["candidates"][0]["qualificationMode"] == "SCORE_SOFT_PASS"
        assert result["candidates"][0]["riskMultiplier"] == 1.0

    def test_tier_b_thresholds_and_half_risk(self):
        cfg = _cfg(
            max_positions=5,
            setup_score_override=65.0,
            min_upside_capacity_r=1.25,
            min_planned_blended_r=1.25,
            min_expected_net_r=0.08,
        )
        row = {
            "symbol": "TIER_B",
            "ticker": "TIER_B",
            "universeSegment": "NIFTY100",
            "sector": "SEC1",
            "decisionPrice": 100.0,
            "structureStop": 98.5,
            "atr14": 1.5,
            "mdtv20": 1_000_000_000.0,
            "dailyObservationCount": 180,
            "modeledRoundTripCostPct": 0.05,
            "spreadPct": 0.05,
            "availableAskDepth": 1000,
            "dailyBarsThroughPreviousClose": True,
            "corporateEventsCurrent": True,
            "surveillanceCurrent": True,
            "universeCurrent": True,
            "sourceTimestamps": {
                "quote": datetime.now(UTC).isoformat(),
                "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            },
            "trendPriorPctile": 62.0,
            "residualStrengthPctile": 62.0,
            "setupQualityPctile": 62.0,
            "rvolPctile": 60.0,
            "clvPctile": 62.0,
            "sectorStrengthPctile": 62.0,
            "liquidityPctile": 80.0,
            "upsideCapacityR": 1.15,
            "plannedMaxBlendedR": 1.15,
            "costPenaltyR": 0.05,
            "gapRiskPenaltyR": 0.0,
            "extensionAtr": 1.0,
            "unexplainedGapPct": 0.0,
            "score": 62.0,
            "expectedNetR": 0.06,
            "expectedNetRStatus": "CALIBRATED",
        }
        result = build_shadow_v2(
            [row],
            universe_coverage=1.0,
            regime="NORMAL",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            apply_coverage_hysteresis=False,
        )
        assert result["selectedCount"] == 1
        assert result["candidates"][0]["qualificationMode"] == "DIVERSIFIED_SOFT_PASS"
        assert result["candidates"][0]["riskMultiplier"] == 0.50


# ============================================================
# 11. REGIME TESTS
# ============================================================

class TestRegimeCaps:
    def test_normal_allows_up_to_five(self):
        cfg = _cfg(max_positions=5, core_risk_bps=15)
        rows = [
            {
                "symbol": f"REG{i:02d}",
                "ticker": f"REG{i:02d}",
                "universeSegment": "NIFTY100",
                "sector": f"SEC{i}",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 1_000_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 72.0,
                "residualStrengthPctile": 72.0,
                "setupQualityPctile": 72.0,
                "rvolPctile": 70.0,
                "clvPctile": 72.0,
                "sectorStrengthPctile": 72.0,
                "liquidityPctile": 90.0,
                "upsideCapacityR": 1.45,
                "plannedMaxBlendedR": 1.45,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
            for i in range(5)
        ]
        correlations = {(a, b): 0.1 for i, a in enumerate([r["symbol"] for r in rows]) for b in [r2["symbol"] for r2 in rows[i + 1:]]}
        result = build_shadow_v2(
            rows,
            universe_coverage=1.0,
            regime="NORMAL",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            correlations=correlations,
            apply_coverage_hysteresis=False,
        )
        assert result["selectedCount"] == 5

    def test_defensive_caps_at_two(self):
        cfg = _cfg(max_positions=5, core_risk_bps=15)
        rows = [
            {
                "symbol": f"DEF{i:02d}",
                "ticker": f"DEF{i:02d}",
                "universeSegment": "NIFTY100",
                "sector": f"SEC{i}",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 1_000_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 72.0,
                "residualStrengthPctile": 72.0,
                "setupQualityPctile": 72.0,
                "rvolPctile": 70.0,
                "clvPctile": 72.0,
                "sectorStrengthPctile": 72.0,
                "liquidityPctile": 90.0,
                "upsideCapacityR": 1.45,
                "plannedMaxBlendedR": 1.45,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
            for i in range(5)
        ]
        correlations = {(a, b): 0.1 for i, a in enumerate([r["symbol"] for r in rows]) for b in [r2["symbol"] for r2 in rows[i + 1:]]}
        result = build_shadow_v2(
            rows,
            universe_coverage=1.0,
            regime="DEFENSIVE",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            correlations=correlations,
            apply_coverage_hysteresis=False,
        )
        assert result["selectedCount"] <= 2

    def test_halt_new_longs_selects_zero(self):
        cfg = _cfg(max_positions=5, core_risk_bps=15)
        rows = [
            {
                "symbol": "HALT01",
                "ticker": "HALT01",
                "universeSegment": "NIFTY100",
                "sector": "SEC1",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 1_000_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 72.0,
                "residualStrengthPctile": 72.0,
                "setupQualityPctile": 72.0,
                "rvolPctile": 70.0,
                "clvPctile": 72.0,
                "sectorStrengthPctile": 72.0,
                "liquidityPctile": 90.0,
                "upsideCapacityR": 1.45,
                "plannedMaxBlendedR": 1.45,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
        ]
        result = build_shadow_v2(
            rows,
            universe_coverage=1.0,
            regime="HALT_NEW_LONGS",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            apply_coverage_hysteresis=False,
        )
        assert result["blocked"] is True
        assert result.get("selectedCount", 0) == 0


# ============================================================
# 12. COVERAGE TESTS
# ============================================================

class TestCoverageTiers:
    def test_98pct_coverage_allows_five_with_reduced_risk(self):
        cfg = _cfg(
            max_positions=5,
            nav=1_000_000.0,
            core_risk_bps=15,
            coverage_normal_threshold=0.99,
            coverage_degraded_threshold=0.95,
            coverage_defensive_threshold=0.90,
            coverage_normal_risk_multiplier=1.00,
            coverage_degraded_risk_multiplier=0.75,
            coverage_defensive_risk_multiplier=0.50,
        )
        symbols = [f"COV{i:02d}" for i in range(5)]
        rows = [
            {
                "symbol": sym,
                "ticker": sym,
                "universeSegment": "NIFTY100",
                "sector": f"SEC{i}",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 1_000_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 72.0,
                "residualStrengthPctile": 72.0,
                "setupQualityPctile": 72.0,
                "rvolPctile": 70.0,
                "clvPctile": 72.0,
                "sectorStrengthPctile": 72.0,
                "liquidityPctile": 90.0,
                "upsideCapacityR": 1.45,
                "plannedMaxBlendedR": 1.45,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
            for i, sym in enumerate(symbols)
        ]
        noise_fresh = [
            {
                "symbol": f"NOISE{i:03d}",
                "ticker": f"NOISE{i:03d}",
                "universeSegment": "NIFTY100",
                "sector": "NOISESEC",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 500_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 30.0,
                "residualStrengthPctile": 30.0,
                "setupQualityPctile": 30.0,
                "rvolPctile": 30.0,
                "clvPctile": 30.0,
                "sectorStrengthPctile": 30.0,
                "liquidityPctile": 30.0,
                "upsideCapacityR": 0.80,
                "plannedMaxBlendedR": 0.80,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
            for i in range(93)
        ]
        noise_stale = [
            {
                "symbol": f"STALE{i:03d}",
                "ticker": f"STALE{i:03d}",
                "universeSegment": "NIFTY100",
                "sector": "STALESEC",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 500_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
                },
                "trendPriorPctile": 30.0,
                "residualStrengthPctile": 30.0,
                "setupQualityPctile": 30.0,
                "rvolPctile": 30.0,
                "clvPctile": 30.0,
                "sectorStrengthPctile": 30.0,
                "liquidityPctile": 30.0,
                "upsideCapacityR": 0.80,
                "plannedMaxBlendedR": 0.80,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
            for i in range(2)
        ]
        all_rows = rows + noise_fresh + noise_stale
        correlations = {(a, b): 0.1 for i, a in enumerate(symbols) for b in symbols[i + 1:]}
        result = build_shadow_v2(
            all_rows,
            universe_coverage=0.98,
            regime="NORMAL",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            correlations=correlations,
            apply_coverage_hysteresis=False,
        )
        assert result["coverageTier"] == "DEGRADED"
        assert result["coverageRiskMultiplier"] == 0.75
        assert result["selectedCount"] == 5

    def test_below_90pct_coverage_blocks(self):
        cfg = _cfg(max_positions=5, core_risk_bps=15)
        rows = [
            {
                "symbol": "BLOCK01",
                "ticker": "BLOCK01",
                "universeSegment": "NIFTY100",
                "sector": "SEC1",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 1_000_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": datetime.now(UTC).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                },
                "trendPriorPctile": 72.0,
                "residualStrengthPctile": 72.0,
                "setupQualityPctile": 72.0,
                "rvolPctile": 70.0,
                "clvPctile": 72.0,
                "sectorStrengthPctile": 72.0,
                "liquidityPctile": 90.0,
                "upsideCapacityR": 1.45,
                "plannedMaxBlendedR": 1.45,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
        ] + [
            {
                "symbol": f"STALE{i:03d}",
                "ticker": f"STALE{i:03d}",
                "universeSegment": "NIFTY100",
                "sector": "SEC1",
                "decisionPrice": 100.0,
                "structureStop": 98.5,
                "atr14": 1.5,
                "mdtv20": 500_000_000.0,
                "dailyObservationCount": 180,
                "modeledRoundTripCostPct": 0.05,
                "spreadPct": 0.05,
                "availableAskDepth": 1000,
                "dailyBarsThroughPreviousClose": True,
                "corporateEventsCurrent": True,
                "surveillanceCurrent": True,
                "universeCurrent": True,
                "sourceTimestamps": {
                    "quote": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                    "bars1h": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
                },
                "trendPriorPctile": 30.0,
                "residualStrengthPctile": 30.0,
                "setupQualityPctile": 30.0,
                "rvolPctile": 30.0,
                "clvPctile": 30.0,
                "sectorStrengthPctile": 30.0,
                "liquidityPctile": 30.0,
                "upsideCapacityR": 0.80,
                "plannedMaxBlendedR": 0.80,
                "costPenaltyR": 0.05,
                "gapRiskPenaltyR": 0.0,
                "extensionAtr": 1.0,
                "unexplainedGapPct": 0.0,
            }
            for i in range(9)
        ]
        result = build_shadow_v2(
            rows,
            universe_coverage=0.10,
            regime="NORMAL",
            final_lock=True,
            now=datetime.now(IST),
            config=cfg,
            apply_coverage_hysteresis=False,
        )
        assert result["blocked"] is True
        assert result.get("selectedCount", 0) == 0


# ============================================================
# 14. HOLIDAY / SESSION CLOCK
# ============================================================

class TestSessionClock:
    def test_nse_holiday_blocks_lock(self):
        assert basket_lock_allowed(datetime(2026, 10, 2, 10, 0, tzinfo=IST))[0] is False

    def test_swing_hunt_opens_at_0945(self):
        assert swing_entry_hunt_allowed(_ist(9, 44)) == (False, "pre_lock")
        assert swing_entry_hunt_allowed(_ist(9, 45))[0] is True

    def test_swing_hunt_continues_until_1510(self):
        assert swing_entry_hunt_allowed(_ist(14, 45))[0] is True
        assert swing_entry_hunt_allowed(_ist(15, 9))[0] is True
        assert swing_entry_hunt_allowed(_ist(15, 10))[0] is False

    def test_1445_intraday_cutoff_does_not_stop_swing(self):
        assert rotation_window_allowed(_ist(14, 46))[0] is False
        assert swing_entry_hunt_allowed(_ist(14, 46))[0] is True
