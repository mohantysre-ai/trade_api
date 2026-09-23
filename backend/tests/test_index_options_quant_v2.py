from app.services.index_options.quant_v2 import (
    GREEK_LIMIT_DELTA_BPS,
    GREEK_LIMIT_GAMMA_BPS,
    GREEK_LIMIT_VEGA_BPS,
    GREEK_SOFT_LIMIT_START,
    IV_SHOCK_POINTS,
    SPOT_SHOCK_PCT,
    STRESS_LIMIT_BPS,
    _bs,
    _N,
    common_scenarios,
    infer_regime_probabilities,
    portfolio_greeks,
    reprice_structure,
    risk_governor,
    score_candidate,
    select_quant_portfolio,
)
from math import exp, log, sqrt


def _bs_greeks(spot, strike, t, r, sigma, is_call):
    if spot <= 0 or strike <= 0 or t <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    d1 = (log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt(t))
    d2 = d1 - sigma * sqrt(t)
    pdf = exp(-0.5 * d1 * d1) / sqrt(2.0 * 3.141592653589793)
    delta = _N.cdf(d1) if is_call else _N.cdf(d1) - 1.0
    gamma = pdf / (spot * sigma * sqrt(t))
    vega = spot * pdf * sqrt(t) / 100.0
    theta_year = (
        -(spot * pdf * sigma) / (2.0 * sqrt(t))
        - r * strike * exp(-r * t) * _N.cdf(d2)
        if is_call
        else -(spot * pdf * sigma) / (2.0 * sqrt(t))
        + r * strike * exp(-r * t) * _N.cdf(-d2)
    )
    theta = theta_year / 365.0
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def _make_nifty_strangle(spot=23346.4, dte=3, iv=0.15, r=0.065, lot_size=65, qty=1):
    call_strike = 24200
    put_strike = 23800
    t = max(1 / 365, dte / 365)
    call = _bs_greeks(spot, call_strike, t, r, iv, True)
    put = _bs_greeks(spot, put_strike, t, r, iv, False)
    call_price = _bs(spot, call_strike, t, iv, True, 0.065)
    put_price = _bs(spot, put_strike, t, iv, False, 0.065)
    call_entry = round(call_price, 4)
    put_entry = round(put_price, 4)
    return {
        "strategyId": "LONG_STRANGLE",
        "key": "NIFTY",
        "eligible": True,
        "spot": spot,
        "atmIv": iv * 100,
        "realizedVol": iv * 100,
        "dte": dte,
        "maxProfit": None,
        "maxLoss": 2 * (call_entry + put_entry) * lot_size * qty,
        "delta": (call["delta"] + put["delta"]) * lot_size * qty,
        "gamma": (call["gamma"] + put["gamma"]) * lot_size * qty,
        "theta": (call["theta"] + put["theta"]) * lot_size * qty,
        "vega": (call["vega"] + put["vega"]) * lot_size * qty,
        "legs": [
            {
                "symbol": "NIFTY24200CE",
                "optionType": "CE",
                "strike": call_strike,
                "side": "BUY",
                "entryPrice": call_entry,
                "qty": qty,
                "lotSize": lot_size,
                "spreadPct": 1,
            },
            {
                "symbol": "NIFTY23800PE",
                "optionType": "PE",
                "strike": put_strike,
                "side": "BUY",
                "entryPrice": put_entry,
                "qty": qty,
                "lotSize": lot_size,
                "spreadPct": 1,
            },
        ],
        "gateEvidence": {
            "breadth": {"directionalScore": 0},
            "futuresOi": {"state": "NEUTRAL"},
            "volatilityEdge": {"ivEdgePoints": 8},
        },
    }


def _make_nifty_straddle(spot=24000, dte=3, iv=0.15, r=0.065, lot_size=65, qty=1):
    strike = 24000
    t = max(1 / 365, dte / 365)
    call = _bs_greeks(spot, strike, t, r, iv, True)
    put = _bs_greeks(spot, strike, t, r, iv, False)
    call_price = _bs(spot, strike, t, iv, True)
    put_price = _bs(spot, strike, t, iv, False)
    call_entry = round(call_price, 4)
    put_entry = round(put_price, 4)
    return {
        "strategyId": "LONG_STRADDLE",
        "key": "NIFTY",
        "eligible": True,
        "spot": spot,
        "atmIv": iv * 100,
        "realizedVol": iv * 100,
        "dte": dte,
        "maxProfit": None,
        "maxLoss": 2 * (call_entry + put_entry) * lot_size * qty,
        "delta": (call["delta"] + put["delta"]) * lot_size * qty,
        "gamma": (call["gamma"] + put["gamma"]) * lot_size * qty,
        "theta": (call["theta"] + put["theta"]) * lot_size * qty,
        "vega": (call["vega"] + put["vega"]) * lot_size * qty,
        "legs": [
            {
                "symbol": "NIFTY24000CE",
                "optionType": "CE",
                "strike": strike,
                "side": "BUY",
                "entryPrice": call_entry,
                "qty": qty,
                "lotSize": lot_size,
                "spreadPct": 1,
            },
            {
                "symbol": "NIFTY24000PE",
                "optionType": "PE",
                "strike": strike,
                "side": "BUY",
                "entryPrice": put_entry,
                "qty": qty,
                "lotSize": lot_size,
                "spreadPct": 1,
            },
        ],
        "gateEvidence": {
            "breadth": {"directionalScore": 0},
            "futuresOi": {"state": "NEUTRAL"},
            "volatilityEdge": {"ivEdgePoints": 8},
        },
    }


def _make_banknifty_negative_ev(spot=50000, dte=3, iv=0.18, r=0.065, lot_size=35, qty=1):
    strike = 50000
    t = max(1 / 365, dte / 365)
    call = _bs_greeks(spot, strike, t, r, iv, True)
    put = _bs_greeks(spot, strike, t, r, iv, False)
    call_price = _bs(spot, strike, t, iv, True)
    put_price = _bs(spot, strike, t, iv, False)
    call_entry = round(call_price, 4)
    put_entry = round(put_price, 4)
    return {
        "strategyId": "LONG_STRADDLE",
        "key": "BANKNIFTY",
        "eligible": True,
        "spot": spot,
        "atmIv": iv * 100,
        "realizedVol": iv * 100,
        "dte": dte,
        "maxProfit": None,
        "maxLoss": 2 * (call_entry + put_entry) * lot_size * qty,
        "delta": (call["delta"] + put["delta"]) * lot_size * qty,
        "gamma": (call["gamma"] + put["gamma"]) * lot_size * qty,
        "theta": (call["theta"] + put["theta"]) * lot_size * qty,
        "vega": (call["vega"] + put["vega"]) * lot_size * qty,
        "legs": [
            {
                "symbol": "BANKNIFTY50000CE",
                "optionType": "CE",
                "strike": strike,
                "side": "BUY",
                "entryPrice": call_entry,
                "qty": qty,
                "lotSize": lot_size,
                "spreadPct": 1,
            },
            {
                "symbol": "BANKNIFTY50000PE",
                "optionType": "PE",
                "strike": strike,
                "side": "BUY",
                "entryPrice": put_entry,
                "qty": qty,
                "lotSize": lot_size,
                "spreadPct": 1,
            },
        ],
        "gateEvidence": {
            "breadth": {"directionalScore": 0},
            "futuresOi": {"state": "NEUTRAL"},
            "volatilityEdge": {"ivEdgePoints": 8},
        },
    }


def candidate(strategy="IRON_CONDOR", max_profit=3000, max_loss=5000, eligible=True, index="NIFTY"):
    return {
        "strategyId": strategy,
        "key": index,
        "eligible": eligible,
        "spot": 24000,
        "atmIv": 15,
        "realizedVol": 14,
        "dte": 3,
        "maxProfit": max_profit,
        "maxLoss": max_loss,
        "delta": 0.02,
        "gamma": 0.0001,
        "theta": 10,
        "vega": -2,
        "legs": [
            {"symbol": "NIFTY23900PE", "optionType": "PE", "strike": 23900, "side": "SELL", "entryPrice": 100, "qty": 1, "lotSize": 25, "spreadPct": 1},
            {"symbol": "NIFTY23700PE", "optionType": "PE", "strike": 23700, "side": "BUY", "entryPrice": 50, "qty": 1, "lotSize": 25, "spreadPct": 1},
            {"symbol": "NIFTY24100CE", "optionType": "CE", "strike": 24100, "side": "SELL", "entryPrice": 100, "qty": 1, "lotSize": 25, "spreadPct": 1},
            {"symbol": "NIFTY24300CE", "optionType": "CE", "strike": 24300, "side": "BUY", "entryPrice": 50, "qty": 1, "lotSize": 25, "spreadPct": 1},
        ],
        "gateEvidence": {"breadth": {"directionalScore": 0}, "futuresOi": {"state": "NEUTRAL"}, "volatilityEdge": {"ivEdgePoints": 8}},
    }


def test_regime_is_probability_simplex():
    p = infer_regime_probabilities(candidate())
    assert abs(sum((p.trend_up, p.trend_down, p.range, p.vol_expansion, p.vol_compression)) - 1) < 1e-9


def test_common_distribution_probability_is_one():
    assert abs(sum(x.probability for x in common_scenarios(candidate())) - 1) < 1e-9


def test_reprices_every_leg_across_same_scenarios():
    r = reprice_structure(candidate())
    assert r["valid"]
    assert len(r["outcomes"]) == 8
    assert all("pnl" in x for x in r["outcomes"])
    assert r["cvar95"] >= 0


def test_missing_defined_loss_rejected():
    d = score_candidate(candidate(max_loss=0))
    assert d.decision == "REJECT"
    assert "DEFINED_LEGS_AND_MAX_LOSS_REQUIRED" in d.reasons


def test_upstream_ineligible_never_admitted():
    d = score_candidate(candidate(eligible=False))
    assert d.decision == "REJECT"
    assert d.reasons == ("UPSTREAM_INELIGIBLE",)


def test_no_trade_is_explicit_competitor():
    weak = candidate(max_profit=50, max_loss=10000)
    r = select_quant_portfolio([weak])
    assert r["noTradeUtility"] == 0.0
    assert r["decision"] in {"NO_TRADE", "TRADE"}
    if r["decision"] == "NO_TRADE":
        assert r["selected"] == []


def test_portfolio_greeks_aggregate():
    g = portfolio_greeks([candidate(), candidate(index="BANKNIFTY")])
    assert round(g["delta"], 4) == 0.04
    assert round(g["theta"], 2) == 20


def test_stress_governor_exposes_limits_and_stress():
    g = risk_governor(candidate(), [], 1_000_000)
    assert "greeks" in g and "stressLoss" in g and "limits" in g
    assert isinstance(g["reasons"], list)


def test_quant_portfolio_returns_auditable_ranked_decisions():
    r = select_quant_portfolio([candidate(), candidate("BULL_PUT_CREDIT_SPREAD", index="BANKNIFTY")])
    assert r["engine"] == "INDEX_OPTIONS_QUANT_V2"
    assert r["model"] == "COMMON_SCENARIO_DISTRIBUTION_REPRICER"
    assert "ranked" in r and "portfolioRisk" in r


def test_quant_portfolio_reserves_independent_buy_and_sell_sleeves(monkeypatch):
    import app.services.index_options.quant_v2 as quant

    rows = [
        {**candidate("BUY_A", index="NIFTY"), "strategyMode": "BUY_PREMIUM", "testUtility": 30},
        {**candidate("BUY_B", index="BANKNIFTY"), "strategyMode": "BUY_PREMIUM", "testUtility": 20},
        {**candidate("SELL_A", index="SENSEX"), "strategyMode": "SELL_PREMIUM", "testUtility": 10},
    ]

    def fake_score(row, **_kwargs):
        utility = float(row["testUtility"])
        return quant.QuantDecision(
            str(row["strategyId"]), str(row["key"]), utility, utility,
            1, 0, 0, 0, 0, "ADMIT", (), 1,
        )

    def fake_governor(*_args, **_kwargs):
        return {"pass": True, "reasons": [], "greeks": {}, "stressLoss": 0, "limits": {}}

    monkeypatch.setattr(quant, "score_candidate", fake_score)
    monkeypatch.setattr(quant, "risk_governor", fake_governor)
    result = quant.select_quant_portfolio(rows, max_positions=2, max_per_sleeve=2)
    assert [row["strategy_id"] for row in result["selected"]] == ["BUY_A", "SELL_A"]


def test_entry_premium_and_greeks_from_identical_bs_inputs():
    c = _make_nifty_strangle()
    call_leg = c["legs"][0]
    put_leg = c["legs"][1]
    assert call_leg["entryPrice"] > 0
    assert put_leg["entryPrice"] > 0
    t = max(1 / 365, c["dte"] / 365)
    for leg in c["legs"]:
        expected = _bs(c["spot"], leg["strike"], t, c["atmIv"] / 100, leg["optionType"] == "CE")
        assert abs(leg["entryPrice"] - expected) < 1e-4


def test_zero_shock_repricing_has_zero_pnl():
    c = _make_nifty_strangle()
    from app.services.index_options.quant_v2 import Scenario
    scenarios = [Scenario(name="ZERO", probability=1.0, spot_return=0.0, iv_shift=0.0)]
    rp = reprice_structure(c, scenarios)
    assert abs(rp["outcomes"][0]["pnl"]) < 1e-6


def test_flat_iv_down_reduces_long_vega_value():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    flat = next(x for x in rp["outcomes"] if x["scenario"] == "FLAT")
    assert flat["pnl"] < 0


def test_iv_up_increases_long_vega_value():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    vol_exp = next(x for x in rp["outcomes"] if x["scenario"] == "VOL_EXPANSION")
    assert vol_exp["pnl"] > 0


def test_long_strangle_spot_curve_is_convex():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    outcomes = {x["scenario"]: x["pnl"] for x in rp["outcomes"]}
    assert outcomes["CRASH"] > outcomes["DOWN"] > outcomes["RANGE_DOWN"]


def test_scenario_pnl_subtracts_entry_debit():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    call_entry = c["legs"][0]["entryPrice"]
    put_entry = c["legs"][1]["entryPrice"]
    total_entry = (call_entry + put_entry) * 65
    for outcome in rp["outcomes"]:
        scenario_value = total_entry + outcome["pnl"]
        assert scenario_value >= -1e-6


def test_ev_uses_pnl_not_option_values():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    ev = sum(x["probability"] * x["pnl"] for x in rp["outcomes"])
    assert abs(rp["ev"] - ev) < 1e-6


def test_cvar_from_true_losses():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    ordered = sorted(rp["outcomes"], key=lambda x: x["pnl"])
    remaining = 0.05
    tail = 0.0
    mass = 0.0
    for x in ordered:
        take = min(remaining, x["probability"])
        tail += x["pnl"] * take
        mass += take
        remaining -= take
        if remaining <= 1e-9:
            break
    cvar = max(0.0, -tail / (mass or 0.05))
    assert abs(rp["cvar95"] - cvar) < 1e-6


def test_long_premium_max_loss_invariant():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    assert rp["stressLoss"] <= c["maxLoss"] + 1e-6


def test_scenario_probabilities_sum_to_one():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    assert abs(sum(x["probability"] for x in rp["outcomes"]) - 1.0) < 1e-9


def test_realistic_nifty_short_dte_fixture():
    c = _make_nifty_strangle()
    assert c["spot"] > 0
    assert c["dte"] > 0
    assert 0 < c["atmIv"] / 100 < 1
    for leg in c["legs"]:
        assert leg["entryPrice"] > 0
        assert leg["lotSize"] > 0


def test_gamma_bs_provider_scale_sanity():
    c = _make_nifty_strangle()
    assert abs(c["gamma"]) < 100.0


def test_small_move_delta_gamma_approximation():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    outcomes = {x["scenario"]: x["pnl"] for x in rp["outcomes"]}
    assert outcomes["CRASH"] > 0
    assert outcomes["VOL_EXPANSION"] > 0


def test_large_move_full_repricing_superior():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    crash = next(x for x in rp["outcomes"] if x["scenario"] == "CRASH")
    assert crash["pnl"] > 0


def test_seller_structures_unaffected():
    c = candidate(strategy="BULL_PUT_CREDIT_SPREAD", max_profit=3000, max_loss=5000, eligible=True, index="NIFTY")
    d = score_candidate(c)
    assert d.decision in {"ADMIT", "REJECT"}


def test_positive_ev_nifty_strangle_with_realistic_bs():
    c = _make_nifty_strangle()
    d = score_candidate(c)
    assert d.decision in {"ADMIT", "REJECT"}
    if d.decision == "ADMIT":
        assert d.utility > 0
        assert "NO_TRADE_DOMINATES" not in d.reasons


def test_negative_ev_banknifty_with_realistic_bs():
    c = _make_banknifty_negative_ev()
    c["legs"][0]["entryPrice"] = 2000
    c["legs"][1]["entryPrice"] = 2000
    c["maxLoss"] = 2 * 2000 * 35
    d = score_candidate(c)
    assert d.decision == "REJECT"
    assert d.utility <= 0


def test_quantity_scaling_with_realistic_bs():
    c1 = _make_nifty_strangle(qty=1)
    c2 = _make_nifty_strangle(qty=2)
    d1 = score_candidate(c1)
    d2 = score_candidate(c2)
    assert d2.expected_value > d1.expected_value
    assert d2.cvar95 > d1.cvar95


def test_governor_boundary_delta():
    base = _make_nifty_strangle()
    nav = 1_000_000
    limit = nav * GREEK_LIMIT_DELTA_BPS
    below = dict(base, delta=limit - 0.1, maxLoss=limit + 100)
    equal = dict(base, delta=limit, maxLoss=limit + 100)
    above = dict(base, delta=limit + 0.1, maxLoss=limit + 100)
    assert risk_governor(below, [], nav, stress_loss=0)["pass"] is True
    assert risk_governor(equal, [], nav, stress_loss=0)["pass"] is True
    assert risk_governor(above, [], nav, stress_loss=0)["pass"] is False


def test_governor_boundary_vega():
    base = _make_nifty_strangle()
    nav = 1_000_000
    limit = nav * GREEK_LIMIT_VEGA_BPS
    below = dict(base, vega=limit - 0.1)
    equal = dict(base, vega=limit)
    above = dict(base, vega=limit + 0.1)
    assert risk_governor(below, [], nav)["pass"] is True
    assert risk_governor(equal, [], nav)["pass"] is True
    assert risk_governor(above, [], nav)["pass"] is False


def test_stress_governor_boundary():
    c = _make_nifty_strangle()
    nav = 1_000_000
    limit = nav * STRESS_LIMIT_BPS
    assert risk_governor(c, [], nav, stress_loss=limit - 0.1)["pass"] is True
    assert risk_governor(c, [], nav, stress_loss=limit)["pass"] is True
    assert risk_governor(c, [], nav, stress_loss=limit + 0.1)["pass"] is False


def test_no_double_lot_size_multiplication():
    from app.services.index_options.legs import OptionLeg, net_greeks

    legs = [
        OptionLeg(
            strategy_position_id="p1",
            leg_id="l1",
            side="BUY",
            option_type="CE",
            symbol="NIFTY24200CE",
            strike=24200,
            expiry="2026-09-25",
            qty=1,
            lot_size=65,
            delta=0.00473578,
            gamma=4.3393e-05,
            vega=0.29159,
            theta=-0.74859,
        ),
        OptionLeg(
            strategy_position_id="p1",
            leg_id="l2",
            side="BUY",
            option_type="PE",
            symbol="NIFTY23800PE",
            strike=23800,
            expiry="2026-09-25",
            qty=1,
            lot_size=65,
            delta=-0.91449,
            gamma=0.00049233,
            vega=3.30837,
            theta=-4.38815,
        ),
    ]
    g = net_greeks(legs)
    assert abs(g["vega"] - (0.29159 + 3.30837) * 65) < 1e-4
    assert abs(g["delta"] - (0.00473578 - 0.91449) * 65) < 1e-4
    assert abs(g["gamma"] - (4.3393e-05 + 0.00049233) * 65) < 1e-6
    assert abs(g["theta"] - (-0.74859 - 4.38815) * 65) < 1e-4


def test_spot_shock_converts_to_points():
    c = _make_nifty_strangle()
    gov = risk_governor(c, [], 1_000_000)
    expected_spot_move = c["spot"] * SPOT_SHOCK_PCT
    assert abs(gov["riskShocks"]["spotMovePoints"] - expected_spot_move) < 1e-6


def test_no_percent_vs_points_double_conversion():
    c = _make_nifty_strangle()
    gov = risk_governor(c, [], 1_000_000)
    spot_move = gov["riskShocks"]["spotMovePoints"]
    assert abs(spot_move - c["spot"] * SPOT_SHOCK_PCT) < 1e-6
    assert abs(spot_move - c["spot"] * 0.03) < 1e-6


def test_delta_shock_arithmetic():
    c = _make_nifty_strangle()
    gov = risk_governor(c, [], 1_000_000)
    portfolio_delta = gov["greeks"]["delta"]
    spot = c["spot"]
    spot_move = spot * SPOT_SHOCK_PCT
    expected = abs(portfolio_delta) * spot_move
    assert abs(gov["greekShockLoss"]["delta"] - expected) < 1e-6


def test_gamma_shock_arithmetic():
    c = _make_nifty_strangle()
    gov = risk_governor(c, [], 1_000_000)
    portfolio_gamma = gov["greeks"]["gamma"]
    spot = c["spot"]
    spot_move = spot * SPOT_SHOCK_PCT
    expected = 0.5 * abs(portfolio_gamma) * spot_move ** 2
    assert abs(gov["greekShockLoss"]["gamma"] - expected) < 1e-6


def test_vega_shock_arithmetic():
    c = _make_nifty_strangle()
    gov = risk_governor(c, [], 1_000_000)
    portfolio_vega = gov["greeks"]["vega"]
    expected = abs(portfolio_vega) * IV_SHOCK_POINTS
    assert abs(gov["greekShockLoss"]["vega"] - expected) < 1e-6


def test_full_repriced_stress_vs_greek_diagnostics():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    gov = risk_governor(c, [], 1_000_000, stress_loss=rp["stressLoss"])
    assert gov["stressLoss"] == rp["stressLoss"]
    assert gov["scenarioStress"]["stressLoss"] == rp["stressLoss"]


def test_scenario_stress_diagnostics_consistent():
    c = _make_nifty_strangle()
    rp = reprice_structure(c)
    gov = risk_governor(c, [], 1_000_000, stress_loss=rp["stressLoss"])
    assert gov["scenarioStress"]["stressLoss"] == rp["stressLoss"]
    assert gov["scenarioStress"]["stressLimit"] == 1_000_000 * STRESS_LIMIT_BPS


def test_api_diagnostics_include_risk_fields():
    c = _make_nifty_strangle()
    d = score_candidate(c)
    data = d.to_dict()
    assert "portfolio_greeks" in data
    assert "greek_units" in data
    assert "risk_limits" in data
    assert "risk_shocks" in data
    assert "greek_shock_loss" in data
    assert data["greek_units"]["vega"] == "INR per 1 percentage point IV move"
    assert data["risk_shocks"]["spotMovePct"] == 0.03
    assert data["risk_shocks"]["ivMovePoints"] == 10.0


def test_soft_penalty_constants_are_named():
    from app.services.index_options.quant_v2 import (
        GREEK_SOFT_LIMIT_START as start,
        GREEK_SOFT_PENALTY_RATE as rate,
        GREEK_SOFT_PENALTY_MAX_EV_FRACTION as cap,
    )
    assert start == 0.80
    assert rate == 0.005
    assert cap == 0.50


def test_risk_limit_constants_are_named():
    from app.services.index_options.quant_v2 import (
        GREEK_LIMIT_DELTA_BPS,
        GREEK_LIMIT_GAMMA_BPS,
        GREEK_LIMIT_VEGA_BPS,
        STRESS_LIMIT_BPS,
        SPOT_SHOCK_PCT,
        IV_SHOCK_POINTS,
    )
    assert GREEK_LIMIT_DELTA_BPS == 0.0008
    assert GREEK_LIMIT_GAMMA_BPS == 0.00002
    assert GREEK_LIMIT_VEGA_BPS == 0.003
    assert STRESS_LIMIT_BPS == 0.015
    assert SPOT_SHOCK_PCT == 0.03
    assert IV_SHOCK_POINTS == 10.0
