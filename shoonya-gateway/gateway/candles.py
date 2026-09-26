from __future__ import annotations
import asyncio,time
from collections import deque
from datetime import datetime
from typing import Any,Callable
from .auth import AuthManager
from .config import IST,Settings
from .http import GuardedHttp
from .registry import InstrumentRegistry
TPSERIES="/NorenWClientAPI/TPSeries"
INTERVALS={"ONE_MINUTE":1,"FIVE_MINUTE":5,"FIFTEEN_MINUTE":15,"THIRTY_MINUTE":30,"ONE_HOUR":60}
class TokenBucket:
    def __init__(self,rate,burst,clock=time.monotonic): self.rate=max(.01,float(rate)); self.burst=max(1,int(burst)); self._tokens=float(self.burst); self._clock=clock; self._last=clock(); self._lock=asyncio.Lock()
    async def acquire(self,timeout):
        deadline=self._clock()+timeout
        while True:
            async with self._lock:
                now=self._clock(); self._tokens=min(self.burst,self._tokens+(now-self._last)*self.rate); self._last=now
                if self._tokens>=1: self._tokens-=1; return True
                wait=(1-self._tokens)/self.rate
            if self._clock()+wait>deadline:return False
            await asyncio.sleep(min(wait,.25))
def parse_time(text):
    for fmt in ("%d-%m-%Y %H:%M:%S","%Y-%m-%d %H:%M:%S"):
        try:return datetime.strptime(str(text).strip(),fmt).replace(tzinfo=IST)
        except ValueError:continue
    return None
def parse_rows(payload):
    if not isinstance(payload,list):raise ValueError("TPSeries returned a non-list body")
    rows=[]
    for item in payload:
        if not isinstance(item,dict) or "time" not in item:continue
        stamp=parse_time(item["time"])
        try:o,h,l,c=(float(item[k]) for k in ("into","inth","intl","intc")); volume=float(item.get("intv") or 0)
        except (KeyError,TypeError,ValueError):continue
        if stamp is None or min(o,h,l,c)<=0:continue
        rows.append((stamp,[stamp.strftime("%Y-%m-%d %H:%M:%S"),o,h,l,c,volume]))
    rows.sort(key=lambda pair:pair[0]); return [row for _,row in rows]
class CandleBroker:
    def __init__(self,settings,http,auth,registry,clock=time.monotonic): self._s=settings; self._http=http; self._auth=auth; self._registry=registry; self._clock=clock; self._bucket=TokenBucket(settings.rest_rps,settings.rest_burst,clock); self._calls=deque(); self._circuit_until=0.; self._serial=asyncio.Lock()
    def circuit_open(self): return self._clock()<self._circuit_until
    def _trip(self): self._circuit_until=self._clock()+self._s.candle_circuit_s
    def _minute_budget_ok(self):
        now=self._clock()
        while self._calls and now-self._calls[0]>60:self._calls.popleft()
        return len(self._calls)<self._s.candle_max_per_min
    async def fetch(self,symbol,interval,start_ts,end_ts):
        intrv=INTERVALS.get(interval)
        if intrv is None:return {"status":"UNSUPPORTED","rows":[]}
        if not self._auth.authenticated or self._auth.session is None:return {"status":"AUTH_REQUIRED","rows":[]}
        token=self._registry.token_for(symbol)
        if not token:return {"status":"UNKNOWN_SYMBOL","rows":[]}
        if self.circuit_open() or not self._minute_budget_ok():return {"status":"RATE_LIMITED","rows":[]}
        if not await self._bucket.acquire(3.):return {"status":"RATE_LIMITED","rows":[]}
        session=self._auth.session
        async with self._serial:
            self._calls.append(self._clock())
            try:payload=await self._http.post_json(TPSERIES,{"uid":session.uid,"exch":"NSE","token":token,"st":str(int(start_ts)),"et":str(int(end_ts)),"intrv":str(intrv)},session.access_token)
            except Exception as exc:return {"status":"ERROR","rows":[],"error":type(exc).__name__}
        if isinstance(payload,dict):
            message=str(payload.get("emsg") or "")
            if "Rate_Limited" in message:self._trip(); return {"status":"RATE_LIMITED","rows":[]}
            if "session" in message.lower():self._auth.mark_expired("candle request rejected the session"); return {"status":"AUTH_REQUIRED","rows":[]}
            return {"status":"ERROR","rows":[],"error":message[:120]}
        try:return {"status":"OK","rows":parse_rows(payload)}
        except ValueError as exc:return {"status":"ERROR","rows":[],"error":str(exc)}
