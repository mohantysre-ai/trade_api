"""Per-day Book P&L report cache and EOD reconciliation.

Book P&L is the execution/reporting source of truth. Institutional scorecards
remain useful for forensic diagnostics, but must not overwrite realized Book
metrics. Cache schema is versioned so accounting-policy changes cannot leave
stale headline numbers on screen.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

from .json_atomic import atomic_update_json, atomic_write_json, load_json_with_fallback

log = logging.getLogger(__name__)
BOOK_CACHE_SCHEMA_VERSION = 8


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
        data = load_json_with_fallback(path)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception as exc:
        log.warning("EOD cache read failed %s: %s", path, exc)
        return None


def _write_json(path: str, payload: dict[str, Any]) -> None:
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


def _apply_book_reconciliation(
    master: dict[str, Any],
    intra: dict[str, Any],
    swing: dict[str, Any],
) -> dict[str, Any]:
    """Patch headline EOD fields from canonical Book caches."""
    intra_rows = [r for r in (intra.get("trades") or []) if isinstance(r, dict)]
    swing_rows = [r for r in (swing.get("picks") or []) if isinstance(r, dict)]
    active_swing = [r for r in swing_rows if _is_triggered_swing(r)]
    active_intra = [r for r in intra_rows if str(r.get("executionStatus") or "").upper() != "NOT_TRIGGERED"]
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
    wins = sum(1 for r in active_rows if str(r.get("outcomeBucket") or "").upper() == "WIN")
    losses = sum(1 for r in active_rows if str(r.get("outcomeBucket") or "").upper() == "LOSS")
    if wins == 0 and losses == 0:
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
    win_rate = round(wins / triggered * 100.0, 2) if triggered else None
    net_return = round(net_pnl / deployed * 100.0, 4) if deployed else None

    win_pcts = [p for p in (_row_pnl_pct(r) for r in active_rows) if p is not None and p > 0]
    loss_pcts = [abs(p) for p in (_row_pnl_pct(r) for r in active_rows) if p is not None and p < 0]
    avg_rr = round((sum(win_pcts) / len(win_pcts)) / (sum(loss_pcts) / len(loss_pcts)), 3) if win_pcts and loss_pcts else None

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
            "Trade-level attribution is sourced from Book rows; forensic scorecards remain diagnostic."
        ),
        "execution_and_slippage_review": "Book reconciliation uses realized P&L, close marks, scale/trail state, and deployed-capital rows shown in the EOD Book.",
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
    return master


def _reconcile_master_from_books(for_date) -> None:
    """Make the headline EOD artifact agree with canonical Book caches."""
    day_dir = _day_dir(for_date)
    master_path = os.path.join(day_dir, "master_eod_payload.json")
    if not os.path.isfile(master_path):
        return

    intra = _read_json(os.path.join(day_dir, "book_intraday.json"))
    swing = _read_json(os.path.join(day_dir, "book_swing.json"))
    if intra is None or swing is None:
        return

    try:
        master = atomic_update_json(
            master_path,
            lambda current: _apply_book_reconciliation(current, intra, swing),
        )
    except (FileNotFoundError, RuntimeError) as exc:
        log.warning("EOD master reconcile failed %s: %s", master_path, exc)
        return

    _write_json(os.path.join(day_dir, "pm_commentary.json"), master["pm_commentary"])


def load_book_cache(for_date, kind: str) -> dict[str, Any] | None:
    path = book_cache_path(for_date, kind)
    data = _read_json(path)
    if data is None:
        return None
    if int(data.get("bookCacheSchemaVersion") or 0) != BOOK_CACHE_SCHEMA_VERSION:
        log.info("Ignoring stale %s Book cache for %s (schema=%s current=%s)", kind, for_date, data.get("bookCacheSchemaVersion"), BOOK_CACHE_SCHEMA_VERSION)
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
    to_store["bookCacheSchemaVersion"] = BOOK_CACHE_SCHEMA_VERSION
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


def freeze_dated_books_from_live(for_date: date | str) -> dict[str, Any]:
    """Snapshot live books into ``data/eod/{date}/`` before a daily rotate.

    Call while the live session files still carry ``sessionDate == for_date``.
    Existing archived trades are left untouched.
    """
    day = date.fromisoformat(str(for_date)[:10]) if not isinstance(for_date, date) else for_date
    intra = load_book_cache(day, "intraday")
    swing = load_book_cache(day, "swing")
    have_intra = bool(intra and intra.get("trades"))
    have_swing = bool(swing and (swing.get("picks") or swing.get("totalPicks")))
    if have_intra and have_swing:
        return {"skipped": True, "reason": "already_archived", "date": day.isoformat()}
    from .eod_intraday_report import generate_intraday_eod_report
    from .eod_swing_report import generate_swing_eod_report

    if not have_intra:
        generate_intraday_eod_report(day, force=True)
    if not have_swing:
        generate_swing_eod_report(day, force=True)
    return {"skipped": False, "date": day.isoformat()}


def _book_total_pnl(book: dict[str, Any] | None) -> float | None:
    if not book or str(book.get("archiveStatus") or "") == "NO_BOOK":
        return None
    raw = book.get("totalPnl")
    if raw is None:
        return None
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return None


def month_book_pnl(month: str | None = None) -> dict[str, Any]:
    """Sum archived daily Book P&L for a calendar month. Missing days stay missing."""
    from zoneinfo import ZoneInfo

    from .eod_engine.ingestion import list_eod_dates

    ist = ZoneInfo("Asia/Kolkata")
    today = datetime.now(tz=ist).date()
    if month:
        parts = str(month).strip().split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid month: {month}")
        try:
            year_i, mon_i = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValueError(f"Invalid month: {month}") from exc
        if not (1 <= mon_i <= 12):
            raise ValueError(f"Invalid month: {month}")
        prefix = f"{year_i:04d}-{mon_i:02d}"
    else:
        prefix = today.strftime("%Y-%m")
        year_i, mon_i = today.year, today.month

    label = date(year_i, mon_i, 1).strftime("%b %Y").upper()
    current_month = prefix == today.strftime("%Y-%m")
    days_out: list[dict[str, Any]] = []
    intra_sum = 0.0
    swing_sum = 0.0
    intra_n = 0
    swing_n = 0
    win_days = 0
    loss_days = 0
    flat_days = 0

    for day_key in list_eod_dates():
        if not day_key.startswith(prefix):
            continue
        try:
            day = date.fromisoformat(day_key)
        except ValueError:
            continue
        intra = load_book_cache(day, "intraday")
        swing = load_book_cache(day, "swing")
        ip = _book_total_pnl(intra)
        sp = _book_total_pnl(swing)
        has_intra = bool(intra and (intra.get("trades") or ip is not None) and str(intra.get("archiveStatus") or "") != "NO_BOOK")
        has_swing = bool(swing and (swing.get("picks") or sp is not None) and str(swing.get("archiveStatus") or "") != "NO_BOOK")
        if not has_intra and not has_swing:
            continue
        combined = round((ip or 0.0) + (sp or 0.0), 2) if (ip is not None or sp is not None) else None
        if ip is not None:
            intra_sum += ip
            intra_n += 1
        if sp is not None:
            swing_sum += sp
            swing_n += 1
        if combined is not None:
            if combined > 0.005:
                win_days += 1
            elif combined < -0.005:
                loss_days += 1
            else:
                flat_days += 1
        days_out.append({
            "date": day_key,
            "intradayPnl": ip,
            "swingPnl": sp,
            "combinedPnl": combined,
            "hasIntraday": has_intra,
            "hasSwing": has_swing,
        })

    return {
        "month": prefix,
        "label": label,
        "scope": "MTD" if current_month else "MONTH",
        "sessionCount": len(days_out),
        "intradayPnl": round(intra_sum, 2) if intra_n else None,
        "swingPnl": round(swing_sum, 2) if swing_n else None,
        "combinedPnl": round(intra_sum + swing_sum, 2) if (intra_n or swing_n) else None,
        "winDays": win_days,
        "lossDays": loss_days,
        "flatDays": flat_days,
        "days": days_out,
    }
