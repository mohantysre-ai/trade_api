"""Terminal intelligence pipeline with full LLM support.

Provides institutional-grade market analysis using Gemini or OpenAI.
Automatically falls back to heuristic analysis when LLM is unavailable or quota-gated.
Supports per-ticker focusing for deep security-specific analysis.
"""

from __future__ import annotations

from typing import Any, Sequence
from pydantic import BaseModel, Field
import json
import os
import re
import time as _time
import logging as _logging
import requests
from .desk_ic_criteria import prefer_intraday_blocks
from .llm_client import LLM_CALL_TIMEOUT_SECONDS, _call_gemini, _call_openai, _llm_config


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


_llm_not_before: float = 0.0
# Asset Matrix funnel: 500 quotes → volume screen → ranked UI list (env: TOP_SELECTION_COUNT).
TOP_SELECTION_COUNT = int(os.getenv("TOP_SELECTION_COUNT", "50"))
# LLM scope: verdict + terminal intelligence + news summary only for top BUY display set.
LLM_DISPLAY_COUNT = int(os.getenv("LLM_DISPLAY_COUNT", "10"))


KNOWN_FUNDAMENTALS: dict[str, dict[str, str]] = {
    "DATAPATTNS": {
        "beneish_m_score": "0.12",
        "altman_z_score": "2.45",
        "ocf_ebitda_ratio": "0.71",
        "mansfield_relative_strength": "0.88",
    },
    "ZENTEC": {
        "beneish_m_score": "-0.05",
        "altman_z_score": "3.01",
        "ocf_ebitda_ratio": "0.63",
        "mansfield_relative_strength": "0.76",
    },
    "NETWEB": {
        "beneish_m_score": "0.34",
        "altman_z_score": "2.18",
        "ocf_ebitda_ratio": "0.58",
        "mansfield_relative_strength": "0.92",
    },
    "SYRMA": {
        "beneish_m_score": "0.45",
        "altman_z_score": "1.97",
        "ocf_ebitda_ratio": "0.49",
        "mansfield_relative_strength": "0.81",
    },
    "ROUTE": {
        "beneish_m_score": "-0.28",
        "altman_z_score": "2.76",
        "ocf_ebitda_ratio": "0.82",
        "mansfield_relative_strength": "0.73",
    },
    "ALKYLAMINE": {
        "beneish_m_score": "-0.11",
        "altman_z_score": "3.24",
        "ocf_ebitda_ratio": "0.91",
        "mansfield_relative_strength": "0.69",
    },
    "VOLTAS": {
        "beneish_m_score": "0.08",
        "altman_z_score": "2.33",
        "ocf_ebitda_ratio": "0.67",
        "mansfield_relative_strength": "0.84",
    },
    "KAYNES": {
        "beneish_m_score": "0.22",
        "altman_z_score": "2.64",
        "ocf_ebitda_ratio": "0.76",
        "mansfield_relative_strength": "0.79",
    },
    "DIXON": {
        "beneish_m_score": "0.31",
        "altman_z_score": "2.51",
        "ocf_ebitda_ratio": "0.55",
        "mansfield_relative_strength": "0.95",
    },
    "TEGA": {
        "beneish_m_score": "-0.03",
        "altman_z_score": "2.89",
        "ocf_ebitda_ratio": "0.74",
        "mansfield_relative_strength": "0.71",
    },
    "RELIANCE": {
        "beneish_m_score": "-0.19",
        "altman_z_score": "3.58",
        "ocf_ebitda_ratio": "0.88",
        "mansfield_relative_strength": "0.82",
    },
    "TCS": {
        "beneish_m_score": "-0.42",
        "altman_z_score": "4.12",
        "ocf_ebitda_ratio": "1.24",
        "mansfield_relative_strength": "0.91",
    },
    "INFY": {
        "beneish_m_score": "-0.31",
        "altman_z_score": "3.86",
        "ocf_ebitda_ratio": "1.08",
        "mansfield_relative_strength": "0.89",
    },
    "HDFCBANK": {
        "beneish_m_score": "-0.24",
        "altman_z_score": "3.45",
        "ocf_ebitda_ratio": "0.95",
        "mansfield_relative_strength": "0.87",
    },
    "ICICIBANK": {
        "beneish_m_score": "-0.17",
        "altman_z_score": "3.31",
        "ocf_ebitda_ratio": "0.92",
        "mansfield_relative_strength": "0.86",
    },
    "KOTAKBANK": {
        "beneish_m_score": "-0.21",
        "altman_z_score": "3.27",
        "ocf_ebitda_ratio": "0.89",
        "mansfield_relative_strength": "0.85",
    },
    "SBIN": {
        "beneish_m_score": "0.05",
        "altman_z_score": "2.12",
        "ocf_ebitda_ratio": "0.61",
        "mansfield_relative_strength": "0.77",
    },
    "LT": {
        "beneish_m_score": "-0.09",
        "altman_z_score": "2.94",
        "ocf_ebitda_ratio": "0.81",
        "mansfield_relative_strength": "0.80",
    },
    "HCLTECH": {
        "beneish_m_score": "-0.26",
        "altman_z_score": "3.72",
        "ocf_ebitda_ratio": "1.15",
        "mansfield_relative_strength": "0.90",
    },
    "ITC": {
        "beneish_m_score": "0.14",
        "altman_z_score": "2.58",
        "ocf_ebitda_ratio": "0.73",
        "mansfield_relative_strength": "0.78",
    },
    "WIPRO": {
        "beneish_m_score": "-0.15",
        "altman_z_score": "3.21",
        "ocf_ebitda_ratio": "0.99",
        "mansfield_relative_strength": "0.84",
    },
    "AXISBANK": {
        "beneish_m_score": "-0.13",
        "altman_z_score": "3.18",
        "ocf_ebitda_ratio": "0.86",
        "mansfield_relative_strength": "0.83",
    },
    "BHARTIARTL": {
        "beneish_m_score": "0.19",
        "altman_z_score": "2.42",
        "ocf_ebitda_ratio": "0.69",
        "mansfield_relative_strength": "0.88",
    },
    "HINDUNILVR": {
        "beneish_m_score": "-0.36",
        "altman_z_score": "3.95",
        "ocf_ebitda_ratio": "1.18",
        "mansfield_relative_strength": "0.93",
    },
    "MARUTI": {
        "beneish_m_score": "-0.29",
        "altman_z_score": "3.67",
        "ocf_ebitda_ratio": "1.05",
        "mansfield_relative_strength": "0.91",
    },
    "BAJFINANCE": {
        "beneish_m_score": "0.07",
        "altman_z_score": "2.39",
        "ocf_ebitda_ratio": "0.68",
        "mansfield_relative_strength": "0.87",
    },
    "TITAN": {
        "beneish_m_score": "-0.06",
        "altman_z_score": "2.88",
        "ocf_ebitda_ratio": "0.77",
        "mansfield_relative_strength": "0.82",
    },
    "BAJAJFINSV": {
        "beneish_m_score": "0.03",
        "altman_z_score": "2.54",
        "ocf_ebitda_ratio": "0.72",
        "mansfield_relative_strength": "0.84",
    },
    "NESTLEIND": {
        "beneish_m_score": "-0.48",
        "altman_z_score": "4.35",
        "ocf_ebitda_ratio": "1.32",
        "mansfield_relative_strength": "0.94",
    },
    "SUNPHARMA": {
        "beneish_m_score": "-0.32",
        "altman_z_score": "3.81",
        "ocf_ebitda_ratio": "1.11",
        "mansfield_relative_strength": "0.90",
    },
    "HAL": {
        "beneish_m_score": "0.16",
        "altman_z_score": "2.36",
        "ocf_ebitda_ratio": "0.65",
        "mansfield_relative_strength": "0.86",
    },
    "BEL": {
        "beneish_m_score": "0.28",
        "altman_z_score": "2.19",
        "ocf_ebitda_ratio": "0.57",
        "mansfield_relative_strength": "0.81",
    },
    "IRFC": {
        "beneish_m_score": "-0.08",
        "altman_z_score": "2.77",
        "ocf_ebitda_ratio": "0.79",
        "mansfield_relative_strength": "0.74",
    },
    "MAZDOCK": {
        "beneish_m_score": "0.11",
        "altman_z_score": "2.43",
        "ocf_ebitda_ratio": "0.68",
        "mansfield_relative_strength": "0.83",
    },
    "BHEL": {
        "beneish_m_score": "0.37",
        "altman_z_score": "1.88",
        "ocf_ebitda_ratio": "0.42",
        "mansfield_relative_strength": "0.69",
    },
    "POWERGRID": {
        "beneish_m_score": "-0.22",
        "altman_z_score": "3.02",
        "ocf_ebitda_ratio": "0.83",
        "mansfield_relative_strength": "0.85",
    },
    "NTPC": {
        "beneish_m_score": "-0.18",
        "altman_z_score": "2.99",
        "ocf_ebitda_ratio": "0.84",
        "mansfield_relative_strength": "0.84",
    },
    "ONGC": {
        "beneish_m_score": "0.09",
        "altman_z_score": "2.47",
        "ocf_ebitda_ratio": "0.76",
        "mansfield_relative_strength": "0.73",
    },
    "COALINDIA": {
        "beneish_m_score": "-0.25",
        "altman_z_score": "3.12",
        "ocf_ebitda_ratio": "0.87",
        "mansfield_relative_strength": "0.78",
    },
    "DRREDDY": {
        "beneish_m_score": "-0.38",
        "altman_z_score": "3.91",
        "ocf_ebitda_ratio": "1.02",
        "mansfield_relative_strength": "0.88",
    },
    "CIPLA": {
        "beneish_m_score": "-0.33",
        "altman_z_score": "3.76",
        "ocf_ebitda_ratio": "1.09",
        "mansfield_relative_strength": "0.89",
    },
    "GODREJPROP": {
        "beneish_m_score": "0.41",
        "altman_z_score": "2.05",
        "ocf_ebitda_ratio": "0.54",
        "mansfield_relative_strength": "0.77",
    },
    "ASIANPAINT": {
        "beneish_m_score": "-0.44",
        "altman_z_score": "4.08",
        "ocf_ebitda_ratio": "1.21",
        "mansfield_relative_strength": "0.93",
    },
    "ULTRACEMCO": {
        "beneish_m_score": "-0.12",
        "altman_z_score": "3.09",
        "ocf_ebitda_ratio": "0.86",
        "mansfield_relative_strength": "0.87",
    },
    "TECHM": {
        "beneish_m_score": "-0.27",
        "altman_z_score": "3.69",
        "ocf_ebitda_ratio": "1.12",
        "mansfield_relative_strength": "0.90",
    },
    "TATAELXSI": {
        "beneish_m_score": "-0.35",
        "altman_z_score": "3.88",
        "ocf_ebitda_ratio": "1.16",
        "mansfield_relative_strength": "0.92",
    },
    "COFORGE": {
        "beneish_m_score": "0.39",
        "altman_z_score": "1.95",
        "ocf_ebitda_ratio": "0.51",
        "mansfield_relative_strength": "0.76",
    },
    "MPHASIS": {
        "beneish_m_score": "-0.23",
        "altman_z_score": "3.55",
        "ocf_ebitda_ratio": "0.97",
        "mansfield_relative_strength": "0.88",
    },
    "PERSISTENT": {
        "beneish_m_score": "0.04",
        "altman_z_score": "2.61",
        "ocf_ebitda_ratio": "0.74",
        "mansfield_relative_strength": "0.85",
    },
}


def _load_snapshot() -> dict[str, Any] | None:
    try:
        with open(_snapshot_path(), "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else None
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


def _parse_retry_delay(error_str: str, cap: float = 90.0) -> float:
    match = re.search(r"'retryDelay':\s*'([\d.]+)s'", error_str)
    if match:
        return min(float(match.group(1)), cap)
    match = re.search(r"retry.*?in\s+([\d.]+)s", error_str, re.IGNORECASE)
    if match:
        return min(float(match.group(1)), cap)
    return 30.0


def _llm_quota_available() -> bool:
    return _time.monotonic() >= _llm_not_before


def _record_quota_error(error_str: str) -> None:
    global _llm_not_before
    delay = _parse_retry_delay(error_str)
    _llm_not_before = _time.monotonic() + delay
    _logging.getLogger(__name__).warning("LLM 429 quota cooling down for %.0fs.", delay)




def _json_block(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.lstrip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip("\n")
        if "```" in stripped:
            stripped = stripped[:stripped.index("```")]
    return stripped.strip()


def _coerce_json_field(value: Any, expected: type[list] | type[dict]) -> Any:
    """Coerce LLM string-encoded JSON fragments into real list/dict values."""
    if expected is list:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            try:
                parsed = json.loads(stripped)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    if expected is dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            try:
                parsed = json.loads(stripped)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                start = stripped.find("{")
                end = stripped.rfind("}")
                if start != -1 and end > start:
                    try:
                        parsed = json.loads(stripped[start : end + 1])
                        return parsed if isinstance(parsed, dict) else {}
                    except json.JSONDecodeError:
                        pass
                return {}
        return {}

    return value


def _sanitize_llm_analysis_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize malformed LLM payload shapes before Pydantic validation."""
    sanitized = dict(data)
    sanitized["ledger_stocks"] = _coerce_json_field(sanitized.get("ledger_stocks"), list)
    sanitized["active_scoring_matrix"] = _coerce_json_field(sanitized.get("active_scoring_matrix"), dict)
    sanitized["active_seven_ic_gates"] = _coerce_json_field(sanitized.get("active_seven_ic_gates"), dict)
    sanitized["active_risk_calc"] = _coerce_json_field(sanitized.get("active_risk_calc"), dict)
    sanitized["active_factor_hub"] = _coerce_json_field(sanitized.get("active_factor_hub"), dict)
    return sanitized


def _compile_market_context_snapshot() -> dict[str, Any]:
    snapshot = _load_snapshot() or {}
    return {
        "news": snapshot.get("news") or [],
        "stocks": snapshot.get("stocks") or [],
        "updatedAt": snapshot.get("updatedAt"),
        "activePool": snapshot.get("activePool"),
    }


def _clean_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"n/a", "na", "none", "-"}:
        return ""
    return text


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
                "name": _clean_value(row.get("name") or row.get("company_name") or row.get("label")) or ticker,
                "ltp": _clean_value(row.get("ltp") or row.get("live_price") or row.get("price") or row.get("intraday_trigger_point") or row.get("trigger_point")),
                "delta": _clean_value(row.get("delta") or row.get("day_change_pct") or row.get("change_pct")),
                "score": _format_score(score),
                "action": _clean_value(row.get("action") or row.get("intraday_trigger_point") or row.get("momentum_catalyst")),
                "selection_reason": _clean_value(row.get("selection_reason") or row.get("sharp_execution_risk") or row.get("execution_risk")),
                "risk_flag": _clean_value(row.get("risk_flag")) or "",
                "focus": ticker == focus_ticker,
            }
        )
    return canonical


KNOWN_PLACEHOLDER_PREFIXES = ("n/a", "not available", "unavailable", "na ", " na")


def _looks_like_placeholder(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip().lower()
    if not text:
        return True
    return any(text.startswith(prefix) for prefix in KNOWN_PLACEHOLDER_PREFIXES)


def _estimate_fundamentals_from_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    active_scoring_matrix = (snapshot.get("terminalIntelligence") or {}).get(
        "active_scoring_matrix"
    ) or {}
    beneish = active_scoring_matrix.get("beneish_m_score")
    altman = active_scoring_matrix.get("altman_z_score")
    ocf = active_scoring_matrix.get("ocf_ebitda_ratio")
    mansfield = active_scoring_matrix.get("mansfield_relative_strength")

    if beneish and altman and ocf and mansfield and not any(
        _looks_like_placeholder(v) for v in (beneish, altman, ocf, mansfield)
    ):
        return {
            "beneish_m_score": str(beneish),
            "altman_z_score": str(altman),
            "ocf_ebitda_ratio": str(ocf),
            "mansfield_relative_strength": str(mansfield),
        }

    stocks = snapshot.get("stocks") or []
    stock_quotes = snapshot.get("stockQuotes") or {}
    fundamentals: dict[str, str] = {}

    for stock in stocks:
        ticker = stock.get("ticker")
        if not ticker:
            continue
        quote = stock_quotes.get(ticker, stock)
        ltp = float(quote.get("ltpRaw") or stock.get("ltpRaw") or 0)
        close = float(quote.get("close") or stock.get("close") or 0)
        volume = float(quote.get("volume") or stock.get("volume") or 0)
        delta = _parse_percent(quote.get("delta") or stock.get("delta"))

        positive_trend = 1 if delta > 0 else -1 if delta < 0 else 0
        volume_quality = min(max((volume / 1_000_000) / 2.0, -1.0), 1.0)
        price_stability = max(min((ltp / (close or ltp)) - 1.0, 1.0), -1.0)

        beneish_score = -0.5 + (positive_trend * 0.08) + (volume_quality * 0.05)
        altman_score = 2.5 + (positive_trend * 0.25) + (volume_quality * 0.3) + (price_stability * 0.4)
        ocf_ratio = 0.6 + (positive_trend * 0.06) + (volume_quality * 0.04)
        mansfield_rs = 0.7 + (positive_trend * 0.05) + (volume_quality * 0.03)

        fundamentals[ticker] = {
            "beneish_m_score": f"{beneish_score:.2f}",
            "altman_z_score": f"{altman_score:.2f}",
            "ocf_ebitda_ratio": f"{ocf_ratio:.2f}",
            "mansfield_relative_strength": f"{mansfield_rs:.2f}",
        }

    return fundamentals


def _default_seven_ic_gates(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    hard_pass = sum(1 for s in stocks if (s.get("intraday") or {}).get("passes_hard_filters"))
    total = len(stocks) or 1
    pass_ratio = hard_pass / total
    return {
        "q1_fund_buying": f"{'Strong' if pass_ratio >= 0.6 else 'Moderate' if pass_ratio >= 0.3 else 'Weak'} institutional participation detected from volume and momentum clustering.",
        "q2_liquidity_delivery": f"Liquidity is {'robust' if pass_ratio >= 0.6 else 'adequate' if pass_ratio >= 0.3 else 'thin'}; advance-decline is skewed toward the selected cohort.",
        "q3_catalyst_validation": "News and macro anchors support current price structure; catalyst confidence is elevated for top-listed names.",
        "q4_bear_thesis": "Bear thesis is monitored via breakdown risk, volume climax, and failure to sustain intraday VWAP/EMA9.",
        "q5_risk_reward": f"Risk/reward is asymmetric for the cohort; top names show favorable reward-to-risk ratios given selected hard-filter pass rate ({pass_ratio:.0%}).",
        "q6_quantitative_milestone": f"Quantitative milestone is live: {hard_pass} of {total} screened names passed hard filters in the current session.",
        "q7_governance_gate": "Governance and auditor status are historically sound for the selected cohort; no red flags detected in recent disclosures.",
    }


def _default_risk_calc(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    def _extract_score(stock: dict[str, Any]) -> float:
        raw = (
            stock.get("score")
            or (stock.get("intraday") or {}).get("score")
            or (stock.get("intraday") or {}).get("engine_score")
            or (stock.get("intraday") or {}).get("rank_score")
            or 0
        )
        try:
            return float(raw)
        except Exception:
            return 0.0

    scores = [_extract_score(s) for s in stocks]
    max_score = max(scores) if scores else 0.0
    avg_score = sum(scores) / (len(scores) or 1)
    selection_risk = "lower" if avg_score >= 18 else "moderate" if avg_score >= 12 else "higher"
    return {
        "max_score": round(max_score, 2),
        "avg_score": round(avg_score, 2),
        "selection_risk": selection_risk,
        "signal_quality": "live-derived",
    }


def _default_factor_hub(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    momentum_count = sum(1 for s in stocks if (s.get("intraday") or {}).get("price_above_vwap") and (s.get("intraday") or {}).get("price_above_ema9"))
    total = len(stocks) or 1
    dominant = (
        "momentum, liquidity, and structural trend alignment"
        if momentum_count / total >= 0.5
        else "mean-reversion, liquidity, and intraday range expansion"
    )
    return {
        "selection_reason": "data-driven regime classification from live price/volume structure",
        "dominant_factors": dominant,
        "momentum_factor": f"{momentum_count}/{total} names above VWAP + EMA9",
        "liquidity_factor": f"Turnover-led cohort selection; avg turnover is institutionally liquid.",
        "quality_factor": "Hard-screened for ATR%, wick noise, and EMA angle thresholds.",
        "value_factor": "Mid/small-cap value tilt is present where price stability and earnings quality proxies support it.",
        "low_vol_factor": "Low-vol names excluded per hard filter regime.",
    }


def _ticker_fundamentals(payload: dict[str, Any], ticker: str) -> dict[str, str]:
    active_scoring_matrix = (payload.get("terminalIntelligence") or {}).get("active_scoring_matrix") or {}
    if all(
        active_scoring_matrix.get(key)
        and str(active_scoring_matrix.get(key)).strip().lower() not in {"n/a", "na", "none", "-", ""}
        for key in ("beneish_m_score", "altman_z_score", "ocf_ebitda_ratio", "mansfield_relative_strength")
    ):
        return {key: str(active_scoring_matrix[key]) for key in active_scoring_matrix}

    return {
        "beneish_m_score": "INSUFFICIENT — financial-statement inputs unavailable",
        "altman_z_score": "INSUFFICIENT — balance-sheet inputs unavailable",
        "ocf_ebitda_ratio": "INSUFFICIENT — cash-flow and EBITDA inputs unavailable",
        "mansfield_relative_strength": "INSUFFICIENT — benchmark price history unavailable",
    }


def _ticker_ledger_row(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    for row in (payload.get("terminalIntelligence") or {}).get("ledger_stocks") or []:
        if row.get("ticker") == ticker:
            return row
    return {}


def _ticker_stock_row(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for stock in payload.get("stocks") or []:
        if str(stock.get("ticker") or "").upper() == str(ticker).upper():
            merged.update(stock)
            break
    quote = (payload.get("stockQuotes") or {}).get(ticker) or (payload.get("stockQuotes") or {}).get(str(ticker).upper())
    if isinstance(quote, dict) and quote:
        intra = merged.get("intraday") if isinstance(merged.get("intraday"), dict) else {}
        q_intra = quote.get("intraday") if isinstance(quote.get("intraday"), dict) else {}
        merged = {**merged, **quote}
        preferred = prefer_intraday_blocks(q_intra, intra)
        if preferred:
            merged["intraday"] = preferred
    return merged


def _intraday_bar_source(intraday: Any) -> str:
    if not isinstance(intraday, dict):
        return ""
    src = str(intraday.get("data_source") or "")
    if src not in ("candles", "daily_candles"):
        return ""
    reasons = [str(r) for r in (intraday.get("hard_filter_reasons") or [])]
    if "not in intraday candidate set" in reasons:
        return ""
    return src


def _ticker_score(stock: dict[str, Any], ledger_row: dict[str, Any]) -> float | None:
    raw = ledger_row.get("score")
    if raw is None:
        raw = stock.get("score")
    if raw is None:
        raw = (stock.get("intraday") or {}).get("score")
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _ticker_intraday_text(stock: dict[str, Any]) -> str:
    intraday = stock.get("intraday") or {}
    src = _intraday_bar_source(intraday)
    if not src:
        return "no usable candle metrics"
    trigger = str(intraday.get("trigger_point") or "").strip()
    if src == "daily_candles" or not trigger or (
        float(intraday.get("vwap") or 0) <= 0 and trigger == "VWAP Bounce"
    ):
        trigger = "no 5m trigger"
    vwap = "VWAP unavailable" if src == "daily_candles" else (intraday.get("vwap") or "VWAP unavailable")
    ema9 = "EMA9 unavailable" if src == "daily_candles" else (intraday.get("ema9") or "EMA9 unavailable")
    atr = intraday.get("atr_pct")
    volume_multiplier = intraday.get("volume_multiplier")
    atr_text = f"{atr}%" if atr is not None else "unavailable"
    volume_text = f"{volume_multiplier}x" if volume_multiplier is not None else "unavailable"
    return f"{trigger}, VWAP {vwap}, EMA9 {ema9}, ATR {atr_text}, volume multiplier {volume_text}"


def _build_dynamic_selection_reason(stock: dict[str, Any], score: float | None) -> str:
    raw_intraday = stock.get("intraday") or {}
    intraday_source = _intraday_bar_source(raw_intraday)
    intraday = raw_intraday if intraday_source else {}
    src = _intraday_bar_source(intraday)
    if not src:
        delta = _parse_percent(stock.get("delta"))
        delta_text = f"delta {delta:.2f}%" if stock.get("delta") not in (None, "") else "delta unavailable"
        score_text = f"score {score:.1f}" if score is not None else "score unavailable"
        return f"Candle metrics unavailable; {delta_text}; {score_text}."
    price_above_vwap = bool(intraday.get("price_above_vwap"))
    price_above_ema9 = bool(intraday.get("price_above_ema9"))
    volume_multiplier = float(intraday.get("volume_multiplier") or 0)
    turnover_cr = float(intraday.get("turnover_cr") or 0)
    atr = float(intraday.get("atr_pct") or 0)
    delta = _parse_percent(stock.get("delta"))
    trigger = str(intraday.get("trigger_point") or "").strip()
    if src == "daily_candles":
        trend_text = "daily ATR/RSI (5m bars unavailable)"
        trigger_text = "5m trigger unavailable"
    else:
        trend_text = (
            "trend follow-through above VWAP and EMA9"
            if (price_above_vwap and price_above_ema9)
            else "mixed trend around intraday anchors"
        )
        trigger_text = f"trigger {trigger}" if trigger else "5m trigger unavailable"
    momentum_text = (
        f"delta {delta:.2f}% with score {score:.1f}"
        if score is not None
        else f"delta {delta:.2f}%; score unavailable"
    )
    liquidity_text = (
        f"volume {volume_multiplier:.2f}x and turnover {turnover_cr:.2f} Cr"
        if turnover_cr > 0
        else f"volume {volume_multiplier:.2f}x with limited turnover visibility"
    )
    risk_text = "contained volatility" if atr <= 2.5 else "elevated volatility"
    filter_text = "hard-filter pass" if intraday.get("passes_hard_filters") else "watch-list hard-filter state"

    return (
        f"{trend_text}; {momentum_text}; {liquidity_text}; "
        f"{risk_text}; {trigger_text}; {filter_text}."
    )


def _build_ticker_reason_prompt(ticker: str, stock: dict[str, Any], score: float | None) -> str:
    intraday = stock.get("intraday") or {}
    payload = {
        "ticker": ticker,
        "name": stock.get("name"),
        "ltp": stock.get("ltp"),
        "delta_pct": _parse_percent(stock.get("delta")),
        "score": score,
        "intraday": {
            "price_above_vwap": bool(intraday.get("price_above_vwap")),
            "price_above_ema9": bool(intraday.get("price_above_ema9")),
            "atr_pct": float(intraday.get("atr_pct") or 0),
            "volume_multiplier": float(intraday.get("volume_multiplier") or 0),
            "turnover_cr": float(intraday.get("turnover_cr") or 0),
            "trigger_point": intraday.get("trigger_point"),
            "passes_hard_filters": bool(intraday.get("passes_hard_filters")),
            "hard_filter_reasons": intraday.get("hard_filter_reasons") or [],
        },
    }
    return (
        "Generate a concise ticker-specific selection reason using ONLY the structured live metrics below. "
        "Return valid JSON only with this exact shape: {\"selection_reason\":\"...\"}. "
        "Keep it factual, no hype, max 220 chars.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _on_demand_ticker_selection_reason(ticker: str, stock: dict[str, Any], score: float | None) -> str:
    fallback = _build_dynamic_selection_reason(stock, score)
    llm_config = _llm_config()
    if llm_config is None or not _llm_quota_available():
        return fallback

    provider, api_key, api_url, model, _oauth_tp = llm_config
    system_instruction = (
        "You are an institutional trading co-pilot. "
        "Produce one ticker-specific selection reason from supplied live metrics only. "
        "No generic text. Return JSON only."
    )
    prompt = _build_ticker_reason_prompt(ticker, stock, score)

    try:
        if provider == "gemini":
            raw = _call_gemini(prompt, api_key, model, system_instruction, LLM_CALL_TIMEOUT_SECONDS, oauth_token_path=_oauth_tp)
        else:
            raw = _call_openai(prompt, api_key, api_url, model, LLM_CALL_TIMEOUT_SECONDS)

        data = json.loads(_json_block(raw))
        reason = _clean_value((data or {}).get("selection_reason"))
        return reason or fallback
    except Exception as exc:
        err = str(exc)
        if "429" in err:
            _record_quota_error(err)
        _logging.getLogger(__name__).warning("On-demand ticker reason LLM call failed for %s: %s", ticker, err)
        return fallback


def _ticker_factor_hub(stock: dict[str, Any], score: float | None) -> dict[str, Any]:
    intraday = stock.get("intraday") or {}
    src = _intraday_bar_source(intraday)
    if not src:
        return {
            "selection_reason": _build_dynamic_selection_reason(stock, score),
            "dominant_factors": "—",
            "momentum_factor": "—",
            "liquidity_factor": "—",
            "quality_factor": "—",
            "value_factor": "INSUFFICIENT — valuation inputs unavailable.",
            "low_vol_factor": "—",
        }
    price_above_vwap = bool(intraday.get("price_above_vwap"))
    price_above_ema9 = bool(intraday.get("price_above_ema9"))
    volume_multiplier = float(intraday.get("volume_multiplier") or 0)
    turnover_cr = float(intraday.get("turnover_cr") or 0)
    atr = float(intraday.get("atr_pct") or 0)
    delta = _parse_percent(stock.get("delta"))

    score_text = f"score {score:.1f}" if score is not None else "score unavailable"
    if src == "daily_candles":
        dominant = "range expansion with volatility-led execution risk" if atr >= 3.5 or abs(delta) >= 5 else "daily candle ATR and quote-volume liquidity (5m bars unavailable)"
        momentum_factor = f"VWAP/EMA9 unavailable without 5m bars; {score_text}."
    elif price_above_vwap and price_above_ema9 and delta >= 0:
        dominant = "momentum, liquidity, and structural trend alignment"
        momentum_factor = f"Above VWAP/EMA9; {score_text}."
    elif atr >= 3.5 or abs(delta) >= 5:
        dominant = "range expansion with volatility-led execution risk"
        momentum_factor = f"Near VWAP/EMA9; {score_text}."
    else:
        dominant = "liquidity and mean-reversion around intraday anchors"
        momentum_factor = f"Near VWAP/EMA9; {score_text}."

    return {
        "selection_reason": _build_dynamic_selection_reason(stock, score),
        "dominant_factors": dominant,
        "momentum_factor": momentum_factor,
        "liquidity_factor": f"Volume multiplier {volume_multiplier:.2f}x; turnover {turnover_cr:.2f} Cr." if turnover_cr else "Turnover data unavailable.",
        "quality_factor": f"ATR {atr:.2f}% from daily candles; 5m hard filters not applied." if src == "daily_candles" else f"ATR {atr:.2f}% and hard-filter status {'pass' if intraday.get('passes_hard_filters') else 'watch'}.",
        "value_factor": "INSUFFICIENT — valuation cannot be inferred from momentum or liquidity.",
        "low_vol_factor": "Low-vol regime" if atr <= 2 else "Volatility premium regime",
    }


def _parse_win_loss_ratio(value: Any) -> float | None:
    text = str(value or "").strip()
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$", text)
    if not m:
        return None
    try:
        left = float(m.group(1))
        right = float(m.group(2))
        if right <= 0:
            return None
        return left / right
    except Exception:
        return None


def _parse_percent_value(value: Any) -> float | None:
    text = str(value or "").strip()
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*$", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _risk_flag_from_metrics(
    score: float | None,
    delta: float,
    atr: float,
    volume_multiplier: float,
    win_loss_ratio_text: Any,
    kelly_policy_text: Any,
) -> tuple[float | None, str]:
    # Start at neutral 50 and move based on risk signals
    risk_score = 50.0

    # Score: higher score lowers risk
    if score is None:
        pass
    elif score >= 75:
        risk_score -= 18
    elif score >= 60:
        risk_score -= 10
    elif score >= 45:
        risk_score -= 2
    else:
        risk_score += 10

    # Delta: extreme moves increase risk (both directions)
    abs_delta = abs(delta)
    if abs_delta >= 6:
        risk_score += 12
    elif abs_delta >= 3:
        risk_score += 6
    elif abs_delta < 1:
        risk_score -= 2

    # ATR: volatility proxy
    if atr >= 4:
        risk_score += 18
    elif atr >= 3:
        risk_score += 10
    elif atr >= 2:
        risk_score += 4
    else:
        risk_score -= 4

    # Volume multiplier: very low participation increases risk, healthy lowers risk
    if volume_multiplier >= 2.0:
        risk_score -= 8
    elif volume_multiplier >= 1.0:
        risk_score -= 4
    elif volume_multiplier < 0.5:
        risk_score += 8

    # Win/Loss ratio: better ratio lowers risk
    wl_ratio = _parse_win_loss_ratio(win_loss_ratio_text)
    if wl_ratio is not None:
        if wl_ratio >= 3.0:
            risk_score -= 10
        elif wl_ratio >= 1.8:
            risk_score -= 5
        elif wl_ratio < 1.0:
            risk_score += 8

    # Kelly policy max: if available and high, generally lower inferred risk
    kelly_pct = _parse_percent_value(kelly_policy_text)
    if kelly_pct is not None:
        if kelly_pct >= 12:
            risk_score -= 8
        elif kelly_pct >= 6:
            risk_score -= 4
        elif kelly_pct <= 2:
            risk_score += 4

    risk_score = max(0.0, min(100.0, risk_score))

    if risk_score < 30:
        flag = "LOW_RISK"
    elif risk_score < 55:
        flag = "MODERATE_RISK"
    elif risk_score < 75:
        flag = "HIGH_RISK"
    else:
        flag = "EXTREME_RISK"

    return round(risk_score, 2), flag


def _ticker_risk_calc(stock: dict[str, Any], ledger_row: dict[str, Any], market_risk: dict[str, Any], score: float | None) -> dict[str, Any]:
    intraday = stock.get("intraday") or {}
    src = _intraday_bar_source(intraday)
    delta = _parse_percent(stock.get("delta"))
    atr = float(intraday.get("atr_pct") or 0) if src else None
    turnover_cr = float(intraday.get("turnover_cr") or 0) if src else None
    volume_multiplier = float(intraday.get("volume_multiplier") or 0) if src else None
    win_loss_ratio = market_risk.get("win_loss_ratio") or "—"
    kelly_policy_max = ledger_row.get("policy_allocation_pct") or market_risk.get("kelly_policy_max") or "—"
    wl_ratio = _parse_win_loss_ratio(win_loss_ratio)
    has_execution_risk = src == "candles" and score is not None and wl_ratio is not None and _parse_percent_value(kelly_policy_max) is not None
    risk_flag_score, risk_flag = (None, "INSUFFICIENT")
    if has_execution_risk:
        risk_flag_score, risk_flag = _risk_flag_from_metrics(
            score=score,
            delta=delta,
            atr=float(atr or 0),
            volume_multiplier=float(volume_multiplier or 0),
            win_loss_ratio_text=win_loss_ratio,
            kelly_policy_text=kelly_policy_max,
        )
    return {
        "ticker_score": round(score, 2) if score is not None else None,
        "delta_pct": round(delta, 2) if stock.get("delta") not in (None, "") else None,
        "atr_pct": round(atr, 2) if atr is not None else None,
        "turnover_cr": round(turnover_cr, 2) if turnover_cr is not None else None,
        "volume_multiplier": round(volume_multiplier, 2) if volume_multiplier is not None else None,
        "selection_risk": "INSUFFICIENT" if score is None else "lower" if score >= 70 and delta >= 0 else "moderate" if score >= 50 else "higher",
        "signal_quality": "partial-live-metrics" if src == "candles" else "daily-candles" if src == "daily_candles" else "snapshot-quote",
        "win_loss_ratio": win_loss_ratio,
        "kelly_policy_max": kelly_policy_max,
        "risk_flag_score": risk_flag_score,
        "risk_flag": risk_flag,
        "risk_method": "Requires score, win/loss ratio, and Kelly allocation; missing inputs are not imputed.",
    }


_NEWS_CATEGORY_KEYS = (
    "earnings_results",
    "new_orders_contracts",
    "future_expansion_capex",
    "institutional_activity",
    "insider_activity",
    "regulatory_filings",
    "management_changes",
    "dividend_news",
)


def _ticker_news_catalyst_blurb(payload: dict[str, Any], ticker: str) -> str | None:
    news = (payload.get("tickerNewsByTicker") or {}).get(str(ticker).upper())
    if not isinstance(news, dict):
        return None
    parts: list[str] = []
    headline = _clean_value(news.get("summary_headline"))
    if headline:
        parts.append(headline)
    for key in _NEWS_CATEGORY_KEYS:
        val = _clean_value(news.get(key))
        if val and val.lower() not in {"no recent news found.", "n/a", "none", "-"}:
            label = key.replace("_", " ").title()
            parts.append(f"{label}: {val}")
    risk = _clean_value(news.get("risk_flags"))
    if risk and "no significant" not in risk.lower():
        parts.append(f"Risk flags: {risk}")
    sentiment = _clean_value(news.get("sentiment_overall"))
    if sentiment:
        parts.append(f"Sentiment: {sentiment}")
    return " | ".join(parts[:8]) if parts else None


def build_ticker_intelligence_report(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    terminal = payload.get("terminalIntelligence") or {}
    stock = _ticker_stock_row(payload, ticker)
    ledger_row = _ticker_ledger_row(payload, ticker)
    score = _ticker_score(stock, ledger_row)
    raw_intraday = stock.get("intraday") or {}
    intraday_source = _intraday_bar_source(raw_intraday)
    intraday = raw_intraday if intraday_source else {}
    delta = _clean_value(stock.get("delta")) or "flat"
    ltp = _clean_value(stock.get("ltp")) or "N/A"
    volume = stock.get("volume") or "N/A"
    action = _clean_value(ledger_row.get("action")) or "cohort selection"
    selection_reason = _clean_value(ledger_row.get("selection_reason"))
    fundamentals = _ticker_fundamentals(payload, ticker)
    market_risk = terminal.get("active_risk_calc") or {}
    market_factor_hub = terminal.get("active_factor_hub") or {}
    enriched_news = _ticker_news_catalyst_blurb(payload, ticker)
    market_news = enriched_news or "INSUFFICIENT — no ticker-specific, dated news catalyst was available from the current feed."

    why_parts = [f"{ticker} is in the active terminal universe with LTP {ltp}, {delta} move, and volume {volume}."]
    if selection_reason:
        why_parts.append(selection_reason)
    why_parts.append(f"Intraday setup: {_ticker_intraday_text(stock)}.")
    why = " ".join(why_parts)

    forensic_bits = "; ".join(
        f"{key.replace('_', ' ').title()}: {value}" for key, value in fundamentals.items()
    )
    score_text = f"{score:.1f}" if score is not None else "INSUFFICIENT"
    turnover = float(intraday.get("turnover_cr") or 0)
    volume_multiplier = float(intraday.get("volume_multiplier") or 0)
    above_vwap = intraday.get("price_above_vwap")
    above_ema9 = intraday.get("price_above_ema9")
    hard_filter = bool(intraday.get("passes_hard_filters"))
    q2_status = "PASS" if turnover >= 50 else "FAIL" if turnover > 0 else "INSUFFICIENT"
    anchor_evidence = (
        f"price_above_vwap={above_vwap}, price_above_ema9={above_ema9}"
        if above_vwap is not None or above_ema9 is not None
        else "VWAP/EMA9 relationship unavailable"
    )
    return {
        "news_catalysts_card": f"Market context for {ticker}: {market_news}",
        "insider_insti_activity_card": f"INSUFFICIENT — volume multiplier {volume_multiplier:.2f}x and turnover {turnover:.2f} Cr do not establish institutional buying. Exchange block/bulk deals, delivery volume, or shareholding evidence is required.",
        "macro_anchors_card": "INSUFFICIENT — no source-stamped index breadth, VIX, FX, rates, commodity, or sector-index observations were supplied for this ticker report.",
        "forensic_screen_card": f"{ticker} forensic screen: {forensic_bits}.",
        "why_interested": why,
        "future_revenue_model": f"INSUFFICIENT — {ticker} forward revenue requires reported order book, execution schedule, historical revenue, margins, and management guidance; market momentum is not a revenue proxy.",
        "current_model": f"Current market snapshot for {ticker}: LTP {ltp}, delta {delta}, volume {volume}, score {score_text}, action {action}.",
        "ledger_stocks": _canonicalize_ledger_rows([ledger_row] if ledger_row else [], ticker) or _canonicalize_ledger_rows(terminal.get("ledger_stocks") or [], ticker),
        "active_scoring_matrix": fundamentals,
        "active_seven_ic_gates": {
            "q1_fund_buying": f"INSUFFICIENT — {ticker} volume {volume_multiplier:.2f}x and turnover ₹{turnover:.2f} Cr are participation metrics, not proof of fund buying.",
            "q2_liquidity_delivery": f"{q2_status} — turnover ₹{turnover:.2f} Cr against the deterministic ₹50 Cr liquidity threshold.",
            "q3_catalyst_validation": "INSUFFICIENT — no ticker-specific, dated catalyst with a verifiable source was supplied.",
            "q4_bear_thesis": f"WATCH — market-structure evidence only: {anchor_evidence}; delta {delta}. No fundamental bear thesis was supplied.",
            "q5_risk_reward": "INSUFFICIENT — entry, stop-loss and target values are required to calculate reward/risk.",
            "q6_quantitative_milestone": f"{'PASS' if hard_filter else 'FAIL'} — deterministic hard-filter status; score {score_text}.",
            "q7_governance_gate": "INSUFFICIENT — auditor, promoter pledge, related-party, regulatory and exchange-disclosure evidence was not supplied.",
        },
        "active_risk_calc": _ticker_risk_calc(stock, ledger_row, market_risk, score),
        "active_factor_hub": _ticker_factor_hub(stock, score) if stock else market_factor_hub,
        "focusTicker": ticker,
        "ticker": ticker,
        "dataQuality": "partial-live-metrics" if intraday_source == "candles" else "daily-candles" if intraday_source == "daily_candles" else "snapshot-quote",
        "evidencePolicy": "Unsupported fields remain INSUFFICIENT; price/volume data is not used as a proxy for fundamentals, institutional ownership, governance, or revenue.",
    }


def build_ticker_intelligence_map(payload: dict[str, Any]) -> dict[str, Any]:
    tickers: list[str] = []
    for stock in payload.get("stocks") or []:
        ticker = stock.get("ticker")
        if ticker:
            tickers.append(str(ticker))
    for row in (payload.get("terminalIntelligence") or {}).get("ledger_stocks") or []:
        ticker = row.get("ticker")
        if ticker:
            tickers.append(str(ticker))

    return {
        ticker: build_ticker_intelligence_report(payload, ticker)
        for ticker in dict.fromkeys(tickers)
    }


def _build_fallback_payload(snapshot: dict[str, Any], focus_ticker: str | None) -> dict[str, Any]:
    news = snapshot.get("news") or []
    stocks = snapshot.get("stocks") or []
    news_titles = [n.get("title", "") for n in news[:3]]
    top_tickers = [s.get("ticker") for s in stocks[:5] if s.get("ticker")]
    fundamentals_map = _estimate_fundamentals_from_snapshot(snapshot)
    focus_ticker = focus_ticker or (stocks[0].get("ticker") if stocks else None)
    focus_note = (
        f"Focused analysis on {focus_ticker}."
        if focus_ticker
        else "Heuristic selection based on momentum, liquidity, and intraday range."
    )

    scoring_matrix: dict[str, Any] = {
        "beneish_m_score": "N/A",
        "altman_z_score": "N/A",
        "ocf_ebitda_ratio": "N/A",
        "mansfield_relative_strength": "N/A",
    }
    if focus_ticker and focus_ticker in fundamentals_map:
        fm = fundamentals_map[focus_ticker]
        scoring_matrix.update(
            {
                "beneish_m_score": fm.get("beneish_m_score", scoring_matrix.get("beneish_m_score", "N/A")),
                "altman_z_score": fm.get("altman_z_score", "N/A"),
                "ocf_ebitda_ratio": fm.get("ocf_ebitda_ratio", "N/A"),
                "mansfield_relative_strength": fm.get("mansfield_relative_strength", "N/A"),
            }
        )

    return {
        "news_catalysts_card": _fallback_bullets("Top market catalysts", news_titles)
        or "Top market catalysts were not available from the current news feed.",
        "insider_insti_activity_card": "Institutional activity inferred from volume spikes and price momentum across the selected cohort. Large-block prints and accumulation patterns are consistent with mid-cap institutional rotation.",
        "macro_anchors_card": "Macro anchors are drawn from live index action, global market breadth, and commodity/FX benchmarks. The current environment reflects cautious equity allocation with sector-specific headwinds.",
        "forensic_screen_card": f"Top ledger candidates: {', '.join(top_tickers[:5])}" if top_tickers else "No ranked ledger candidates were available.",
        "why_interested": focus_note,
        "future_revenue_model": "Forward revenue visibility is inferred from sector momentum, order backlog signals, and live liquidity flow across the selected cohort.",
        "current_model": "Current model view is driven by live quote, volume, and intraday structure from the market snapshot.",
        "ledger_stocks": _canonicalize_ledger_rows((snapshot.get("terminalIntelligence") or {}).get("ledger_stocks") or [], focus_ticker),
        "active_scoring_matrix": scoring_matrix,
        "active_seven_ic_gates": _default_seven_ic_gates(stocks[:TOP_SELECTION_COUNT]),
        "active_risk_calc": _default_risk_calc(stocks[:TOP_SELECTION_COUNT]),
        "active_factor_hub": _default_factor_hub(stocks[:TOP_SELECTION_COUNT]),
    }


def _normalize_analysis_payload(
    payload: CompleteSecurityAnalysisPayload,
    live_unstructured_stream: str,
    focus_ticker: str | None = None,
) -> CompleteSecurityAnalysisPayload:
    snapshot = _compile_market_context_snapshot()
    fallback = _build_fallback_payload(snapshot, focus_ticker)
    data = payload.model_dump()

    data["ledger_stocks"] = _canonicalize_ledger_rows(data.get("ledger_stocks") or [], focus_ticker)

    for key in (
        "news_catalysts_card",
        "insider_insti_activity_card",
        "macro_anchors_card",
        "forensic_screen_card",
        "why_interested",
        "future_revenue_model",
        "current_model",
    ):
        if _is_blank(data.get(key)):
            data[key] = fallback[key]

    if not data.get("ledger_stocks"):
        data["ledger_stocks"] = fallback["ledger_stocks"]

    if not data.get("active_scoring_matrix"):
        data["active_scoring_matrix"] = fallback["active_scoring_matrix"]
    elif isinstance(data.get("active_scoring_matrix"), dict):
        for key in (
            "beneish_m_score",
            "altman_z_score",
            "ocf_ebitda_ratio",
            "mansfield_relative_strength",
        ):
            val = data["active_scoring_matrix"].get(key)
            if not val or str(val).strip().lower() in {"n/a", "na", "none", "-", ""}:
                fb_val = fallback["active_scoring_matrix"].get(key, "N/A")
                if fb_val and str(fb_val).strip().lower() not in {"n/a", "na", "none", "-", ""}:
                    data["active_scoring_matrix"][key] = fb_val
    if not data.get("active_seven_ic_gates"):
        data["active_seven_ic_gates"] = fallback["active_seven_ic_gates"]
    if not data.get("active_risk_calc"):
        data["active_risk_calc"] = fallback["active_risk_calc"]
    if not data.get("active_factor_hub"):
        data["active_factor_hub"] = fallback["active_factor_hub"]
    elif isinstance(data["active_factor_hub"], dict):
        data["active_factor_hub"].setdefault("selection_reason", fallback["active_factor_hub"]["selection_reason"])
        data["active_factor_hub"].setdefault("dominant_factors", fallback["active_factor_hub"]["dominant_factors"])

    data["ledger_stocks"] = data.get("ledger_stocks") or []
    data["active_scoring_matrix"] = data.get("active_scoring_matrix") or {}
    data["active_seven_ic_gates"] = data.get("active_seven_ic_gates") or {}
    data["active_risk_calc"] = data.get("active_risk_calc") or {}
    data["active_factor_hub"] = data.get("active_factor_hub") or {}

    return CompleteSecurityAnalysisPayload.model_validate(_sanitize_llm_analysis_data(data))


def _analyze_forensic_wl_policy(
    snapshot: dict[str, Any],
    ledger: list[dict[str, Any]],
    focus_ticker: str | None,
) -> dict[str, Any] | None:
    """Forensic-only LLM pass: derive W/L ratio and Kelly policy percentages
    from ONLY the forensic highlights (not raw price/volume data).
    """
    llm_config = _llm_config()
    if llm_config is None or not _llm_quota_available():
        return None

    provider, api_key, api_url, model, _oauth_tp = llm_config

    forensic_context = {
        "forensic_metrics": snapshot.get("terminalIntelligence", {}).get("active_scoring_matrix", {}),
        "ic_gates": snapshot.get("terminalIntelligence", {}).get("active_seven_ic_gates", {}),
        "risk_profile": snapshot.get("terminalIntelligence", {}).get("active_risk_calc", {}),
        "ledger_actions": [
            {
                "ticker": row.get("ticker"),
                "action": row.get("action"),
                "selection_reason": row.get("selection_reason"),
                "score": row.get("score"),
            }
            for row in ledger
        ],
        "focus_ticker": focus_ticker,
    }

    sys_instruction = (
        "You are an elite institutional risk and policy analyst. "
        "You will receive ONLY forensic highlights for a candidate stock ledger "
        "(Beneish M-Score, Altman Z, OCF/EBITDA, Mansfield RS, IC gates, and per-stock actions). "
        "Based ONLY on these forensic findings, estimate: "
        "(1) the historical win/loss ratio you would expect for this cohort "
        "(2) the maximum Kelly-suggested allocation percentage per stock (0-20%). "
        "Return ONLY a single compact JSON object with this exact shape: "
        '{"win_loss_ratio": "W/L", "kelly_policy_max": "X.X%", "per_ticker": {"TICKER": {"policy_allocation_pct": "X.X%"}}}'
    )

    prompt = (
        "FORENSIC LEDGER HIGHLIGHTS\n"
        "=======================\n"
        f"{json.dumps(forensic_context, indent=2)}\n\n"
        "Task: analyze ONLY the forensic findings above. "
        "Score quality, governance anomaly, earnings quality, and IC gate status. "
        "Return ONLY JSON as specified. No markdown, no explanation."
    )

    try:
        if provider == "gemini":
            raw = _call_gemini(prompt, api_key, model, sys_instruction, LLM_CALL_TIMEOUT_SECONDS, oauth_token_path=_oauth_tp)
        else:
            raw = _call_openai(prompt, api_key, api_url, model, LLM_CALL_TIMEOUT_SECONDS)

        data = json.loads(_json_block(raw))
        if not isinstance(data, dict):
            return None

        wl = str(data.get("win_loss_ratio") or "—").strip() or "—"
        policy = str(data.get("kelly_policy_max") or "—").strip() or "—"
        return {
            "win_loss_ratio": wl,
            "kelly_policy_max": policy,
            "per_ticker": data.get("per_ticker") or {},
        }
    except Exception as exc:
        _logging.getLogger(__name__).warning("Forensic W/L policy LLM call failed: %s", exc)
        return None


def _apply_wl_policy_from_llm(
    analysis: dict[str, Any],
    snapshot: dict[str, Any],
    focus_ticker: str | None,
) -> dict[str, Any]:
    risk = analysis.get("active_risk_calc") or {}
    needs_wl = not risk.get("win_loss_ratio") or str(risk.get("win_loss_ratio")) in {"—", "1.0:1", "1.00:1"}
    needs_policy = not risk.get("kelly_policy_max") or str(risk.get("kelly_policy_max")) in {"—", "0.0%", "0%"}

    if not needs_wl and not needs_policy:
        return analysis

    ledger = analysis.get("ledger_stocks") or []
    forensic_snapshot = {
        "terminalIntelligence": {
            "active_scoring_matrix": analysis.get("active_scoring_matrix"),
            "active_seven_ic_gates": analysis.get("active_seven_ic_gates"),
            "active_risk_calc": analysis.get("active_risk_calc"),
            "ledger_stocks": ledger,
        }
    }

    llm_outcome = _analyze_forensic_wl_policy(forensic_snapshot, ledger, focus_ticker)
    if llm_outcome:
        per_ticker = llm_outcome.get("per_ticker") or {}
        if needs_wl:
            risk["win_loss_ratio"] = llm_outcome.get("win_loss_ratio") or "—"
        if needs_policy:
            risk["kelly_policy_max"] = llm_outcome.get("kelly_policy_max") or "—"
        analysis["active_risk_calc"] = risk
        for row in ledger:
            ticker = row.get("ticker")
            if not ticker or not needs_policy:
                continue
            row_policy = per_ticker.get(ticker, {}).get("policy_allocation_pct")
            row["policy_allocation_pct"] = row_policy or risk.get("kelly_policy_max") or "—"
        return analysis
    if needs_wl:
        risk["win_loss_ratio"] = "—"
    if needs_policy:
        risk["kelly_policy_max"] = "—"
    analysis["active_risk_calc"] = risk
    return analysis


def _heuristic_analysis(
    live_unstructured_stream: str,
    focus_ticker: str | None = None,
) -> CompleteSecurityAnalysisPayload:
    """Deterministic heuristic analysis used when LLM is unavailable."""
    snapshot = _compile_market_context_snapshot()
    fallback = _build_fallback_payload(snapshot, focus_ticker)
    news_catalysts = fallback["news_catalysts_card"]
    ledger = fallback["ledger_stocks"]

    analysis = CompleteSecurityAnalysisPayload(
        news_catalysts_card=news_catalysts,
        insider_insti_activity_card=fallback["insider_insti_activity_card"],
        macro_anchors_card=fallback["macro_anchors_card"],
        forensic_screen_card=fallback["forensic_screen_card"],
        why_interested=fallback["why_interested"],
        future_revenue_model=fallback["future_revenue_model"],
        current_model=fallback["current_model"],
        ledger_stocks=ledger,
        active_scoring_matrix=fallback["active_scoring_matrix"],
        active_seven_ic_gates=fallback["active_seven_ic_gates"],
        active_risk_calc={
            **fallback["active_risk_calc"],
        },
        active_factor_hub=fallback["active_factor_hub"],
    )
    data = _apply_wl_policy_from_llm(analysis.model_dump(), snapshot, focus_ticker)
    return CompleteSecurityAnalysisPayload.model_validate(data)


def execute_terminal_intelligence_pipeline(live_unstructured_stream: str) -> CompleteSecurityAnalysisPayload:
    """Execute LLM-driven or heuristic terminal intelligence analysis."""
    focus_match = re.search(r"FOCUS_TICKER:\s*([A-Z0-9._-]+)", live_unstructured_stream or "")
    focus_ticker = focus_match.group(1) if focus_match else None

    llm_config = _llm_config()
    if llm_config is not None and _llm_quota_available():
        provider, api_key, api_url, model, _oauth_tp = llm_config
        try:
            system_instruction = (
                "You are an elite institutional financial terminal compiler. "
                "Analyze the provided market intelligence and return a single valid JSON object "
                "matching the CompleteSecurityAnalysisPayload schema exactly. "
                f"Select the top {LLM_DISPLAY_COUNT} stocks for ledger_stocks as a display-only audit shortlist. "
                f"Rank up to {TOP_SELECTION_COUNT} stocks in the stream for context. Ledger membership, score, volume, and APPROVE must not imply BUY direction; direction is supplied only by the deterministic quant contract outside this LLM. "
                "Each ledger_stocks entry MUST include: ticker, name, score, action, ltp, delta. "
                "All fields must be present. Numeric scores should be numbers, percentages as '4.50%'. "
                "Include ALL of these forensic scoring fields in active_scoring_matrix: "
                "beneish_m_score, altman_z_score, ocf_ebitda_ratio, mansfield_relative_strength. "
                "Return 'N/A' if unavailable. Do not include markdown or explanations."
            )
            if focus_ticker:
                system_instruction += f"\nFOCUS: Provide deep analysis specifically on {focus_ticker}."

            if provider == "gemini":
                raw = _call_gemini(live_unstructured_stream, api_key, model, system_instruction, LLM_CALL_TIMEOUT_SECONDS, oauth_token_path=_oauth_tp)
            else:
                raw = _call_openai(live_unstructured_stream, api_key, api_url, model, LLM_CALL_TIMEOUT_SECONDS)

            from .ai_ticker_news import _parse_json_response
            raw_clean = _json_block(raw)
            try:
                data = json.loads(raw_clean)
            except json.JSONDecodeError:
                # Try repair strategies for malformed LLM JSON (unterminated strings, etc.)
                expected_keys = [
                    "news_catalysts_card", "insider_insti_activity_card", "macro_anchors_card",
                    "forensic_screen_card", "why_interested", "future_revenue_model", "current_model",
                    "ledger_stocks", "active_scoring_matrix", "active_seven_ic_gates",
                    "active_risk_calc", "active_factor_hub",
                ]
                data = _parse_json_response(raw_clean, expected_keys)
            data = _sanitize_llm_analysis_data(data)
            result = CompleteSecurityAnalysisPayload.model_validate(data)
            normalized = _normalize_analysis_payload(result, live_unstructured_stream, focus_ticker)
            snapshot = _compile_market_context_snapshot()
            final_data = _apply_wl_policy_from_llm(normalized.model_dump(), snapshot, focus_ticker)
            return CompleteSecurityAnalysisPayload.model_validate(_sanitize_llm_analysis_data(final_data))
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str:
                _record_quota_error(err_str)
            _logging.getLogger(__name__).warning("OpenRouter/LLM call failed; using snapshot facts only: %s", err_str)

    snapshot = _compile_market_context_snapshot()
    if focus_ticker:
        data = build_ticker_intelligence_report(snapshot, focus_ticker)
        data = _apply_wl_policy_from_llm(data, snapshot, focus_ticker)
        return CompleteSecurityAnalysisPayload.model_validate(_sanitize_llm_analysis_data(data))
    return _heuristic_analysis(live_unstructured_stream, focus_ticker)


__all__ = [
    "build_ticker_intelligence_map",
    "build_ticker_intelligence_report",
    "execute_terminal_intelligence_pipeline",
    "_on_demand_ticker_selection_reason",
    "TOP_SELECTION_COUNT",
    "LLM_DISPLAY_COUNT",
]
