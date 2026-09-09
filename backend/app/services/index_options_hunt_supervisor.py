"""Autonomous server-side hunt for index-option BUY/SELL paper candidates.

This is orchestration only. It does not implement or modify any trading rule.
Every minute during the index-options market session it invokes the existing
``compose_live_index_options_radar`` pipeline, which remains the single source
of truth for scoring, gates, candidate selection, defined-risk seller
construction, re-entry policy, paper entry and persistence.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .angel_index_options import IST_ZONE
from .index_options_paper import index_options_market_open
from .json_atomic import atomic_write_json, load_json_with_fallback
from .market_snapshot_store import market_snapshot_path

logger = logging.getLogger(__name__)

HUNT_INTERVAL_SECONDS = 60
_THREAD_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STOP_EVENT = threading.Event()
_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "owner": False,
    "intervalSeconds": HUNT_INTERVAL_SECONDS,
    "lastCycleAt": None,
    "lastSuccessAt": None,
    "lastError": None,
    "consecutiveFailures": 0,
    "pid": os.getpid(),
}


def _enabled() -> bool:
    value = str(os.environ.get("INDEX_OPTIONS_HUNT_SUPERVISOR_ENABLED", "true")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _status_path() -> Path:
    override = (os.environ.get("INDEX_OPTIONS_HUNT_SUPERVISOR_STATUS_FILE") or "").strip()
    return Path(override) if override else market_snapshot_path().with_name("index_options_hunt_supervisor.json")


def _lock_path() -> Path:
    override = (os.environ.get("INDEX_OPTIONS_HUNT_SUPERVISOR_LOCK_FILE") or "").strip()
    return Path(override) if override else market_snapshot_path().with_name("index_options_hunt_supervisor.lock")


def _next_minute_boundary(now: datetime) -> datetime:
    clock = now.astimezone(IST_ZONE)
    return clock.replace(second=0, microsecond=0) + timedelta(minutes=1)


def _status_update(**changes: Any) -> None:
    with _STATUS_LOCK:
        _STATUS.update(changes)
        payload = dict(_STATUS)
    try:
        atomic_write_json(_status_path(), payload)
    except Exception:
        logger.exception("failed to persist index-options hunt supervisor status")


def index_options_hunt_status() -> dict[str, Any]:
    """Return local status or the durable heartbeat from the elected owner."""
    with _STATUS_LOCK:
        current = dict(_STATUS)
    try:
        persisted = load_json_with_fallback(_status_path())
    except (FileNotFoundError, ValueError, TypeError):
        persisted = {}
    if isinstance(persisted, dict):
        persisted_success = str(persisted.get("lastSuccessAt") or "")
        current_success = str(current.get("lastSuccessAt") or "")
        if persisted_success > current_success:
            return persisted
    return current


def run_index_options_hunt_cycle(client: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Run the existing live index-options pipeline once, unchanged."""
    from .angel_one_feed import ensure_fresh_market_snapshot
    from .index_options_live import compose_live_index_options_radar

    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    snapshot = ensure_fresh_market_snapshot(reason="autonomous_index_options_hunt")
    return compose_live_index_options_radar(
        snapshot,
        live=True,
        client=client,
        persist=True,
        now=clock,
    )


class _ProcessLease:
    """Cross-process single ownership for multi-worker API deployments."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.handle.seek(0)
            self.handle.truncate()
            self.handle.write(f"pid={os.getpid()}\n")
            self.handle.flush()
            return True
        except ImportError:
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


def _hunt_loop(client_factory: Callable[[], Any]) -> None:
    lease = _ProcessLease(_lock_path())
    owner = lease.acquire()
    if not owner:
        logger.info("index-options hunt supervisor already owned by another worker")
        return
    _status_update(enabled=True, running=True, owner=True, pid=os.getpid())

    client: Any = None
    try:
        while not _STOP_EVENT.is_set():
            now = datetime.now(IST_ZONE)
            if not index_options_market_open(now):
                _status_update(
                    running=True,
                    owner=True,
                    sessionActive=False,
                    nextCycleAt=None,
                    lastError=None,
                )
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
                radar = run_index_options_hunt_cycle(client, now=cycle_time)
                paper = radar.get("paperBook") if isinstance(radar.get("paperBook"), dict) else {}
                selected = radar.get("selected") if isinstance(radar.get("selected"), list) else []
                sellers = radar.get("sellerCandidates") if isinstance(radar.get("sellerCandidates"), list) else []
                _status_update(
                    running=True,
                    owner=True,
                    sessionActive=True,
                    lastCycleAt=cycle_time.isoformat(),
                    lastSuccessAt=cycle_time.isoformat(),
                    lastError=None,
                    consecutiveFailures=0,
                    selectedCount=len(selected),
                    sellerCandidateCount=len(sellers),
                    openPaperPositions=len(paper.get("open") or []),
                    dailyEntryCount=int(paper.get("entryCount") or 0),
                    huntActive=bool(radar.get("huntActive")),
                )
            except Exception as exc:
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
                logger.exception("autonomous index-options hunt cycle failed")
    finally:
        lease.release()
        _status_update(running=False, owner=False, nextCycleAt=None)


def start_index_options_hunt_supervisor(client_factory: Callable[[], Any]) -> bool:
    """Start continuous BUY/SELL option discovery once for this process."""
    global _THREAD
    if not _enabled():
        _status_update(enabled=False, running=False, owner=False)
        return False

    with _THREAD_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        _STOP_EVENT.clear()
        _THREAD = threading.Thread(
            target=_hunt_loop,
            args=(client_factory,),
            name="index-options-hunt-supervisor",
            daemon=True,
        )
        _THREAD.start()
    return True


def stop_index_options_hunt_supervisor(*, join_timeout: float = 2.0) -> None:
    global _THREAD
    _STOP_EVENT.set()
    with _THREAD_LOCK:
        thread = _THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=join_timeout)
    with _THREAD_LOCK:
        if _THREAD is thread and (thread is None or not thread.is_alive()):
            _THREAD = None
