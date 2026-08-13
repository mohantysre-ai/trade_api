from app.services.exit_plan import MAX_STOP_PCT, cap_stop_risk
from app.services.intraday_session_engine import _build_levels
from app.services.swing_prefilter import passes_prefilter_metrics
from app.services.swing_session import _matrix_row_levels


def test_stop_risk_hard_capped_at_half_percent():
    assert abs(MAX_STOP_PCT - 0.005) < 1e-12
    assert cap_stop_risk(1000.0, 20.0) == 5.0
    assert cap_stop_risk(1000.0, 3.0) == 3.0


def test_intraday_levels_respect_half_percent_cap():
    levels = _build_levels(200.0, 2.0, "LONG")
    assert levels["riskPerShare"] == 1.0
    assert levels["stopLoss"] == 199.0


def test_swing_matrix_levels_cap_wide_atr_stop():
    stop, _t1, _t2, risk, src = _matrix_row_levels({"atr_pct": 3.0}, 400.0)
    assert abs(risk - 2.0) < 1e-9
    assert stop == 398.0
    assert "max_stop_0p5pct" in src


def test_prefilter_metrics_match_buy_subset():
    assert passes_prefilter_metrics(close=100.0, ema9=99.0, rsi=62.0, volume=2_000_000, volume_sma20=1_000_000) is True
    assert passes_prefilter_metrics(close=100.0, ema9=101.0, rsi=62.0, volume=2_000_000, volume_sma20=1_000_000) is False
    assert passes_prefilter_metrics(close=100.0, ema9=99.0, rsi=50.0, volume=2_000_000, volume_sma20=1_000_000) is False
    assert passes_prefilter_metrics(close=40.0, ema9=39.0, rsi=62.0, volume=2_000_000, volume_sma20=1_000_000) is False
