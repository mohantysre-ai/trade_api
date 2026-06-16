"""Terminal intelligence pipeline with full LLM support.

Provides institutional-grade market analysis using Gemini or OpenAI.
Automatically falls back to heuristic analysis when LLM is unavailable or quota-gated.
Supports per-ticker focusing for deep security-specific analysis.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field
import json
import os
import re
import logging as _logging
import requests
import time as _time
from llm_client import LLM_CALL_TIMEOUT_SECONDS, _call_gemini, _call_openai


class CompleteSecurityAnalysisPayload(BaseModel):
    news_catalysts_card: str | None = Field(default=None, description="Key news catalysts and macro themes")
    insider_insti_activity_card: str | None = Field(default=None, description="Insider and institutional activity")
    macro_anchors_card: str | None = Field(default=None, description="Macro economic anchors")
    forensic_screen_card: str | None = Field(default=None, description="Forensic screening results")
    why_interested: str | None = Field(default=None, description="Rationale for security focus")
    future_revenue_model: str | None = Field(default=None, description="Forward-looking revenue model")
    current_model: str | None = Field(default=None, description="Current revenue and earnings model")
    ledger_stocks: list[dict[str, Any]] = Field(default_factory=list, description="Top picked stocks with scoring")
    active_scoring_matrix: dict[str, Any] = Field(default_factory=dict, description="Ticker -> score mapping")
    active_seven_ic_gates: dict[str, Any] = Field(default_factory=dict, description="Quality gates")
    active_risk_calc: dict[str, Any] = Field(default_factory=dict, description="Risk calculations")
    active_factor_hub: dict[str, Any] = Field(default_factory=dict, description="Factor attribution")


# Module-level quota gate
_llm_not_before: float = 0.0


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


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list)):
        return len(value) == 0
    return False


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _format_score(value: Any) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _fallback_bullets(title: str, items: list[str]) -> str:
    clean = [item.strip() for item in items if item and item.strip()]
    if not clean:
        return ""
    return title + "\n" + "\n".join([f"• {item}" for item in clean])


def _llm_config() -> tuple[str, str, str, str] | None:
    """Load LLM provider config from environment."""
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
    _logging.getLogger(__name__).warning("Gemini 429 quota cooling down for %.0fs.", delay)




def _compile_market_context_snapshot() -> dict[str, Any]:
    snapshot = _load_snapshot() or {}
    return {
        "news": snapshot.get("news") or [],
        "stocks": snapshot.get("stocks") or [],
        "updatedAt": snapshot.get("updatedAt"),
        "activePool": snapshot.get("activePool"),
    }


def _canonicalize_ledger_rows(rows: list[dict[str, Any]], focus_ticker: str | None = None) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    for row in rows:
        ticker = row.get("ticker") or row.get("ticker_symbol") or row.get("symbol")
        if not ticker:
            continue
        score = row.get("score")
        if score is None:
            score = row.get("alpha_score") or row.get("engine_score") or row.get("rank_score") or 0
        canonical.append(
            {
                "ticker": ticker,
                "name": row.get("name") or row.get("company_name") or row.get("label") or ticker,
                "ltp": row.get("ltp") or row.get("live_price") or row.get("price") or row.get("intraday_trigger_point") or row.get("trigger_point") or "",
                "delta": row.get("delta") or row.get("day_change_pct") or row.get("change_pct") or "",
                "score": _format_score(score),
                "action": row.get("action") or row.get("intraday_trigger_point") or row.get("momentum_catalyst") or "",
                "selection_reason": row.get("selection_reason") or row.get("sharp_execution_risk") or row.get("execution_risk") or "",
                "focus": ticker == focus_ticker,
            }
        )
    return canonical


def _heuristic_analysis(
    live_unstructured_stream: str,
    focus_ticker: str | None = None,
) -> CompleteSecurityAnalysisPayload:
    """Deterministic heuristic analysis used when LLM is unavailable."""
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
            "action": s.get("verdict") or s.get("action") or "Heuristic selection",
            "wl_ratio": "—",
            "policy_allocation_pct": "—",
        })

    return CompleteSecurityAnalysisPayload(
        news_catalysts_card=news_catalysts,
        insider_insti_activity_card="",
        macro_anchors_card="",
        forensic_screen_card=(f"Top picks: {', '.join([row['ticker'] for row in ledger[:5]])}" if ledger else ""),
        why_interested=(f"Focused analysis on {focus_ticker}." if focus_ticker else "Heuristic selection (LLM unavailable)."),
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
        active_risk_calc={
            "max_score": max([r['score'] for r in ledger], default=0.0),
            "selection_risk": "moderate",
            "signal_quality": "heuristic"
        },
        active_factor_hub={"selection_reason": "momentum+volume heuristic"},
    )


def execute_terminal_intelligence_pipeline(live_unstructured_stream: str) -> CompleteSecurityAnalysisPayload:
    """Execute LLM-driven or heuristic terminal intelligence analysis."""
    focus_match = re.search(r"FOCUS_TICKER:\s*([A-Z0-9._-]+)", live_unstructured_stream or "")
    focus_ticker = focus_match.group(1) if focus_match else None

    llm_config = _llm_config()
    if llm_config is not None and _llm_quota_available():
        provider, api_key, api_url, model = llm_config
        try:
            system_instruction = (
                "You are an elite institutional financial terminal compiler. "
                "Analyze the provided market intelligence and return a single valid JSON object "
                "matching the CompleteSecurityAnalysisPayload schema exactly. "
                "All fields must be present. Numeric scores should be numbers, percentages as '4.50%'. "
                "Include ALL of these forensic scoring fields in active_scoring_matrix: "
                "beneish_m_score, altman_z_score, ocf_ebitda_ratio, mansfield_relative_strength. "
                "Return 'N/A' if unavailable. Do not include markdown or explanations."
            )
            if focus_ticker:
                system_instruction += f"\nFOCUS: Provide deep analysis specifically on {focus_ticker}."

            if provider == "gemini":
                raw = _call_gemini(live_unstructured_stream, api_key, model, system_instruction, LLM_CALL_TIMEOUT_SECONDS)
            else:
                raw = _call_openai(live_unstructured_stream, api_key, api_url, model, LLM_CALL_TIMEOUT_SECONDS)

            data = json.loads(raw)
            result = CompleteSecurityAnalysisPayload.model_validate(data)
            return result
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str:
                _record_quota_error(err_str)
            _logging.getLogger(__name__).warning("LLM call failed, falling back to heuristic: %s", err_str)

    # Heuristic fallback
    return _heuristic_analysis(live_unstructured_stream, focus_ticker)


__all__ = ["execute_terminal_intelligence_pipeline"]
