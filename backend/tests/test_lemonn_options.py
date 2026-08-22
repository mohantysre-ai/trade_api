import json
from datetime import date

from app.services.lemonn_options import (
    apply_lemonn_fallback,
    discover_lemonn_expiries,
    fetch_lemonn_option_chain,
    parse_lemonn_expiries,
)


HTML = """
<div><div>25 AUG 2026</div><div class="font-bold">01 SEP 2026</div>
<div>08 SEP 2026</div><div>29 DEC 2026</div></div>
"""


def test_expiry_dropdown_parser_returns_real_sorted_dates():
    assert parse_lemonn_expiries(HTML, today=date(2026, 8, 22)) == [
        date(2026, 8, 25), date(2026, 9, 1), date(2026, 9, 8), date(2026, 12, 29)
    ]


def test_dynamic_expiry_discovery_uses_nearest_date():
    result = discover_lemonn_expiries(
        ["NIFTY"], page_fetcher=lambda url, timeout: HTML, ttl_seconds=0
    )
    assert result["NIFTY"] >= date(2026, 8, 25)


def test_chain_post_uses_required_symbol_and_expiry_format():
    seen = {}

    def requester(body, timeout):
        seen.update(json.loads(body.decode()))
        return {"data": {"optionChain": [
            {"strikePrice": 25000, "ce": {"ltp": 150, "oi": 1000}, "pe": {"ltp": 140, "oi": 900}}
        ]}}

    result = fetch_lemonn_option_chain("NIFTY", date(2026, 9, 1), requester=requester)
    assert seen == {"symbol": "NIFTY", "expiry": "01SEP2026"}
    assert result["status"] == "LIVE"
    assert len(result["chain"]) == 2


def test_lemonn_only_fills_chain_still_missing_after_secondary():
    current = {"indices": {
        "NIFTY": {"source": "SCANX_FALLBACK", "status": "LIVE", "chain": [{"strike": 25000}]},
        "SENSEX": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
    }}

    def fetcher(key, expiry):
        return {"source": "LEMONN_FALLBACK", "status": "LIVE", "chain": [{"strike": 82000}]}

    merged = apply_lemonn_fallback(current, {"NIFTY": date(2026, 8, 25), "SENSEX": date(2026, 8, 25)}, fetcher=fetcher)
    assert merged["thirdFallbackUsedFor"] == ["SENSEX"]
    assert merged["indices"]["NIFTY"]["source"] == "SCANX_FALLBACK"
    assert merged["indices"]["SENSEX"]["source"] == "LEMONN_FALLBACK"
