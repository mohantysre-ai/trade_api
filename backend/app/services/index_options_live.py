"""Live radar compose: Angel → ScanX → Lemonn, plus session replay routing."""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Callable

from .angel_index_options import IST_ZONE, _apply_oi_baselines, _effective_breadth_gate, active_index_expiries, cached_angel_index_option_snapshot, option_data_to_strategy_inputs, persist_radar, unavailable_provider_snapshot
from .angel_one_feed import ensure_fresh_market_snapshot
from .angel_index_stream import ANGEL_INDEX_STREAM
from .dhan_scanx_options import apply_scanx_fallback
from .index_options_engine import build_index_options_radar
from .index_options_paper import index_options_market_open, reconcile_paper_book
from .index_options_replay import parse_session_date, replay_index_options_session
from .lemonn_options import LEMONN_SLUGS, apply_lemonn_fallback, discover_lemonn_expiries
from .market_data_provider import fetch_nse_option_chain
from .trendlyne_oi import apply_oi_enrichment


def _float(value: Any) -> float | None:
    try: number=float(value)
    except (TypeError,ValueError): return None
    return number if math.isfinite(number) else None


def _live_structural_levels(row: dict[str, Any]) -> tuple[float | None,float | None,float | None]:
    direction=str(row.get("direction") or "").upper(); structure=row.get("structure") if isinstance(row.get("structure"),dict) else {}; spot=_float(row.get("spot")); structure_entry=_float(structure.get("last")); ema9=_float(structure.get("ema9")); orb_high=_float(structure.get("orbHigh")); orb_low=_float(structure.get("orbLow")); atr=_float(structure.get("atr5m"))
    if direction not in {"CALL","PUT"} or not spot or not structure_entry or not ema9 or not orb_high or not orb_low or not atr: return None,None,None
    opening_range=orb_high-orb_low
    if opening_range<=0: return None,None,None
    if direction=="CALL":
        stops=[x for x in (orb_high,ema9) if x<structure_entry]; stop=max(stops) if stops else None; target=min((x for x in (orb_high+opening_range,spot+atr) if x>spot),default=None)
    else:
        stops=[x for x in (orb_low,ema9) if x>structure_entry]; stop=min(stops) if stops else None; target=max((x for x in (orb_low-opening_range,spot-atr) if x<spot),default=None)
    return stop,target,opening_range


def _refresh_live_breadth_confirmation(row: dict[str, Any], expected_r: float) -> None:
    direction=str(row.get("direction") or "").upper(); evidence=row.get("gateEvidence") if isinstance(row.get("gateEvidence"),dict) else {}; breadth=evidence.get("breadth") if isinstance(evidence.get("breadth"),dict) else row.get("breadth"); futures=evidence.get("futuresOi") if isinstance(evidence.get("futuresOi"),dict) else {}; chain=evidence.get("optionChain") if isinstance(evidence.get("optionChain"),dict) else {}; economics=evidence.get("contractEconomics") if isinstance(evidence.get("contractEconomics"),dict) else {}
    if not isinstance(breadth,dict) or direction not in {"CALL","PUT"}: return
    oi_state=str(futures.get("state") or "").upper(); strong_oi=(direction=="CALL" and oi_state=="LONG_BUILDUP") or (direction=="PUT" and oi_state=="SHORT_BUILDUP")
    refreshed=_effective_breadth_gate({**breadth,"aligned":breadth.get("strictAligned")},strong_oi=strong_oi,chain_aligned=chain.get("aligned"),expected_r=expected_r,spread_pct=_float(economics.get("spreadPct")),vix_regime=str(row.get("vixRegime") or "").upper() or None)
    row["breadth"]=refreshed; evidence["breadth"]=refreshed; row.setdefault("gates",{})["breadth"]=refreshed.get("aligned")


def _refresh_seller_tail_buffer(row: dict[str, Any], spot: float) -> None:
    seller=row.get("seller") if isinstance(row.get("seller"),dict) else None
    if not seller: return
    risk=seller.get("risk") if isinstance(seller.get("risk"),dict) else {}; structure=row.get("structure") if isinstance(row.get("structure"),dict) else {}; atr=_float(structure.get("atr5m"))
    if not atr or atr<=0: return
    lower,upper=_float(risk.get("shortPutStrike")),_float(risk.get("shortCallStrike")); buffers=[x for x in ((spot-lower) if lower is not None else None,(upper-spot) if upper is not None else None) if x is not None]
    if not buffers: return
    minimum=min(buffers)/atr; required=1.0 if seller.get("strategyType")=="IRON_CONDOR" else .75; aligned=minimum>=required
    seller.setdefault("gates",{})["tailBuffer"]=aligned; seller.setdefault("gateEvidence",{})["tailBuffer"]={"aligned":aligned,"minimumBufferAtr":round(minimum,3),"minimum":required,"basis":"LIVE_STREAMED_SPOT"}; risk["minimumBufferAtr"]=round(minimum,3)


def _apply_live_spot_risk_guard(strategy_inputs: dict[str, Any]) -> dict[str, Any]:
    indices=strategy_inputs.get("indices") if isinstance(strategy_inputs.get("indices"),dict) else {}
    for row in indices.values():
        if not isinstance(row,dict): continue
        direction=str(row.get("direction") or "").upper(); spot=_float(row.get("spot"));
        if spot: _refresh_seller_tail_buffer(row,spot)
        contract=row.get("contract") if isinstance(row.get("contract"),dict) else None; structure=row.get("structure") if isinstance(row.get("structure"),dict) else {}
        if direction not in {"CALL","PUT"} or not spot or not contract: continue
        stop,target,opening_range=_live_structural_levels(row); atr=_float(structure.get("atr5m")); premium=_float(contract.get("ltp")); delta=abs(_float(contract.get("delta")) or 0); gamma=abs(_float(contract.get("gamma")) or 0); gate_evidence=row.setdefault("gateEvidence",{}); economics=gate_evidence.get("contractEconomics") if isinstance(gate_evidence.get("contractEconomics"),dict) else {}; spread_pct=max(0,_float(economics.get("spreadPct")) or 0); gates=row.setdefault("gates",{}); limitations=row.setdefault("dataLimitations",[])
        invalidated=bool(stop is not None and ((direction=="CALL" and spot<=stop) or (direction=="PUT" and spot>=stop)))
        if invalidated:
            gates["structure"]=gates["breakout"]=gates["riskReward"]=False; row["expectedR"]=0.0
            if "LIVE_SPOT_CROSSED_STRUCTURAL_STOP" not in limitations: limitations.append("LIVE_SPOT_CROSSED_STRUCTURAL_STOP")
            continue
        if stop is None or target is None or not atr or not premium or delta<=0 or not opening_range: continue
        structural_risk=abs(spot-stop); atr_floor=atr*.20; spread_cost=premium*spread_pct/100; spread_underlying=spread_cost/delta if spread_cost>0 else 0; risk_move=max(structural_risk,atr_floor,spread_underlying); reward_move=abs(target-spot); option_loss=max(delta*risk_move-.5*gamma*risk_move*risk_move+spread_cost,spread_cost,.05); option_gain=max(delta*reward_move+.5*gamma*reward_move*reward_move-spread_cost,0); expected_r=round(option_gain/option_loss,3) if option_loss>0 else 0
        row["expectedR"]=expected_r; gates["riskReward"]=expected_r>=1.5; gate_evidence["riskReward"]={"expectedR":expected_r,"aligned":expected_r>=1.5,"minimumR":1.5,"basis":"LIVE_SPOT_ORB_INVALIDATION_WITH_ATR_SPREAD_RISK_FLOOR","entryUnderlying":round(spot,4),"stop":round(stop,4),"target":round(target,4)}; _refresh_live_breadth_confirmation(row,expected_r)
    return strategy_inputs


def _strategy_projection(strategy_book: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(strategy_book,dict): return []
    rows=[]
    for p in strategy_book.get("positions") or []:
        if p.get("authority")!="INDEX_OPTIONS_QUANT_V2": continue
        legs=p.get("legs") or []; quantity=sum(int(l.get("lotSize") or 0) for l in legs[:1]) or 1
        rows.append({"id":p.get("strategyPositionId"),"strategyPositionId":p.get("strategyPositionId"),"index":p.get("index"),"symbol":p.get("strategyId"),"direction":"QUANT_V2","quantity":quantity,"status":p.get("status"),"strategyMode":"QUANT_V2","strategyType":p.get("strategyId"),"entryCredit":p.get("entryCredit"),"currentDebit":abs(_float(p.get("combinedStructureValue")) or 0),"maxLossPerLot":p.get("maxLoss"),"unrealizedPnl":p.get("unrealizedPnl"),"pnl":p.get("realizedPnl"),"exitReason":p.get("exitReason"),"enteredAt":p.get("enteredAt"),"markedAt":p.get("updatedAt"),"markStatus":p.get("markStatus"),"markSource":"INDEX_OPTIONS_QUANT_V2","projectionOnly":True})
    return rows


def _merge_strategy_projection(paper_book: dict[str, Any], strategy_book: dict[str, Any] | None) -> dict[str, Any]:
    from .index_options.accounting import merge_paper_books

    return merge_paper_books(paper_book, strategy_book)


def update_locked_position_prices(positions: list[dict[str, Any]]) -> None:
    """Update live prices for locked positions using NSE public API.

    This is called during market hours to keep MTM fresh without
    hammering the Angel One API.
    """
    for position in positions:
        if position.get("status") != "OPEN":
            continue
        index_key = str(position.get("index") or position.get("symbol") or "").upper()
        if index_key not in LEMONN_SLUGS:
            continue
        expiry_raw = position.get("expiry") or position.get("expiryDate")
        if not expiry_raw:
            continue
        try:
            expiry = date.fromisoformat(str(expiry_raw))
        except (TypeError, ValueError):
            continue
        try:
            result = fetch_nse_option_chain(index_key, expiry)
        except Exception:
            continue
        chain = result.get("chain") or []
        if not chain:
            continue
        _apply_nse_chain_to_position(position, result)


def _apply_nse_chain_to_position(position: dict[str, Any], nse_result: dict[str, Any]) -> None:
    """Apply NSE option-chain prices to a locked position's legs."""
    legs = position.get("legs") or []
    chain = nse_result.get("chain") or []
    if not legs or not chain:
        return
    lookup = {
        (round(float(leg.get("strike") or 0), 2), str(leg.get("optionType") or "").upper()): leg
        for leg in legs if isinstance(leg, dict)
    }
    updated = 0
    for row in chain:
        if not isinstance(row, dict):
            continue
        key = (round(float(row.get("strike") or 0), 2), str(row.get("optionType") or "").upper())
        if key not in lookup:
            continue
        leg = lookup[key]
        ltp = row.get("ltp")
        if ltp is not None:
            leg["currentPrice"] = float(ltp)
            leg["priceSource"] = "NSE"
            updated += 1
    if updated:
        position["markSource"] = "NSE"
        position["markedAt"] = datetime.now(timezone.utc).isoformat()


def compose_live_index_options_radar(snapshot: dict[str,Any],*,live:bool=True,client:Any,persist:bool=True,scanx_fn:Callable[...,dict[str,Any]]=apply_scanx_fallback,lemonn_fn:Callable[...,dict[str,Any]]=apply_lemonn_fallback,lemonn_discover_fn:Callable[...,dict[str,date]]=discover_lemonn_expiries,oi_enrichment_fn:Callable[...,dict[str,Any]]=apply_oi_enrichment,expiries_fn:Callable[...,dict[str,date]]=active_index_expiries,snapshot_fn:Callable[...,dict[str,Any]]=cached_angel_index_option_snapshot,now:datetime|None=None)->dict[str,Any]:
    book=ensure_fresh_market_snapshot(snapshot,reason="index_options_breadth"); option_data=None
    if live:
        try: option_data=snapshot_fn(client)
        except Exception as exc: option_data=unavailable_provider_snapshot(exc)
        expiries={}
        try: expiries.update(expiries_fn())
        except Exception as exc: option_data["fallbackSource"]="SCANX"; option_data["expiryMasterError"]=str(exc)
        missing=[k for k in LEMONN_SLUGS if k not in expiries]
        if missing:
            try: expiries.update(lemonn_discover_fn(missing))
            except Exception: pass
        try: option_data=scanx_fn(option_data,expiries)
        except Exception as exc: option_data["fallbackSource"]="SCANX"; option_data["fallbackError"]=str(exc)
        try: option_data=lemonn_fn(option_data,expiries)
        except Exception as exc: option_data["thirdFallbackSource"]="LEMONN"; option_data["thirdFallbackError"]=str(exc)
        try: option_data=oi_enrichment_fn(option_data,expiries)
        except Exception as exc: option_data["oiEnrichment"]={"source":"SIGQ_RESEARCH","status":"UNAVAILABLE","error":str(exc)}
        option_data=_apply_oi_baselines(option_data); strategy_inputs=option_data_to_strategy_inputs(option_data,book); book["indexOptions"]=_apply_live_spot_risk_guard(strategy_inputs); book["indexOptionProvider"]=option_data
    result=build_index_options_radar(book)
    from .index_options.radar_builder import build_index_options_radar_v2
    from .index_options.runtime import process_strategy_cycle, strategy_book
    modular=build_index_options_radar_v2(book)
    result["modularCandidates"]=modular.get("candidates",[])+modular.get("sellerCandidates",[]); result["modularSelected"]=modular.get("selected",[]); result["quantDecision"]=modular.get("quantDecision"); result["quantEngine"]="INDEX_OPTIONS_QUANT_V2"; result["selectionAuthority"]="INDEX_OPTIONS_QUANT_V2"
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    result["sessionDate"] = clock.date().isoformat()
    result["strategyBook"] = process_strategy_cycle(result, book, clock) if persist else strategy_book(result["sessionDate"])
    market_open=index_options_market_open(now); paper=reconcile_paper_book(result,client=client,persist=persist,now=now); result["paperBook"]=_merge_strategy_projection(paper,result.get("strategyBook")); result["sessionStatus"]="OPEN" if market_open else "CLOSED"; result["huntActive"]=market_open; result["limits"]["huntMode"]="CONTINUOUS_MARKET_SESSION" if market_open else "SESSION_CLOSED"; result["limits"]["selectionAuthority"]="INDEX_OPTIONS_QUANT_V2"; result["provider"]="ANGEL_ONE_WITH_SCANX_AND_LEMONN_FALLBACK"; result["providerEvidence"]=book.get("indexOptionProvider"); result["streamStatus"]=ANGEL_INDEX_STREAM.status()
    if persist: persist_radar(result)
    return result


def hydrate_durable_index_options_radar(radar: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    from .index_options.runtime import strategy_book
    from .index_options_paper import _load_book

    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    day = clock.date().isoformat()
    result = dict(radar)
    result["sessionDate"] = day
    result["strategyBook"] = strategy_book(day)
    result["paperBook"] = _merge_strategy_projection(_load_book(day), result["strategyBook"])
    result["sessionStatus"] = "OPEN" if index_options_market_open(clock) else "CLOSED"
    return result


def finalize_closed_index_options_radar(radar:dict[str,Any],*,client:Any,persist:bool=True,now:datetime|None=None)->dict[str,Any]:
    result = hydrate_durable_index_options_radar(radar, now=now)
    result["huntActive"] = False
    result["limits"] = {**(result.get("limits") or {}), "huntMode": "SESSION_CLOSED", "selectionAuthority": "INDEX_OPTIONS_QUANT_V2"}
    result["cacheStatus"] = "SESSION_FROZEN"
    if persist: persist_radar(result)
    return result


def load_historical_execution(session_date: date) -> dict[str, Any]:
    """Load actual executed trades from the durable Quant V2 ledger.

    Falls back to the EOD book cache when the live DB is empty so that
    historical screens remain authoritative across restarts.
    """
    from .index_options.runtime import strategy_eod
    from .eod_book_cache import load_book_cache

    day = session_date.isoformat()
    book = strategy_eod(day)
    positions = [p for p in book.get("positions") or [] if isinstance(p, dict)]

    if not positions:
        cached = load_book_cache(session_date, "index_options")
        if cached:
            strategy_attribution = cached.get("strategyAttribution") or {}
            positions = [p for p in strategy_attribution.get("positions") or [] if isinstance(p, dict)]
            if positions:
                book = strategy_attribution

    return {
        "sessionDate": day,
        "authority": "INDEX_OPTIONS_QUANT_V2",
        "positions": positions,
        "open": [p for p in positions if str(p.get("status") or "").upper() == "OPEN"],
        "closed": [p for p in positions if str(p.get("status") or "").upper() == "CLOSED"],
    }


def replay_session_payload(client:Any,raw_session_date:str,*,today:date|None=None,persist:bool=True,master:list[dict[str,Any]]|None=None)->dict[str,Any]:
    replay_day=parse_session_date(raw_session_date,today=today)
    try: return replay_index_options_session(client,replay_day,persist=persist,master=master)
    except Exception as exc: return {"success":False,"mode":"SESSION_REPLAY","sessionDate":replay_day.isoformat(),"executionPolicy":"MANUAL_ONLY","candidates":[],"selected":[],"buySideContracts":[],"implemented":[],"error":str(exc)}
def _durable_quant_decision(positions: list[dict[str, Any]]) -> dict[str, Any]:
    rows=[]
    for p in positions:
        realized=_float(p.get("realizedPnl")) or 0.0; unrealized=_float(p.get("unrealizedPnl")) or 0.0; pnl=realized+unrealized; max_loss=_float(p.get("maxLoss")); is_open=str(p.get("status") or "").upper()=="OPEN"
        rows.append({"strategy_id":p.get("strategyId"),"index":p.get("index"),"utility":round(pnl,4),"expected_value":round(pnl,4),"cvar95":round(max_loss,4) if max_loss is not None else None,"stress_loss":round(max_loss,4) if max_loss is not None else None,"transaction_cost":0.0,"decision":"ADMIT","reasons":[str(p.get("status") or ""),("OPEN" if is_open else str(p.get("exitReason") or "CLOSED"))]})
    return {"engine":"INDEX_OPTIONS_QUANT_V2","model":"DURABLE_PAPER_BOOK","decision":"ADMIT" if rows else "NO_TRADE","noTradeUtility":0.0,"selected":rows,"ranked":rows,"rejected":[]}


def attach_durable_session_book(payload: dict[str, Any], session_date: date) -> dict[str, Any]:
    """Merge the durable Quant V2 paper book into a closed-session replay payload."""
    from .index_options_paper import _load_book
    from .index_options.runtime import load_decision_audit

    strategy_book = load_historical_execution(session_date)
    positions = strategy_book["positions"]
    result = dict(payload if isinstance(payload, dict) else {})
    result["sessionDate"] = strategy_book["sessionDate"]
    result["sessionStatus"] = "CLOSED"
    result["huntActive"] = False
    result["strategyBook"] = strategy_book
    result["paperBook"] = _merge_strategy_projection(_load_book(strategy_book["sessionDate"]), strategy_book)
    result["quantEngine"] = "INDEX_OPTIONS_QUANT_V2"
    result["selectionAuthority"] = "INDEX_OPTIONS_QUANT_V2"
    result["quantDecision"] = _durable_quant_decision(positions)
    result["limits"] = {**(result.get("limits") or {}), "selectionAuthority": "INDEX_OPTIONS_QUANT_V2", "huntMode": "SESSION_CLOSED"}

    replay_limitations = [str(item) for item in (result.get("limitations") or [])]
    result["historicalExecution"] = {
        "authority": "INDEX_OPTIONS_QUANT_V2_DURABLE_LEDGER",
        "source": "shared_state.db" if positions else "eod_book_cache",
        "entryCount": len(positions),
        "openCount": len(strategy_book["open"]),
        "closedCount": len(strategy_book["closed"]),
    }
    result["replayDiagnostics"] = {
        "mode": result.get("mode", "SESSION_REPLAY"),
        "limitations": replay_limitations,
        "indices": result.get("indices", []),
        "implemented": result.get("implemented", []),
        "buySideContracts": result.get("buySideContracts", []),
    }

    day = session_date.isoformat()
    decision_audit = load_decision_audit(day)
    result["qualificationHistoryAvailable"] = bool(decision_audit.get("audits"))
    result["qualificationLimitations"] = replay_limitations
    result["historicalQualification"] = {
        "evaluatedCount": decision_audit.get("evaluatedCount", 0),
        "eligibleCount": decision_audit.get("eligibleCount", 0),
        "qualifiedCount": decision_audit.get("qualifiedCount", 0),
        "selectedCount": decision_audit.get("selectedCount", 0),
        "executedCount": decision_audit.get("executedCount", 0),
        "rejectedCount": decision_audit.get("rejectedCount", 0),
        "entryBlockedCount": decision_audit.get("entryBlockedCount", 0),
        "rejectionSummary": decision_audit.get("rejectionSummary", {}),
    }
    result["candidateHistory"] = decision_audit.get("audits", [])
    return result
