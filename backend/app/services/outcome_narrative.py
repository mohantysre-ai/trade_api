"""LLM outcome narratives for EOD Book — grounded only in diagnostic FactPacks."""
from __future__ import annotations

import json
import logging
from typing import Any

from .llm_client import (
    LLM_CALL_TIMEOUT_SECONDS,
    _call_gemini,
    _call_openai,
    _llm_config,
    _llm_quota_available,
    _record_quota_error,
)

log = logging.getLogger(__name__)

_OUTCOME_SYSTEM = (
    "You are an IB desk risk reviewer for NSE equity day books. "
    "Write 2–4 sentences explaining why the trade hit or missed using ONLY the FactPack numbers "
    "(prices, R-multiple, MAE/MFE, factors, rootCause). "
    "Never invent metrics, news, or catalysts not in the FactPack. "
    "If data is thin, say so. Return JSON: {\"outcomeNarrative\":\"...\"}."
)


def _fact_pack(row: dict[str, Any], diagnostic: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "direction": row.get("direction"),
        "book": row.get("book") or ("SWING" if row.get("daysHeld") is not None else "INTRADAY"),
        "status": row.get("status") or row.get("exitReason"),
        "entryPrice": row.get("entryPrice"),
        "exitPrice": row.get("exitPrice") or row.get("currentPrice"),
        "stopLoss": row.get("stopLoss"),
        "target1": row.get("target1"),
        "target2": row.get("target2"),
        "pnl": row.get("pnl"),
        "pnlPct": row.get("pnlPct"),
        "selectionReason": row.get("selectionReason"),
        "score": row.get("score"),
        "diagnostic": {
            "isMiss": diagnostic.get("isMiss"),
            "isHit": diagnostic.get("isHit"),
            "exitReason": diagnostic.get("exitReason"),
            "rootCause": diagnostic.get("rootCause"),
            "factors": diagnostic.get("factors"),
            "rMultiple": diagnostic.get("rMultiple"),
            "movePct": diagnostic.get("movePct"),
            "maePct": diagnostic.get("maePct"),
            "mfePct": diagnostic.get("mfePct"),
            "gapToT1Pct": diagnostic.get("gapToT1Pct"),
            "gapToT2Pct": diagnostic.get("gapToT2Pct"),
            "stopUtilization": diagnostic.get("stopUtilization"),
            "source": diagnostic.get("source"),
        },
    }


def _call_outcome_llm(fact_pack: dict[str, Any]) -> str | None:
    if not _llm_quota_available():
        return None
    config = _llm_config()
    provider, api_key, api_url, model, oauth_token_path = config or (None, None, None, None, None)
    if not provider or not api_key:
        return None
    prompt = (
        "FactPack (sole evidence):\n"
        f"{json.dumps(fact_pack, indent=2, default=str)}\n\n"
        'Return JSON: {"outcomeNarrative":"2-4 sentences"}'
    )
    try:
        if provider == "gemini":
            text = _call_gemini(
                prompt=prompt,
                api_key=api_key,
                model=model,
                system_instruction=_OUTCOME_SYSTEM,
                timeout=LLM_CALL_TIMEOUT_SECONDS,
                oauth_token_path=oauth_token_path,
            )
        elif provider == "openai" and api_url:
            text = _call_openai(
                f"{_OUTCOME_SYSTEM}\n\n{prompt}",
                api_key,
                api_url,
                model,
            )
        else:
            return None
        from .ai_ticker_news import _parse_json_response

        parsed = _parse_json_response(text.strip(), ["outcomeNarrative"])
        if not isinstance(parsed, dict):
            return None
        narrative = str(parsed.get("outcomeNarrative") or "").strip()
        return narrative or None
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "quota" in msg or "resource exhausted" in msg:
            _record_quota_error(str(exc))
        log.warning("Outcome narrative LLM failed for %s: %s", fact_pack.get("symbol"), exc)
        return None


def attach_outcome_narratives(
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
    refresh_existing: bool = False,
    max_rows: int = 24,
) -> list[dict[str, Any]]:
    """Attach outcomeNarrative from diagnostic FactPack.

    force=False → skip LLM (keep rebuild snappy).
    force=True → fill missing narratives only unless refresh_existing=True.
    """
    if not force:
        return rows
    out: list[dict[str, Any]] = []
    done = 0
    for row in rows:
        r = dict(row)
        diag = r.get("missDiagnostic")
        if not isinstance(diag, dict):
            out.append(r)
            continue
        # LLM only for hit/miss FactPacks — skips stay deterministic attribution
        if diag.get("isSkip") and not diag.get("isMiss") and not diag.get("isHit"):
            out.append(r)
            continue
        if r.get("outcomeNarrative") and not refresh_existing:
            out.append(r)
            continue
        if done >= max_rows:
            out.append(r)
            continue
        narrative = _call_outcome_llm(_fact_pack(r, diag))
        if narrative:
            r["outcomeNarrative"] = narrative
            done += 1
        out.append(r)
    return out


def build_day_lessons(
    rows: list[dict[str, Any]],
    *,
    force: bool = False,
    refresh_existing: bool = False,
    existing: list[str] | None = None,
    max_bullets: int = 5,
) -> list[str]:
    """Day-level lessons from aggregated diagnostics — LLM only on force rebuild."""
    if not force:
        return list(existing or [])[:max_bullets]
    if existing and not refresh_existing:
        return list(existing)[:max_bullets]
    packs = []
    for row in rows:
        diag = row.get("missDiagnostic")
        if isinstance(diag, dict):
            packs.append(_fact_pack(row, diag))
    if not packs:
        return []
    if not _llm_quota_available():
        return []
    config = _llm_config()
    provider, api_key, api_url, model, oauth_token_path = config or (None, None, None, None, None)
    if not provider or not api_key:
        return []
    prompt = (
        f"Aggregated trade FactPacks ({len(packs)}):\n"
        f"{json.dumps(packs[:20], indent=2, default=str)}\n\n"
        f'Return JSON: {{"lessons":["bullet",...]}} with at most {max_bullets} bullets. '
        "Ground only in FactPack rootCause/factors/R. No invented metrics."
    )
    system = (
        "You are a desk post-mortem coach. Emit concise actionable lessons only from provided facts."
    )
    try:
        if provider == "gemini":
            text = _call_gemini(
                prompt=prompt,
                api_key=api_key,
                model=model,
                system_instruction=system,
                timeout=LLM_CALL_TIMEOUT_SECONDS,
                oauth_token_path=oauth_token_path,
            )
        elif provider == "openai" and api_url:
            text = _call_openai(f"{system}\n\n{prompt}", api_key, api_url, model)
        else:
            return []
        from .ai_ticker_news import _parse_json_response

        parsed = _parse_json_response(text.strip(), ["lessons"])
        lessons = (parsed or {}).get("lessons") if isinstance(parsed, dict) else None
        if not isinstance(lessons, list):
            return []
        return [str(x).strip() for x in lessons if str(x).strip()][:max_bullets]
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "quota" in msg or "resource exhausted" in msg:
            _record_quota_error(str(exc))
        log.warning("Day lessons LLM failed: %s", exc)
        return []
