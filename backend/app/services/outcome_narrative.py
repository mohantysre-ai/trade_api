"""LLM outcome narratives for EOD Book — grounded only in diagnostic FactPacks."""
from __future__ import annotations

import hashlib
import json
import logging
import re
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
    "Write 2–4 sentences explaining why the trade hit or missed using ONLY CanonicalMetrics "
    "and secondary forensic context in the FactPack. "
    "If you cite R-multiple, P&L, MAE%, or MFE%, the number MUST match CanonicalMetrics exactly. "
    "Never invent MAE/MFE when those keys are absent. Never invent a second R-multiple. "
    "If data is thin, say so. Return JSON: {\"outcomeNarrative\":\"...\"}."
)

_R_MENTION_RE = re.compile(
    r"(?:"
    r"([+-]?\d+(?:\.\d+)?)\s*R\b"  # 0.84R / -1.00R
    r"|"
    r"[Rr](?:-|\s)?multiple(?:\s+of)?\s+([+-]?\d+(?:\.\d+)?)"  # R-multiple of 0.34
    r"|"
    r"\bR\s*[:=]\s*([+-]?\d+(?:\.\d+)?)"  # R: 0.84 / R = -1
    r")",
)


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def canonical_r_multiple(row: dict[str, Any], diagnostic: dict[str, Any] | None = None) -> float | None:
    """Book economic R is source of truth. Never use `or` (0.0 is valid)."""
    for key in ("economicR", "rMultiple"):
        r = _num(row.get(key))
        if r is not None:
            return r
    if isinstance(diagnostic, dict):
        for key in ("economicR", "rMultiple"):
            r = _num(diagnostic.get(key))
            if r is not None:
                return r
    return None


def sync_diagnostic_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """Keep missDiagnostic numeric fields aligned with desk/table row."""
    r = dict(row)
    diag = r.get("missDiagnostic")
    if not isinstance(diag, dict):
        return r
    d = dict(diag)
    r_can = canonical_r_multiple(r, d)
    if r_can is not None:
        d["rMultiple"] = round(r_can, 3)
        d["economicR"] = round(r_can, 3)
    path = _num(r.get("pathR"))
    if path is not None:
        d["pathR"] = round(path, 3)
    for src, dst in (
        ("maePct", "maePct"),
        ("mfePct", "mfePct"),
        ("mfeR", "mfeR"),
        ("maeR", "maeR"),
        ("pnlPct", "movePct"),
    ):
        v = _num(r.get(src))
        if v is not None and d.get(dst) is None:
            d[dst] = v
    if r.get("rootCause") and not d.get("rootCause"):
        d["rootCause"] = r.get("rootCause")
    # Prefer desk exit label for outcome desk copy; keep forensic exitReason if present
    if r.get("deskExitLabel") and not d.get("exitReason"):
        d["exitReason"] = r.get("deskExitLabel")
    r["missDiagnostic"] = d
    return r


def _omit_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _fact_pack(row: dict[str, Any], diagnostic: dict[str, Any]) -> dict[str, Any]:
    r_can = canonical_r_multiple(row, diagnostic)
    path = _num(row.get("pathR"))
    if path is None:
        path = _num(diagnostic.get("pathR"))
    mae = _num(diagnostic.get("maePct"))
    if mae is None:
        mae = _num(row.get("maePct"))
    mfe_pct = _num(diagnostic.get("mfePct"))
    if mfe_pct is None:
        mfe_pct = _num(row.get("mfePct"))
    mfe_r = _num(row.get("mfeR"))

    canonical = _omit_none(
        {
            "economicR": r_can,
            "rMultiple": r_can,  # alias — cite economic Book R only
            "pathR": path,
            "pnl": _num(row.get("pnl")),
            "pnlPct": _num(row.get("pnlPct")),
            "mfeR": mfe_r,
            "maeR": _num(row.get("maeR")),
            "maePct": mae,
            "mfePct": mfe_pct,
            "deskProgress": row.get("deskProgress") or row.get("scaleProgress"),
            "executionStatus": row.get("executionStatus"),
            "outcomeBucket": row.get("outcomeBucket"),
            "deskExitLabel": row.get("deskExitLabel") or diagnostic.get("exitReason") or row.get("exitReason"),
            "rootCause": diagnostic.get("rootCause") or row.get("rootCause"),
        }
    )

    forensic = _omit_none(
        {
            "isMiss": diagnostic.get("isMiss"),
            "isHit": diagnostic.get("isHit"),
            "rootCause": diagnostic.get("rootCause"),
            "factors": diagnostic.get("factors"),
            "movePct": _num(diagnostic.get("movePct")),
            "gapToT1Pct": _num(diagnostic.get("gapToT1Pct")),
            "gapToT2Pct": _num(diagnostic.get("gapToT2Pct")),
            "stopUtilization": _num(diagnostic.get("stopUtilization")),
            "pathR": path,
            "source": diagnostic.get("source"),
            # Intentionally omit forensic rMultiple — CanonicalMetrics.economicR is sole Book R.
        }
    )

    return _omit_none(
        {
            "symbol": row.get("symbol"),
            "direction": row.get("direction"),
            "book": row.get("book") or ("SWING" if row.get("daysHeld") is not None else "INTRADAY"),
            "CanonicalMetrics": canonical,
            "entryPrice": _num(row.get("entryPrice")),
            "exitPrice": _num(row.get("exitPrice") or row.get("currentPrice")),
            "stopLoss": _num(row.get("stopLoss")),
            "target1": _num(row.get("target1")),
            "target2": _num(row.get("target2")),
            "selectionReason": row.get("selectionReason"),
            "score": row.get("score"),
            "forensic": forensic or None,
            "policyChain": row.get("policyChain"),
        }
    )


def metrics_fingerprint(row: dict[str, Any], diagnostic: dict[str, Any] | None = None) -> str:
    diag = diagnostic if isinstance(diagnostic, dict) else {}
    pack = _fact_pack(row, diag).get("CanonicalMetrics") or {}
    payload = json.dumps(pack, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def narrative_r_consistent(text: str, r_canonical: float | None, *, tol: float = 0.05) -> bool:
    """Reject narratives that cite an R-multiple far from the table value."""
    if r_canonical is None:
        return True
    mentions: list[float] = []
    for m in _R_MENTION_RE.finditer(text or ""):
        for g in m.groups():
            if g is not None:
                try:
                    mentions.append(float(g))
                except ValueError:
                    pass
    if not mentions:
        return True
    return all(abs(m - float(r_canonical)) <= tol for m in mentions)


def _call_outcome_llm(fact_pack: dict[str, Any]) -> str | None:
    if not _llm_quota_available():
        return None
    config = _llm_config()
    provider, api_key, api_url, model, oauth_token_path = config or (None, None, None, None, None)
    if not provider or not api_key:
        return None
    prompt = (
        "FactPack (sole evidence). Cite ONLY CanonicalMetrics numbers:\n"
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
    force=True → fill missing / fingerprint-stale narratives unless refresh_existing=True
    (refresh_existing regenerates even when fingerprint matches).
    """
    if not force:
        return [sync_diagnostic_metrics(r) for r in rows]
    out: list[dict[str, Any]] = []
    done = 0
    for row in rows:
        r = sync_diagnostic_metrics(row)
        diag = r.get("missDiagnostic")
        if not isinstance(diag, dict):
            out.append(r)
            continue
        # LLM only for hit/miss FactPacks — skips stay deterministic attribution
        if diag.get("isSkip") and not diag.get("isMiss") and not diag.get("isHit"):
            out.append(r)
            continue
        fp = metrics_fingerprint(r, diag)
        r["narrativeFingerprint"] = fp
        existing = str(r.get("outcomeNarrative") or "").strip() or None
        r_can = canonical_r_multiple(r, diag)
        stored = r.get("narrativeFingerprintStored")
        consistent = bool(existing) and narrative_r_consistent(existing, r_can)
        stale = bool(existing) and (
            (stored is not None and stored != fp) or not consistent
        )
        if existing and consistent and not refresh_existing and not stale:
            r["narrativeFingerprintStored"] = fp
            out.append(r)
            continue
        if done >= max_rows:
            out.append(r)
            continue
        pack = _fact_pack(r, diag)
        narrative = _call_outcome_llm(pack)
        if narrative and not narrative_r_consistent(narrative, r_can):
            log.warning(
                "Dropping inconsistent outcome narrative for %s (canonical R=%s): %s",
                r.get("symbol"),
                r_can,
                narrative[:160],
            )
            narrative = None
        if narrative:
            r["outcomeNarrative"] = narrative
            r["narrativeFingerprintStored"] = fp
            done += 1
        elif stale or refresh_existing:
            # Drop stale mismatched prose rather than keep lying numbers
            r.pop("outcomeNarrative", None)
            r.pop("narrativeFingerprintStored", None)
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
        synced = sync_diagnostic_metrics(row)
        diag = synced.get("missDiagnostic")
        if isinstance(diag, dict):
            packs.append(_fact_pack(synced, diag))
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
        "Ground only in CanonicalMetrics + forensic rootCause/factors. "
        "Cite R only from CanonicalMetrics.rMultiple. No invented metrics."
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
