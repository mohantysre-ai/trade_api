"""Single Shoonya WebSocket: connect, subscribe to the planner's set, merge ticks, reconnect."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Awaitable, Callable

from .auth import AuthManager
from .config import Settings
from .hub import Hub
from .mapper import QuoteBook
from .planner import SubscriptionPlanner, chunks, diff
from .registry import InstrumentRegistry

log = logging.getLogger(__name__)
ConnectFn = Callable[[str], Awaitable[Any]]

async def _default_connect(url: str) -> Any:
    import websockets
    return await websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22)

class FeedManager:
    def __init__(self, settings: Settings, auth: AuthManager, registry: InstrumentRegistry, planner: SubscriptionPlanner, book: QuoteBook, hub: Hub, *, connect_fn: ConnectFn | None = None, mono: Callable[[], float] = time.monotonic) -> None:
        self._s=settings; self._auth=auth; self._registry=registry; self._planner=planner; self._book=book; self._hub=hub; self._connect=connect_fn or _default_connect; self._mono=mono
        self.connected=False; self.subscribed=set(); self.acked=set(); self.not_streaming=set(); self.unresolved=[]; self.plan_counts={}; self.p0_overflow=False; self.reconnects=0
        self._pending={}; self._key_to_name={}; self._last_sub_sent=0.; self._last_reconcile=0.; self._ws_ref=None; self._stop=False
    def stop(self): self._stop=True
    def resolve(self,name):
        if "|" in name:return name.upper()
        token=self._registry.token_for(name); return f"NSE|{token}" if token else None
    def is_subscribed(self,symbol):
        if symbol in {self._key_to_name[k] for k in self.subscribed if k in self._key_to_name}: return True
        latest=self._hub.latest(symbol); return bool(latest and f"{latest['exchange']}|{latest['token']}" in self.subscribed)
    def status(self):
        return {"wsConnected":self.connected,"subscribed":len(self.subscribed),"acked":len(self.acked & self.subscribed),"notStreaming":len(self.not_streaming),"unresolved":len(self.unresolved),"planCounts":dict(self.plan_counts),"p0Overflow":self.p0_overflow,"reconnects":self.reconnects,"registryStale":self._registry.is_stale(max_age_days=self._s.registry_max_age_days),"lastTickAgeMs":self._hub.last_tick_age_ms()}
    async def run(self):
        delay=self._s.reconnect_base_s
        while not self._stop:
            if not self._auth.authenticated or self._auth.session is None:
                await asyncio.sleep(.5); continue
            ws=None
            try:
                ws=await self._connect(self._s.ws_url); self._ws_ref=ws
                if not await self._handshake(ws): raise ConnectionError("connect ack rejected")
                delay=self._s.reconnect_base_s; await self._session(ws)
            except asyncio.CancelledError: raise
            except Exception as exc: log.warning("shoonya ws session ended: %s",type(exc).__name__)
            finally:
                self._on_disconnect()
                if ws is not None:
                    try: await ws.close()
                    except Exception: pass
            if self._stop: break
            self.reconnects+=1; await asyncio.sleep(delay+random.uniform(0,delay/2)); delay=min(delay*2,self._s.reconnect_max_s)
    def _on_disconnect(self):
        self.connected=False; self.subscribed.clear(); self.acked.clear(); self.not_streaming.clear(); self._pending.clear(); self._key_to_name.clear(); self._book.reset_connection()
    async def _handshake(self,ws):
        session=self._auth.session; assert session is not None
        await ws.send(json.dumps({"t":"a","uid":session.uid,"actid":session.account_id,"source":self._s.source,"accesstoken":session.access_token}))
        deadline=self._mono()+10.
        while self._mono()<deadline:
            raw=await asyncio.wait_for(ws.recv(),timeout=10.); msg=self._parse(raw)
            if not msg or msg.get("t")!="ak": continue
            if msg.get("s")=="Ok": self.connected=True; return True
            self._auth.mark_expired("ws connect ack Not_Ok"); return False
        return False
    @staticmethod
    def _parse(raw):
        try: msg=json.loads(raw)
        except (TypeError,ValueError): return None
        return msg if isinstance(msg,dict) else None
    async def _session(self,ws):
        last_hb=self._mono(); first=True
        while not self._stop:
            try: raw=await asyncio.wait_for(ws.recv(),timeout=.2)
            except asyncio.TimeoutError: raw=None
            if raw is not None:self._on_message(raw)
            if first or self._mono()-self._last_reconcile>=.5:
                self._last_reconcile=self._mono(); await self._reconcile(force_first=first)
            first=False; self._check_acks()
            if self._s.app_heartbeat_s and self._mono()-last_hb>=self._s.app_heartbeat_s:
                await ws.send(json.dumps({"t":"h"})); last_hb=self._mono()
            if not self._auth.authenticated:return
    def _on_message(self,raw):
        msg=self._parse(raw)
        if not msg:return
        kind=msg.get("t")
        if kind in ("tk","tf"):
            key=f"{str(msg.get('e') or '').upper()}|{msg.get('tk')}"
            if kind=="tk":
                self.acked.add(key); self._pending.pop(key,None); self.not_streaming.discard(key)
            tick=self._book.apply(msg,self._mono())
            if tick is not None:self._hub.publish(tick)
        elif kind=="ak" and msg.get("s") not in (None,"Ok"): self._auth.mark_expired("ws reported not-ok")
    def _check_acks(self):
        now=self._mono()
        for key,sent_at in list(self._pending.items()):
            if now-sent_at>self._s.ack_timeout_s: self.not_streaming.add(key); self._pending.pop(key,None)
    async def _reconcile(self,force_first=False):
        if self._registry.is_stale(max_age_days=self._s.registry_max_age_days):return
        plan=self._planner.plan(); self.plan_counts=plan.counts; self.p0_overflow=plan.p0_overflow; desired_keys=[]; unresolved=[]
        for name in plan.names:
            key=self.resolve(name)
            if key is None: unresolved.append(name); continue
            self._key_to_name[key]=name if "|" not in name else self._index_name(key); desired_keys.append(key)
        self.unresolved=unresolved; add,remove=diff(self.subscribed,desired_keys); now=self._mono()
        if not force_first and now-self._last_sub_sent<self._s.subscribe_gap_s:return
        if remove:
            batch=chunks(remove,self._s.subscribe_chunk)[0]; await self._send_sub("u",batch)
            for key in batch:self.subscribed.discard(key); self.acked.discard(key); self.not_streaming.discard(key); self._pending.pop(key,None)
            return
        if add:
            batch=chunks(add,self._s.subscribe_chunk)[0]; await self._send_sub("t",batch)
            for key in batch:self.subscribed.add(key); self._pending[key]=now
    def _index_name(self,key): return key
    async def _send_sub(self,kind,keys):
        await self._ws_ref.send(json.dumps({"t":kind,"k":"#".join(keys)})); self._last_sub_sent=self._mono()
