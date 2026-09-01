import json
from datetime import date

from app.services import eod_intraday_report as intraday
from app.services.eod_index_options_report import generate_index_options_eod_report
from app.services.eod_engine import ingestion


def test_zero_realized_pnl_does_not_fall_back_to_stale_live_pnl(monkeypatch):
    session = {
        "long": [{"symbol": "AAA", "direction": "LONG", "realizedPnl": 0.0, "pnl": -98765.0}],
        "short": [],
    }
    monkeypatch.setattr(intraday, "_session_leg_is_triggered", lambda row: True)

    assert intraday.session_realized_pnl(session) == 0.0
    reason, exit_price, pnl, _ = intraday.apply_session_leg_economics(
        session["long"][0], reason="OPEN", exit_price=100.0, pnl=-98765.0, scale_meta=None,
    )
    assert pnl == 0.0


def test_index_options_paper_book_is_archived_with_exact_daily_total(tmp_path, monkeypatch):
    paper = tmp_path / "index_options_paper_book.json"
    eod_root = tmp_path / "eod"
    paper.write_text(json.dumps({
        "sessionDate": "2026-09-01",
        "mode": "AUTO_PAPER_ONLY",
        "open": [{"symbol": "NIFTY-OPEN", "unrealizedPnl": 125.0}],
        "closed": [{"symbol": "NIFTY-CLOSED", "pnl": -40.0}],
    }), encoding="utf-8")
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(paper))
    monkeypatch.setattr(ingestion, "EOD_DATA_ROOT", str(eod_root))

    report = generate_index_options_eod_report(date(2026, 9, 1))

    assert report["realizedPnl"] == -40.0
    assert report["openPnl"] == 125.0
    assert report["totalPnl"] == 85.0
    archived = json.loads((eod_root / "2026-09-01" / "book_index_options.json").read_text())
    assert archived["totalPnl"] == 85.0


def test_session_fill_state_replaces_conflicting_replay_metadata(monkeypatch):
    monkeypatch.setattr(intraday, "_session_leg_is_triggered", lambda row: True)
    state = {"realizedPnl": 101.27, "unrealizedPnl": 0, "remainingQty": 0, "closed": True}
    row = {"realizedPnl": 101.27, "exitState": state}
    _, _, pnl, meta = intraday.apply_session_leg_economics(
        row, reason="TRAIL STOP HIT", exit_price=1557.8, pnl=-490.77,
        scale_meta={"realizedPnl": -490.77, "unrealizedPnl": 0, "remainingQty": 63},
    )
    assert pnl == meta["realizedPnl"] == meta["exitState"]["realizedPnl"] == 101.27
    assert meta["remainingQty"] == 0


def test_correct_headline_does_not_hide_inconsistent_cached_realized_field():
    cached = {"symbolSource": "intraday_session", "totalPnl": 101.27, "trades": [
        {"symbol": "PRESTIGE", "pnl": 101.27, "realizedPnl": -490.77,
         "exitState": {"realizedPnl": 101.27}},
    ]}
    assert intraday.intraday_book_cache_stale(
        for_date=date(2026, 9, 1), cached=cached, picks=[{"symbol": "PRESTIGE"}],
        is_mock=False, symbol_source="intraday_session", session=None,
    ) == "row_economics_mismatch"


def test_initial_stop_in_scale_engine_is_not_labelled_a_trailing_stop():
    from app.services.intraday_session_engine import _enrich_position
    row = {"symbol": "FINCABLES", "direction": "SHORT", "entryPrice": 1232,
           "approxQty": 80, "closed": True, "status": "TRAIL STOP HIT",
           "realizedPnl": -492.8, "exitState": {"closed": True,
           "legsFilled": [{"r": "INITIAL_SL", "qty": 80, "price": 1238.16, "pnl": -492.8}]}}
    enriched = _enrich_position(row, {})
    assert enriched["status"] == "STOP LOSS HIT"
    assert enriched["realizedPnl"] == -492.8
