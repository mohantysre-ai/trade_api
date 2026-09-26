from __future__ import annotations
import asyncio,time,uuid
from typing import Any,Callable
class Subscriber:
    def __init__(self): self.pending={}; self.event=asyncio.Event()
    def push(self,tick): self.pending[tick["symbol"]]=tick; self.event.set()
    def drain(self): items=list(self.pending.values()); self.pending.clear(); self.event.clear(); return items
class Hub:
    def __init__(self,mono:Callable[[],float]=time.monotonic)->None:
        self._mono=mono; self.epoch=uuid.uuid4().hex[:12]; self._latest={}; self._seq={}; self._subs=set(); self.last_tick_mono=None; self.tick_count=0
    def subscribe(self): sub=Subscriber(); self._subs.add(sub); return sub
    def unsubscribe(self,sub): self._subs.discard(sub)
    def publish(self,tick):
        symbol=tick["symbol"]; seq=self._seq.get(symbol,0)+1; self._seq[symbol]=seq
        stamped={**tick,"gwEpoch":self.epoch,"gwSeq":seq}; self._latest[symbol]=stamped; self.last_tick_mono=tick.get("recvMono",self._mono()); self.tick_count+=1
        for sub in self._subs: sub.push(stamped)
        return stamped
    def wire(self,tick):
        out={k:v for k,v in tick.items() if k!="recvMono"}; out["gwAgeMs"]=max(0,round((self._mono()-tick.get("recvMono",self._mono()))*1000)); return out
    def latest(self,symbol): return self._latest.get(symbol)
    def last_tick_age_ms(self): return None if self.last_tick_mono is None else max(0,int((self._mono()-self.last_tick_mono)*1000))
