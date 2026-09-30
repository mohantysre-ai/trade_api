from app.services.index_options.strike_selection import build_straddle_legs


def _contract(option_type: str, strike: int) -> dict:
    suffix = "CE" if option_type == "CALL" else "PE"
    return {
        "symbol": f"SENSEX{strike}{suffix}",
        "token": str(strike),
        "exchange": "BFO",
        "optionType": option_type,
        "strike": strike,
        "expiry": "2026-10-01",
        "bestBid": 100.0,
        "bestAsk": 101.0,
        "volume": 1000,
    }


def test_straddle_uses_nearest_shared_executable_strike():
    chain = [
        _contract("CALL", 73100),
        _contract("PUT", 72000),
        _contract("PUT", 73100),
    ]

    legs = build_straddle_legs(
        chain,
        spot=72647.32,
        strategy_position_id="SENSEX-STRADDLE",
        expiry="2026-10-01",
    )

    assert legs is not None
    assert legs[0].strike == legs[1].strike == 73100


def test_straddle_requires_a_shared_executable_strike():
    chain = [_contract("CALL", 73100), _contract("PUT", 72000)]

    assert build_straddle_legs(
        chain,
        spot=72647.32,
        strategy_position_id="SENSEX-STRADDLE",
        expiry="2026-10-01",
    ) is None