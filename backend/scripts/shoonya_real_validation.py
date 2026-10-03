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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHOONYA_GATEWAY_DIR = _REPO_ROOT / "shoonya-gateway"
if str(_SHOONYA_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_SHOONYA_GATEWAY_DIR))

try:
    from dotenv import load_dotenv
    _GATEWAY_ENV = _REPO_ROOT / "shoonya-gateway" / ".env"
    _BACKEND_ENV = _REPO_ROOT / "backend" / ".env"
    if _GATEWAY_ENV.exists():
        load_dotenv(str(_GATEWAY_ENV), override=False)
    if _BACKEND_ENV.exists():
        load_dotenv(str(_BACKEND_ENV), override=False)
except Exception:
    pass

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

required_env = ["SHOONYA_UID", "SHOONYA_ACCOUNT_ID", "SHOONYA_PASSWORD", "SHOONYA_TOTP_SECRET"]
missing = [v for v in required_env if not os.getenv(v)]
if missing:
    results["blocker"] = f"Missing Shoonya credentials: {', '.join(missing)}"
    print(json.dumps(results, indent=2, default=str))
    sys.exit(0)

try:
    import requests
    import pyotp
    import websockets
    import asyncio

    base_url = os.getenv("SHOONYA_API_BASE", "https://api.shoonya.com")
    ws_url = os.getenv("SHOONYA_WS_URL", "wss://api.shoonya.com/NorenWSAPI/")
    uid = os.getenv("SHOONYA_UID", "")
    account_id = os.getenv("SHOONYA_ACCOUNT_ID", "") or uid
    password = os.getenv("SHOONYA_PASSWORD", "")
    totp_secret = os.getenv("SHOONYA_TOTP_SECRET", "")
    client_id = os.getenv("SHOONYA_CLIENT_ID", "")
    secret_code = os.getenv("SHOONYA_SECRET_CODE", "")

    totp = pyotp.TOTP(totp_secret).now()
    auth_payload = {
        "uid": uid,
        "pwd": password,
        "factor2": totp,
        "apk": client_id,
        "vc": secret_code,
    }

    auth_resp = requests.post(
        f"{base_url}/NorenWClientAPI/UserAuth",
        json=auth_payload,
        timeout=15,
    )
    auth_data = auth_resp.json() if auth_resp.status_code == 200 else {}
    if not auth_data.get("status"):
        results["error"] = f"Shoonya auth failed: {auth_data.get('message', auth_data)}"
        print(json.dumps(results, indent=2, default=str))
        sys.exit(0)

    access_token = auth_data.get("data", {}).get("token", "")
    results["authenticated"] = True
    results["account"] = f"****{account_id[-4:]}" if len(account_id) >= 4 else f"****{account_id}"
    results["session_valid"] = True
    results["login_time"] = datetime.now(IST).isoformat()

    headers = {"Authorization": f"Bearer {access_token}"}

    symbol_master_resp = requests.get(
        f"{base_url}/NSE_symbols.txt.zip",
        headers=headers,
        timeout=30,
    )
    if symbol_master_resp.status_code == 200:
        from gateway.registry import InstrumentRegistry
        registry = InstrumentRegistry()
        count = registry.load_zip(symbol_master_resp.content)
        results["symbol_master"]["required"] = count
        results["symbol_master"]["resolved"] = count
    else:
        results["symbol_master"]["required"] = 0
        results["symbol_master"]["resolved"] = 0
        results["symbol_master"]["missing"] = [f"HTTP {symbol_master_resp.status_code}"]

    test_symbols = ["RELIANCE", "TCS", "HDFCBANK", "NIFTY", "BANKNIFTY"]
    for sym in test_symbols:
        token = registry.token_for(sym) if 'registry' in dir() else None
        if not token:
            results["candles"].append({
                "symbol": sym, "timeframe": "FIVE_MINUTE", "status": "TOKEN_MISSING", "rows": 0
            })
            continue

        for interval, label in [
            ("FIVE_MINUTE", "5m"), ("ONE_HOUR", "1h"), ("ONE_DAY", "daily")
        ]:
            try:
                start_ts = int(FRIDAY_START.timestamp())
                end_ts = int(FRIDAY_END.timestamp())
                candle_resp = requests.post(
                    f"{base_url}/NorenWClientAPI/TPSeries",
                    json={
                        "uid": uid,
                        "exch": "NSE",
                        "token": token,
                        "st": str(start_ts),
                        "et": str(end_ts),
                        "intrv": str({"FIVE_MINUTE": 5, "ONE_HOUR": 60, "ONE_DAY": 1440}[interval]),
                    },
                    headers=headers,
                    timeout=15,
                )
                candle_data = candle_resp.json() if candle_resp.status_code == 200 else {}
                rows = candle_data if isinstance(candle_data, list) else []
                status = "OK" if rows else "NO_DATA"
                if "Rate_Limited" in str(candle_data):
                    status = "RATE_LIMITED"
                elif "session" in str(candle_data).lower():
                    status = "AUTH_FAILED"
                results["candles"].append({
                    "symbol": sym,
                    "timeframe": label,
                    "status": status,
                    "rows": len(rows),
                })
            except Exception as exc:
                results["candles"].append({
                    "symbol": sym,
                    "timeframe": label,
                    "status": "ERROR",
                    "rows": 0,
                    "error": str(exc),
                })

    quote_symbols = ["RELIANCE", "TCS", "HDFCBANK", "NIFTY", "BANKNIFTY"]
    quote_resp = requests.post(
        f"{base_url}/NorenWClientAPI/GetQuotes",
        json={"uid": uid, "exch": "NSE", "token": registry.token_for("NIFTY") or ""},
        headers=headers,
        timeout=15,
    )
    results["quotes"].append({
        "symbol": "NIFTY",
        "status": "OK" if quote_resp.status_code == 200 else "ERROR",
        "data": quote_resp.json() if quote_resp.status_code == 200 else {},
    })

    async def test_ws():
        ws_results = {"connected": False, "auth_ack": False, "subscriptions": 0}
        try:
            async with websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=20,
                max_size=2**22,
                close_timeout=5,
            ) as ws:
                auth_msg = {
                    "t": "a",
                    "uid": uid,
                    "actid": account_id,
                    "source": "API",
                    "accesstoken": access_token,
                }
                await ws.send(json.dumps(auth_msg))
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw)
                if msg.get("t") == "ak" and msg.get("s") == "Ok":
                    ws_results["connected"] = True
                    ws_results["auth_ack"] = True
        except Exception:
            pass
        return ws_results

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ws_results = loop.run_until_complete(test_ws())
        loop.close()
        results["websocket"] = ws_results
    except Exception as exc:
        results["websocket"]["error"] = str(exc)

except Exception as exc:
    results["error"] = f"{type(exc).__name__}: {exc}"

print(json.dumps(results, indent=2, default=str))
