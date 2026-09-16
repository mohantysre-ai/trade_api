"""Single-writer orchestration for the paper-authoritative Swing V2 book.

The service deliberately never sends a broker order. It turns the immutable
V2 ledger into the compatibility session consumed by the existing dashboard
and EOD routes.
"""
from __future__ import annotations
import json, os, copy, threading, time as monotonic_time
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from .calendar import session_age, time_exit_due
from .config import SwingV2Config, load_config
from .engine import execute_paper_order, process_position_bar
from .facade import build_from_market_snapshot
from .ledger import SwingLedger, materialize_position
from .reporting import ledger_eod_report
IST=ZoneInfo("Asia/Kolkata"); _LOCK=threading.RLock(); _DATA_REFRESH_LOCK=threading.Lock()
_FINAL_REFRESH_MARGIN_SECONDS=int(os.getenv("SWING_FINAL_REFRESH_MARGIN_SECONDS","90")); _SESSION_READ_CACHE=None; _SESSION_READ_CACHE_AT=0.0; _SESSION_READ_TTL=float(os.getenv("SWING_SESSION_READ_TTL","2")); _EOD_READ_CACHE={}; _SWING_SCAN_INTERVAL_SECONDS=float(os.getenv("SWING_SCAN_INTERVAL_SECONDS","15"))
_RETRYABLE_FINAL_BLOCK_REASONS={"FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW","UNIVERSE_COVERAGE_BELOW_99PCT","UNIVERSE_COVERAGE_BELOW_90PCT","REGIME_UNRATED","SWING_V2_DATA_NOT_READY"}
def is_v2_authoritative(config=None): return (config or load_config()).paper_authoritative
def _state_path():
 p=os.getenv("SWING_V2_SESSION_FILE","").strip(); return Path(p) if p else Path(__file__).resolve().parents[2]/"data"/"swing_v2_session.json"
def _read_json(path):
 try:
  v=json.loads(path.read_text(encoding="utf-8-sig")); return v if isinstance(v,dict) else {}
 except (OSError,ValueError): return {}
def _write_state(payload):
 t=_state_path(); t.parent.mkdir(parents=True,exist_ok=True); tmp=t.with_suffix(t.suffix+".tmp"); tmp.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8"); os.replace(tmp,t)
def _snapshot():
 from ..market_snapshot_store import readable_market_snapshot_path
 return _read_json(readable_market_snapshot_path())
def _clock(value): h,m=(int(x) for x in value.split(":")); return time(h,m)
def _position_groups(ledger):
 g=defaultdict(list)
 for e in ledger.events():
  if e.get("positionId"): g[str(e["positionId"])].append(e)
 return g
def _positions(ledger): return [materialize_position(e) for e in _position_groups(ledger).values()]
def _position_row(position,mark=None):
 entry=float(position.get("entryPrice") or position.get("decisionPrice") or 0); qty=int(position.get("filledQty") or position.get("qty") or 0); remaining=int(position.get("remainingQty") if position.get("remainingQty") is not None else qty)
 try: age=session_age(date.fromisoformat(str(position.get("sessionDate"))[:10]),datetime.now(IST).date())
 except (TypeError,ValueError): age=None
 row={**position,"book":"SWING","strategyId":"SWING_2S_MOMENTUM_V2","selectionContract":"SWING_2S_MOMENTUM_V2","direction":"LONG","buyAbove":position.get("limitPrice") or position.get("decisionPrice"),"stopLoss":position.get("effectiveStop") or position.get("initialStop"),"target1":position.get("t1"),"target2":position.get("t2"),"approxQty":qty,"remainingQty":remaining,"deployedCapital":float(position.get("deployedCapital") or entry*qty),"executionStatus":position.get("executionStatus") or ("FILLED" if position.get("entryTimestamp") else "LOCKED"),"locked":True,"source":"swing_v2_ledger","holdingSessionAge":age,"overnightCount":age}
 if mark and mark>0:
  row["currentPrice"]=row["ltp"]=mark; row["markUpdatedAt"]=datetime.now(timezone.utc).isoformat()
  if entry>0 and remaining>0 and not position.get("terminal"):
   u=remaining*(mark-entry); row["unrealizedPnl"]=round(u,2); row["unrealizedPnlPct"]=round((mark/entry-1)*100,4); row["totalPnl"]=round(float(position.get("realizedPnl") or 0)+u,2)
 return row
def _marks(snapshot):
 out={}; quotes=snapshot.get("stockQuotes") if isinstance(snapshot.get("stockQuotes"),dict) else {}
 for s,r in quotes.items():
  if not isinstance(r,dict): continue
  try: p=float(r.get("ltpRaw") or r.get("ltp") or r.get("close") or 0)
  except (TypeError,ValueError): p=0
  if p>0: out[str(s).upper()]=p
 return out
def _entry_hunt_diagnostics(scan,snapshot):
 f=(scan or {}).get("funnel")
 if not isinstance(f,dict): return f
 stocks=snapshot.get("stocks") if isinstance(snapshot.get("stocks"),list) else []
 try: us=int(snapshot.get("universeSize") or 0)
 except: us=0
 try: vs=int(snapshot.get("volumeScreenedCount") or 0)
 except: vs=0
 f={**f,"evaluated":f.get("evaluated",f.get("evaluated_count",f.get("universe"))),"qualified":f.get("qualified",f.get("qualified_out",(scan or {}).get("qualifiedCount",0))),"candleMetrics":f.get("candleMetrics",f.get("fresh_count",f.get("freshData",0))),"candleTimeframe":f.get("candleTimeframe","1H")}
 return {**f,"universeSize":us or None,"volumeScreened":vs or us or None,"evaluated":f.get("evaluated",f.get("universe")),"displayPool":len(stocks) if stocks else None,"swingUniverse":"Total Market 750","corePriorityUniverse":"Top 500 by liquidity","microcapPolicy":"SATELLITE · 20% priority · max 1 position","candleTimeframe":"1H"}
def _session(scan=None,*,now=None):
 cfg=load_config(); now=(now or datetime.now(timezone.utc)).astimezone(IST); day=now.date().isoformat(); ledger=SwingLedger(cfg.ledger_path); positions=_positions(ledger); snapshot=_snapshot(); marks=_marks(snapshot); active=[r for r in positions if r.get("positionId") and not r.get("terminal")]; closed=[]
 for r in positions:
  if not r.get("terminal"): continue
  try: cd=datetime.fromisoformat(str(r.get("lastEventAt") or "").replace("Z","+00:00")).astimezone(IST).date().isoformat()
  except: cd=None
  if str(r.get("sessionDate") or "")==day or cd==day: closed.append(r)
 rows=[_position_row(r,marks.get(str(r.get("symbol") or "").upper())) for r in active]; state=_read_json(_state_path()); state=state if str(state.get("sessionDate") or "")==day else {}; effective=scan if isinstance(scan,dict) else state.get("scan"); local=now.time().replace(tzinfo=None); start=_clock(cfg.decision_start_ist); freeze_clock=_clock(cfg.decision_freeze_ist); freeze=local>=freeze_clock; before_decision=local<start; in_window=start<=local<freeze_clock; finalized=bool(state.get("selectionFinalized")); locked_today=any(str(r.get("sessionDate") or "")==day for r in positions); blocked=bool((effective or {}).get("blocked")); cash=finalized and not locked_today; realized=sum(float(r.get("realizedPnl") or 0) for r in rows); unreal=sum(float(r.get("unrealizedPnl") or 0) for r in rows); diagnostics=_entry_hunt_diagnostics(effective,snapshot) or {}; diagnostics={**diagnostics,"diagnosticPhase":"WAITING_FOR_DECISION_WINDOW" if before_decision and not finalized else ("V2_DECISION_SCAN" if in_window and not finalized else "V2_FINALIZED"),"refreshError":state.get("refreshError")}
 cash_reason="WAITING_FOR_DECISION_WINDOW" if before_decision and not finalized else ((effective or {}).get("blockReason") if cash or blocked else None)
 return {"success":True,"book":"SWING","strategyId":cfg.strategy_id,"policyVersion":cfg.policy_version,"featureVersion":cfg.feature_version,"validationState":"RESEARCH_HYPOTHESIS","authority":"V2","authoritative":True,"executionMode":"PAPER","manualBrokerOrderPlaced":False,"v1Enabled":False,"sessionDate":day,"locked":bool(active) or locked_today or cash,"hunting":in_window and not finalized and not blocked,"waitingForDecisionWindow":before_decision and not finalized,"decisionPhase":diagnostics["diagnosticPhase"],"decisionWindow":{"start":cfg.decision_start_ist,"freeze":cfg.decision_freeze_ist,"entryCutoff":cfg.entry_cutoff_ist,"orderExpiry":cfg.order_expire_ist,"timezone":"Asia/Kolkata"},"selectionFinalized":finalized,"cashHeld":cash,"cashReason":cash_reason,"source":"swing_v2_ledger","selectionContract":cfg.strategy_id,"long":rows,"short":[],"closedPositions":[_position_row(r) for r in closed],"counts":{"long":len(rows),"short":0,"total":len(rows)},"capital":{"swingCapital":cfg.nav,"slots":len(rows),"deployedCapital":round(sum(float(r.get("deployedCapital") or 0) for r in rows),2),"remainingCapital":round(max(0,cfg.nav-sum(float(r.get("deployedCapital") or 0) for r in rows)),2),"portfolioRisk":round(sum(float(r.get("initialRiskRupees") or 0) for r in rows),2)},"portfolio":{"swingCapital":cfg.nav,"realizedPnl":round(realized,2),"unrealizedPnl":round(unreal,2),"totalPnl":round(realized+unreal,2),"lockedCount":len(rows)},"v2":effective or {"enabled":True,"authoritative":True,"candidates":[]},"entryHuntDiagnostics":diagnostics,"updatedAt":datetime.now(timezone.utc).isoformat()}
def _time_until_expiry(now,expiry): return datetime.combine(now.astimezone(IST).date(),expiry,tzinfo=IST)-now.astimezone(IST)
def _retryable_final_block(scan): return str((scan or {}).get("blockReason") or "") in _RETRYABLE_FINAL_BLOCK_REASONS
def _refresh_snapshot(reason,*,deadline=None):
 try:
  from ..angel_one_feed import run_scheduled_live_refresh
  with _DATA_REFRESH_LOCK:
   result=run_scheduled_live_refresh(reason=reason)
 except Exception as exc:
  result={"success":False,"error":str(exc),"reason":reason}
 snapshot=_snapshot()
 if not isinstance(result,dict) or result.get("success") is not True:
  snapshot=dict(snapshot); snapshot["swingV2RefreshError"]=result.get("error") if isinstance(result,dict) else "unknown_refresh_failure"
 return snapshot
def _v2_snapshot_ready(snapshot,cfg):
 status=snapshot.get("swingV2DataStatus")
 feature_rows=int(status.get("featureRows") or 0) if isinstance(status,dict) else 0
 history_ready=int(status.get("historyReadyRows") or 0) if isinstance(status,dict) else 0
 coverage=float(snapshot.get("swingV2UniverseCoverage") or 0.0)
 regime=str(snapshot.get("swingV2Regime") or "")
 return bool(isinstance(status,dict) and feature_rows>0 and history_ready/feature_rows>=cfg.required_coverage and coverage>=cfg.required_coverage and status.get("universeCurrent") and status.get("surveillanceCurrent") and status.get("corporateEventsCurrent") and regime and regime!="REGIME_UNRATED")
def _quote_observations(symbols,now):
 if not symbols:return {}
 try:
  from .market_data import latest_quotes
  quotes=latest_quotes([str(s).upper() for s in symbols])
 except Exception:return {}
 stamp=datetime.now(timezone.utc).isoformat(); out={}
 for s,q in quotes.items():
  if not isinstance(q,dict):continue
  try: ask=float(q.get("ltp") or q.get("open") or 0); depth=int(float(q.get("tradeVolume") or 0))
  except:continue
  if ask>0: out[str(s).upper()]={"timestamp":stamp,"ask":ask,"askDepth":depth,"open":float(q.get("open") or ask),"high":float(q.get("high") or ask),"low":float(q.get("low") or ask),"close":float(q.get("close") or ask),"source":str(q.get("quoteProvider") or "NEUTRAL_FEED")}
 return out
def _refresh_final_candidate_facts(snapshot,scan,now): return snapshot
def _fill_locked_orders(ledger,now,cfg):
 locked=[]
 for _,events in _position_groups(ledger).items():
  s=materialize_position(events)
  if not s.get("terminal") and not s.get("entryTimestamp") and str(s.get("lastEventType") or "")=="POSITION_LOCKED": locked.append(s)
 obs=_quote_observations([s["symbol"] for s in locked],now); expiry=datetime.combine(now.astimezone(IST).date(),_clock(cfg.order_expire_ist),tzinfo=IST)
 for c in locked:
  o=obs.get(str(c.get("symbol") or "").upper()); execute_paper_order(ledger,c,[o] if o else [],expiry=expiry) if o or now.astimezone(IST)>=expiry else None
def _manage_open_positions(ledger,now,cfg):
 opens=[]
 for pid,events in _position_groups(ledger).items():
  s=materialize_position(events)
  if s.get("entryTimestamp") and not s.get("terminal"): opens.append((pid,s))
 obs=_quote_observations([s["symbol"] for _,s in opens],now)
 for pid,s in opens:
  symbol=str(s.get("symbol") or "").upper(); bars=[obs[symbol]] if symbol in obs else []
  if not bars:continue
  try: age=session_age(date.fromisoformat(str(s.get("sessionDate"))[:10]),now.astimezone(IST).date())
  except:continue
  due=time_exit_due(now,age,max_overnights=cfg.max_overnights,exit_clock=cfg.mandatory_exit_ist)
  for i,bar in enumerate(bars):
   s=process_position_bar(ledger,pid,bar,is_d2_exit=due and i==len(bars)-1,data_status="LIVE")
   if s.get("terminal"):break
def run_authoritative_cycle(*,now=None,force=False):
 global _SESSION_READ_CACHE,_SESSION_READ_CACHE_AT,_EOD_READ_CACHE
 cfg=load_config()
 if not cfg.paper_authoritative: raise RuntimeError("Swing V2 is not configured as paper authority")
 now=(now or datetime.now(timezone.utc)).astimezone(IST)
 with _LOCK:
  _SESSION_READ_CACHE=None; _SESSION_READ_CACHE_AT=0; _EOD_READ_CACHE={}; ledger=SwingLedger(cfg.ledger_path)
  from ..nse_trading_calendar import is_nse_trading_day
  if not is_nse_trading_day(now.date()): return _session({"enabled":True,"authoritative":True,"mode":"PAPER","blocked":True,"blockReason":"NSE_MARKET_HOLIDAY","candidates":[],"funnel":{"universe":0}},now=now)
  _manage_open_positions(ledger,now,cfg); current=_read_json(_state_path()); day=now.date().isoformat(); current=current if str(current.get("sessionDate") or "")==day else {"sessionDate":day,"selectionFinalized":False}; local=now.time().replace(tzinfo=None)
  from .market_data import intraday_occupied_symbols
  occupied=intraday_occupied_symbols(day); existing=[r for r in _positions(ledger) if not r.get("terminal")]; start,freeze,expiry=(_clock(cfg.decision_start_ist),_clock(cfg.decision_freeze_ist),_clock(cfg.order_expire_ist)); scan=current.get("scan") if isinstance(current.get("scan"),dict) else None
  due=True
  if current.get("lastScanAt"):
   try: due=(now-datetime.fromisoformat(str(current["lastScanAt"]).replace("Z","+00:00")).astimezone(IST)).total_seconds()>=_SWING_SCAN_INTERVAL_SECONDS
   except: pass
  if start<=local<freeze and not current.get("selectionFinalized") and due:
   snapshot=_refresh_snapshot("swing_v2_decision_scan")
   if not _v2_snapshot_ready(snapshot,cfg):
    scan={"enabled":True,"authoritative":True,"mode":"PAPER","blocked":True,"blockReason":"SWING_V2_DATA_NOT_READY","candidates":[],"funnel":{"universe":snapshot.get("swingV2UniverseSize") or 0,"freshData":0,"topRejectionReasons":[{"reason":"SWING_V2_DATA_NOT_READY","count":1}]},"dataStatus":snapshot.get("swingV2DataStatus") or {}}
   else:
    scan=build_from_market_snapshot(snapshot,final_lock=True,persist_events=True,occupied_symbols=occupied,existing_positions=existing,now=now)
   current.update(scan=scan,lastScanAt=now.astimezone(timezone.utc).isoformat(),refreshError=snapshot.get("swingV2RefreshError"))
  elif freeze<=local and (not current.get("selectionFinalized") or (_retryable_final_block(scan) and due and local<=expiry)):
   snapshot=_refresh_snapshot("swing_v2_final_lock")
   if not _v2_snapshot_ready(snapshot,cfg):
    scan={"enabled":True,"authoritative":True,"mode":"PAPER","blocked":True,"blockReason":"SWING_V2_DATA_NOT_READY","candidates":[],"funnel":{"universe":snapshot.get("swingV2UniverseSize") or 0,"freshData":0,"topRejectionReasons":[{"reason":"SWING_V2_DATA_NOT_READY","count":1}]},"dataStatus":snapshot.get("swingV2DataStatus") or {}}
   else:
    scan=build_from_market_snapshot(snapshot,final_lock=True,persist_events=local<=expiry,occupied_symbols=occupied,existing_positions=existing,now=now)
   current.update(scan=scan,selectionFinalized=True,finalizedAt=now.astimezone(timezone.utc).isoformat(),lastScanAt=now.astimezone(timezone.utc).isoformat(),refreshError=snapshot.get("swingV2RefreshError"))
  if freeze<=local: _fill_locked_orders(ledger,now,cfg)
  _write_state(current); return _session(scan,now=now)
def get_authoritative_session(*,live=False):
 global _SESSION_READ_CACHE,_SESSION_READ_CACHE_AT
 now=monotonic_time.monotonic()
 with _LOCK:
  ttl=0.75 if live else _SESSION_READ_TTL
  if _SESSION_READ_CACHE is None or now-_SESSION_READ_CACHE_AT>=ttl: _SESSION_READ_CACHE=_session(); _SESSION_READ_CACHE_AT=monotonic_time.monotonic()
  return copy.deepcopy(_SESSION_READ_CACHE)
def lock_authoritative_session(*,force=False):
 s=run_authoritative_cycle(force=force); return {"success":True,"alreadyLocked":bool(s.get("locked")),"session":s}
def authoritative_eod_report(for_date): return ledger_eod_report(SwingLedger(load_config().ledger_path),for_date.isoformat())
__all__=["authoritative_eod_report","get_authoritative_session","is_v2_authoritative","lock_authoritative_session","run_authoritative_cycle"]