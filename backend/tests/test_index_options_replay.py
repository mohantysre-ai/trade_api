from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.angel_index_options import index_structure_from_candles, walk_forward_structure
from app.services.index_options_replay import (
    paper_long_option_pnl,
    previous_friday,
    replay_index_options_session,
)

IST = ZoneInfo("Asia/Kolkata")


def _rising_bars(n: int = 25, start: float = 100.0, premium: bool = False):
    t0 = datetime(2026, 8, 21, 9, 15, tzinfo=IST)
    rows = []
    for i in range(n):
        close = (20.0 + i * 0.5) if premium else (start + i * 2.0)
        open_ = close - 0.4
        high = close + 0.5
        low = open_ - 0.3
        ts = (t0 + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append([ts, open_, high, low, close, 1_000])
    return rows


def test_previous_friday_from_sunday_is_21_aug_2026():
    assert previous_friday(date(2026, 8, 23)) == date(2026, 8, 21)


def test_walk_forward_confirms_call_after_orb_and_ema():
    bars = _rising_bars()
    eod = index_structure_from_candles(bars)
    assert eod["direction"] == "CALL"
    assert eod["barCount"] == 25
    walked = walk_forward_structure(bars)
    assert walked["firstDirection"] == "CALL"
    assert walked["confirmedAt"]


def test_paper_option_pnl_uses_confirmation_bar_through_last_close():
    bars = _rising_bars(n=25, premium=True)
    confirm = bars[19][0]
    result = paper_long_option_pnl(bars, confirm, lot_size=75)
    assert result["entry"] == bars[19][4]
    assert result["exit"] == bars[-1][4]
    assert result["pnlPoints"] == round(bars[-1][4] - bars[19][4], 4)
    assert result["pnlRupees"] == round(result["pnlPoints"] * 75, 2)


def test_missing_option_candles_are_not_invented():
    result = paper_long_option_pnl([], "2026-08-21 10:50:00", 75)
    assert result["pnlRupees"] is None
    assert result["limitation"] == "OPTION_CANDLES_UNAVAILABLE"


def _master_for_replay():
    return [
        {"token": "ce1", "symbol": "NIFTY27AUG2625000CE", "name": "NIFTY", "expiry": "27AUG2026", "strike": "2500000", "lotsize": "75", "instrumenttype": "OPTIDX", "exch_seg": "NFO"},
        {"token": "pe1", "symbol": "NIFTY27AUG2625000PE", "name": "NIFTY", "expiry": "27AUG2026", "strike": "2500000", "lotsize": "75", "instrumenttype": "OPTIDX", "exch_seg": "NFO"},
        {"token": "ce2", "symbol": "BANKNIFTY27AUG2655000CE", "name": "BANKNIFTY", "expiry": "27AUG2026", "strike": "5500000", "lotsize": "15", "instrumenttype": "OPTIDX", "exch_seg": "NFO"},
        {"token": "pe2", "symbol": "BANKNIFTY27AUG2655000PE", "name": "BANKNIFTY", "expiry": "27AUG2026", "strike": "5500000", "lotsize": "15", "instrumenttype": "OPTIDX", "exch_seg": "NFO"},
        {"token": "sce", "symbol": "SENSEX27AUG2682000CE", "name": "SENSEX", "expiry": "27AUG2026", "strike": "8200000", "lotsize": "10", "instrumenttype": "OPTIDX", "exch_seg": "BFO"},
        {"token": "fce", "symbol": "FINNIFTY27AUG2624000CE", "name": "FINNIFTY", "expiry": "27AUG2026", "strike": "2400000", "lotsize": "25", "instrumenttype": "OPTIDX", "exch_seg": "NFO"},
    ]


class _ReplayClient:
    def fetch_candles(self, exchange, token, interval, start, end):
        if token in {"ce1", "ce2", "sce", "fce"}:
            return _rising_bars(premium=True)
        starts = {"99926000": 25_000, "99926009": 55_000, "99926037": 24_000, "99919000": 82_000}
        return _rising_bars(start=starts.get(str(token), 25_000))


def test_friday_replay_selects_one_broad_and_one_financial_call():
    payload = replay_index_options_session(_ReplayClient(), date(2026, 8, 21), master=_master_for_replay(), persist=False)
    assert payload["sessionDate"] == "2026-08-21"
    selected = [row["key"] for row in payload["indices"] if row["selected"]]
    assert selected == ["NIFTY", "BANKNIFTY"]
    assert all(row["optionType"] == "CALL" for row in payload["buySideContracts"])
    assert len(payload["buySideContracts"]) <= 10
    assert {row["index"] for row in payload["implemented"]} == {"NIFTY", "BANKNIFTY"}
    nifty = next(row for row in payload["implemented"] if row["index"] == "NIFTY")
    assert nifty["pnlRupees"] is not None
    assert nifty["barCount"] == 25
    assert "RADAR_GATES_NOT_OVERRIDDEN" in payload["limitations"]
    assert "INDEX_CANDLES_UNAVAILABLE" not in payload["limitations"]
    blocked = [row["index"] for row in payload["buySideContracts"] if row.get("blockedBy") == "CORRELATION_GUARD"]
    assert "FINNIFTY" in blocked or "SENSEX" in blocked
