import threading

from app.services.angel_index_options import (
    INDEXES,
    _contracts,
    _fetch_candles_with_retry,
    fetch_angel_index_option_snapshot,
    index_structure_from_candles,
    option_data_to_strategy_inputs,
)
from datetime import date, datetime, timedelta


def _master(name="NIFTY", segment="NFO"):
    return [
        {"token": "1", "symbol": f"{name}01JAN9925000CE", "name": name, "expiry": "01JAN2099", "strike": "2500000", "lotsize": "1", "instrumenttype": "OPTIDX", "exch_seg": segment},
        {"token": "2", "symbol": f"{name}01JAN9925000PE", "name": name, "expiry": "01JAN2099", "strike": "2500000", "lotsize": "1", "instrumenttype": "OPTIDX", "exch_seg": segment},
        {"token": "3", "symbol": f"{name}01JAN99FUT", "name": name, "expiry": "01JAN2099", "strike": "-1", "lotsize": "1", "instrumenttype": "FUTIDX", "exch_seg": segment},
    ]


def test_contract_resolution_normalizes_angel_paise_strike():
    expiry, options, future = _contracts(_master(), INDEXES[0], 25_010)
    assert expiry.isoformat() == "2099-01-01"
    assert {row["_strike"] for row in options} == {25_000.0}
    assert future["symbol"].endswith("FUT")


class FakeClient:
    def fetch_quote(self, exchange, symbol, token):
        return {"ltp": 25_050, "close": 25_000}

    def fetch_batch_quotes(self, instruments):
        rows = {}
        for instrument in instruments:
            rows[instrument.key] = {
                "ltp": 150 if instrument.key.endswith(":1") else 130,
                "close": 120,
                "tradeVolume": 100_000,
                "opnInterest": 200_000,
                "previousOI": 150_000,
                "bestBidPrice": 149.5,
                "bestAskPrice": 150.5,
            }
        return rows

    def fetch_option_greeks(self, name, expiry):
        return [{"strikePrice": "25000", "optionType": "CE", "delta": "0.55", "gamma": "0.001", "theta": "-12", "vega": "10", "impliedVolatility": "14"}]

    def fetch_candles(self, exchange, symboltoken, interval, fromdate, todate):
        return []


def test_angel_snapshot_and_strategy_input_preserve_real_greeks():
    payload = fetch_angel_index_option_snapshot(FakeClient(), master=_master())
    nifty = payload["indices"]["NIFTY"]
    assert nifty["status"] == "LIVE"
    call = next(row for row in nifty["chain"] if row["optionType"] == "CALL")
    assert call["delta"] == 0.55
    converted = option_data_to_strategy_inputs(payload)["indices"]["NIFTY"]
    # A spot change alone cannot choose a direction; 5-minute ORB/EMA structure is mandatory.
    assert converted["direction"] is None
    assert converted["contract"] is None
    assert converted["gates"]["structure"] is None
    assert "WEIGHTED_CONSTITUENT_BREADTH_NOT_CONFIRMED" in converted["dataLimitations"]


def test_index_snapshot_uses_one_thread_for_shared_client():
    seen: list[int] = []

    class Tracking(FakeClient):
        def fetch_quote(self, exchange, symbol, token):
            seen.append(threading.get_ident())
            return super().fetch_quote(exchange, symbol, token)

    fetch_angel_index_option_snapshot(Tracking(), master=_master())
    assert seen
    assert len(set(seen)) == 1


def test_prior_session_bars_seed_ema_but_not_today_orb():
    rows = []
    start = datetime(2026, 8, 21, 9, 15)
    for index in range(20):
        stamp = start + timedelta(minutes=5 * index)
        rows.append([stamp.isoformat(), 100 + index, 101 + index, 99 + index, 100 + index, 1000])
    today = datetime(2026, 8, 24, 9, 15)
    rows.extend([
        [today.isoformat(), 120, 121, 119, 120, 1000],
        [(today + timedelta(minutes=5)).isoformat(), 120, 122, 119, 121, 1000],
        [(today + timedelta(minutes=10)).isoformat(), 121, 123, 120, 124, 1000],
    ])
    structure = index_structure_from_candles(rows, session_date=date(2026, 8, 24))
    assert structure["barCount"] == 3
    assert structure["seedBarCount"] == 20
    assert structure["orbHigh"] == 123
    assert structure["status"] in {"CONFIRMED", "NO_BREAKOUT"}


def test_candle_fetch_retries_empty_response():
    class RetryClient:
        calls = 0

        def fetch_candles(self, *args):
            self.calls += 1
            return [] if self.calls == 1 else [["2026-08-24T09:15:00+05:30", 1, 2, 1, 2, 10]]

    client = RetryClient()
    rows, error = _fetch_candles_with_retry(client, "NSE", "1", datetime.now(), datetime.now(), attempts=2)
    assert rows
    assert error is None
    assert client.calls == 2


def test_leader_basket_supplies_breadth_when_official_weights_absent():
    intraday = {"vwap": 100, "ema9": 101}
    snapshot = {
        "stockQuotes": {
            symbol: {"ltpRaw": 110, "intraday": intraday}
            for symbol in ("HDFCBANK", "ICICIBANK", "RELIANCE", "BHARTIARTL", "INFY", "LT", "ITC", "SBIN", "AXISBANK", "KOTAKBANK")
        }
    }
    converted = option_data_to_strategy_inputs({
        "indices": {"NIFTY": {
            "source": "ANGEL_ONE", "status": "LIVE", "spot": 25000, "spotClose": 24900,
            "chain": [], "greeksStatus": "UNAVAILABLE",
            "structure": {"status": "CONFIRMED", "direction": "CALL", "last": 25000, "ema9": 24950},
        }}
    }, snapshot)["indices"]["NIFTY"]
    assert converted["breadth"]["source"] == "LEADER_BASKET_PROXY"
    assert converted["breadth"]["coveragePct"] == 100.0
    assert converted["gates"]["breadth"] is True
