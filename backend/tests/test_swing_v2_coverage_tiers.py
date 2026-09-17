from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.shadow import _raw_coverage_tier, build_shadow_v2


def test_coverage_tier_boundaries_and_risk_multipliers():
    cfg = SwingV2Config()
    cases = [
        (1.00, "NORMAL", 1.00),
        (0.99, "NORMAL", 1.00),
        (0.97, "DEGRADED", 0.75),
        (0.92, "DEFENSIVE", 0.50),
        (0.85, "BLOCK", 0.00),
        (0.50, "BLOCK", 0.00),
    ]
    for coverage, tier, multiplier in cases:
        assert _raw_coverage_tier(coverage, cfg) == (tier, multiplier)


def test_494_of_498_is_normal_and_493_of_498_is_degraded():
    cfg = SwingV2Config()
    coverage_494 = 494 / 498
    coverage_493 = 493 / 498
    assert coverage_494 == 0.9919678714859438
    assert coverage_494 >= cfg.coverage_normal_threshold
    assert _raw_coverage_tier(coverage_494, cfg) == ("NORMAL", 1.0)
    assert coverage_493 == 0.9899598393574297
    assert coverage_493 < cfg.coverage_normal_threshold
    assert coverage_493 >= cfg.coverage_degraded_threshold
    assert _raw_coverage_tier(coverage_493, cfg) == ("DEGRADED", 0.75)


def test_coverage_risk_multipliers_are_tunable():
    cfg = replace(SwingV2Config(), coverage_degraded_risk_multiplier=0.70, coverage_defensive_risk_multiplier=0.40)
    assert _raw_coverage_tier(0.97, cfg) == ("DEGRADED", 0.70)
    assert _raw_coverage_tier(0.92, cfg) == ("DEFENSIVE", 0.40)


def test_full_coverage_is_behavior_neutral_for_risk():
    cfg = SwingV2Config()
    tier, multiplier = _raw_coverage_tier(1.0, cfg)
    assert tier == "NORMAL"
    assert multiplier == 1.0


def test_block_is_distinct_below_90_percent():
    cfg = SwingV2Config()
    assert _raw_coverage_tier(0.899999, cfg) == ("BLOCK", 0.0)


def test_tiered_gate_is_authoritative_by_default():
    cfg = SwingV2Config()
    assert cfg.coverage_tiers_authoritative is True
    assert cfg.required_coverage == 0.90


def test_final_lock_490_of_505_is_degraded_not_99pct_block():
    now = datetime(2026, 9, 17, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    rows = []
    for index in range(505):
        fresh = index < 490
        rows.append({
            "symbol": f"SYM{index}",
            "universeSegment": "NIFTY100",
            "dailyBarsThroughPreviousClose": fresh,
            "corporateEventsCurrent": fresh,
            "surveillanceCurrent": fresh,
            "universeCurrent": fresh,
            "sourceTimestamps": {"quote": now.isoformat(), "bars1h": now.isoformat()} if fresh else {},
        })
    result = build_shadow_v2(
        rows,
        universe_coverage=490 / 505,
        regime="NORMAL",
        final_lock=True,
        now=now,
        config=SwingV2Config(),
        apply_coverage_hysteresis=False,
    )
    assert result.get("blocked") is not True
    assert result["coverageTier"] == "DEGRADED"
    assert result["funnel"]["block_reason"] is None
    assert result["funnel"]["coverage_numerator"] == 490
    assert result["funnel"]["coverage_denominator"] == 505
