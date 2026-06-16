import json
import os
import time as _time
from typing import Any
from pydantic import BaseModel, Field

import requests


_llm_not_before: float = 0.0
LLM_API_TIMEOUT_SECONDS = int(os.getenv("LLM_API_TIMEOUT_SECONDS", "60"))
MIN_LLM_TIMEOUT = 1
MAX_LLM_TIMEOUT = 120
LLM_CALL_TIMEOUT_SECONDS = min(max(MIN_LLM_TIMEOUT, LLM_API_TIMEOUT_SECONDS), MAX_LLM_TIMEOUT)


def _llm_config() -> tuple[str, str, str, str] | None:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    api_url = os.getenv("LLM_API_URL", "").strip()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()

    if provider == "gemini" and not api_key:
        api_key = gemini_key
    if not provider and gemini_key:
        provider = "gemini"
        api_key = gemini_key
    if not provider or not api_key:
        return None
    if not api_url and provider == "openai":
        api_url = "https://api.openai.com/v1/chat/completions"
    return provider, api_key, api_url, model


def _record_quota_error(message: str) -> None:
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


def _call_gemini(prompt: str, api_key: str, model: str, system_instruction: str, timeout: int = LLM_CALL_TIMEOUT_SECONDS) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini support requires google-genai. Install it in the backend venv.") from exc

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=2000,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config, timeout=timeout)
    return getattr(response, "text", None) or getattr(response, "output_text", None) or str(response)
