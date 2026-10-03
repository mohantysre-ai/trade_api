import hashlib
import json
import asyncio
from datetime import datetime

from gateway.auth import AuthManager
from gateway.config import IST, Settings
from gateway.feed import FeedManager


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Client:
    response = {}
    request = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, content, headers):
        type(self).request = {"url": url, "content": content, "headers": headers}
        return Response(type(self).response)


def test_oauth_code_exchange_uses_official_contract(monkeypatch):
    from gateway import auth

    Client.response = {
        "access_token": "rest-token",
        "susertoken": "ws-token",
        "USERID": "USER1",
        "actid": "ACCOUNT1",
    }
    monkeypatch.setattr(auth.httpx, "AsyncClient", Client)
    settings = Settings(
        uid="USER1",
        vendor_code="client-id",
        api_secret="secret-code",
        auth_mode="oauth",
    )
    session = asyncio.run(AuthManager(settings).exchange_oauth_code("auth-code"))
    body = Client.request["content"].decode()
    payload = json.loads(body.removeprefix("jData="))

    assert Client.request["url"].endswith("/NorenWClientAPI/GenAcsTok")
    assert payload == {
        "code": "auth-code",
        "checksum": hashlib.sha256(b"client-idsecret-codeauth-code").hexdigest(),
        "uid": "USER1",
    }
    assert session.access_token == "rest-token"
    assert session.websocket_token == "ws-token"


def test_oauth_authorize_url_uses_client_id():
    settings = Settings(vendor_code="client-id")

    assert AuthManager(settings).oauth_authorize_url() == (
        "https://api.shoonya.com/OAuthlogin/authorize/oauth?client_id=client-id"
    )


def test_session_restore_accepts_legacy_session_file(tmp_path):
    now = datetime.now(IST)
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps(
            {
                "uid": "USER1",
                "accountId": "ACCOUNT1",
                "accessToken": "legacy-token",
                "obtainedAt": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    manager = AuthManager(Settings(session_file=str(session_file)), clock=lambda: now)

    assert manager.restore() is True
    assert manager.session.websocket_token == "legacy-token"


class WebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    async def recv(self):
        return json.dumps({"t": "ak", "s": "OK"})


def test_websocket_accepts_oauth_uppercase_ack():
    manager = AuthManager(Settings(session_file=""))
    manager.set_session("USER1", "ACCOUNT1", "rest-token", "ws-token")
    feed = FeedManager.__new__(FeedManager)
    feed._auth = manager
    feed._s = Settings()
    feed._mono = lambda: 1.0
    feed.connected = False
    ws = WebSocket()

    assert asyncio.run(feed._handshake(ws)) is True
    assert ws.sent[0]["accesstoken"] == "ws-token"
