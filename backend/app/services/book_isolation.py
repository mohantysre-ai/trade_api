"""Runtime contract for independent trading books.

When enabled, a book may read common market facts but it cannot refresh,
reconcile, exclude, mutate, or persist another book's decisions or state.
"""
from __future__ import annotations

import os


def independent_books_enabled() -> bool:
    value = os.getenv("BOOK_EXECUTION_ISOLATION", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


__all__ = ["independent_books_enabled"]
