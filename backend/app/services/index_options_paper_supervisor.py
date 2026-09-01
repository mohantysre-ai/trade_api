"""Autonomous server-side supervisor for already-locked index-option paper trades.

This module deliberately does not scan, score, select, or create trades. The
existing index-options engine remains the only source of trade-entry decisions.
The supervisor only wakes on a one-minute cadence, refreshes marks for positions
already present in the durable paper book, applies the existing exit rules via
``reconcile_paper_book``, and persists the resulting state.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Callable

from .angel_index_options import IST_ZONE
from .index_options_paper import reconcile_paper_book
from .json_atomic import atomic_write_json, load_json_with_fallback
from .market_snapshot_store import market_snapshot_path

logger = logging.getLogger(__name__)

SUPERVISOR_INTERVAL_SECONDS = 60
SUPERVISOR_SESSION_START = dt_time(9, 15)
SUPERVISOR_SESSION_END = dt_time(15, 30)

_THREAD_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "owner": False,
    "intervalSeconds": SUPERVISOR_INTERVAL_SECONDS,
    "lastCycleAt": None,
    "lastSuccessAt": None,
    "lastError": None,
    "consecutiveFailures": 0,
    "pid": os.getpid(),
}


def _enabled() -> bool:
    value = str(os.environ.get("INDEX_OPTIONS_PAPER_SUPERVISOR_ENABLED", "true")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _status_path() -> Path:
    override = (os.environ.get("INDEX_OPTIONS_PAPER_SUPERVISOR_STATUS_FILE") or "").strip()
    return Path(override) if override else market_snapshot_path().with_name("index_options_paper_supervisor.json")


def _lock_path() -> Path:
    override = (os.environ.get("INDEX_OPTIONS_PAPER_SUPERVISOR_LOCK_FILE") or "").strip()
    return Path(override) if override else market_snapshot_path().with_name("index_options_paper_supervisor.lock")


def _session_active(now: datetime) -> bool:
    clock = now.astimezone(IST_ZONE)
    local_time = clock.time().replace(tzinfo=None)
    return clock.weekday() < 5 and SUPERVISOR_SESSION_START <= local_time <= SUPERVISOR_SESSION_END


def _next_minute_boundary(now: datetime) -> datetime:
    clock = now.astimezone(IST_ZONE)
    return clock.replace(second=0, microsecond=0) + timedelta(minutes=1)


def _set_local_status(**changes: Any) -> None:
    with _STATUS_LOCK:
        _STATUS.update(changes)


def _status_update(**changes: Any) -> None:
    """Update owner-local state and durable heartbeat.

    Only the cross-process lease owner calls this function. Non-owner workers
    keep their process-local status but never overwrite the shared heartbeat.
    """
    with _STATUS_LOCK:
        _STATUS.update(changes)
        payload = dict(_STATUS)
    try:
        atomic_write_json(_status_path(), payload)
    except Exception:
        logger.exception("failed to persist index-options paper supervisor status")


def paper_supervisor_status() -> dict[str, Any]:
    """Return the durable owner heartbeat plus this worker's ownership state."""
    with _STATUS_LOCK:
        current = dict(_STATUS)
    try:
        persisted = load_json_with_fallback(_status_path())
    except (FileNotFoundError, ValueError, TypeError):
        persisted = {}
    if isinstance(persisted, dict) and persisted:
        return {
            **persisted,
            "localWorkerPid": os.getpid(),
            "localWorkerOwner": bool(current.get("owner")),
            "localWorkerRunning": bool(current.get("running")),
        }
    return current


def run_paper_supervisor_cycle(client: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Mark/exit existing paper positions without admitting any new trades."""
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    radar = {
        "candidates": [],
        "sellerCandidates": [],
        "selected": [],  # critical: supervisor can never create a new entry
    }
    return reconcile_paper_book(radar, client=client, now=clock, persist=True)


class _ProcessLease:
    """Best-effort cross-process ownership so multi-worker servers run one marker."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            import fcntl  # Linux/Unix production path

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write(f"pid={os.getpid()}\n")
            self.handle.flush()
            return True
        except ImportError:
            # Windows/dev fallback: process-local singleton still prevents duplicate threads.
            return True
        except (BlockingIOError, OSError):
            self.handle.close()
            self.handle = None
            return False

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            try:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            self.handle.close()
        finally:
            self.handle = None


def _supervisor_loop(client_factory: Callable[[], Any]) -> None:
    lease = _ProcessLease(_lock_path())
    owner = lease.acquire()
    if not owner:
        _set_local_status(enabled=True, running=False, owner=False, pid=os.getpid())
        logger.info("index-options paper supervisor already owned by another worker")
        return

    _status_update(enabled=True, running=True, owner=True, pid=os.getpid())
    client: Any = None
    try:
        while not _STOP_EVENT.is_set():
            now = datetime.now(IST_ZONE)
            if not _session_active(now):
                _status_update(
                    running=True,
                    owner=True,
                    sessionActive=False,
                    nextCycleAt=None,
                    lastError=None,
                )
                # Sleep lightly so a long-running service notices the next session without restart.
                _STOP_EVENT.wait(30.0)
                continue

            next_boundary = _next_minute_boundary(now)
            wait_seconds = max(0.0, (next_boundary - now).total_seconds())
            _status_update(
                running=True,
                owner=True,
                sessionActive=True,
                nextCycleAt=next_boundary.isoformat(),
            )
            if _STOP_EVENT.wait(wait_seconds):
                break

            cycle_time = datetime.now(IST_ZONE).replace(second=0, microsecond=0)
            try:
                if client is None:
                    client = client_factory()
                book = run_paper_supervisor_cycle(client, now=cycle_time)
                _status_update(
                    running=True,
                    owner=True,
                    sessionActive=True,
                    lastCycleAt=cycle_time.isoformat(),
                    lastSuccessAt=cycle_time.isoformat(),
                    lastError=None,
                    consecutiveFailures=0,
                    openPositions=len(book.get("open") or []),
                    closedPositions=len(book.get("closed") or []),
                    entryCount=int(book.get("entryCount") or 0),
                )
            except Exception as exc:
                # Drop the client so the next minute recreates the Angel session cleanly.
                client = None
                with _STATUS_LOCK:
                    failures = int(_STATUS.get("consecutiveFailures") or 0) + 1
                _status_update(
                    running=True,
                    owner=True,
                    sessionActive=True,
                    lastCycleAt=cycle_time.isoformat(),
                    lastError=str(exc),
                    consecutiveFailures=failures,
                )
                logger.exception("index-options autonomous paper mark cycle failed")
    finally:
        lease.release()
        _status_update(running=False, owner=False, nextCycleAt=None)


def start_paper_supervisor(client_factory: Callable[[], Any]) -> bool:
    """Start the one-minute autonomous marker once for this application process."""
    global _THREAD
    if not _enabled():
        _set_local_status(enabled=False, running=False, owner=False)
        return False

    with _THREAD_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _STOP_EVENT.clear()
        _THREAD = threading.Thread(
            target=_supervisor_loop,
            args=(client_factory,),
            name="index-options-paper-supervisor",
            daemon=True,
        )
        _THREAD.start()
    return True


def stop_paper_supervisor(*, join_timeout: float = 2.0) -> None:
    """Stop the process-local supervisor; primarily used by tests/shutdown hooks."""
    global _THREAD
    _STOP_EVENT.set()
    with _THREAD_LOCK:
        thread = _THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=join_timeout)
    with _THREAD_LOCK:
        if _THREAD is thread and (thread is None or not thread.is_alive()):
            _THREAD = None
