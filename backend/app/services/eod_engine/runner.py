"""EOD runner — ingest → engines → validate → atomic JSON writes."""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import (
    CompleteEODAnalysisPayload,
    ExecutiveSummary,
    MarketRegimeLabel,
    PMCommentary,
    RegimeBreadth,
    ensure_eod_schema_file,
)
from .engines import (
    build_executive_summary,
    build_pm_commentary,
    build_scorecard,
    compute_regime_breadth,
    generate_learning_proposals,
    scan_missed_opportunities,
    utc_now_iso,
)
from .ingestion import (
    atomic_write_json,
    eod_day_dir,
    fetch_and_persist_candles,
    load_day_picks,
)

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _load_cached_pm_commentary(day_dir: str) -> PMCommentary | None:
    path = os.path.join(day_dir, "pm_commentary.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("executive_summary"):
            return PMCommentary.model_validate(data)
    except Exception as exc:
        log.warning("cached pm_commentary unreadable: %s", exc)
    return None


def run_eod_analysis(
    for_date: date | str | None = None,
    *,
    force: bool = False,
    use_llm: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """Orchestrate full EOD pipeline for a trading date.

    Idempotent: if master payload exists and force=False, returns existing.
    Never mutates live strategy parameters.

    LLM policy (minimum):
    - Refresh / GET paths never call LLM (read JSON only).
    - Default run uses deterministic PM commentary.
    - LLM only when use_llm=True, or EOD_PM_LLM=1 on a *first* write with no
      cached commentary. Existing pm_commentary.json is reused on force rebuilds
      unless use_llm=True.
    """
    ensure_eod_schema_file()

    if for_date is None:
        for_date = datetime.now(tz=IST).date()
    elif isinstance(for_date, str):
        for_date = date.fromisoformat(for_date)

    day_dir = eod_day_dir(for_date)
    master_path = os.path.join(day_dir, "master_eod_payload.json")
    cached_pm = _load_cached_pm_commentary(day_dir)

    if not force and os.path.isfile(master_path):
        try:
            with open(master_path, "r", encoding="utf-8-sig") as fh:
                existing = json.load(fh)
            _ensure_book_reports_cached(for_date)
            return {
                "success": True,
                "skipped": True,
                "reason": "artifacts_exist",
                "date": for_date.isoformat(),
                "payload": existing,
                "llm_used": False,
            }
        except Exception:
            pass

    # Opt-in LLM only; never on refresh. Never re-call if day already has LLM cache.
    already_llm = cached_pm is not None and str(cached_pm.source).upper() == "LLM"
    allow_llm = (bool(use_llm) or (_env_flag("EOD_PM_LLM", False) and cached_pm is None)) and not already_llm

    notes: list[str] = []
    ingested = load_day_picks(for_date)
    picks = ingested.get("picks") or []
    snapshot = ingested.get("snapshot") or {}
    capital = ingested.get("capital") or {}
    regime = ingested.get("regime") or {}

    if not picks:
        notes.append("no_picks_for_date")
        payload = _empty_payload(for_date, notes, regime, snapshot)
        if cached_pm is not None and not allow_llm:
            payload.pm_commentary = cached_pm
        _write_artifacts(
            day_dir,
            payload,
            [],
            {"date": for_date.isoformat(), "trades": {}},
            {"date": for_date.isoformat(), "proposals": []},
            payload.pm_commentary,
        )
        return {
            "success": True,
            "skipped": False,
            "date": for_date.isoformat(),
            "status": "NO_PICKS",
            "payload": payload.model_dump(mode="json"),
            "llm_used": False,
        }

    symbols = [p["symbol"] for p in picks]
    candles_by_sym = fetch_and_persist_candles(for_date, symbols, client=client)
    empty_candle_syms = [s for s, c in candles_by_sym.items() if not c]
    if empty_candle_syms:
        notes.append(f"empty_candles:{','.join(empty_candle_syms[:10])}")

    scorecards = [
        build_scorecard(pick, candles_by_sym.get(pick["symbol"]) or [], snapshot)
        for pick in picks
    ]

    regime_breadth = compute_regime_breadth(regime, snapshot)
    selected = {p["symbol"] for p in picks}
    missed = scan_missed_opportunities(snapshot, selected)
    executive = build_executive_summary(scorecards, regime_breadth, missed, capital)
    proposals = generate_learning_proposals(scorecards, for_date.isoformat())
    commentary = build_pm_commentary(
        executive,
        scorecards,
        proposals,
        allow_llm=allow_llm,
        cached=cached_pm if not allow_llm else None,
    )
    if allow_llm:
        notes.append("pm_commentary_llm")
    elif cached_pm is not None:
        notes.append("pm_commentary_reused")
    else:
        notes.append("pm_commentary_deterministic")

    status = "OK"
    if empty_candle_syms and len(empty_candle_syms) == len(symbols):
        status = "PARTIAL"
        notes.append("all_candles_missing_used_plan_fallback")
    elif empty_candle_syms:
        status = "PARTIAL"

    payload = CompleteEODAnalysisPayload(
        analysis_date=for_date.isoformat(),
        generated_at=utc_now_iso(),
        status=status,  # type: ignore[arg-type]
        notes=notes,
        executive_summary=executive,
        scorecards=scorecards,
        learning_proposals=proposals,
        pm_commentary=commentary,
    )
    # Validate round-trip
    payload = CompleteEODAnalysisPayload.model_validate(payload.model_dump(mode="json"))

    cf_payload = {
        "date": for_date.isoformat(),
        "trades": {
            sc.trade_id: [c.model_dump(mode="json") for c in sc.counterfactuals]
            for sc in scorecards
        },
    }
    scorecards_payload = [sc.model_dump(mode="json") for sc in scorecards]
    proposals_payload = {
        "date": for_date.isoformat(),
        "proposals": [p.model_dump(mode="json") for p in proposals],
    }

    _write_artifacts(
        day_dir,
        payload,
        scorecards_payload,
        cf_payload,
        proposals_payload,
        commentary,
    )

    # Persist timeline events onto candle files (non-destructive merge)
    for sc in scorecards:
        tick_path = os.path.join(day_dir, "timeline_ticks", f"{sc.ticker}.json")
        if not os.path.isfile(tick_path):
            continue
        try:
            with open(tick_path, "r", encoding="utf-8-sig") as fh:
                tick = json.load(fh)
            if isinstance(tick, dict):
                tick["events"] = sc.timeline_events
                tick["trade_id"] = sc.trade_id
                tick["outcome"] = sc.outcome.value
                atomic_write_json(tick_path, tick)
        except Exception:
            continue

    _ensure_book_reports_cached(for_date, force=True)

    return {
        "success": True,
        "skipped": False,
        "date": for_date.isoformat(),
        "status": status,
        "scorecard_count": len(scorecards),
        "payload": payload.model_dump(mode="json"),
        "llm_used": bool(allow_llm and commentary.source == "LLM"),
    }


def _ensure_book_reports_cached(for_date: date, *, force: bool = False) -> None:
    """Warm Book P&L JSON caches so Book tab refresh is instant.

    force=False still rebuilds when locked pick set ≠ cached trades (stale morning book).
    """
    try:
        from ..eod_book_cache import warm_book_caches
        from ..eod_intraday_report import generate_intraday_eod_report
        from ..eod_swing_report import generate_swing_eod_report

        if force:
            warm_book_caches(for_date)
        else:
            generate_intraday_eod_report(for_date, force=False)
            generate_swing_eod_report(for_date, force=False)
    except Exception as exc:
        log.warning("book cache warm failed for %s: %s", for_date, exc)


def llm_status(for_date: date | str | None = None) -> dict[str, Any]:
    """Whether PM commentary LLM already ran for this day (cache hit)."""
    if for_date is None:
        for_date = datetime.now(tz=IST).date()
    elif isinstance(for_date, str):
        for_date = date.fromisoformat(for_date)

    day_dir = eod_day_dir(for_date)
    master_path = os.path.join(day_dir, "master_eod_payload.json")
    cached = _load_cached_pm_commentary(day_dir)
    source = cached.source if cached else None
    llm_done = bool(cached and str(cached.source).upper() == "LLM")
    return {
        "date": for_date.isoformat(),
        "has_artifacts": os.path.isfile(master_path),
        "pm_source": source,
        "llm_done": llm_done,
        "llm_available": bool(os.path.isfile(master_path) and not llm_done),
    }


def ensure_pm_llm_once(for_date: date | str | None = None) -> dict[str, Any]:
    """Generate PM commentary via LLM at most once per analysis date.

    If ``pm_commentary.json`` already has ``source=LLM``, returns cache — never
    calls the model again. Refresh paths must not invoke this.
    Requires existing EOD artifacts (run engine first if missing).
    """
    if for_date is None:
        for_date = datetime.now(tz=IST).date()
    elif isinstance(for_date, str):
        for_date = date.fromisoformat(for_date)

    day_dir = eod_day_dir(for_date)
    master_path = os.path.join(day_dir, "master_eod_payload.json")
    cached = _load_cached_pm_commentary(day_dir)

    if cached is not None and str(cached.source).upper() == "LLM":
        return {
            "success": True,
            "skipped": True,
            "reason": "llm_already_cached_for_day",
            "date": for_date.isoformat(),
            "llm_used": False,
            "llm_done": True,
            "pm_source": "LLM",
            "commentary": cached.model_dump(mode="json"),
        }

    if not os.path.isfile(master_path):
        # First-time: full engine with LLM opt-in (still only once)
        result = run_eod_analysis(for_date, force=False, use_llm=True)
        pm = (result.get("payload") or {}).get("pm_commentary") or {}
        return {
            "success": result.get("success", True),
            "skipped": result.get("skipped", False),
            "reason": result.get("reason") or "engine_run_with_llm",
            "date": for_date.isoformat(),
            "llm_used": result.get("llm_used", False),
            "llm_done": str(pm.get("source") or "").upper() == "LLM",
            "pm_source": pm.get("source"),
            "commentary": pm,
        }

    # Artifacts exist — rebuild PM from stored facts only (no full candle re-fetch)
    try:
        with open(master_path, "r", encoding="utf-8-sig") as fh:
            master = json.load(fh)
    except Exception as exc:
        return {
            "success": False,
            "skipped": False,
            "reason": f"master_unreadable:{exc}",
            "date": for_date.isoformat(),
            "llm_used": False,
            "llm_done": False,
        }

    from .contracts import CompleteEODAnalysisPayload

    try:
        payload = CompleteEODAnalysisPayload.model_validate(master)
    except Exception as exc:
        return {
            "success": False,
            "skipped": False,
            "reason": f"master_invalid:{exc}",
            "date": for_date.isoformat(),
            "llm_used": False,
            "llm_done": False,
        }

    commentary = build_pm_commentary(
        payload.executive_summary,
        payload.scorecards,
        payload.learning_proposals,
        allow_llm=True,
        cached=None,
    )

    payload.pm_commentary = commentary
    payload.generated_at = utc_now_iso()
    notes = list(payload.notes or [])
    if commentary.source == "LLM":
        notes.append("pm_commentary_llm_once")
    else:
        notes.append("pm_commentary_llm_failed_deterministic")
    payload.notes = notes

    atomic_write_json(master_path, payload.model_dump(mode="json"))
    atomic_write_json(
        os.path.join(day_dir, "pm_commentary.json"),
        commentary.model_dump(mode="json"),
    )

    return {
        "success": True,
        "skipped": False,
        "reason": "pm_llm_generated" if commentary.source == "LLM" else "pm_llm_fallback",
        "date": for_date.isoformat(),
        "llm_used": commentary.source == "LLM",
        "llm_done": commentary.source == "LLM",
        "pm_source": commentary.source,
        "commentary": commentary.model_dump(mode="json"),
    }


def _empty_payload(
    for_date: date,
    notes: list[str],
    regime: dict[str, Any],
    snapshot: dict[str, Any],
) -> CompleteEODAnalysisPayload:
    rb = compute_regime_breadth(regime, snapshot) if (regime or snapshot) else RegimeBreadth(
        market_regime=MarketRegimeLabel.SECTOR_ROTATION_SELECTIVE,
    )
    executive = ExecutiveSummary(
        overall_institutional_score=0.0,
        total_trades=0,
        win_trades=0,
        loss_trades=0,
        no_entry_trades=0,
        win_rate_pct=None,
        average_risk_reward=None,
        net_strategy_return_pct=None,
        capital_efficiency_pct=None,
        expected_calibration_error=None,
        brier_score=None,
        market_regime=rb.market_regime,
        regime_breadth=rb,
        missed_opportunities=[],
        false_positive_count=0,
    )
    commentary = PMCommentary(
        executive_summary="No recommendations for this date.",
        attribution_narrative="No trades to attribute.",
        execution_and_slippage_review="TCA not applicable (no picks).",
        actionable_directives=["No action — empty session."],
        source="DETERMINISTIC_FALLBACK",
    )
    return CompleteEODAnalysisPayload(
        analysis_date=for_date.isoformat(),
        generated_at=utc_now_iso(),
        status="NO_PICKS",
        notes=notes,
        executive_summary=executive,
        scorecards=[],
        learning_proposals=[],
        pm_commentary=commentary,
    )


def _write_artifacts(
    day_dir: str,
    payload: CompleteEODAnalysisPayload,
    scorecards: list | dict,
    counterfactuals: list | dict,
    proposals: list | dict,
    commentary: PMCommentary,
) -> None:
    atomic_write_json(os.path.join(day_dir, "master_eod_payload.json"), payload.model_dump(mode="json"))
    atomic_write_json(os.path.join(day_dir, "scorecards.json"), scorecards)
    atomic_write_json(os.path.join(day_dir, "counterfactuals.json"), counterfactuals)
    atomic_write_json(os.path.join(day_dir, "proposals.json"), proposals)
    atomic_write_json(os.path.join(day_dir, "pm_commentary.json"), commentary.model_dump(mode="json"))
