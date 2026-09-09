from datetime import datetime

from app.services.angel_index_options import INDEX_LEADER_WEIGHTS, IST_ZONE
from app.services import index_options_context as context


def test_index_options_context_owns_a_small_dedicated_snapshot(monkeypatch, tmp_path):
    required = sorted({symbol for rows in INDEX_LEADER_WEIGHTS.values() for symbol, _ in rows})
    master = [
        {"exch_seg": "NSE", "name": symbol, "symbol": f"{symbol}-EQ", "token": str(index + 1)}
        for index, symbol in enumerate(required)
    ]
    monkeypatch.setattr(context, "load_angel_scrip_master", lambda: master)
    monkeypatch.setenv("INDEX_OPTIONS_MARKET_CONTEXT_FILE", str(tmp_path / "options-context.json"))

    class Client:
        def fetch_batch_quotes(self, instruments):
            return {
                item.key: {"ltp": 15.0 if item.key == "indiavix" else 100.0, "open": 99.0, "close": 98.0}
                for item in instruments
            }

    payload = context.refresh_index_options_context(Client(), now=datetime.now(IST_ZONE))
    assert payload["book"] == "INDEX_OPTIONS"
    assert payload["indexOptionsContext"]["status"] == "LIVE"
    assert payload["indexOptionsContext"]["receivedLeaders"] == len(required)
    assert payload["macroDataStrip"]["morning"][0]["val"] == 15.0
    assert context.load_index_options_context()["stockQuotes"] == payload["stockQuotes"]


def test_index_options_context_never_falls_back_to_another_book(monkeypatch, tmp_path):
    monkeypatch.setenv("INDEX_OPTIONS_MARKET_CONTEXT_FILE", str(tmp_path / "options-context.json"))
    monkeypatch.setattr(context, "load_angel_scrip_master", lambda: (_ for _ in ()).throw(RuntimeError("provider down")))
    payload = context.refresh_index_options_context(object())
    assert payload["indexOptionsContext"]["status"] == "UNAVAILABLE"
    assert payload["stockQuotes"] == {}
    assert context.load_index_options_context()["stockQuotes"] == {}
