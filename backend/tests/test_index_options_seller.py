from datetime import datetime, timedelta

from app.services.angel_index_options import IST_ZONE
from app.services.index_options_engine import build_index_options_radar
from app.services.index_options_paper import reconcile_paper_book
from app.services.index_options_seller import build_defined_risk_seller_setup


def _contract(option_type: str, strike: float, delta: float, bid: float, ask: float, *, lot: int = 75, iv: float = 20.0):
    suffix = "CE" if option_type == "CALL" else "PE"
    return {
        "symbol": f"NIFTY01SEP26{int(strike)}{suffix}", "token": f"{suffix}-{strike}", "exchange": "NFO",
        "optionType": option_type, "strike": strike, "delta": delta,
        "gamma": 0.0005 if abs(delta) < 0.15 else 0.001,
        "theta": -2.0 if abs(delta) < 0.15 else -5.0,
        "vega": 2.0 if abs(delta) < 0.15 else 3.0, "iv": iv, "ltp": (bid + ask) / 2,
        "close": max(3.0, (bid + ask) / 2),
        "bestBid": bid, "bestAsk": ask, "volume": 100_000, "oi": 500_000,
        "oiChange": 25_000, "lotSize": lot,
    }


def _chain(*, iv: float = 20.0):
    return [
        _contract("PUT", 90, -0.10, 0.60, 0.61, iv=iv),
        _contract("PUT", 95, -0.25, 2.80, 2.82, iv=iv),
        _contract("PUT", 100, -0.50, 4.80, 4.84, iv=iv),
        _contract("CALL", 100, 0.50, 4.80, 4.84, iv=iv),
        _contract("CALL", 105, 0.25, 2.80, 2.82, iv=iv),
        _contract("CALL", 110, 0.10, 0.60, 0.61, iv=iv),
    ]


def _seller(chain=None, *, structure=None, vix=12.0):
    structure = structure or {
        "status": "NO_BREAKOUT", "direction": None, "last": 100,
        "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
    }
    return build_defined_risk_seller_setup(
        chain=chain or _chain(), spot=100, expiry_value="2026-09-01", structure=structure,
        breadth_neutral={"status": "LIVE", "score": 0.02, "coveragePct": 100.0},
        breadth_directional={"status": "LIVE", "score": 0.60, "directionalScore": 0.60, "coveragePct": 100.0},
        futures_oi={"state": "LONG_UNWINDING", "priceChangePct": 0.10, "oiChangePct": -2.0},
        directional_oi_aligned=True, vix=vix, vix_regime="CALM", provider_live=True,
        now=datetime(2026, 8, 31, 11, 0, tzinfo=IST_ZONE),
    )


def test_range_builds_defined_risk_iron_condor_from_executable_depth():
    setup = _seller()
    assert setup is not None
    assert setup["strategyType"] == "IRON_CONDOR"
    assert [leg["action"] for leg in setup["legs"]] == ["SELL", "BUY", "SELL", "BUY"]
    assert setup["risk"]["entryCredit"] == 4.38
    assert setup["risk"]["estimatedRoundTripCosts"] == 160.0
    assert setup["risk"]["maxProfitPerLot"] == 168.5
    assert setup["risk"]["maxLossPerLot"] == 206.5
    assert setup["risk"]["creditToRisk"] > 0.8
    assert all(value is True for value in setup["gates"].values())


def test_directional_breakout_builds_bull_put_credit_spread_not_naked_short():
    setup = _seller(structure={
        "status": "CONFIRMED", "direction": "CALL", "last": 104,
        "orbLow": 97, "orbHigh": 103, "atr5m": 2, "barCount": 27,
    })
    assert setup is not None
    assert setup["strategyType"] == "BULL_PUT_CREDIT_SPREAD"
    assert len(setup["legs"]) == 2
    assert {leg["action"] for leg in setup["legs"]} == {"BUY", "SELL"}
    assert setup["risk"]["maxLossPerLot"] > 0


def test_seller_rejects_missing_hedge_and_unpriced_volatility_edge():
    no_wings = [row for row in _chain() if row["strike"] in {95, 100, 105}]
    assert _seller(chain=no_wings) is None
    cheap_iv = _seller(chain=_chain(iv=12.1), vix=12.0)
    assert cheap_iv is not None
    assert cheap_iv["gates"]["volatilityEdge"] is False


def test_eligible_condor_auto_locks_and_takes_half_credit_profit(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    setup = _seller()
    supplied = {"spot": 100, "source": "ANGEL_ONE", "providerStatus": "LIVE", "expiry": "2026-09-01",
                "rawChain": _chain(), "seller": setup}
    radar = build_index_options_radar({"indexOptions": {"indices": {"NIFTY": supplied}}})
    assert radar["sellerCandidates"][0]["state"] == "ELIGIBLE"
    assert radar["selected"][0]["strategyType"] == "IRON_CONDOR"

    now = datetime(2026, 8, 31, 11, 0, tzinfo=IST_ZONE)
    entered = reconcile_paper_book(radar, now=now)
    assert entered["entryCount"] == 1
    assert entered["open"][0]["strategyMode"] == "SELL_PREMIUM"
    assert entered["open"][0]["entryCredit"] == 4.38
    assert entered["open"][0]["estimatedRoundTripCosts"] == 160.0
    assert entered["open"][0]["nakedRisk"] is False

    cheaper = _chain()
    for row in cheaper:
        if abs(row["delta"]) == 0.25:
            row["bestBid"], row["bestAsk"] = 0.70, 0.71
        elif abs(row["delta"]) == 0.10:
            row["bestBid"], row["bestAsk"] = 0.40, 0.405
    next_setup = _seller(chain=cheaper)
    next_radar = build_index_options_radar({"indexOptions": {"indices": {"NIFTY": {
        **supplied, "rawChain": cheaper, "seller": next_setup,
    }}}})
    closed = reconcile_paper_book(next_radar, now=now + timedelta(minutes=5))
    assert closed["open"] == []
    assert closed["closed"][0]["exitReason"] == "PROFIT_TARGET_50PCT_CREDIT"
    assert closed["closed"][0]["exitDebit"] == 0.62
    assert closed["closed"][0]["pnl"] == 122.0


def test_oi_rise_without_premium_softening_is_not_classified_as_writing():
    chain = _chain()
    for row in chain:
        row["close"] = row["ltp"] - 0.10
    setup = _seller(chain=chain)
    assert setup is not None
    assert setup["gates"]["optionChain"] is False


def test_single_trade_max_loss_cap_blocks_auto_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setenv("INDEX_OPTIONS_SELLER_MAX_SINGLE_RISK", "100")
    setup = _seller()
    supplied = {"spot": 100, "source": "ANGEL_ONE", "providerStatus": "LIVE", "expiry": "2026-09-01",
                "rawChain": _chain(), "seller": setup}
    radar = build_index_options_radar({"indexOptions": {"indices": {"NIFTY": supplied}}})
    book = reconcile_paper_book(radar, now=datetime(2026, 8, 31, 11, 0, tzinfo=IST_ZONE))
    assert book["entryCount"] == 0
    assert book["sellerRiskCaps"]["singleTrade"] == 100.0
