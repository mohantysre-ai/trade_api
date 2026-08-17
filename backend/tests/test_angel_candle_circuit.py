from datetime import datetime

from app.services import angel_one_feed as feed


def _reset_circuit() -> None:
    feed._ANGEL_CANDLE_CIRCUIT_UNTIL = 0.0
    feed._CANDLE_COOLDOWN_UNTIL_MONO = 0.0
    feed._CANDLE_LAST_CALL_MONO = 0.0


def test_ab1021_opens_circuit_and_skips_further_angel_posts(monkeypatch):
    _reset_circuit()
    calls: list[dict] = []

    class DummySmart:
        def getCandleData(self, params):
            calls.append(dict(params))
            return {
                "status": False,
                "message": "Too many requests",
                "errorcode": "AB1021",
                "data": None,
            }

    client = object.__new__(feed.AngelOneClient)
    dummy = DummySmart()
    monkeypatch.setattr(client, "connect", lambda: dummy)
    monkeypatch.setattr(client, "_is_auth_error", lambda _exc: False)
    now = datetime(2026, 8, 17, 11, 9, tzinfo=feed.IST_ZONE)

    assert client.fetch_candles("NSE", "317", "ONE_DAY", now, now) == []
    assert len(calls) == 1
    assert feed._angel_candle_calls_allowed() is False

    assert client.fetch_candles("NSE", "318", "ONE_DAY", now, now) == []
    assert len(calls) == 1


def test_dhan_mapped_symbol_does_not_fall_back_to_angel(monkeypatch):
    _reset_circuit()
    angel_calls: list[str] = []

    class DummyClient:
        def fetch_candles(self, *args, **kwargs):
            angel_calls.append("angel")
            return [["t", 1, 2, 0, 1, 10]]

    monkeypatch.setattr(feed, "dhan_configured", lambda: True)
    monkeypatch.setattr(feed, "load_dhan_security_ids", lambda: {"RELIANCE": "2885"})
    monkeypatch.setattr(feed, "fetch_dhan_candles", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(feed, "fetch_nse_candles", lambda *_args, **_kwargs: [])

    from app.utils.symbols import Instrument

    inst = Instrument("RELIANCE", "NSE", "RELIANCE-EQ", "2885", "RELIANCE")
    metrics = feed._intraday_metrics(
        DummyClient(),  # type: ignore[arg-type]
        inst,
        1400.0,
        datetime(2026, 8, 17, 11, 9, tzinfo=feed.IST_ZONE),
    )
    assert angel_calls == []
    assert metrics["passes_hard_filters"] is False
    assert "insufficient candle data" in (metrics.get("hard_filter_reasons") or [])


def test_nse_daily_skips_angel_one_day(monkeypatch):
    _reset_circuit()
    angel_intervals: list[str] = []
    nse_intervals: list[str] = []

    class DummyClient:
        def fetch_candles(self, _exchange, _token, interval, *_args, **_kwargs):
            angel_intervals.append(interval)
            return [["t", 1, 2, 0, 1, 10]]

    def fake_nse(_symbol, _token, interval, *_args, **_kwargs):
        nse_intervals.append(interval)
        if interval == "ONE_DAY":
            return [["2026-08-17 00:00:00", 10, 11, 9, 10.5, 1000]]
        return []

    monkeypatch.setattr(feed, "dhan_configured", lambda: False)
    monkeypatch.setattr(feed, "fetch_nse_candles", fake_nse)

    from app.utils.symbols import Instrument

    inst = Instrument("RELIANCE", "NSE", "RELIANCE-EQ", "2885", "RELIANCE")
    feed._intraday_metrics(
        DummyClient(),  # type: ignore[arg-type]
        inst,
        1400.0,
        datetime(2026, 8, 17, 11, 9, tzinfo=feed.IST_ZONE),
    )
    assert nse_intervals == ["ONE_DAY", "FIVE_MINUTE"]
    assert angel_intervals == ["FIVE_MINUTE"]
