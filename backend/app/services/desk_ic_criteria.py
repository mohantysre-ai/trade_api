"""Desk IC criteria — senior IB / large-portfolio PM checklist.

Fact-grounded only: never invent metrics. Deterministic hard rows
(price floor, DVR/denylist) always overwrite LLM output.
Soft gate: REJECT flags UI; does not empty the book on LLM outage.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any

from .feed_scanner import SWING_MIN_PRICE, is_swing_desk_eligible
from .llm_client import (
    LLM_CALL_TIMEOUT_SECONDS,
    _call_gemini,
    _call_openai,
    _llm_config,
    _llm_quota_available,
    _record_quota_error,
)
from .stock_quality import MIN_PROMOTER_HOLDING_PCT, MIN_TURNOVER_CR, is_risky_symbol

log = logging.getLogger(__name__)

_MISSING_SECTOR = frozenset({"", "NA", "N/A", "OTHER", "NONE"})


def _resolve_sector(ticker: str, row: dict[str, Any]) -> str | None:
    for key in ("sector", "industry"):
        raw = row.get(key)
        if isinstance(raw, str) and raw.strip():
            val = raw.strip().upper()
            if val not in _MISSING_SECTOR:
                return val
    if not ticker:
        return None
    from .intraday_session_engine import _sector_of

    hinted = str(_sector_of(ticker, row) or "").strip().upper()
    if hinted and hinted not in _MISSING_SECTOR:
        return hinted
    return None


_CANDLE_SOURCES = frozenset({"candles", "daily_candles"})
_INTRADAY_STUB_REASON = 'not in intraday candidate set'

AI_CACHE_TTL_SECONDS = int(os.getenv("AI_CACHE_TTL_SECONDS", "900"))
DESK_IC_LLM_TIMEOUT_SECONDS = int(os.getenv("DESK_IC_LLM_TIMEOUT_SECONDS", "20"))

CRITERION_DEFS: list[dict[str, str]] = [
    {"id": "price_floor", "label": "Price floor"},
    {"id": "instrument_quality", "label": "Instrument quality"},
    {"id": "liquidity_turnover", "label": "Liquidity / turnover"},
    {"id": "technical_alignment", "label": "Technical alignment"},
    {"id": "governance_promoter", "label": "Governance / promoter"},
    {"id": "news_event_risk", "label": "News / event risk"},
    {"id": "portfolio_fit", "label": "Portfolio fit"},
]

BLOCKING_CRITERION_IDS = frozenset(
    {"price_floor", "instrument_quality", "liquidity_turnover", "governance_promoter", "news_event_risk"}
)

DESK_IC_SYSTEM_PROMPT = """
You are a senior investment banking / sell-side analyst and large-portfolio PM
with 20+ years managing institutional books (fat AUM, capital preservation first).

You are NOT a retail tipster. You do NOT invent prices, ratios, or news.

Rules:
1. Use ONLY the FactPack JSON provided. No external knowledge.
2. For each criterion return status PASS | FAIL | INSUFFICIENT.
3. INSUFFICIENT when the FactPack lacks the needed field — never guess PASS.
4. If FactPack.penny_or_dvr is true OR ltp < min_price → price_floor and/or
   instrument_quality MUST be FAIL (already pre-scored; reinforce in narrative).
5. REJECT if any blocking criterion FAIL: price_floor, instrument_quality,
   liquidity_turnover, governance_promoter, or news_event_risk.
6. HOLD_FOR_DATA if ≥2 core criteria are INSUFFICIENT and no hard FAIL.
7. Otherwise APPROVE. conviction = round(100 * PASS_count / 7), integer 0-100.
8. categoryScores are calculated by Python from criteria; do not invent them.
9. oneLiner: one terse desk sentence. Cite sourceFields on every criterion.
10. Return JSON only matching the schema. No markdown.
""".strip()


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, str):
        v = (
            v.replace("₹", "")
            .replace(",", "")
            .replace("%", "")
            .replace("Cr", "")
            .replace("cr", "")
            .strip()
        )
        if not v or v in {"—", "-", "N/A", "n/a", "NA", "None"}:
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _criterion(
    cid: str,
    status: str,
    detail: str,
    source_fields: list[str],
) -> dict[str, Any]:
    label = next((d["label"] for d in CRITERION_DEFS if d["id"] == cid), cid)
    return {
        "id": cid,
        "label": label,
        "status": status,
        "detail": detail,
        "sourceFields": source_fields,
    }


def build_fact_pack(
    ticker: str,
    stock: dict[str, Any] | None,
    *,
    ticker_news: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble snapshot-only facts for Desk IC (no invented fields)."""
    row = stock if isinstance(stock, dict) else {}
    sym = str(ticker or row.get("ticker") or "").upper().strip()
    intraday = row.get("intraday") if isinstance(row.get("intraday"), dict) else {}
    ltp = _f(
        row.get("ltpRaw")
        or row.get("lastPrice")
        or row.get("ltp")
        or row.get("Ltp")
        or row.get("entryPrice")
        or row.get("scanLtp")
        or row.get("close")
    )
    turnover = _f(
        row.get("turnoverCr")
        or row.get("turnover_cr")
        or intraday.get("turnover_cr")
        or intraday.get("turnoverCr")
    )
    volume = _f(row.get("volume") or row.get("Volume") or intraday.get("volume"))
    vol_mult = _f(row.get("volume_multiplier") or intraday.get("volume_multiplier"))
    rsi = _f(row.get("rsi") or row.get("RSI") or intraday.get("rsi"))
    atr_pct = _f(row.get("atr_pct") or intraday.get("atr_pct") or row.get("atrPct"))
    promoter = _f(
        row.get("promoter_holding_pct")
        or row.get("promoterHoldingPct")
        or intraday.get("promoter_holding_pct")
    )
    passes_hard = row.get("passes_hard_filters")
    if passes_hard is None:
        passes_hard = intraday.get("passes_hard_filters")
    passes_quality = row.get("passes_quality_filters")
    if passes_quality is None:
        passes_quality = intraday.get("passes_quality_filters")
    risk_flags = row.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = [str(risk_flags)]
    verdict = str(row.get("verdict") or "").upper() or None

    news = ticker_news if isinstance(ticker_news, dict) else {}
    news_sentiment = news.get("sentiment_overall")
    news_risk = news.get("risk_flags")
    news_headline = news.get("summary_headline")

    penny_or_dvr = False
    if sym:
        if sym.endswith("DVR") or is_risky_symbol(sym):
            penny_or_dvr = True
        if ltp is not None and not is_swing_desk_eligible(sym, ltp):
            penny_or_dvr = True

    return {
        "ticker": sym,
        "name": row.get("name") or sym,
        "ltp": ltp,
        "min_price": SWING_MIN_PRICE,
        "penny_or_dvr": penny_or_dvr,
        "on_risky_denylist": is_risky_symbol(sym) if sym else False,
        "is_dvr": bool(sym.endswith("DVR")) if sym else False,
        "turnover_cr": turnover,
        "min_turnover_cr": MIN_TURNOVER_CR,
        "volume": volume,
        "volume_multiplier": vol_mult,
        "rsi": rsi,
        "atr_pct": atr_pct,
        "promoter_holding_pct": promoter,
        "min_promoter_holding_pct": MIN_PROMOTER_HOLDING_PCT,
        "passes_hard_filters": passes_hard if isinstance(passes_hard, bool) else None,
        "passes_quality_filters": passes_quality if isinstance(passes_quality, bool) else None,
        "alpha_score": _f(row.get("alpha_score") or row.get("score")),
        "verdict": verdict,
        "risk_flags": [str(x) for x in risk_flags if x and str(x) != "None"][:8],
        "news_sentiment": news_sentiment,
        "news_risk_flags": news_risk,
        "news_headline": news_headline,
        "sector": _resolve_sector(sym, row),
    }


def deterministic_hard_criteria(fact_pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Python-owned hard rows — LLM cannot override PASS on these when FAIL."""
    out: dict[str, dict[str, Any]] = {}
    ltp = _f(fact_pack.get("ltp"))
    min_price = _f(fact_pack.get("min_price")) or SWING_MIN_PRICE
    sym = str(fact_pack.get("ticker") or "")

    if ltp is None:
        out["price_floor"] = _criterion(
            "price_floor",
            "INSUFFICIENT",
            "LTP missing from snapshot — cannot verify institutional price floor.",
            ["ltp"],
        )
    elif ltp < min_price:
        out["price_floor"] = _criterion(
            "price_floor",
            "FAIL",
            f"LTP {ltp:.2f} below desk floor {min_price:.0f} — not institutional size.",
            ["ltp", "min_price"],
        )
    else:
        out["price_floor"] = _criterion(
            "price_floor",
            "PASS",
            f"LTP {ltp:.2f} meets desk floor {min_price:.0f}.",
            ["ltp", "min_price"],
        )

    if not sym:
        out["instrument_quality"] = _criterion(
            "instrument_quality",
            "INSUFFICIENT",
            "Symbol missing.",
            ["ticker"],
        )
    elif fact_pack.get("is_dvr"):
        out["instrument_quality"] = _criterion(
            "instrument_quality",
            "FAIL",
            f"{sym} is a DVR — rejected for institutional book.",
            ["ticker"],
        )
    elif fact_pack.get("on_risky_denylist"):
        out["instrument_quality"] = _criterion(
            "instrument_quality",
            "FAIL",
            f"{sym} is on the risky denylist.",
            ["ticker"],
        )
    else:
        out["instrument_quality"] = _criterion(
            "instrument_quality",
            "PASS",
            f"{sym} clears DVR / denylist screen.",
            ["ticker"],
        )

    return out


def _deterministic_soft_hints(fact_pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Fallback criteria when LLM unavailable — still fact-grounded, no invention."""
    hints: dict[str, dict[str, Any]] = {}
    turnover = _f(fact_pack.get("turnover_cr"))
    min_to = _f(fact_pack.get("min_turnover_cr")) or MIN_TURNOVER_CR
    if turnover is None:
        hints["liquidity_turnover"] = _criterion(
            "liquidity_turnover",
            "INSUFFICIENT",
            "Turnover Cr not in FactPack.",
            ["turnover_cr"],
        )
    elif turnover < min_to:
        hints["liquidity_turnover"] = _criterion(
            "liquidity_turnover",
            "FAIL",
            f"Turnover {turnover:.1f} Cr below desk {min_to:.0f} Cr.",
            ["turnover_cr", "min_turnover_cr"],
        )
    else:
        hints["liquidity_turnover"] = _criterion(
            "liquidity_turnover",
            "PASS",
            f"Turnover {turnover:.1f} Cr meets {min_to:.0f} Cr floor.",
            ["turnover_cr", "min_turnover_cr"],
        )

    ph = fact_pack.get("passes_hard_filters")
    pq = fact_pack.get("passes_quality_filters")
    rsi = _f(fact_pack.get("rsi"))
    if ph is None and pq is None:
        hints["technical_alignment"] = _criterion(
            "technical_alignment",
            "INSUFFICIENT",
            f"Quant hard/quality status unavailable{f'; RSI={rsi:.1f} alone cannot establish alignment' if rsi is not None else ''}.",
            ["passes_hard_filters", "passes_quality_filters", "rsi"],
        )
    elif ph is False or pq is False:
        hints["technical_alignment"] = _criterion(
            "technical_alignment",
            "FAIL",
            "Quant hard/quality filters marked fail.",
            ["passes_hard_filters", "passes_quality_filters"],
        )
    else:
        detail_parts = []
        src = []
        if isinstance(ph, bool):
            detail_parts.append(f"hard_filters={'PASS' if ph else 'FAIL'}")
            src.append("passes_hard_filters")
        if isinstance(pq, bool):
            detail_parts.append(f"quality={'PASS' if pq else 'FAIL'}")
            src.append("passes_quality_filters")
        if rsi is not None:
            detail_parts.append(f"RSI={rsi:.1f}")
            src.append("rsi")
        hints["technical_alignment"] = _criterion(
            "technical_alignment",
            "PASS" if ph is not False and pq is not False else "FAIL",
            "; ".join(detail_parts) or "Technical fields present.",
            src or ["passes_hard_filters"],
        )

    promoter = _f(fact_pack.get("promoter_holding_pct"))
    min_p = _f(fact_pack.get("min_promoter_holding_pct")) or MIN_PROMOTER_HOLDING_PCT
    if promoter is None:
        hints["governance_promoter"] = _criterion(
            "governance_promoter",
            "INSUFFICIENT",
            "Promoter holding % not in FactPack.",
            ["promoter_holding_pct"],
        )
    elif promoter < min_p:
        hints["governance_promoter"] = _criterion(
            "governance_promoter",
            "FAIL",
            f"Promoter {promoter:.1f}% below desk {min_p:.0f}%.",
            ["promoter_holding_pct", "min_promoter_holding_pct"],
        )
    else:
        hints["governance_promoter"] = _criterion(
            "governance_promoter",
            "PASS",
            f"Promoter {promoter:.1f}% meets {min_p:.0f}% floor.",
            ["promoter_holding_pct"],
        )

    flags = list(fact_pack.get("risk_flags") or [])
    news_risk = fact_pack.get("news_risk_flags")
    verdict = str(fact_pack.get("verdict") or "").upper()
    if verdict == "REJECT" or (
        isinstance(news_risk, str) and any(
            k in news_risk.lower()
            for k in ("earnings", "regulatory", "court", "ban", "restriction")
        )
    ):
        hints["news_event_risk"] = _criterion(
            "news_event_risk",
            "FAIL",
            f"Binary/news risk flagged (verdict={verdict or 'n/a'}).",
            ["verdict", "risk_flags", "news_risk_flags"],
        )
    elif not flags and not news_risk and not fact_pack.get("news_headline"):
        hints["news_event_risk"] = _criterion(
            "news_event_risk",
            "INSUFFICIENT",
            "No news / risk_flags in FactPack for event screen.",
            ["risk_flags", "news_risk_flags"],
        )
    else:
        hints["news_event_risk"] = _criterion(
            "news_event_risk",
            "PASS",
            "No hard binary event flag in FactPack.",
            ["risk_flags", "news_sentiment"],
        )

    atr = _f(fact_pack.get("atr_pct"))
    sector = str(fact_pack.get("sector") or "").strip()
    if not sector:
        hints["portfolio_fit"] = _criterion(
            "portfolio_fit",
            "INSUFFICIENT",
            "Sector classification missing — cannot assess sleeve concentration or thematic fit.",
            ["sector"],
        )
    elif atr is None and _f(fact_pack.get("alpha_score")) is None:
        hints["portfolio_fit"] = _criterion(
            "portfolio_fit",
            "INSUFFICIENT",
            "ATR% / alpha_score missing — cannot size fat-book fit.",
            ["atr_pct", "alpha_score"],
        )
    elif atr is not None and (atr < 0.5 or atr > 12):
        hints["portfolio_fit"] = _criterion(
            "portfolio_fit",
            "FAIL",
            f"ATR% {atr:.2f} outside institutional sleeve band.",
            ["atr_pct"],
        )
    else:
        bits = []
        src = []
        if atr is not None:
            bits.append(f"ATR%={atr:.2f}")
            src.append("atr_pct")
        score = _f(fact_pack.get("alpha_score"))
        if score is not None:
            bits.append(f"alpha={score:.1f}")
            src.append("alpha_score")
        bits.insert(0, f"{sector} sleeve")
        src.insert(0, "sector")
        hints["portfolio_fit"] = _criterion(
            "portfolio_fit",
            "PASS",
            "; ".join(bits) or "Fit fields present.",
            src or ["sector"],
        )

    return hints


def _decide_from_criteria(criteria: list[dict[str, Any]]) -> tuple[str, int]:
    by_id = {c["id"]: c for c in criteria}
    hard_fail = any(
        by_id.get(cid, {}).get("status") == "FAIL" for cid in BLOCKING_CRITERION_IDS
    )
    if hard_fail:
        return "REJECT", max(
            0,
            int(100 * sum(1 for c in criteria if c.get("status") == "PASS") / max(len(criteria), 1)),
        )
    insuff = sum(1 for c in criteria if c.get("status") == "INSUFFICIENT")
    if insuff >= 2:
        return "HOLD_FOR_DATA", int(
            100 * sum(1 for c in criteria if c.get("status") == "PASS") / max(len(CRITERION_DEFS), 1)
        )
    passes = sum(1 for c in criteria if c.get("status") == "PASS")
    return "APPROVE", int(100 * passes / max(len(CRITERION_DEFS), 1))


def _category_scores_from_criteria(criteria: list[dict[str, Any]]) -> dict[str, int | None]:
    mapping = {
        "liquidity": ["price_floor", "liquidity_turnover"],
        "technical": ["technical_alignment"],
        "governance": ["instrument_quality", "governance_promoter"],
        "eventRisk": ["news_event_risk"],
        "portfolioFit": ["portfolio_fit"],
    }

    def score_ids(ids: list[str]) -> int | None:
        rows = [c for c in criteria if c.get("id") in ids]
        if not rows:
            return None
        if any(r.get("status") == "INSUFFICIENT" for r in rows):
            return None
        pts = 0
        for r in rows:
            st = r.get("status")
            if st == "PASS":
                pts += 100
            elif st == "FAIL":
                pts += 0
        return int(pts / len(rows))

    return {k: score_ids(v) for k, v in mapping.items()}


def build_deterministic_desk_ic(fact_pack: dict[str, Any], *, llm_used: bool = False) -> dict[str, Any]:
    hard = deterministic_hard_criteria(fact_pack)
    soft = _deterministic_soft_hints(fact_pack)
    merged = {**soft, **hard}
    criteria = [merged[d["id"]] for d in CRITERION_DEFS if d["id"] in merged]
    decision, conviction = _decide_from_criteria(criteria)
    return {
        "ticker": fact_pack.get("ticker"),
        "deskDecision": decision,
        "conviction": conviction,
        "oneLiner": (
            f"Deterministic desk screen: {decision}."
            if not llm_used
            else f"Desk IC (LLM merge): {decision}."
        ),
        "criteria": criteria,
        "categoryScores": _category_scores_from_criteria(criteria),
        "source": "deterministic" if not llm_used else "llm+deterministic",
        "llmUsed": llm_used,
        "generatedAt": _utc_now_iso(),
        "factPack": {
            "ltp": fact_pack.get("ltp"),
            "penny_or_dvr": fact_pack.get("penny_or_dvr"),
            "min_price": fact_pack.get("min_price"),
        },
    }


def _merge_llm_over_hard(
    fact_pack: dict[str, Any],
    llm_payload: dict[str, Any],
) -> dict[str, Any]:
    hard = deterministic_hard_criteria(fact_pack)
    soft_fallback = _deterministic_soft_hints(fact_pack)
    llm_criteria = llm_payload.get("criteria") if isinstance(llm_payload.get("criteria"), list) else []
    by_id: dict[str, dict[str, Any]] = {c["id"]: c for c in soft_fallback.values()}
    by_id.update(hard)
    for raw in llm_criteria:
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or "").strip()
        if cid not in {d["id"] for d in CRITERION_DEFS}:
            continue
        # The LLM may explain a criterion, but it cannot change its deterministic
        # evidence status or source fields. Missing facts remain INSUFFICIENT.
        baseline = by_id.get(cid)
        if baseline is None:
            continue
        detail = str(raw.get("detail") or "").strip()[:400]
        if detail and baseline.get("status") != "INSUFFICIENT":
            baseline = dict(baseline)
            baseline["llmDetail"] = detail
            by_id[cid] = baseline
    criteria = [by_id[d["id"]] for d in CRITERION_DEFS if d["id"] in by_id]
    decision, conviction = _decide_from_criteria(criteria)
    final_decision = decision
    cat_scores = _category_scores_from_criteria(criteria)
    failed = [c["label"] for c in criteria if c.get("status") == "FAIL"]
    missing = [c["label"] for c in criteria if c.get("status") == "INSUFFICIENT"]
    one = f"Evidence-gated Desk IC: {final_decision}."
    if failed:
        one += f" Failed: {', '.join(failed)}."
    if missing:
        one += f" Insufficient: {', '.join(missing)}."

    return {
        "ticker": fact_pack.get("ticker"),
        "deskDecision": final_decision,
        "conviction": conviction,
        "oneLiner": one,
        "criteria": criteria,
        "categoryScores": cat_scores,
        "source": "deterministic-gates+llm-notes",
        "llmUsed": True,
        "generatedAt": _utc_now_iso(),
        "factPack": {
            "ltp": fact_pack.get("ltp"),
            "penny_or_dvr": fact_pack.get("penny_or_dvr"),
            "min_price": fact_pack.get("min_price"),
        },
    }


def _desk_ic_llm_model(default_model: str) -> str:
    return (os.getenv("LLM_DESK_IC_MODEL") or default_model or "").strip() or default_model


def _call_desk_ic_llm_inner(
    fact_pack: dict[str, Any],
    *,
    provider: str,
    api_key: str,
    api_url: str,
    model: str,
    oauth_token_path: str | None,
) -> dict[str, Any] | None:

    schema_hint = {
        "ticker": fact_pack.get("ticker"),
        "deskDecision": "APPROVE|REJECT|HOLD_FOR_DATA",
        "conviction": 0,
        "oneLiner": "string",
        "criteria": [
            {
                "id": d["id"],
                "label": d["label"],
                "status": "PASS|FAIL|INSUFFICIENT",
                "detail": "string",
                "sourceFields": ["field"],
            }
            for d in CRITERION_DEFS
        ],
        "categoryScores": {
            "liquidity": 0,
            "technical": 0,
            "governance": 0,
            "eventRisk": 0,
            "portfolioFit": 0,
        },
    }
    prompt = (
        "FactPack (sole evidence):\n"
        f"{json.dumps(fact_pack, indent=2, default=str)}\n\n"
        "Return JSON exactly shaped like:\n"
        f"{json.dumps(schema_hint, indent=2)}\n"
    )
    try:
        if provider == "gemini":
            text = _call_gemini(
                prompt=prompt,
                api_key=api_key,
                model=model,
                system_instruction=DESK_IC_SYSTEM_PROMPT,
                timeout=LLM_CALL_TIMEOUT_SECONDS,
                oauth_token_path=oauth_token_path,
            )
        elif provider == "openai" and api_url:
            text = _call_openai(
                f"{DESK_IC_SYSTEM_PROMPT}\n\n{prompt}",
                api_key,
                api_url,
                model,
                DESK_IC_LLM_TIMEOUT_SECONDS,
            )
        else:
            return None
        from .ai_ticker_news import _parse_json_response

        parsed = _parse_json_response(text.strip(), ["deskDecision", "criteria"])
        return parsed if isinstance(parsed, dict) else None
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "quota" in msg or "resource exhausted" in msg:
            _record_quota_error(str(exc))
        log.warning("Desk IC LLM failed for %s: %s", fact_pack.get("ticker"), exc)
        return None


def _call_desk_ic_llm(fact_pack: dict[str, Any]) -> dict[str, Any] | None:
    if not _llm_quota_available():
        return None
    config = _llm_config()
    provider, api_key, api_url, model, oauth_token_path = config or (None, None, None, None, None)
    if not provider or not api_key:
        return None
    model = _desk_ic_llm_model(model)
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(
            _call_desk_ic_llm_inner,
            fact_pack,
            provider=provider,
            api_key=api_key,
            api_url=api_url,
            model=model,
            oauth_token_path=oauth_token_path,
        )
        try:
            return fut.result(timeout=DESK_IC_LLM_TIMEOUT_SECONDS + 2)
        except FuturesTimeoutError:
            log.warning(
                "Desk IC LLM timed out for %s after %ss",
                fact_pack.get("ticker"),
                DESK_IC_LLM_TIMEOUT_SECONDS,
            )
            return None


def evaluate_desk_ic(
    ticker: str,
    stock: dict[str, Any] | None,
    *,
    ticker_news: dict[str, Any] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    fact_pack = build_fact_pack(ticker, stock, ticker_news=ticker_news)
    if not use_llm:
        return build_deterministic_desk_ic(fact_pack, llm_used=False)
    llm_payload = _call_desk_ic_llm(fact_pack)
    if not llm_payload:
        return build_deterministic_desk_ic(fact_pack, llm_used=False)
    return _merge_llm_over_hard(fact_pack, llm_payload)


def _cache_fresh(entry: dict[str, Any] | None) -> bool:
    if not isinstance(entry, dict):
        return False
    gen = entry.get("generatedAt")
    if not gen:
        return False
    try:
        ts = datetime.fromisoformat(str(gen).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return False
    return (time.time() - ts) <= AI_CACHE_TTL_SECONDS


def get_cached_desk_ic(
    snapshot: dict[str, Any] | None,
    ticker: str,
    *,
    require_llm: bool = False,
) -> dict[str, Any] | None:
    if not snapshot:
        return None
    block = snapshot.get("deskIcByTicker")
    if not isinstance(block, dict):
        return None
    entry = block.get(str(ticker).upper())
    if not _cache_fresh(entry if isinstance(entry, dict) else None):
        return None
    if require_llm and entry.get("llmUsed") is not True:
        return None
    return entry  # type: ignore[return-value]


def _intraday_source_rank(block: Any) -> int:
    if not isinstance(block, dict) or not block:
        return 0
    reasons = [str(r) for r in (block.get("hard_filter_reasons") or [])]
    if _INTRADAY_STUB_REASON in reasons:
        return 0
    src = str(block.get("data_source") or "")
    if src not in _CANDLE_SOURCES:
        return 0
    if src == "candles":
        return 2
    return 1


def prefer_intraday_blocks(quote_intra: Any, stock_intra: Any) -> dict[str, Any] | None:
    """Keep usable 5m/daily candle metrics; do not let a hunt stub replace them."""
    q = quote_intra if isinstance(quote_intra, dict) else {}
    s = stock_intra if isinstance(stock_intra, dict) else {}
    qn = _intraday_source_rank(q)
    sn = _intraday_source_rank(s)
    if qn >= sn and qn > 0:
        return q
    if sn > 0:
        return s
    if q:
        return q
    return s or None


def resolve_stock_from_snapshot(snapshot: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    sym = ticker.upper().strip()
    merged: dict[str, Any] = {"ticker": sym}
    found = False
    for row in snapshot.get("stocks") or []:
        if isinstance(row, dict) and str(row.get("ticker") or "").upper() == sym:
            merged.update(row)
            found = True
            break
    quotes = snapshot.get("stockQuotes")
    if isinstance(quotes, dict):
        q = quotes.get(sym) or quotes.get(ticker)
        if isinstance(q, dict):
            intra = merged.get("intraday") if isinstance(merged.get("intraday"), dict) else {}
            q_intra = q.get("intraday") if isinstance(q.get("intraday"), dict) else {}
            merged = {**merged, **q}
            preferred = prefer_intraday_blocks(q_intra, intra)
            if preferred:
                merged["intraday"] = preferred
            found = True
    dhan = snapshot.get("dhanSwingPicks")
    if isinstance(dhan, dict):
        for p in dhan.get("picks") or []:
            if isinstance(p, dict) and str(p.get("symbol") or p.get("ticker") or "").upper() == sym:
                merged.setdefault("name", p.get("name") or sym)
                merged.setdefault("ltp", p.get("ltp") or p.get("entry") or p.get("entryPrice") or p.get("scanLtp"))
                merged.setdefault("score", p.get("score"))
                merged.setdefault("sector", p.get("sector"))
                found = True
                break
    return merged if found else None


def evaluate_and_cache_ticker(
    snapshot: dict[str, Any],
    ticker: str,
    *,
    use_llm: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    sym = ticker.upper().strip()
    if not force:
        cached = get_cached_desk_ic(snapshot, sym, require_llm=use_llm)
        if cached:
            return cached
    stock = resolve_stock_from_snapshot(snapshot, sym)
    news_map = snapshot.get("tickerNewsByTicker") if isinstance(snapshot.get("tickerNewsByTicker"), dict) else {}
    news = news_map.get(sym) if isinstance(news_map, dict) else None
    result = evaluate_desk_ic(sym, stock, ticker_news=news if isinstance(news, dict) else None, use_llm=use_llm)
    block = snapshot.get("deskIcByTicker")
    if not isinstance(block, dict):
        block = {}
    existing = block.get(sym)
    if (
        not use_llm
        and isinstance(existing, dict)
        and existing.get("llmUsed") is True
        and _cache_fresh(existing)
    ):
        snapshot["deskIcByTicker"] = block
        return existing
    block[sym] = result
    snapshot["deskIcByTicker"] = block
    # Soft summary on stock row when present in ranked list
    for row in snapshot.get("stocks") or []:
        if isinstance(row, dict) and str(row.get("ticker") or "").upper() == sym:
            row["deskIcSummary"] = {
                "deskDecision": result.get("deskDecision"),
                "conviction": result.get("conviction"),
                "oneLiner": result.get("oneLiner"),
                "source": result.get("source"),
            }
            break
    return result


def batch_desk_ic_for_stocks(
    stocks: list[dict[str, Any]],
    *,
    news_by_ticker: dict[str, Any] | None = None,
    use_llm: bool = True,
    limit: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Run Desk IC on top-N stocks; attach deskIcSummary; return deskIcByTicker map."""
    news_by_ticker = news_by_ticker or {}
    n = limit if limit is not None else len(stocks)
    out: dict[str, dict[str, Any]] = {}
    for row in stocks[:n]:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("ticker") or "").upper().strip()
        if not sym:
            continue
        news = news_by_ticker.get(sym)
        result = evaluate_desk_ic(
            sym,
            row,
            ticker_news=news if isinstance(news, dict) else None,
            use_llm=use_llm,
        )
        out[sym] = result
        row["deskIcSummary"] = {
            "deskDecision": result.get("deskDecision"),
            "conviction": result.get("conviction"),
            "oneLiner": result.get("oneLiner"),
            "source": result.get("source"),
        }
    return out
