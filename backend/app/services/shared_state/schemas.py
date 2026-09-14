"""Shared schemas and types for the high-scale live data architecture."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FeedStatus(str, Enum):
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class EventType(str, Enum):
    MARKET_QUOTE = "MARKET_QUOTE"
    BAR_CLOSED = "BAR_CLOSED"
    INTRADAY_STATE_CHANGED = "INTRADAY_STATE_CHANGED"
    SWING_STATE_CHANGED = "SWING_STATE_CHANGED"
    INDEX_OPTIONS_STATE_CHANGED = "INDEX_OPTIONS_STATE_CHANGED"
    TRADE_EVENT = "TRADE_EVENT"
    EOD_READY = "EOD_READY"
    HEALTH_CHANGED = "HEALTH_CHANGED"


@dataclass
class Quote:
    symbol: str
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None
    oi: float | None = None
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    data_age: float = 0.0
    feed_status: FeedStatus = FeedStatus.UNAVAILABLE
    completed_bars: int = 0


@dataclass
class Bar:
    symbol: str
    interval: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    timestamp: float = field(default_factory=time.time)
    bucket: str = ""


@dataclass
class ViewVersion:
    version: int = 0
    updated_at: float = field(default_factory=time.time)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: int = 0
