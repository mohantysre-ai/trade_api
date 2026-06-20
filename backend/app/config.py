"""
IROS Trade API - Configuration Module
======================================
Centralized configuration loader for the backend.
Reads from environment variables (loaded from backend/.env).
"""

from __future__ import annotations

import os
from typing import Any
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment is loaded
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def get_env(name: str, default: str | None = None) -> str:
    """Get a required or optional environment variable."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    if default is not None:
        return default
    raise RuntimeError(f"Missing required environment variable: {name}")


# Angel One API
REDACTED = os.getenv("REDACTED", "")
REDACTED = os.getenv("REDACTED", "")
ANGEL_MPIN = os.getenv("ANGEL_MPIN") or os.getenv("REDACTED") or ""
REDACTED = os.getenv("REDACTED", "")

# LLM Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
REDACTED = os.getenv("REDACTED", "") or os.getenv("REDACTED", "") or os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")
LLM_API_URL = os.getenv("LLM_API_URL", "")

# Server
MARKET_API_HOST = os.getenv("MARKET_API_HOST", "0.0.0.0")
MARKET_API_PORT = int(os.getenv("MARKET_API_PORT", "8000"))
AI_NEWS_API_URL = os.getenv("AI_NEWS_API_URL", "http://127.0.0.1:8001")

# Market
LLM_UNIVERSE_LIMIT = int(os.getenv("LLM_UNIVERSE_LIMIT", "30"))
ANGEL_API_TIMEOUT_SECONDS = int(os.getenv("ANGEL_API_TIMEOUT_SECONDS", "24"))
LLM_CALL_TIMEOUT_SECONDS = min(max(1, int(os.getenv("LLM_CALL_TIMEOUT_SECONDS", "60"))), 120)
QUOTE_CHUNK_SIZE = int(os.getenv("QUOTE_CHUNK_SIZE", "10"))
INTRADAY_CHUNK_SIZE = int(os.getenv("INTRADAY_CHUNK_SIZE", "10"))
MARKET_FILTER_PROMPT = os.getenv("MARKET_FILTER_PROMPT", "")

# Debug
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")