"""Post-market-close reconciliation for the day's intraday scanner picks.

Reads the day's archived intraday picks (see eod_archive.py — populated by
the trade_outcome.py patch), reconciles each against T1/T2/SL, computes
realized/unrealized P&L against a fixed capital allocation, and for every
miss (SL hit or no target hit by close) generates an LLM explanation using
the entry setup context already computed by angel_one_feed's scoring
pipeline, via the existing llm_client wrapper.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from .eod_archive import load_archive

log = logging.getLogger(__name__)

MISS_ANALYSIS_SYSTEM_PROMPT = (
    "You are a trading journal assistant. Given one closed intraday equity "
    "trade's setup and outcome, explain concisely why it likely missed its "
    "target or hit stop-loss. Be specific, reference the provided context, "
    "keep it to 3-4 sentences."
)

DEFAULT_INTRADAY_CAPITAL = 1_000_000.0  # ₹10L


def _leg_pnl(pick: dict[str, Any]) -> tuple[str, float, float]:
    """Return (exit_reason, exit_price, pnl) for one intraday pick."""
    direction = pick.get("direction", "LONG")
    entry = float(pick.get("entryPrice") or 0)
    qty = int(pick.get("approxQty") or 0)
    outcome = pick.get("outcome") or {}
    hit_level = outcome.get("hitLevel")
    ltp = float(pick.get("currentPrice") or outcome.get("ltp") or entry)

    if hit_level == "t2":
        exit_price = float(pick.get("target2") or ltp)
        reason = "T2_HIT"
    elif hit_level == "t1":
        exit_price = float(pick.get("target1") or ltp)
        reason = "T1_HIT"
    elif hit_level == "sl":
        exit_price = float(pick.get("stopLoss") or ltp)
        reason = "SL_HIT"
    else:
        exit_price = ltp
        reason = "EOD_SQUAREOFF"

    sign = 1 if direction == "LONG" else -1
    pnl = sign * (exit_price - entry) * qty
    return reason, exit_price, pnl


def _build_miss_prompt(pick: dict[str, Any], reason: str, pnl: float) -> str:
    setup = pick.get("setupSnapshot") or {}
    return f"""You are reviewing one intraday equity trade after market close.

Symbol: {pick.get('symbol')}
Direction: {pick.get('direction')}
Entry: {pick.get('entryPrice')} | Stop-loss: {pick.get('stopLoss')} | T1: {pick.get('target1')} | T2: {pick.get('target2')}
Outcome: {reason} | Exit price: {pick.get('currentPrice')} | P&L: {pnl:.2f}

Entry setup context (if available): {setup or 'not recorded for this pick'}

In 3-4 sentences, explain the most likely reason this trade did not reach
its target (or hit stop-loss), referencing the setup context where relevant.
Be specific and concise — this is a daily trading journal entry, not a report."""


def _get_miss_analysis(pick: dict[str, Any], reason: str, pnl: float) -> str | None:
    """Generate a miss-diagnosis using the same provider-dispatch pattern as
    angel_one_feed._execute_llm_risk_audit. Degrades to None if LLM isn't configured."""
    if reason not in ("SL_HIT", "EOD_SQUAREOFF"):
        return None

    from .angel_one_feed import _llm_config_canonical, LLM_CALL_TIMEOUT_SECONDS

    config = _llm_config_canonical()
    provider, api_key, api_url, model, oauth_token_path = config or (None, None, None, None, None)
    if not provider or not api_key:
        return None

    prompt = _build_miss_prompt(pick, reason, pnl)

    try:
        if provider == "gemini":
            from .llm_client import _call_gemini
            return _call_gemini(
                prompt=prompt,
                api_key=api_key,
                model=model,
                system_instruction=MISS_ANALYSIS_SYSTEM_PROMPT,
                timeout=min(30, LLM_CALL_TIMEOUT_SECONDS),
                oauth_token_path=oauth_token_path,
            )
        elif provider == "openai":
            import requests
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": MISS_ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 300,
            }
            resp = requests.post(api_url, json=body, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        log.warning("LLM miss-analysis failed for %s: %s", pick.get("symbol"), exc)
        return None
    return None


def generate_intraday_eod_report(for_date: date, capital: float = DEFAULT_INTRADAY_CAPITAL) -> dict[str, Any]:
    archive = load_archive(for_date)
    picks = list((archive.get("intradayPicks") or {}).values())

    if not picks:
        return {
            "date": for_date.isoformat(),
            "capital": capital,
            "trades": [],
            "summary": {"note": "No archived intraday picks for this date"},
        }

    rows = []
    total_pnl = 0.0
    total_deployed = 0.0
    hits = {"T1_HIT": 0, "T2_HIT": 0, "SL_HIT": 0, "EOD_SQUAREOFF": 0}

    for pick in picks:
        reason, exit_price, pnl = _leg_pnl(pick)
        deployed = float(pick.get("deployedCapital") or 0)
        total_pnl += pnl
        total_deployed += deployed
        hits[reason] = hits.get(reason, 0) + 1

        miss_analysis = _get_miss_analysis(pick, reason, pnl)

        rows.append({
            "symbol": pick.get("symbol"),
            "direction": pick.get("direction"),
            "entryPrice": pick.get("entryPrice"),
            "exitPrice": round(exit_price, 2),
            "exitReason": reason,
            "qty": pick.get("approxQty"),
            "deployedCapital": deployed,
            "pnl": round(pnl, 2),
            "pnlPct": round((pnl / deployed * 100), 2) if deployed else None,
            "missAnalysis": miss_analysis,
        })

    remaining_capital = capital + total_pnl

    return {
        "date": for_date.isoformat(),
        "capital": capital,
        "totalDeployed": round(total_deployed, 2),
        "totalPnl": round(total_pnl, 2),
        "remainingCapital": round(remaining_capital, 2),
        "hitBreakdown": hits,
        "hitRatePct": round((hits["T1_HIT"] + hits["T2_HIT"]) / len(picks) * 100, 1) if picks else 0,
        "trades": rows,
    }