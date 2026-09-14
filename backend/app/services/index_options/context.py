"""Immutable market context for index-options strategy evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from zoneinfo import ZoneInfo

IST_ZONE = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class IndexOptionContext:
    """Single market snapshot consumed by all strategies in one decision cycle."""
    index: str
    spot: float | None
    futures_price: float | None
    direction: str | None
    direction_score: float | None
    trend_score: float | None
    breakout_score: float | None
    breadth_score: float | None
    breadth_coverage: float | None
    breadth_directional_score: float | None
    futures_oi_state: str | None
    futures_oi_aligned: bool | None
    realized_vol: float | None
    atm_iv: float | None
    iv_rank: float | None
    iv_percentile: float | None
    skew: float | None
    term_structure: float | None
    expected_move: float | None
    chain: list[dict[str, Any]]
    expiry: str | None
    session_time: datetime
    structure: dict[str, Any] = field(default_factory=dict)
    breadth: dict[str, Any] = field(default_factory=dict)
    futures_oi: dict[str, Any] = field(default_factory=dict)
    gate_evidence: dict[str, Any] = field(default_factory=dict)
    data_limitations: list[str] = field(default_factory=list)
    provider_status: str | None = None
    data_source: str | None = None
    component_freshness: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def is_fresh(self) -> bool:
        return bool(self.provider_status and self.provider_status.upper() == "LIVE")

    def has_chain(self) -> bool:
        return bool(self.chain)

    def has_contract_data(self) -> bool:
        return any(
            isinstance(row, dict) and row.get("symbol") and row.get("ltp") is not None
            for row in self.chain
        )
