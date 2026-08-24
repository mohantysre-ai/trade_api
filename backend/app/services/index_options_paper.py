"""Durable automatic paper execution for eligible index-option contracts.

This module never calls a broker order API. It locks one exchange lot at the
observed option premium and marks/exits it only from later market-data quotes.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any

from .angel_index_options import IST_ZONE, _float
from .index_options_engine import (
    MAX_CONCURRENT_TRADES,
    MAX_DAILY_ENTRIES,
    IndexOptionReEntryGovernor,
    can_reenter_index_option,
)
from .json_atomic import atomic_write_json, load_json_with_fallback
from .market_snapshot_store import market_snapshot_path

_PAPER_LOCK = threading.Lock()
PAPER_SQUARE_OFF_TIME = dt_time(15, 29)


def paper_book_path() -> Path:
    override = (os.environ.get("INDEX_OPTIONS_PAPER_BOOK_FILE") or "").strip()
    return Path(override) if override else market_snapshot_path().with_name("index_options_paper_book.json")


def _market_open(now: datetime) -> bool:
    clock = now.astimezone(IST_ZONE)
    return clock.weekday() < 5 and dt_time(9, 15) <= clock.time().replace(tzinfo=None) < PAPER_SQUARE_OFF_TIME


def _blank_book(session_date: str) -> dict[str, Any]:
    return {"sessionDate": session_date, "mode": "AUTO_PAPER_ONLY", "open": [], "closed": [], "entryCount": 0}


def _load_book(session_date: str) -> dict[str, Any]:
    try:
        book = load_json_with_fallback(paper_book_path())
    except (FileNotFoundError, ValueError, TypeError):
        book = {}
    if not isinstance(book, dict) or book.get("sessionDate") != session_date:
        return _blank_book(session_date)
    book.setdefault("open", [])
    book.setdefault("closed", [])
    book["entryCount"] = len(book["open"]) + len(book["closed"])
    return book


def _mark_for(position: dict[str, Any], candidates: list[dict[str, Any]]) -> float | None:
    symbol = str(position.get("symbol") or "")
    for row in candidates:
        for contract in row.get("chain") or []:
            if isinstance(contract, dict) and str(contract.get("symbol") or "") == symbol:
                return _float(contract.get("ltp"))
        contract = row.get("contract") if isinstance(row.get("contract"), dict) else {}
        if str(contract.get("symbol") or "") == symbol:
            return _float(contract.get("ltp"))
    return None


def _close(position: dict[str, Any], mark: float, reason: str, now: datetime) -> dict[str, Any]:
    entry, qty = float(position["entryPremium"]), int(position["quantity"])
    return {**position, "status": "CLOSED", "exitPremium": round(mark, 2), "exitReason": reason,
            "exitedAt": now.isoformat(), "pnl": round((mark - entry) * qty, 2),
            "pnlPct": round((mark - entry) / entry * 100.0, 2), "currentPremium": round(mark, 2)}


def _update_open(position: dict[str, Any], mark: float, now: datetime) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    entry, initial_stop = float(position["entryPremium"]), float(position["initialStopPremium"])
    risk = max(entry - initial_stop, 0.05)
    peak = max(float(position.get("peakPremium") or entry), mark)
    stop = float(position.get("effectiveStopPremium") or initial_stop)
    favourable_r = (peak - entry) / risk
    if favourable_r >= 1.0:
        stop = max(stop, entry)
    if favourable_r >= 2.0:
        stop = max(stop, peak - risk)
    target = float(position["targetPremium"])
    updated = {**position, "currentPremium": round(mark, 2), "peakPremium": round(peak, 2),
               "effectiveStopPremium": round(stop, 2), "unrealizedPnl": round((mark - entry) * int(position["quantity"]), 2),
               "updatedAt": now.isoformat()}
    if mark <= stop:
        return None, _close(updated, mark, "TRAIL_STOP" if stop >= entry else "INITIAL_STOP", now)
    if mark >= target:
        return None, _close(updated, mark, "TARGET", now)
    if now.astimezone(IST_ZONE).time().replace(tzinfo=None) >= PAPER_SQUARE_OFF_TIME:
        return None, _close(updated, mark, "EOD_SQUAREOFF", now)
    return updated, None


def _new_position(row: dict[str, Any], now: datetime, sequence: int) -> dict[str, Any] | None:
    contract = row.get("contract") if isinstance(row.get("contract"), dict) else {}
    rr = ((row.get("gateEvidence") or {}).get("riskReward") or {})
    premium, lot = _float(contract.get("ltp")), _float(contract.get("lotSize"))
    projected_loss, projected_gain = _float(rr.get("projectedOptionLoss")), _float(rr.get("projectedOptionGain"))
    if not premium or not lot or lot < 1 or not projected_loss or not projected_gain:
        return None
    stop = max(0.05, premium - projected_loss)
    target = premium + projected_gain
    return {
        "id": f"{now.astimezone(IST_ZONE).date().isoformat()}-{sequence:02d}-{row['key']}",
        "index": row["key"], "bucket": row["bucket"], "direction": row["direction"],
        "symbol": contract.get("symbol"), "strike": contract.get("strike"), "expiry": contract.get("expiry"),
        "quantity": int(lot), "lotSize": int(lot), "entryPremium": round(premium, 2),
        "currentPremium": round(premium, 2), "peakPremium": round(premium, 2),
        "initialStopPremium": round(stop, 2), "effectiveStopPremium": round(stop, 2),
        "targetPremium": round(target, 2), "expectedR": rr.get("expectedR"), "score": row.get("score"),
        "status": "OPEN", "enteredAt": now.isoformat(), "updatedAt": now.isoformat(), "unrealizedPnl": 0.0,
        "source": row.get("dataSource"), "execution": "PAPER_ONLY",
    }


def _governor(book: dict[str, Any]) -> IndexOptionReEntryGovernor:
    governor = IndexOptionReEntryGovernor()
    for row in [*(book.get("open") or []), *(book.get("closed") or [])]:
        key = str(row.get("index") or "")
        if key:
            governor.trade_counts[key] = governor.trade_counts.get(key, 0) + 1
    for row in book.get("closed") or []:
        key = str(row.get("index") or "")
        reason = str(row.get("exitReason") or "")
        pnl = float(row.get("pnl") or 0)
        mapped = "TARGET" if reason == "TARGET" else "TRAILING_SL_PROFIT" if reason == "TRAIL_STOP" and pnl >= 0 else "STOP_LOSS"
        if mapped == "STOP_LOSS":
            governor.sl_counts[key] = governor.sl_counts.get(key, 0) + 1
        governor.last_exits[key] = {"time": row.get("exitedAt"), "reason": mapped,
                                    "direction": row.get("direction"), "price": row.get("exitPremium")}
    return governor


def reconcile_paper_book(radar: dict[str, Any], *, now: datetime | None = None, persist: bool = True) -> dict[str, Any]:
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    session = clock.date().isoformat()
    with _PAPER_LOCK:
        book = _load_book(session)
        candidates = radar.get("candidates") if isinstance(radar.get("candidates"), list) else []
        next_open: list[dict[str, Any]] = []
        closed_now: list[dict[str, Any]] = []
        for position in book["open"]:
            mark = _mark_for(position, candidates)
            if mark is None:
                next_open.append(position)
                continue
            active, closed = _update_open(position, mark, clock)
            if active:
                next_open.append(active)
            if closed:
                closed_now.append(closed)
        book["open"] = next_open
        book["closed"].extend(closed_now)
        book["entryCount"] = len(book["open"]) + len(book["closed"])

        open_indexes = {str(row.get("index")) for row in book["open"]}
        open_buckets = {str(row.get("bucket")) for row in book["open"]}
        if _market_open(clock):
            for row in radar.get("selected") or []:
                if book["entryCount"] >= MAX_DAILY_ENTRIES or len(book["open"]) >= MAX_CONCURRENT_TRADES:
                    break
                if row.get("state") != "ELIGIBLE" or row.get("key") in open_indexes or row.get("bucket") in open_buckets:
                    continue
                governor = _governor(book)
                decision = can_reenter_index_option(
                    str(row.get("key") or ""), str(row.get("direction") or ""), clock, governor,
                    fresh_breakout_confirmed=True, oi_aligned=True, breadth_aligned=True,
                )
                if not decision.get("allowed"):
                    continue
                position = _new_position(row, clock, book["entryCount"] + 1)
                if position is None:
                    continue
                book["open"].append(position)
                book["entryCount"] += 1
                open_indexes.add(str(row.get("key")))
                open_buckets.add(str(row.get("bucket")))

        open_pnl = round(sum(float(row.get("unrealizedPnl") or 0) for row in book["open"]), 2)
        realized = round(sum(float(row.get("pnl") or 0) for row in book["closed"]), 2)
        book.update({"updatedAt": clock.isoformat(), "openPnl": open_pnl, "realizedPnl": realized,
                     "totalPnl": round(open_pnl + realized, 2), "dailyEntryCap": MAX_DAILY_ENTRIES,
                     "marketOpen": _market_open(clock)})
        if persist:
            atomic_write_json(paper_book_path(), book)
        return book
