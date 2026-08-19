from datetime import datetime, timezone

from app.services.desk_ic_criteria import (
    _INTRADAY_STUB_REASON,
    get_cached_desk_ic,
    prefer_intraday_blocks,
    resolve_stock_from_snapshot,
)


def _entry(*, llm_used: bool) -> dict:
    return {
        "ticker": "RELIANCE",
        "deskDecision": "HOLD_FOR_DATA",
        "llmUsed": llm_used,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def test_deterministic_cache_is_not_used_for_drawer_llm():
    snap = {"deskIcByTicker": {"RELIANCE": _entry(llm_used=False)}}
    assert get_cached_desk_ic(snap, "RELIANCE", require_llm=False) is not None
    assert get_cached_desk_ic(snap, "RELIANCE", require_llm=True) is None


def test_llm_cache_is_used_for_drawer_llm():
    snap = {"deskIcByTicker": {"RELIANCE": _entry(llm_used=True)}}
    hit = get_cached_desk_ic(snap, "RELIANCE", require_llm=True)
    assert hit is not None
    assert hit["llmUsed"] is True


def test_resolve_stock_keeps_daily_candles_over_hunt_stub():
    daily = {
        "data_source": "daily_candles",
        "atr_pct": 2.4,
        "turnover_cr": 41.2,
        "rsi": 48.0,
        "vwap": 0.0,
        "trigger_point": None,
    }
    stub = {
        "data_source": "none",
        "atr_pct": 0.0,
        "hard_filter_reasons": [_INTRADAY_STUB_REASON],
    }
    snap = {
        "stocks": [{"ticker": "BALKRISIND", "intraday": stub, "ltpRaw": 0}],
        "stockQuotes": {"BALKRISIND": {"ticker": "BALKRISIND", "ltpRaw": 2301.0, "intraday": daily}},
    }
    row = resolve_stock_from_snapshot(snap, "BALKRISIND")
    assert row is not None
    assert row["intraday"]["data_source"] == "daily_candles"
    assert row["intraday"]["atr_pct"] == 2.4
    chosen = prefer_intraday_blocks(daily, stub)
    assert chosen is daily
