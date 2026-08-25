from datetime import date

from app.services.trendlyne_oi import apply_oi_enrichment, normalize_derivative_payload


def test_normalizes_nested_call_put_oi_and_pcr():
    payload = {
        "putCallRatio": 0.82,
        "data": [
            {
                "strikePrice": 24200,
                "ce": {"openInterest": 1200, "changeInOi": 200, "volume": 44},
                "pe": {"openInterest": 900, "previousOi": 1000, "volume": 55},
            }
        ],
    }
    result = normalize_derivative_payload(payload)
    rows = {(row["strike"], row["optionType"]): row for row in result["chain"]}
    assert result["pcr"] == 0.82
    assert rows[(24200.0, "CALL")]["previousOi"] == 1000
    assert rows[(24200.0, "PUT")]["oiChange"] == -100


def test_enrichment_fills_only_missing_primary_values(monkeypatch):
    payload = {
        "indices": {
            "NIFTY": {
                "chain": [
                    {"strike": 24200, "optionType": "CALL", "oi": 5000, "previousOi": None, "oiChange": None},
                    {"strike": 24200, "optionType": "PUT", "oi": None, "previousOi": None, "oiChange": None},
                ],
                "future": {"oi": 8000, "previousOi": None},
            }
        }
    }
    monkeypatch.setattr(
        "app.services.trendlyne_oi.fetch_oi_enrichment",
        lambda code, expiry: {
            "chain": [
                {"strike": 24200, "optionType": "CALL", "oi": 1200, "previousOi": 1000, "oiChange": 200},
                {"strike": 24200, "optionType": "PUT", "oi": 900, "previousOi": 1000, "oiChange": -100},
            ],
            "future": {"oi": 7000, "previousOi": 6500, "oiChange": 500},
            "pcr": 0.82,
            "fetchedAt": "2026-08-25T04:00:00+00:00",
        },
    )
    out = apply_oi_enrichment(payload, {"NIFTY": date(2026, 8, 25)})
    call, put = out["indices"]["NIFTY"]["chain"]
    assert call["oi"] == 5000
    assert call["previousOi"] == 1000
    assert put["oi"] == 900
    assert out["indices"]["NIFTY"]["future"]["oi"] == 8000
    assert out["indices"]["NIFTY"]["future"]["previousOi"] == 6500
    assert out["indices"]["NIFTY"]["pcr"] == 0.82
