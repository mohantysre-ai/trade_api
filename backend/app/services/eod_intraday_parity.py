"""Final Intraday -> EOD parity boundary.

The execution session is authoritative for entry/exit/partial/open economics.
For the live session date this wrapper projects every locked row from the
session, overlays exact execution economics, and persists that same object into
the EOD Book cache so the UI, master EOD payload, and cache warmer cannot see a
different reconstruction.
"""
from __future__ import annotations

from typing import Any, Callable

_INSTALLED = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import eod_intraday_report as report_mod
    from .eod_intraday_authority import reconcile_report

    original: Callable[..., dict[str, Any]] = report_mod.generate_intraday_eod_report
    if getattr(original, "_intraday_parity_wrapped", False):
        _INSTALLED = True
        return

    def parity_generate(for_date, *args, **kwargs):
        report = original(for_date, *args, **kwargs)
        try:
            force = bool(kwargs.get("force", False))
            # A normal EOD read is immutable. If the generator returned a
            # versioned snapshot, do not recompute the session or rewrite the
            # same file on every dashboard poll.
            if not force and report.get("fromCache"):
                return report

            from .desk_clock import cash_session_phase
            from .eod_book_cache import save_book_cache
            from .intraday_session_engine import _compute_session

            session = _compute_session(include_live=True, persist=False)
            if str(session.get("sessionDate") or "")[:10] != for_date.isoformat():
                return report

            capital = kwargs.get("capital")
            if capital is None and args:
                capital = args[0]
            if capital is None:
                capital = report.get("capital") or report_mod.DEFAULT_INTRADAY_CAPITAL

            # At/after close (and for an explicit rebuild), construct the Book
            # directly from every locked session row. This prevents a stale
            # scanner/plan/archive symbol set from dropping an executed trade.
            if force or cash_session_phase(for_date) == "CLOSED":
                report = report_mod.project_session_live(
                    session, for_date=for_date, capital=float(capital)
                )

            # Exact stop fills, partial realized + remaining MTM, open MTM and
            # NOT_TRIGGERED=0 are copied from the execution ledger.
            report = reconcile_report(report, session)
            report["reconciliationSource"] = "INTRADAY_EXECUTION_LEDGER"
            report["reconciliationParity"] = "AUTHORITATIVE"

            # Critical: persist the reconciled object, not the pre-overlay
            # forensic reconstruction. save_book_cache also reconciles master EOD.
            return save_book_cache(for_date, "intraday", report)
        except Exception as exc:
            # Preserve availability, but make a parity failure observable rather
            # than silently claiming reconciliation succeeded.
            out = dict(report) if isinstance(report, dict) else {"trades": []}
            out["reconciliationParity"] = "FALLBACK"
            out["reconciliationError"] = str(exc)
            return out

    parity_generate._intraday_parity_wrapped = True  # type: ignore[attr-defined]
    parity_generate.__name__ = original.__name__
    parity_generate.__doc__ = original.__doc__
    report_mod.generate_intraday_eod_report = parity_generate
    _INSTALLED = True
