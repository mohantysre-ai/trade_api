"""Login to Shoonya and inject session into the local gateway (temporary helper)."""
import base64, json, sys, urllib.error, urllib.parse, urllib.request

sys.path.insert(0, r"d:\trade_api\shoonya-gateway")
from dotenv import load_dotenv  # noqa: E402
import os  # noqa: E402

load_dotenv(r"d:\trade_api\shoonya-gateway\.env")
import pyotp  # noqa: E402

UID = os.getenv("SHOONYA_UID")
PASSWORD = os.getenv("SHOONYA_PASSWORD")
TOTP_SECRET = os.getenv("SHOONYA_TOTP_SECRET")
VENDOR = os.getenv("SHOONYA_CLIENT_ID")
ADMIN_TOKEN = os.getenv("SHOONYA_ADMIN_TOKEN")

import hashlib  # noqa: E402

payload = {
    "apkversion": "1.0.0",
    "source": "API",
    "uid": UID,
    "pwd": hashlib.sha256(PASSWORD.encode()).hexdigest(),
    "factor2": pyotp.TOTP(TOTP_SECRET).now(),
    "vc": VENDOR,
    "appkey": hashlib.sha256(f"{UID}|{os.getenv('SHOONYA_SECRET_CODE')}".encode()).hexdigest(),
    "imei": "abc1234",
}
body = ('jData=' + json.dumps(payload)).encode()
req = urllib.request.Request(
    "https://api.shoonya.com/NorenWClientAPI/QuickAuth",
    data=body,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
try:
    r = json.load(urllib.request.urlopen(req))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:300])
    sys.exit(1)
print(json.dumps({"stat": r.get("stat"), "emsg": r.get("emsg", "")}))
if r.get("stat") != "Ok":
    sys.exit(2)
open(r"d:\trade_api\shoonya-gateway\login_result.json", "w").write(json.dumps(r))

inj = json.dumps({"uid": UID, "accountId": r.get("actid") or UID, "accessToken": r.get("susertoken")}).encode()
req2 = urllib.request.Request(
    "http://127.0.0.1:8787/admin/oauth/code",
    data=inj,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {ADMIN_TOKEN}"},
)
print("gateway:", urllib.request.urlopen(req2).read().decode())
