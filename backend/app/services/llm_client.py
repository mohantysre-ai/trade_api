import json
import os
import time as _time
from typing import Any
from pydantic import BaseModel, Field

import requests


_llm_not_before: float = 0.0
LLM_API_TIMEOUT_SECONDS = int(os.getenv("LLM_API_TIMEOUT_SECONDS", "60"))
_MIN_LLM_TIMEOUT = 1
_MAX_LLM_TIMEOUT = 120
LLM_CALL_TIMEOUT_SECONDS = min(max(_MIN_LLM_TIMEOUT, LLM_API_TIMEOUT_SECONDS), _MAX_LLM_TIMEOUT)

_GEMINI_OAUTH_TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_oauth_token.json")
_GEMINI_OAUTH_REQ_SCOPES = [
    "https://www.googleapis.com/auth/generative-language.retriever",
]


def _get_gemini_oauth_token(token_path: str | None = None) -> str | None:
    """Load a valid access token from stored OAuth credentials."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None

    path = token_path or _GEMINI_OAUTH_TOKEN_PATH
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.isfile(path):
        return None

    try:
        creds = Credentials.from_authorized_user_file(path, _GEMINI_OAUTH_REQ_SCOPES)
    except Exception:
        return None

    if creds.valid:
        return creds.token

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(path, "w") as f:
                f.write(creds.to_json())
            return creds.token
        except Exception:
            return None

    return None


def _llm_config() -> tuple[str, str, str, str, str | None]:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    api_url = os.getenv("LLM_API_URL", "").strip()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    oauth_token_path = os.getenv("GEMINI_OAUTH_TOKEN_PATH", "").strip()

    if provider == "gemini":
        if not api_key and gemini_key:
            api_key = gemini_key
        if not api_key and oauth_token_path:
            api_key = _get_gemini_oauth_token(oauth_token_path) or api_key
    elif not provider and gemini_key:
        provider = "gemini"
        api_key = gemini_key
    if not provider or not api_key:
        return None, None, None, None, None
    if not api_url and provider == "openai":
        api_url = "https://api.openai.com/v1/chat/completions"
    return provider, api_key, api_url, model, oauth_token_path


def _record_quota_error(message: str) -> None:
    global _llm_not_before
    _llm_not_before = _time.time() + 60


def _llm_quota_available() -> bool:
    return _time.time() >= _llm_not_before


def _call_openai(prompt: str, api_key: str, api_url: str, model: str, timeout: int = LLM_CALL_TIMEOUT_SECONDS) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an elite institutional financial terminal. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    if response.status_code >= 300:
        raise RuntimeError(f"OpenAI request failed ({response.status_code}): {response.text}")
    data = response.json()
    if not data.get("choices") or not data["choices"][0].get("message"):
        raise RuntimeError("OpenAI response missing expected content")
    return data["choices"][0]["message"]["content"].strip()


def _call_gemini(
    prompt: str,
    api_key: str,
    model: str,
    system_instruction: str,
    timeout: int = LLM_CALL_TIMEOUT_SECONDS,
    oauth_token_path: str | None = None,
) -> str:
    """Call Gemini. Tries REST API with API key first, then OAuth, then SDK."""
    # Try REST API with API key as query parameter (fastest, most reliable)
    if api_key:
        try:
            return _call_gemini_rest_api_key(api_key, model, system_instruction, prompt, timeout)
        except Exception:
            pass  # Fall through to other methods

    # Try OAuth token
    if oauth_token_path:
        token = _get_gemini_oauth_token(oauth_token_path)
        if token:
            return _call_gemini_rest(token, model, system_instruction, prompt, timeout)

    # Try SDK as last resort
    if api_key:
        return _call_gemini_sdk(api_key, model, system_instruction, prompt, timeout)

    raise RuntimeError("No Gemini credentials available (no API key or OAuth token).")


def _call_gemini_rest_api_key(
    api_key: str,
    model: str,
    system_instruction: str,
    prompt: str,
    timeout: int,
) -> str:
    """Call Gemini REST API directly using API key as query parameter."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini REST returned no candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"Gemini REST returned empty parts: {data}")
    return parts[0].get("text", "").strip()


def _call_gemini_sdk(api_key: str, model: str, system_instruction: str, prompt: str, timeout: int) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini support requires google-genai. Install it in the backend venv.") from exc

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout))
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=2000,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return getattr(response, "text", None) or getattr(response, "output_text", None) or str(response)


def _call_gemini_rest(
    access_token: str,
    model: str,
    system_instruction: str,
    prompt: str,
    timeout: int,
) -> str:
    """Call Gemini REST API directly using an OAuth2 access token."""
    import httpx as _httpx

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }
    resp = _httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini REST returned no candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"Gemini REST returned empty parts: {data}")
    return parts[0].get("text", "").strip()