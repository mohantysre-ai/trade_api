from __future__ import annotations
import threading,time
from dataclasses import dataclass,field
from typing import Callable,Iterable
def _n(value:str)->str:return str(value or "").strip().upper()
@dataclass
class _Owner:
    names:list[str]; expires_at:float|None=None; released_at:float|None=None
@dataclass
class Plan:
    names:list[str]=field(default_factory=list); counts:dict[str,int]=field(default_factory=dict); p0_overflow:bool=False; dropped_p0:list[str]=field(default_factory=list)
class SubscriptionPlanner:
    def __init__(self,max_tokens:int,index_reserve:int=20,unpin_grace_s:float=60.0,clock:Callable[[],float]=time.monotonic)->None:
        self.max_tokens=max(1,int(max_tokens)); self.index_reserve=max(0,int(index_reserve)); self.unpin_grace_s=float(unpin_grace_s); self._clock=clock; self._lock=threading.RLock(); self._owners={}; self._index=[]; self._candidates=[]; self._fill=[]
    def pin(self,owner:str,names:Iterable[str],ttl_s:float|None=None)->int:
        owner=str(owner or "").strip(); cleaned=list(dict.fromkeys(n for n in (_n(x) for x in names) if n))
        if not owner:return 0
        now=self._clock()
        with self._lock:self._owners[owner]=_Owner(cleaned,(now+float(ttl_s)) if ttl_s else None)
        return len(cleaned)
    def unpin(self,owner:str)->None:
        with self._lock:
            entry=self._owners.get(str(owner or "").strip())
            if entry is not None and entry.released_at is None: entry.released_at=self._clock()
    def set_universe(self,index=None,candidates=None,fill=None):
        with self._lock:
            if index is not None:self._index=list(dict.fromkeys(_n(x) for x in index if _n(x)))
            if candidates is not None:self._candidates=list(dict.fromkeys(_n(x) for x in candidates if _n(x)))
            if fill is not None:self._fill=list(dict.fromkeys(_n(x) for x in fill if _n(x)))
    def _active_owner_names(self,now):
        out=[]; dead=[]
        for owner,entry in self._owners.items():
            if entry.expires_at is not None and now>=entry.expires_at: dead.append(owner); continue
            if entry.released_at is not None and now>=entry.released_at+self.unpin_grace_s: dead.append(owner); continue
            out.extend(entry.names)
        for owner in dead:self._owners.pop(owner,None)
        return list(dict.fromkeys(out))
    def pinned_owners(self):
        now=self._clock()
        with self._lock:self._active_owner_names(now); return {o:len(e.names) for o,e in self._owners.items()}
    def plan(self):
        now=self._clock()
        with self._lock:p0_all=self._active_owner_names(now); index=list(self._index); candidates=list(self._candidates); fill=list(self._fill)
        budget=self.max_tokens; chosen=[]; seen=set()
        def take(source,limit):
            taken=0
            for name in source:
                if taken>=limit or len(chosen)>=budget:break
                if name in seen:continue
                seen.add(name); chosen.append(name); taken+=1
            return taken
        p0=take(p0_all,budget); dropped=[n for n in p0_all if n not in seen]; p1=take(index,min(self.index_reserve,budget-len(chosen))); p2=take(candidates,budget-len(chosen)); p3=take(fill,budget-len(chosen))
        return Plan(chosen,{"p0":p0,"p1":p1,"p2":p2,"p3":p3},bool(dropped),dropped)
def diff(current:set[str],desired:list[str]): want=set(desired); return [n for n in desired if n not in current],sorted(n for n in current if n not in want)
def chunks(items:list[str],size:int): size=max(1,int(size)); return [items[i:i+size] for i in range(0,len(items),size)]
