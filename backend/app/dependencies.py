"""
IROS Trade API - Dependencies Module
=====================================
FastAPI dependency injection utilities.
"""

from __future__ import annotations

from typing import AsyncGenerator
from fastapi import Request


async def get_client_host(request: Request) -> str:
    """Get the client's host address from the request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"