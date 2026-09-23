from app.services.swing_v2.ingestion import _apply_factor_percentiles


def test_liquidity_rank_uses_daily_turnover_when_depth_cost_is_missing():
    rows = [
        {"symbol": "LIQUID", "mdtv20": 2_000_000_000.0, "modeledRoundTripCostPct": None},
        {"symbol": "THIN", "mdtv20": 100_000_000.0, "modeledRoundTripCostPct": None},
    ]

    _apply_factor_percentiles(rows)

    assert rows[0]["liquidityPctile"] > rows[1]["liquidityPctile"]
