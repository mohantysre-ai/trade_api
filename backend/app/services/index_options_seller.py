"""Defined-risk index-option premium-selling strategy builder.

The seller sleeve is deliberately independent from the long-premium breakout
engine.  It only constructs executable vertical credit spreads or iron
condors; naked short options are never emitted.  All economics use short-leg
bid and hedge-leg ask so a paper fill cannot manufacture credit from LTPs.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time as dt_time
from statistics import median
from typing import Any

from .angel_index_options import IST_ZONE, _expiry, _float


SELLER_MIN_SCORE = 82.0
SELLER_ENTRY_START = dt_time(9, 45)
SELLER_ENTRY_CUTOFF = dt_time(14, 30)
SELLER_EXPIRY_DAY_CUTOFF = dt_time(13, 30)
MIN_CREDIT_TO_RISK = 0.20
MIN_IV_EDGE_POINTS = 0.75
MIN_IV_EDGE_RATIO = 1.05
MAX_LEG_SPREAD_PCT = 2.0
MIN_SHORT_DELTA = 0.15
MAX_SHORT_DELTA = 0.40
ESTIMATED_COST_PER_ORDER_INR = 20.0


def _leg_spread(row: dict[str, Any]) -> float | None:
    bid, ask = _float(row.get("bestBid")), _float(row.get("bestAsk"))
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    return ((ask - bid) / mid * 100.0) if mid > 0 else None


def _usable(row: dict[str, Any]) -> bool:
    spread = _leg_spread(row)
    return bool(
        row.get("symbol")
        and (_float(row.get("volume")) or 0) > 0
        and (_float(row.get("lotSize")) or 0) >= 1
        and _float(row.get("delta")) is not None
        and _float(row.get("iv")) is not None
        and spread is not None
        and spread <= MAX_LEG_SPREAD_PCT
    )


def _pick_short(rows: list[dict[str, Any]], spot: float, option_type: str) -> dict[str, Any] | None:
    wanted = []
    for row in rows:
        if row.get("optionType") != option_type or not _usable(row):
            continue
        strike, delta = _float(row.get("strike")), abs(_float(row.get("delta")) or 0)
        if strike is None or not (MIN_SHORT_DELTA <= delta <= MAX_SHORT_DELTA):
            continue
        if option_type == "CALL" and strike <= spot:
            continue
        if option_type == "PUT" and strike >= spot:
            continue
        wanted.append(row)
    return min(wanted, key=lambda row: abs(abs(_float(row.get("delta")) or 0) - 0.25), default=None)


def _pick_wing(rows: list[dict[str, Any]], short: dict[str, Any], option_type: str) -> dict[str, Any] | None:
    short_strike = _float(short.get("strike"))
    if short_strike is None:
        return None
    wings = []
    for row in rows:
        strike = _float(row.get("strike"))
        if row.get("optionType") != option_type or strike is None or not _usable(row):
            continue
        farther = strike > short_strike if option_type == "CALL" else strike < short_strike
        if farther:
            wings.append(row)
    if not wings:
        return None
    return min(wings, key=lambda row: abs((_float(row.get("strike")) or short_strike) - short_strike))


def _leg(row: dict[str, Any], action: str, role: str) -> dict[str, Any]:
    entry = _float(row.get("bestBid" if action == "SELL" else "bestAsk"))
    return {
        "action": action,
        "role": role,
        "symbol": row.get("symbol"),
        "token": row.get("token"),
        "exchange": row.get("exchange"),
        "optionType": row.get("optionType"),
        "strike": _float(row.get("strike")),
        "entryPrice": round(entry, 2) if entry is not None else None,
        "ltp": _float(row.get("ltp")),
        "close": _float(row.get("close")),
        "bestBid": _float(row.get("bestBid")),
        "bestAsk": _float(row.get("bestAsk")),
        "delta": _float(row.get("delta")),
        "gamma": _float(row.get("gamma")),
        "theta": _float(row.get("theta")),
        "vega": _float(row.get("vega")),
        "iv": _float(row.get("iv")),
        "oi": _float(row.get("oi")),
        "oiChange": _float(row.get("oiChange")),
        "spreadPct": round(_leg_spread(row) or 0.0, 3),
        "lotSize": int(_float(row.get("lotSize")) or 0),
    }


def _structure_ready(structure: dict[str, Any], *, neutral: bool) -> bool | None:
    bar_count = int(structure.get("barCount") or 0)
    status = str(structure.get("status") or "")
    if bar_count < 20 or status == "DATA_INCOMPLETE":
        return None
    if neutral:
        last, high, low = (_float(structure.get(name)) for name in ("last", "orbHigh", "orbLow"))
        return bool(status == "NO_BREAKOUT" and last is not None and high is not None and low is not None and low < last < high)
    return bool(status == "CONFIRMED" and structure.get("direction") in {"CALL", "PUT"})


def _time_gate(expiry_value: Any, now: datetime) -> tuple[bool | None, dict[str, Any]]:
    expiry = _expiry(expiry_value)
    if expiry is None:
        return None, {"reason": "EXPIRY_UNAVAILABLE"}
    clock = now.astimezone(IST_ZONE)
    days = (expiry - clock.date()).days
    cutoff = SELLER_EXPIRY_DAY_CUTOFF if days == 0 else SELLER_ENTRY_CUTOFF
    allowed = 0 <= days <= 14 and SELLER_ENTRY_START <= clock.time().replace(tzinfo=None) <= cutoff
    reason = "SELLER_WINDOW_OPEN" if allowed else "EXPIRY_GAMMA_CUTOFF" if days == 0 and clock.time().replace(tzinfo=None) > cutoff else "SELLER_TIME_WINDOW_CLOSED"
    return allowed, {"reason": reason, "daysToExpiry": days, "entryCutoffIst": cutoff.strftime("%H:%M")}


def _wall_ok(short: dict[str, Any]) -> bool | None:
    oi, change = _float(short.get("oi")), _float(short.get("oiChange"))
    premium, close = _float(short.get("ltp")), _float(short.get("close"))
    if oi is None or change is None or premium is None or close is None or close <= 0:
        return None
    return oi > 0 and change > 0 and premium <= close


def _setup_from_legs(
    *,
    strategy_type: str,
    bias: str,
    legs: list[dict[str, Any]],
    spot: float,
    structure: dict[str, Any],
    breadth: dict[str, Any],
    futures_oi: dict[str, Any],
    vix: float | None,
    vix_regime: str | None,
    expiry_value: Any,
    provider_live: bool,
    now: datetime,
) -> dict[str, Any]:
    sell_legs = [leg for leg in legs if leg["action"] == "SELL"]
    buy_legs = [leg for leg in legs if leg["action"] == "BUY"]
    neutral = strategy_type == "IRON_CONDOR"
    credit = sum(_float(leg.get("entryPrice")) or 0 for leg in sell_legs) - sum(_float(leg.get("entryPrice")) or 0 for leg in buy_legs)
    call_strikes = sorted(_float(leg.get("strike")) or 0 for leg in legs if leg.get("optionType") == "CALL")
    put_strikes = sorted(_float(leg.get("strike")) or 0 for leg in legs if leg.get("optionType") == "PUT")
    widths = []
    if len(call_strikes) == 2:
        widths.append(call_strikes[1] - call_strikes[0])
    if len(put_strikes) == 2:
        widths.append(put_strikes[1] - put_strikes[0])
    width = max(widths, default=0.0)
    lots = {int(_float(leg.get("lotSize")) or 0) for leg in legs}
    lot_size = next(iter(lots), 0) if len(lots) == 1 else 0
    estimated_cost = len(legs) * 2 * ESTIMATED_COST_PER_ORDER_INR
    gross_profit_lot = credit * lot_size
    gross_loss_lot = max(0.0, width - credit) * lot_size
    net_profit_lot = max(0.0, gross_profit_lot - estimated_cost)
    max_loss_lot = gross_loss_lot + estimated_cost
    max_loss = max_loss_lot / lot_size if lot_size > 0 else 0.0
    credit_to_risk = net_profit_lot / max_loss_lot if max_loss_lot > 0 else 0.0
    short_ivs = [_float(leg.get("iv")) for leg in sell_legs]
    short_ivs = [value for value in short_ivs if value is not None]
    short_iv = median(short_ivs) if short_ivs else None
    iv_edge = short_iv - vix if short_iv is not None and vix is not None else None
    iv_ratio = short_iv / vix if short_iv is not None and vix and vix > 0 else None
    volatility_edge = bool(iv_edge is not None and iv_ratio is not None and iv_edge >= MIN_IV_EDGE_POINTS and iv_ratio >= MIN_IV_EDGE_RATIO)
    carry_theta = sum(-(_float(leg.get("theta")) or 0) for leg in sell_legs) + sum((_float(leg.get("theta")) or 0) for leg in buy_legs)
    net_gamma = sum(-(_float(leg.get("gamma")) or 0) for leg in sell_legs) + sum((_float(leg.get("gamma")) or 0) for leg in buy_legs)
    gamma_cap = max(0.001, 75.0 / spot)
    leg_spreads = [_float(leg.get("spreadPct")) for leg in legs]
    max_spread = max((value for value in leg_spreads if value is not None), default=math.inf)
    contract_ok = bool(credit > 0 and len(lots) == 1 and next(iter(lots), 0) > 0 and max_spread <= MAX_LEG_SPREAD_PCT)

    raw_breadth = _float(breadth.get("score"))
    coverage = _float(breadth.get("coveragePct"))
    directional_score = _float(breadth.get("directionalScore"))
    if neutral:
        breadth_ok = None if raw_breadth is None or coverage is None else abs(raw_breadth) <= 0.25 and coverage >= 90.0
    else:
        breadth_ok = None if directional_score is None or coverage is None else directional_score >= 0.35 and coverage >= 90.0
    price_change = _float(futures_oi.get("priceChangePct"))
    if neutral:
        futures_ok = None if price_change is None else abs(price_change) <= 0.50
    else:
        futures_ok = futures_oi.get("aligned")
    wall_checks = [_wall_ok(leg) for leg in sell_legs]
    wall_ok = None if any(value is None for value in wall_checks) else all(value is True for value in wall_checks)
    structure_ok = _structure_ready(structure, neutral=neutral)
    time_ok, time_evidence = _time_gate(expiry_value, now)
    defined_risk = width > 0 and max_loss > 0 and credit_to_risk >= MIN_CREDIT_TO_RISK
    theta_ok = carry_theta > 0 and abs(net_gamma) <= gamma_cap

    atr = _float(structure.get("atr5m"))
    short_call = next((leg for leg in sell_legs if leg.get("optionType") == "CALL"), None)
    short_put = next((leg for leg in sell_legs if leg.get("optionType") == "PUT"), None)
    lower_buffer = (spot - (_float(short_put.get("strike")) or spot)) if short_put else None
    upper_buffer = ((_float(short_call.get("strike")) or spot) - spot) if short_call else None
    buffers = [value for value in (lower_buffer, upper_buffer) if value is not None]
    min_buffer_atr = min((value / atr for value in buffers), default=None) if atr and atr > 0 else None
    tail_ok = min_buffer_atr is not None and min_buffer_atr >= (1.0 if neutral else 0.75)

    gates = {
        "fresh": provider_live,
        "structure": structure_ok,
        "futuresRegime": futures_ok,
        "optionChain": wall_ok,
        "breadth": breadth_ok,
        "volatilityEdge": volatility_edge if iv_edge is not None else None,
        "contractEconomics": contract_ok,
        "definedRisk": defined_risk,
        "thetaCarry": theta_ok,
        "tailBuffer": tail_ok,
        "timeWindow": time_ok,
    }
    score_values = {
        "structure": 100.0 if structure_ok else 0.0 if structure_ok is False else None,
        "futuresRegime": 100.0 if futures_ok else 0.0 if futures_ok is False else None,
        "optionChain": 100.0 if wall_ok else 0.0 if wall_ok is False else None,
        "breadth": 100.0 if breadth_ok else 0.0 if breadth_ok is False else None,
        "volatilityEdge": min(100.0, 70.0 + max(0.0, (iv_edge or 0) - MIN_IV_EDGE_POINTS) * 10.0) if iv_edge is not None else None,
        "contract": min(100.0, credit_to_risk / MIN_CREDIT_TO_RISK * 80.0) if max_loss > 0 else 0.0,
        "theta": 100.0 if theta_ok else 0.0,
    }
    short_put_strike = _float(short_put.get("strike")) if short_put else None
    short_call_strike = _float(short_call.get("strike")) if short_call else None
    lower_break_even = short_put_strike - credit if short_put_strike is not None else None
    upper_break_even = short_call_strike + credit if short_call_strike is not None else None
    return {
        "strategyMode": "SELL_PREMIUM",
        "strategyType": strategy_type,
        "bias": bias,
        "direction": bias,
        "expiry": str(expiry_value) if expiry_value else None,
        "legs": legs,
        "primaryContract": sell_legs[0] if sell_legs else None,
        "scores": score_values,
        "gates": gates,
        "risk": {
            "entryCredit": round(credit, 2),
            "wingWidth": round(width, 2),
            "grossMaxProfitPerLot": round(gross_profit_lot, 2),
            "estimatedRoundTripCosts": round(estimated_cost, 2),
            "maxProfitPerLot": round(net_profit_lot, 2),
            "maxLossPerUnit": round(max_loss, 2),
            "maxLossPerLot": round(max_loss_lot, 2),
            "creditToRisk": round(credit_to_risk, 3),
            "lowerBreakEven": round(lower_break_even, 2) if lower_break_even is not None else None,
            "upperBreakEven": round(upper_break_even, 2) if upper_break_even is not None else None,
            "shortPutStrike": short_put_strike,
            "shortCallStrike": short_call_strike,
            "minimumBufferAtr": round(min_buffer_atr, 3) if min_buffer_atr is not None else None,
            "profitTakePct": 50.0,
            "lossBudgetPctOfMaxLoss": 35.0,
        },
        "gateEvidence": {
            "structure": {"aligned": structure_ok, "status": structure.get("status"), "barCount": structure.get("barCount")},
            "futuresRegime": {**futures_oi, "aligned": futures_ok},
            "optionChain": {"aligned": wall_ok, "reason": "TWO_SIDED_OI_UP_PREMIUM_DOWN_WRITING" if neutral else "DIRECTIONAL_OI_UP_PREMIUM_DOWN_WRITING",
                            "shortLegWalls": wall_checks},
            "breadth": {**breadth, "aligned": breadth_ok, "sellerMode": "NEUTRAL" if neutral else "DIRECTIONAL"},
            "volatilityEdge": {"aligned": volatility_edge if iv_edge is not None else None, "shortIv": round(short_iv, 3) if short_iv is not None else None,
                               "indiaVix": vix, "ivEdgePoints": round(iv_edge, 3) if iv_edge is not None else None,
                               "ivToVix": round(iv_ratio, 3) if iv_ratio is not None else None, "vixRegime": vix_regime},
            "contractEconomics": {"aligned": contract_ok, "maxLegSpreadPct": round(max_spread, 3) if math.isfinite(max_spread) else None,
                                  "entryBasis": "SELL_BID_BUY_ASK"},
            "definedRisk": {"aligned": defined_risk, "creditToRisk": round(credit_to_risk, 3), "minimum": MIN_CREDIT_TO_RISK,
                            "maxLossPerLot": round(max_loss_lot, 2), "netMaxProfitPerLot": round(net_profit_lot, 2),
                            "estimatedRoundTripCosts": round(estimated_cost, 2)},
            "thetaCarry": {"aligned": theta_ok, "netTheta": round(carry_theta, 4), "netGamma": round(net_gamma, 6), "gammaCap": round(gamma_cap, 6)},
            "tailBuffer": {"aligned": tail_ok, "minimumBufferAtr": round(min_buffer_atr, 3) if min_buffer_atr is not None else None,
                           "minimum": 1.0 if neutral else 0.75},
            "timeWindow": {"aligned": time_ok, **time_evidence},
        },
        "dataLimitations": [name for name, value in gates.items() if value is None],
    }


def build_defined_risk_seller_setup(
    *,
    chain: list[dict[str, Any]],
    spot: float | None,
    expiry_value: Any,
    structure: dict[str, Any],
    breadth_neutral: dict[str, Any],
    breadth_directional: dict[str, Any],
    futures_oi: dict[str, Any],
    directional_oi_aligned: bool | None,
    vix: float | None,
    vix_regime: str | None,
    provider_live: bool,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Choose one auditable seller structure, preferring confirmed direction."""
    if spot is None or spot <= 0 or not chain:
        return None
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    direction = structure.get("direction")
    if direction == "CALL":
        short = _pick_short(chain, spot, "PUT")
        wing = _pick_wing(chain, short, "PUT") if short else None
        if short and wing:
            fut = {**futures_oi, "aligned": directional_oi_aligned}
            return _setup_from_legs(
                strategy_type="BULL_PUT_CREDIT_SPREAD", bias="BULLISH",
                legs=[_leg(short, "SELL", "SHORT_PUT"), _leg(wing, "BUY", "LONG_PUT_HEDGE")],
                spot=spot, structure=structure, breadth=breadth_directional, futures_oi=fut,
                vix=vix, vix_regime=vix_regime, expiry_value=expiry_value,
                provider_live=provider_live, now=clock,
            )
    elif direction == "PUT":
        short = _pick_short(chain, spot, "CALL")
        wing = _pick_wing(chain, short, "CALL") if short else None
        if short and wing:
            fut = {**futures_oi, "aligned": directional_oi_aligned}
            return _setup_from_legs(
                strategy_type="BEAR_CALL_CREDIT_SPREAD", bias="BEARISH",
                legs=[_leg(short, "SELL", "SHORT_CALL"), _leg(wing, "BUY", "LONG_CALL_HEDGE")],
                spot=spot, structure=structure, breadth=breadth_directional, futures_oi=fut,
                vix=vix, vix_regime=vix_regime, expiry_value=expiry_value,
                provider_live=provider_live, now=clock,
            )

    if str(structure.get("status") or "") != "NO_BREAKOUT":
        return None
    short_call = _pick_short(chain, spot, "CALL")
    short_put = _pick_short(chain, spot, "PUT")
    long_call = _pick_wing(chain, short_call, "CALL") if short_call else None
    long_put = _pick_wing(chain, short_put, "PUT") if short_put else None
    if not all((short_call, short_put, long_call, long_put)):
        return None
    return _setup_from_legs(
        strategy_type="IRON_CONDOR", bias="NEUTRAL",
        legs=[
            _leg(short_put, "SELL", "SHORT_PUT"), _leg(long_put, "BUY", "LONG_PUT_HEDGE"),
            _leg(short_call, "SELL", "SHORT_CALL"), _leg(long_call, "BUY", "LONG_CALL_HEDGE"),
        ],
        spot=spot, structure=structure, breadth=breadth_neutral, futures_oi=futures_oi,
        vix=vix, vix_regime=vix_regime, expiry_value=expiry_value,
        provider_live=provider_live, now=clock,
    )
