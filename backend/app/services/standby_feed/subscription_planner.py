"""What IROS asks the standby gateway to pin: the P0 (open-position) symbol set."""
from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


def compute_p0_symbols(day: str) -> list[str]:
    try:
        from ..desk_book_symbols import intraday_locked_symbols, swing_locked_symbols
        symbols = intraday_locked_symbols(day) | swing_locked_symbols(day)
    except Exception:
        LOGGER.debug("standby P0 symbol computation failed", exc_info=True)
        return []
    return sorted(s for s in symbols if s)
