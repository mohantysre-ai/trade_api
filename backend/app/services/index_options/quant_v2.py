"""Deterministic Quant V2 scenario, structure and portfolio engine."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from math import erf, exp, log, sqrt
from statistics import NormalDist
from typing import Any

QUANT_V2_ENGINE="INDEX_OPTIONS_QUANT_V2"; NO_TRADE="NO_TRADE"; _N=NormalDist()

GREEK_SOFT_LIMIT_START=0.80
GREEK_SOFT_PENALTY_RATE=0.005
GREEK_SOFT_PENALTY_MAX_EV_FRACTION=0.50

GREEK_LIMIT_DELTA_BPS=0.0008
GREEK_LIMIT_GAMMA_BPS=0.00002
GREEK_LIMIT_VEGA_BPS=0.003
STRESS_LIMIT_BPS=0.015

SPOT_SHOCK_PCT=0.03
IV_SHOCK_POINTS=10.0

@dataclass(frozen=True)
class RegimeProbabilities:
    trend_up:float; trend_down:float; range:float; vol_expansion:float; vol_compression:float
    def normalized(self):
        v=[max(0,x) for x in (self.trend_up,self.trend_down,self.range,self.vol_expansion,self.vol_compression)]; s=sum(v) or 1
        return RegimeProbabilities(*(x/s for x in v))

@dataclass(frozen=True)
class Scenario:
    name:str; probability:float; spot_return:float; iv_shift:float

@dataclass(frozen=True)
class QuantDecision:
    strategy_id:str; index:str; utility:float; expected_value:float; cvar95:float; transaction_cost:float; tail_penalty:float; greek_penalty:float; concentration_penalty:float; decision:str; reasons:tuple[str,...]; stress_loss:float=0.0; portfolio_greeks:dict|None=None; greek_utilization:dict|None=None; greek_units:dict|None=None; risk_limits:dict|None=None; risk_shocks:dict|None=None; greek_shock_loss:dict|None=None; utility_before_greek_risk:float|None=None; risk_gate_passed:bool|None=None; risk_rejection_reasons:tuple[str,...]|None=None
    def to_dict(self):
        d=asdict(self)
        for k in ("portfolio_greeks","greek_utilization","greek_units","risk_limits","risk_shocks","greek_shock_loss"):
            if d.get(k) is None: d[k]={}
        if d.get("risk_rejection_reasons") is None: d["risk_rejection_reasons"]=[]
        return d

def _num(v,d=0.0):
    try:
        x=float(v); return x if x==x else d
    except (TypeError,ValueError): return d

def infer_regime_probabilities(c):
    e=c.get("gateEvidence") if isinstance(c.get("gateEvidence"),dict) else {}; b=e.get("breadth") if isinstance(e.get("breadth"),dict) else {}; f=e.get("futuresOi") if isinstance(e.get("futuresOi"),dict) else {}; ve=e.get("volatilityEdge") if isinstance(e.get("volatilityEdge"),dict) else {}; direction=str(c.get("direction") or c.get("bias") or "").upper(); bs=max(-100,min(100,_num(b.get("directionalScore"),_num(b.get("score")))))/100; oi=str(f.get("state") or "").upper(); edge=_num(ve.get("ivEdgePoints")); up=1+max(0,bs)*2; down=1+max(0,-bs)*2
    if direction in {"CALL","BULLISH"}: up+=.8
    if direction in {"PUT","BEARISH"}: down+=.8
    if oi in {"LONG_BUILDUP","SHORT_COVERING"}: up+=.7
    if oi in {"SHORT_BUILDUP","LONG_UNWINDING"}: down+=.7
    return RegimeProbabilities(up,down,1.2+max(0,1-abs(bs)),1+max(0,-edge)*.08,1+max(0,edge)*.08).normalized()

def common_scenarios(c):
    """One shared distribution used by every candidate on an index snapshot."""
    p=infer_regime_probabilities(c); rv=max(.004,_num(c.get("realizedVol"),_num(c.get("atmIv"),15))/100/sqrt(252)); sigma=max(.004,min(.06,rv)); raw=[
      Scenario("CRASH",.025,-3*sigma,+.12),Scenario("DOWN",p.trend_down,-1.25*sigma,+.04),Scenario("RANGE_DOWN",p.range/2,-.35*sigma,-.015),Scenario("FLAT",p.vol_compression,0,-.025),Scenario("RANGE_UP",p.range/2,.35*sigma,-.015),Scenario("UP",p.trend_up,1.25*sigma,+.02),Scenario("MELT_UP",.025,3*sigma,+.06),Scenario("VOL_EXPANSION",p.vol_expansion,0,+.10)]
    s=sum(x.probability for x in raw); return [Scenario(x.name,x.probability/s,x.spot_return,x.iv_shift) for x in raw]

def _bs(spot,strike,t,vol,is_call,r=0.065):
    if spot<=0 or strike<=0:return 0
    if t<=0:return max(0,spot-strike) if is_call else max(0,strike-spot)
    vol=max(.01,vol); d1=(log(spot/strike)+(r+.5*vol*vol)*t)/(vol*sqrt(t)); d2=d1-vol*sqrt(t); nd1=_N.cdf(d1); nd2=_N.cdf(d2); df=exp(-r*t)
    return spot*nd1-strike*df*nd2 if is_call else strike*df*_N.cdf(-d2)-spot*_N.cdf(-d1)

def _leg_entry(leg): return _num(leg.get("entryPrice"),_num(leg.get("ltp"),(_num(leg.get("bestBid"))+_num(leg.get("bestAsk")))/2))
def _strike(leg): return _num(leg.get("strike") or leg.get("strikePrice"))
def _call(leg): return str(leg.get("optionType") or leg.get("type") or leg.get("symbol") or "").upper().endswith("CE") or str(leg.get("optionType") or "").upper() in {"CALL","CE"}
def _sign(leg): return 1 if str(leg.get("side") or leg.get("action") or "BUY").upper()=="BUY" else -1

def reprice_structure(c,scenarios=None):
    spot=_num(c.get("spot")); legs=[x for x in c.get("legs") or [] if isinstance(x,dict)]; max_loss=abs(_num(c.get("maxLoss") or (c.get("risk") or {}).get("maxLossPerLot")))
    if not spot or not legs or not max_loss:return {"valid":False,"reason":"DEFINED_LEGS_AND_MAX_LOSS_REQUIRED","ev":-1e9,"cvar95":max_loss,"stressLoss":max_loss,"outcomes":[]}
    scenarios=scenarios or common_scenarios(c); base_iv=max(.01,_num(c.get("atmIv"),15)/100); dte=max(1,int(_num(c.get("dte"),1))); t=max(1/365,dte/365); outcomes=[]
    for sc in scenarios:
        ss=spot*(1+sc.spot_return); iv=max(.01,base_iv+sc.iv_shift); pnl=0
        for leg in legs:
            k=_strike(leg)
            if not k: return {"valid":False,"reason":"LEG_STRIKE_REQUIRED","ev":-1e9,"cvar95":max_loss,"stressLoss":max_loss,"outcomes":[]}
            qty=max(1,int(_num(leg.get("qty"),1)))*max(1,int(_num(leg.get("lotSize"),1))); mark=_bs(ss,k,t,iv,_call(leg),0.065); pnl+=(mark-_leg_entry(leg))*qty*_sign(leg)
        pnl=max(-max_loss,pnl); outcomes.append({"scenario":sc.name,"probability":sc.probability,"pnl":round(pnl,2)})
    ev=sum(x["probability"]*x["pnl"] for x in outcomes); ordered=sorted(outcomes,key=lambda x:x["pnl"]); remaining=.05; tail=0; mass=0
    for x in ordered:
        take=min(remaining,x["probability"]); tail+=x["pnl"]*take; mass+=take; remaining-=take
        if remaining<=1e-9:break
    cvar=max(0,-tail/(mass or .05)); stress=max(0,-min(x["pnl"] for x in outcomes)); return {"valid":True,"ev":ev,"cvar95":cvar,"stressLoss":stress,"outcomes":outcomes}

def portfolio_greeks(rows):
    return {g:sum(_num(r.get(g)) for r in rows) for g in ("delta","gamma","theta","vega")}

def portfolio_stress(rows):
    losses=[]
    for shock,iv in ((-.03,.10),(-.02,.08),(-.01,.05),(.01,.03),(.02,.05),(.03,.08)):
        pnl=0
        for r in rows:
            spot=_num(r.get("spot")); delta=_num(r.get("delta")); gamma=_num(r.get("gamma")); vega=_num(r.get("vega")); move=spot*shock; pnl+=delta*move+.5*gamma*move*move+vega*(iv*100)
        losses.append(pnl)
    return max(0,-min(losses or [0]))

def risk_governor(candidate,portfolio,nav=1_000_000,*,stress_loss=None):
    rows=[*portfolio,candidate]; g=portfolio_greeks(rows)
    if stress_loss is None:
        stress_loss=portfolio_stress(rows)
    limits={"delta":nav*GREEK_LIMIT_DELTA_BPS,"gamma":nav*GREEK_LIMIT_GAMMA_BPS,"vega":nav*GREEK_LIMIT_VEGA_BPS,"stress":nav*STRESS_LIMIT_BPS}
    reasons=[]
    if abs(g["delta"])>limits["delta"]: reasons.append("PORTFOLIO_DELTA_LIMIT")
    if abs(g["gamma"])>limits["gamma"]: reasons.append("PORTFOLIO_GAMMA_LIMIT")
    if abs(g["vega"])>limits["vega"]: reasons.append("PORTFOLIO_VEGA_LIMIT")
    if stress_loss>limits["stress"]: reasons.append("PORTFOLIO_STRESS_LIMIT")
    spot=_num(candidate.get("spot") or (portfolio[0].get("spot") if portfolio else 0))
    spot_shock_points=spot*SPOT_SHOCK_PCT if spot else 0
    greek_shock_loss={
        "delta":abs(g["delta"])*spot_shock_points,
        "gamma":0.5*abs(g["gamma"])*spot_shock_points**2,
        "vega":abs(g["vega"])*IV_SHOCK_POINTS,
        "stress":stress_loss,
    }
    return {"pass":not reasons,"reasons":reasons,"greeks":g,"stressLoss":round(stress_loss,2),"limits":limits,"greekUnits":{"delta":"INR per 1 underlying point","gamma":"INR per 1 underlying point^2","theta":"INR per day","vega":"INR per 1 percentage point IV move"},"riskShocks":{"spot":spot,"spotMovePct":SPOT_SHOCK_PCT,"spotMovePoints":spot_shock_points,"ivMovePoints":IV_SHOCK_POINTS},"greekShockLoss":greek_shock_loss,"scenarioStress":{"stressLoss":round(stress_loss,2),"stressLimit":limits["stress"],"utilization":round(stress_loss/limits["stress"],4) if limits["stress"] else 0}}

def score_candidate(c,*,portfolio=None,scenarios=None,nav=1_000_000):
    sid=str(c.get("strategyId") or c.get("strategyType") or "UNKNOWN"); idx=str(c.get("key") or c.get("index") or "UNKNOWN")
    if not c.get("eligible"): return QuantDecision(sid,idx,-1e9,0,0,0,0,0,0,"REJECT",("UPSTREAM_INELIGIBLE",))
    rp=reprice_structure(c,scenarios)
    if not rp["valid"]: return QuantDecision(sid,idx,-1e9,0,rp["cvar95"],0,rp["cvar95"],0,0,"REJECT",(rp["reason"],),rp["stressLoss"])
    legs=c.get("legs") or []; spread=sum(abs(_num(x.get("spreadPct"))) for x in legs); cost=sum(max(1,int(_num(x.get("qty"),1)))*max(1,int(_num(x.get("lotSize"),1)))*max(.05,_leg_entry(x)*spread*.0005) for x in legs)
    rows=[*(portfolio or []),c]; g=portfolio_greeks(rows); gov=risk_governor(c,portfolio or [],nav,stress_loss=rp["stressLoss"]); limits=gov["limits"]; utilizations={"delta":abs(g["delta"])/limits["delta"] if limits["delta"] else 0,"gamma":abs(g["gamma"])/limits["gamma"] if limits["gamma"] else 0,"vega":abs(g["vega"])/limits["vega"] if limits["vega"] else 0}
    max_util=max(utilizations.values()) if utilizations else 0
    tail=.15*rp["cvar95"]; same=sum(1 for x in portfolio or [] if str(x.get("index") or x.get("key"))==idx); conc=.10*rp["cvar95"]*same
    gp=0.0
    if max_util>GREEK_SOFT_LIMIT_START and rp["ev"]>0:
        excess=max_util-GREEK_SOFT_LIMIT_START
        gp=min(GREEK_SOFT_PENALTY_RATE*rp["ev"]*excess**2, rp["ev"]*GREEK_SOFT_PENALTY_MAX_EV_FRACTION)
    utility=rp["ev"]-cost-tail-gp-conc; reasons=[]
    if utility<=0:reasons.append("NO_TRADE_DOMINATES")
    return QuantDecision(sid,idx,round(utility,2),round(rp["ev"],2),round(rp["cvar95"],2),round(cost,2),round(tail,2),round(gp,2),round(conc,2),"ADMIT" if utility>0 else "REJECT",tuple(reasons),round(rp["stressLoss"],2),portfolio_greeks=g,greek_utilization=utilizations,greek_units=gov.get("greekUnits"),risk_limits=limits,risk_shocks=gov.get("riskShocks"),greek_shock_loss=gov.get("greekShockLoss"),utility_before_greek_risk=round(rp["ev"]-cost-tail-conc,2),risk_gate_passed=gov["pass"],risk_rejection_reasons=tuple(gov["reasons"]))

def select_quant_portfolio(candidates,max_positions=2,nav=1_000_000,max_per_sleeve=None):
    # Group by index so every competing structure sees exactly the same scenario distribution.
    scenarios={};
    for c in candidates:
        idx=str(c.get("key") or c.get("index") or "UNKNOWN")
        if idx not in scenarios: scenarios[idx]=common_scenarios(c)
    ranked=sorted((score_candidate(c,scenarios=scenarios[str(c.get("key") or c.get("index") or "UNKNOWN")],nav=nav) for c in candidates),key=lambda d:d.utility,reverse=True); source={(str(c.get("strategyId") or c.get("strategyType")),str(c.get("key") or c.get("index"))):c for c in candidates}; admitted=[]; admitted_rows=[]; rejected=[]
    def sleeve_for(decision):
        candidate=source.get((decision.strategy_id,decision.index)) or {}
        return str(candidate.get("strategyMode") or "BUY_PREMIUM").upper()
    ordered=ranked
    if max_per_sleeve is not None:
        # Give every eligible sleeve its own admission opportunity before a
        # second position from a stronger sleeve can consume the shared book.
        # Risk/utility gates still decide whether any position is admitted.
        groups={}
        for decision in ranked: groups.setdefault(sleeve_for(decision),[]).append(decision)
        sleeve_order=sorted(groups,key=lambda name:groups[name][0].utility,reverse=True)
        ordered=[]
        for offset in range(max((len(rows) for rows in groups.values()),default=0)):
            ordered.extend(groups[name][offset] for name in sleeve_order if offset<len(groups[name]))
    sleeve_counts={}
    for initial in ordered:
        c=source.get((initial.strategy_id,initial.index));
        if not c or len(admitted)>=max_positions:continue
        sleeve=sleeve_for(initial)
        if max_per_sleeve is not None and sleeve_counts.get(sleeve,0)>=max_per_sleeve:continue
        d=score_candidate(c,portfolio=admitted_rows,scenarios=scenarios[initial.index],nav=nav)
        if d.utility<=0: rejected.append(d.to_dict()); continue
        gov=risk_governor(c,admitted_rows,nav,stress_loss=d.stress_loss)
        if not gov["pass"]:
            x=d.to_dict(); x["decision"]="REJECT"; x["reasons"]=gov["reasons"]; x["portfolioRisk"]=gov; rejected.append(x); continue
        admitted.append(d); admitted_rows.append(c); sleeve_counts[sleeve]=sleeve_counts.get(sleeve,0)+1
    portfolio_stress_val=sum((x.stress_loss or 0) for x in admitted) if admitted_rows else 0
    return {"engine":QUANT_V2_ENGINE,"model":"COMMON_SCENARIO_DISTRIBUTION_REPRICER","noTradeUtility":0.0,"selected":[x.to_dict() for x in admitted],"rejected":rejected,"ranked":[x.to_dict() for x in ranked],"portfolioRisk":risk_governor({},admitted_rows,nav,stress_loss=portfolio_stress_val) if admitted_rows else {"pass":True,"greeks":portfolio_greeks([]),"stressLoss":0,"greekUnits":{"delta":"INR per 1 underlying point","gamma":"INR per 1 underlying point^2","theta":"INR per day","vega":"INR per 1 percentage point IV move"},"riskShocks":{"spot":0,"spotMovePct":SPOT_SHOCK_PCT,"spotMovePoints":0,"ivMovePoints":IV_SHOCK_POINTS},"greekShockLoss":{"delta":0,"gamma":0,"vega":0,"stress":0},"scenarioStress":{"stressLoss":0,"stressLimit":0,"utilization":0}},"decision":"TRADE" if admitted else NO_TRADE}
