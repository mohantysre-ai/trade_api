"""
Dhan ScanX → feed_scanner pipeline service
===========================================
Fetches live ScanX data from Dhan, runs it through feed_scanner.py's
evaluate_stock / scan_feed, and returns the top 10 LONG candidates
with BUY/SELL/Stop Loss + Trade Plan for ₹5L capital deployment.

Also provides a local mock fallback when the Dhan API is unreachable
(common in sandbox/off-network environments) so the frontend always
has data to render.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .feed_scanner import ScanResult, scan_feed
from .live_pipeline import FIELDS, fetch_page, extract_rows

_log = logging.getLogger(__name__)

# ── Trade Plan defaults ───────────────────────────────────────────────────
TOTAL_CAPITAL = 500_000.0        # ₹5 Lakh
PER_STOCK_CAPITAL = 100_000.0    # ₹1 Lakh each (5 stocks)
TOP_N = 10                       # top 10 from scanner
TRADE_PLAN_STOCKS = 5            # top 5 get capital allocation
TARGET_1_R_MULTIPLE = 1.5        # first target at 1.5R
TARGET_2_R_MULTIPLE = 3.0        # second target at 3R


@dataclass
class TradePlanRow:
    """One row of the trade plan with capital allocation."""
    symbol: str
    name: str
    buy_above: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_per_share: float
    rr_t2: float                # Risk:Reward to T2
    entry_price: float          # original scanner entry
    approx_qty: int = 0
    deployed_capital: float = 0.0
    risk_amount: float = 0.0    # ₹ lost if SL hit

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "buyAbove": round(self.buy_above, 2),
            "stopLoss": round(self.stop_loss, 2),
            "target1": round(self.target_1, 2),
            "target2": round(self.target_2, 2),
            "riskPerShare": round(self.risk_per_share, 2),
            "rrT2": round(self.rr_t2, 1),
            "entryPrice": round(self.entry_price, 2),
            "approxQty": self.approx_qty,
            "deployedCapital": round(self.deployed_capital, 2),
            "riskAmount": round(self.risk_amount, 2),
        }


def build_trade_plan(scan_results: List[ScanResult], direction: str = "LONG") -> List[TradePlanRow]:
    """Take scan results and allocate ₹5L capital across top 5."""
    rows: List[TradePlanRow] = []

    for i, r in enumerate(scan_results[:TRADE_PLAN_STOCKS]):
        if r.entry <= 0 or r.risk_per_share <= 0:
            continue

        # Calculate targets using the scanner's R multiples
        # (feed_scanner uses TARGET_R_MULTIPLE=2.0 as single target,
        #  we expand to T1=1.5R, T2=3.0R for the trade plan)
        risk = r.risk_per_share
        t1 = r.entry + TARGET_1_R_MULTIPLE * risk if direction == "LONG" else r.entry - TARGET_1_R_MULTIPLE * risk
        t2 = r.entry + TARGET_2_R_MULTIPLE * risk if direction == "LONG" else r.entry - TARGET_2_R_MULTIPLE * risk

        # Capital allocation: ₹1L per stock
        buy_price = r.entry
        qty = int(PER_STOCK_CAPITAL / buy_price)  # whole shares
        deployed = qty * buy_price
        risk_amount = qty * risk

        rr_t2 = TARGET_2_R_MULTIPLE  # always 3.0 by construction

        rows.append(TradePlanRow(
            symbol=r.symbol,
            name=r.name,
            buy_above=r.entry,
            stop_loss=r.stop_loss,
            target_1=round(t1, 2),
            target_2=round(t2, 2),
            risk_per_share=risk,
            rr_t2=rr_t2,
            entry_price=r.entry,
            approx_qty=qty,
            deployed_capital=round(deployed, 2),
            risk_amount=round(risk_amount, 2),
        ))

    return rows


# ── Mock / fallback data ──────────────────────────────────────────────────
# When Dhan ScanX is unreachable (common in sandboxes), serve this realistic
# fallback so the frontend never gets a 404 empty panel.

MOCK_DHAN_RESULTS: List[Dict[str, Any]] = [
    {"symbol": "PARADEEP", "name": "Paradeep Phosphates", "direction": "LONG",
     "buyAbove": 147.10, "stopLoss": 145.00, "target1": 150.30, "target2": 153.40,
     "riskPerShare": 2.10, "rrT2": 3.0, "entryPrice": 147.10},
    {"symbol": "HFCL", "name": "HFCL Ltd", "direction": "LONG",
     "buyAbove": 215.00, "stopLoss": 211.50, "target1": 220.30, "target2": 225.50,
     "riskPerShare": 3.50, "rrT2": 3.0, "entryPrice": 215.00},
    {"symbol": "PPLPHARMA", "name": "Piramal Pharma", "direction": "LONG",
     "buyAbove": 176.40, "stopLoss": 173.60, "target1": 180.60, "target2": 184.80,
     "riskPerShare": 2.80, "rrT2": 3.0, "entryPrice": 176.40},
    {"symbol": "BAJAJHFL", "name": "Bajaj Housing Fin", "direction": "LONG",
     "buyAbove": 91.50, "stopLoss": 90.10, "target1": 93.60, "target2": 95.70,
     "riskPerShare": 1.40, "rrT2": 3.0, "entryPrice": 91.50},
    {"symbol": "SOUTHBANK", "name": "South Indian Bank", "direction": "LONG",
     "buyAbove": 46.30, "stopLoss": 45.60, "target1": 47.30, "target2": 48.40,
     "riskPerShare": 0.70, "rrT2": 3.0, "entryPrice": 46.30},
    {"symbol": "IDEA", "name": "Vodafone Idea", "direction": "LONG",
     "buyAbove": 12.50, "stopLoss": 12.10, "target1": 13.10, "target2": 13.70,
     "riskPerShare": 0.40, "rrT2": 3.0, "entryPrice": 12.50},
    {"symbol": "NHPC", "name": "NHPC Ltd", "direction": "LONG",
     "buyAbove": 98.20, "stopLoss": 96.80, "target1": 100.30, "target2": 102.40,
     "riskPerShare": 1.40, "rrT2": 3.0, "entryPrice": 98.20},
    {"symbol": "YESBANK", "name": "Yes Bank", "direction": "LONG",
     "buyAbove": 24.80, "stopLoss": 24.30, "target1": 25.55, "target2": 26.30,
     "riskPerShare": 0.50, "rrT2": 3.0, "entryPrice": 24.80},
    {"symbol": "SUZLON", "name": "Suzlon Energy", "direction": "LONG",
     "buyAbove": 62.40, "stopLoss": 61.00, "target1": 64.50, "target2": 66.60,
     "riskPerShare": 1.40, "rrT2": 3.0, "entryPrice": 62.40},
    {"symbol": "ZOMATO", "name": "Zomato Ltd", "direction": "LONG",
     "buyAbove": 280.50, "stopLoss": 276.00, "target1": 287.25, "target2": 294.00,
     "riskPerShare": 4.50, "rrT2": 3.0, "entryPrice": 280.50},
]

MOCK_CAPITAL_ALLOCATION: List[Dict[str, Any]] = [
    {"symbol": "PARADEEP", "buyPrice": 147.10, "approxQty": 680, "deployedCapital": 100028.00, "riskAmount": 1428.00},
    {"symbol": "HFCL", "buyPrice": 215.00, "approxQty": 465, "deployedCapital": 99975.00, "riskAmount": 1627.00},
    {"symbol": "PPLPHARMA", "buyPrice": 176.40, "approxQty": 567, "deployedCapital": 100019.00, "riskAmount": 1588.00},
    {"symbol": "BAJAJHFL", "buyPrice": 91.50, "approxQty": 1093, "deployedCapital": 100010.00, "riskAmount": 1530.00},
    {"symbol": "SOUTHBANK", "buyPrice": 46.30, "approxQty": 2160, "deployedCapital": 100008.00, "riskAmount": 1512.00},
]


def _mock_fallback(error: str) -> dict:
    """Build the mock-result payload used only when the Dhan API is truly
    unreachable (network/HTTP failure)."""
    return {
        "success": True,  # treat as success so the frontend renders something
        "source": "dhan-scanx (mock fallback)",
        "recommendations": MOCK_DHAN_RESULTS,
        "shortRecommendations": [],
        "tradePlan": MOCK_DHAN_RESULTS[:5],
        "shortTradePlan": [],
        "capitalAllocation": MOCK_CAPITAL_ALLOCATION,
        "totalRisk": sum(r["riskAmount"] for r in MOCK_CAPITAL_ALLOCATION),
        "totalCapital": TOTAL_CAPITAL,
        "scannedCount": 500,
        "passedCount": 10,
        "longPassedCount": 10,
        "shortPassedCount": 0,
        "error": error,
        "isMock": True,
    }


def _empty_result() -> dict:
    """Build a real (non-mock) empty payload.

    Used when the API is reachable but returns nothing — either zero rows
    or zero stocks that clear the feed_scanner filter. This keeps the
    frontend honest: it shows 'no signals' instead of fake mock picks.
    """
    return {
        "success": True,
        "source": "dhan-scanx",
        "recommendations": [],
        "shortRecommendations": [],
        "tradePlan": [],
        "shortTradePlan": [],
        "capitalAllocation": [],
        "totalRisk": 0.0,
        "totalCapital": TOTAL_CAPITAL,
        "scannedCount": 0,
        "passedCount": 0,
        "longPassedCount": 0,
        "shortPassedCount": 0,
        "error": None,
        "isMock": False,
    }


def _recommendation_dicts(scan_results: List[ScanResult]) -> List[dict]:
    """Convert ScanResult rows into the frontend recommendation shape.

    Direction-aware: LONG targets sit above entry, SHORT targets below.
    """
    return [
        {
            "symbol": r.symbol,
            "name": r.name,
            "direction": r.direction,
            "buyAbove": r.entry,
            "stopLoss": r.stop_loss,
            "target1": round(r.entry + 1.5 * r.risk_per_share if r.direction == "LONG" else r.entry - 1.5 * r.risk_per_share, 2),
            "target2": round(r.entry + 3.0 * r.risk_per_share if r.direction == "LONG" else r.entry - 3.0 * r.risk_per_share, 2),
            "riskPerShare": round(r.risk_per_share, 2),
            "rrT2": 3.0,
            "rsi": r.rsi,
            "deliveryPct": r.delivery_pct,
            "score": r.score,
            "reasons": r.reasons,
        }
        for r in scan_results
    ]


def fetch_dhan_scan_results(min_volume: int = 1_000_000, top_n: int = TOP_N) -> dict:
    """Fetch from Dhan ScanX API, run through feed_scanner for BOTH directions.

    Returns LONG picks in 'recommendations' and SHORT/SELL picks in
    'shortRecommendations', each with its own trade plan. 'tradePlan' /
    'capitalAllocation' describe the LONG deployment (buy) book;
    'shortTradePlan' describes the SHORT book.

    Returns a dict with 'success', 'source', 'recommendations',
    'shortRecommendations', 'tradePlan', 'shortTradePlan', 'capitalAllocation',
    'totalCapital', 'totalRisk', and 'error' (if any).
    """
    result: Dict[str, Any] = {
        "success": False,
        "source": "dhan-scanx",
        "recommendations": [],
        "shortRecommendations": [],
        "tradePlan": [],
        "shortTradePlan": [],
        "capitalAllocation": [],
        "totalCapital": TOTAL_CAPITAL,
        "totalRisk": 0.0,
        "error": None,
    }

    try:
        # Pull all pages from Dhan ScanX
        rows = []
        for pgno in range(1, 11):  # max 10 pages
            resp = fetch_page(pgno=pgno, count=500, min_volume=min_volume)
            page_rows = extract_rows(resp)
            if not page_rows:
                break
            rows.extend(page_rows)
            if len(page_rows) < 500:
                break
    except Exception as exc:
        # Genuine API failure (network/HTTP/timeout). Mock fallback is the
        # right call here so the frontend always renders something.
        _log.warning("Dhan ScanX API unreachable, using mock fallback: %s", exc)
        return _mock_fallback(str(exc))

    if not rows:
        # API is reachable but returned zero rows — no mock data, just an
        # honest empty panel.
        _log.info("Dhan ScanX reachable but returned 0 rows")
        return _empty_result()

    # Run through feed_scanner for both directions
    payload = {"data": rows}
    long_results = scan_feed(payload, direction="LONG", top_n=top_n)
    short_results = scan_feed(payload, direction="SHORT", top_n=top_n)

    if not long_results and not short_results:
        # API is fine, but nothing cleared either filter. Show an empty panel
        # instead of fake mock picks.
        _log.info("Dhan ScanX returned %d rows but 0 passed the feed_scanner filter", len(rows))
        return _empty_result()

    # Build trade plans (LONG = buy book, SHORT = sell book)
    trade_plan = build_trade_plan(long_results, direction="LONG")
    short_trade_plan = build_trade_plan(short_results, direction="SHORT")

    # Convert to dicts
    recommendations = _recommendation_dicts(long_results)
    short_recommendations = _recommendation_dicts(short_results)

    capital_allocation = [tp.to_dict() for tp in trade_plan]
    total_risk = sum(tp.risk_amount for tp in trade_plan)

    result.update({
        "success": True,
        "source": "dhan-scanx",
        "recommendations": recommendations,
        "shortRecommendations": short_recommendations,
        "tradePlan": [tp.to_dict() for tp in trade_plan],
        "shortTradePlan": [tp.to_dict() for tp in short_trade_plan],
        "capitalAllocation": capital_allocation[:5],
        "totalRisk": round(total_risk, 2),
        "scannedCount": len(rows),
        "passedCount": len(long_results) + len(short_results),
        "longPassedCount": len(long_results),
        "shortPassedCount": len(short_results),
        "isMock": False,
    })

    return result