import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services import eod_intraday_report, eod_swing_report


IST = ZoneInfo("Asia/Kolkata")


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _chart_payload(days):
    return {
        "chart": {
            "result": [{
                "timestamp": [int(datetime.combine(d, datetime.min.time(), IST).timestamp()) for d, *_ in days],
                "indicators": {"quote": [{
                    "high": [hi for _, hi, _, _ in days],
                    "low": [lo for _, _, lo, _ in days],
                    "close": [cl for _, _, _, cl in days],
                }]},
            }]
        }
    }


def test_yahoo_range_rejects_latest_bar_from_wrong_session(monkeypatch):
    payload = _chart_payload([(date(2026, 8, 11), 121, 116, 120)])
    monkeypatch.setattr(eod_intraday_report.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(payload))

    assert eod_intraday_report._yahoo_day_range("PNB", for_date=date(2026, 8, 12)) == (None, None, None)


def test_yahoo_range_selects_requested_session_not_last_element(monkeypatch):
    payload = _chart_payload([
        (date(2026, 8, 11), 119, 115, 118),
        (date(2026, 8, 12), 121, 117, 120),
    ])
    monkeypatch.setattr(eod_intraday_report.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(payload))

    assert eod_intraday_report._yahoo_day_range("PNB", for_date=date(2026, 8, 12)) == (121.0, 117.0, 120.0)


def test_date_matched_eod_does_not_fall_back_to_stale_current_price(monkeypatch):
    monkeypatch.setattr(eod_swing_report, "get_reference_price", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(eod_swing_report, "get_close_mark_price", lambda *_args, **_kwargs: 999.0)
    pick = {
        "symbol": "PNB",
        "direction": "LONG",
        "entryDate": "2026-08-12",
        "entryPrice": 117.73,
        "currentPrice": 118.98,
        "approxQty": 100,
    }

    row = eod_swing_report._evaluate_swing_pick(
        pick,
        after_close=True,
        require_date_matched_mark=True,
    )

    assert row["status"] == "NO_MARK"
    assert row["pnl"] == 0.0
    assert row["skipped"] is True
