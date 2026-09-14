"""Common economics calculations for option strategies."""

from __future__ import annotations

import math
from typing import Any


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def calculate_spread_width(legs: list[dict[str, Any]], option_type: str) -> float | None:
    strikes = sorted(
        _float(leg.get("strike"))
        for leg in legs
        if leg.get("optionType") == option_type and _float(leg.get("strike")) is not None
    )
    if len(strikes) >= 2:
        return strikes[-1] - strikes[0]
    return None


def calculate_net_debit(legs: list[dict[str, Any]]) -> float | None:
    total = 0.0
    found = False
    for leg in legs:
        price = _float(leg.get("entryPrice"))
        if price is None:
            continue
        found = True
        if leg.get("action") == "BUY":
            total += price
        elif leg.get("action") == "SELL":
            total -= price
    return total if found else None


def calculate_max_profit_loss(legs: list[dict[str, Any]], width: float | None) -> tuple[float | None, float | None]:
    net = calculate_net_debit(legs)
    if net is None or width is None:
        return None, None
    if net > 0:
        max_profit = None  # unlimited for debit spreads
        max_loss = net * 100  # approximate per-lot
    elif net < 0:
        max_profit = abs(net) * 100
        max_loss = (width - abs(net)) * 100
    else:
        max_profit = 0.0
        max_loss = 0.0
    return max_profit, max_loss


def calculate_breakeven(short_strike: float | None, net_credit: float | None, net_debit: float | None, direction: str) -> list[float]:
    breakevens = []
    if short_strike is None:
        return breakevens
    if net_credit is not None and net_credit > 0:
        if direction == "BULLISH":
            breakevens.append(short_strike - net_credit)
        elif direction == "BEARISH":
            breakevens.append(short_strike + net_credit)
    elif net_debit is not None and net_debit > 0:
        breakevens.append(short_strike + net_debit)
    return breakevens
