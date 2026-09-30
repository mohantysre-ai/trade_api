import asyncio
import json

from gateway.config import Settings
from gateway.http import GuardedHttp


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"stat": "Ok"}


class Client:
    def __init__(self):
        self.request = None

    async def post(self, url, content, headers):
        self.request = {"url": url, "content": content, "headers": headers}
        return Response()


def test_oauth_rest_uses_jdata_form_with_bearer():
    client = Client()
    gateway = GuardedHttp(Settings(), client=client)
    result = asyncio.run(
        gateway.post_json(
            "/NorenWClientAPI/GetQuotes",
            {"uid": "USER1", "exch": "NSE", "token": "2885"},
            "access-token",
        )
    )

    assert result == {"stat": "Ok"}
    assert client.request["headers"]["Authorization"] == "Bearer access-token"
    assert json.loads(client.request["content"].decode().removeprefix("jData=")) == {
        "uid": "USER1",
        "exch": "NSE",
        "token": "2885",
    }
