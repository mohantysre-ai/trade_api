import json
import logging
import os
import re
import time as _time
from dataclasses import dataclass
from typing import Any
from pydantic import BaseModel, Field

import requests

_log = logging.getLogger(__name__)


_llm_not_before: float = 0.0
_model_not_before: dict[str, float] = {}
_last_good_model: str | None = None
_provider_not_before: dict[str, float] = {}
_last_good_provider: str | None = None
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
    model = os.getenv("LLM_MODEL", "").strip()
    oauth_token_path = os.getenv("GEMINI_OAUTH_TOKEN_PATH", "").strip()

    openrouter = "openrouter.ai" in api_url.lower() or api_key.startswith("sk-or-")
    if openrouter and provider in ("", "openrouter", "openai"):
        provider = "openai"
        model = model or OPENROUTER_FREE_ROUTER
        if not api_url:
            api_url = "https://openrouter.ai/api/v1/chat/completions"
    elif provider == "gemini":
        model = model or "gemini-2.0-flash"
        if not api_key and gemini_key:
            api_key = gemini_key
        if not api_key and oauth_token_path:
            api_key = _get_gemini_oauth_token(oauth_token_path) or api_key
    elif not provider and gemini_key:
        provider = "gemini"
        model = model or "gemini-2.0-flash"
        api_key = gemini_key
    if not provider or not api_key:
        return None, None, None, None, None
    if not api_url and provider == "openai":
        api_url = "https://api.openai.com/v1/chat/completions"
    model = model or "gpt-4o-mini"
    return provider, api_key, api_url, model, oauth_token_path


def parse_openrouter_reset_unix(message: str) -> float | None:
    """Parse OpenRouter X-RateLimit-Reset (unix seconds or milliseconds)."""
    match = re.search(r"X-RateLimit-Reset['\"]?\s*[:=]\s*['\"]?(\d+)", message or "")
    raw: float | None = None
    if match:
        raw = float(match.group(1))
    else:
        start = (message or "").find("{")
        if start >= 0:
            try:
                data = json.loads(message[start:])
                headers = ((data.get("error") or {}).get("metadata") or {}).get("headers") or {}
                token = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")
                if token is not None:
                    raw = float(token)
            except (json.JSONDecodeError, TypeError, ValueError):
                raw = None
    if raw is None:
        return None
    if raw > 1e12:
        raw /= 1000.0
    return raw


def _retry_delay_seconds(error_str: str, cap: float = 90.0) -> float:
    match = re.search(r"'retryDelay':\s*'([\d.]+)s'", error_str or "")
    if match:
        return min(float(match.group(1)), cap)
    match = re.search(r"retry.*?in\s+([\d.]+)s", error_str or "", re.IGNORECASE)
    if match:
        return min(float(match.group(1)), cap)
    return 60.0


def quota_not_before_unix(message: str, now: float | None = None) -> float:
    now = _time.time() if now is None else now
    reset = parse_openrouter_reset_unix(message)
    if reset is not None:
        return min(max(reset, now + 5.0), now + 36 * 3600)
    return now + _retry_delay_seconds(message)


def _is_account_wide_quota(message: str) -> bool:
    text = (message or "").lower()
    return "free-models-per-day" in text or "free models per day" in text


def _model_available(model: str, now: float | None = None) -> bool:
    now = _time.time() if now is None else now
    return now >= _model_not_before.get((model or "").strip(), 0.0)


def _record_model_skip(model: str, message: str) -> None:
    name = (model or "").strip()
    if not name:
        return
    until = quota_not_before_unix(message)
    _model_not_before[name] = until
    remaining = max(0.0, until - _time.time())
    _log.warning("OpenRouter model %s cooling down for %.0fs: %s", name, remaining, (message or "")[:160])


def _record_quota_error(message: str, model: str | None = None) -> None:
    """Lock all LLMs only on account-wide free-model daily quota. Per-model 429s skip that id."""
    global _llm_not_before
    if model:
        _record_model_skip(model, message)
    if not _is_account_wide_quota(message):
        if not model:
            _log.warning("LLM 429 without account-wide quota — not locking all models: %s", (message or "")[:160])
        return
    until = quota_not_before_unix(message)
    _llm_not_before = until
    remaining = max(0.0, until - _time.time())
    _log.warning("LLM account quota cooling down for %.0fs due to: %s", remaining, (message or "")[:160])


def _llm_quota_available() -> bool:
    """Compatibility: reports OpenRouter availability, not every configured provider."""
    return _time.time() >= _llm_not_before


def llm_quota_resume_unix() -> float:
    return _llm_not_before


@dataclass(frozen=True)
class LLMProviderConfig:
    name: str
    api_key: str
    api_url: str
    model: str
    kind: str = "openai"
    oauth_token_path: str | None = None


_OPENAI_COMPATIBLE_PROVIDERS = {
    "nvidia": (
        "NVIDIA_API_KEY",
        "NVIDIA_API_URL",
        "https://integrate.api.nvidia.com/v1/chat/completions",
        "NVIDIA_MODEL",
        "nvidia/llama-3.3-nemotron-super-49b-v1",
    ),
    "groq": (
        "GROQ_API_KEY",
        "GROQ_API_URL",
        "https://api.groq.com/openai/v1/chat/completions",
        "GROQ_MODEL",
        "llama-3.3-70b-versatile",
    ),
    "cerebras": (
        "CEREBRAS_API_KEY",
        "CEREBRAS_API_URL",
        "https://api.cerebras.ai/v1/chat/completions",
        "CEREBRAS_MODEL",
        "llama-3.3-70b",
    ),
    "sambanova": (
        "SAMBANOVA_API_KEY",
        "SAMBANOVA_API_URL",
        "https://api.sambanova.ai/v1/chat/completions",
        "SAMBANOVA_MODEL",
        "Meta-Llama-3.3-70B-Instruct",
    ),
    "huggingface": (
        "HUGGINGFACE_API_KEY",
        "HUGGINGFACE_API_URL",
        "https://router.huggingface.co/v1/chat/completions",
        "HUGGINGFACE_MODEL",
        "meta-llama/Llama-3.1-8B-Instruct:fastest",
    ),
}


def _env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _provider_order() -> list[str]:
    raw = os.getenv(
        "LLM_PROVIDER_ORDER",
        "nvidia,groq,cerebras,sambanova,huggingface,openrouter,omniroute,gemini",
    )
    seen: set[str] = set()
    result: list[str] = []
    for token in raw.split(","):
        name = token.strip().lower()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _purpose_model(provider: str, default: str, purpose: str) -> str:
    suffix = "NEWS_MODEL" if purpose == "news" else "REASONING_MODEL"
    return (os.getenv(f"{provider.upper()}_{suffix}") or default).strip()


def configured_llm_providers(purpose: str = "reasoning") -> list[LLMProviderConfig]:
    """Return configured providers in failover order; credentials are never logged."""
    configs: dict[str, LLMProviderConfig] = {}
    for name, (key_env, url_env, url_default, model_env, model_default) in _OPENAI_COMPATIBLE_PROVIDERS.items():
        key = os.getenv(key_env, "").strip()
        if key:
            default_model = os.getenv(model_env, model_default).strip() or model_default
            configs[name] = LLMProviderConfig(
                name=name,
                api_key=key,
                api_url=os.getenv(url_env, url_default).strip() or url_default,
                model=_purpose_model(name, default_model, purpose),
            )

    # OmniRoute is a self-hosted OpenAI-compatible gateway, not a source of
    # tokens by itself. It is opt-in because the local service may route to
    # third-party upstreams selected by its own configuration.
    omniroute_key = os.getenv("OMNIROUTE_API_KEY", "").strip()
    if omniroute_key or _env_enabled("OMNIROUTE_ENABLED"):
        default_model = os.getenv("OMNIROUTE_MODEL", "auto/best-free").strip() or "auto/best-free"
        configs["omniroute"] = LLMProviderConfig(
            name="omniroute",
            api_key=omniroute_key or "omniroute-local",
            api_url=(
                os.getenv(
                    "OMNIROUTE_API_URL",
                    "http://127.0.0.1:20128/v1/chat/completions",
                ).strip()
                or "http://127.0.0.1:20128/v1/chat/completions"
            ),
            model=_purpose_model("omniroute", default_model, purpose),
        )

    provider, api_key, api_url, model, oauth_path = _llm_config()
    if provider and api_key:
        if provider == "gemini":
            configs["gemini"] = LLMProviderConfig(
                "gemini", api_key, "", _purpose_model("gemini", model, purpose), "gemini", oauth_path
            )
        elif _is_openrouter_url(api_url):
            configs["openrouter"] = LLMProviderConfig(
                "openrouter", api_key, api_url, _purpose_model("openrouter", model, purpose)
            )
        else:
            configs["openai"] = LLMProviderConfig("openai", api_key, api_url, model)

    # GEMINI_API_KEY can coexist with an OpenRouter primary.
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key and "gemini" not in configs:
        configs["gemini"] = LLMProviderConfig(
            "gemini",
            gemini_key,
            "",
            _purpose_model("gemini", os.getenv("GEMINI_MODEL", "gemini-2.0-flash"), purpose),
            "gemini",
            os.getenv("GEMINI_OAUTH_TOKEN_PATH", "").strip() or None,
        )

    ordered = [configs[name] for name in _provider_order() if name in configs]
    for name, config in configs.items():
        if name not in {item.name for item in ordered}:
            ordered.append(config)
    return ordered


def _provider_available(name: str) -> bool:
    if name == "openrouter" and not _llm_quota_available():
        return False
    return _time.time() >= _provider_not_before.get(name, 0.0)


def _record_provider_failure(name: str, message: str) -> None:
    text = (message or "").lower()
    retryable = any(token in text for token in ("429", "quota", "rate limit", "402", "503", "529", "timeout"))
    if not retryable:
        return
    until = quota_not_before_unix(message)
    _provider_not_before[name] = until
    if name == "openrouter" and _is_account_wide_quota(message):
        _record_quota_error(message)
    _log.warning("LLM provider %s cooling down for %.0fs", name, max(0.0, until - _time.time()))


def call_llm_with_fallback(
    prompt: str,
    system_instruction: str,
    *,
    purpose: str = "reasoning",
    max_tokens: int | None = None,
    timeout: int = LLM_CALL_TIMEOUT_SECONDS,
) -> tuple[str, str, str]:
    """Sequential provider failover. Never fans out or retries a successful request."""
    global _last_good_provider
    providers = configured_llm_providers(purpose)
    if not providers:
        raise RuntimeError("No LLM provider configured")
    last_good = _last_good_provider
    if last_good:
        providers.sort(key=lambda item: item.name != last_good)
    try:
        cap = max(1, min(int(os.getenv("LLM_PROVIDER_ATTEMPTS", "3")), 7))
    except ValueError:
        cap = 3
    candidates = [item for item in providers if _provider_available(item.name)][:cap]
    if not candidates:
        raise RuntimeError("All configured LLM providers are cooling down")
    errors: list[str] = []
    for config in candidates:
        try:
            if config.kind == "gemini":
                text = _call_gemini(
                    prompt, config.api_key, config.model, system_instruction, timeout,
                    oauth_token_path=config.oauth_token_path,
                )
            else:
                text = _call_openai(
                    f"{system_instruction}\n\n{prompt}", config.api_key, config.api_url,
                    config.model, timeout, max_tokens=max_tokens,
                )
            _last_good_provider = config.name
            _log.info("LLM completion purpose=%s provider=%s model=%s", purpose, config.name, config.model)
            return text, config.name, config.model
        except Exception as exc:
            message = str(exc)
            errors.append(f"{config.name}: {message[:180]}")
            _record_provider_failure(config.name, message)
            _log.warning("LLM provider %s failed; trying next configured provider: %s", config.name, message[:160])
    raise RuntimeError("LLM provider failover exhausted: " + "; ".join(errors))


OPENROUTER_FREE_ROUTER = "openrouter/free"
_DEFAULT_OPENROUTER_FREE = [
    OPENROUTER_FREE_ROUTER,
    "nvidia/nemotron-3-super-120b-a12b:free",
    "inclusionai/ling-3.0-flash:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "openai/gpt-oss-20b:free",
    "poolside/laguna-s-2.1:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
]
_SKIP_FREE_SUBSTR = ("content-safety", "lyria")
_MAX_FREE_FAILOVER = 4
_live_free_models: list[str] = []
_live_free_models_at: float = 0.0


def _is_openrouter_url(api_url: str) -> bool:
    return "openrouter.ai" in (api_url or "").lower()


def _is_openrouter_free_model(model: str) -> bool:
    name = (model or "").strip()
    return name == OPENROUTER_FREE_ROUTER or name.endswith(":free")


def _skip_free_model(model: str) -> bool:
    lowered = (model or "").lower()
    return any(token in lowered for token in _SKIP_FREE_SUBSTR)


def _env_free_fallback_models() -> list[str]:
    raw = (
        os.getenv("LLM_FREE_FALLBACK_MODELS", "").strip()
        or os.getenv("OPENROUTER_MODELS", "").strip()
        or os.getenv("LLM_FALLBACK_MODELS", "").strip()
    )
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _list_openrouter_free_models() -> list[str]:
    """Live :free catalog; falls back to a short static list if the models API is down."""
    global _live_free_models, _live_free_models_at
    now = _time.time()
    if _live_free_models and now - _live_free_models_at < 1800:
        return list(_live_free_models)
    ids: list[str] = []
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=8)
        if response.status_code < 300:
            rows = (response.json() or {}).get("data") or []
            for row in rows:
                model_id = str((row or {}).get("id") or "").strip()
                if not _is_openrouter_free_model(model_id) or _skip_free_model(model_id):
                    continue
                ids.append(model_id)
    except Exception as exc:
        _log.warning("OpenRouter free-model catalog fetch failed: %s", exc)
    if not ids:
        ids = list(_DEFAULT_OPENROUTER_FREE)
    if OPENROUTER_FREE_ROUTER not in ids:
        ids.insert(0, OPENROUTER_FREE_ROUTER)
    _live_free_models = ids
    _live_free_models_at = now
    return list(ids)


def _failover_cap() -> int:
    raw = os.getenv("LLM_FREE_FAILOVER_MAX", "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 12))
    return _MAX_FREE_FAILOVER


def openrouter_free_failover_models(primary: str) -> list[str]:
    """Last-good, then primary, then free router, env extras, and live :free catalog."""
    seen: set[str] = set()
    ordered: list[str] = []
    env_extras = _env_free_fallback_models()
    catalog = _list_openrouter_free_models()
    last_good = (_last_good_model or "").strip()
    primary_name = (primary or "").strip()
    for model in [last_good, primary_name, OPENROUTER_FREE_ROUTER, *env_extras, *catalog]:
        name = (model or "").strip()
        if not name or name in seen or _skip_free_model(name):
            continue
        if name not in {last_good, primary_name} and not _is_openrouter_free_model(name):
            continue
        seen.add(name)
        ordered.append(name)
    cap = _failover_cap()
    available = [name for name in ordered if _model_available(name)]
    if available:
        return available[:cap]
    preferred = [name for name in ordered if name in {last_good, primary_name}]
    return (preferred or ordered)[: max(1, min(3, cap))]


def _openrouter_error_retryable(message: str) -> bool:
    text = (message or "").lower()
    return any(
        token in text
        for token in (
            "429",
            "rate limit",
            "quota",
            "free-models-per-day",
            "no endpoints",
            "not found",
            "unavailable",
            "404",
            "502",
            "503",
            "524",
            "529",
            "timeout",
            "timed out",
            "provider returned error",
            "model is not available",
        )
    )


def _close_truncated_json(content: str) -> str:
    """Best-effort close of truncated JSON, respecting brace/bracket nesting order."""
    text = content.rstrip().rstrip(",")
    stack: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_string:
        if escape:
            text += "\\"
        text += '"'
    return text + "".join(reversed(stack))


def _openai_chat_once(
    prompt: str,
    api_key: str,
    api_url: str,
    model: str,
    timeout: int,
    max_tokens: int | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter.ai" in (api_url or "").lower():
        headers["HTTP-Referer"] = os.getenv("OPENROUTER_HTTP_REFERER", "https://sigq.in")
        headers["X-Title"] = os.getenv("OPENROUTER_APP_TITLE", "IROS Desk")
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
        "max_tokens": max_tokens or int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "2000")),
    }
    response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    if response.status_code >= 300:
        raise RuntimeError(f"OpenAI request failed ({response.status_code}): {response.text}")
    data = response.json()
    if _is_openrouter_url(api_url):
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        _log.info(
            "OpenRouter completion model=%s prompt_tokens=%s completion_tokens=%s",
            data.get("model") or model,
            usage.get("prompt_tokens", "unknown"),
            usage.get("completion_tokens", "unknown"),
        )
    choices = data.get("choices") or []
    if not choices or not choices[0].get("message"):
        raise RuntimeError("OpenAI response missing expected content")
    finish = choices[0].get("finish_reason", "")
    content = choices[0]["message"].get("content") or ""
    if finish == "length" and content:
        content = _close_truncated_json(content)
    return content.strip()


def _call_openai(
    prompt: str,
    api_key: str,
    api_url: str,
    model: str,
    timeout: int = LLM_CALL_TIMEOUT_SECONDS,
    max_tokens: int | None = None,
) -> str:
    global _last_good_model
    if _is_openrouter_url(api_url) and not _llm_quota_available():
        raise RuntimeError("LLM quota cooling down")
    models = [model]
    if _is_openrouter_url(api_url):
        models = openrouter_free_failover_models(model)
    available = [candidate for candidate in models if _model_available(candidate)]
    if available:
        models = available
    last_error = ""
    for index, candidate in enumerate(models):
        try:
            text = _openai_chat_once(prompt, api_key, api_url, candidate, timeout, max_tokens)
            _last_good_model = candidate
            if candidate != model or index > 0:
                _log.info("OpenRouter succeeded via %s (requested %s)", candidate, model)
            return text
        except Exception as exc:
            last_error = str(exc)
            _record_model_skip(candidate, last_error)
            if _is_account_wide_quota(last_error):
                _record_quota_error(last_error)
                break
            more = index < len(models) - 1
            if more and _is_openrouter_url(api_url) and _openrouter_error_retryable(last_error):
                _log.warning("OpenRouter model %s failed; trying next free model: %s", candidate, last_error[:160])
                continue
            break
    raise RuntimeError(last_error or "OpenRouter free-model failover exhausted")


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
