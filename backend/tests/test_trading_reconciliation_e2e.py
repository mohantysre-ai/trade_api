from copy import deepcopy
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.services.eod_intraday_report import project_session_live
from app.services.index_options.runtime import load_positions, process_strategy_cycle
from app.services.swing_v2.authoritative import _retryable_final_block
from app.services.swing_v2.config import SwingV2Config
from app.services.swing_v2.ledger import SwingLedger
from app.services.swing_v2.reporting import ledger_eod_report
from app.services.swing_v2.shadow import build_shadow_v2


IST = ZoneInfo("Asia/Kolkata")


def _swing_row(symbol: str, now: datetime) -> dict:
    return {
        "symbol": symbol,
        "ticker": symbol,
        "universeSegment": "NIFTY100",
        "decisionPrice": 2500.0,
        "structureStop": 2450.0,
        "atr14": 40.0,
        "prior20dHigh": 2480.0,
        "clv": 0.85,
        "rvolPaced": 1.8,
        "trendPriorPctile": 90,
        "residualStrengthPctile": 90,
        "sectorStrengthPctile": 90,
        "setupQualityPctile": 90,
        "rvolPctile": 90,
        "clvPctile": 90,
        "liquidityPctile": 90,
        "breakoutDistanceAtr": 0.2,
        "extensionAtr": 1.1,
        "mdtv20": 3e9,
        "dailyObservationCount": 260,
        "modeledRoundTripCostPct": 0.15,
        "spreadPct": 0.05,
        "availableAskDepth": 1000,
        "dailyBarsThroughPreviousClose": True,
        "corporateEventsCurrent": True,
        "surveillanceCurrent": True,
        "universeCurrent": True,
        "upsideCapacityR": 2.5,
        "plannedMaxBlendedR": 2.5,
        "passes_hard_filters": True,
        "passes_quality_filters": True,
        "priceAboveVwap": True,
        "priceAboveEma9": True,
        "vwap": 2400.0,
        "ema9": 2450.0,
        "breakoutPass": True,
        "pivotR1Breakout": True,
        "rsiPivotBreak": True,
        "riskAuditVerdict": "APPROVE",
        "sourceTimestamps": {
            "quote": now.astimezone(timezone.utc).isoformat(),
            "depth": now.astimezone(timezone.utc).isoformat(),
            "bars5m": now.astimezone(timezone.utc).isoformat(),
        },
    }


def _option_leg(symbol: str, side: str, bid: float, ask: float, strike: float) -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "bestBid": bid,
        "bestAsk": ask,
        "strike": strike,
        "optionType": "CALL",
        "expiry": "2026-09-17",
        "qty": 1,
        "lotSize": 50,
        "delta": 0.4,
        "gamma": 0.01,
        "theta": -0.2,
        "vega": 0.3,
        "iv": 14.0,
    }


def _option_candidate() -> dict:
    return {
        "strategyId": "BULL_CALL_DEBIT_SPREAD",
        "strategyType": "BULL_CALL_DEBIT_SPREAD",
        "family": "DIRECTIONAL",
        "key": "NIFTY",
        "eligible": True,
        "expiry": "2026-09-17",
        "legs": [
            _option_leg("NIFTY-A", "BUY", 99, 101, 25000),
            _option_leg("NIFTY-B", "SELL", 39, 41, 25200),
        ],
        "maxLoss": 3100,
        "maxProfit": 6900,
        "breakevens": [25062],
        "delta": 0.1,
        "gamma": 0.0,
        "theta": 0.0,
        "vega": 0.0,
        "spot": 25000,
        "atmIv": 14.0,
        "snapshotId": "e2e-snapshot",
    }


def _option_snapshot() -> dict:
    return {
        "indexOptions": {
            "indices": {
                "NIFTY": {
                    "rawChain": [
                        _option_leg("NIFTY-A", "BUY", 99, 101, 25000),
                        _option_leg("NIFTY-B", "SELL", 39, 41, 25200),
                    ]
                }
            }
        }
    }


def test_coverage_block_retries_then_persists_scanner_candidate_to_swing_eod(tmp_path):
    now = datetime(2026, 9, 16, 10, 0, tzinfo=IST)
    rows = [_swing_row(f"LONG{i:02d}", now) for i in range(19)]
    for row in rows[1:]:
        row["insolvencyOrDefault"] = True
    rows[-1]["sourceTimestamps"] = {}
    cfg = SwingV2Config(
        enabled=True,
        mode="PAPER",
        authority="V2",
        ledger_path=str(tmp_path / "swing.sqlite3"),
    )

    blocked = build_shadow_v2(
        rows,
        universe_coverage=18 / 19,
        regime="NORMAL",
        final_lock=True,
        persist_events=True,
        now=now,
        config=cfg,
    )

    assert blocked["blockReason"] == "UNIVERSE_COVERAGE_BELOW_99PCT"
    assert blocked["retryable"] is True
    assert blocked["missingFreshRows"] == 1
    assert blocked["candidates"] == []
    assert blocked["funnel"]["universe"] == 19
    assert _retryable_final_block(blocked) is True

    rows[-1]["sourceTimestamps"] = deepcopy(rows[0]["sourceTimestamps"])
    recovered = build_shadow_v2(
        rows,
        universe_coverage=1.0,
        regime="NORMAL",
        final_lock=True,
        persist_events=True,
        now=now,
        config=cfg,
    )
    report = ledger_eod_report(SwingLedger(cfg.ledger_path), now.date().isoformat())

    assert recovered["tradableCoverage"] == 1.0
    assert [row["symbol"] for row in recovered["candidates"]] == ["LONG00"]
    assert [row["symbol"] for row in report["positions"]] == ["LONG00"]


def test_multileg_paper_candidate_reaches_atomic_open_state(tmp_path, monkeypatch):
    monkeypatch.setenv("INDEX_OPTIONS_STRATEGY_DB", str(tmp_path / "strategy.sqlite3"))
    candidate = _option_candidate()
    radar = {"modularCandidates": [candidate], "modularSelected": [candidate]}

    book = process_strategy_cycle(radar, _option_snapshot(), datetime(2026, 9, 16, 10, 0, tzinfo=IST))
    persisted = load_positions("2026-09-16")

    assert len(book["open"]) == 1
    assert len(persisted) == 1
    assert persisted[0]["status"] == "OPEN"
    assert persisted[0]["strategyId"] == "BULL_CALL_DEBIT_SPREAD"
    assert [leg["entryFill"] for leg in persisted[0]["legs"]] == [101, 39]
    assert candidate["paperEntryState"] == "FILLED"


def test_intraday_and_eod_projection_have_exact_symbol_and_total_pnl_parity():
    session = {
        "locked": True,
        "sessionDate": "2026-09-16",
        "long": [
            {
                "symbol": "OPEN",
                "direction": "LONG",
                "entryPrice": 100.0,
                "ltp": 125.0,
                "approxQty": 1,
                "realizedPnl": 5.0,
                "unrealizedPnl": 25.0,
                "executionStatus": "TRIGGERED",
                "status": "RUNNING",
                "closed": False,
            },
            {
                "symbol": "CLOSED",
                "direction": "LONG",
                "entryPrice": 100.0,
                "ltp": 80.0,
                "approxQty": 1,
                "realizedPnl": -10.0,
                "unrealizedPnl": 0.0,
                "executionStatus": "TRIGGERED",
                "status": "STOP LOSS HIT",
                "closed": True,
            },
        ],
        "short": [],
    }

    report = project_session_live(session, date(2026, 9, 16), 1000.0)
    intraday = {
        row["symbol"]: float(row.get("realizedPnl") or 0) + float(row.get("unrealizedPnl") or 0)
        for row in session["long"]
    }
    eod = {row["symbol"]: row["pnl"] for row in report["trades"]}

    assert eod == intraday
    assert report["totalPnl"] == sum(intraday.values()) == 20.0
    assert sum(row["realizedPnl"] for row in report["trades"]) == -5.0
    assert sum(row["unrealizedPnl"] for row in report["trades"]) == 25.0
