from app.services.swing_v2.authoritative import _entry_hunt_diagnostics, _scan_not_ready, _v2_readiness
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
            "historyReadyRows": 400,
            "shortMomentumReadyRows": 390,
            "universeCurrent": True,
            "surveillanceCurrent": True,
            "corporateEventsCurrent": True,
        },
    }
    out = _scan_not_ready(snapshot, cfg)
    assert out["funnel"]["universe"] == 755
    assert out["funnel"]["evaluated"] == 503
    assert out["funnel"]["freshData"] == 390
    assert out["funnel"]["candleMetrics"] == 390
    assert out["funnel"]["topRejectionReasons"][0]["reason"].startswith("HISTORY_READY_COVERAGE_")


def test_readiness_preserves_all_distinct_blockers():
    cfg = _cfg()
    snapshot = {
        "swingV2UniverseSize": 750,
        "swingV2UniverseCoverage": 0.80,
        "swingV2Regime": "REGIME_UNRATED",
        "swingV2DataStatus": {
            "featureRows": 503,
            "historyReadyRows": 400,
            "shortMomentumReadyRows": 390,
            "universeCurrent": False,
            "surveillanceCurrent": False,
            "corporateEventsCurrent": False,
        },
    }
    out = _v2_readiness(snapshot, cfg)
    reasons = out["reasons"]
    assert any(reason.startswith("HISTORY_READY_COVERAGE_") for reason in reasons)
    assert any(reason.startswith("UNIVERSE_QUOTE_COVERAGE_") for reason in reasons)
    assert "UNIVERSE_FEED_NOT_CURRENT" in reasons
    assert "SURVEILLANCE_FEED_NOT_CURRENT" in reasons
    assert "CORPORATE_EVENTS_FEED_NOT_CURRENT" in reasons
    assert "REGIME_UNRATED" in reasons


def test_entry_hunt_diagnostics_exposes_swing_v2_denominators():
    snapshot = {
        "universeSize": 498,
        "volumeScreenedCount": 498,
        "stocks": [{} for _ in range(50)],
        "swingV2UniverseSize": 755,
        "swingV2UniverseCoverage": 0.80,
        "swingV2Regime": "DEFENSIVE",
        "swingV2DataStatus": {
            "featureRows": 503,
            "historyReadyRows": 400,
            "shortMomentumReadyRows": 390,
            "universeCurrent": True,
            "surveillanceCurrent": True,
            "corporateEventsCurrent": True,
        },
    }
    scan = _scan_not_ready(snapshot, _cfg())
    out = _entry_hunt_diagnostics(scan, snapshot)
    assert out["universeSize"] == 755
    assert out["featureRows"] == 503
    assert out["historyReadyRows"] == 400
    assert out["shortMomentumReadyRows"] == 390
    assert out["historyReadyRatio"] == round(400 / 503, 4)
    assert out["universeCoverage"] == 0.80
    assert out["regime"] == "DEFENSIVE"
    assert out["evaluated"] == 503
    assert out["candleMetrics"] == 390
