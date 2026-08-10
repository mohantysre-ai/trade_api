"""Per-day Book P&L report cache and EOD reconciliation.

Files under ``backend/app/data/eod/YYYY-MM-DD/``:
  - book_intraday.json
  - book_swing.json

Book P&L is the execution/reporting source of truth. Institutional scorecards
remain useful for forensic diagnostics, but must not overwrite the Book's
realized trade counts, win rate, deployed capital, or net return.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _day_dir(for_date) -> str:
    from .eod_engine.ingestion import eod_day_dir
    return eod_day_dir(for_date)


def book_cache_path(for_date, kind: str) -> str:
    name = "book_intraday.json" if kind == "intraday" else "book_swing.json"
    return os.path.join(_day_dir(for_date), name)


def _read_json(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.warning("EOD cache read failed %s: %s", path, exc)
        return None


def _write_json(path: str, payload: dict[str, Any]) -> None:
    from .eod_engine.ingestion import atomic_write_json
    atomic_write_json(path, payload)


def _row_pnl_pct(row: dict[str, Any]) -> float | None:
    value = row.get("pnlPct")
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    pnl = row.get("pnl")
    deployed = row.get("deployedCapital")
    try:
        if pnl is not None and deployed not in (None, 0, ""):
            return float(pnl) / float(deployed) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None


def _is_triggered_swing(row: dict[str, Any]) -> bool:
    return not bool(row.get("skipped")) and str(row.get("status") or "").upper() != "NOT_TRIGGERED"


def _reconcile_master_from_books(for_date) -> None:
    """Make the headline EOD artifact agree with the canonical Book caches.

    The forensic engine may model a different exit path (for example a 1-minute
    T1/SL path) from the Book's SCALE_TRAIL / close-mark accounting. That is
    valid for diagnostics, but it must not overwrite realized Book metrics.
    """
    day_dir = _day_dir(for_date)
    master_path = os.path.join(day_dir, "master_eod_payload.json")
    master = _read_json(master_path)
    if master is None:
        return

    intra = _read_json(os.path.join(day_dir, "book_intraday.json"))
    swing = _read_json(os.path.join(day_dir, "book_swing.json"))
    if intra is None or swing is None:
        return

    intra_rows = [r for r in (intra.get("trades") or []) if isinstance(r, dict)]
    swing_rows = [r for r in (swing.get("picks") or []) if isinstance(r, dict)]
    active_swing = [r for r in swing_rows if _is_triggered_swing(r)]
    active_intra = [
        r for r in intra_rows
        if str(r.get("exitReason") or "").upper() != "NOT_TRIGGERED"
    ]
    active_rows = active_intra + active_swing

    locked = len(intra_rows) + len(swing_rows)
    triggered = len(active_rows)
    skipped = max(0, locked - triggered)

    pnls: list[float] = []
    deployed = 0.0
    for row in active_rows:
        try:
            pnl = float(row.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        pnls.append(pnl)
        try:
            deployed += float(row.get("deployedCapital") or 0.0)
        except (TypeError, ValueError):
            pass

    deployed_from_reports = 0.0
    for report in (intra, swing):
        try:
            deployed_from_reports += float(report.get("totalDeployed") or 0.0)
        except (TypeError, ValueError):
            pass
    if deployed_from_reports > 0:
        deployed = deployed_from_reports

    net_pnl = round(sum(pnls), 2)
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    win_rate = round(wins / triggered * 100.0, 2) if triggered else None
    net_return = round(net_pnl / deployed * 100.0, 4) if deployed else None

    win_pcts = [p for p in (_row_pnl_pct(r) for r in active_rows) if p is not None and p > 0]
    loss_pcts = [abs(p) for p in (_row_pnl_pct(r) for r in active_rows) if p is not None and p < 0]
    avg_rr = (
        round((sum(win_pcts) / len(win_pcts)) / (sum(loss_pcts) / len(loss_pcts)), 3)
        if win_pcts and loss_pcts else None
    )

    # Score is deterministic and tied to reconciled headline metrics. ECE/Brier
    # are forensic probability metrics, not Book accounting metrics, so they are
    # cleared here rather than displaying stale values from a different model.
    score = 5.0
    if win_rate is not None:
        score += (win_rate - 50.0) / 20.0
    if net_return is not None:
        score += max(-2.0, min(2.0, net_return))
    score = round(max(0.0, min(10.0, score)), 2)

    executive = master.get("executive_summary")
    if not isinstance(executive, dict):
        executive = {}
        master["executive_summary"] = executive

    executive.update({
        "overall_institutional_score": score,
        "total_trades": locked,
        "win_trades": wins,
        "loss_trades": losses,
        "no_entry_trades": skipped,
        "win_rate_pct": win_rate,
        "average_risk_reward": avg_rr,
        "net_strategy_return_pct": net_return,
        "capital_efficiency_pct": round(deployed / (deployed + abs(net_pnl)) * 100.0, 2) if deployed else None,
        "expected_calibration_error": None,
        "brier_score": None,
        "false_positive_count": 0,
    })

    master["book_reconciliation"] = {
        "source": "BOOK",
        "locked": locked,
        "triggered": triggered,
        "skipped": skipped,
        "wins": wins,
        "losses": losses,
        "deployed": round(deployed, 2),
        "net_pnl": net_pnl,
        "win_rate_pct": win_rate,
        "net_return_pct": net_return,
        "intraday_pnl": round(float(intra.get("totalPnl") or 0.0), 2),
        "swing_pnl": round(float(swing.get("totalPnl") or 0.0), 2),
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
    }

    # Deterministic Book commentary replaces stale LLM prose until the user
    # explicitly regenerates PM commentary from the corrected artifact.
    master["pm_commentary"] = {
        "executive_summary": (
            f"Book-reconciled EOD: {net_pnl:+.2f} net P&L across {locked} locked names "
            f"({triggered} triggered, {skipped} not triggered), with {wins} wins and "
            f"{losses} losses. Win rate is {win_rate if win_rate is not None else '—'}% "
            f"and net return is {net_return if net_return is not None else '—'}% on "
            f"₹{deployed:,.0f} deployed."
        ),
        "attribution_narrative": (
            f"Intraday P&L {float(intra.get('totalPnl') or 0.0):+.2f}; "
            f"Swing P&L {float(swing.get('totalPnl') or 0.0):+.2f}. "
            "Trade-level attribution is sourced from the Book rows; forensic "
            "scorecards remain diagnostic and do not override realized Book P&L."
        ),
        "execution_and_slippage_review": (
            "Book reconciliation uses the same realized P&L, close marks, scale/trail "
            "state, and deployed-capital rows shown in the EOD Book."
        ),
        "actionable_directives": [
            "Use BOOK as the headline P&L / win-rate source for EOD reporting.",
            "Keep ECE/Brier and forensic scorecards separate from realized Book accounting.",
        ],
        "source": "DETERMINISTIC_FALLBACK",
    }

    notes = list(master.get("notes") or [])
    if "book_reconciled_headline_metrics" not in notes:
        notes.append("book_reconciled_headline_metrics")
    master["notes"] = notes
    _write_json(master_path, master)
    _write_json(os.path.join(day_dir, "pm_commentary.json"), master["pm_commentary"])


def load_book_cache(for_date, kind: str) -> dict[str, Any] | None:
    path = book_cache_path(for_date, kind)
    data = _read_json(path)
    if data is None:
        return None
    try:
        _reconcile_master_from_books(for_date)
    except Exception as exc:
        log.warning("EOD Book reconciliation failed for %s: %s", for_date, exc)
    out = dict(data)
    out["fromCache"] = True
    return out


def save_book_cache(for_date, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = book_cache_path(for_date, kind)
    to_store = {k: v for k, v in payload.items() if k != "fromCache"}
    to_store["cachedAt"] = datetime.now(timezone.utc).isoformat()
    _write_json(path, to_store)
    try:
        _reconcile_master_from_books(for_date)
    except Exception as exc:
        log.warning("EOD Book reconciliation after save failed for %s: %s", for_date, exc)
    out = dict(to_store)
    out["fromCache"] = False
    return out


def warm_book_caches(for_date) -> dict[str, Any]:
    """Rebuild and persist both book reports (called after institutional EOD run)."""
    from .eod_intraday_report import generate_intraday_eod_report
    from .eod_swing_report import generate_swing_eod_report

    intra = generate_intraday_eod_report(for_date, force=True)
    swing = generate_swing_eod_report(for_date, force=True)
    try:
        _reconcile_master_from_books(for_date)
    except Exception as exc:
        log.warning("EOD Book reconciliation after warm failed for %s: %s", for_date, exc)
    return {
        "intraday": bool(intra),
        "swing": bool(swing),
        "date": for_date.isoformat() if hasattr(for_date, "isoformat") else str(for_date),
    }
