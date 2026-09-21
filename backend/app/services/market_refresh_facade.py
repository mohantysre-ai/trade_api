"""Provider-neutral entry point for shared market snapshot refreshes.

Strategy modules depend on this facade rather than broker-specific refresh
implementations.  The broker adapter remains centralized in angel_one_feed.
"""
from __future__ import annotations

from typing import Any


def refresh_market_snapshot(*, reason: str = "scheduled_live_refresh") -> dict[str, Any]:
    from .angel_one_feed import run_scheduled_live_refresh

    return run_scheduled_live_refresh(reason=reason)


__all__ = ["refresh_market_snapshot"]
