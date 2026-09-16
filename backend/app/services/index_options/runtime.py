from __future__ import annotations
import hashlib,json,os,sqlite3
from datetime import datetime,time
from pathlib import Path
from typing import Any
from .config import PAPER_SLIPPAGE_POINTS

def _db_path():
    override=os.getenv("INDEX_OPTIONS_STRATEGY_DB","").strip()
    if override:return Path(override)
    from ..shared_state.sqlite_store import _DB_PATH
    return _DB_PATH

def _connect():
    p=_db_path();p.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(str(p),timeout=10);db.row_factory=sqlite3.Row;db.execute("PRAGMA journal_mode=WAL");db.execute("PRAGMA synchronous=FULL");db.execute("PRAGMA busy_timeout=10000");db.executescript("""CREATE TABLE IF NOT EXISTS index_option_positions(strategy_position_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL UNIQUE,strategy_id TEXT NOT NULL,session_date TEXT NOT NULL,index_key TEXT NOT NULL,status TEXT NOT NULL,payload_json TEXT NOT NULL,updated_at TEXT NOT NULL);CREATE INDEX IF NOT EXISTS index_option_positions_session_idx ON index_option_positions(session_date,status);CREATE UNIQUE INDEX IF NOT EXISTS index_option_open_strategy_idx ON index_option_positions(session_date,index_key,strategy_id) WHERE status='OPEN';CREATE TABLE IF NOT EXISTS index_option_events(event_id TEXT PRIMARY KEY,strategy_position_id TEXT NOT NULL,event_type TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS index_option_shadows(shadow_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL,strategy_id TEXT NOT NULL,session_date TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);""");return db
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
def process_strategy_cycle(radar,snapshot,now):
    """Quant V2 selected structures are the only source of new durable entries."""
    d=now.date().isoformat();q=_quotes(snapshot)
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT payload_json FROM index_option_positions WHERE session_date=? AND status='OPEN'",(d,)).fetchall():
            stored=json.loads(row[0]);market=(((snapshot.get("indexOptions") or {}).get("indices") or {}).get(stored.get("index")) or {});marked=_mark_position(stored,q,now,market);reason=_exit_reason(marked,now) if marked.get("markStatus")=="LIVE" else None;updated=_close(marked,reason,now) if reason else marked;_save_position(db,updated)
            if reason:db.execute("INSERT OR IGNORE INTO index_option_events VALUES(?,?,?,?,?)",(_stable_id(updated["strategyPositionId"],"CLOSE"),updated["strategyPositionId"],"CLOSED",json.dumps(updated),now.isoformat()))
        candidates=radar.get("modularCandidates") or []; selected=radar.get("modularSelected") or []; selected_ids={str(r.get("strategyId"))+"|"+str(r.get("key")) for r in selected}
        for c in candidates:
            sid=str(c.get("strategyId") or c.get("strategyType") or "");identity=sid+"|"+str(c.get("key"));decision_id=_stable_id(d,identity,c.get("snapshotId") or c.get("decisionTimestamp"))
            if not c.get("eligible") or identity not in selected_ids:
                db.execute("INSERT OR IGNORE INTO index_option_shadows VALUES(?,?,?,?,?,?)",(_stable_id("SHADOW",decision_id),decision_id,sid,d,json.dumps({**c,"quantDecision":"NO_TRADE_OR_NOT_SELECTED"}),now.isoformat()));continue
            if c.get("quantAuthority")!="INDEX_OPTIONS_QUANT_V2":continue
            if db.execute("SELECT COUNT(*) FROM index_option_positions WHERE session_date=? AND status='OPEN'",(d,)).fetchone()[0]>=2:c["paperEntryState"]="ENTRY_BLOCKED";c["paperEntryReason"]="QUANT_PORTFOLIO_MAX_CONCURRENT";continue
            if db.execute("SELECT 1 FROM index_option_positions WHERE decision_id=? OR(session_date=? AND index_key=? AND strategy_id=? AND status='OPEN')",(decision_id,d,c.get("key"),sid)).fetchone():continue
            fills=[_entry_fill(x,now.isoformat()) for x in _candidate_legs(c)]
            if not fills or any(x is None for x in fills):c["paperEntryState"]="ENTRY_BLOCKED";c["paperEntryReason"]="MANDATORY_LEG_UNPRICED";continue
            legs=[x for x in fills if x is not None];pid=_stable_id("POSITION",decision_id)
            for x in legs:x["strategyPositionId"]=pid
            ev=_entry_value(legs);risk=c.get("risk") if isinstance(c.get("risk"),dict) else {};ml=c.get("maxLoss") if c.get("maxLoss") is not None else risk.get("maxLossPerLot");mp=c.get("maxProfit") if c.get("maxProfit") is not None else risk.get("maxProfitPerLot");be=c.get("breakevens") or [v for v in(risk.get("lowerBreakEven"),risk.get("upperBreakEven")) if v is not None]
            p={"strategyPositionId":pid,"decisionId":decision_id,"strategyId":sid,"family":c.get("family"),"index":c.get("key"),"status":"OPEN","sessionDate":d,"expiry":c.get("expiry"),"farExpiry":c.get("farExpiry"),"expiryState":c.get("expiryState"),"legs":legs,"entryValue":ev,"entryDebit":max(0.,ev),"entryCredit":max(0.,-ev),"maxLoss":ml,"maxProfit":mp,"breakevens":be,"entryGreeks":{n:c.get(n) for n in("delta","gamma","theta","vega")},"netGreeks":{n:c.get(n) for n in("delta","gamma","theta","vega")},"entrySpot":c.get("spot"),"entryIv":c.get("atmIv"),"unrealizedPnl":0.,"realizedPnl":0.,"lifecycleState":"NO_ACTION","enteredAt":now.isoformat(),"updatedAt":now.isoformat(),"authority":"INDEX_OPTIONS_QUANT_V2","selectionModel":"COMMON_SCENARIO_DISTRIBUTION_REPRICER"}
            try:db.execute("INSERT INTO index_option_positions VALUES(?,?,?,?,?,?,?,?)",(pid,decision_id,sid,d,c.get("key"),"OPEN",json.dumps(p),now.isoformat()))
            except sqlite3.IntegrityError:continue
            db.execute("INSERT INTO index_option_events VALUES(?,?,?,?,?)",(_stable_id(pid,"OPEN"),pid,"OPENED",json.dumps(p),now.isoformat()));c["strategyPositionId"]=pid;c["paperEntryState"]="FILLED"
        db.commit()
    p=load_positions(d);return {"authority":"INDEX_OPTIONS_QUANT_V2","positions":p,"open":[x for x in p if x.get("status")=="OPEN"],"closed":[x for x in p if x.get("status")=="CLOSED"]}
def strategy_eod(d):
    p=load_positions(d);rows=[{"strategy":x.get("strategyId"),"strategyPositionId":x.get("strategyPositionId"),"authority":x.get("authority"),"entry":x.get("enteredAt"),"exit":x.get("exitedAt"),"realizedPnl":x.get("realizedPnl"),"unrealizedPnl":x.get("unrealizedPnl"),"maxLoss":x.get("maxLoss"),"maxProfit":x.get("maxProfit"),"breakevens":x.get("breakevens"),"entryGreeks":x.get("entryGreeks"),"exitGreeks":x.get("exitGreeks"),"exitReason":x.get("exitReason")} for x in p];return {"sessionDate":d,"authority":"INDEX_OPTIONS_QUANT_V2","positions":rows,"realizedPnl":round(sum(float(x.get("realizedPnl") or 0) for x in p),2),"unrealizedPnl":round(sum(float(x.get("unrealizedPnl") or 0) for x in p),2)}
