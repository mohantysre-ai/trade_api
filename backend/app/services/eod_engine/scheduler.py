"""Full desk automation daemon — weekday IST pipeline, no manual clicks required.

Stages (weekdays, institutional open cadence):
  09:45+  Morning pre-work (Angel live + LLM day-lock) — post open-auction
  09:45–10:15  Primary basket lock (intraday top-five total + swing); catch-up if app starts later
  12:00   Midday live refresh (quotes/candles; LLM stays day-locked)
  14:00   Afternoon live refresh (same)
  15:31   Fixed-plan close marks
  15:35   EOD analysis (deterministic)
  16:00+  EOD PM LLM commentary (once)

Catch-up: if the app starts after 10:15, pending pre-work + lock still run once
until cash close — never before 09:45 (refuse stale pre-open books).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .ingestion import eod_day_dir
from .runner import ensure_pm_llm_once, run_eod_analysis
from ..desk_clock import basket_lock_allowed, lock_window_config

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_STARTED = False
_LOCK = threading.Lock()
_STOP = threading.Event()
_CLOSE_MARKS_DONE_FOR: str | None = None
_MORNING_ATTEMPTED_FOR: str | None = None
_COMMIT_ATTEMPTED_FOR: str | None = None
_MIDDAY_DONE: set[str] = set()
_PM_LLM_ATTEMPTED_FOR: str | None = None
_BG_RUNNING: set[str] = set()
_BG_LOCK = threading.Lock()


def _spawn_once(job_key: str, target) -> bool:
    """Start a daemon job if not already running for this key. Returns True if started."""
    with _BG_LOCK:
        if job_key in _BG_RUNNING:
            return False
        _BG_RUNNING.add(job_key)

    def _runner() -> None:
        try:
            target()
        finally:
            with _BG_LOCK:
                _BG_RUNNING.discard(job_key)

    threading.Thread(target=_runner, name=f"desk-{job_key[:40]}", daemon=True).start()
    return True


_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_STAMP_PATH = _DATA_DIR / "desk_automation_stamp.json"

# Align pre-work with lock open (09:45) — env overrideable
_PREWORK_HOUR = int(os.getenv("MARKET_PREWORK_HOUR", "9"))
_PREWORK_MINUTE = int(os.getenv("MARKET_PREWORK_MINUTE", "45"))
_PREWORK_ENABLED = os.getenv("MARKET_PREWORK_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

_DESK_AUTO = os.getenv("DESK_AUTO_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
_AUTO_COMMIT = os.getenv("DESK_AUTO_COMMIT", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
_AUTO_MIDDAY = os.getenv("DESK_AUTO_MIDDAY_REFRESH", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
_AUTO_PM_LLM = os.getenv("DESK_AUTO_PM_LLM", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
# Legacy delay kept for status display; commit window is DESK_LOCK_* via desk_clock
_COMMIT_DELAY_MIN = int(os.getenv("DESK_COMMIT_DELAY_MIN", "0"))
_MIDDAY_TIMES = os.getenv("DESK_MIDDAY_REFRESH_TIMES", "12:00,14:00")
_PM_LLM_HOUR = int(os.getenv("DESK_PM_LLM_HOUR", "16"))
_PM_LLM_MINUTE = int(os.getenv("DESK_PM_LLM_MINUTE", "0"))


def start_eod_scheduler() -> None:
    """Start background daemon once (idempotent)."""
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    t = threading.Thread(target=_scheduler_loop, name="desk-scheduler", daemon=True)
    t.start()
    lw = lock_window_config()
    msg = (
        f"Desk automation started "
        f"(pre-work {_PREWORK_HOUR:02d}:{_PREWORK_MINUTE:02d} · "
        f"lock {lw['lockStart']}–{lw['lockEnd']} catch-up≤{lw['catchupUntil']} · "
        f"midday {_MIDDAY_TIMES} · "
        f"close 15:31 · EOD 15:35 · PM-LLM {_PM_LLM_HOUR:02d}:{_PM_LLM_MINUTE:02d} IST)"
    )
    log.info(msg)
    print(f"INFO: {msg}", flush=True)


def stop_eod_scheduler() -> None:
    _STOP.set()


def desk_automation_status() -> dict[str, Any]:
    """Snapshot of automation config + today's stage stamp."""
    now = datetime.now(tz=IST)
    stamp = _load_stamp()
    day = now.strftime("%Y-%m-%d")
    allowed, reason = basket_lock_allowed(now)
    return {
        "success": True,
        "enabled": _DESK_AUTO,
        "date": day,
        "schedulerStarted": _STARTED,
        "config": {
            "preworkHour": _PREWORK_HOUR,
            "preworkMinute": _PREWORK_MINUTE,
            "preworkEnabled": _PREWORK_ENABLED,
            "autoCommit": _AUTO_COMMIT,
            "commitDelayMin": _COMMIT_DELAY_MIN,
            "lockWindow": lock_window_config(),
            "lockAllowedNow": allowed,
            "lockReason": reason,
            "autoMiddayRefresh": _AUTO_MIDDAY,
            "middayTimes": [f"{h:02d}:{m:02d}" for h, m in _parse_midday_times()],
            "autoPmLlm": _AUTO_PM_LLM,
            "pmLlmHour": _PM_LLM_HOUR,
            "pmLlmMinute": _PM_LLM_MINUTE,
        },
        "stamp": stamp if str(stamp.get("date") or "") == day else {"date": day, "stages": {}},
    }


def _scheduler_loop() -> None:
    while not _STOP.is_set():
        try:
            now = datetime.now(tz=IST)
            if now.weekday() < 5 and _DESK_AUTO:
                # The scheduler is the sole durable intraday state writer.
                # Public GET handlers only enrich/calculate in memory.
                try:
                    from ..intraday_session_engine import refresh_session_state

                    refresh_session_state()
                except Exception as exc:
                    log.debug("Live session state refresh skipped: %s", exc)
                _maybe_run_morning_prework(now)
                _maybe_auto_commit(now)
                _maybe_midday_refresh(now)
                if now.hour == 15:
                    if 31 <= now.minute < 35:
                        _maybe_refresh_close_marks(now)
                        _STOP.wait(30)
                        continue
                    if 35 <= now.minute < 40:
                        _maybe_refresh_close_marks(now)
                        _maybe_run_today()
                        _STOP.wait(300)
                        continue
                _maybe_pm_llm(now)
            _STOP.wait(30)
        except Exception as exc:
            log.warning("Desk scheduler loop error: %s", exc)
            _STOP.wait(60)


def _parse_midday_times() -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for part in (_MIDDAY_TIMES or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        try:
            hh_s, mm_s = part.split(":", 1)
            out.append((int(hh_s), int(mm_s)))
        except Exception:
            continue
    return out or [(12, 0), (14, 0)]


def _mins(h: int, m: int) -> int:
    return h * 60 + m


def _in_prework_window(now: datetime) -> bool:
    """Pre-work from configured open through cash close (catch-up friendly)."""
    mins = _mins(now.hour, now.minute)
    return _mins(_PREWORK_HOUR, _PREWORK_MINUTE) <= mins < _mins(15, 30)


def _in_commit_window(now: datetime) -> bool:
    """Primary lock window + late-start catch-up via desk_clock."""
    allowed, _reason = basket_lock_allowed(now)
    return allowed


def _load_stamp() -> dict[str, Any]:
    try:
        raw = json.loads(_STAMP_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_stamp(stamp: dict[str, Any]) -> None:
    try:
        _STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STAMP_PATH.write_text(json.dumps(stamp, indent=2), encoding="utf-8")
    except Exception:
        pass


def _today_stamp(now: datetime) -> dict[str, Any]:
    day = now.strftime("%Y-%m-%d")
    stamp = _load_stamp()
    if str(stamp.get("date") or "") != day:
        stamp = {"date": day, "stages": {}}
    stamp.setdefault("stages", {})
    return stamp


def _mark_stage(now: datetime, stage: str, **extra: Any) -> None:
    stamp = _today_stamp(now)
    entry = {
        "status": extra.pop("status", "done"),
        "at": datetime.now(tz=IST).isoformat(),
        **extra,
    }
    stamp["stages"][stage] = entry
    _save_stamp(stamp)


def _stage_done(now: datetime, stage: str) -> bool:
    stamp = _today_stamp(now)
    entry = (stamp.get("stages") or {}).get(stage) or {}
    return str(entry.get("status") or "") in ("done", "skipped")


def _maybe_run_morning_prework(now: datetime) -> None:
    global _MORNING_ATTEMPTED_FOR
    if not _PREWORK_ENABLED:
        return
    if not _in_prework_window(now):
        return
    day_key = now.strftime("%Y-%m-%d")
    if _MORNING_ATTEMPTED_FOR == day_key or _stage_done(now, "morning_prework"):
        _MORNING_ATTEMPTED_FOR = day_key
        return
    try:
        from ..angel_one_feed import morning_prework_done_today, run_scheduled_morning_prework

        if morning_prework_done_today():
            _MORNING_ATTEMPTED_FOR = day_key
            _mark_stage(now, "morning_prework", status="skipped", reason="already_done")
            log.info("Morning pre-work already done for %s — skip", day_key)
            return

        def _job() -> None:
            global _MORNING_ATTEMPTED_FOR
            try:
                result = run_scheduled_morning_prework(force=False)
                log.info(
                    "Morning pre-work result: skipped=%s llm_locked=%s success=%s error=%s",
                    result.get("skipped"),
                    result.get("llm_locked"),
                    result.get("success"),
                    result.get("error"),
                )
                if result.get("skipped") or result.get("success"):
                    _MORNING_ATTEMPTED_FOR = day_key
                    _mark_stage(
                        now,
                        "morning_prework",
                        status="done",
                        llm_locked=bool(result.get("llm_locked")),
                        skipped=bool(result.get("skipped")),
                    )
                else:
                    _mark_stage(now, "morning_prework", status="error", error=result.get("error"))
            except Exception as exc:
                log.warning("Morning pre-work failed: %s", exc)
                _mark_stage(now, "morning_prework", status="error", error=str(exc))

        if not _spawn_once(f"morning:{day_key}", _job):
            return
        log.info("Scheduled morning pre-work starting for %s", day_key)
    except Exception as exc:
        log.warning("Morning pre-work schedule error: %s", exc)
        _mark_stage(now, "morning_prework", status="error", error=str(exc))


def _session_already_locked() -> bool:
    try:
        from ..intraday_session_engine import load_session

        sess = load_session()
        return bool(sess.get("locked")) and str(sess.get("sessionDate") or "") == datetime.now(tz=IST).strftime(
            "%Y-%m-%d"
        )
    except Exception:
        return False


def _maybe_auto_commit(now: datetime) -> None:
    """Lock intraday top-five-total + swing session once pre-work is done."""
    global _COMMIT_ATTEMPTED_FOR
    if not _AUTO_COMMIT:
        return
    if not _in_commit_window(now):
        return
    day_key = now.strftime("%Y-%m-%d")
    if _COMMIT_ATTEMPTED_FOR == day_key or _stage_done(now, "session_commit"):
        _COMMIT_ATTEMPTED_FOR = day_key
        return
    if not (_stage_done(now, "morning_prework") or _MORNING_ATTEMPTED_FOR == day_key):
        try:
            from ..angel_one_feed import morning_prework_done_today

            if not morning_prework_done_today() and not _session_already_locked():
                return
        except Exception:
            return

    if _session_already_locked():
        _COMMIT_ATTEMPTED_FOR = day_key
        _mark_stage(now, "session_commit", status="skipped", reason="already_locked")
        try:
            from ..swing_session import ensure_swing_session_locked

            ensure_swing_session_locked()
            _mark_stage(now, "swing_lock", status="done")
        except Exception as exc:
            log.warning("Swing ensure after locked session failed: %s", exc)
        return

    try:
        from ..intraday_session_engine import ensure_intraday_session_locked, load_session
        from ..swing_session import ensure_swing_session_locked

        def _job() -> None:
            global _COMMIT_ATTEMPTED_FOR
            try:
                prior = load_session()
                prior_date = str(prior.get("sessionDate") or "").strip()[:10]
                stale_day = bool(prior.get("locked") and prior_date and prior_date != day_key)
                # Idempotent ensure — rotates when sessionDate != today
                result_sess = ensure_intraday_session_locked()
                locked = bool(result_sess.get("locked")) and str(result_sess.get("sessionDate") or "")[:10] == day_key
                rotated = bool(result_sess.get("rotated") or stale_day)
                if locked:
                    _COMMIT_ATTEMPTED_FOR = day_key
                    _mark_stage(
                        now,
                        "session_commit",
                        status="done",
                        reason="rotated" if rotated else "committed",
                    )
                    ensure_swing_session_locked()
                    _mark_stage(now, "swing_lock", status="done")
                    log.info(
                        "Auto-commit locked intraday + swing for %s (stale_rotate=%s)",
                        day_key,
                        rotated,
                    )
                    return
                err = result_sess.get("commitError") or "commit_failed"
                log.warning("Auto-commit not ready: %s", err)
                _mark_stage(now, "session_commit", status="pending", error=str(err))
                # Pool often empty when macros/regime mis-parsed or snapshot thin —
                # kick a live refresh so the next tick can adopt.
                if "Insufficient candidate" in str(err) or "Could not adopt" in str(err):
                    try:
                        from ..angel_one_feed import run_scheduled_live_refresh

                        run_scheduled_live_refresh(reason="auto_commit_pool_retry")
                    except Exception as refresh_exc:
                        log.warning("Auto-commit pool refresh failed: %s", refresh_exc)
            except Exception as exc:
                log.warning("Auto-commit failed: %s", exc)
                _mark_stage(now, "session_commit", status="error", error=str(exc))

        if not _spawn_once(f"commit:{day_key}", _job):
            return
        log.info("Scheduled auto-commit starting for %s", day_key)
    except Exception as exc:
        log.warning("Auto-commit schedule error: %s", exc)
        _mark_stage(now, "session_commit", status="error", error=str(exc))


def _maybe_midday_refresh(now: datetime) -> None:
    """Live Angel refresh at configured times; LLM stays day-locked."""
    if not _AUTO_MIDDAY:
        return
    day_key = now.strftime("%Y-%m-%d")
    mins_now = _mins(now.hour, now.minute)
    if mins_now >= _mins(15, 20):
        return
    for hh, mm in _parse_midday_times():
        stage = f"midday_{hh:02d}{mm:02d}"
        key = f"{day_key}:{stage}"
        if key in _MIDDAY_DONE or _stage_done(now, stage):
            _MIDDAY_DONE.add(key)
            continue
        start = _mins(hh, mm)
        if mins_now < start:
            continue
        try:
            from ..angel_one_feed import run_scheduled_live_refresh

            def _job(stage_name: str = stage, done_key: str = key) -> None:
                try:
                    result = run_scheduled_live_refresh(reason=f"desk_midday_{stage_name}")
                    if result.get("success"):
                        _MIDDAY_DONE.add(done_key)
                        _mark_stage(now, stage_name, status="done", llm_reused=result.get("llm_reused"))
                        log.info(
                            "Midday refresh %s done llm_reused=%s",
                            stage_name,
                            result.get("llm_reused"),
                        )
                    else:
                        _mark_stage(now, stage_name, status="error", error=result.get("error"))
                        log.warning("Midday refresh %s failed: %s", stage_name, result.get("error"))
                except Exception as exc:
                    log.warning("Midday refresh %s error: %s", stage_name, exc)
                    _mark_stage(now, stage_name, status="error", error=str(exc))

            if not _spawn_once(f"midday:{key}", _job):
                continue
            log.info("Scheduled midday live refresh %s starting", stage)
        except Exception as exc:
            log.warning("Midday refresh %s schedule error: %s", stage, exc)
            _mark_stage(now, stage, status="error", error=str(exc))


def _maybe_refresh_close_marks(now: datetime) -> None:
    global _CLOSE_MARKS_DONE_FOR
    day_key = now.strftime("%Y-%m-%d")
    minute_bucket = "early" if now.minute < 35 else "eod"
    stamp = f"{day_key}:{minute_bucket}"
    if _CLOSE_MARKS_DONE_FOR == stamp:
        return
    try:
        from ..angel_one_feed import refresh_fixed_plan_close_marks

        result = refresh_fixed_plan_close_marks(force=True)
        _CLOSE_MARKS_DONE_FOR = stamp
        _mark_stage(now, f"close_marks_{minute_bucket}", status="done", quotes=result.get("quoteCount"))
        log.info(
            "Post-close plan marks refreshed: ok=%s quotes=%s",
            result.get("ok"),
            result.get("quoteCount"),
        )
    except Exception as exc:
        log.warning("Post-close plan mark refresh failed: %s", exc)


def _maybe_run_today() -> None:
    today = datetime.now(tz=IST).date()
    now = datetime.now(tz=IST)
    master = os.path.join(eod_day_dir(today), "master_eod_payload.json")
    if os.path.isfile(master):
        log.info("EOD artifacts already present for %s — skip scheduled run", today)
        _mark_stage(now, "eod", status="skipped", reason="artifacts_present")
        return
    log.info("Scheduled EOD run starting for %s", today)
    try:
        result = run_eod_analysis(today, force=False)
        _mark_stage(
            now,
            "eod",
            status="done" if result.get("success", True) else "error",
            skipped=result.get("skipped"),
        )
        log.info(
            "Scheduled EOD run done: date=%s status=%s skipped=%s",
            result.get("date"),
            result.get("status"),
            result.get("skipped"),
        )
    except Exception as exc:
        log.exception("Scheduled EOD run failed: %s", exc)
        _mark_stage(now, "eod", status="error", error=str(exc))


def _maybe_pm_llm(now: datetime) -> None:
    """Once-per-day PM LLM after configured hour (default 16:00 IST)."""
    global _PM_LLM_ATTEMPTED_FOR
    if not _AUTO_PM_LLM:
        return
    mins_now = _mins(now.hour, now.minute)
    if mins_now < _mins(_PM_LLM_HOUR, _PM_LLM_MINUTE):
        return
    if mins_now >= _mins(18, 30):
        return
    day_key = now.strftime("%Y-%m-%d")
    if _PM_LLM_ATTEMPTED_FOR == day_key or _stage_done(now, "pm_llm"):
        _PM_LLM_ATTEMPTED_FOR = day_key
        return
    master = os.path.join(eod_day_dir(now.date()), "master_eod_payload.json")
    if not os.path.isfile(master) and not _stage_done(now, "eod"):
        if mins_now < _mins(16, 30):
            return
    try:
        log.info("Scheduled PM LLM starting for %s", day_key)

        def _job() -> None:
            global _PM_LLM_ATTEMPTED_FOR
            try:
                result = ensure_pm_llm_once(now.date())
                if result.get("llm_done") or result.get("skipped") or result.get("success"):
                    _PM_LLM_ATTEMPTED_FOR = day_key
                    _mark_stage(
                        now,
                        "pm_llm",
                        status="done",
                        skipped=bool(result.get("skipped")),
                        llm_done=bool(result.get("llm_done")),
                        pm_source=result.get("pm_source"),
                    )
                else:
                    _mark_stage(now, "pm_llm", status="error", reason=result.get("reason"))
                log.info(
                    "PM LLM result: skipped=%s llm_done=%s source=%s",
                    result.get("skipped"),
                    result.get("llm_done"),
                    result.get("pm_source"),
                )
            except Exception as exc:
                log.warning("PM LLM scheduled run failed: %s", exc)
                _mark_stage(now, "pm_llm", status="error", error=str(exc))

        _spawn_once(f"pm_llm:{day_key}", _job)
    except Exception as exc:
        log.warning("PM LLM schedule error: %s", exc)
        _mark_stage(now, "pm_llm", status="error", error=str(exc))
