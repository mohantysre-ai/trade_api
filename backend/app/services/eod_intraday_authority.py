"""Authoritative Intraday -> EOD reconciliation overlay.

The Intraday desk is the execution source of truth.  EOD analytics may replay
candles for diagnostics, but they must never replace a booked stop/partial fill
or turn an open MTM position into a zero-P&L binary close.
"""
from __future__ import annotations

from typing import Any, Callable


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _weighted_fill_price(row: dict[str, Any]) -> float | None:
    state = row.get("exitState") if isinstance(row.get("exitState"), dict) else {}
    fills = state.get("legsFilled") if isinstance(state.get("legsFilled"), list) else []
    qty = 0
    notional = 0.0
    for fill in fills:
        if not isinstance(fill, dict):
            continue
        q = int(fill.get("qty") or 0)
        px = _f(fill.get("price"))
        if q > 0 and px is not None:
            qty += q
            notional += q * px
    return round(notional / qty, 2) if qty else None


def _session_rows(session: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for side, default_direction in (("long", "LONG"), ("short", "SHORT")):
        for row in session.get(side) or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper().strip()
            direction = str(row.get("direction") or default_direction).upper()
            if symbol:
                out[(symbol, direction)] = row
    return out


def _is_closed(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").upper()
    return bool(row.get("closed")) or status in {
        "CLOSED", "STOP LOSS HIT", "TRAIL STOP HIT", "SCALE COMPLETE",
        "TARGET 1 HIT", "TARGET 2 HIT",
    }


def _is_skipped(row: dict[str, Any]) -> bool:
    return bool(row.get("skipped")) or str(row.get("executionStatus") or "").upper() == "NOT_TRIGGERED"


def _authoritative_pnl(row: dict[str, Any], *, closed: bool) -> tuple[float, float, float, str]:
    realized = _f(row.get("realizedPnl"))
    unrealized = _f(row.get("unrealizedPnl"))
    total = _f(row.get("totalPnl"))
    pnl = _f(row.get("pnl"))

    if closed:
        value = realized if realized is not None else (total if total is not None else (pnl or 0.0))
        return round(value, 2), round(value, 2), 0.0, "realised"

    # Open/partial rows must include both booked tranches and remaining MTM.
    if total is None:
        if realized is not None or unrealized is not None:
            total = (realized or 0.0) + (unrealized or 0.0)
        else:
            total = pnl or 0.0
    kind = "mixed" if (realized or 0.0) != 0 and int(row.get("remainingQty") or 0) > 0 else "unrealised"
    return round(total, 2), round(realized or 0.0, 2), round(unrealized or 0.0, 2), kind


def reconcile_report(report: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    """Overlay EOD rows with the exact economics shown by the Intraday desk."""
    if not isinstance(report, dict) or not isinstance(session, dict):
        return report
    idx = _session_rows(session)
    trades = report.get("trades") if isinstance(report.get("trades"), list) else []
    if not trades or not idx:
        return report

    out = dict(report)
    rows: list[dict[str, Any]] = []
    total = 0.0
    wins = losses = triggered = skipped = 0

    for old in trades:
        if not isinstance(old, dict):
            continue
        row = dict(old)
        key = (str(row.get("symbol") or "").upper().strip(), str(row.get("direction") or "LONG").upper())
        live = idx.get(key)
        if live is None:
            rows.append(row)
            total += float(row.get("pnl") or 0.0)
            continue

        if _is_skipped(live):
            row.update({
                "exitPrice": None, "exitReason": "NOT_TRIGGERED", "deskExitLabel": "SKIPPED",
                "executionStatus": "NOT_TRIGGERED", "outcomeBucket": "SKIPPED", "pnl": 0.0,
                "pnlPct": 0.0, "realizedPnl": 0.0, "unrealizedPnl": 0.0,
                "remainingQty": 0, "closed": True, "triggered": False, "skipped": True,
                "pnlKind": "skipped", "executionEvidence": "INTRADAY_SESSION_AUTHORITY",
            })
            skipped += 1
            rows.append(row)
            continue

        triggered += 1
        closed = _is_closed(live)
        pnl, realized, unrealized, pnl_kind = _authoritative_pnl(live, closed=closed)
        remaining = int(live.get("remainingQty") if live.get("remainingQty") is not None else (0 if closed else live.get("approxQty") or live.get("qty") or 0))
        state = live.get("exitState") if isinstance(live.get("exitState"), dict) else None
        fills = (state or {}).get("legsFilled") or []
        partial = bool(fills and remaining > 0)

        if closed:
            reason = str(live.get("exitReason") or live.get("status") or row.get("exitReason") or "CLOSED")
            exit_price = _f(live.get("exitPrice")) or _weighted_fill_price(live) or _f(live.get("effectiveStop")) or _f(live.get("ltp"))
        else:
            reason = "PARTIAL_SCALE" if partial else "OPEN_EOD_MTM"
            exit_price = _f(live.get("ltp")) or _f(live.get("currentPrice")) or _f(row.get("exitPrice"))

        entry = _f(live.get("entryPrice")) or _f(row.get("entryPrice"))
        qty = int(live.get("approxQty") or live.get("qty") or row.get("qty") or 0)
        deployed = _f(live.get("deployedCapital")) or (entry * qty if entry is not None and qty else _f(row.get("deployedCapital")) or 0.0)
        pnl_pct = round(pnl / deployed * 100.0, 2) if deployed else 0.0
        bucket = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")
        if pnl > 0:
            wins += 1
        elif pnl < 0:
            losses += 1

        row.update({
            "entryPrice": entry, "exitPrice": round(exit_price, 2) if exit_price is not None else None,
            "exitReason": reason, "deskExitLabel": reason, "executionStatus": "TRIGGERED",
            "outcomeBucket": bucket, "qty": qty, "deployedCapital": round(deployed, 2),
            "pnl": pnl, "pnlPct": pnl_pct, "realizedPnl": realized,
            "unrealizedPnl": unrealized, "remainingQty": remaining, "exitState": state,
            "closed": closed, "triggered": True, "skipped": False, "pnlKind": pnl_kind,
            "executionEvidence": "INTRADAY_SESSION_AUTHORITY",
        })
        total += pnl
        rows.append(row)

    out["trades"] = rows
    out["totalPnl"] = round(total, 2)
    capital = _f(out.get("capital")) or 0.0
    out["remainingCapital"] = round(capital + total, 2) if capital else out.get("remainingCapital")
    attr = dict(out.get("attribution") or {})
    attr.update({"triggered": triggered, "skipped": skipped, "wins": wins, "losses": losses})
    out["attribution"] = attr
    out["hitCount"] = wins
    out["missCount"] = losses
    out["hitRatePct"] = round(wins / triggered * 100.0, 1) if triggered else 0.0
    out["reconciliationSource"] = "INTRADAY_SESSION_AUTHORITY"
    return out


def install() -> None:
    """Wrap the existing EOD generator without changing its forensic engines."""
    from . import eod_intraday_report as report_mod

    original: Callable[..., dict[str, Any]] = report_mod.generate_intraday_eod_report
    if getattr(original, "_intraday_authority_wrapped", False):
        return

    def authoritative_generate(for_date, *args, **kwargs):
        report = original(for_date, *args, **kwargs)
        try:
            from .intraday_session_engine import _compute_session
            session = _compute_session(include_live=True, persist=False)
            if str(session.get("sessionDate") or "")[:10] == for_date.isoformat():
                report = reconcile_report(report, session)
        except Exception:
            # Never make EOD unavailable because live enrichment is unavailable;
            # the original deterministic report remains the fallback.
            pass
        return report

    authoritative_generate._intraday_authority_wrapped = True  # type: ignore[attr-defined]
    authoritative_generate.__name__ = original.__name__
    authoritative_generate.__doc__ = original.__doc__
    report_mod.generate_intraday_eod_report = authoritative_generate
