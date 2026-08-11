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


def atomic_write_json(path: str | Path, payload: Any) -> None:
    """Write JSON without ever leaving a truncated live file.

    Strategy: unique tmp → validate → bak of last-good → os.replace with retries.
    If replace keeps failing (Docker Desktop EBUSY), write to ``*.new`` and leave
    it for readers (``load_json_with_fallback``).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, default=str)
    # Round-trip validate before touching disk targets
    json.loads(text)

    lock = _lock_for(str(path))
    with lock:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        new_path = path.with_suffix(path.suffix + ".new")
        bak = path.with_suffix(path.suffix + ".bak")
        tmp.write_text(text, encoding="utf-8")
        try:
            if path.is_file():
                try:
                    json.loads(path.read_text(encoding="utf-8-sig"))
                    # Keep last-known-good for recovery
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

            # Bind-mount rename failed — publish complete bytes via *.new only.
            # Never open(path, "w") / write_text(path) here (truncates under readers).
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


def load_json_with_fallback(path: str | Path) -> Any:
    """Load JSON, preferring live file then ``*.new`` then ``*.bak``."""
    path = Path(path)
    candidates = [
        path,
        path.with_suffix(path.suffix + ".new"),
        path.with_suffix(path.suffix + ".bak"),
    ]
    # Prefer newest valid among candidates that exist
    existing = [p for p in candidates if p.is_file()]
    existing.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    errors: list[str] = []
    for candidate in existing:
        try:
            return json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            errors.append(f"{candidate.name}: {exc}")
            continue
    if errors:
        raise RuntimeError("; ".join(errors))
    raise FileNotFoundError(str(path))
