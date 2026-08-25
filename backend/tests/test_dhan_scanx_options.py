import json
from datetime import date

from app.services.dhan_scanx_options import (
    apply_scanx_fallback,
    expiry_epoch,
    fetch_scanx_option_chain,
    normalize_scanx_chain,
    has_usable_option_chain,
)


def test_expiry_epoch_uses_actual_contract_date_at_1830_ist():
    assert expiry_epoch(date(2026, 8, 25)) == 1787662800


def test_fetch_uses_sid_and_normalizes_nested_call_put_rows():
    seen = {}

    def requester(body, timeout):
        seen.update(json.loads(body.decode()))
        return {"data": {"spotPrice": 25010, "optionChain": [
            {"strikePrice": 25000, "ce": {"ltp": 150, "oi": 1000, "previousOi": 800, "delta": .55},
             "pe": {"ltp": 140, "oi": 900, "previousOi": 950, "delta": -.45}}
        ]}}

    result = fetch_scanx_option_chain("NIFTY", date(2026, 8, 25), requester=requester)
    assert seen["Data"]["Sid"] == 13
    assert seen["Data"]["Exp"] == expiry_epoch(date(2026, 8, 25))
    assert result["status"] == "LIVE"
    assert {row["optionType"] for row in result["chain"]} == {"CALL", "PUT"}


def test_fallback_only_replaces_unusable_angel_index():
    angel = {"source": "ANGEL_ONE", "indices": {
        "NIFTY": {"status": "SOURCE_UNAVAILABLE", "error": "timeout", "chain": []},
        "BANKNIFTY": {"status": "LIVE", "chain": [{"strike": 50000}]},
    }}

    def fetcher(key, expiry):
        return {"source": "SCANX_FALLBACK", "status": "LIVE", "expiry": expiry.isoformat(), "chain": [{"strike": 25000}]}

    merged = apply_scanx_fallback(angel, {"NIFTY": date(2026, 8, 25), "BANKNIFTY": date(2026, 8, 26)}, fetcher=fetcher)
    assert merged["fallbackUsedFor"] == ["NIFTY"]
    assert merged["indices"]["NIFTY"]["source"] == "SCANX_FALLBACK"
    assert merged["indices"]["BANKNIFTY"]["chain"] == [{"strike": 50000}]


def test_sensex_uses_scanx_sid_51():
    seen = {}

    def requester(body, timeout):
        seen.update(json.loads(body.decode()))
        return {"data": {"optionChain": [
            {"strike": 82000, "ce": {"ltp": 200}, "pe": {"ltp": 180}}
        ]}}

    result = fetch_scanx_option_chain("SENSEX", date(2026, 8, 25), requester=requester)
    assert seen["Data"]["Sid"] == 51
    assert result["status"] == "LIVE"


def test_live_chain_without_executable_direction_quote_uses_fallback():
    angel = {"source": "ANGEL_ONE", "indices": {
        "NIFTY": {
            "status": "LIVE",
            "structure": {"direction": "CALL"},
            "chain": [{"strike": 25000, "optionType": "CALL", "ltp": 100,
                       "volume": 1000, "bestBid": 0, "bestAsk": 100}],
        },
    }}

    assert has_usable_option_chain(angel["indices"]["NIFTY"]) is False
    merged = apply_scanx_fallback(
        angel,
        {"NIFTY": date(2026, 8, 25)},
        fetcher=lambda key, expiry: {
            "source": "SCANX_FALLBACK", "status": "LIVE", "expiry": expiry.isoformat(),
            "chain": [{"strike": 25000, "optionType": "CALL", "ltp": 101,
                       "volume": 1200, "bestBid": 100.5, "bestAsk": 101}],
        },
    )
    assert merged["fallbackUsedFor"] == ["NIFTY"]
    assert merged["indices"]["NIFTY"]["source"] == "SCANX_FALLBACK"
    assert merged["indices"]["NIFTY"]["structure"]["direction"] == "CALL"
