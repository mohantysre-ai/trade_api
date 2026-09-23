"""Quant V2 radar: construct legal structures, then let one portfolio engine select."""
from __future__ import annotations
from typing import Any
from .context import IndexOptionContext
from .strategy_registry import get_registered_strategies,is_strategy_enabled
from .quant_v2 import select_quant_portfolio
from ..index_options_engine import (
    INDEX_CONFIG,
    MAX_CONCURRENT_PER_SLEEVE,
    MAX_CONCURRENT_TRADES,
    MAX_DAILY_ENTRIES,
)

def _num(v):
    try:
        n=float(v); return n if n==n else None
    except (TypeError,ValueError): return None

def _build_context(index,snapshot):
    s=((snapshot.get("indexOptions") or {}).get("indices") or {}).get(index["key"],{}); spot=_num(s.get("spot"))
    if spot is None:return None
    scores=s.get("scores") if isinstance(s.get("scores"),dict) else {}; structure=s.get("structure") if isinstance(s.get("structure"),dict) else {}; breadth=s.get("breadth") if isinstance(s.get("breadth"),dict) else {}; oi=s.get("futuresOi") if isinstance(s.get("futuresOi"),dict) else {}; now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    return IndexOptionContext(index=index["key"],spot=spot,futures_price=None,direction=str(s.get("direction") or "").upper() or None,direction_score=_num(scores.get("regime")),trend_score=_num(scores.get("trend")),breakout_score=_num(scores.get("breakout")),breadth_score=_num(breadth.get("score")),breadth_coverage=_num(breadth.get("coveragePct")),breadth_directional_score=_num(breadth.get("directionalScore")),futures_oi_state=str(oi.get("state") or "").upper() or None,futures_oi_aligned=oi.get("aligned"),realized_vol=_num(s.get("realizedVol")),atm_iv=_num(s.get("atmIv")),iv_rank=_num(s.get("ivRank")),iv_percentile=_num(s.get("ivPercentile")),skew=_num(s.get("skew")),term_structure=_num(s.get("termStructure")),expected_move=_num(s.get("expectedMove")),chain=s.get("rawChain") or [],expiry=str(s.get("expiry")) if s.get("expiry") else None,session_time=now,structure=structure,breadth=breadth,futures_oi=oi,gate_evidence=s.get("gateEvidence") or {},data_limitations=s.get("dataLimitations") or [],provider_status=s.get("providerStatus"),data_source=s.get("source"),component_freshness=s.get("componentFreshness") or {},raw_snapshot=s,full_snapshot=snapshot,snapshot_id=str(snapshot.get("snapshotId") or snapshot.get("updatedAt") or ""),decision_timestamp=str(snapshot.get("updatedAt") or now.isoformat()),market_generation=str(snapshot.get("marketGeneration") or ""),put_skew=_num(s.get("putSkew")),call_skew=_num(s.get("callSkew")),dte=int(s["dte"]) if s.get("dte") is not None else None,far_expiry=str(s.get("farExpiry")) if s.get("farExpiry") else None,far_chain=s.get("farChain") if isinstance(s.get("farChain"),list) else [],expiry_state=str(s.get("expiryState") or "NORMAL_EXPIRY_SESSION"))

def _row(result,index,context):
    is_seller=result.family=="VOLATILITY_COMPRESSION"; x={**index,"spot":context.spot,"realizedVol":context.realized_vol,"atmIv":context.atm_iv,"dte":context.dte,"direction":(result.bias or "").upper() or context.direction,"state":result.state,"reason":result.reason,"score":result.strategy_score,"strategyMode":"SELL_PREMIUM" if is_seller else "BUY_PREMIUM","strategyType":result.strategy_id,"strategyId":result.strategy_id,"family":result.family,"bias":result.bias,"eligible":result.eligible,"expiry":result.expiry,"dataLimitations":result.reason_codes,"gateEvidence":context.gate_evidence,"entryDebit":result.entry_debit,"entryCredit":result.entry_credit,"maxProfit":result.max_profit,"maxLoss":result.max_loss,"breakevens":result.breakevens,"rewardRisk":result.reward_risk,"delta":result.delta,"gamma":result.gamma,"theta":result.theta,"vega":result.vega,"margin":result.margin,"liquidityScore":result.liquidity_score,"executionScore":result.execution_score,"snapshotId":context.snapshot_id,"decisionTimestamp":context.decision_timestamp,"marketGeneration":context.market_generation,"farExpiry":context.far_expiry,"expiryState":context.expiry_state,"legs":result.legs,"risk":result.extra.get("risk",{}),"gates":result.extra.get("gates",{}),"componentFreshness":context.component_freshness,"providerStatus":context.provider_status,"dataSource":context.data_source}
    if not x["legs"] and result.extra.get("contract"): x["legs"]=[{**result.extra["contract"],"side":"BUY","qty":1,"expiry":result.expiry}]
    return x

def build_index_options_radar_v2(snapshot):
    payload=snapshot if isinstance(snapshot,dict) else {}; candidates=[]
    # V2 no longer preselects by V1 regime. Every enabled legal structure is built;
    # the common-distribution optimizer decides among them and NO_TRADE.
    for index in INDEX_CONFIG:
        ctx=_build_context(index,payload)
        if ctx is None:continue
        for sid,strategy in get_registered_strategies().items():
            if not is_strategy_enabled(sid):continue
            try:
                if not strategy.eligible(ctx):continue
                candidates.append(_row(strategy.build(ctx),index,ctx))
            except Exception:continue
    quant=select_quant_portfolio(
        candidates,
        max_positions=MAX_CONCURRENT_TRADES,
        max_per_sleeve=MAX_CONCURRENT_PER_SLEEVE,
    )
    keys={(x["strategy_id"],x["index"]) for x in quant["selected"]}; selected=[c for c in candidates if (str(c.get("strategyId")),str(c.get("key"))) in keys]
    for c in selected:c["quantAuthority"]="INDEX_OPTIONS_QUANT_V2"
    return {"success":True,"executionPolicy":"AUTO_PAPER_ONLY","strategy":"QUANT_V2_COMMON_DISTRIBUTION_PORTFOLIO","updatedAt":payload.get("updatedAt"),"candidates":[c for c in candidates if c.get("strategyMode")!="SELL_PREMIUM"],"sellerCandidates":[c for c in candidates if c.get("strategyMode")=="SELL_PREMIUM"],"selected":selected,"buySelected":[c for c in selected if c.get("strategyMode")!="SELL_PREMIUM"],"sellSelected":[c for c in selected if c.get("strategyMode")=="SELL_PREMIUM"],"quantDecision":quant,"limits":{"minDailyEntries":0,"maxDailyEntries":MAX_DAILY_ENTRIES,"maxConcurrent":MAX_CONCURRENT_TRADES,"maxConcurrentPerSleeve":MAX_CONCURRENT_PER_SLEEVE,"selectionAuthority":"INDEX_OPTIONS_QUANT_V2","noTradeUtility":0.0}}
