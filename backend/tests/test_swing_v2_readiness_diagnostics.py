from app.services.swing_v2.authoritative import _v2_readiness, _scan_not_ready
from app.services.swing_v2.config import SwingV2Config


def _cfg():
    return SwingV2Config(enabled=True, mode="PAPER", authority="V2")


def test_readiness_reports_exact_history_coverage_failure():
    cfg = _cfg()
    snapshot = {
        "swingV2UniverseSize": 750,
        "swingV2UniverseCoverage": 0.98,
        "swingV2Regime": "NORMAL",
        "swingV2DataStatus": {
            "featureRows": 500,
            "historyReadyRows": 400,
            "shortMomentumReadyRows": 390,
            "universeCurrent": True,
            "surveillanceCurrent": True,
            "corporateEventsCurrent": True,
        },
    }
    out = _v2_readiness(snapshot, cfg)
    assert out["ready"] is False
    assert out["historyReadyRatio"] == 0.8
    assert any(reason.startswith("HISTORY_READY_COVERAGE_") for reason in out["reasons"])


def test_not_ready_funnel_uses_real_feature_and_history_counts():
    cfg = _cfg()
    snapshot = {
        "swingV2UniverseSize": 755,
        "swingV2UniverseCoverage": 0.98,
        "swingV2Regime": "NORMAL",
        "swingV2DataStatus": {
            "featureRows": 503,
            "historyReadyRows": 489,
            "shortMomentumReadyRows": 480,
            "universeCurrent": True,
            "surveillanceCurrent": True,
            "corporateEventsCurrent": True,
        },
    }
    out = _scan_not_ready(snapshot, cfg)
    assert out["funnel"]["universe"] == 755
    assert out["funnel"]["evaluated"] == 503
    assert out["funnel"]["freshData"] == 480
    assert out["funnel"]["candleMetrics"] == 480
    assert out["funnel"]["topRejectionReasons"][0]["reason"].startswith("HISTORY_READY_COVERAGE_")
