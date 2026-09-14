"""Deterministic economics for every option structure.

Each helper takes realised legs (with conservative entries already applied) and
returns the structure's cash, maximum profit/loss, breakevens, reward/risk and
net Greeks. ``None`` is always propagated rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .legs import OptionLeg, net_greeks, structure_entry_debit


@dataclass
class StructureEconomics:
    entry_debit: float | None
    entry_credit: float | None
    max_profit: float | None
    max_loss: float | None
    breakevens: list[float]
    reward_risk: float | None
    net_delta: float | None
    net_gamma: float | None
    net_theta: float | None
    net_vega: float | None
    margin: float | None
    width: float | None
    round_trip_costs: float | None
    liquidity_score: float | None
    execution_score: float | None


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _lot(legs: list[OptionLeg]) -> int:
    for leg in legs:
        if leg.lot_size:
            return int(leg.lot_size)
    return 1


def structure_width(legs: list[OptionLeg], option_type: str | None = None) -> float | None:
    strikes = sorted(
        leg.strike
        for leg in legs
        if leg.strike is not None and (option_type is None or leg.option_type == option_type)
    )
    if len(strikes) >= 2:
        return round(strikes[-1] - strikes[0], 4)
    return None


def estimate_round_trip_costs(legs: list[OptionLeg]) -> float | None:
    """Approximate round-trip cost: half the spread per leg, both sides."""
    total = 0.0
    found = False
    for leg in legs:
        if leg.entry_bid is None or leg.entry_ask is None:
            continue
        found = True
        half_spread = (leg.entry_ask - leg.entry_bid) / 2.0
        total += half_spread * 2.0  # entry + exit
    if not found:
        return None
    return round(total * _lot(legs), 4)


def _greeks(legs: list[OptionLeg]) -> dict[str, float | None]:
    g = net_greeks(legs)
    return {
        "net_delta": round(g["delta"], 6),
        "net_gamma": round(g["gamma"], 6),
        "net_theta": round(g["theta"], 6),
        "net_vega": round(g["vega"], 6),
    }


def debit_spread_economics(legs: list[OptionLeg], option_type: str) -> StructureEconomics:
    lot = _lot(legs)
    debit = structure_entry_debit(legs)  # per share, positive = net debit
    width = structure_width(legs, option_type)
    greeks = _greeks(legs)
    margin = None
    max_profit = None
    max_loss = None
    breakevens: list[float] = []
    reward_risk = None
    entry_debit = debit
    entry_credit = None

    if debit is not None and width is not None and debit > 0:
        if debit >= width:
            # Debit at/above width is not a valid debit spread.
            max_profit = None
            max_loss = None
        else:
            max_profit = round((width - debit) * lot, 4)
            max_loss = round(debit * lot, 4)
            margin = max_loss
            # Breakeven: long strike +/- debit.
            long_leg = next((leg for leg in legs if leg.side.upper() == "BUY" and leg.strike is not None), None)
            if long_leg is not None and long_leg.strike is not None:
                if option_type == "CALL":
                    breakevens.append(round(long_leg.strike + debit, 4))
                else:
                    breakevens.append(round(long_leg.strike - debit, 4))
            if max_loss:
                reward_risk = round(max_profit / max_loss, 4)
    elif debit is not None and debit <= 0:
        # Not a debit position.
        entry_debit = None
        entry_credit = abs(debit)

    return StructureEconomics(
        entry_debit=entry_debit,
        entry_credit=entry_credit,
        max_profit=max_profit,
        max_loss=max_loss,
        breakevens=breakevens,
        reward_risk=reward_risk,
        margin=margin,
        width=width,
        round_trip_costs=estimate_round_trip_costs(legs),
        liquidity_score=None,
        execution_score=None,
        **greeks,
    )


def long_vol_economics(legs: list[OptionLeg], spot: float | None) -> StructureEconomics:
    lot = _lot(legs)
    debit = structure_entry_debit(legs)
    greeks = _greeks(legs)
    breakevens: list[float] = []
    max_loss = None
    reward_risk = None
    margin = None
    if debit is not None and debit > 0:
        max_loss = round(debit * lot, 4)
        margin = max_loss
        call = next((leg for leg in legs if leg.option_type == "CALL" and leg.strike is not None), None)
        put = next((leg for leg in legs if leg.option_type == "PUT" and leg.strike is not None), None)
        if call is not None and call.strike is not None:
            breakevens.append(round(call.strike + debit, 4))
        if put is not None and put.strike is not None:
            breakevens.append(round(put.strike - debit, 4))
    return StructureEconomics(
        entry_debit=debit if debit and debit > 0 else None,
        entry_credit=None,
        max_profit=None,  # unbounded to the upside for long vol
        max_loss=max_loss,
        breakevens=sorted(breakevens),
        reward_risk=reward_risk,
        margin=margin,
        width=None,
        round_trip_costs=estimate_round_trip_costs(legs),
        liquidity_score=None,
        execution_score=None,
        **greeks,
    )


def iron_butterfly_economics(legs: list[OptionLeg]) -> StructureEconomics:
    lot = _lot(legs)
    net = structure_entry_debit(legs)  # negative => credit received
    greeks = _greeks(legs)
    credit = None
    max_profit = None
    max_loss = None
    breakevens: list[float] = []
    reward_risk = None
    margin = None
    width = structure_width(legs)
    if net is not None and net < 0:
        credit = round(abs(net), 4)
        # Iron butterfly max loss = (wing width - credit) * lot
        wing = None
        body_strikes = [leg.strike for leg in legs if leg.side.upper() == "SELL" and leg.strike is not None]
        wing_strikes = [leg.strike for leg in legs if leg.side.upper() == "BUY" and leg.strike is not None]
        if body_strikes and wing_strikes:
            body = body_strikes[0]
            wing = max(abs((w or body) - body) for w in wing_strikes)
        if wing is not None:
            max_profit = round(credit * lot, 4)
            max_loss = round((wing - credit) * lot, 4)
            margin = max_loss
            lower_strike = min(leg.strike for leg in legs if leg.strike is not None)
            upper_strike = max(leg.strike for leg in legs if leg.strike is not None)
            breakevens = [round(lower_strike + credit, 4), round(upper_strike - credit, 4)]
            if max_loss:
                reward_risk = round(max_profit / max_loss, 4)
    return StructureEconomics(
        entry_debit=None if credit is not None else (net if net and net > 0 else None),
        entry_credit=credit,
        max_profit=max_profit,
        max_loss=max_loss,
        breakevens=sorted(breakevens),
        reward_risk=reward_risk,
        margin=margin,
        width=width,
        round_trip_costs=estimate_round_trip_costs(legs),
        liquidity_score=None,
        execution_score=None,
        **greeks,
    )


def long_butterfly_economics(legs: list[OptionLeg], option_type: str) -> StructureEconomics:
    lot = _lot(legs)
    debit = structure_entry_debit(legs)
    greeks = _greeks(legs)
    max_profit = None
    max_loss = None
    breakevens: list[float] = []
    reward_risk = None
    margin = None
    strikes = sorted({leg.strike for leg in legs if leg.strike is not None})
    wing = None
    if len(strikes) == 3:
        wing = round(strikes[1] - strikes[0], 4)
    if debit is not None and debit > 0 and wing is not None:
        max_profit = round((wing - debit) * lot, 4)
        max_loss = round(debit * lot, 4)
        margin = max_loss
        if option_type == "CALL":
            breakevens = [round(strikes[0] + debit, 4), round(strikes[2] - debit, 4)]
        else:
            breakevens = [round(strikes[2] - debit, 4), round(strikes[0] + debit, 4)]
        if max_loss:
            reward_risk = round(max_profit / max_loss, 4)
    return StructureEconomics(
        entry_debit=debit if debit and debit > 0 else None,
        entry_credit=None,
        max_profit=max_profit,
        max_loss=max_loss,
        breakevens=sorted(breakevens),
        reward_risk=reward_risk,
        margin=margin,
        width=wing,
        round_trip_costs=estimate_round_trip_costs(legs),
        liquidity_score=None,
        execution_score=None,
        **greeks,
    )


def calendar_economics(legs: list[OptionLeg]) -> StructureEconomics:
    lot = _lot(legs)
    net = structure_entry_debit(legs)
    greeks = _greeks(legs)
    debit = net if net is not None and net > 0 else None
    max_loss = round(debit * lot, 4) if debit is not None else None
    return StructureEconomics(
        entry_debit=debit,
        entry_credit=None if debit is not None else (abs(net) if net else None),
        max_profit=None,  # calendar payoff is non-linear; not a fixed ledger value
        max_loss=max_loss,
        breakevens=[],
        reward_risk=None,
        margin=max_loss,
        width=None,
        round_trip_costs=estimate_round_trip_costs(legs),
        liquidity_score=None,
        execution_score=None,
        **greeks,
    )


def breakeven_move(legs: list[OptionLeg], spot: float | None) -> float | None:
    """Smallest absolute underlying move that reaches a breakeven."""
    if spot is None:
        return None
    distances = [abs(be - spot) for be in _all_breakevens(legs)]
    return round(min(distances), 4) if distances else None


def _all_breakevens(legs: list[OptionLeg]) -> list[float]:
    # Reuse the per-structure compute by type inspection.
    types = {leg.option_type for leg in legs}
    sides = {leg.side.upper() for leg in legs}
    if types == {"CALL"} or types == {"PUT"}:
        opt = next(iter(types))
        if len(legs) == 2 and sides == {"BUY", "SELL"}:
            return debit_spread_economics(legs, opt).breakevens
        if len(legs) == 3:
            return long_butterfly_economics(legs, opt).breakevens
    if types == {"CALL", "PUT"}:
        sells = sum(1 for leg in legs if leg.side.upper() == "SELL")
        if sells == 0 and len(legs) == 2:
            return long_vol_economics(legs, None).breakevens
        if sells >= 2:
            return iron_butterfly_economics(legs).breakevens
    return []
