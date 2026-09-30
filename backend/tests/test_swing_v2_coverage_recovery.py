from app.services.swing_v2 import shadow
from app.services.swing_v2.config import SwingV2Config


def test_coverage_recovers_immediately_from_transient_block():
    cfg = SwingV2Config(coverage_hysteresis_cycles=3)
    shadow._COVERAGE_STATE.update(sessionDate=None, tier=None, pendingTier=None, pendingCycles=0)
    blocked, _, _ = shadow._coverage_tier(0.0, cfg, session_date="2026-09-29", apply_hysteresis=True)
    recovered, multiplier, evidence = shadow._coverage_tier(0.98, cfg, session_date="2026-09-29", apply_hysteresis=True)
    assert blocked == "BLOCK"
    assert recovered == "DEGRADED"
    assert multiplier == cfg.coverage_degraded_risk_multiplier
    assert evidence["pendingTier"] is None
