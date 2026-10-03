"""Shoonya touchline (tk full snapshot, tf diff) -> normalized quote ticks."""
from __future__ import annotations
import math
from typing import Any, Callable
from .config import Settings
_IST_OFFSET_S = 19800
def norm_symbol(value: Any) -> str:
    text = str(value or "").upper().strip()
    for suffix in ("-EQ","-BE","-BZ"):
        if text.endswith(suffix): text=text[:-len(suffix)]
    return text.replace(" ","")
def num(value: Any) -> float | None:
    try: out=float(value)
    except (TypeError,ValueError): return None
    return out if math.isfinite(out) else None
def positive(value: Any) -> float | None:
    out=num(value); return out if out is not None and out>0 else None
class QuoteBook:
    def __init__(self,settings:Settings,symbol_for_token:Callable[[str,str],str|None]|None=None)->None:
        self._settings=settings; self._symbol_for_token=symbol_for_token or (lambda exch,token:None)
        self._raw={}; self._last_ft={}
    def reset_connection(self)->None: self._raw.clear(); self._last_ft.clear()
    def raw(self,exch:str,token:str): 
        row=self._raw.get((exch,token)); return dict(row) if row is not None else None
    def _exchange_ts_ms(self,ft):
        value=num(ft)
        if value is None or value<=0:return None
        if self._settings.ft_mode=="epoch_ist_shifted": value-=_IST_OFFSET_S
        return int(value*1000)
    def apply(self,msg:dict[str,Any],recv_mono:float):
        kind=msg.get("t")
        if kind not in ("tk","tf"): return None
        exch=str(msg.get("e") or "").upper(); token=str(msg.get("tk") or "")
        if not exch or not token:return None
        key=(exch,token); state=self._raw.setdefault(key,{})
        for field,value in msg.items():
            if field not in ("t","e","tk"): state[field]=value
        has_lp="lp" in msg; ft_value=num(msg.get("ft")); ft_int=int(ft_value) if ft_value is not None else None; heartbeat=False
        if not has_lp:
            last_ft=self._last_ft.get(key)
            if self._settings.ft_is_heartbeat and ft_int is not None and (last_ft is None or ft_int>last_ft): heartbeat=True
            else:return None
        ltp=positive(state.get("lp"))
        if ltp is None:return None
        if ft_int is not None:self._last_ft[key]=ft_int
        ts=str(state.get("ts") or ""); symbol=norm_symbol(ts) if ts else ""
        if not symbol:symbol=norm_symbol(self._symbol_for_token(exch,token) or "")
        if not symbol:return None
        tick={"symbol":symbol,"exchange":exch,"token":token,"ltp":ltp,"open":positive(state.get("o")),"high":positive(state.get("h")),"low":positive(state.get("l")),"volume":num(state.get("v")),"bid":positive(state.get("bp1")),"ask":positive(state.get("sp1")),"bidQty":num(state.get("bq1")),"askQty":num(state.get("sq1")),"oi":num(state.get("oi")),"exchangeTsMs":self._exchange_ts_ms(state.get("ft")),"heartbeat":heartbeat,"recvMono":recv_mono}
        if self._settings.trust_c_as_prev_close: tick["prevClose"]=positive(state.get("c"))
        return tick
