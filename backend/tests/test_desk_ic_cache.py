from datetime import datetime, timezone

from app.services.desk_ic_criteria import get_cached_desk_ic


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
