"""Institutional EOD Analysis Engine — post-close analytics package.

Strict isolation: never mutates live recommendation/strategy parameters.
Artifacts live under backend/app/data/eod/YYYY-MM-DD/.
"""
from __future__ import annotations

from .runner import run_eod_analysis
from .scheduler import start_eod_scheduler

__all__ = ["run_eod_analysis", "start_eod_scheduler"]
