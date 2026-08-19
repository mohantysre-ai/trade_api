"""Safe JSON persistence for Windows Docker bind mounts.

Never truncate the live file in place — that races with concurrent readers and
produces torn JSON (Expecting ':', Extra data, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_WRITE_LOCKS: dict[str, threading.Lock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _WRITE_LOCKS[key] = lock
        return lock


def _emit_atomic_json(path: Path, text: str) -> None:
    """Write already-validated JSON. Caller must hold ``_lock_for(path)``."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    new_path = path.with_suffix(path.suffix + ".new")
    bak = path.with_suffix(path.suffix + ".bak")
    tmp.write_text(text, encoding="utf-8")
    try:
        if path.is_file():
            try:
                json.loads(path.read_text(encoding="utf-8-sig"))
                bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass

        last_err: OSError | None = None
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                try:
                    new_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return
            except OSError as exc:
                last_err = exc
                time.sleep(0.08 * (attempt + 1))

        new_path.write_text(text, encoding="utf-8")
        log.warning(
            "atomic replace failed for %s (%s); wrote %s instead",
            path,
            last_err,
            new_path.name,
        )
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_json(path: str | Path, payload: Any) -> None:
    """Write JSON without ever leaving a truncated live file.

    Strategy: unique tmp → validate → bak of last-good → os.replace with retries.
    If replace keeps failing (Docker Desktop EBUSY), write to ``*.new`` and leave
    it for readers (``load_json_with_fallback``).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, default=str)
    json.loads(text)
    with _lock_for(str(path)):
        _emit_atomic_json(path, text)


def atomic_update_json(
    path: str | Path,
    mutator: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    """Load-mutate-write under the same lock so a stale in-memory snapshot cannot clobber disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(str(path)):
        try:
            current = load_json_with_fallback(path)
        except FileNotFoundError:
            current = {}
        if not isinstance(current, dict):
            raise TypeError(f"{path} did not contain a JSON object; refusing to patch")
        updated = mutator(dict(current))
        if not isinstance(updated, dict):
            updated = current
        text = json.dumps(updated, indent=2, default=str)
        json.loads(text)
        _emit_atomic_json(path, text)
        return updated


def load_json_with_fallback(path: str | Path) -> Any:
    """Load JSON from live / ``*.new`` / ``*.bak``.

    Prefer the newest valid among live and ``*.new`` (writers publish to
    ``*.new`` when ``os.replace`` fails). ``*.bak`` is last-known-good only
    after live and ``*.new`` fail to parse — it must not beat a valid live file
    just because it was stamped later during the write.
    """
    path = Path(path)
    live = path
    new_path = path.with_suffix(path.suffix + ".new")
    bak = path.with_suffix(path.suffix + ".bak")
    primary = [p for p in (live, new_path) if p.is_file()]
    if not primary and not bak.is_file():
        raise FileNotFoundError(str(path))

    def _rank(candidate: Path) -> tuple[float, int]:
        return (candidate.stat().st_mtime, 1 if candidate == new_path else 0)

    primary.sort(key=_rank, reverse=True)
    errors: list[str] = []
    for candidate in primary:
        try:
            return json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")
    if bak.is_file():
        try:
            return json.loads(bak.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"{bak.name}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    raise FileNotFoundError(str(path))
