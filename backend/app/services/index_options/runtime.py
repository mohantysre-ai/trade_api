from __future__ import annotations
import hashlib,json,os,sqlite3
from datetime import datetime,time
from pathlib import Path
from typing import Any
from .config import PAPER_SLIPPAGE_POINTS

DURABLE_LEGACY_SELLERS = {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR"}

def _db_path():
    override=os.getenv("INDEX_OPTIONS_STRATEGY_DB","").strip()
    if override:return Path(override)
    from ..shared_state.sqlite_store import _DB_PATH
    return _DB_PATH

def _connect():
    p=_db_path();p.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(str(p),timeout=10);db.row_factory=sqlite3.Row;db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA synchronous=FULL");db.execute("PRAGMA busy_timeout=10000");db.executescript("""CREATE TABLE IF NOT EXISTS index_option_positions(strategy_position_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL UNIQUE,strategy_id TEXT NOT NULL,session_date TEXT NOT NULL,index_key TEXT NOT NULL,status TEXT NOT NULL,payload_json TEXT NOT NULL,updated_at TEXT NOT NULL);CREATE INDEX IF NOT EXISTS index_option_positions_session_idx ON index_option_positions(session_date,status);CREATE UNIQUE INDEX IF NOT EXISTS index_option_open_strategy_idx ON index_option_positions(session_date,index_key,strategy_id) WHERE status='OPEN';CREATE TABLE IF NOT EXISTS index_option_events(event_id TEXT PRIMARY KEY,strategy_position_id TEXT NOT NULL,event_type TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS index_option_shadows(shadow_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL,strategy_id TEXT NOT NULL,session_date TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS index_option_decision_audit(decision_audit_id TEXT PRIMARY KEY,session_date TEXT NOT NULL,decision_timestamp TEXT NOT NULL,snapshot_id TEXT,market_generation TEXT,strategy_id TEXT NOT NULL,index_key TEXT NOT NULL,strategy_mode TEXT,family TEXT,candidate_state TEXT NOT NULL,eligible BOOLEAN,selected BOOLEAN,executed BOOLEAN,decision TEXT NOT NULL,decision_reason TEXT,score REAL,utility REAL,expected_value REAL,cvar95 REAL,stress_loss REAL,transaction_cost REAL,tail_penalty REAL,greek_penalty REAL,concentration_penalty REAL,risk_gate_passed BOOLEAN,risk_rejection_reasons TEXT,gates TEXT,market_evidence TEXT,futures_oi_evidence TEXT,breadth_evidence TEXT,greeks_evidence TEXT,iv_evidence TEXT,option_chain_evidence TEXT,execution_attempted BOOLEAN,execution_state TEXT,execution_reason TEXT,strategy_position_id TEXT,decision_fingerprint TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(session_date,strategy_id,index_key,decision_fingerprint));CREATE INDEX IF NOT EXISTS index_option_decision_audit_session_idx ON index_option_decision_audit(session_date);CREATE INDEX IF NOT EXISTS index_option_decision_audit_fingerprint_idx ON index_option_decision_audit(decision_fingerprint);""");return db
def _stable_id(*p):return hashlib.sha256("|".join(str(x or "") for x in p).encode()).hexdigest()[:24]
def _float(v):
    try:x=float(v);return x if x==x else None
    except(TypeError,ValueError):return None
def _side(l):return str(l.get("side") or l.get("action") or "").upper()
def _entry_fill(l,ts):
    bid=_float(l.get("entryBid") if l.get("entryBid") is not None else l.get("bestBid"));ask=_float(l.get("entryAsk") if l.get("entryAsk") is not None else l.get("bestAsk"));entry=_float(l.get("entryPrice") if l.get("entryPrice") is not None else l.get("ltp"));side=_side(l)
    if not l.get("symbol") or side not in {"BUY","SELL"}:return None
    if bid and ask and ask>=bid:fill=ask+PAPER_SLIPPAGE_POINTS if side=="BUY" else bid-PAPER_SLIPPAGE_POINTS;mid=(bid+ask)/2
    elif entry and entry>0:fill=entry;mid=entry
    else:return None
    if fill<=0:return None
    return {**l,"side":side,"entryBid":bid,"entryAsk":ask,"entryFill":round(fill,4),"entryPrice":round(fill,4),"entrySlippage":round(abs(fill-mid),4),"entryTimestamp":ts,"currentPrice":round(fill,4)}
def _candidate_legs(c):
    legs=[dict(x) for x in c.get("legs") or [] if isinstance(x,dict)]
    if legs:return legs
    x=c.get("contract") if isinstance(c.get("contract"),dict) else {};return [{**x,"side":"BUY","qty":1,"expiry":c.get("expiry")}] if x else []
def _entry_value(legs):return round(sum((1 if _side(x)=="BUY" else -1)*float(x["entryFill"])*int(x.get("qty") or 1) for x in legs),4)
def _quotes(s):
    out={}
    for supplied in (((s.get("indexOptions") or {}).get("indices") or {}).values()):
        if isinstance(supplied,dict):
            for r in [*(supplied.get("rawChain") or []),*(supplied.get("farChain") or [])]:
                if isinstance(r,dict) and r.get("symbol"):out[str(r["symbol"])]=r
    return out
def _mark_position(p,q,now,m):
    legs=[];pnl=0.;g={"delta":0.,"gamma":0.,"theta":0.,"vega":0.};complete=True
    for old in p.get("legs") or []:
        l=dict(old);r=q.get(str(l.get("symbol") or ""))
        if r is None:complete=False;legs.append(l);continue
        bid=_float(r.get("bestBid"));ask=_float(r.get("bestAsk"));ltp=_float(r.get("ltp"));mark=(bid if _side(l)=="BUY" else ask) if bid is not None and ask is not None else ltp
        if mark is None or mark<=0:complete=False;legs.append(l);continue
        qty=int(l.get("qty") or 1)*int(l.get("lotSize") or 1);sign=1 if _side(l)=="BUY" else -1;pnl+=(mark-float(l["entryFill"]))*qty*sign
        for n in g:g[n]+=(_float(r.get(n)) or 0)*qty*sign
        legs.append({**l,"currentBid":bid,"currentAsk":ask,"currentPrice":round(mark,4),"currentIv":_float(r.get("iv")),"markedAt":now.isoformat()})
    return {**p,"legs":legs,"combinedStructureValue":round(sum((1 if _side(l)=="BUY" else -1)*float(l.get("currentPrice") or 0)*int(l.get("qty") or 1) for l in legs),4),"unrealizedPnl":round(pnl,2),"netGreeks":{k:round(v,6) for k,v in g.items()},"markStatus":"LIVE" if complete else "INCOMPLETE","currentSpot":_float(m.get("spot")),"currentIv":_float(m.get("atmIv")),"structuralInvalidated":str((m.get("structure") or {}).get("status") or "").upper()=="INVALIDATED","lifecycleState":"NO_ACTION","updatedAt":now.isoformat()}
def _exit_reason(p,now):
    family=str(p.get("family") or "");pnl=float(p.get("unrealizedPnl") or 0);ml=abs(float(p.get("maxLoss") or 0));mp=abs(float(p.get("maxProfit") or 0));limits={"DIRECTIONAL":(.5,.5,time(15,20)),"VOLATILITY_EXPANSION":(.4,.35,time(15,15)),"RANGE":(.4,.5,time(15,0)),"TERM_STRUCTURE":(.25,.3,time(15,0))};pf,lf,cut=limits.get(family,(.5,.35,time(15,20)))
    if p.get("structuralInvalidated"):return "STRUCTURAL_INVALIDATION"
    if mp and pnl>=mp*pf:return "PROFIT_TARGET"
    if ml and pnl<=-(ml*lf):return "STRUCTURE_RISK_STOP"
    if str(p.get("expiryState") or "")=="EXPIRY_CUTOFF":return "EXPIRY_CUTOFF"
    if now.timetz().replace(tzinfo=None)>=cut:return "TIME_EXIT"
    return None
def _close(p,reason,now):
    legs=[]
    for l in p.get("legs") or []:
        fill=l.get("currentPrice");bid=_float(l.get("currentBid"));ask=_float(l.get("currentAsk"));mid=(bid+ask)/2 if bid is not None and ask is not None else None;slip=abs(float(fill)-mid) if fill is not None and mid is not None else None;legs.append({**l,"exitBid":bid,"exitAsk":ask,"exitFill":fill,"exitSlippage":None if slip is None else round(slip,4),"exitTimestamp":now.isoformat()})
    return {**p,"legs":legs,"status":"CLOSED","exitReason":reason,"exitedAt":now.isoformat(),"realizedPnl":round(float(p.get("unrealizedPnl") or 0),2),"unrealizedPnl":0.,"exitGreeks":p.get("netGreeks"),"exitSpot":p.get("currentSpot"),"exitIv":p.get("currentIv"),"lifecycleState":"EXIT_ALL","updatedAt":now.isoformat()}
def _save_position(db,p):db.execute("UPDATE index_option_positions SET status=?,payload_json=?,updated_at=? WHERE strategy_position_id=?",(p["status"],json.dumps(p),p["updatedAt"],p["strategyPositionId"]))
def load_positions(session_date=None):
    with _connect() as db:rows=db.execute("SELECT payload_json FROM index_option_positions WHERE session_date=? ORDER BY updated_at",(session_date,)).fetchall() if session_date else db.execute("SELECT payload_json FROM index_option_positions ORDER BY updated_at").fetchall()
    return [json.loads(r[0]) for r in rows]
def load_events(pid):
    with _connect() as db:rows=db.execute("SELECT event_type,payload_json FROM index_option_events WHERE strategy_position_id=? ORDER BY created_at",(pid,)).fetchall()
    return [{"eventType":r[0],"payload":json.loads(r[1])} for r in rows]
def load_shadows(d):
    with _connect() as db:rows=db.execute("SELECT payload_json FROM index_option_shadows WHERE session_date=? ORDER BY created_at",(d,)).fetchall()
    return [json.loads(r[0]) for r in rows]
def daily_entry_count(d):
    with _connect() as db:return db.execute("SELECT COUNT(*) FROM index_option_positions WHERE session_date=?",(d,)).fetchone()[0]
def _paper_daily_count(d):
    try:
        from ..index_options_paper import paper_book_path
        from ..json_atomic import load_json_with_fallback
        b=load_json_with_fallback(paper_book_path())
        if isinstance(b,dict) and b.get("sessionDate")==d:return max(0,int(b.get("entryCount") or 0))
    except Exception:pass
    return 0


def _decision_fingerprint(candidate: dict[str, Any], extra_state: str = "") -> str:
    gates = candidate.get("gates") if isinstance(candidate.get("gates"), dict) else {}
    risk = candidate.get("risk") if isinstance(candidate.get("risk"), dict) else {}
    payload = "|".join([
        str(candidate.get("strategyId") or candidate.get("strategyType") or ""),
        str(candidate.get("key") or candidate.get("index") or ""),
        str(candidate.get("eligible")),
        str(candidate.get("quantAuthority") or ""),
        json.dumps(gates, sort_keys=True),
        json.dumps(risk, sort_keys=True),
        str(candidate.get("utility") or candidate.get("expected_value") or ""),
        str(candidate.get("cvar95") or ""),
        str(candidate.get("stress_loss") or risk.get("stressLoss") or ""),
        str(candidate.get("paperEntryState") or ""),
        extra_state,
    ])
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _summarize_gates(candidate: dict[str, Any]) -> dict[str, Any]:
    gates = candidate.get("gates") if isinstance(candidate.get("gates"), dict) else {}
    return {k: bool(v) if not isinstance(v, dict) else v.get("aligned") for k, v in gates.items()}


def _summarize_market_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "spot": _float(candidate.get("spot")),
        "direction": str(candidate.get("direction") or candidate.get("bias") or "").upper() or None,
        "trend": str(candidate.get("trend") or "").upper() or None,
        "marketRegime": str(candidate.get("state") or candidate.get("marketRegime") or "").upper() or None,
        "expiryState": str(candidate.get("expiryState") or "").upper() or None,
        "dataSource": str(candidate.get("dataSource") or candidate.get("source") or "").upper() or None,
        "snapshotId": str(candidate.get("snapshotId") or ""),
        "decisionTimestamp": str(candidate.get("decisionTimestamp") or ""),
        "marketGeneration": str(candidate.get("marketGeneration") or ""),
    }


def _summarize_futures_oi(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("gateEvidence") if isinstance(candidate.get("gateEvidence"), dict) else {}
    futures = evidence.get("futuresOi") if isinstance(evidence.get("futuresOi"), dict) else {}
    return {
        "state": str(futures.get("state") or "").upper() or None,
        "aligned": futures.get("aligned") if isinstance(futures.get("aligned"), bool) else None,
        "priceChange": _float(futures.get("priceChange")),
        "oiChange": _float(futures.get("oiChange")),
        "source": str(futures.get("source") or "").upper() or None,
        "timestamp": str(futures.get("timestamp") or ""),
    }


def _summarize_breadth(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = candidate.get("gateEvidence") if isinstance(candidate.get("gateEvidence"), dict) else {}
    breadth = evidence.get("breadth") if isinstance(evidence.get("breadth"), dict) else {}
    return {
        "score": _float(breadth.get("score")),
        "directionalScore": _float(breadth.get("directionalScore")),
        "coveragePct": _float(breadth.get("coveragePct")),
        "aligned": breadth.get("aligned") if isinstance(breadth.get("aligned"), bool) else None,
        "strictAligned": breadth.get("strictAligned") if isinstance(breadth.get("strictAligned"), bool) else None,
        "constituentCount": int(breadth.get("constituentCount") or 0) if breadth.get("constituentCount") is not None else None,
        "source": str(breadth.get("source") or "").upper() or None,
        "timestamp": str(breadth.get("timestamp") or ""),
    }


def _summarize_greeks(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "delta": _float(candidate.get("delta")),
        "gamma": _float(candidate.get("gamma")),
        "theta": _float(candidate.get("theta")),
        "vega": _float(candidate.get("vega")),
        "units": {
            "delta": "INR per 1 underlying point",
            "gamma": "INR per 1 underlying point^2",
            "theta": "INR per day",
            "vega": "INR per 1 percentage point IV move",
        },
        "source": str(candidate.get("dataSource") or candidate.get("source") or "").upper() or None,
        "timestamp": str(candidate.get("decisionTimestamp") or ""),
    }


def _summarize_iv(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "atmIv": _float(candidate.get("atmIv")),
        "ivRank": _float(candidate.get("ivRank")),
        "ivPercentile": _float(candidate.get("ivPercentile")),
        "realizedVol": _float(candidate.get("realizedVol")),
        "expectedMove": _float(candidate.get("expectedMove")),
        "skew": _float(candidate.get("skew")),
        "putSkew": _float(candidate.get("putSkew")),
        "callSkew": _float(candidate.get("callSkew")),
        "termStructure": _float(candidate.get("termStructure")),
        "dte": int(candidate.get("dte")) if candidate.get("dte") is not None else None,
    }


def _summarize_option_chain(candidate: dict[str, Any]) -> dict[str, Any]:
    legs = candidate.get("legs") or []
    if not legs and candidate.get("contract"):
        legs = [{**candidate["contract"], "side": "BUY", "qty": 1, "expiry": candidate.get("expiry")}]
    summarized_legs = []
    for leg in legs[:8]:
        summarized_legs.append({
            "symbol": str(leg.get("symbol") or ""),
            "token": str(leg.get("token") or ""),
            "exchange": str(leg.get("exchange") or ""),
            "strike": _float(leg.get("strike")),
            "optionType": str(leg.get("optionType") or leg.get("type") or "").upper() or None,
            "expiry": str(leg.get("expiry") or candidate.get("expiry") or ""),
            "side": str(leg.get("side") or leg.get("action") or "").upper() or None,
            "qty": int(leg.get("qty") or 1),
            "lotSize": int(leg.get("lotSize") or 0),
            "bid": _float(leg.get("bestBid")),
            "ask": _float(leg.get("bestAsk")),
            "ltp": _float(leg.get("ltp") or leg.get("entryPrice")),
            "iv": _float(leg.get("iv")),
            "delta": _float(leg.get("delta")),
            "gamma": _float(leg.get("gamma")),
            "theta": _float(leg.get("theta")),
            "vega": _float(leg.get("vega")),
            "spreadPct": _float(leg.get("spreadPct")),
            "liquidityScore": _float(leg.get("liquidityScore")),
            "selectedFill": _float(leg.get("selectedFill") or leg.get("entryFill") or leg.get("entryPrice")),
        })
    selection_evidence = candidate.get("selectionEvidence") if isinstance(candidate.get("selectionEvidence"), dict) else {}
    return {
        "legs": summarized_legs,
        "selectionBasis": selection_evidence.get("selectionReasons") or [],
        "strategyType": str(candidate.get("strategyType") or candidate.get("strategyId") or ""),
    }


def _candidate_state_label(candidate: dict[str, Any], decision: str, selected: bool, entry_state: str, executed: bool = False, entry_attempted: bool = False) -> str:
    if not candidate.get("eligible"):
        return "REJECTED"
    if decision == "REJECT":
        return "REJECTED"
    if entry_state == "ENTRY_BLOCKED":
        return "ENTRY_BLOCKED"
    if executed:
        return "EXECUTED"
    if entry_attempted:
        return "ENTRY_ATTEMPT"
    if selected:
        return "SELECTED"
    return "EVALUATED"


def _persist_decision_audit(db, candidate: dict[str, Any], state: str, decision: str, selected: bool, executed: bool, entry_state: str, now: datetime, snapshot_id: str = "", market_generation: str = "") -> bool:
    sid = str(candidate.get("strategyId") or candidate.get("strategyType") or "")
    idx = str(candidate.get("key") or candidate.get("index") or "")
    if not sid or not idx:
        return False

    decision_id = _stable_id(now.date().isoformat(), sid + "|" + idx, candidate.get("snapshotId") or candidate.get("decisionTimestamp") or now.isoformat())
    audit_id = _stable_id("AUDIT", decision_id, state, now.isoformat())
    state_label = state if state else _candidate_state_label(candidate, decision, selected, entry_state, executed)
    fingerprint = _decision_fingerprint(candidate, state_label)

    existing = db.execute("SELECT decision_audit_id FROM index_option_decision_audit WHERE session_date=? AND strategy_id=? AND index_key=? AND decision_fingerprint=?", (now.date().isoformat(), sid, idx, fingerprint)).fetchone()
    if existing:
        return False

    q = candidate.get("quantDecision") if isinstance(candidate.get("quantDecision"), dict) else {}
    risk_rejection = []
    if isinstance(q.get("riskRejectionReasons"), (list, tuple)):
        risk_rejection = [str(r) for r in q["riskRejectionReasons"]]
    elif isinstance(q.get("portfolioRisk"), dict) and isinstance(q["portfolioRisk"].get("reasons"), (list, tuple)):
        risk_rejection = [str(r) for r in q["portfolioRisk"]["reasons"]]

    reasons = []
    if isinstance(q.get("reasons"), (list, tuple)):
        reasons = [str(r) for r in q["reasons"]]
    elif candidate.get("paperEntryReason"):
        reasons = [str(candidate.get("paperEntryReason"))]

    db.execute(
        """INSERT OR IGNORE INTO index_option_decision_audit VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            audit_id,
            now.date().isoformat(),
            now.isoformat(),
            str(snapshot_id or candidate.get("snapshotId") or ""),
            str(market_generation or candidate.get("marketGeneration") or ""),
            sid,
            idx,
            str(candidate.get("strategyMode") or ""),
            str(candidate.get("family") or ""),
            state_label,
            int(candidate.get("eligible") is True),
            int(selected is True),
            int(executed is True),
            str(decision or q.get("decision") or "REJECT"),
            json.dumps(reasons) if reasons else None,
            _float(q.get("score") or candidate.get("score")),
            _float(q.get("utility") or candidate.get("utility")),
            _float(q.get("expected_value") or q.get("expectedValue") or candidate.get("expected_value")),
            _float(q.get("cvar95") or candidate.get("cvar95")),
            _float(q.get("stress_loss") or q.get("stressLoss") or candidate.get("stress_loss")),
            _float(q.get("transaction_cost") or q.get("transactionCost") or candidate.get("transaction_cost")),
            _float(q.get("tail_penalty") or q.get("tailPenalty") or candidate.get("tail_penalty")),
            _float(q.get("greek_penalty") or q.get("greekPenalty") or candidate.get("greek_penalty")),
            _float(q.get("concentration_penalty") or q.get("concentrationPenalty") or candidate.get("concentration_penalty")),
            int(bool(q.get("risk_gate_passed") or (not risk_rejection))),
            json.dumps(risk_rejection) if risk_rejection else None,
            json.dumps(_summarize_gates(candidate)),
            json.dumps(_summarize_market_evidence(candidate)),
            json.dumps(_summarize_futures_oi(candidate)),
            json.dumps(_summarize_breadth(candidate)),
            json.dumps(_summarize_greeks(candidate)),
            json.dumps(_summarize_iv(candidate)),
            json.dumps(_summarize_option_chain(candidate)),
            int(entry_state in {"FILLED", "ENTRY_BLOCKED"}),
            str(entry_state or ""),
            candidate.get("paperEntryReason"),
            candidate.get("strategyPositionId"),
            fingerprint,
            now.isoformat(),
        ),
    )
    return True
def process_strategy_cycle(radar,snapshot,now):
    """Quant V2 selected structures are the only source of new durable entries."""
    from ..angel_index_options import IST_ZONE

    now = now.astimezone(IST_ZONE)
    d=now.date().isoformat();q=_quotes(snapshot)
    from ..index_options_engine import (
        MAX_CONCURRENT_PER_SLEEVE,
        MAX_CONCURRENT_TRADES,
        MAX_DAILY_ENTRIES,
    )
    daily_entries=daily_entry_count(d)+_paper_daily_count(d)
    snapshot_id=str(snapshot.get("snapshotId") or snapshot.get("updatedAt") or "")
    market_generation=str(snapshot.get("marketGeneration") or "")
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT payload_json FROM index_option_positions WHERE session_date=? AND status='OPEN'",(d,)).fetchall():
            stored=json.loads(row[0]);market=(((snapshot.get("indexOptions") or {}).get("indices") or {}).get(stored.get("index")) or {});marked=_mark_position(stored,q,now,market);reason=_exit_reason(marked,now);updated=_close(marked,reason,now) if reason else marked;_save_position(db,updated)
            if reason:db.execute("INSERT OR IGNORE INTO index_option_events VALUES(?,?,?,?,?)",(_stable_id(updated["strategyPositionId"],"CLOSE"),updated["strategyPositionId"],"CLOSED",json.dumps(updated),now.isoformat()))
        candidates=radar.get("modularCandidates") or []; selected=radar.get("modularSelected") or []; selected_ids={str(r.get("strategyId"))+"|"+str(r.get("key")) for r in selected}
        selected_map={(str(r.get("strategyId") or r.get("strategyType") or ""), str(r.get("key") or r.get("index") or "")): r for r in selected}
        for c in candidates:
            sid=str(c.get("strategyId") or c.get("strategyType") or "");identity=sid+"|"+str(c.get("key"));decision_id=_stable_id(d,identity,c.get("snapshotId") or c.get("decisionTimestamp"))
            is_selected = identity in selected_ids
            entry_state = str(c.get("paperEntryState") or "")
            executed = bool(c.get("strategyPositionId") or (entry_state == "FILLED"))
            decision = "ADMIT" if c.get("eligible") and is_selected else "REJECT"
            state_label = _candidate_state_label(c, decision, is_selected, entry_state, executed)
            if not c.get("eligible") or not is_selected:
                _persist_decision_audit(db, c, state_label, decision, is_selected, executed, entry_state, now, snapshot_id, market_generation)
                db.execute("INSERT OR IGNORE INTO index_option_shadows VALUES(?,?,?,?,?,?)",(_stable_id("SHADOW",decision_id),decision_id,sid,d,json.dumps({**c,"quantDecision":"NO_TRADE_OR_NOT_SELECTED"}),now.isoformat()))
                continue

            if entry_state not in {"ENTRY_BLOCKED", "FILLED"}:
                _persist_decision_audit(db, c, "SELECTED", "ADMIT", True, False, "", now, snapshot_id, market_generation)

            if c.get("quantAuthority")!="INDEX_OPTIONS_QUANT_V2":continue
            if daily_entries>=MAX_DAILY_ENTRIES:c["paperEntryState"]="ENTRY_BLOCKED";c["paperEntryReason"]="MAX_DAILY_ENTRIES_REACHED";_persist_decision_audit(db,c,"ENTRY_BLOCKED","REJECT",True,False,"ENTRY_BLOCKED",now,snapshot_id,market_generation);continue
            if now.weekday() >= 5 or now.time().replace(tzinfo=None) < time(9, 15) or _exit_reason({"family": c.get("family")}, now) == "TIME_EXIT":
                c["paperEntryState"] = "ENTRY_BLOCKED"
                c["paperEntryReason"] = "SESSION_ENTRY_CUTOFF"
                _persist_decision_audit(db,c,"ENTRY_BLOCKED","REJECT",True,False,"ENTRY_BLOCKED",now,snapshot_id,market_generation)
                continue
            open_payloads=[json.loads(row[0]) for row in db.execute("SELECT payload_json FROM index_option_positions WHERE session_date=? AND status='OPEN'",(d,)).fetchall()]
            if len(open_payloads)>=MAX_CONCURRENT_TRADES:c["paperEntryState"]="ENTRY_BLOCKED";c["paperEntryReason"]="QUANT_PORTFOLIO_MAX_CONCURRENT";_persist_decision_audit(db,c,"ENTRY_BLOCKED","REJECT",True,False,"ENTRY_BLOCKED",now,snapshot_id,market_generation);continue
            sleeve=str(c.get("strategyMode") or "BUY_PREMIUM").upper()
            if sum(1 for row in open_payloads if str(row.get("strategyMode") or "BUY_PREMIUM").upper()==sleeve)>=MAX_CONCURRENT_PER_SLEEVE:c["paperEntryState"]="ENTRY_BLOCKED";c["paperEntryReason"]="QUANT_SLEEVE_MAX_CONCURRENT";_persist_decision_audit(db,c,"ENTRY_BLOCKED","REJECT",True,False,"ENTRY_BLOCKED",now,snapshot_id,market_generation);continue

            if entry_state == "ENTRY_BLOCKED":
                _persist_decision_audit(db, c, "ENTRY_BLOCKED", "REJECT", True, False, "ENTRY_BLOCKED", now, snapshot_id, market_generation)
                continue

            if entry_state not in {"ENTRY_BLOCKED", "FILLED"}:
                _persist_decision_audit(db, c, "ENTRY_ATTEMPT", "ADMIT", True, False, "", now, snapshot_id, market_generation)

            if db.execute("SELECT 1 FROM index_option_positions WHERE decision_id=? OR(session_date=? AND index_key=? AND strategy_id=? AND status='OPEN')",(decision_id,d,c.get("key"),sid)).fetchone():continue
            fills=[_entry_fill(x,now.isoformat()) for x in _candidate_legs(c)]
            if not fills or any(x is None for x in fills):c["paperEntryState"]="ENTRY_BLOCKED";c["paperEntryReason"]="MANDATORY_LEG_UNPRICED";_persist_decision_audit(db,c,"ENTRY_BLOCKED","REJECT",True,False,"ENTRY_BLOCKED",now,snapshot_id,market_generation);continue
            legs=[x for x in fills if x is not None];pid=_stable_id("POSITION",decision_id)
            for x in legs:x["strategyPositionId"]=pid
            ev=_entry_value(legs);risk=c.get("risk") if isinstance(c.get("risk"),dict) else {};ml=c.get("maxLoss") if c.get("maxLoss") is not None else risk.get("maxLossPerLot");mp=c.get("maxProfit") if c.get("maxProfit") is not None else risk.get("maxProfitPerLot");be=c.get("breakevens") or [v for v in(risk.get("lowerBreakEven"),risk.get("upperBreakEven")) if v is not None]
            p={"strategyPositionId":pid,"decisionId":decision_id,"strategyId":sid,"family":c.get("family"),"index":c.get("key"),"status":"OPEN","sessionDate":d,"expiry":c.get("expiry"),"farExpiry":c.get("farExpiry"),"expiryState":c.get("expiryState"),"legs":legs,"entryValue":ev,"entryDebit":max(0.,ev),"entryCredit":max(0.,-ev),"maxLoss":ml,"maxProfit":mp,"breakevens":be,"entryGreeks":{n:c.get(n) for n in("delta","gamma","theta","vega")},"netGreeks":{n:c.get(n) for n in("delta","gamma","theta","vega")},"entrySpot":c.get("spot"),"entryIv":c.get("atmIv"),"unrealizedPnl":0.,"realizedPnl":0.,"lifecycleState":"NO_ACTION","enteredAt":now.isoformat(),"updatedAt":now.isoformat(),"authority":"INDEX_OPTIONS_QUANT_V2","selectionModel":"COMMON_SCENARIO_DISTRIBUTION_REPRICER"}
            try:db.execute("INSERT INTO index_option_positions VALUES(?,?,?,?,?,?,?,?)",(pid,decision_id,sid,d,c.get("key"),"OPEN",json.dumps(p),now.isoformat()))
            except sqlite3.IntegrityError:continue
            db.execute("INSERT INTO index_option_events VALUES(?,?,?,?,?)",(_stable_id(pid,"OPEN"),pid,"OPENED",json.dumps(p),now.isoformat()));c["strategyPositionId"]=pid;c["paperEntryState"]="FILLED";_persist_decision_audit(db,c,"EXECUTED","ADMIT",True,True,"FILLED",now,snapshot_id,market_generation);daily_entries+=1
        db.commit()
    p=load_positions(d);return {"authority":"INDEX_OPTIONS_QUANT_V2","positions":p,"open":[x for x in p if x.get("status")=="OPEN"],"closed":[x for x in p if x.get("status")=="CLOSED"]}
def strategy_book(d):
    positions = load_positions(d)
    return {
        "sessionDate": d,
        "authority": "INDEX_OPTIONS_QUANT_V2",
        "positions": positions,
        "open": [p for p in positions if p.get("status") == "OPEN"],
        "closed": [p for p in positions if p.get("status") == "CLOSED"],
    }


def strategy_eod(d):
    book = strategy_book(d)
    rows = []
    for p in book["positions"]:
        spot, entry_spot = _float(p.get("currentSpot")), _float(p.get("entrySpot"))
        iv, entry_iv = _float(p.get("currentIv")), _float(p.get("entryIv"))
        rows.append({
            **p,
            "strategy": p.get("strategyId"),
            "entry": p.get("enteredAt"),
            "exit": p.get("exitedAt"),
            "spotMove": round(spot - entry_spot, 6) if spot is not None and entry_spot is not None else None,
            "ivMove": round(iv - entry_iv, 6) if iv is not None and entry_iv is not None else None,
        })
    return {
        **book,
        "positions": rows,
        "realizedPnl": round(sum(float(p.get("realizedPnl") or 0) for p in book["closed"]), 2),
        "unrealizedPnl": round(sum(float(p.get("unrealizedPnl") or 0) for p in book["open"]), 2),
    }


def load_decision_audit(session_date: str) -> dict[str, Any]:
    JSON_KEYS = (
        "gates", "market_evidence", "futures_oi_evidence", "breadth_evidence",
        "greeks_evidence", "iv_evidence", "option_chain_evidence",
        "risk_rejection_reasons", "decision_reason",
    )
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM index_option_decision_audit WHERE session_date=? ORDER BY created_at",
            (session_date,),
        ).fetchall()
    audits: list[dict[str, Any]] = []
    for row in rows:
        raw = dict(row)
        for key in JSON_KEYS:
            val = raw.get(key)
            if isinstance(val, str):
                try:
                    raw[key] = json.loads(val)
                except (TypeError, ValueError):
                    pass
        audits.append({
            "decisionAuditId": raw.get("decision_audit_id"),
            "sessionDate": raw.get("session_date"),
            "decisionTimestamp": raw.get("decision_timestamp"),
            "snapshotId": raw.get("snapshot_id"),
            "marketGeneration": raw.get("market_generation"),
            "strategyId": raw.get("strategy_id"),
            "indexKey": raw.get("index_key"),
            "strategyMode": raw.get("strategy_mode"),
            "family": raw.get("family"),
            "candidateState": raw.get("candidate_state"),
            "eligible": bool(raw.get("eligible")),
            "selected": bool(raw.get("selected")),
            "executed": bool(raw.get("executed")),
            "decision": raw.get("decision"),
            "decisionReason": raw.get("decision_reason"),
            "score": raw.get("score"),
            "utility": raw.get("utility"),
            "expectedValue": raw.get("expected_value"),
            "cvar95": raw.get("cvar95"),
            "stressLoss": raw.get("stress_loss"),
            "transactionCost": raw.get("transaction_cost"),
            "tailPenalty": raw.get("tail_penalty"),
            "greekPenalty": raw.get("greek_penalty"),
            "concentrationPenalty": raw.get("concentration_penalty"),
            "riskGatePassed": bool(raw.get("risk_gate_passed")),
            "riskRejectionReasons": raw.get("risk_rejection_reasons"),
            "gates": raw.get("gates"),
            "marketEvidence": raw.get("market_evidence"),
            "futuresOiEvidence": raw.get("futures_oi_evidence"),
            "breadthEvidence": raw.get("breadth_evidence"),
            "greeksEvidence": raw.get("greeks_evidence"),
            "ivEvidence": raw.get("iv_evidence"),
            "optionChainEvidence": raw.get("option_chain_evidence"),
            "executionAttempted": bool(raw.get("execution_attempted")),
            "executionState": raw.get("execution_state"),
            "executionReason": raw.get("execution_reason"),
            "strategyPositionId": raw.get("strategy_position_id"),
            "decisionFingerprint": raw.get("decision_fingerprint"),
            "createdAt": raw.get("created_at"),
        })
    rejection_summary: dict[str, int] = {}
    for a in audits:
        if a.get("candidateState") != "REJECTED":
            continue
        reasons: list[str] = []
        decision_reason = a.get("decisionReason")
        if isinstance(decision_reason, list):
            reasons = [str(r) for r in decision_reason]
        elif isinstance(decision_reason, str):
            try:
                parsed = json.loads(decision_reason)
                reasons = [str(r) for r in parsed] if isinstance(parsed, list) else [decision_reason]
            except (TypeError, ValueError):
                reasons = [decision_reason] if decision_reason else []
        risk_reasons = a.get("riskRejectionReasons")
        if isinstance(risk_reasons, list):
            reasons.extend(str(r) for r in risk_reasons)
        elif isinstance(risk_reasons, str):
            try:
                parsed = json.loads(risk_reasons)
                reasons.extend(str(r) for r in parsed) if isinstance(parsed, list) else reasons.append(risk_reasons)
            except (TypeError, ValueError):
                if risk_reasons:
                    reasons.append(risk_reasons)
        for reason in reasons:
            if reason:
                rejection_summary[reason] = rejection_summary.get(reason, 0) + 1

    def _ck(a):
        return a.get("strategyId") + "|" + a.get("indexKey")

    return {
        "sessionDate": session_date,
        "audits": audits,
        "evaluatedCount": len(audits),
        "eligibleCount": len({_ck(a) for a in audits if a.get("eligible")}),
        "qualifiedCount": len({_ck(a) for a in audits if a.get("candidateState") in {"QUALIFIED", "SELECTED", "ENTRY_ATTEMPT", "EXECUTED", "ENTRY_BLOCKED"}}),
        "selectedCount": len({_ck(a) for a in audits if a.get("candidateState") in {"SELECTED", "ENTRY_ATTEMPT", "EXECUTED", "ENTRY_BLOCKED"}}),
        "executedCount": len({_ck(a) for a in audits if a.get("candidateState") == "EXECUTED"}),
        "rejectedCount": len({_ck(a) for a in audits if a.get("candidateState") == "REJECTED"}),
        "entryBlockedCount": len({_ck(a) for a in audits if a.get("candidateState") == "ENTRY_BLOCKED"}),
        "rejectionSummary": rejection_summary,
    }
