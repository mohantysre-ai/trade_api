from datetime import datetime

from app.services.angel_index_options import IST_ZONE
from app.services import index_options_hunt_supervisor as sup


def test_next_minute_boundary_is_wall_clock_aligned():
    now = datetime(2026, 9, 1, 11, 7, 43, tzinfo=IST_ZONE)
    assert sup._next_minute_boundary(now) == datetime(2026, 9, 1, 11, 8, 0, tzinfo=IST_ZONE)


def test_hunt_cycle_delegates_to_existing_live_radar(monkeypatch):
    observed = {}

    def fake_snapshot(*, reason):
        observed["reason"] = reason
        return {"snapshot": "fresh"}

    def fake_compose(snapshot, *, live, client, persist, now):
        observed.update({
            "snapshot": snapshot,
            "live": live,
            "client": client,
            "persist": persist,
            "now": now,
        })
        return {
            "huntActive": True,
            "selected": [{"key": "NIFTY"}],
            "sellerCandidates": [{"key": "BANKNIFTY"}],
            "paperBook": {"open": [], "entryCount": 0},
        }

    import app.services.angel_one_feed as feed
    import app.services.index_options_live as live_mod

    monkeypatch.setattr(feed, "ensure_fresh_market_snapshot", fake_snapshot)
    monkeypatch.setattr(live_mod, "compose_live_index_options_radar", fake_compose)

    client = object()
    now = datetime(2026, 9, 1, 11, 8, 0, tzinfo=IST_ZONE)
    result = sup.run_index_options_hunt_cycle(client, now=now)

    assert result["huntActive"] is True
    assert observed["reason"] == "autonomous_index_options_hunt"
    assert observed["snapshot"] == {"snapshot": "fresh"}
    assert observed["live"] is True
    assert observed["client"] is client
    assert observed["persist"] is True
    assert observed["now"] == now
