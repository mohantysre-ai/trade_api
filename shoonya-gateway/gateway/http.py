from __future__ import annotations

from typing import Any

import httpx

from .allowlist import assert_allowed
from .config import Settings


class GuardedHttp:
    """Thin httpx wrapper that refuses any non-allowlisted path."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._base = settings.api_base
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, read=30.0), verify=settings.tls_verify
        )

    async def get_bytes(self, path: str) -> bytes:
        assert_allowed(path)
        response = await self._client.get(self._base + path)
        response.raise_for_status()
        return response.content

    async def post_json(self, path: str, payload: dict[str, Any], access_token: str) -> Any:
        assert_allowed(path)
        response = await self._client.post(
            self._base + path,
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
