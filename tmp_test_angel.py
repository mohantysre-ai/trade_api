"""Test Angel One connection and identify why it fails at current time."""
import os
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, 'backend')
from dotenv import load_dotenv
load_dotenv('backend/.env')

IST_ZONE = ZoneInfo("Asia/Kolkata")
now = datetime.now(tz=IST_ZONE)
print(f"Current time IST: {now}")
print(f"Is market hours? Weekday={now.weekday()}, Hour={now.hour}")
# Market hours: 9:15 AM - 3:30 PM IST
is_market_hours = now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30))
print(f"Within market hours: {is_market_hours}")

# Try Angel One
try:
    from SmartApi import SmartConnect
    import pyotp
    
    api_key = os.getenv('REDACTED', '')
    client_id = os.getenv('REDACTED', '')
    mpin = os.getenv('ANGEL_MPIN') or os.getenv('REDACTED', '')
    totp_secret = os.getenv('REDACTED', '')
    
    print(f"\nAngel One Config: API_KEY={'set' if api_key else 'MISSING'}, CLIENT_ID={'set' if client_id else 'MISSING'}, MPIN={'set' if mpin else 'MISSING'}, TOTP={'set' if totp_secret else 'MISSING'}")
    
    if not all([api_key, client_id, mpin, totp_secret]):
        print("ERROR: Missing Angel One credentials")
        sys.exit(1)
    
    smart = SmartConnect(api_key=api_key, timeout=12)
    totp = pyotp.TOTP(totp_secret).now()
    session = smart.generateSession(client_id, mpin, totp)
    status = session.get("status")
    print(f"\nLogin status: {status}")
    
    if not status:
        print(f"Login error: {session.get('message', 'Unknown')}")
        sys.exit(1)
    
    print("Login SUCCESS - token obtained")
    
    # Try LTP for a single stock
    try:
        resp = smart.ltpData("NSE", "RELIANCE", "2885")
        print(f"\nLTP Quote status: {resp.get('status')}")
        if resp.get('status'):
            print(f"LTP data: {json.dumps(resp['data'], indent=2)}")
        else:
            print(f"LTP error: {resp.get('message')}")
            print(f"Full response: {json.dumps(resp, indent=2)}")
    except Exception as e:
        print(f"\nLTP exception: {type(e).__name__}: {e}")
    
    # Try candle data for today
    try:
        fromdate = now.replace(hour=9, minute=15, second=0, microsecond=0)
        todate = now
        params = {
            "exchange": "NSE",
            "symboltoken": "2885",
            "interval": "ONE_DAY",
            "fromdate": fromdate.strftime("%Y-%m-%d %H:%M"),
            "todate": todate.strftime("%Y-%m-%d %H:%M"),
        }
        resp = smart.getCandleData(params)
        print(f"\nCandle status: {resp.get('status')}")
        if resp.get('status'):
            print(f"Candles: {json.dumps(resp.get('data', []), indent=2)[:500]}")
        else:
            print(f"Candle error msg: {resp.get('message', 'N/A')}")
            print(f"Full response: {json.dumps(resp, indent=2)[:500]}")
    except Exception as e:
        print(f"\nCandle exception: {type(e).__name__}: {e}")
        
    # Try batch market data
    try:
        resp = smart.getMarketData("FULL", {"NSE": ["2885"]})
        print(f"\nBatch Market Data status: {resp.get('status')}")
        if resp.get('status'):
            print(f"Batch data: {json.dumps(resp.get('data', {}), indent=2)[:500]}")
        else:
            print(f"Batch error: {resp.get('message', 'N/A')}")
    except Exception as e:
        print(f"\nBatch exception: {type(e).__name__}: {e}")

except Exception as e:
    print(f"Connection exception: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()