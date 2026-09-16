from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, time
from pathlib import Path
from typing import Any

from .config import LEGACY_ALWAYS_ENABLED, PAPER_SLIPPAGE_POINTS

DURABLE_LEGACY_SELLERS = {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR"}


def _db_path() -> Path:
    override = os.getenv("INDEX_OPTIONS_STRATEGY_DB", "").strip()
    if override:
        return Path(override)
    from ..shared_state.sqlite_store import _DB_PATH
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    path = _db_path(); path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=10); db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=FULL"); db.execute("PRAGMA busy_timeout=10000")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS index_option_positions (
            strategy_position_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL UNIQUE, strategy_id TEXT NOT NULL,
            session_date TEXT NOT NULL, index_key TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS index_option_positions_session_idx ON index_option_positions(session_date, status);
        CREATE UNIQUE INDEX IF NOT EXISTS index_option_open_strategy_idx ON index_option_positions(session_date, index_key, strategy_id) WHERE status='OPEN';
        CREATE TABLE IF NOT EXISTS index_option_events (event_id TEXT PRIMARY KEY, strategy_position_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS index_option_shadows (shadow_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, strategy_id TEXT NOT NULL, session_date TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    return db


def _stable_id(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:24]


def _float(value: Any) -> float | None:
    try:
        result = float(value); return result if result == result else None
    except (TypeError, ValueError): return None


def _side(leg: dict[str, Any]) -> str:
    return str(leg.get("side") or leg.get("action") or "").upper()


def _entry_fill(leg: dict[str, Any], timestamp: str) -> dict[str, Any] | None:
    bid = _float(leg.get("entryBid") if leg.get("entryBid") is not None else leg.get("bestBid"))
    ask = _float(leg.get("entryAsk") if leg.get("entryAsk") is not None else leg.get("bestAsk"))
    # Legacy seller constructors expose entryPrice/ltp. Use it only when an
    # executable bid/ask pair is absent; never invent a price.
    entry = _float(leg.get("entryPrice") if leg.get("entryPrice") is not None else leg.get("ltp"))
    side = _side(leg)
    if not leg.get("symbol") or side not in {"BUY", "SELL"}:
        return None
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        fill = ask + PAPER_SLIPPAGE_POINTS if side == "BUY" else bid - PAPER_SLIPPAGE_POINTS
        midpoint = (bid + ask) / 2.0
    elif entry is not None and entry > 0:
        fill = entry; midpoint = entry
    else:
        return None
    if fill <= 0: return None
    return {**leg, "side": side, "entryBid": bid, "entryAsk": ask, "entryFill": round(fill, 4),
            "entryPrice": round(fill, 4), "entrySlippage": round(abs(fill - midpoint), 4),
            "entryTimestamp": timestamp, "currentPrice": round(fill, 4)}


def _candidate_legs(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    legs = [dict(leg) for leg in candidate.get("legs") or [] if isinstance(leg, dict)]
    if legs: return legs
    contract = candidate.get("contract") if isinstance(candidate.get("contract"), dict) else {}
    return [{**contract, "side": "BUY", "qty": 1, "expiry": candidate.get("expiry")}] if contract else []


def _entry_value(legs: list[dict[str, Any]]) -> float:
    return round(sum((1 if _side(leg) == "BUY" else -1) * float(leg["entryFill"]) * int(leg.get("qty") or 1) for leg in legs), 4)


def _quotes(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for supplied in (((snapshot.get("indexOptions") or {}).get("indices") or {}).values()):
        if not isinstance(supplied, dict): continue
        for row in [*(supplied.get("rawChain") or []), *(supplied.get("farChain") or [])]:
            if isinstance(row, dict) and row.get("symbol"): result[str(row["symbol"])] = row
    return result


def _mark_position(position: dict[str, Any], quotes: dict[str, dict[str, Any]], now: datetime, market: dict[str, Any]) -> dict[str, Any]:
    legs=[]; pnl=0.0; greeks={"delta":0.0,"gamma":0.0,"theta":0.0,"vega":0.0}; complete=True
    for stored in position.get("legs") or []:
        leg=dict(stored); quote=quotes.get(str(leg.get("symbol") or ""))
        if quote is None: complete=False; legs.append(leg); continue
        bid=_float(quote.get("bestBid")); ask=_float(quote.get("bestAsk")); ltp=_float(quote.get("ltp"))
        mark = (bid if _side(leg)=="BUY" else ask) if bid is not None and ask is not None else ltp
        if mark is None or mark<=0: complete=False; legs.append(leg); continue
        qty=int(leg.get("qty") or 1)*int(leg.get("lotSize") or 1); sign=1 if _side(leg)=="BUY" else -1
        pnl+=(mark-float(leg["entryFill"]))*qty*sign
        for name in greeks:
            value=_float(quote.get(name)); greeks[name]+= (value or 0.0)*qty*sign
        legs.append({**leg,"currentBid":bid,"currentAsk":ask,"currentPrice":round(mark,4),"currentIv":_float(quote.get("iv")),"markedAt":now.isoformat()})
    return {**position,"legs":legs,"combinedStructureValue":round(sum((1 if _side(l)=="BUY" else -1)*float(l.get("currentPrice") or 0)*int(l.get("qty") or 1) for l in legs),4),
            "unrealizedPnl":round(pnl,2),"netGreeks":{k:round(v,6) for k,v in greeks.items()},"markStatus":"LIVE" if complete else "INCOMPLETE",
            "currentSpot":_float(market.get("spot")),"currentIv":_float(market.get("atmIv")),"structuralInvalidated":str((market.get("structure") or {}).get("status") or "").upper()=="INVALIDATED",
            "lifecycleState":"NO_ACTION","updatedAt":now.isoformat()}


def _exit_reason(position: dict[str, Any], now: datetime) -> str | None:
    family=str(position.get("family") or ""); pnl=float(position.get("unrealizedPnl") or 0); max_loss=abs(float(position.get("maxLoss") or 0)); max_profit=abs(float(position.get("maxProfit") or 0))
    limits={"DIRECTIONAL":(0.50,0.50,time(15,20)),"VOLATILITY_EXPANSION":(0.40,0.35,time(15,15)),"RANGE":(0.40,0.50,time(15,0)),"TERM_STRUCTURE":(0.25,0.30,time(15,0))}
    profit_fraction,loss_fraction,cutoff=limits.get(family,(0.50,0.35,time(15,20)))
    if position.get("structuralInvalidated"): return "STRUCTURAL_INVALIDATION"
    if max_profit and pnl>=max_profit*profit_fraction: return "PROFIT_TARGET"
    if max_loss and pnl<=-(max_loss*loss_fraction): return "STRUCTURE_RISK_STOP"
    if str(position.get("expiryState") or "")=="EXPIRY_CUTOFF": return "EXPIRY_CUTOFF"
    if now.timetz().replace(tzinfo=None)>=cutoff: return "TIME_EXIT"
    return None


def _close(position: dict[str, Any], reason: str, now: datetime) -> dict[str, Any]:
    legs=[]
    for leg in position.get("legs") or []:
        exit_fill=leg.get("currentPrice"); bid=_float(leg.get("currentBid")); ask=_float(leg.get("currentAsk")); midpoint=(bid+ask)/2 if bid is not None and ask is not None else None
        slippage=abs(float(exit_fill)-midpoint) if exit_fill is not None and midpoint is not None else None
        legs.append({**leg,"exitBid":bid,"exitAsk":ask,"exitFill":exit_fill,"exitSlippage":None if slippage is None else round(slippage,4),"exitTimestamp":now.isoformat()})
    return {**position,"legs":legs,"status":"CLOSED","exitReason":reason,"exitedAt":now.isoformat(),"realizedPnl":round(float(position.get("unrealizedPnl") or 0),2),"unrealizedPnl":0.0,
            "exitGreeks":position.get("netGreeks"),"exitSpot":position.get("currentSpot"),"exitIv":position.get("currentIv"),"lifecycleState":"EXIT_ALL","updatedAt":now.isoformat()}


def _save_position(db: sqlite3.Connection, position: dict[str, Any]) -> None:
    db.execute("UPDATE index_option_positions SET status=?, payload_json=?, updated_at=? WHERE strategy_position_id=?",(position["status"],json.dumps(position),position["updatedAt"],position["strategyPositionId"]))


def load_positions(session_date: str | None = None) -> list[dict[str, Any]]:
    with _connect() as db:
        rows=db.execute("SELECT payload_json FROM index_option_positions WHERE session_date=? ORDER BY updated_at",(session_date,)).fetchall() if session_date else db.execute("SELECT payload_json FROM index_option_positions ORDER BY updated_at").fetchall()
    return [json.loads(row[0]) for row in rows]


def load_events(strategy_position_id: str) -> list[dict[str, Any]]:
    with _connect() as db: rows=db.execute("SELECT event_type, payload_json FROM index_option_events WHERE strategy_position_id=? ORDER BY created_at",(strategy_position_id,)).fetchall()
    return [{"eventType":row[0],"payload":json.loads(row[1])} for row in rows]


def load_shadows(session_date: str) -> list[dict[str, Any]]:
    with _connect() as db: rows=db.execute("SELECT payload_json FROM index_option_shadows WHERE session_date=? ORDER BY created_at",(session_date,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def process_strategy_cycle(radar: dict[str, Any], snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    session_date=now.date().isoformat(); quotes=_quotes(snapshot)
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row in db.execute("SELECT payload_json FROM index_option_positions WHERE session_date=? AND status='OPEN'",(session_date,)).fetchall():
            stored=json.loads(row[0]); market=(((snapshot.get("indexOptions") or {}).get("indices") or {}).get(stored.get("index")) or {})
            marked=_mark_position(stored,quotes,now,market); reason=_exit_reason(marked,now) if marked.get("markStatus")=="LIVE" else None; updated=_close(marked,reason,now) if reason else marked; _save_position(db,updated)
            if reason: db.execute("INSERT OR IGNORE INTO index_option_events VALUES (?, ?, ?, ?, ?)",(_stable_id(updated["strategyPositionId"],"CLOSE"),updated["strategyPositionId"],"CLOSED",json.dumps(updated),now.isoformat()))
        modular=radar.get("modularCandidates") or []; selected_ids={str(r.get("strategyId"))+"|"+str(r.get("key")) for r in radar.get("modularSelected") or []}
        for candidate in modular:
            strategy_id=str(candidate.get("strategyId") or candidate.get("strategyType") or "")
            if (strategy_id in LEGACY_ALWAYS_ENABLED and strategy_id not in DURABLE_LEGACY_SELLERS) or not candidate.get("eligible"): continue
            identity=strategy_id+"|"+str(candidate.get("key")); decision_id=_stable_id(session_date,identity,candidate.get("snapshotId") or candidate.get("decisionTimestamp"))
            if identity not in selected_ids:
                db.execute("INSERT OR IGNORE INTO index_option_shadows VALUES (?, ?, ?, ?, ?, ?)",(_stable_id("SHADOW",decision_id),decision_id,strategy_id,session_date,json.dumps(candidate),now.isoformat())); continue
            if db.execute("SELECT COUNT(*) FROM index_option_positions WHERE session_date=? AND status='OPEN'",(session_date,)).fetchone()[0]>=2:
                candidate["paperEntryState"]="ENTRY_BLOCKED"; candidate["paperEntryReason"]="MAX_CONCURRENT_REACHED"; continue
            if db.execute("SELECT 1 FROM index_option_positions WHERE decision_id=? OR (session_date=? AND index_key=? AND strategy_id=? AND status='OPEN')",(decision_id,session_date,candidate.get("key"),strategy_id)).fetchone(): continue
            fills=[_entry_fill(leg,now.isoformat()) for leg in _candidate_legs(candidate)]
            if not fills or any(fill is None for fill in fills): candidate["paperEntryState"]="ENTRY_BLOCKED"; candidate["paperEntryReason"]="MANDATORY_LEG_UNPRICED"; continue
            legs=[fill for fill in fills if fill is not None]; position_id=_stable_id("POSITION",decision_id)
            for leg in legs: leg["strategyPositionId"]=position_id
            entry_value=_entry_value(legs); risk=candidate.get("risk") if isinstance(candidate.get("risk"),dict) else {}
            max_loss=candidate.get("maxLoss") if candidate.get("maxLoss") is not None else risk.get("maxLossPerLot"); max_profit=candidate.get("maxProfit") if candidate.get("maxProfit") is not None else risk.get("maxProfitPerLot")
            breakevens=candidate.get("breakevens") or [v for v in (risk.get("lowerBreakEven"),risk.get("upperBreakEven")) if v is not None]
            position={"strategyPositionId":position_id,"decisionId":decision_id,"strategyId":strategy_id,"family":candidate.get("family"),"index":candidate.get("key"),"status":"OPEN","sessionDate":session_date,
                      "expiry":candidate.get("expiry"),"farExpiry":candidate.get("farExpiry"),"expiryState":candidate.get("expiryState"),"legs":legs,"entryValue":entry_value,"entryDebit":max(0.0,entry_value),"entryCredit":max(0.0,-entry_value),
                      "maxLoss":max_loss,"maxProfit":max_profit,"breakevens":breakevens,"entryGreeks":{n:candidate.get(n) for n in ("delta","gamma","theta","vega")},"netGreeks":{n:candidate.get(n) for n in ("delta","gamma","theta","vega")},
                      "entrySpot":candidate.get("spot"),"entryIv":candidate.get("atmIv"),"unrealizedPnl":0.0,"realizedPnl":0.0,"lifecycleState":"NO_ACTION","enteredAt":now.isoformat(),"updatedAt":now.isoformat(),
                      "authority":"MULTI_LEG_STRATEGY_BOOK","legacyProjectionEligible":strategy_id in DURABLE_LEGACY_SELLERS}
            try: db.execute("INSERT INTO index_option_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",(position_id,decision_id,strategy_id,session_date,candidate.get("key"),"OPEN",json.dumps(position),now.isoformat()))
            except sqlite3.IntegrityError: continue
            db.execute("INSERT INTO index_option_events VALUES (?, ?, ?, ?, ?)",(_stable_id(position_id,"OPEN"),position_id,"OPENED",json.dumps(position),now.isoformat())); candidate["strategyPositionId"]=position_id; candidate["paperEntryState"]="FILLED"
        db.commit()
    positions=load_positions(session_date)
    return {"positions":positions,"open":[r for r in positions if r.get("status")=="OPEN"],"closed":[r for r in positions if r.get("status")=="CLOSED"]}


def strategy_eod(session_date: str) -> dict[str, Any]:
    positions=load_positions(session_date); rows=[]
    for p in positions:
        rows.append({"strategy":p.get("strategyId"),"strategyPositionId":p.get("strategyPositionId"),"entry":p.get("enteredAt"),"exit":p.get("exitedAt"),"realizedPnl":p.get("realizedPnl"),"unrealizedPnl":p.get("unrealizedPnl"),
                     "maxLoss":p.get("maxLoss"),"maxProfit":p.get("maxProfit"),"breakevens":p.get("breakevens"),"holdingTime":{"from":p.get("enteredAt"),"to":p.get("exitedAt")},"entryGreeks":p.get("entryGreeks"),"exitGreeks":p.get("exitGreeks"),
                     "spotMove":None if p.get("exitSpot") is None else round(float(p["exitSpot"])-float(p.get("entrySpot") or 0),4),"ivMove":None if p.get("exitIv") is None else round(float(p["exitIv"])-float(p.get("entryIv") or 0),4),"exitReason":p.get("exitReason")})
    return {"sessionDate":session_date,"positions":rows,"realizedPnl":round(sum(float(r.get("realizedPnl") or 0) for r in positions),2),"unrealizedPnl":round(sum(float(r.get("unrealizedPnl") or 0) for r in positions),2)}
