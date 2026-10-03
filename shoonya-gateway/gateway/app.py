from __future__ import annotations
import asyncio,logging,time
from typing import Any
from fastapi import Depends,FastAPI,Header,HTTPException,Query,WebSocket,WebSocketDisconnect
from .auth import AuthManager
from .candles import CandleBroker, parse_rows
from .config import IST,Settings
from .registry import RegistrySet
from .http import GuardedHttp
from .hub import Hub
from .feed import FeedManager
from .mapper import QuoteBook
from .planner import SubscriptionPlanner
log=logging.getLogger(__name__)
class GatewayState:
    def __init__(self,settings):
        self.settings=settings; self.registry=RegistrySet(); self.auth=AuthManager(settings); self.http=GuardedHttp(settings)
        self.planner=SubscriptionPlanner(settings.ws_max_tokens,settings.index_reserve,settings.unpin_grace_s); self.hub=Hub(); self.book=QuoteBook(settings,symbol_for_token=self._symbol_for_token); self.feed=FeedManager(settings,self.auth,self.registry.nse,self.planner,self.book,self.hub); self.candles=CandleBroker(settings,self.http,self.auth,self.registry); self._tasks=[]; self.started_at=time.monotonic()
    def _symbol_for_token(self,exch,token): return self.registry.for_exchange(exch).symbol_for(exch,token) if self.registry.for_exchange(exch) else None
    async def refresh_registry(self):
        count=self.registry.nse.load_zip(await self.http.get_bytes("/NSE_symbols.txt.zip"))
        try: count+=self.registry.nfo.load_zip(await self.http.get_bytes("/NFO_symbols.txt.zip"))
        except Exception: log.warning("shoonya NFO registry refresh failed; keeping previous copy",exc_info=True)
        try: count+=self.registry.bfo.load_zip(await self.http.get_bytes("/BFO_symbols.txt.zip"))
        except Exception: log.warning("shoonya BFO registry refresh failed; keeping previous copy",exc_info=True)
        self.planner.set_universe(index=self.settings.index_keys); return count
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
        return {"healthy":healthy,"auth":auth_status,"feed":feed_status,"registry":{"count":len(self.registry.nse)+len(self.registry.nfo)+len(self.registry.bfo),"loadedOn":self.registry.nse.loaded_on.isoformat() if self.registry.nse.loaded_on else None,"stale":self.registry.is_stale(max_age_days=self.settings.registry_max_age_days)},"uptimeSeconds":round(time.monotonic()-self.started_at,1)}
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
    async def candles(symbol:str,interval:str,from_ts:int=Query(...,alias="from"),to_ts:int=Query(...,alias="to"),exchange:str="NSE"):
        return await state.candles.fetch(symbol.strip().upper(),interval.strip().upper(),from_ts,to_ts,exchange.strip().upper())
    @app.post("/admin/oauth/code",dependencies=[Depends(_require_admin)])
    async def oauth_code(body:dict[str,Any]):
        try:
            session=await state.auth.exchange_oauth_code(str(body["code"]))
            state.auth.set_session(session.uid,session.account_id,session.access_token,session.websocket_token)
        except (KeyError,ValueError) as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
        except Exception as exc: raise HTTPException(status_code=502,detail=f"OAuth exchange failed: {type(exc).__name__}") from exc
        return {"state":state.auth.state.value}
    @app.get("/admin/oauth/url",dependencies=[Depends(_require_admin)])
    def oauth_url():
        try: return {"url":state.auth.oauth_authorize_url()}
        except Exception as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    @app.post("/admin/oauth/refresh",dependencies=[Depends(_require_admin)])
    async def oauth_refresh():
        try: await state.auth.refresh()
        except Exception as exc: raise HTTPException(status_code=502,detail=f"OAuth refresh failed: {type(exc).__name__}") from exc
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
