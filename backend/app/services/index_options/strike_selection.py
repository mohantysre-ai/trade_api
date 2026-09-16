"""Deterministic strike/leg selection helpers for multi-leg structures.

All construction is derived from the live chain: strikes, delta, distance from
spot, expected move, liquidity and spread. Nothing is hardcoded. When the chain
cannot supply a required leg the builder returns ``None`` and the caller emits
``DATA_INCOMPLETE`` rather than fabricating a strike.
"""

from __future__ import annotations

from typing import Any

from .config import MAX_LEG_SPREAD_PCT, MIN_LEG_OI, MIN_LEG_VOLUME
from .legs import OptionLeg, leg_from_chain_contract


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _quote_ok(row: dict[str, Any]) -> tuple[bool, str]:
    bid = _float(row.get("bestBid"))
    ask = _float(row.get("bestAsk"))
    if bid is None or ask is None:
        return False, "MISSING_QUOTE"
    if ask < bid:
        return False, "CROSSED_QUOTE"
    if bid <= 0 or ask <= 0:
        return False, "NON_POSITIVE_QUOTE"
    if (ask - bid) / ask * 100.0 > MAX_LEG_SPREAD_PCT:
        return False, "WIDE_SPREAD"
    volume = row.get("volume")
    if volume is not None and int(volume) < MIN_LEG_VOLUME:
        return False, "LOW_VOLUME"
    oi = row.get("oi")
    if MIN_LEG_OI and oi is not None and int(oi) < MIN_LEG_OI:
        return False, "LOW_OI"
    return True, "OK"


def chain_by_type(
    chain: list[dict[str, Any]], option_type: str
) -> list[dict[str, Any]]:
    rows = []
    for row in chain or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("optionType") or "").upper() != option_type:
            continue
        if _float(row.get("strike")) is None:
            continue
        rows.append(row)
    rows.sort(key=lambda r: _float(r.get("strike")) or 0.0)
    return rows


def executable_rows(
    chain: list[dict[str, Any]], option_type: str
) -> list[dict[str, Any]]:
    return [row for row in chain_by_type(chain, option_type) if _quote_ok(row)[0]]


def atm_row(
    chain: list[dict[str, Any]], option_type: str, spot: float
) -> dict[str, Any] | None:
    rows = executable_rows(chain, option_type)
    if not rows:
        return None
    return min(rows, key=lambda r: abs((_float(r.get("strike")) or 0.0) - spot))


def nearest_strike(
    chain: list[dict[str, Any]], option_type: str, target: float
) -> dict[str, Any] | None:
    rows = executable_rows(chain, option_type)
    if not rows:
        return None
    return min(rows, key=lambda r: abs((_float(r.get("strike")) or 0.0) - target))


def pick_by_delta(
    chain: list[dict[str, Any]],
    option_type: str,
    target_delta: float,
    *,
    side: str,
) -> dict[str, Any] | None:
    """Pick the executable row whose delta is closest to ``target_delta``.

    ``target_delta`` is always expressed as a positive magnitude; the sign is
    applied from the real chain delta so calls/puts are handled uniformly.
    """
    rows = [
        row
        for row in executable_rows(chain, option_type)
        if _float(row.get("delta")) is not None
    ]
    if not rows:
        return None
    want = abs(target_delta)
    return min(rows, key=lambda r: abs(abs(_float(r.get("delta")) or 0.0) - want))


def _mk_leg(
    row: dict[str, Any],
    *,
    strategy_position_id: str,
    leg_id: str,
    side: str,
    expiry: str | None,
    qty: int = 1,
) -> OptionLeg | None:
    return leg_from_chain_contract(
        row,
        strategy_position_id=strategy_position_id,
        leg_id=leg_id,
        side=side,
        qty=qty,
        expiry=expiry,
    )


def build_debit_spread_legs(
    chain: list[dict[str, Any]],
    *,
    option_type: str,
    spot: float,
    expected_move: float | None,
    strategy_position_id: str,
    expiry: str | None,
    width_target: float | None = None,
) -> tuple[OptionLeg, OptionLeg] | None:
    """BUY near-the-money, SELL a further out-of-the-money leg of ``option_type``.

    For CALL debit (bull): buy the lower strike, sell the higher strike.
    For PUT debit (bear): buy the higher strike, sell the lower strike.
    Width is derived from expected move when available, else one chain step.
    """
    rows = executable_rows(chain, option_type)
    if len(rows) < 2:
        return None
    strikes = [_float(r.get("strike")) or 0.0 for r in rows]
    step = min((b - a for a, b in zip(strikes, strikes[1:]) if b > a), default=None)
    target_width = width_target or expected_move or (step or 0.0)
    if target_width <= 0:
        return None

    if option_type == "CALL":
        long_row = atm_row(chain, "CALL", spot)
        if long_row is None:
            return None
        long_strike = _float(long_row.get("strike")) or 0.0
        short_target = long_strike + target_width
        short_row = nearest_strike(chain, "CALL", short_target)
        if short_row is None or (_float(short_row.get("strike")) or 0.0) <= long_strike:
            return None
        long_leg = _mk_leg(
            long_row,
            strategy_position_id=strategy_position_id,
            leg_id="L1",
            side="BUY",
            expiry=expiry,
        )
        short_leg = _mk_leg(
            short_row,
            strategy_position_id=strategy_position_id,
            leg_id="S1",
            side="SELL",
            expiry=expiry,
        )
    else:
        long_row = atm_row(chain, "PUT", spot)
        if long_row is None:
            return None
        long_strike = _float(long_row.get("strike")) or 0.0
        short_target = long_strike - target_width
        short_row = nearest_strike(chain, "PUT", short_target)
        if short_row is None or (_float(short_row.get("strike")) or 0.0) >= long_strike:
            return None
        long_leg = _mk_leg(
            long_row,
            strategy_position_id=strategy_position_id,
            leg_id="L1",
            side="BUY",
            expiry=expiry,
        )
        short_leg = _mk_leg(
            short_row,
            strategy_position_id=strategy_position_id,
            leg_id="S1",
            side="SELL",
            expiry=expiry,
        )

    if long_leg is None or short_leg is None:
        return None
    return long_leg, short_leg


def build_straddle_legs(
    chain: list[dict[str, Any]],
    *,
    spot: float,
    strategy_position_id: str,
    expiry: str | None,
) -> tuple[OptionLeg, OptionLeg] | None:
    call_row = atm_row(chain, "CALL", spot)
    put_row = atm_row(chain, "PUT", spot)
    if call_row is None or put_row is None:
        return None
    # Prefer a shared strike when the chain offers both at the same strike.
    call_strike = _float(call_row.get("strike"))
    put_strike = _float(put_row.get("strike"))
    if call_strike != put_strike:
        shared = min(
            (
                r
                for r in executable_rows(chain, "CALL")
                if _float(r.get("strike")) == put_strike
            ),
            key=lambda r: 0,
            default=None,
        )
        if shared is not None:
            call_row = shared
    call_leg = _mk_leg(
        call_row,
        strategy_position_id=strategy_position_id,
        leg_id="C1",
        side="BUY",
        expiry=expiry,
    )
    put_leg = _mk_leg(
        put_row,
        strategy_position_id=strategy_position_id,
        leg_id="P1",
        side="BUY",
        expiry=expiry,
    )
    if call_leg is None or put_leg is None:
        return None
    return call_leg, put_leg


def build_strangle_legs(
    chain: list[dict[str, Any]],
    *,
    spot: float,
    strategy_position_id: str,
    expiry: str | None,
) -> tuple[OptionLeg, OptionLeg] | None:
    call_row = pick_by_delta(chain, "CALL", 0.25, side="BUY")
    put_row = pick_by_delta(chain, "PUT", 0.25, side="BUY")
    if call_row is None or put_row is None:
        return None
    call_strike = _float(call_row.get("strike")) or 0.0
    put_strike = _float(put_row.get("strike")) or 0.0
    if call_strike <= spot or put_strike >= spot:
        return None
    call_leg = _mk_leg(
        call_row,
        strategy_position_id=strategy_position_id,
        leg_id="C1",
        side="BUY",
        expiry=expiry,
    )
    put_leg = _mk_leg(
        put_row,
        strategy_position_id=strategy_position_id,
        leg_id="P1",
        side="BUY",
        expiry=expiry,
    )
    if call_leg is None or put_leg is None:
        return None
    return call_leg, put_leg


def build_iron_butterfly_legs(
    chain: list[dict[str, Any]],
    *,
    spot: float,
    strategy_position_id: str,
    expiry: str | None,
    expected_move: float | None,
) -> list[OptionLeg] | None:
    call_body = atm_row(chain, "CALL", spot)
    put_body = atm_row(chain, "PUT", spot)
    if call_body is None or put_body is None:
        return None
    body_strike = _float(put_body.get("strike")) or spot
    width = expected_move or 0.0
    if width <= 0:
        return None
    put_wing = nearest_strike(chain, "PUT", body_strike - width)
    call_wing = nearest_strike(chain, "CALL", body_strike + width)
    if put_wing is None or call_wing is None:
        return None
    if (_float(put_wing.get("strike")) or 0.0) >= body_strike:
        return None
    if (_float(call_wing.get("strike")) or 0.0) <= body_strike:
        return None
    legs = [
        _mk_leg(
            call_body,
            strategy_position_id=strategy_position_id,
            leg_id="SB_C",
            side="SELL",
            expiry=expiry,
        ),
        _mk_leg(
            put_body,
            strategy_position_id=strategy_position_id,
            leg_id="SB_P",
            side="SELL",
            expiry=expiry,
        ),
        _mk_leg(
            put_wing,
            strategy_position_id=strategy_position_id,
            leg_id="WL_P",
            side="BUY",
            expiry=expiry,
        ),
        _mk_leg(
            call_wing,
            strategy_position_id=strategy_position_id,
            leg_id="WL_C",
            side="BUY",
            expiry=expiry,
        ),
    ]
    if any(leg is None for leg in legs):
        return None
    return legs  # type: ignore[return-value]


def build_long_butterfly_legs(
    chain: list[dict[str, Any]],
    *,
    option_type: str,
    target: float,
    strategy_position_id: str,
    expiry: str | None,
    width: float | None,
) -> list[OptionLeg] | None:
    """BUY 1 lower, SELL 2 middle, BUY 1 upper — symmetric around ``target``."""
    rows = executable_rows(chain, option_type)
    if len(rows) < 3:
        return None
    strikes = sorted({_float(r.get("strike")) or 0.0 for r in rows})
    step = min((b - a for a, b in zip(strikes, strikes[1:]) if b > a), default=None)
    wing = width or step
    if not wing or wing <= 0:
        return None
    middle = nearest_strike(chain, option_type, target)
    if middle is None:
        return None
    mid_strike = _float(middle.get("strike")) or 0.0
    lower = nearest_strike(chain, option_type, mid_strike - wing)
    upper = nearest_strike(chain, option_type, mid_strike + wing)
    if lower is None or upper is None:
        return None
    lo = _float(lower.get("strike")) or 0.0
    up = _float(upper.get("strike")) or 0.0
    if not (lo < mid_strike < up):
        return None
    if abs((mid_strike - lo) - (up - mid_strike)) > max(1e-6, wing * 0.5):
        return None
    for row in (lower, upper):
        if _float(row.get("strike")) == mid_strike:
            return None
    legs = [
        _mk_leg(
            lower,
            strategy_position_id=strategy_position_id,
            leg_id="L1",
            side="BUY",
            expiry=expiry,
        ),
        _mk_leg(
            middle,
            strategy_position_id=strategy_position_id,
            leg_id="M1",
            side="SELL",
            qty=2,
            expiry=expiry,
        ),
        _mk_leg(
            upper,
            strategy_position_id=strategy_position_id,
            leg_id="U1",
            side="BUY",
            expiry=expiry,
        ),
    ]
    if any(leg is None for leg in legs):
        return None
    return legs  # type: ignore[return-value]


def build_calendar_legs(
    near_chain: list[dict[str, Any]],
    far_chain: list[dict[str, Any]],
    *,
    option_type: str,
    spot: float,
    strategy_position_id: str,
    near_expiry: str | None,
    far_expiry: str | None,
) -> list[OptionLeg] | None:
    near_row = atm_row(near_chain, option_type, spot)
    if near_row is None:
        return None
    strike = _float(near_row.get("strike")) or 0.0
    far_row = nearest_strike(far_chain, option_type, strike)
    if far_row is None or _float(far_row.get("strike")) != strike:
        return None
    near_leg = _mk_leg(
        near_row,
        strategy_position_id=strategy_position_id,
        leg_id="NEAR",
        side="SELL",
        expiry=near_expiry,
    )
    far_leg = _mk_leg(
        far_row,
        strategy_position_id=strategy_position_id,
        leg_id="FAR",
        side="BUY",
        expiry=far_expiry,
    )
    if near_leg is None or far_leg is None:
        return None
    return [near_leg, far_leg]


def build_diagonal_legs(
    near_chain: list[dict[str, Any]],
    far_chain: list[dict[str, Any]],
    *,
    option_type: str,
    spot: float,
    strategy_position_id: str,
    near_expiry: str | None,
    far_expiry: str | None,
    expected_move: float | None,
) -> list[OptionLeg] | None:
    """SELL nearer OTM, BUY farther OTM of the same type on a later expiry."""
    near_row = pick_by_delta(near_chain, option_type, 0.35, side="SELL")
    if near_row is None:
        near_row = atm_row(near_chain, option_type, spot)
    if near_row is None:
        return None
    near_strike = _float(near_row.get("strike")) or spot
    offset = expected_move or 0.0
    if option_type == "CALL":
        far_target = near_strike + offset
    else:
        far_target = near_strike - offset
    far_row = nearest_strike(far_chain, option_type, far_target)
    if far_row is None:
        return None
    if _float(far_row.get("expiry")) is None and not far_expiry:
        return None
    near_leg = _mk_leg(
        near_row,
        strategy_position_id=strategy_position_id,
        leg_id="NEAR",
        side="SELL",
        expiry=near_expiry,
    )
    far_leg = _mk_leg(
        far_row,
        strategy_position_id=strategy_position_id,
        leg_id="FAR",
        side="BUY",
        expiry=far_expiry,
    )
    if near_leg is None or far_leg is None:
        return None
    return [near_leg, far_leg]
