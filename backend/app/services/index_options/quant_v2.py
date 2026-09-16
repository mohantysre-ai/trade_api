"""Deterministic Quant V2 scenario, structure and portfolio engine."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from math import erf, exp, log, sqrt
from statistics import NormalDist
from typing import Any

QUANT_V2_ENGINE="INDEX_OPTIONS_QUANT_V2"; NO_TRADE="NO_TRADE"; _N=NormalDist()

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
    strategy_id:str; index:str; utility:float; expected_value:float; cvar95:float; transaction_cost:float; tail_penalty:float; greek_penalty:float; concentration_penalty:float; decision:str; reasons:tuple[str,...]; stress_loss:float=0.0
    def to_dict(self): return asdict(self)

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

def _bs(spot,strike,t,vol,is_call):
    if spot<=0 or strike<=0:return 0
    if t<=0:return max(0,spot-strike) if is_call else max(0,strike-spot)
    vol=max(.01,vol); d1=(log(spot/strike)+.5*vol*vol*t)/(vol*sqrt(t)); d2=d1-vol*sqrt(t); nd1=_N.cdf(d1); nd2=_N.cdf(d2)
    return spot*nd1-strike*nd2 if is_call else strike*_N.cdf(-d2)-spot*_N.cdf(-d1)

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
            qty=max(1,int(_num(leg.get("qty"),1)))*max(1,int(_num(leg.get("lotSize"),1))); mark=_bs(ss,k,t,iv,_call(leg)); pnl+=(mark-_leg_entry(leg))*qty*_sign(leg)
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

def risk_governor(candidate,portfolio,nav=1_000_000):
    rows=[*portfolio,candidate]; g=portfolio_greeks(rows); stress=portfolio_stress(rows); limits={"delta":nav*.0008,"gamma":nav*.00002,"vega":nav*.003,"stress":nav*.015}; reasons=[]
    if abs(g["delta"])>limits["delta"]: reasons.append("PORTFOLIO_DELTA_LIMIT")
    if abs(g["gamma"])>limits["gamma"]: reasons.append("PORTFOLIO_GAMMA_LIMIT")
    if abs(g["vega"])>limits["vega"]: reasons.append("PORTFOLIO_VEGA_LIMIT")
    if stress>limits["stress"]: reasons.append("PORTFOLIO_STRESS_LIMIT")
    return {"pass":not reasons,"reasons":reasons,"greeks":g,"stressLoss":round(stress,2),"limits":limits}

def score_candidate(c,*,portfolio=None,scenarios=None):
    sid=str(c.get("strategyId") or c.get("strategyType") or "UNKNOWN"); idx=str(c.get("key") or c.get("index") or "UNKNOWN")
    if not c.get("eligible"): return QuantDecision(sid,idx,-1e9,0,0,0,0,0,0,"REJECT",("UPSTREAM_INELIGIBLE",))
    rp=reprice_structure(c,scenarios)
    if not rp["valid"]: return QuantDecision(sid,idx,-1e9,0,rp["cvar95"],0,rp["cvar95"],0,0,"REJECT",(rp["reason"],),rp["stressLoss"])
    legs=c.get("legs") or []; spread=sum(abs(_num(x.get("spreadPct"))) for x in legs); cost=sum(max(1,int(_num(x.get("qty"),1)))*max(1,int(_num(x.get("lotSize"),1)))*max(.05,_leg_entry(x)*spread*.0005) for x in legs); gp=.02*rp["cvar95"]*(abs(_num(c.get("delta")))+5*abs(_num(c.get("gamma")))+.1*abs(_num(c.get("vega")))); tail=.15*rp["cvar95"]; same=sum(1 for x in portfolio or [] if str(x.get("index") or x.get("key"))==idx); conc=.10*rp["cvar95"]*same; utility=rp["ev"]-cost-tail-gp-conc; reasons=[]
    if utility<=0:reasons.append("NO_TRADE_DOMINATES")
    return QuantDecision(sid,idx,round(utility,2),round(rp["ev"],2),round(rp["cvar95"],2),round(cost,2),round(tail,2),round(gp,2),round(conc,2),"ADMIT" if utility>0 else "REJECT",tuple(reasons),round(rp["stressLoss"],2))

def select_quant_portfolio(candidates,max_positions=2,nav=1_000_000):
    # Group by index so every competing structure sees exactly the same scenario distribution.
    scenarios={};
    for c in candidates:
        idx=str(c.get("key") or c.get("index") or "UNKNOWN")
        if idx not in scenarios: scenarios[idx]=common_scenarios(c)
    ranked=sorted((score_candidate(c,scenarios=scenarios[str(c.get("key") or c.get("index") or "UNKNOWN")]) for c in candidates),key=lambda d:d.utility,reverse=True); source={(str(c.get("strategyId") or c.get("strategyType")),str(c.get("key") or c.get("index"))):c for c in candidates}; admitted=[]; admitted_rows=[]; rejected=[]
    for initial in ranked:
        c=source.get((initial.strategy_id,initial.index));
        if not c or len(admitted)>=max_positions:continue
        d=score_candidate(c,portfolio=admitted_rows,scenarios=scenarios[initial.index])
        if d.utility<=0: rejected.append(d.to_dict()); continue
        gov=risk_governor(c,admitted_rows,nav)
        if not gov["pass"]:
            x=d.to_dict(); x["decision"]="REJECT"; x["reasons"]=gov["reasons"]; x["portfolioRisk"]=gov; rejected.append(x); continue
        admitted.append(d); admitted_rows.append(c)
    return {"engine":QUANT_V2_ENGINE,"model":"COMMON_SCENARIO_DISTRIBUTION_REPRICER","noTradeUtility":0.0,"selected":[x.to_dict() for x in admitted],"rejected":rejected,"ranked":[x.to_dict() for x in ranked],"portfolioRisk":risk_governor({},admitted_rows,nav) if admitted_rows else {"pass":True,"greeks":portfolio_greeks([]),"stressLoss":0},"decision":"TRADE" if admitted else NO_TRADE}
