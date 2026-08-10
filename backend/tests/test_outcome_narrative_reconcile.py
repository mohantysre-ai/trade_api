"""Outcome narrative FactPack must match table R / MAE / MFE."""
from __future__ import annotations

from app.services.outcome_narrative import (
    _fact_pack,
    canonical_r_multiple,
    metrics_fingerprint,
    narrative_r_consistent,
    sync_diagnostic_metrics,
)


def test_canonical_r_keeps_zero():
    row = {"rMultiple": 0.0}
    diag = {"rMultiple": 0.99}
    assert canonical_r_multiple(row, diag) == 0.0


def test_fact_pack_single_r_not_forensic():
    row = {
        "symbol": "CHOLAFIN",
        "rMultiple": 0.0,
        "pnl": 12.5,
        "deskExitLabel": "EOD_SQUAREOFF",
        "executionStatus": "TRIGGERED",
        "outcomeBucket": "WIN",
        "mfeR": 0.2,
    }
    diag = {
        "rMultiple": 0.99,
        "maePct": 0.4,
        "mfePct": 1.1,
        "isMiss": True,
        "rootCause": "STALLED_TRADE",
        "factors": ["TARGET_NOT_REACHED"],
    }
    pack = _fact_pack(row, diag)
    assert pack["CanonicalMetrics"]["rMultiple"] == 0.0
    assert "rMultiple" not in (pack.get("forensic") or {})
    assert pack["CanonicalMetrics"]["maePct"] == 0.4
    assert pack["CanonicalMetrics"]["mfeR"] == 0.2


def test_sync_diagnostic_overwrites_forensic_r():
    row = {
        "rMultiple": -1.0,
        "missDiagnostic": {"rMultiple": -4.38, "maePct": None},
    }
    synced = sync_diagnostic_metrics(row)
    assert synced["missDiagnostic"]["rMultiple"] == -1.0


def test_narrative_r_consistent_rejects_wrong_r():
    assert narrative_r_consistent("Lost -1.00R at initial stop.", -1.0)
    assert not narrative_r_consistent("Blew through for -4.38R on the day.", -1.0)
    assert narrative_r_consistent("No R cited, only stalled at targets.", 0.84)


def test_fingerprint_changes_when_r_changes():
    row_a = {"rMultiple": 0.84, "pnl": 100}
    row_b = {"rMultiple": 0.66, "pnl": 100}
    diag = {"isMiss": True}
    assert metrics_fingerprint(row_a, diag) != metrics_fingerprint(row_b, diag)
