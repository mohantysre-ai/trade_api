from datetime import datetime
from zoneinfo import ZoneInfo

from app.services import angel_one_feed
from app.services.swing_v2.config import SwingV2Config, load_config


IST = ZoneInfo("Asia/Kolkata")


def _daily(n: int):
    rows = []
    base = 100.0
    for i in range(n):
        close = base * (1.0 + 0.002 * i)
        rows.append({
            "ts": f"2026-08-{(i % 28) + 1:02d} 15:30:00",
            "open": close * 0.997,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000 + i * 1000,
        })
    return rows


def test_short_horizon_metrics_are_ready_with_30_daily_observations(monkeypatch):
    monkeypatch.setenv("SWING_MIN_DAILY_OBSERVATIONS", "30")
    # Use unique dates before the decision date so all rows count as previous.
    rows = []
    start = datetime(2026, 7, 20, tzinfo=IST)
    for i in range(30):
        day = start.date().fromordinal(start.date().toordinal() + i)
        close = 100.0 + i * 0.4
        rows.append({
            "ts": f"{day.isoformat()} 15:30:00",
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000 + i * 10_000,
        })
    now = datetime(2026, 9, 22, 10, 30, tzinfo=IST)
    raw = angel_one_feed._swing_v2_raw_metrics(rows, [], float(rows[-1]["close"]), now)
    assert raw["dailyObservationCount"] == 30
    assert raw["historyReady"] is True
    assert raw["mom10dRaw"] is not None
    assert raw["mom20dRaw"] is not None
    assert raw["mom6mRaw"] is None
    assert raw["mom12mRaw"] is None
    assert raw["recent30dHigh"] is not None
    assert raw["atr14"] is not None
    assert raw["ema20Daily"] is not None
    assert raw["prior20dHigh"] is not None


def test_config_defaults_match_short_horizon_history(monkeypatch):
    for name in ("SWING_MIN_DAILY_OBSERVATIONS", "SWING_HISTORY_LOOKBACK_DAYS"):
        monkeypatch.delenv(name, raising=False)
    cfg = load_config()
    assert cfg.min_daily_observations == 30
    assert cfg.history_lookback_days == 60
    assert cfg.policy_version == "2.4.0"
    assert cfg.feature_version == "swing_features_v2_short_horizon"


def test_config_still_rejects_too_little_history():
    cfg = SwingV2Config(history_lookback_days=29, min_daily_observations=30)
    try:
        cfg.validate()
    except ValueError as exc:
        assert "SWING_HISTORY_LOOKBACK_DAYS" in str(exc)
    else:
        raise AssertionError("29-day lookback must fail validation")
