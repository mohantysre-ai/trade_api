"""Common option-leg model shared by every strategy structure.

A single structure (spread, condor, butterfly, straddle, calendar, diagonal)
persists its legs independently. Every leg carries its own identity, pricing,
Greeks and lifecycle timestamps so live marking and EOD attribution can operate
leg-by-leg without re-deriving anything from summary values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class OptionLeg:
    """One executable option leg inside a multi-leg strategy position."""

    strategy_position_id: str
    leg_id: str
    side: str
    option_type: str
    symbol: str
    strike: float | None
    expiry: str | None
    qty: int = 1
    lot_size: int | None = None

    entry_bid: float | None = None
    entry_ask: float | None = None
    entry_mid: float | None = None
    entry_price: float | None = None

    current_bid: float | None = None
    current_ask: float | None = None
    current_mid: float | None = None
    current_price: float | None = None

    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    iv: float | None = None

    oi: int | None = None
    volume: int | None = None
    spread_pct: float | None = None

    entry_timestamp: str | None = None
    exit_timestamp: str | None = None
    exit_price: float | None = None
    leg_pnl: float | None = None

    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def signed_qty(self) -> int:
        q = self.qty or 0
        return q if self.side.upper() == "BUY" else -q

    def to_dict(self) -> dict[str, Any]:
        return {
            "legId": self.leg_id,
            "strategyPositionId": self.strategy_position_id,
            "side": self.side,
            "optionType": self.option_type,
            "symbol": self.symbol,
            "strike": self.strike,
            "expiry": self.expiry,
            "qty": self.qty,
            "lotSize": self.lot_size,
            "entryBid": self.entry_bid,
            "entryAsk": self.entry_ask,
            "entryMid": self.entry_mid,
            "entryPrice": self.entry_price,
            "currentBid": self.current_bid,
            "currentAsk": self.current_ask,
            "currentMid": self.current_mid,
            "currentPrice": self.current_price,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "iv": self.iv,
            "oi": self.oi,
            "volume": self.volume,
            "spreadPct": self.spread_pct,
            "entryTimestamp": self.entry_timestamp,
            "exitTimestamp": self.exit_timestamp,
            "exitPrice": self.exit_price,
            "legPnl": self.leg_pnl,
            **self.extra,
        }


def leg_from_chain_contract(
    contract: dict[str, Any],
    *,
    strategy_position_id: str,
    leg_id: str,
    side: str,
    qty: int = 1,
    expiry: str | None = None,
) -> OptionLeg | None:
    """Build a leg from a raw option-chain contract row.

    Returns ``None`` when the row lacks the minimum executable identity
    (symbol + strike + two-sided quote). Missing material fields are never
    fabricated — the caller treats ``None`` as ``DATA_INCOMPLETE``.
    """
    if not isinstance(contract, dict):
        return None
    symbol = str(contract.get("symbol") or "").strip()
    strike = _float(contract.get("strike"))
    option_type = str(contract.get("optionType") or "").upper()
    if not symbol or strike is None or option_type not in {"CALL", "PUT"}:
        return None
    bid = _float(contract.get("bestBid"))
    ask = _float(contract.get("bestAsk"))
    mid = None
    if bid is not None and ask is not None:
        mid = round((bid + ask) / 2.0, 4)
    spread_pct = None
    if bid is not None and ask is not None and ask > 0:
        spread_pct = round((ask - bid) / ask * 100.0, 4)
    return OptionLeg(
        strategy_position_id=strategy_position_id,
        leg_id=leg_id,
        side=side.upper(),
        option_type=option_type,
        symbol=symbol,
        strike=strike,
        expiry=expiry or contract.get("expiry"),
        qty=qty,
        lot_size=_int(contract.get("lotSize")),
        entry_bid=bid,
        entry_ask=ask,
        entry_mid=mid,
        delta=_float(contract.get("delta")),
        gamma=_float(contract.get("gamma")),
        theta=_float(contract.get("theta")),
        vega=_float(contract.get("vega")),
        iv=_float(contract.get("iv")),
        oi=_int(contract.get("oi")),
        volume=_int(contract.get("volume")),
        spread_pct=spread_pct,
        extra={"token": contract.get("token"), "exchange": contract.get("exchange")},
    )


def net_greeks(legs: list[OptionLeg]) -> dict[str, float]:
    """Position-level Greeks from signed leg quantities."""
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    seen = {name: False for name in totals}
    for leg in legs:
        qty = leg.signed_qty * (leg.lot_size or 1)
        for name in totals:
            value = getattr(leg, name)
            if value is not None:
                totals[name] += float(value) * qty
                seen[name] = True
    return {name: (totals[name] if seen[name] else 0.0) for name in totals}


def structure_entry_debit(legs: list[OptionLeg]) -> float | None:
    """Net debit (positive) or credit (negative) using per-share entry prices."""
    total = 0.0
    found = False
    for leg in legs:
        price = leg.entry_price
        if price is None:
            continue
        found = True
        total += price if leg.side.upper() == "BUY" else -price
    return round(total, 4) if found else None


def structure_current_value(legs: list[OptionLeg]) -> float | None:
    """Current liquidation value per share: longs minus shorts."""
    total = 0.0
    found = False
    for leg in legs:
        price = leg.current_price if leg.current_price is not None else leg.current_mid
        if price is None:
            continue
        found = True
        total += price if leg.side.upper() == "BUY" else -price
    return round(total, 4) if found else None
