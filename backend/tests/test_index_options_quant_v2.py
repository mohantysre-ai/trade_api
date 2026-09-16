from app.services.index_options.quant_v2 import common_scenarios,infer_regime_probabilities,portfolio_greeks,reprice_structure,risk_governor,score_candidate,select_quant_portfolio

def candidate(strategy="IRON_CONDOR",max_profit=3000,max_loss=5000,eligible=True,index="NIFTY"):
    return {"strategyId":strategy,"key":index,"eligible":eligible,"spot":24000,"atmIv":15,"realizedVol":14,"dte":3,"maxProfit":max_profit,"maxLoss":max_loss,"delta":0.02,"gamma":0.0001,"theta":10,"vega":-2,"legs":[{"symbol":"NIFTY23900PE","optionType":"PE","strike":23900,"side":"SELL","entryPrice":100,"qty":1,"lotSize":25,"spreadPct":1},{"symbol":"NIFTY23700PE","optionType":"PE","strike":23700,"side":"BUY","entryPrice":50,"qty":1,"lotSize":25,"spreadPct":1},{"symbol":"NIFTY24100CE","optionType":"CE","strike":24100,"side":"SELL","entryPrice":100,"qty":1,"lotSize":25,"spreadPct":1},{"symbol":"NIFTY24300CE","optionType":"CE","strike":24300,"side":"BUY","entryPrice":50,"qty":1,"lotSize":25,"spreadPct":1}],"gateEvidence":{"breadth":{"directionalScore":0},"futuresOi":{"state":"NEUTRAL"},"volatilityEdge":{"ivEdgePoints":8}}}

def test_regime_is_probability_simplex():
    p=infer_regime_probabilities(candidate());assert abs(sum((p.trend_up,p.trend_down,p.range,p.vol_expansion,p.vol_compression))-1)<1e-9

def test_common_distribution_probability_is_one():assert abs(sum(x.probability for x in common_scenarios(candidate()))-1)<1e-9

def test_reprices_every_leg_across_same_scenarios():
    r=reprice_structure(candidate());assert r["valid"];assert len(r["outcomes"])==8;assert all("pnl" in x for x in r["outcomes"]);assert r["cvar95"]>=0

def test_missing_defined_loss_rejected():
    d=score_candidate(candidate(max_loss=0));assert d.decision=="REJECT";assert "DEFINED_LEGS_AND_MAX_LOSS_REQUIRED" in d.reasons

def test_upstream_ineligible_never_admitted():
    d=score_candidate(candidate(eligible=False));assert d.decision=="REJECT";assert d.reasons==("UPSTREAM_INELIGIBLE",)

def test_no_trade_is_explicit_competitor():
    weak=candidate(max_profit=50,max_loss=10000);r=select_quant_portfolio([weak]);assert r["noTradeUtility"]==0.;assert r["decision"] in {"NO_TRADE","TRADE"};
    if r["decision"]=="NO_TRADE":assert r["selected"]==[]

def test_portfolio_greeks_aggregate():
    g=portfolio_greeks([candidate(),candidate(index="BANKNIFTY")]);assert round(g["delta"],4)==.04;assert round(g["theta"],2)==20

def test_stress_governor_exposes_limits_and_stress():
    g=risk_governor(candidate(),[],1_000_000);assert "greeks" in g and "stressLoss" in g and "limits" in g;assert isinstance(g["reasons"],list)

def test_quant_portfolio_returns_auditable_ranked_decisions():
    r=select_quant_portfolio([candidate(),candidate("BULL_PUT_CREDIT_SPREAD",index="BANKNIFTY")]);assert r["engine"]=="INDEX_OPTIONS_QUANT_V2";assert r["model"]=="COMMON_SCENARIO_DISTRIBUTION_REPRICER";assert "ranked" in r and "portfolioRisk" in r
