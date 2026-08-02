"""15:35 IST daemon scheduler for Institutional EOD Engine."""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from .ingestion import eod_day_dir
from .runner import run_eod_analysis

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_STARTED = False
_LOCK = threading.Lock()
_STOP = threading.Event()


def start_eod_scheduler() -> None:
    """Start background daemon once (idempotent). Fires runner at 15:35 IST."""
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    t = threading.Thread(target=_scheduler_loop, name="eod-scheduler", daemon=True)
    t.start()
    log.info("EOD scheduler started (15:35 IST)")


def stop_eod_scheduler() -> None:
    _STOP.set()


def _scheduler_loop() -> None:
    while not _STOP.is_set():
        try:
            now = datetime.now(tz=IST)
            # Fire window: 15:35–15:40 IST on weekdays if artifacts missing
            if now.weekday() < 5 and now.hour == 15 and 35 <= now.minute < 40:
                _maybe_run_today()
                # Sleep past the window to avoid double-fire
                _STOP.wait(300)
            else:
                _STOP.wait(30)
        except Exception as exc:
            log.warning("EOD scheduler loop error: %s", exc)
            _STOP.wait(60)


def _maybe_run_today() -> None:
    today = datetime.now(tz=IST).date()
    master = os.path.join(eod_day_dir(today), "master_eod_payload.json")
    if os.path.isfile(master):
        log.info("EOD artifacts already present for %s — skip scheduled run", today)
        return
    log.info("Scheduled EOD run starting for %s", today)
    try:
        result = run_eod_analysis(today, force=False)
        log.info(
            "Scheduled EOD run done: date=%s status=%s skipped=%s",
            result.get("date"),
            result.get("status"),
            result.get("skipped"),
        )
    except Exception as exc:
        log.exception("Scheduled EOD run failed: %s", exc)
