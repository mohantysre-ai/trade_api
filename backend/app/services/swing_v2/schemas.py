from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ValidationState(StrEnum):
    RESEARCH_HYPOTHESIS = "RESEARCH_HYPOTHESIS"
    OOS_VALIDATED = "OOS_VALIDATED"
    PAPER_VALIDATED = "PAPER_VALIDATED"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"


class EventType(StrEnum):
    CANDIDATE_OBSERVED = "CANDIDATE_OBSERVED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    CANDIDATE_QUALIFIED = "CANDIDATE_QUALIFIED"
    POSITION_LOCKED = "POSITION_LOCKED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    FILL_PARTIAL = "FILL_PARTIAL"
    FILL_COMPLETE = "FILL_COMPLETE"
    MARK_OBSERVED = "MARK_OBSERVED"
    STOP_UPDATED = "STOP_UPDATED"
    T1_FILLED = "T1_FILLED"
    T2_FILLED = "T2_FILLED"
    STOP_FILLED = "STOP_FILLED"
    THESIS_BREAK_FILLED = "THESIS_BREAK_FILLED"
    TIME_EXIT_FILLED = "TIME_EXIT_FILLED"
    EXIT_EXECUTION_FAILED = "EXIT_EXECUTION_FAILED"
    ADMIN_CORRECTION = "ADMIN_CORRECTION"


TERMINAL_EVENTS = {
    EventType.ORDER_EXPIRED,
    EventType.T2_FILLED,
    EventType.STOP_FILLED,
    EventType.THESIS_BREAK_FILLED,
    EventType.TIME_EXIT_FILLED,
    EventType.EXIT_EXECUTION_FAILED,
}


@dataclass(frozen=True)
class SourceFact:
    value: Any
    source: str
    source_timestamp: str
    received_at: str
    quality_status: str = "OK"


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    session_date: str
    decision_timestamp: str
    symbol: str
    universe_segment: str
    setup_ids: tuple[str, ...]
    source_snapshot_id: str
    features: dict[str, Any]
    hard_gate_results: dict[str, Any]
    score: float
    segment_percentile: float
    upside_capacity_r: float
    expected_net_r: float | None
    expected_net_r_status: str
    regime: str
    decision: str
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    strategy_id: str = "SWING_2S_MOMENTUM_V2"
    policy_version: str = "2.0.0"
    feature_version: str = "swing_features_v2"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def trade_event_hash(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()
