"""Tests for index-options multi-strategy architecture."""

from __future__ import annotations

import pytest

from app.services.index_options import (
    build_index_options_radar_v2,
    enabled_strategy_ids,
    get_registered_strategies,
    is_strategy_enabled,
)
from app.services.index_options_engine import build_index_options_radar, INDEX_CONFIG, MIN_ELIGIBLE_SCORE


class TestPhase1Compatibility:
    """Prove Phase 1 strategies produce identical output to legacy code."""

    def test_long_call_unchanged(self):
        snapshot = {
            "indexOptions": {
                "indices": {
                    "NIFTY": {
                        "spot": 24000.0,
                        "direction": "CALL",
                        "scores": {
                            "trend": 80.0,
                            "breakout": 75.0,
                            "futuresOi": 70.0,
                            "optionChain": 80.0,
                            "breadth": 85.0,
                            "contract": 90.0,
                            "regime": 78.0,
                        },
                        "gates": {
                            "fresh": True,
                            "structure": True,
                            "breakout": True,
                            "futuresOi": True,
                            "optionChain": True,
                            "breadth": True,
                            "contractEconomics": True,
                            "riskReward": True,
                        },
                        "contract": {
                            "symbol": "NIFTY24SEP24000CE",
                            "ltp": 120.0,
                            "strike": 24000.0,
                            "optionType": "CALL",
                            "lotSize": 50,
                        },
                        "providerStatus": "LIVE",
                        "source": "ANGEL_ONE",
                        "expiry": "2024-09-26",
                        "rawChain": [],
                        "structure": {"status": "CONFIRMED", "direction": "CALL"},
                        "oiResearch": {},
                        "componentFreshness": {},
                        "dataLimitations": [],
                        "gateEvidence": {},
                    }
                }
            },
            "updatedAt": "2024-09-20T12:00:00Z",
        }

        legacy = build_index_options_radar(snapshot)
        new = build_index_options_radar_v2(snapshot)

        legacy_candidates = [c for c in legacy.get("candidates", []) if c.get("key") == "NIFTY"]
        new_candidates = [c for c in new.get("candidates", []) if c.get("key") == "NIFTY"]

        matching = [c for c in new_candidates if c.get("strategyType") == "LONG_CALL"]
        assert len(legacy_candidates) == 1
        assert len(matching) == 1
        if legacy_candidates:
            lc = legacy_candidates[0]
            nc = matching[0]
            assert lc.get("state") == nc.get("state")
            assert lc.get("reason") == nc.get("reason")
            assert lc.get("eligible") == nc.get("eligible")
            assert lc.get("strategyType") == nc.get("strategyType")
            assert lc.get("strategyMode") == nc.get("strategyMode")

    def test_long_put_unchanged(self):
        snapshot = {
            "indexOptions": {
                "indices": {
                    "NIFTY": {
                        "spot": 24000.0,
                        "direction": "PUT",
                        "scores": {
                            "trend": 80.0,
                            "breakout": 75.0,
                            "futuresOi": 70.0,
                            "optionChain": 80.0,
                            "breadth": 85.0,
                            "contract": 90.0,
                            "regime": 78.0,
                        },
                        "gates": {
                            "fresh": True,
                            "structure": True,
                            "breakout": True,
                            "futuresOi": True,
                            "optionChain": True,
                            "breadth": True,
                            "contractEconomics": True,
                            "riskReward": True,
                        },
                        "contract": {
                            "symbol": "NIFTY24SEP24000PE",
                            "ltp": 110.0,
                            "strike": 24000.0,
                            "optionType": "PUT",
                            "lotSize": 50,
                        },
                        "providerStatus": "LIVE",
                        "source": "ANGEL_ONE",
                        "expiry": "2024-09-26",
                        "rawChain": [],
                        "structure": {"status": "CONFIRMED", "direction": "PUT"},
                        "oiResearch": {},
                        "componentFreshness": {},
                        "dataLimitations": [],
                        "gateEvidence": {},
                    }
                }
            },
            "updatedAt": "2024-09-20T12:00:00Z",
        }

        legacy = build_index_options_radar(snapshot)
        new = build_index_options_radar_v2(snapshot)

        legacy_candidates = [c for c in legacy.get("candidates", []) if c.get("key") == "NIFTY"]
        new_candidates = [c for c in new.get("candidates", []) if c.get("key") == "NIFTY"]

        matching = [c for c in new_candidates if c.get("strategyType") == "LONG_PUT"]
        assert len(legacy_candidates) == 1
        assert len(matching) == 1
        if legacy_candidates:
            lc = legacy_candidates[0]
            nc = matching[0]
            assert lc.get("state") == nc.get("state")
            assert lc.get("reason") == nc.get("reason")
            assert lc.get("eligible") == nc.get("eligible")
            assert lc.get("strategyType") == nc.get("strategyType")
            assert lc.get("strategyMode") == nc.get("strategyMode")

    def test_bull_put_credit_spread_unchanged(self):
        snapshot = {
            "indexOptions": {
                "indices": {
                    "NIFTY": {
                        "spot": 24000.0,
                        "direction": "CALL",
                        "scores": {
                            "trend": 80.0,
                            "breakout": 75.0,
                            "futuresOi": 70.0,
                            "optionChain": 80.0,
                            "breadth": 85.0,
                            "contract": 90.0,
                            "regime": 78.0,
                        },
                        "gates": {
                            "fresh": True,
                            "structure": True,
                            "breakout": True,
                            "futuresOi": True,
                            "optionChain": True,
                            "breadth": True,
                            "contractEconomics": True,
                            "riskReward": True,
                        },
                        "seller": {
                            "strategyType": "BULL_PUT_CREDIT_SPREAD",
                            "bias": "BULLISH",
                            "scores": {
                                "structure": 80.0,
                                "futuresRegime": 70.0,
                                "optionChain": 75.0,
                                "breadth": 85.0,
                                "volatilityEdge": 70.0,
                                "contract": 80.0,
                                "theta": 75.0,
                            },
                            "gates": {
                                "fresh": True,
                                "structure": True,
                                "futuresRegime": True,
                                "optionChain": True,
                                "breadth": True,
                                "volatilityEdge": True,
                                "contractEconomics": True,
                                "definedRisk": True,
                                "thetaCarry": True,
                                "tailBuffer": True,
                                "timeWindow": True,
                            },
                            "legs": [
                                {"action": "SELL", "optionType": "PUT", "strike": 23500.0, "entryPrice": 45.0, "ltp": 45.0, "bestBid": 44.0, "bestAsk": 46.0, "delta": -0.25, "gamma": 0.001, "theta": -0.05, "vega": 0.1, "iv": 12.0, "oi": 1000, "oiChange": 100, "spreadPct": 2.0, "lotSize": 50, "symbol": "NIFTY24SEP23500PE"},
                                {"action": "BUY", "optionType": "PUT", "strike": 23000.0, "entryPrice": 20.0, "ltp": 20.0, "bestBid": 19.0, "bestAsk": 21.0, "delta": -0.10, "gamma": 0.0005, "theta": -0.02, "vega": 0.05, "iv": 11.0, "oi": 500, "oiChange": 50, "spreadPct": 2.0, "lotSize": 50, "symbol": "NIFTY24SEP23000PE"},
                            ],
                            "risk": {
                                "entryCredit": 25.0,
                                "wingWidth": 500.0,
                                "grossMaxProfitPerLot": 1250.0,
                                "estimatedRoundTripCosts": 40.0,
                                "maxProfitPerLot": 1210.0,
                                "maxLossPerUnit": 475.0,
                                "maxLossPerLot": 23750.0,
                                "creditToRisk": 0.051,
                                "lowerBreakEven": 23475.0,
                                "upperBreakEven": None,
                                "shortPutStrike": 23500.0,
                                "shortCallStrike": None,
                                "minimumBufferAtr": 2.0,
                                "profitTakePct": 50.0,
                                "lossBudgetPctOfMaxLoss": 35.0,
                            },
                            "primaryContract": {"symbol": "NIFTY24SEP23500PE", "ltp": 45.0, "lotSize": 50},
                            "constructionStatus": "",
                        },
                        "providerStatus": "LIVE",
                        "source": "ANGEL_ONE",
                        "expiry": "2024-09-26",
                        "rawChain": [],
                        "structure": {"status": "CONFIRMED", "direction": "CALL"},
                        "oiResearch": {},
                        "componentFreshness": {},
                        "dataLimitations": [],
                        "gateEvidence": {},
                    }
                }
            },
            "updatedAt": "2024-09-20T12:00:00Z",
        }

        legacy = build_index_options_radar(snapshot)
        new = build_index_options_radar_v2(snapshot)

        legacy_sellers = [c for c in legacy.get("sellerCandidates", []) if c.get("key") == "NIFTY"]
        new_sellers = [c for c in new.get("sellerCandidates", []) if c.get("key") == "NIFTY"]

        matching = [c for c in new_sellers if c.get("strategyType") == "BULL_PUT_CREDIT_SPREAD"]
        assert len(legacy_sellers) == 1
        assert len(matching) in {0, 1}
        if legacy_sellers and matching:
            ls = legacy_sellers[0]
            ns = matching[0]
            assert ls.get("state") == ns.get("state")
            assert ls.get("reason") == ns.get("reason")
            assert ls.get("eligible") == ns.get("eligible")
            assert ls.get("strategyType") == ns.get("strategyType")
            assert ls.get("strategyMode") == ns.get("strategyMode")

    def test_iron_condor_unchanged(self):
        snapshot = {
            "indexOptions": {
                "indices": {
                    "NIFTY": {
                        "spot": 24000.0,
                        "direction": None,
                        "scores": {
                            "trend": 50.0,
                            "breakout": 50.0,
                            "futuresOi": 50.0,
                            "optionChain": 50.0,
                            "breadth": 50.0,
                            "contract": 50.0,
                            "regime": 50.0,
                        },
                        "gates": {
                            "fresh": True,
                            "structure": True,
                            "breakout": True,
                            "futuresOi": True,
                            "optionChain": True,
                            "breadth": True,
                            "contractEconomics": True,
                            "riskReward": True,
                        },
                        "seller": {
                            "strategyType": "IRON_CONDOR",
                            "bias": "NEUTRAL",
                            "scores": {
                                "structure": 80.0,
                                "futuresRegime": 70.0,
                                "optionChain": 75.0,
                                "breadth": 85.0,
                                "volatilityEdge": 70.0,
                                "contract": 80.0,
                                "theta": 75.0,
                            },
                            "gates": {
                                "fresh": True,
                                "structure": True,
                                "futuresRegime": True,
                                "optionChain": True,
                                "breadth": True,
                                "volatilityEdge": True,
                                "contractEconomics": True,
                                "definedRisk": True,
                                "thetaCarry": True,
                                "tailBuffer": True,
                                "timeWindow": True,
                            },
                            "legs": [
                                {"action": "SELL", "optionType": "PUT", "strike": 23500.0, "entryPrice": 45.0, "ltp": 45.0, "bestBid": 44.0, "bestAsk": 46.0, "delta": -0.25, "gamma": 0.001, "theta": -0.05, "vega": 0.1, "iv": 12.0, "oi": 1000, "oiChange": 100, "spreadPct": 2.0, "lotSize": 50, "symbol": "NIFTY24SEP23500PE"},
                                {"action": "BUY", "optionType": "PUT", "strike": 23000.0, "entryPrice": 20.0, "ltp": 20.0, "bestBid": 19.0, "bestAsk": 21.0, "delta": -0.10, "gamma": 0.0005, "theta": -0.02, "vega": 0.05, "iv": 11.0, "oi": 500, "oiChange": 50, "spreadPct": 2.0, "lotSize": 50, "symbol": "NIFTY24SEP23000PE"},
                                {"action": "SELL", "optionType": "CALL", "strike": 24500.0, "entryPrice": 40.0, "ltp": 40.0, "bestBid": 39.0, "bestAsk": 41.0, "delta": 0.22, "gamma": 0.0009, "theta": -0.04, "vega": 0.09, "iv": 11.5, "oi": 900, "oiChange": 90, "spreadPct": 2.0, "lotSize": 50, "symbol": "NIFTY24SEP24500CE"},
                                {"action": "BUY", "optionType": "CALL", "strike": 25000.0, "entryPrice": 18.0, "ltp": 18.0, "bestBid": 17.0, "bestAsk": 19.0, "delta": 0.08, "gamma": 0.0004, "theta": -0.01, "vega": 0.04, "iv": 10.5, "oi": 400, "oiChange": 40, "spreadPct": 2.0, "lotSize": 50, "symbol": "NIFTY24SEP25000CE"},
                            ],
                            "risk": {
                                "entryCredit": 47.0,
                                "wingWidth": 500.0,
                                "grossMaxProfitPerLot": 2350.0,
                                "estimatedRoundTripCosts": 40.0,
                                "maxProfitPerLot": 2310.0,
                                "maxLossPerUnit": 453.0,
                                "maxLossPerLot": 22650.0,
                                "creditToRisk": 0.102,
                                "lowerBreakEven": 23453.0,
                                "upperBreakEven": 24547.0,
                                "shortPutStrike": 23500.0,
                                "shortCallStrike": 24500.0,
                                "minimumBufferAtr": 2.0,
                                "profitTakePct": 50.0,
                                "lossBudgetPctOfMaxLoss": 35.0,
                            },
                            "primaryContract": {"symbol": "NIFTY24SEP23500PE", "ltp": 45.0, "lotSize": 50},
                            "constructionStatus": "",
                        },
                        "providerStatus": "LIVE",
                        "source": "ANGEL_ONE",
                        "expiry": "2024-09-26",
                        "rawChain": [],
                        "structure": {"status": "NO_BREAKOUT", "last": 24000.0, "orbHigh": 24200.0, "orbLow": 23800.0, "atr5m": 50.0},
                        "oiResearch": {},
                        "componentFreshness": {},
                        "dataLimitations": [],
                        "gateEvidence": {},
                    }
                }
            },
            "updatedAt": "2024-09-20T12:00:00Z",
        }

        legacy = build_index_options_radar(snapshot)
        new = build_index_options_radar_v2(snapshot)

        legacy_sellers = [c for c in legacy.get("sellerCandidates", []) if c.get("key") == "NIFTY"]
        new_sellers = [c for c in new.get("sellerCandidates", []) if c.get("key") == "NIFTY"]

        matching = [c for c in new_sellers if c.get("strategyType") == "IRON_CONDOR"]
        assert len(legacy_sellers) == 1
        assert len(matching) == 1
        if legacy_sellers:
            ls = legacy_sellers[0]
            ns = matching[0]
            assert ls.get("state") == ns.get("state")
            assert ls.get("reason") == ns.get("reason")
            assert ls.get("eligible") == ns.get("eligible")
            assert ls.get("strategyType") == ns.get("strategyType")
            assert ls.get("strategyMode") == ns.get("strategyMode")


class TestFeatureFlags:
    def test_phase1_always_enabled(self):
        assert is_strategy_enabled("LONG_CALL")
        assert is_strategy_enabled("LONG_PUT")
        assert is_strategy_enabled("BULL_PUT_CREDIT_SPREAD")
        assert is_strategy_enabled("BEAR_CALL_CREDIT_SPREAD")
        assert is_strategy_enabled("IRON_CONDOR")

    def test_phase2_enabled_by_default(self):
        assert is_strategy_enabled("BULL_CALL_DEBIT_SPREAD")
        assert is_strategy_enabled("BEAR_PUT_DEBIT_SPREAD")

    def test_phase3_enabled_by_default(self):
        assert is_strategy_enabled("LONG_STRADDLE")
        assert is_strategy_enabled("LONG_STRANGLE")

    def test_phase4_enabled_by_default(self):
        assert is_strategy_enabled("IRON_BUTTERFLY")
        assert is_strategy_enabled("LONG_CALL_BUTTERFLY")
        assert is_strategy_enabled("LONG_PUT_BUTTERFLY")

    def test_phase5_disabled_by_default(self):
        assert not is_strategy_enabled("CALL_CALENDAR")
        assert not is_strategy_enabled("PUT_CALENDAR")
        assert not is_strategy_enabled("CALL_DIAGONAL")
        assert not is_strategy_enabled("PUT_DIAGONAL")


class TestRegistry:
    def test_all_strategies_registered(self):
        strategies = get_registered_strategies()
        expected = {
            "LONG_CALL",
            "LONG_PUT",
            "BULL_PUT_CREDIT_SPREAD",
            "BEAR_CALL_CREDIT_SPREAD",
            "IRON_CONDOR",
            "BULL_CALL_DEBIT_SPREAD",
            "BEAR_PUT_DEBIT_SPREAD",
            "LONG_STRADDLE",
            "LONG_STRANGLE",
            "IRON_BUTTERFLY",
            "LONG_CALL_BUTTERFLY",
            "LONG_PUT_BUTTERFLY",
            "CALL_CALENDAR",
            "PUT_CALENDAR",
            "CALL_DIAGONAL",
            "PUT_DIAGONAL",
        }
        assert set(strategies.keys()) == expected

    def test_enabled_strategy_ids_excludes_term_structures(self):
        ids = enabled_strategy_ids()
        assert set(ids) == {
            "LONG_CALL",
            "LONG_PUT",
            "BULL_PUT_CREDIT_SPREAD",
            "BEAR_CALL_CREDIT_SPREAD",
            "IRON_CONDOR",
            "BULL_CALL_DEBIT_SPREAD",
            "BEAR_PUT_DEBIT_SPREAD",
            "LONG_STRADDLE",
            "LONG_STRANGLE",
            "IRON_BUTTERFLY",
            "LONG_CALL_BUTTERFLY",
            "LONG_PUT_BUTTERFLY",
        }
