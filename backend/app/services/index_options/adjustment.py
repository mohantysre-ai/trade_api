"""Strategy adjustment stubs for future lifecycle conversions."""

from __future__ import annotations

from typing import Any


def can_adjust(position: dict[str, Any], context: Any) -> tuple[bool, str]:
    return False, "ADJUSTMENT_NOT_IMPLEMENTED"


def adjust(position: dict[str, Any], context: Any) -> dict[str, Any]:
    raise NotImplementedError("Strategy adjustment not implemented in Phase 1")
