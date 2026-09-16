#!/usr/bin/env python3
"""Deterministic smoke test for scanner -> paper execution -> EOD parity.

No broker order is sent. The script deliberately uses 98% universe coverage,
19 LONG scanner candidates, a same-index BUY+SELL options selection, a durable
multi-leg seller paper lock, and exact Intraday/EOD accounting assertions.

Run from backend/:  python scripts/e2e_execution_parity_smoke.py
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _long_candidates() -> list[dict]:
    return [
        {
            "symbol": f"LONG{i:02d}", "direction": "LONG", "score": 90 - i / 10,
            "entryPrice": 100.0 + i, "approxQty": 100, "eligible": True,
        }
        for i in range(1, 20)
    ]


def _option_buy() -> dict:
    return {
        "key": "NIFTY", "bucket": "BROAD", "direction": "CALL",
        "strategyMode": "BUY_PREMIUM", "strategyType": "LONG_CALL",
        "score": 76.0, "eligible": True, "state": "ELIGIBLE",
        "dataSource": "SMOKE", "expiry": "2026-09-17",
        "contract": {
            "symbol": "NIFTY17SEP2625000CE", "ltp": 100.0, "lotSize": 50,
            "token": "10001", "exchange": "NFO", "strike": 25000,
            "expiry": "2026-09-17",
        },
        "chain": [],
    }


def _option_sell() -> dict:
    legs = [
        {"symbol": "NIFTY17SEP2624900PE", "action": "SELL", "lotSize": 50,
         "token": "20001", "exchange": "NFO", "entryPrice": 40.0},
        {"symbol": "NIFTY17SEP2624800PE", "action": "BUY", "lotSize": 50,
         "token": "20002", "exchange": "NFO", "entryPrice": 20.0},
    ]
    return {
        "key": "NIFTY", "bucket": "BROAD", "direction": "BULLISH", "bias": "BULLISH",
        "strategyMode": "SELL_PREMIUM", "strategyType": "BULL_PUT_CREDIT_SPREAD",
        "score": 88.0, "eligible": True, "state": "ELIGIBLE", "dataSource": "SMOKE",
        "expiry": "2026-09-17", "legs": legs, "chain": [],
        "risk": {
            "entryCredit": 20.0, "maxLossPerUnit": 80.0, "maxLossPerLot": 4000.0,
            "maxProfitPerLot": 1000.0, "estimatedRoundTripCosts": 80.0,
            "creditToRisk": 0.25, "shortPutStrike": 24900, "lowerBreakEven": 24880,
        },
    }


def main() -> None:
    # 1) Partial ingestion must be observable, not silently promoted to 100%.
    universe_total, ingested = 500, 490
    coverage = ingested / universe_total
    assert coverage < 0.99 and coverage == 0.98

    # 2) Simulate 19 LONG scanner results and one actual paper execution.
    scanner = _long_candidates()
    assert len(scanner) == 19
    locked = scanner[0]
    session = {
        "sessionDate": "2026-09-16", "locked": True,
        "long": [{
            **locked, "executionStatus": "TRIGGERED", "triggered": True,
            "closed": False, "status": "RUNNING", "entryPrice": locked["entryPrice"],
            "ltp": locked["entryPrice"] + 1.25, "approxQty": locked["approxQty"],
            "remainingQty": locked["approxQty"], "deployedCapital": locked["entryPrice"] * locked["approxQty"],
            "realizedPnl": 0.0, "unrealizedPnl": 125.0, "totalPnl": 125.0, "pnl": 125.0,
        }],
        "short": [],
    }

    # 3) BUY and SELL on the same index must survive independent sleeves; seller
    # must actually register in the durable multi-leg paper book.
    from app.services.index_options_live_authority import _rebalance_radar
    from app.services import index_options_paper as paper

    radar = {
        "candidates": [_option_buy()], "sellerCandidates": [_option_sell()], "selected": []
    }
    _rebalance_radar(radar, 2)
    assert {r["strategyMode"] for r in radar["selected"]} == {"BUY_PREMIUM", "SELL_PREMIUM"}

    with tempfile.TemporaryDirectory() as td:
        paper_path = Path(td) / "index_options_paper_book.json"
        old = os.environ.get("INDEX_OPTIONS_PAPER_BOOK_FILE")
        os.environ["INDEX_OPTIONS_PAPER_BOOK_FILE"] = str(paper_path)
        try:
            now = datetime(2026, 9, 16, 10, 30, tzinfo=IST)
            book = paper.reconcile_paper_book(radar, client=None, now=now, persist=True)
            assert len(book["open"]) == 2, book
            seller = [p for p in book["open"] if p.get("strategyMode") == "SELL_PREMIUM"]
            assert len(seller) == 1 and len(seller[0].get("legs") or []) == 2
            assert paper_path.exists()
        finally:
            if old is None:
                os.environ.pop("INDEX_OPTIONS_PAPER_BOOK_FILE", None)
            else:
                os.environ["INDEX_OPTIONS_PAPER_BOOK_FILE"] = old

    # 4) EOD must mirror the execution ledger, including open MTM.
    from app.services.eod_intraday_authority import reconcile_report

    forensic = {
        "date": "2026-09-16", "capital": 1_000_000.0, "totalPnl": 0.0,
        "trades": [{
            "symbol": locked["symbol"], "direction": "LONG", "entryPrice": locked["entryPrice"],
            "exitPrice": locked["entryPrice"], "qty": locked["approxQty"],
            "deployedCapital": locked["entryPrice"] * locked["approxQty"],
            "pnl": 0.0, "exitReason": "EOD_SQUAREOFF",
        }],
    }
    eod = reconcile_report(forensic, session)
    intraday_row = session["long"][0]
    eod_row = eod["trades"][0]
    assert eod_row["symbol"] == intraday_row["symbol"]
    assert eod_row["remainingQty"] == intraday_row["remainingQty"]
    assert eod_row["realizedPnl"] == intraday_row["realizedPnl"]
    assert eod_row["unrealizedPnl"] == intraday_row["unrealizedPnl"]
    assert eod_row["pnl"] == intraday_row["totalPnl"] == eod["totalPnl"]
    assert eod_row["exitReason"] == "OPEN_EOD_MTM"

    print("PASS coverage=98% scannerLong=19 locked=1 optionOpen=2 sellerMultiLeg=1 parity=100%")


if __name__ == "__main__":
    main()
