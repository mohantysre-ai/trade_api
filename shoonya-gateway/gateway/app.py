from __future__ import annotations
import asyncio,logging,time
from typing import Any
from fastapi import Depends,FastAPI,Header,HTTPException,Query,WebSocket,WebSocketDisconnect
from .auth import AuthManager
from .candles import CandleBroker
from .config import Settings
from .http import GuardedHttp
from .hub import Hub
from .feed import FeedManager
from .mapper import QuoteBook
from .planner import SubscriptionPlanner
from .registry import InstrumentRegistry
log=logging.getLogger(__name__)
class GatewayState:
    def __init__(self,settings):
        self.settings=settings; self.registry=InstrumentRegistry(); self.auth=AuthManager(settings); self.http=GuardedHttp(settings)
        self.planner=SubscriptionPlanner(settings.ws_max_tokens,settings.index_reserve,settings.unpin_grace_s); self.hub=Hub(); self.book=QuoteBook(settings,symbol_for_token=self._symbol_for_token); self.feed=FeedManager(settings,self.auth,self.registry,self.planner,self.book,self.hub); self.candles=CandleBroker(settings,self.http,self.auth,self.registry); self._tasks=[]; self.started_at=time.monotonic()
    def _symbol_for_token(self,exch,token): return self.registry.symbol_for(exch,token)
    async def refresh_registry(self):
        payload=await self.http.get_bytes("/NSE_symbols.txt.zip"); count=self.registry.load_zip(payload); self.planner.set_universe(index=self.settings.index_keys); return count
    async def start(self):
        self.auth.restore(); self.planner.set_universe(index=self.settings.index_keys); self._tasks.append(asyncio.create_task(self.feed.run())); self._tasks.append(asyncio.create_task(self._background()))
    async def _background(self):
        while True:
            try:
                if self.registry.is_stale(max_age_days=self.settings.registry_max_age_days): await self.refresh_registry()
            except Exception: log.warning("shoonya registry refresh failed; keeping previous copy",exc_info=True)
            try: await self.auth.maybe_login()
            except Exception: log.exception("automated shoonya login attempt raised")
            await asyncio.sleep(30.)
    async def stop(self):
        self.feed.stop()
        for task in self._tasks: task.cancel()
        await self.http.aclose()
    def health(self):
        feed_status=self.feed.status(); auth_status=self.auth.snapshot(); healthy=auth_status["state"]=="AUTHENTICATED" and feed_status["wsConnected"]; age_ms=feed_status.get("lastTickAgeMs")
        if healthy and age_ms is not None and age_ms>self.settings.quote_stale_s*1000*3: healthy=False
        return {"healthy":healthy,"auth":auth_status,"feed":feed_status,"registry":{"count":len(self.registry),"loadedOn":self.registry.loaded_on.isoformat() if self.registry.loaded_on else None,"stale":self.registry.is_stale(max_age_days=self.settings.registry_max_age_days)},"uptimeSeconds":round(time.monotonic()-self.started_at,1)}
def create_app(settings:Settings|None=None)->FastAPI:
    settings=settings or Settings.from_env(); state=GatewayState(settings); app=FastAPI(title="shoonya-standby-gateway"); app.state.gw=state
    def _require_bearer(authorization:str|None=Header(default=None)):
        if settings.gateway_token and authorization!=f"Bearer {settings.gateway_token}": raise HTTPException(status_code=401,detail="unauthorized")
    def _require_admin(x_admin_token:str|None=Header(default=None)):
        if not settings.admin_token or x_admin_token!=settings.admin_token: raise HTTPException(status_code=401,detail="unauthorized")
    @app.on_event("startup")
    async def _startup(): await state.start()
    @app.on_event("shutdown")
    async def _shutdown(): await state.stop()
    @app.get("/v1/health")
    def health(): return state.health()
    @app.get("/v1/quotes",dependencies=[Depends(_require_bearer)])
    def quotes(symbols:str=Query(...)):
        out={}
        for raw in symbols.split(","):
            sym=raw.strip().upper()
            if not sym: continue
            tick=state.hub.latest(sym); out[sym]=state.hub.wire(tick) if tick else {"status":"NOT_SUBSCRIBED"}
        return {"quotes":out}
    @app.post("/v1/pin",dependencies=[Depends(_require_bearer)])
    def pin(body:dict[str,Any]):
        owner=str(body.get("owner") or ""); symbols=body.get("symbols") or []; ttl=body.get("ttlSeconds")
        if not owner: raise HTTPException(status_code=422,detail="owner is required")
        return {"owner":owner,"pinned":state.planner.pin(owner,symbols,ttl_s=float(ttl) if ttl else None)}
    @app.post("/v1/unpin",dependencies=[Depends(_require_bearer)])
    def unpin(body:dict[str,Any]):
        owner=str(body.get("owner") or "")
        if not owner: raise HTTPException(status_code=422,detail="owner is required")
        state.planner.unpin(owner); return {"owner":owner,"released":True}
    @app.get("/v1/candles",dependencies=[Depends(_require_bearer)])
    async def candles(symbol:str,interval:str,from_ts:int=Query(...,alias="from"),to_ts:int=Query(...,alias="to")):
        return await state.candles.fetch(symbol.strip().upper(),interval.strip().upper(),from_ts,to_ts)
    @app.post("/admin/oauth/code",dependencies=[Depends(_require_admin)])
    def oauth_code(body:dict[str,Any]):
        try: state.auth.set_session(uid=str(body["uid"]),account_id=str(body.get("accountId") or body["uid"]),access_token=str(body["accessToken"]))
        except (KeyError,ValueError) as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
        return {"state":state.auth.state.value}
    @app.websocket("/v1/stream")
    async def stream(ws:WebSocket):
        if settings.gateway_token and ws.query_params.get("token")!=settings.gateway_token: await ws.close(code=4401); return
        await ws.accept(); sub=state.hub.subscribe(); owner=f"ws-{id(sub)}"
        try:
            while True:
                recv_task=asyncio.create_task(ws.receive_json()); wait_task=asyncio.create_task(sub.event.wait()); done,pending=await asyncio.wait({recv_task,wait_task},timeout=1.,return_when=asyncio.FIRST_COMPLETED)
                for task in pending: task.cancel()
                if recv_task in done:
                    try: msg=recv_task.result()
                    except WebSocketDisconnect: break
                    except Exception: continue
                    if msg.get("op")=="pin": state.planner.pin(owner,msg.get("symbols") or [],ttl_s=msg.get("ttlSeconds"))
                    elif msg.get("op")=="unpin": state.planner.unpin(owner)
                if wait_task in done or sub.pending:
                    for tick in sub.drain(): await ws.send_json({"type":"tick","data":state.hub.wire(tick)})
                await ws.send_json({"type":"heartbeat","data":state.health()})
        except WebSocketDisconnect: pass
        finally: state.hub.unsubscribe(sub); state.planner.unpin(owner)
    return app
