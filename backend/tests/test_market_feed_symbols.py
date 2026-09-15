from app.services.market_feeds import DOMESTIC_INDEX_INSTRUMENTS


def test_midcap_uses_current_yahoo_instrument_ticker():
    midcap = next(item for item in DOMESTIC_INDEX_INSTRUMENTS if item.key == "niftymidcap")

    assert midcap.symbol == "NIFTY_MIDCAP_100.NS"
    assert midcap.symbol != "^CRSMID"
from app.services.angel_one_feed import _resolve_nse_equity


def test_resolve_nse_equity_searches_base_symbol_and_caches_dynamic_match():
    class Smart:
        def __init__(self):
            self.queries = []

        def searchScrip(self, exchange, query):
            self.queries.append((exchange, query))
            return {
                "status": True,
                "data": [
                    {"tradingsymbol": "DIACABS-BE", "symboltoken": "18545"},
                    {"tradingsymbol": "DIACABS-EQ", "symboltoken": "18543"},
                ],
            }

    class Client:
        def __init__(self):
            self.smart = Smart()

        def connect(self):
            return self.smart

    mapping = {}
    client = Client()
    assert _resolve_nse_equity("DIACABS-EQ", client=client, token_map=mapping) == ("18543", "DIACABS-EQ")
    assert client.smart.queries == [("NSE", "DIACABS")]
    assert mapping["DIACABS"] == ("18543", "DIACABS-EQ")


def test_resolve_nse_equity_skips_removed_symbol_without_retrying():
    class Smart:
        def __init__(self):
            self.queries = []

        def searchScrip(self, exchange, query):
            self.queries.append((exchange, query))
            return {"status": False, "data": None}

    class Client:
        def __init__(self):
            self.smart = Smart()

        def connect(self):
            return self.smart

    client = Client()
    assert _resolve_nse_equity("LOTUSDEV-EQ", client=client, token_map={}) is None
    assert client.smart.queries == [("NSE", "LOTUSDEV")]
