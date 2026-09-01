from app.services.index_options_engine import MIN_ELIGIBLE_SCORE, build_index_options_radar


def _long_premium_payload(*, score=75.0, fresh=True, contract_economics=True, premium=100.0):
    scores = {name: score for name in (
        "trend", "breakout", "futuresOi", "optionChain", "breadth", "contract", "regime"
    )}
    gates = {
        "fresh": fresh,
        "structure": False,
        "breakout": False,
        "futuresOi": False,
        "optionChain": False,
        "breadth": False,
        "contractEconomics": contract_economics,
        "riskReward": False,
    }
    return {
        "indexOptions": {
            "indices": {
                "NIFTY": {
                    "spot": 24101,
                    "direction": "CALL",
                    "providerStatus": "LIVE",
                    "source": "ANGEL_ONE",
                    "expiry": "2026-09-01",
                    "scores": scores,
                    "gates": gates,
                    "contract": {
                        "symbol": "NIFTY01SEP2624100CE",
                        "ltp": premium,
                        "lotSize": 75,
                        "token": "123",
                        "exchange": "NFO",
                    },
                    "rawChain": [],
                }
            }
        }
    }


def test_long_premium_score_floor_is_70():
    assert MIN_ELIGIBLE_SCORE == 70.0


def test_score_above_70_locks_even_when_confirmation_gates_fail():
    radar = build_index_options_radar(_long_premium_payload(score=73.9))
    row = radar["candidates"][0]
    assert row["score"] == 73.9
    assert row["state"] == "ELIGIBLE"
    assert row["reason"] == "SCORE_LOCK_70"
    assert row["eligible"] is True
    assert set(row["failedGates"]) >= {"structure", "breakout", "futuresOi", "optionChain", "breadth", "riskReward"}
    assert radar["selected"][0]["key"] == "NIFTY"


def test_score_below_70_remains_watch():
    radar = build_index_options_radar(_long_premium_payload(score=69.9))
    row = radar["candidates"][0]
    assert row["state"] == "WATCH"
    assert row["eligible"] is False
    assert row["reason"] == "SCORE_BELOW_70"


def test_stale_quote_still_blocks_high_score():
    radar = build_index_options_radar(_long_premium_payload(score=90.0, fresh=False))
    row = radar["candidates"][0]
    assert row["state"] == "NO_TRADE"
    assert row["eligible"] is False
    assert row["reason"] == "SAFETY_GATE_FAILED:fresh"


def test_invalid_contract_still_blocks_high_score():
    radar = build_index_options_radar(_long_premium_payload(score=90.0, premium=0.0))
    row = radar["candidates"][0]
    assert row["state"] == "NO_TRADE"
    assert row["eligible"] is False
    assert row["reason"] == "CONTRACT_NOT_EXECUTABLE"
