from datetime import date
from unittest.mock import Mock

from app.services import eod_book_cache
from app.services import eod_index_options_report
from app.services.index_options import runtime


def test_september_17_report_reconciles_all_durable_trades(monkeypatch):
    day = "2026-09-17"
    paper = {
        "sessionDate": day,
        "open": [],
        "closed": [
            {"id": f"paper-{i}", "symbol": f"CONTRACT-{i}", "pnl": pnl}
            for i, pnl in enumerate((-1384.50, -688.50, -613.50, 14.00))
        ],
    }
    strategies = [
        {
            "strategyPositionId": f"strategy-{i}",
            "strategyId": "TEST_TWO_LEG_STRATEGY",
            "sessionDate": day,
            "status": "CLOSED",
            "realizedPnl": pnl,
            "unrealizedPnl": 0.0,
            "legs": [
                {"symbol": f"LEG-{i}-BUY", "side": "BUY"},
                {"symbol": f"LEG-{i}-SELL", "side": "SELL"},
            ],
        }
        for i, pnl in enumerate([-200.0] * 28 + [4.0])
    ]
    load_positions = Mock(return_value=strategies)
    save_cache = Mock(side_effect=lambda requested_day, kind, payload: payload)
    monkeypatch.setattr(eod_index_options_report, "load_json_with_fallback", lambda path: paper)
    monkeypatch.setattr(runtime, "load_positions", load_positions)
    monkeypatch.setattr(eod_book_cache, "load_book_cache", Mock(return_value=None))
    monkeypatch.setattr(eod_book_cache, "save_book_cache", save_cache)

    report = eod_index_options_report.generate_index_options_eod_report(date(2026, 9, 17))

    load_positions.assert_called_once_with(day)
    assert report["sessionDate"] == day
    assert report["entryCount"] == report["closedCount"] == 33
    assert report["openCount"] == 0
    assert len(report["positions"]) == len({row["id"] for row in report["positions"]}) == 33
    assert report["realizedPnl"] == report["totalPnl"] == -8268.50
    assert report["openPnl"] == 0.0
    assert sum(row["pnl"] for row in report["positions"]) == -8268.50
    assert report["strategyEntryCount"] == 29
    assert report["strategyRealizedPnl"] == -5596.0
    projected = {row["strategyPositionId"]: row for row in report["positions"] if row.get("strategyPositionId")}
    assert sum(len(row["legs"]) for row in projected.values()) == 58
    for position in strategies:
        assert projected[position["strategyPositionId"]]["legs"] == position["legs"]
    save_cache.assert_called_once_with(date(2026, 9, 17), "index_options", report)



def test_http_cache_recovery_matches_eod_after_restart(tmp_path, monkeypatch):
    import json
    import socket
    import threading
    import time
    from datetime import datetime
    from urllib.request import urlopen

    import uvicorn

    from app.services.angel_index_options import IST_ZONE
    from app.services.angel_one_feed import create_app
    from app.services.eod_engine import ingestion
    from app.services.shared_state import view_store

    day = datetime.now(IST_ZONE).date().isoformat()
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "strategy.db"))
    monkeypatch.setenv("INDEX_OPTIONS_PAPER_BOOK_FILE", str(tmp_path / "paper.json"))
    monkeypatch.setattr(ingestion, "EOD_DATA_ROOT", str(tmp_path / "eod"))
    paper = {"sessionDate": day, "open": [], "closed": [{"id": "legacy", "pnl": -40.0}]}
    (tmp_path / "paper.json").write_text(json.dumps(paper), encoding="utf-8")
    position = {
        "strategyPositionId": "durable", "strategyId": "SPREAD", "index": "NIFTY",
        "status": "CLOSED", "sessionDate": day, "realizedPnl": 100.0, "unrealizedPnl": 0.0,
        "legs": [{"symbol": "A", "side": "BUY"}, {"symbol": "B", "side": "SELL"}],
    }
    with runtime._connect() as db:
        db.execute("INSERT INTO index_option_positions VALUES(?,?,?,?,?,?,?,?)", (
            "durable", "decision", "SPREAD", day, "NIFTY", "CLOSED", json.dumps(position), day,
        ))
    stale = {"success": True, "strategyBook": {"positions": [], "open": [], "closed": []}}
    monkeypatch.setattr(view_store, "get_view_store", lambda: Mock(get=lambda namespace: {"payload": stale, "updatedAt": time.time()}))
    results = []
    for _ in range(2):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, lifespan="off", log_level="error"))
        worker = threading.Thread(target=server.run, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started
            with urlopen(f"http://127.0.0.1:{port}/api/index-options", timeout=10) as response:
                radar = json.load(response)
            with urlopen(f"http://127.0.0.1:{port}/api/reports/eod-index-options?date={day}", timeout=10) as response:
                report = json.load(response)
            summary = radar["paperBook"]
            assert radar["cacheStatus"] == "HIT"
            assert radar["strategyBook"]["closed"] == [position]
            assert report["entryCount"] == summary["entryCount"] == 2
            assert report["closedCount"] == summary["closedCount"] == 2
            assert report["realizedPnl"] == summary["realizedPnl"] == 60.0
            assert report["openPnl"] == summary["openPnl"] == 0.0
            assert sum(row["pnl"] for row in report["positions"]) == report["totalPnl"] == summary["totalPnl"] == 60.0
            assert report["strategyPositions"][0]["legs"] == position["legs"]
            results.append((summary, report["positions"]))
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            assert not worker.is_alive()
    assert results[0] == results[1]
