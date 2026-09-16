from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.swing_v2.config import SwingV2Config, load_config
from app.services.swing_v2.data_quality import evaluate_freshness


def _row(now: datetime, *, quote_age: int = 30, bar_age: int = 3600) -> dict:
    return {
        "sourceTimestamps": {
            "quote": (now - timedelta(seconds=quote_age)).isoformat(),
            "depth": (now - timedelta(seconds=quote_age)).isoformat(),
            "bars1h": (now - timedelta(seconds=bar_age)).isoformat(),
        },
        "dailyBarsThroughPreviousClose": True,
        "corporateEventsCurrent": True,
        "surveillanceCurrent": True,
        "universeCurrent": True,
    }


def test_final_lock_accepts_recent_quote_with_latest_completed_one_hour_bar():
    now = datetime.now(timezone.utc)
    ok, reasons = evaluate_freshness(_row(now), final_lock=True, now=now)
    assert ok, reasons


def test_final_lock_rejects_stale_quote_even_when_one_hour_bar_is_valid():
    now = datetime.now(timezone.utc)
    ok, reasons = evaluate_freshness(_row(now, quote_age=61), final_lock=True, now=now)
    assert not ok
    assert "STALE_QUOTE" in reasons


def test_legacy_bars5m_timestamp_is_accepted_as_one_hour_snapshot_compatibility():
    now = datetime.now(timezone.utc)
    row = _row(now)
    row["sourceTimestamps"]["bars5m"] = row["sourceTimestamps"].pop("bars1h")
    ok, reasons = evaluate_freshness(row, final_lock=True, now=now)
    assert ok, reasons


def test_default_policy_is_750_two_session_and_risk_scaled_coverage(monkeypatch):
    for key in (
        "SWING_UNIVERSE",
        "SWING_MAX_OVERNIGHTS",
        "SWING_COVERAGE_TIERS_AUTHORITATIVE",
    ):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    assert cfg.universe == "NIFTY_TOTAL_MARKET_750"
    assert cfg.max_overnights == 2
    assert cfg.coverage_tiers_authoritative is True
    assert cfg.required_coverage == 0.90


def test_policy_keeps_microcap_shadow_only():
    cfg = SwingV2Config()
    assert cfg.microcap_mode == "SHADOW"
    assert "NIFTY_MICROCAP250" not in cfg.active_segments
