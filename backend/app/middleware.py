"""Shared API hardening middleware for the backend services."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send


_SECURITY_HEADERS = {
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
    b"referrer-policy": b"no-referrer",
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
}


def _rate_limit_per_minute() -> int:
    raw = os.getenv("API_RATE_LIMIT_PER_MINUTE", "240").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"API_RATE_LIMIT_PER_MINUTE must be an integer, got {raw!r}") from exc
    if not 1 <= value <= 100_000:
        raise RuntimeError("API_RATE_LIMIT_PER_MINUTE must be between 1 and 100000")
    return value


def configured_cors_origins() -> list[str]:
    raw = os.getenv(
        "API_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://sigq.in",
    )
    origins = list(dict.fromkeys(item.strip().rstrip("/") for item in raw.split(",") if item.strip()))
    if not origins or "*" in origins:
        raise RuntimeError("API_ALLOWED_ORIGINS must contain explicit origins; wildcard CORS is disabled")
    return origins


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                headers.extend((key, value) for key, value in _SECURITY_HEADERS.items() if key not in existing)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimitMiddleware:
    """Per-client token bucket for one backend process.

    This protects accidental bursts and direct-origin traffic. Production edge
    limits should still be enforced by the reverse proxy across all replicas.
    """

    def __init__(self, app: ASGIApp, requests_per_minute: int) -> None:
        self.app = app
        self.capacity = float(requests_per_minute)
        self.refill_per_second = self.capacity / 60.0
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _consume(self, client: str) -> tuple[bool, int, int]:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(client)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, updated_at=now)
                self._buckets[client] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.refill_per_second)
            bucket.updated_at = now
            if bucket.tokens < 1.0:
                retry_after = max(1, math.ceil((1.0 - bucket.tokens) / self.refill_per_second))
                return False, 0, retry_after
            bucket.tokens -= 1.0
            return True, max(0, int(bucket.tokens)), 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        client_info = scope.get("client")
        client = str(client_info[0]) if client_info else "unknown"
        allowed, remaining, retry_after = self._consume(client)
        if not allowed:
            body = json.dumps({"detail": "Rate limit exceeded"}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"retry-after", str(retry_after).encode("ascii")),
                        (b"x-ratelimit-limit", str(int(self.capacity)).encode("ascii")),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_limit(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-ratelimit-limit", str(int(self.capacity)).encode("ascii")),
                        (b"x-ratelimit-remaining", str(remaining).encode("ascii")),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_limit)


def add_api_hardening(app: FastAPI) -> None:
    app.add_middleware(RateLimitMiddleware, requests_per_minute=_rate_limit_per_minute())
    app.add_middleware(SecurityHeadersMiddleware)
