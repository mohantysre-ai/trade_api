from app.services.index_options.runtime import DURABLE_LEGACY_SELLERS
from app.services.index_options_live import _merge_strategy_projection


def test_defined_risk_legacy_sellers_are_durable():
    assert DURABLE_LEGACY_SELLERS == {
        "BULL_PUT_CREDIT_SPREAD",
        "BEAR_CALL_CREDIT_SPREAD",
        "IRON_CONDOR",
    }


def test_paper_book_projects_strategy_book_without_duplicate_seller():
    paper = {
        "open": [
            {"id": "legacy-1", "index": "NIFTY", "strategyType": "IRON_CONDOR", "strategyMode": "SELL_PREMIUM", "unrealizedPnl": 10},
            {"id": "buy-1", "index": "BANKNIFTY", "strategyType": "LONG_CALL", "strategyMode": "BUY_PREMIUM", "unrealizedPnl": 5},
        ],
        "closed": [],
    }
    strategy = {
        "positions": [{
            "strategyPositionId": "durable-1",
            "strategyId": "IRON_CONDOR",
            "index": "NIFTY",
            "status": "OPEN",
            "legs": [{"lotSize": 25}],
            "entryCredit": 100,
            "combinedStructureValue": -80,
            "maxLoss": 5000,
            "unrealizedPnl": 500,
            "realizedPnl": 0,
            "markStatus": "LIVE",
        }]
    }
    merged = _merge_strategy_projection(paper, strategy)
    condors = [row for row in merged["open"] if row.get("strategyType") == "IRON_CONDOR"]
    assert len(condors) == 1
    assert condors[0]["id"] == "durable-1"
    assert condors[0]["projectionOnly"] is True
    assert merged["openPnl"] == 505.0
    assert merged["projectionAuthority"] == "MULTI_LEG_STRATEGY_BOOK_FOR_DEFINED_RISK_SELLERS"
