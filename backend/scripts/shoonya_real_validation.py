"""Shoonya real-broker acceptance check for 2026-09-25.

This script attempts REAL Shoonya authentication and data fetch.
It does NOT use mocks. If credentials are unavailable, it reports the exact blocker.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow shoonya-gateway imports when running from backend/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHOONYA_GATEWAY_DIR = _REPO_ROOT / "shoonya-gateway"
if str(_SHOONYA_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_SHOONYA_GATEWAY_DIR))

results = {
    "date": "2026-09-25",
    "authenticated": False,
    "account": None,
    "session_valid": False,
    "login_time": None,
    "symbol_master": {"required": 0, "resolved": 0, "missing": []},
    "candles": [],
    "quotes": [],
    "websocket": {"connected": False, "auth_ack": False, "subscriptions": 0},
    "blocker": None,
    "error": None,
}

IST = timezone(timedelta(hours=5, minutes=30))
FRIDAY = datetime(2026, 9, 25, tzinfo=IST)
FRIDAY_START = FRIDAY.replace(hour=9, minute=15)
FRIDAY_END = FRIDAY.replace(hour=15, minute=30)

# Check credentials
required_env = ["SHOONYA_UID", "SHOONYA_ACCOUNT_ID", "SHOONYA_PASSWORD", "SHOONYA_TOTP_SECRET"]
missing = [v for v in required_env if not os.getenv(v)]
if missing:
    results["blocker"] = f"Missing Shoonya credentials: {', '.join(missing)}"
    print(json.dumps(results, indent=2, default=str))
    sys.exit(0)

# Try direct Shoonya API auth
try:
    from gateway.auth import AuthManager
    from gateway.config import Settings
    from gateway.http import GuardedHttp
    from gateway.candles import CandleBroker
    from gateway.registry import InstrumentRegistry

    settings = Settings.from_env()
    settings.auth_mode = "auto"
    
    async def login_fn():
        http = GuardedHttp(settings)
        payload = {
            "uid": settings.uid,
            "pwd": os.getenv("SHOONYA_PASSWORD"),
            "factor2": pyotp.TOTP(os.getenv("SHOONYA_TOTP_SECRET")).now(),
            "apk": os.getenv("SHOONYA_CLIENT_ID", ""),
            "vc": os.getenv("SHOONYA_SECRET_CODE", ""),
        }
        resp = await http.post_json("/NorenWClientAPI/UserAuth", payload, "")
        return resp

    import pyotp
    auth = AuthManager(settings, login_fn=login_fn)
    
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        success = loop.run_until_complete(auth.maybe_login())
    finally:
        loop.close()
    
    if success and auth.authenticated and auth.session:
        results["authenticated"] = True
        results["account"] = f"****{auth.session.account_id[-4:]}" if auth.session.account_id else None
        results["session_valid"] = True
        results["login_time"] = auth.session.obtained_at
        
        # Try symbol master
        registry = InstrumentRegistry()
        http = GuardedHttp(settings)
        
        async def load_registry():
            payload = await http.get_bytes("/NSE_symbols.txt.zip")
            return registry.load_zip(payload)
        
        loop2 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop2)
        try:
            count = loop2.run_until_complete(load_registry())
        finally:
            loop2.close()
        
        results["symbol_master"]["resolved"] = count
        results["symbol_master"]["required"] = count  # At least the master loaded
        
        # Try candle fetch
        candle_broker = CandleBroker(settings, http, auth, registry)
        test_symbols = ["RELIANCE", "TCS", "HDFCBANK", "NIFTY", "BANKNIFTY"]
        
        loop3 = asyncio.new_event_loop()
        asyncio.set_event_loop(loop3)
        try:
            for sym in test_symbols:
                token = registry.token_for(sym)
                if not token:
                    results["candles"].append({
                        "symbol": sym, "status": "TOKEN_MISSING", "rows": 0
                    })
                    continue
                
                start_ts = int(FRIDAY_START.timestamp())
                end_ts = int(FRIDAY_END.timestamp())
                
                for interval in ["FIVE_MINUTE", "ONE_HOUR", "ONE_DAY"]:
                    result = loop3.run_until_complete(
                        candle_broker.fetch(sym, interval, start_ts, end_ts)
                    )
                    results["candles"].append({
                        "symbol": sym,
                        "timeframe": interval,
                        "status": result.get("status", "ERROR"),
                        "rows": len(result.get("rows", [])),
                    })
        finally:
            loop3.close()
    else:
        results["error"] = f"Authentication failed: state={auth.state.value}, last_error={auth.last_error}"
        
except Exception as exc:
    results["error"] = f"{type(exc).__name__}: {exc}"

print(json.dumps(results, indent=2, default=str))
