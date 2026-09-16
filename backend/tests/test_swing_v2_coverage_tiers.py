from dataclasses import replace

from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.shadow import _raw_coverage_tier


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


def test_tiered_gate_is_not_authoritative_by_default():
    cfg = SwingV2Config()
    assert cfg.coverage_tiers_authoritative is False
    assert cfg.required_coverage == 0.99
