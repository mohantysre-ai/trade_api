"""
IROS Trade API - Configuration Module
======================================
Centralized configuration loader for the backend.
Reads from environment variables (loaded from backend/.env).
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

# Ensure environment is loaded
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    try:
        load_dotenv(_env_path, encoding="utf-8")
    except UnicodeDecodeError:
        # Windows-created deployments may still contain cp1252 punctuation.
        load_dotenv(_env_path, encoding="cp1252")


def get_env(name: str, default: str | None = None) -> str:
    """Get a required or optional environment variable."""
    value = os.getenv(name, "").strip()
    if value:
        return value
    if default is not None:
        return default
    raise RuntimeError(f"Missing required environment variable: {name}")


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def _url_issue(name: str, value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"{name} must be an absolute http(s) URL"
    return None


def runtime_config_issues() -> list[str]:
    """Return actionable configuration problems without exposing secret values."""
    issues: list[str] = []

    dhan = {name: bool(os.getenv(name, "").strip()) for name in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN")}
    if any(dhan.values()) and not all(dhan.values()):
        missing = [name for name, present in dhan.items() if not present]
        issues.append(f"Dhan credentials are incomplete; missing {', '.join(missing)}")

    angel_names = ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_TOTP_SECRET")
    angel = {name: bool(os.getenv(name, "").strip()) for name in angel_names}
    angel["ANGEL_MPIN or ANGEL_PASSWORD"] = bool(
        os.getenv("ANGEL_MPIN", "").strip() or os.getenv("ANGEL_PASSWORD", "").strip()
    )
    if any(angel.values()) and not all(angel.values()):
        missing = [name for name, present in angel.items() if not present]
        issues.append(f"Angel One credentials are incomplete; missing {', '.join(missing)}")

    if os.getenv("LLM_PROVIDER", "").strip() and not any(
        os.getenv(name, "").strip()
        for name in (
            "LLM_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "NVIDIA_API_KEY",
            "GROQ_API_KEY",
            "CEREBRAS_API_KEY",
            "SAMBANOVA_API_KEY",
            "HUGGINGFACE_API_KEY",
        )
    ) and not os.getenv("OMNIROUTE_ENABLED", "").strip().lower() in {"1", "true", "yes"}:
        issues.append("LLM_PROVIDER is set but no supported LLM API key is configured")

    for name, value in (
        ("AI_NEWS_API_URL", AI_NEWS_API_URL),
        ("BACKEND_URL", BACKEND_URL),
        ("LLM_API_URL", LLM_API_URL),
    ):
        if not value:
            continue
        issue = _url_issue(name, value)
        if issue:
            issues.append(issue)
    return issues


# Angel One API
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_MPIN = os.getenv("ANGEL_MPIN") or os.getenv("ANGEL_PASSWORD") or ""
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

# LLM Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "") or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_API_URL = os.getenv("LLM_API_URL", "")

# TinyFish Search (backup news fetch)
TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY", "")

# Server
MARKET_API_HOST = os.getenv("MARKET_API_HOST", "0.0.0.0")
MARKET_API_PORT = _int_env("MARKET_API_PORT", 8000, minimum=1, maximum=65535)
AI_NEWS_API_URL = os.getenv("AI_NEWS_API_URL", "http://127.0.0.1:8001")

# Market
LLM_UNIVERSE_LIMIT = _int_env("LLM_UNIVERSE_LIMIT", 30, minimum=1, maximum=500)
ANGEL_API_TIMEOUT_SECONDS = _int_env("ANGEL_API_TIMEOUT_SECONDS", 24, minimum=1, maximum=120)
LLM_CALL_TIMEOUT_SECONDS = _int_env("LLM_CALL_TIMEOUT_SECONDS", 60, minimum=1, maximum=120)
QUOTE_CHUNK_SIZE = _int_env("QUOTE_CHUNK_SIZE", 10, minimum=1, maximum=50)
INTRADAY_CHUNK_SIZE = _int_env("INTRADAY_CHUNK_SIZE", 10, minimum=1, maximum=50)
MARKET_FILTER_PROMPT = os.getenv("MARKET_FILTER_PROMPT", "")

# Debug
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
