"""FastAPI routes for Institutional EOD Analysis Engine."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .contracts import AuditTrailEntry, ProposalStatus
from .ingestion import (
    EOD_DATA_ROOT,
    atomic_write_json,
    eod_day_dir,
    list_eod_dates,
    load_persisted_candles,
)
from .runner import ensure_pm_llm_once, llm_status, run_eod_analysis
from .scheduler import start_eod_scheduler

router = APIRouter(tags=["eod"])


class ProposalReviewBody(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    reviewer: Optional[str] = None
    note: Optional[str] = None


def _day_path(for_date: str, filename: str) -> str:
    try:
        d = date.fromisoformat(for_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {for_date}") from exc
    return os.path.join(eod_day_dir(d), filename)


def _read_json_file(path: str) -> Any:
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Artifact not found: {os.path.basename(path)}")
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read artifact: {exc}") from exc


@router.get("/api/eod/dates")
def eod_dates() -> dict[str, Any]:
    return {"dates": list_eod_dates(), "root": EOD_DATA_ROOT}


@router.get("/api/eod/summary/{analysis_date}")
def eod_summary(analysis_date: str) -> dict[str, Any]:
    return _read_json_file(_day_path(analysis_date, "master_eod_payload.json"))


@router.get("/api/eod/scorecards/{analysis_date}")
def eod_scorecards(analysis_date: str) -> Any:
    return _read_json_file(_day_path(analysis_date, "scorecards.json"))


@router.get("/api/eod/proposals/{analysis_date}")
def eod_proposals(analysis_date: str) -> Any:
    return _read_json_file(_day_path(analysis_date, "proposals.json"))


@router.get("/api/eod/timeline/{analysis_date}/{ticker}")
def eod_timeline(analysis_date: str, ticker: str) -> Any:
    try:
        d = date.fromisoformat(analysis_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {analysis_date}") from exc
    data = load_persisted_candles(d, ticker.upper())
    if not data:
        raise HTTPException(status_code=404, detail=f"No timeline for {ticker} on {analysis_date}")
    return data


@router.get("/api/eod/counterfactuals/{analysis_date}/{trade_id}")
def eod_counterfactuals(analysis_date: str, trade_id: str) -> Any:
    payload = _read_json_file(_day_path(analysis_date, "counterfactuals.json"))
    trades = payload.get("trades") if isinstance(payload, dict) else None
    if not isinstance(trades, dict):
        raise HTTPException(status_code=404, detail="No counterfactuals file structure")
    # trade_id may be URL-encoded RELIANCE:LONG
    key = trade_id
    if key not in trades:
        # Try uppercase / decode variants
        alt = trade_id.replace("%3A", ":").upper()
        if alt in trades:
            key = alt
        else:
            # Fuzzy: match ticker prefix
            matches = [k for k in trades if k.upper().startswith(trade_id.upper().split(":")[0])]
            if len(matches) == 1:
                key = matches[0]
            else:
                raise HTTPException(status_code=404, detail=f"trade_id not found: {trade_id}")
    return {"trade_id": key, "date": analysis_date, "counterfactuals": trades[key]}


@router.get("/api/eod/llm-status/{analysis_date}")
def eod_llm_status(analysis_date: str) -> dict[str, Any]:
    """Whether PM LLM already ran for this day (safe for UI polling / refresh)."""
    try:
        return llm_status(analysis_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/eod/pm-llm")
def eod_pm_llm(date_str: Optional[str] = Query(None, alias="date")) -> dict[str, Any]:
    """Generate PM commentary with LLM at most once per day.

    If already cached as source=LLM, returns cache without calling the model.
    Refresh must never hit this endpoint.
    """
    try:
        result = ensure_pm_llm_once(date_str)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result


@router.post("/api/eod/run")
def eod_run(
    date_str: Optional[str] = Query(None, alias="date"),
    force: bool = Query(False),
    use_llm: bool = Query(
        False,
        description="Opt-in LLM for PM commentary only. Ignored if day already has LLM cache.",
    ),
) -> dict[str, Any]:
    """Manual / scheduled trigger. Does not mutate live strategy params.

    LLM is not used on GET/refresh. Prefer POST /api/eod/pm-llm for once-per-day
    PM commentary. use_llm on this route still respects per-day LLM cache.
    """
    try:
        result = run_eod_analysis(date_str, force=force, use_llm=use_llm)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "success": result.get("success", True),
        "skipped": result.get("skipped", False),
        "date": result.get("date"),
        "status": result.get("status"),
        "scorecard_count": result.get("scorecard_count"),
        "reason": result.get("reason"),
        "llm_used": result.get("llm_used", False),
    }


@router.post("/api/eod/proposals/{analysis_date}/{proposal_id}/review")
def review_proposal(
    analysis_date: str,
    proposal_id: str,
    body: ProposalReviewBody,
) -> dict[str, Any]:
    """APPROVE/REJECT a proposal and append audit trail. Never applies to live engine."""
    path = _day_path(analysis_date, "proposals.json")
    data = _read_json_file(path)
    proposals = data.get("proposals") if isinstance(data, dict) else data
    if not isinstance(proposals, list):
        raise HTTPException(status_code=500, detail="Invalid proposals artifact")

    target = None
    for p in proposals:
        if isinstance(p, dict) and p.get("proposal_id") == proposal_id:
            target = p
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"Proposal not found: {proposal_id}")

    if target.get("status") == ProposalStatus.INSUFFICIENT_SAMPLES.value:
        raise HTTPException(
            status_code=400,
            detail="Cannot review proposal with INSUFFICIENT_SAMPLES status",
        )

    new_status = (
        ProposalStatus.APPROVED.value
        if body.action == "APPROVE"
        else ProposalStatus.REJECTED.value
    )
    entry = AuditTrailEntry(
        action=body.action,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        reviewer=body.reviewer,
        note=body.note,
    )
    trail = list(target.get("audit_trail") or [])
    trail.append(entry.model_dump())
    target["status"] = new_status
    target["audit_trail"] = trail

    if isinstance(data, dict):
        data["proposals"] = proposals
        atomic_write_json(path, data)
    else:
        atomic_write_json(path, proposals)

    # Mirror status into master payload learning_proposals if present
    master_path = _day_path(analysis_date, "master_eod_payload.json")
    if os.path.isfile(master_path):
        try:
            master = _read_json_file(master_path)
            for mp in master.get("learning_proposals") or []:
                if isinstance(mp, dict) and mp.get("proposal_id") == proposal_id:
                    mp["status"] = new_status
                    mp["audit_trail"] = trail
            atomic_write_json(master_path, master)
        except Exception:
            pass

    return {
        "success": True,
        "proposal_id": proposal_id,
        "status": new_status,
        "audit_trail": trail,
        "note": "Review recorded only — live strategy parameters were not mutated.",
    }


def wire_eod_into_app(app: Any) -> None:
    """Include router and start scheduler on the FastAPI app."""
    app.include_router(router)
    start_eod_scheduler()
