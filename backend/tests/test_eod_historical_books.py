import json
from datetime import date
from unittest.mock import patch

from app.services.eod_book_cache import month_book_pnl
from app.services.eod_engine.ingestion import list_eod_dates
from app.services.eod_intraday_report import generate_intraday_eod_report


def test_list_eod_dates_includes_book_only_folders(tmp_path, monkeypatch):
    root = tmp_path / "eod"
    (root / "2026-08-19").mkdir(parents=True)
    (root / "2026-08-20").mkdir(parents=True)
    (root / "2026-08-21").mkdir(parents=True)
    (root / "2026-08-19" / "book_intraday.json").write_text("{}", encoding="utf-8")
    (root / "2026-08-20" / "book_swing.json").write_text("{}", encoding="utf-8")
    (root / "2026-08-21" / "master_eod_payload.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("app.services.eod_engine.ingestion.EOD_DATA_ROOT", str(root))
    assert list_eod_dates() == ["2026-08-19", "2026-08-20", "2026-08-21"]


def test_historical_force_does_not_wipe_archived_intraday_book():
    day = date(2026, 8, 20)
    cached = {
        "date": "2026-08-20",
        "totalPnl": 1250.5,
        "trades": [{"symbol": "AAA", "pnl": 1250.5}],
        "symbolSource": "intraday_session",
    }
    session = {"locked": True, "sessionDate": "2026-08-21", "long": [], "short": []}
    with (
        patch(
            "app.services.eod_intraday_report._load_canonical_intraday_picks",
            return_value=(
                [],
                False,
                "empty",
                {"swing": 0, "intradayLong": 0, "intradayShort": 0, "total": 0},
            ),
        ),
        patch("app.services.desk_clock.cash_session_phase", return_value="CLOSED"),
        patch("app.services.eod_engine.ingestion.load_intraday_session", return_value=session),
        patch("app.services.eod_book_cache.load_book_cache", return_value=cached),
        patch("app.services.eod_book_cache.save_book_cache") as save,
    ):
        out = generate_intraday_eod_report(day, force=True)
    assert out is cached
    save.assert_not_called()


def test_historical_missing_book_is_not_persisted():
    day = date(2026, 8, 19)
    session = {"locked": True, "sessionDate": "2026-08-21", "long": [], "short": []}
    with (
        patch(
            "app.services.eod_intraday_report._load_canonical_intraday_picks",
            return_value=(
                [],
                False,
                "empty",
                {"swing": 0, "intradayLong": 0, "intradayShort": 0, "total": 0},
            ),
        ),
        patch("app.services.desk_clock.cash_session_phase", return_value="CLOSED"),
        patch("app.services.eod_engine.ingestion.load_intraday_session", return_value=session),
        patch("app.services.eod_book_cache.load_book_cache", return_value=None),
        patch("app.services.eod_book_cache.save_book_cache") as save,
    ):
        out = generate_intraday_eod_report(day, force=True)
    assert out.get("archiveStatus") == "NO_BOOK"
    assert out.get("totalPnl") is None
    save.assert_not_called()


def test_month_book_pnl_sums_archived_days(tmp_path, monkeypatch):
    root = tmp_path / "eod"
    d1 = root / "2026-08-19"
    d2 = root / "2026-08-21"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    (d1 / "book_intraday.json").write_text(
        json.dumps({"totalPnl": 100.0, "trades": [{"symbol": "A"}]}),
        encoding="utf-8",
    )
    (d2 / "book_intraday.json").write_text(
        json.dumps({"totalPnl": -40.0, "trades": [{"symbol": "B"}]}),
        encoding="utf-8",
    )
    (d2 / "book_swing.json").write_text(
        json.dumps({"totalPnl": 10.0, "picks": [{"symbol": "C"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.eod_engine.ingestion.EOD_DATA_ROOT", str(root))
    monkeypatch.setattr(
        "app.services.eod_engine.ingestion.list_eod_dates",
        lambda: ["2026-08-19", "2026-08-21"],
    )

    def _load(for_date, kind):
        name = "book_intraday.json" if kind == "intraday" else "book_swing.json"
        path = root / for_date.isoformat() / name
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    monkeypatch.setattr("app.services.eod_book_cache.load_book_cache", _load)
    out = month_book_pnl("2026-08")
    assert out["sessionCount"] == 2
    assert out["intradayPnl"] == 60.0
    assert out["swingPnl"] == 10.0
    assert out["combinedPnl"] == 70.0
    assert out["winDays"] == 1
    assert out["lossDays"] == 1
    assert out["scope"] in {"MTD", "MONTH"}
