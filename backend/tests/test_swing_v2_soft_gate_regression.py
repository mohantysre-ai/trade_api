"""Regression coverage for the softened Swing V2 opportunity gate.

The fixture mirrors the 2026-09-21 observed shape: 750 universe names, 735 with
fresh usable data (98% coverage), and a small set of momentum-like names.  It
does not pretend to replay unavailable broker ticks; it protects the production
gate semantics that today's incident exposed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.shadow import build_shadow_v2

IST = ZoneInfo("Asia/Kolkata")


def _row(i: int, now: datetime, *, fresh: bool, soft_candidate: bool = False) -> dict:
    quote_ts = now.astimezone(timezone.utc)
    bar_ts = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc) if fresh else datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)
    score = 66.0 if soft_candidate else 40.0
    return {
        "symbol": f"T{i:03d}",
        "ticker": f"T{i:03d}",
        "universeSegment": "NIFTY100",
        "sector": f"SEC{i % 20}",
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
            "quote": quote_ts.isoformat() if fresh else (quote_ts - timedelta(hours=2)).isoformat(),
            "bars1h": bar_ts.isoformat(),
        },
        "trendPriorPctile": score,
        "residualStrengthPctile": score,
        "setupQualityPctile": score,
        "rvolPctile": score,
        "clvPctile": score,
        "sectorStrengthPctile": score,
        "liquidityPctile": score,
        "upsideCapacityR": 1.30 if soft_candidate else 0.50,
        "plannedMaxBlendedR": 1.30 if soft_candidate else 0.50,
        "costPenaltyR": 0.05,
        "gapRiskPenaltyR": 0.0,
        "extensionAtr": 1.0,
        "unexplainedGapPct": 0.0,
    }


def test_20260921_like_98pct_coverage_allows_borderline_safe_candidate_to_lock():
    now = datetime(2026, 9, 21, 10, 30, tzinfo=IST)
    rows = []
    # 735 fresh names out of 750.  The first 42 represent the observed
    # scanner-long cohort; one is deliberately a 66-score borderline candidate.
    for i in range(750):
        fresh = i < 735
        rows.append(_row(i, now, fresh=fresh, soft_candidate=(i == 0)))

    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        setup_score_override=65.0,
        min_upside_capacity_r=1.25,
        min_planned_blended_r=1.25,
        min_expected_net_r=0.08,
    )
    result = build_shadow_v2(
        rows,
        universe_coverage=735 / 750,
        regime="NORMAL",
        final_lock=True,
        now=now,
        config=cfg,
        apply_coverage_hysteresis=False,
    )

    assert round(result["dataCoverage"], 2) == 0.98
    assert result["blocked"] is False
    assert result["qualifiedCount"] >= 1
    assert result["selectedCount"] >= 1
    assert result["candidates"][0]["qualificationMode"] == "SCORE_SOFT_PASS"
    assert result["candidates"][0]["score"] >= 65.0


def test_soft_gate_never_bypasses_hard_tradability_safety():
    now = datetime(2026, 9, 21, 10, 30, tzinfo=IST)
    row = _row(1, now, fresh=True, soft_candidate=True)
    row["nearPriceBand"] = True

    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        setup_score_override=65.0,
        min_upside_capacity_r=1.25,
        min_planned_blended_r=1.25,
        min_expected_net_r=0.08,
    )
    result = build_shadow_v2(
        [row],
        universe_coverage=1.0,
        regime="NORMAL",
        final_lock=True,
        now=now,
        config=cfg,
        apply_coverage_hysteresis=False,
    )

    assert result["qualifiedCount"] == 0
    assert result["selectedCount"] == 0
    reasons = {reason for item in result["rejected"] for reason in (item.get("reasonCodes") or [])}
    assert "WITHIN_1PCT_PRICE_BAND" in reasons
