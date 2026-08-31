import threading

from app.services.angel_index_options import (
    INDEXES,
    IST_ZONE,
    _apply_oi_baselines,
    _chain_confirmation,
    _contract_risk_reward,
    _contracts,
    _fetch_candles_with_retry,
    _futures_oi_state,
    _effective_breadth_gate,
    _local_greeks,
    _weighted_breadth,
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


def test_sensex_resolution_does_not_select_sensex50_future():
    rows = _master("SENSEX", "BFO") + [
        {"token": "bad", "symbol": "SENSEX5026AUGFUT", "name": "SENSEX50",
         "expiry": "01JAN2098", "strike": "-1", "lotsize": "10",
         "instrumenttype": "FUTIDX", "exch_seg": "BFO"},
    ]
    _, _, future = _contracts(rows, INDEXES[3], 77_750, today=date(2026, 8, 26))
    assert future is not None
    assert future["name"] == "SENSEX"
    assert future["token"] != "bad"


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


def test_put_breadth_score_penalizes_bullish_constituents():
    intraday = {"vwap": 100, "ema9": 101}
    snapshot = {
        "stockQuotes": {
            symbol: {"ltpRaw": 110, "intraday": intraday}
            for symbol in ("HDFCBANK", "ICICIBANK", "RELIANCE", "BHARTIARTL", "INFY", "LT", "ITC", "SBIN", "AXISBANK", "KOTAKBANK")
        }
    }
    converted = option_data_to_strategy_inputs({
        "indices": {"NIFTY": {
            "source": "ANGEL_ONE", "status": "LIVE", "spot": 25000, "spotClose": 25100,
            "chain": [], "structure": {"status": "CONFIRMED", "direction": "PUT", "last": 25000, "ema9": 25050},
        }}
    }, snapshot)["indices"]["NIFTY"]
    assert converted["breadth"]["classification"] == "OPPOSING"
    assert converted["breadth"]["directionalScore"] == -1.0
    assert converted["scores"]["breadth"] == 0.0
    assert converted["gates"]["breadth"] is False


def test_breadth_threshold_scales_with_actual_quote_proxy_share():
    snapshot = {
        "indexConstituentWeights": {"NIFTY": [
            {"symbol": "CANDLE", "weight": 50}, {"symbol": "QUOTE", "weight": 50},
        ]},
        "stockQuotes": {
            "CANDLE": {"ltpRaw": 110, "intraday": {"vwap": 100, "ema9": 101}},
            "QUOTE": {"ltpRaw": 110, "open": 100, "close": 101},
        },
    }
    breadth = _weighted_breadth(snapshot, "NIFTY", "CALL")
    assert breadth["quoteProxyPct"] == 50.0
    assert breadth["alignmentFloor"] == 0.625
    assert breadth["aligned"] is True


def test_partial_directional_breadth_can_pass_only_with_strong_independent_evidence():
    partial = {
        "status": "LIVE", "aligned": False, "strictAligned": False,
        "directionalScore": 0.52, "adaptiveFloor": 0.50, "classification": "PARTIAL",
    }
    allowed = _effective_breadth_gate(
        partial, strong_oi=True, chain_aligned=True, expected_r=2.2,
        spread_pct=0.8, vix_regime="NORMAL",
    )
    assert allowed["aligned"] is True
    assert allowed["confirmationMode"] == "ADAPTIVE_STRONG_EVIDENCE"

    blocked = _effective_breadth_gate(
        partial, strong_oi=True, chain_aligned=True, expected_r=1.9,
        spread_pct=0.8, vix_regime="NORMAL",
    )
    assert blocked["aligned"] is False
    assert blocked["adaptiveChecks"]["minimumExpectedR"] is False


def test_opposing_breadth_never_uses_adaptive_confirmation():
    opposing = {
        "status": "LIVE", "aligned": False, "strictAligned": False,
        "directionalScore": -0.05, "adaptiveFloor": 0.35, "classification": "OPPOSING",
    }
    result = _effective_breadth_gate(
        opposing, strong_oi=True, chain_aligned=True, expected_r=10.0,
        spread_pct=0.1, vix_regime="NORMAL",
    )
    assert result["aligned"] is False
    assert result["reason"] == "BREADTH_OPPOSES_DIRECTION"


def test_early_directional_breadth_requires_exceptional_independent_evidence():
    early = {
        "status": "LIVE", "aligned": False, "strictAligned": False,
        "directionalScore": 0.14, "adaptiveFloor": 0.50, "classification": "NEUTRAL",
    }
    allowed = _effective_breadth_gate(
        early, strong_oi=True, chain_aligned=True, expected_r=3.76,
        spread_pct=0.4, vix_regime="NORMAL",
    )
    assert allowed["aligned"] is True
    assert allowed["strictAligned"] is False
    assert allowed["confirmationMode"] == "EARLY_EXCEPTIONAL_EVIDENCE"
    assert allowed["earlyFloor"] == 0.10

    weak_rr = _effective_breadth_gate(
        early, strong_oi=True, chain_aligned=True, expected_r=2.99,
        spread_pct=0.4, vix_regime="NORMAL",
    )
    assert weak_rr["aligned"] is False

    flat = _effective_breadth_gate(
        {**early, "directionalScore": 0.0}, strong_oi=True, chain_aligned=True,
        expected_r=10.0, spread_pct=0.1, vix_regime="NORMAL",
    )
    assert flat["aligned"] is False
    assert flat["reason"] == "BREADTH_TOO_NEUTRAL"


def test_local_black_scholes_fills_missing_sensex_put_greeks():
    result = _local_greeks(
        {"strike": 77300, "ltp": 420, "optionType": "PUT"},
        77321,
        "2026-08-25",
        now=datetime(2026, 8, 24, 10, 0, tzinfo=IST_ZONE),
    )
    assert -1 < result["delta"] < 0
    assert result["gamma"] > 0
    assert result["iv"] > 0
    assert result["greeksSource"] == "LOCAL_BLACK_SCHOLES"


def test_local_black_scholes_replaces_expiry_day_zero_greeks():
    result = _local_greeks(
        {"strike": 24300, "ltp": 92, "optionType": "CALL", "delta": 0, "gamma": 0,
         "theta": 0, "vega": 0, "iv": 0, "greeksSource": "ANGEL_ONE"},
        24334,
        "2026-08-25",
        now=datetime(2026, 8, 25, 11, 0, tzinfo=IST_ZONE),
    )
    assert 0 < result["delta"] < 1
    assert result["gamma"] > 0
    assert result["iv"] > 0
    assert result["greeksSource"] == "LOCAL_BLACK_SCHOLES"
    assert result["providerGreeksSource"] == "ANGEL_ONE"


def test_futures_oi_classifies_all_directional_regimes():
    assert _futures_oi_state({"ltp": 99, "close": 100, "oi": 110, "previousOi": 100})["state"] == "SHORT_BUILDUP"
    assert _futures_oi_state({"ltp": 99, "close": 100, "oi": 90, "previousOi": 100})["state"] == "LONG_UNWINDING"
    assert _futures_oi_state({"ltp": 101, "close": 100, "oi": 110, "previousOi": 100})["state"] == "LONG_BUILDUP"
    assert _futures_oi_state({"ltp": 101, "close": 100, "oi": 90, "previousOi": 100})["state"] == "SHORT_COVERING"


def test_chain_confirmation_uses_atm_band_wall_migration():
    chain = [
        {"optionType": "PUT", "oiChange": -200, "ltp": 90, "close": 100},
        {"optionType": "CALL", "oiChange": 300, "ltp": 80, "close": 85},
    ]
    evidence = _chain_confirmation(chain, "PUT", chain[0])
    assert evidence["aligned"] is True
    assert evidence["reason"] == "OPPOSING_WALL_BUILDUP_AND_SUPPORT_UNWIND"


def test_intraday_oi_baseline_persists_and_warms_before_use(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_OI_BASELINE_FILE", str(tmp_path / "oi.json"))
    first = {"indices": {"NIFTY": {"future": {"symbol": "NIFTYFUT", "oi": 1000},
                                      "chain": [{"symbol": "NIFTYCE", "oi": 500}]}}}
    start = datetime(2026, 8, 24, 10, 0, tzinfo=IST_ZONE)
    _apply_oi_baselines(first, now=start)
    assert first["indices"]["NIFTY"]["future"]["oiBaseline"]["basis"] == "WARMING_UP"

    second = {"indices": {"NIFTY": {"future": {"symbol": "NIFTYFUT", "oi": 1120},
                                       "chain": [{"symbol": "NIFTYCE", "oi": 450}]}}}
    _apply_oi_baselines(second, now=start + timedelta(minutes=2))
    future = second["indices"]["NIFTY"]["future"]
    option = second["indices"]["NIFTY"]["chain"][0]
    assert future["previousOi"] == 1000
    assert future["oiChange"] == 120
    assert future["oiBaseline"]["basis"] == "INTRADAY_SESSION_BASELINE"
    assert option["oiChange"] == -50


def test_provider_previous_oi_is_preferred_over_intraday_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_OI_BASELINE_FILE", str(tmp_path / "oi.json"))
    payload = {"indices": {"NIFTY": {"future": {"symbol": "NIFTYFUT", "oi": 1200, "previousOi": 900}, "chain": []}}}
    _apply_oi_baselines(payload, now=datetime(2026, 8, 24, 10, 0, tzinfo=IST_ZONE))
    future = payload["indices"]["NIFTY"]["future"]
    assert future["oiChange"] == 300
    assert future["oiBaseline"]["basis"] == "PROVIDER_PREVIOUS_OI"


def test_contract_risk_reward_uses_orb_invalidation_and_atr_target():
    evidence = _contract_risk_reward(
        {"ltp": 100, "delta": 0.55, "gamma": 0.001, "spreadPct": 1.0},
        {"last": 247, "ema9": 246, "orbHigh": 245, "orbLow": 235, "atr5m": 12},
        "CALL",
    )
    assert evidence["basis"] == "ORB_INVALIDATION_NEAREST_ATR_OR_MEASURED_MOVE"
    assert evidence["stop"] == 246
    assert evidence["target"] == 255
    assert evidence["projectedOptionLoss"] < 20
    assert evidence["spreadCost"] == 1
    assert evidence["expectedR"] > 1.5


def test_contract_risk_reward_rejects_exhausted_orb_target():
    evidence = _contract_risk_reward(
        {"ltp": 100, "delta": -0.55, "gamma": 0.001},
        {"last": 220, "ema9": 225, "orbHigh": 245, "orbLow": 235, "atr5m": 10},
        "PUT",
    )
    assert evidence["basis"] == "ORB_INVALIDATION_NEAREST_ATR_OR_MEASURED_MOVE"
    assert evidence["stop"] == 225
    assert evidence["target"] == 210
