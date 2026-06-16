"""Terminal intelligence with full LLM support and heuristic fallback.

When LLM credentials are configured (REDACTED or LLM_PROVIDER + REDACTED),
this module calls Gemini or OpenAI to generate institutional-grade analysis.
It validates all responses against a strict Pydantic schema and gracefully
falls back to heuristic-based analysis when LLM is unavailable or fails.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ValidationError
import json
import os
import re
import logging

logger = logging.getLogger(__name__)


class CompleteSecurityAnalysisPayload(BaseModel):
    news_catalysts_card: str | None = Field(default=None)
    insider_insti_activity_card: str | None = Field(default=None)
    macro_anchors_card: str | None = Field(default=None)
    forensic_screen_card: str | None = Field(default=None)
    why_interested: str | None = Field(default=None)
    future_revenue_model: str | None = Field(default=None)
    current_model: str | None = Field(default=None)
    ledger_stocks: list[dict[str, Any]] = Field(default_factory=list)
    active_scoring_matrix: dict[str, Any] = Field(default_factory=dict)
    active_seven_ic_gates: dict[str, Any] = Field(default_factory=dict)
    active_risk_calc: dict[str, Any] = Field(default_factory=dict)
    active_factor_hub: dict[str, Any] = Field(default_factory=dict)


def _snapshot_path() -> str:
    return os.path.join(os.path.dirname(__file__), "last_market_snapshot.json")


def _load_snapshot() -> dict[str, Any] | None:
    try:
        with open(_snapshot_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _parse_percent(s: str | None) -> float:
    if not s:
        return 0.0
    m = re.search(r"([+-]?\d+(?:\.\d+)?)%", s)
    if not m:
        try:
            return float(s)
        except Exception:
            return 0.0
    return float(m.group(1))


def _llm_config() -> tuple[str, str, str, str] | None:
    """Load LLM provider config from environment."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    api_key = os.getenv("REDACTED", "").strip()
    gemini_key = os.getenv("REDACTED", "").strip()
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


# Module-level quota gate
_llm_not_before: float = 0.0


def _parse_retry_delay(error_str: str, cap: float = 90.0) -> float:
    """Extract retryDelay from Gemini 429 error."""
    match = re.search(r"'retryDelay':\s*'([\d.]+)s'", error_str)
    if match:
        return min(float(match.group(1)), cap)
    match = re.search(r"retry.*?in\s+([\d.]+)s", error_str, re.IGNORECASE)
    if match:
        return min(float(match.group(1)), cap)
    return 30.0


def _llm_quota_available() -> bool:
    """Check if quota cooldown has passed."""
    return _time.monotonic() >= _llm_not_before


def _record_quota_error(error_str: str) -> None:
    """Record a 429 quota error and set cooldown."""
    global _llm_not_before
    delay = _parse_retry_delay(error_str)
    _llm_not_before = _time.monotonic() + delay
    _logging.getLogger(__name__).warning(
        "Gemini 429 quota cooling down for %.0fs.", delay
    )


def execute_terminal_intelligence_pipeline(live_unstructured_stream: str) -> CompleteSecurityAnalysisPayload:
    """Execute terminal intelligence: try LLM if configured, fall back to heuristic.

    If `live_unstructured_stream` contains a `FOCUS_TICKER: <TICKER>` line,
    the returned payload will prioritize that ticker in the ledger.
    """
    # Extract focus ticker hint
    focus_match = re.search(r"FOCUS_TICKER:\s*([A-Z0-9._-]+)", live_unstructured_stream or "")
    focus_ticker = focus_match.group(1) if focus_match else None

    # Try LLM first
    try:
        return _run_llm_intelligence_pipeline(live_unstructured_stream, focus_ticker)
    except Exception as exc:
        logger.warning(f"LLM pipeline failed ({exc}), falling back to heuristic.")
        return _run_heuristic_intelligence_pipeline(live_unstructured_stream, focus_ticker)


def _run_llm_intelligence_pipeline(live_unstructured_stream: str, focus_ticker: str | None = None) -> CompleteSecurityAnalysisPayload:
    """Call Gemini or OpenAI to generate institutional analysis."""
    from angel_one_feed import _llm_config, _call_gemini, _call_openai, _llm_quota_available, _record_quota_error, LLM_CALL_TIMEOUT_SECONDS

    if not _llm_quota_available():
        raise RuntimeError("LLM quota cooling down")

    llm_config = _llm_config()
    if llm_config is None:
        raise RuntimeError("No LLM configured")

    provider, api_key, api_url, model = llm_config

    system_instruction = (
        "You are an elite institutional financial analysis terminal. Ingest live market data streams "
        "and output a single compact JSON object matching the provided schema exactly. "
        "Numeric fields must be numbers, percentage strings use '4.50%' format. "
        "If a field cannot be computed, use null. Always return valid JSON."
    )

    user_prompt = f"""Analyze this live market intelligence stream and extract institutional insights.

{live_unstructured_stream}

Return ONLY a single JSON object matching this schema (no explanation, no markdown):
{{
  "news_catalysts_card": "<string or null>",
  "insider_insti_activity_card": "<string or null>",
  "macro_anchors_card": "<string or null>",
  "forensic_screen_card": "<string or null>",
  "why_interested": "<string or null>",
  "future_revenue_model": "<string or null>",
  "current_model": "<string or null>",
  "ledger_stocks": [{{"ticker": "...", "name": "...", "ltp": "...", "delta": "...", "score": 0.0}}],
  "active_scoring_matrix": {{}},
  "active_seven_ic_gates": {{}},
  "active_risk_calc": {{}},
  "active_factor_hub": {{}}
}}

{f'Focus on {focus_ticker} for deep analysis.' if focus_ticker else 'Select top stocks with highest conviction.'}
"""

    try:
        if provider == "gemini":
            raw = _call_gemini(
                user_prompt,
                api_key,
                model,
                system_instruction,
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
        else:
            raw = _call_openai(user_prompt, api_key, api_url, model, LLM_CALL_TIMEOUT_SECONDS)

        # Parse and validate JSON
        data = json.loads(raw)
        payload = CompleteSecurityAnalysisPayload.model_validate(data)
        logger.info(f"LLM analysis successful ({provider})")
        return payload
    except ValidationError as exc:
        logger.error(f"LLM response validation failed: {exc}")
        raise RuntimeError(f"Invalid LLM response schema: {exc}") from exc
    except json.JSONDecodeError as exc:
        logger.error(f"LLM response not valid JSON: {exc}")
        raise RuntimeError(f"LLM response not JSON: {exc}") from exc
    except Exception as exc:
        err_str = str(exc)
        if "429" in err_str:
            _record_quota_error(err_str)
        raise


def _run_heuristic_intelligence_pipeline(live_unstructured_stream: str, focus_ticker: str | None = None) -> CompleteSecurityAnalysisPayload:
    """Fallback: generate deterministic analysis from last snapshot."""
    snapshot = _load_snapshot()
    news = (snapshot.get("news") if snapshot else []) or []
    stocks = (snapshot.get("stocks") if snapshot else []) or []

    news_titles = [n.get("title", "") for n in news[:3]]
    news_catalysts = "\n".join([f"• {t}" for t in news_titles]) if news_titles else ""

    ledger: list[dict[str, Any]] = []
    scored: list[tuple[dict[str, Any], float]] = []
    for s in stocks:
        pct = _parse_percent(s.get("delta"))
        vol = float(s.get("volume") or 0)
        score = abs(pct) * 2.0 + (0.0 if vol <= 0 else (len(str(int(vol))) - 1))
        scored.append((s, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    selected: list[tuple[dict[str, Any], float]] = []
    if focus_ticker:
        for s, sc in scored:
            if s.get("ticker") == focus_ticker:
                selected.append((s, sc))
                break

    for s, sc in scored:
        if len(selected) >= 8:
            break
        if s.get("ticker") == focus_ticker:
            continue
        selected.append((s, sc))

    for s, sc in selected:
        ledger.append({
            "ticker": s.get("ticker"),
            "name": s.get("name"),
            "ltp": s.get("ltp"),
            "delta": s.get("delta"),
            "score": round(float(sc), 2),
        })

    payload = CompleteSecurityAnalysisPayload(
        news_catalysts_card=news_catalysts,
        insider_insti_activity_card="",
        macro_anchors_card="",
        forensic_screen_card=(f"Top picks: {', '.join([row['ticker'] for row in ledger[:5]])}" if ledger else ""),
        why_interested=(f"Focused analysis on {focus_ticker}." if focus_ticker else "Heuristic-selected high-conviction names from pool."),
        future_revenue_model="",
        current_model="",
        ledger_stocks=ledger,
        active_scoring_matrix={
            **({t['ticker']: t['score'] for t in ledger}),
            "beneish_m_score": "N/A",
            "altman_z_score": "N/A",
            "ocf_ebitda_ratio": "N/A",
            "mansfield_relative_strength": "N/A",
        },
        active_seven_ic_gates={},
        active_risk_calc={"max_score": max([r['score'] for r in ledger], default=0.0)},
        active_factor_hub={"selection_reason": "momentum+volume heuristic"},
    )
    logger.info("Using heuristic intelligence pipeline (LLM unavailable)")

    return payload
