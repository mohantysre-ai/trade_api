from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.stock_quality import (
    MAX_WICK_NOISE_RATIO,
    MIN_EMA_ANGLE_DEG,
    evaluate_short_term_quality,
    pace_volume_multiplier,
    session_elapsed_fraction,
)

IST = ZoneInfo("Asia/Kolkata")


def _quality_intra(**overrides) -> dict:
    row = {
        "price_above_vwap": True,
        "price_above_ema9": True,
        "rsi": 62.0,
        "pivot_r1_breakout": True,
        "rsi_pivot_break": True,
        "volume_multiplier": 1.8,
        "turnover_cr": 80.0,
        "oi_setup": "LONG_BUILDUP",
        "ema_angle_deg": 25.0,
        "wick_noise_ratio": 0.40,
    }
    row.update(overrides)
    return row


def test_session_elapsed_fraction_mid_morning():
    now = datetime(2026, 8, 14, 11, 15, tzinfo=IST)
    frac = session_elapsed_fraction(now)
    assert 0.30 < frac < 0.40


def test_pace_volume_multiplier_scales_for_elapsed_session():
    now = datetime(2026, 8, 14, 11, 15, tzinfo=IST)
    frac = session_elapsed_fraction(now)
    paced = pace_volume_multiplier(500_000, 1_000_000, now)
    assert paced == 500_000 / (1_000_000 * frac)
    assert paced > 1.0


def test_loosened_angle_and_wick_can_pass_together():
    assert MIN_EMA_ANGLE_DEG == 20.0
    assert MAX_WICK_NOISE_RATIO == 0.45
    ok, reasons = evaluate_short_term_quality("BDL", _quality_intra(), 72.0)
    assert ok is True
    assert reasons == []


def test_legacy_tight_wick_and_angle_no_longer_veto_alone():
    ok, reasons = evaluate_short_term_quality(
        "FLUOROCHEM",
        _quality_intra(ema_angle_deg=21.0, wick_noise_ratio=0.44),
        72.0,
    )
    assert ok is True
    assert reasons == []
    _fail, fail_reasons = evaluate_short_term_quality(
        "NOISE",
        _quality_intra(ema_angle_deg=19.0, wick_noise_ratio=0.46),
        72.0,
    )
    assert "EMA angle below 20 degrees" in fail_reasons
    assert "wick noise too high" in fail_reasons
