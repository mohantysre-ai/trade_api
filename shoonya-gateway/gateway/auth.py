"""Daily-session auth state machine."""
from __future__ import annotations
import enum,json,logging,os,time
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable,Callable
from .config import IST,Settings
log=logging.getLogger(__name__)
class AuthState(str,enum.Enum):
    AUTH_REQUIRED="AUTH_REQUIRED"; LOGGING_IN="LOGGING_IN"; AUTHENTICATED="AUTHENTICATED"; EXPIRED="EXPIRED"
class LoginUnavailable(RuntimeError): pass
@dataclass
class Session:
    uid:str; account_id:str; access_token:str; obtained_at:str
    def redacted(self): return {"uid":self.uid,"accountId":self.account_id,"obtainedAt":self.obtained_at}
LoginFn=Callable[[],Awaitable[Session]]
def _hhmm(text): h,m=text.split(":"); return int(h),int(m)
class AuthManager:
    def __init__(self,settings:Settings,login_fn:LoginFn|None=None,clock:Callable[[],datetime]=lambda:datetime.now(IST),mono:Callable[[],float]=time.monotonic)->None:
        self._s=settings; self._login_fn=login_fn; self._clock=clock; self._mono=mono; self.state=AuthState.AUTH_REQUIRED; self.session=None; self.last_error=""; self._attempts=[]; self._next_attempt_at=0.; self._backoff=30.
    def set_session(self,uid,account_id,access_token):
        if not access_token or not uid: raise ValueError("uid and access_token are required")
        self.session=Session(uid,account_id or uid,access_token,self._clock().isoformat()); self.state=AuthState.AUTHENTICATED; self.last_error=""; self._save()
    def mark_expired(self,reason):
        if self.state==AuthState.AUTHENTICATED: log.warning("shoonya session marked expired: %s",reason)
        self.state=AuthState.EXPIRED; self.last_error=reason; self.session=None; self._clear_saved()
    @property
    def authenticated(self): return self.state==AuthState.AUTHENTICATED and self.session is not None
    def _save(self):
        if not self._s.session_file or self.session is None:return
        try:
            os.makedirs(os.path.dirname(self._s.session_file) or ".",exist_ok=True)
            payload={"uid":self.session.uid,"accountId":self.session.account_id,"accessToken":self.session.access_token,"obtainedAt":self.session.obtained_at}
            tmp=self._s.session_file+".tmp"; fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,"w",encoding="utf-8") as fh: json.dump(payload,fh)
            os.replace(tmp,self._s.session_file)
        except OSError as exc: log.warning("could not persist shoonya session: %s",type(exc).__name__)
    def _clear_saved(self):
        try:
            if self._s.session_file and os.path.exists(self._s.session_file): os.remove(self._s.session_file)
        except OSError: pass
    def restore(self):
        try:
            with open(self._s.session_file,"r",encoding="utf-8") as fh:data=json.load(fh)
            if str(data.get("obtainedAt",""))[:10]!=self._clock().date().isoformat():return False
            self.session=Session(str(data["uid"]),str(data.get("accountId") or data["uid"]),str(data["accessToken"]),str(data["obtainedAt"])); self.state=AuthState.AUTHENTICATED; return True
        except (OSError,ValueError,KeyError): return False
    def in_login_window(self): now=self._clock(); h,m=_hhmm(self._s.login_hhmm); return (now.hour,now.minute)>=(h,m)
    def deadline_breached(self): now=self._clock(); h,m=_hhmm(self._s.login_deadline_hhmm); return (now.hour,now.minute)>=(h,m) and not self.authenticated
    def _attempts_left(self):
        cutoff=self._mono()-self._s.login_attempt_window_s; self._attempts=[t for t in self._attempts if t>=cutoff]; return len(self._attempts)<self._s.login_max_attempts
    async def maybe_login(self):
        if self.authenticated or self._s.auth_mode!="auto" or self._login_fn is None or not self.in_login_window(): return False
        if self._mono()<self._next_attempt_at or not self._attempts_left(): return False
        self._attempts.append(self._mono()); self.state=AuthState.LOGGING_IN
        try: session=await self._login_fn()
        except LoginUnavailable as exc:
            self.state=AuthState.AUTH_REQUIRED; self.last_error=f"login unavailable: {exc}"; self._next_attempt_at=self._mono()+self._s.login_attempt_window_s; return False
        except Exception as exc:
            self.state=AuthState.AUTH_REQUIRED; self.last_error=f"login failed: {type(exc).__name__}"; self._next_attempt_at=self._mono()+self._backoff; self._backoff=min(self._backoff*2,self._s.login_attempt_window_s); return False
        self._backoff=30.; self.set_session(session.uid,session.account_id,session.access_token); return True
    def snapshot(self): return {"state":self.state.value,"mode":self._s.auth_mode,"session":self.session.redacted() if self.session else None,"lastError":self.last_error,"deadlineBreached":self.deadline_breached()}
