from datetime import date
from pathlib import Path

from app.services.index_options_live import compose_live_index_options_radar, replay_session_payload
from app.services.lemonn_options import apply_lemonn_fallback
from tests.test_index_options_replay import _ReplayClient, _master_for_replay


def test_handler_reaches_session_date_before_live_return():
    text = Path("app/services/angel_one_feed.py").read_text(encoding="utf-8")
    start = text.index("def index_options(")
    chunk = text[start:text.index("def dhan_scanner_matrix(")]
    assert "if sessionDate:" in chunk
    assert "replay_session_payload" in chunk
    assert "compose_live_index_options_radar" in chunk
    assert chunk.find("if sessionDate:") < chunk.find("return _compose()")
    assert "return result" not in chunk


def test_last_friday_replay_is_not_live_radar():
    payload = replay_session_payload(
        _ReplayClient(),
        "last-friday",
        today=date(2026, 8, 23),
        persist=False,
        master=_master_for_replay(),
    )
    assert payload["mode"] == "SESSION_REPLAY"
    assert payload["sessionDate"] == "2026-08-21"
    assert payload.get("buySideContracts") is not None


def test_invalid_session_date_raises():
    try:
        replay_session_payload(object(), "not-a-date", persist=False)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_compose_applies_lemonn_after_scanx():
    empty = {
        "indices": {
            "NIFTY": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
            "BANKNIFTY": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
            "FINNIFTY": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
            "SENSEX": {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []},
        }
    }
    lemonn_calls: list[str] = []

    def lemonn_fn(payload, expiries):
        lemonn_calls.append("hit")
        return apply_lemonn_fallback(
            payload,
            expiries,
            fetcher=lambda key, expiry: {"source": "LEMONN_FALLBACK", "status": "LIVE", "chain": [{"strike": 1}]},
        )

    result = compose_live_index_options_radar(
        {},
        live=True,
        client=object(),
        persist=False,
        snapshot_fn=lambda client: empty,
        scanx_fn=lambda payload, expiries: payload,
        lemonn_fn=lemonn_fn,
        expiries_fn=lambda: {
            "NIFTY": date(2026, 8, 25),
            "BANKNIFTY": date(2026, 8, 25),
            "FINNIFTY": date(2026, 8, 25),
            "SENSEX": date(2026, 8, 25),
        },
        lemonn_discover_fn=lambda keys: {},
        oi_enrichment_fn=lambda payload, expiries: payload,
    )
    assert lemonn_calls == ["hit"]
    assert result["provider"] == "ANGEL_ONE_WITH_SCANX_AND_LEMONN_FALLBACK"
    assert result["providerEvidence"]["thirdFallbackUsedFor"] == ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
