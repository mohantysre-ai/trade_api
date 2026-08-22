from app.services.angel_index_options import (
    INDEXES,
    _contracts,
    fetch_angel_index_option_snapshot,
    option_data_to_strategy_inputs,
)


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
