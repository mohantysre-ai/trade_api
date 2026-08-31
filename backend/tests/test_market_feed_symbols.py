from app.services.market_feeds import DOMESTIC_INDEX_INSTRUMENTS


def test_midcap_uses_current_yahoo_instrument_ticker():
    midcap = next(item for item in DOMESTIC_INDEX_INSTRUMENTS if item.key == "niftymidcap")

    assert midcap.symbol == "NIFTY_MIDCAP_100.NS"
    assert midcap.symbol != "^CRSMID"
