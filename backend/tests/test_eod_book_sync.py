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
