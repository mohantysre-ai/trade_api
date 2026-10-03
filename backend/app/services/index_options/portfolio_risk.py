"""Portfolio-level risk checks for index-options strategies."""

from __future__ import annotations

from typing import Any


def check_portfolio_limits(position: dict[str, Any], open_positions: list[dict[str, Any]]) -> tuple[bool, str]:
    # Keep this compatibility helper aligned with the active engine limit.
    # The authoritative Quant V2 governor still owns Greeks/stress/CVaR.
    from ..index_options_engine import MAX_CONCURRENT_TRADES

    if len(open_positions) >= MAX_CONCURRENT_TRADES:
        return False, "MAX_CONCURRENT_TRADES_REACHED"
    return True, "OK"


def aggregate_greeks(positions: list[dict[str, Any]]) -> dict[str, float]:
    total_delta = 0.0
    total_gamma = 0.0
    total_theta = 0.0
    total_vega = 0.0
    for pos in positions:
        legs = pos.get("legs") or [pos]
        for leg in legs:
            d = leg.get("delta")
            g = leg.get("gamma")
            t = leg.get("theta")
            v = leg.get("vega")
            if d is not None:
                total_delta += float(d)
            if g is not None:
                total_gamma += float(g)
            if t is not None:
                total_theta += float(t)
            if v is not None:
                total_vega += float(v)
    return {
        "delta": total_delta,
        "gamma": total_gamma,
        "theta": total_theta,
        "vega": total_vega,
    }
