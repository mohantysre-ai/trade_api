from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.shadow import build_shadow_v2

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 9, 22, 11, 30, tzinfo=IST)


def _row(symbol="EXPENSIVE"):
    score = 70.0
    return {
        "symbol": symbol, "ticker": symbol, "universeSegment": "NIFTY100", "sector": "IT",
        "decisionPrice": 2500.0, "structureStop": 2450.0, "atr14": 45.0,
        "mdtv20": 2_000_000_000.0, "dailyObservationCount": 30,
        "modeledRoundTripCostPct": 0.30, "spreadPct": 0.09, "availableAskDepth": 1000,
        "dailyBarsThroughPreviousClose": True, "corporateEventsCurrent": True,
        "surveillanceCurrent": True, "universeCurrent": True,
        "sourceTimestamps": {"quote": NOW.astimezone(timezone.utc).isoformat(), "bars1h": NOW.astimezone(timezone.utc).isoformat()},
        "trendPriorPctile": score, "residualStrengthPctile": score, "setupQualityPctile": score,
        "rvolPctile": score, "clvPctile": score, "sectorStrengthPctile": score, "liquidityPctile": score,
        "upsideCapacityR": 1.30, "plannedMaxBlendedR": 1.30, "extensionAtr": 1.0, "unexplainedGapPct": 0.0,
    }


def test_high_price_candidate_uses_structural_risk_for_cost_r():
    cfg = SwingV2Config(enabled=True, mode="PAPER", authority="V2", setup_score_override=65.0, min_upside_capacity_r=1.25, min_planned_blended_r=1.25, min_expected_net_r=0.08)
    result = build_shadow_v2([_row()], universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    assert result["qualifiedCount"] == 1
    reasons = {reason for rejected in result["rejected"] for reason in (rejected.get("reasonCodes") or [])}
    assert "NET_REWARD_BELOW_MINIMUM" not in reasons


def test_rank_unrated_reports_decisive_reason():
    row = _row("UNRATED")
    row.pop("trendPriorPctile")
    cfg = SwingV2Config(enabled=True, mode="PAPER", authority="V2")
    result = build_shadow_v2([row], universe_coverage=1.0, regime="NORMAL", final_lock=True, now=NOW, config=cfg, apply_coverage_hysteresis=False)
    reasons = {reason for rejected in result["rejected"] for reason in (rejected.get("reasonCodes") or [])}
    assert "RANK_UNRATED" in reasons
    assert "MISSING_trendPriorPctile" in reasons
