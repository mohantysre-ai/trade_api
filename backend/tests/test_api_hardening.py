import asyncio

import pytest

from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware, configured_cors_origins


async def _request(app, path="/api/test", client=("127.0.0.1", 1234)):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {"type": "http", "method": "GET", "path": path, "headers": [], "client": client},
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    return start["status"], dict(start.get("headers", []))


async def _ok_app(_scope, _receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_security_headers_are_added():
    status, headers = asyncio.run(_request(SecurityHeadersMiddleware(_ok_app)))
    assert status == 200
    assert headers[b"content-security-policy"].startswith(b"default-src 'none'")
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"x-content-type-options"] == b"nosniff"


def test_rate_limit_returns_429_and_exempts_health():
    app = RateLimitMiddleware(_ok_app, requests_per_minute=1)
    first_status, _ = asyncio.run(_request(app))
    second_status, second_headers = asyncio.run(_request(app))
    health_status, _ = asyncio.run(_request(app, path="/health"))
    assert first_status == 200
    assert second_status == 429
    assert int(second_headers[b"retry-after"]) >= 1
    assert health_status == 200


def test_cors_origins_reject_wildcard(monkeypatch):
    monkeypatch.setenv("API_ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="wildcard CORS is disabled"):
        configured_cors_origins()
