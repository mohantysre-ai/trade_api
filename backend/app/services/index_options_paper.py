"""Durable automatic paper execution for eligible index-option contracts.

This module never calls a broker order API. It locks one exchange lot at the
observed option premium and marks/exits it only from later market-data quotes.
Long-premium paper positions use an immutable 20-point stop, 40-point target,
and one-minute mark cadence (1:2 option-premium risk/reward).
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any

from ..utils.symbols import Instrument
from .angel_index_options import IST_ZONE, _float, load_angel_scrip_master
from .index_options_engine import (
    MAX_CONCURRENT_TRADES,
    MAX_DAILY_ENTRIES,
    IndexOptionReEntryGovernor,
    can_reenter_index_option,
)
from .index_options_seller import SELLER_ENTRY_CUTOFF
from .json_atomic import atomic_write_json, load_json_with_fallback
from .market_snapshot_store import market_snapshot_path

_PAPER_LOCK = threading.Lock()
PAPER_SQUARE_OFF_TIME = dt_time(15, 29)
SELLER_SQUARE_OFF_TIME = dt_time(15, 20)
DEFAULT_SELLER_MAX_SINGLE_RISK_INR = 5_000.0
DEFAULT_SELLER_MAX_PORTFOLIO_RISK_INR = 10_000.0
LONG_PREMIUM_MARK_INTERVAL_SECONDS = 60
LONG_PREMIUM_STOP_POINTS = 20.0
LONG_PREMIUM_TARGET_POINTS = 40.0
LONG_PREMIUM_RISK_REWARD = 2.0
LONG_PREMIUM_MARK_HISTORY_LIMIT = 400


def _positive_env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _seller_single_risk_cap() -> float:
    return _positive_env_float("INDEX_OPTIONS_SELLER_MAX_SINGLE_RISK", DEFAULT_SELLER_MAX_SINGLE_RISK_INR)


def _seller_portfolio_risk_cap() -> float:
    return _positive_env_float("INDEX_OPTIONS_SELLER_MAX_PORTFOLIO_RISK", DEFAULT_SELLER_MAX_PORTFOLIO_RISK_INR)


def paper_book_path() -> Path:
    override = (os.environ.get("INDEX_OPTIONS_PAPER_BOOK_FILE") or "").strip()
    return Path(override) if override else market_snapshot_path().with_name("index_options_paper_book.json")


def _market_open(now: datetime) -> bool:
    clock = now.astimezone(IST_ZONE)
    return clock.weekday() < 5 and dt_time(9, 15) <= clock.time().replace(tzinfo=None) < PAPER_SQUARE_OFF_TIME


def index_options_market_open(now: datetime | None = None) -> bool:
    """Public session gate shared by the API and UI payload composer."""
    return _market_open((now or datetime.now(IST_ZONE)).astimezone(IST_ZONE))


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


def _hydrate_locked_instruments(positions: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in candidates:
        for contract in row.get("chain") or []:
            if isinstance(contract, dict) and contract.get("symbol"):
                by_symbol[str(contract["symbol"])] = contract
    locked_instruments = [
        instrument
        for row in positions
        for instrument in ((row.get("legs") or []) if row.get("strategyMode") == "SELL_PREMIUM" else [row])
        if isinstance(instrument, dict)
    ]
    unresolved = [row for row in locked_instruments if not row.get("token") or not row.get("exchange")]
    if unresolved:
        try:
            for raw in load_angel_scrip_master():
                symbol = str(raw.get("symbol") or "")
                if symbol and symbol not in by_symbol:
                    by_symbol[symbol] = {"token": raw.get("token"), "exchange": raw.get("exch_seg")}
        except Exception:
            pass
    for position in positions:
        instruments = [position, *(leg for leg in (position.get("legs") or []) if isinstance(leg, dict))]
        for instrument in instruments:
            contract = by_symbol.get(str(instrument.get("symbol") or "")) or {}
            if not instrument.get("token") and contract.get("token"):
                instrument["token"] = str(contract["token"])
            if not instrument.get("exchange") and (contract.get("exchange") or contract.get("exch_seg")):
                instrument["exchange"] = str(contract.get("exchange") or contract.get("exch_seg"))


def _direct_locked_marks(client: Any, positions: list[dict[str, Any]]) -> tuple[dict[str, float], str | None]:
    if client is None:
        return {}, None
    instruments: list[Instrument] = []
    seen: set[str] = set()
    for position in positions:
        locked = (position.get("legs") or []) if position.get("strategyMode") == "SELL_PREMIUM" else [position]
        for leg in locked:
            if not isinstance(leg, dict):
                continue
            symbol, token, exchange = str(leg.get("symbol") or ""), str(leg.get("token") or ""), str(leg.get("exchange") or "")
            if symbol and token and exchange and symbol not in seen:
                instruments.append(Instrument(f"PAPER:{symbol}", exchange, symbol, token, symbol))
                seen.add(symbol)
    if not instruments:
        return {}, "LOCKED_CONTRACT_TOKEN_UNAVAILABLE" if positions else None
    try:
        quotes = client.fetch_batch_quotes(instruments)
    except Exception as exc:
        return {}, str(exc)
    marks: dict[str, float] = {}
    for instrument in instruments:
        mark = _float((quotes.get(instrument.key) or {}).get("ltp"))
        if mark is not None and mark > 0:
            marks[instrument.tradingsymbol] = mark
    return marks, None


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST_ZONE)


def _long_mark_due(position: dict[str, Any], now: datetime) -> bool:
    if now.astimezone(IST_ZONE).time().replace(tzinfo=None) >= PAPER_SQUARE_OFF_TIME:
        return True
    last = _parse_iso(position.get("markedAt") or position.get("enteredAt"))
    if last is None:
        return True
    return (now - last.astimezone(now.tzinfo)).total_seconds() >= LONG_PREMIUM_MARK_INTERVAL_SECONDS


def _record_long_mark(position: dict[str, Any], mark: float, now: datetime, source: str) -> dict[str, Any]:
    entry, qty = float(position["entryPremium"]), int(position["quantity"])
    pnl = round((mark - entry) * qty, 2)
    history = list(position.get("minuteMarks") or [])
    history.append({"at": now.isoformat(), "premium": round(mark, 2), "pnl": pnl, "source": source})
    if len(history) > LONG_PREMIUM_MARK_HISTORY_LIMIT:
        history = history[-LONG_PREMIUM_MARK_HISTORY_LIMIT:]
    return {
        **position,
        "currentPremium": round(mark, 2),
        "peakPremium": round(max(float(position.get("peakPremium") or entry), mark), 2),
        "effectiveStopPremium": round(float(position["initialStopPremium"]), 2),
        "unrealizedPnl": pnl,
        "updatedAt": now.isoformat(),
        "markedAt": now.isoformat(),
        "markSource": source,
        "markStatus": "LIVE",
        "minuteMarks": history,
        "nextMarkDueAt": datetime.fromtimestamp(now.timestamp() + LONG_PREMIUM_MARK_INTERVAL_SECONDS, tz=now.tzinfo).isoformat(),
    }


def _close(position: dict[str, Any], mark: float, reason: str, now: datetime) -> dict[str, Any]:
    entry, qty = float(position["entryPremium"]), int(position["quantity"])
    return {
        **position,
        "status": "CLOSED",
        "exitPremium": round(mark, 2),
        "exitReason": reason,
        "exitedAt": now.isoformat(),
        "pnl": round((mark - entry) * qty, 2),
        "pnlPct": round((mark - entry) / entry * 100.0, 2),
        "currentPremium": round(mark, 2),
        "unrealizedPnl": 0.0,
        "nextMarkDueAt": None,
    }


def _update_open(
    position: dict[str, Any], mark: float, now: datetime, *, mark_source: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    stop = float(position["initialStopPremium"])
    target = float(position["targetPremium"])
    updated = _record_long_mark(position, mark, now, mark_source)
    if mark <= stop:
        return None, _close(updated, mark, "INITIAL_STOP", now)
    if mark >= target:
        return None, _close(updated, mark, "TARGET", now)
    if now.astimezone(IST_ZONE).time().replace(tzinfo=None) >= PAPER_SQUARE_OFF_TIME:
        return None, _close(updated, mark, "EOD_SQUAREOFF", now)
    return updated, None


def _candidate_contract(symbol: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    for row in candidates:
        for contract in row.get("chain") or []:
            if isinstance(contract, dict) and str(contract.get("symbol") or "") == symbol:
                return contract
        for leg in row.get("legs") or []:
            if isinstance(leg, dict) and str(leg.get("symbol") or "") == symbol:
                return leg
    return {}


def _credit_close_debit(
    position: dict[str, Any], candidates: list[dict[str, Any]], direct_marks: dict[str, float],
) -> tuple[float | None, list[dict[str, Any]], str]:
    """Price seller exits conservatively: buy shorts at ask, sell hedges at bid."""
    marked: list[dict[str, Any]] = []
    direct_used = False
    for leg in position.get("legs") or []:
        if not isinstance(leg, dict):
            return None, [], "UNAVAILABLE"
        symbol = str(leg.get("symbol") or "")
        quote = _candidate_contract(symbol, candidates)
        action = str(leg.get("action") or "").upper()
        executable = _float(quote.get("bestAsk" if action == "SELL" else "bestBid"))
        source = "RADAR_EXECUTABLE_DEPTH"
        if executable is None:
            executable = direct_marks.get(symbol)
            source = "ANGEL_DIRECT_LTP_FALLBACK"
            direct_used = direct_used or executable is not None
        if executable is None:
            return None, [], "UNAVAILABLE"
        marked.append({**leg, "currentPrice": round(executable, 2), "markSource": source})
    debit = sum(float(leg["currentPrice"]) for leg in marked if leg.get("action") == "SELL") \
        - sum(float(leg["currentPrice"]) for leg in marked if leg.get("action") == "BUY")
    return round(max(0.0, debit), 2), marked, "ANGEL_DIRECT_LTP_FALLBACK" if direct_used else "RADAR_EXECUTABLE_DEPTH"


def _spot_for(position: dict[str, Any], candidates: list[dict[str, Any]]) -> float | None:
    key = str(position.get("index") or "")
    for row in candidates:
        if str(row.get("key") or "") == key:
            spot = _float(row.get("spot"))
            if spot is not None:
                return spot
    return None


def _close_credit(position: dict[str, Any], debit: float, reason: str, now: datetime) -> dict[str, Any]:
    credit, qty = float(position["entryCredit"]), int(position["quantity"])
    costs = float(position.get("estimatedRoundTripCosts") or 0)
    pnl = round((credit - debit) * qty - costs, 2)
    max_loss = max(float(position.get("maxLossPerLot") or 0), 0.01)
    return {
        **position,
        "status": "CLOSED",
        "exitDebit": round(debit, 2),
        "currentDebit": round(debit, 2),
        "exitReason": reason,
        "exitedAt": now.isoformat(),
        "pnl": pnl,
        "pnlPct": round(pnl / max_loss * 100.0, 2),
        "unrealizedPnl": 0.0,
    }


def _update_credit_open(
    position: dict[str, Any], debit: float, marked_legs: list[dict[str, Any]], spot: float | None, now: datetime,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    credit, qty = float(position["entryCredit"]), int(position["quantity"])
    costs = float(position.get("estimatedRoundTripCosts") or 0)
    max_loss_unit = float(position["maxLossPerUnit"])
    profit_debit = credit * 0.50
    loss_budget = min(credit * 1.50, max_loss_unit * 0.35)
    stop_debit = credit + loss_budget
    pnl = round((credit - debit) * qty - costs, 2)
    updated = {
        **position,
        "legs": marked_legs,
        "currentDebit": round(debit, 2),
        "profitTargetDebit": round(profit_debit, 2),
        "stopDebit": round(stop_debit, 2),
        "currentUnderlying": round(spot, 2) if spot is not None else None,
        "unrealizedPnl": pnl,
        "updatedAt": now.isoformat(),
    }
    lower = _float(position.get("shortPutStrike"))
    upper = _float(position.get("shortCallStrike"))
    breached = bool(spot is not None and ((lower is not None and spot <= lower) or (upper is not None and spot >= upper)))
    if breached:
        return None, _close_credit(updated, debit, "UNDERLYING_SHORT_STRIKE_BREACH", now)
    if debit <= profit_debit:
        return None, _close_credit(updated, debit, "PROFIT_TARGET_50PCT_CREDIT", now)
    if debit >= stop_debit:
        return None, _close_credit(updated, debit, "DEFINED_RISK_STOP", now)
    if now.astimezone(IST_ZONE).time().replace(tzinfo=None) >= SELLER_SQUARE_OFF_TIME:
        return None, _close_credit(updated, debit, "EOD_GAMMA_SQUAREOFF", now)
    return updated, None


def _new_position(row: dict[str, Any], now: datetime, sequence: int) -> dict[str, Any] | None:
    if row.get("strategyMode") == "SELL_PREMIUM":
        if now.astimezone(IST_ZONE).time().replace(tzinfo=None) > SELLER_ENTRY_CUTOFF:
            return None
        legs = [dict(leg) for leg in (row.get("legs") or []) if isinstance(leg, dict)]
        risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
        credit = _float(risk.get("entryCredit"))
        max_loss_unit = _float(risk.get("maxLossPerUnit"))
        max_loss_lot = _float(risk.get("maxLossPerLot"))
        estimated_costs = _float(risk.get("estimatedRoundTripCosts")) or 0.0
        lots = {int(_float(leg.get("lotSize")) or 0) for leg in legs}
        if (not legs or len(lots) != 1 or next(iter(lots), 0) < 1 or not credit or not max_loss_unit
                or not max_loss_lot or max_loss_lot > _seller_single_risk_cap()):
            return None
        lot = next(iter(lots))
        primary = next((leg for leg in legs if leg.get("action") == "SELL"), legs[0])
        return {
            "id": f"{now.astimezone(IST_ZONE).date().isoformat()}-{sequence:02d}-{row['key']}-SELL",
            "index": row["key"], "bucket": row["bucket"], "direction": row.get("direction"),
            "strategyMode": "SELL_PREMIUM", "strategyType": row.get("strategyType"),
            "symbol": primary.get("symbol"), "expiry": row.get("expiry"), "legs": legs,
            "quantity": lot, "lotSize": lot, "entryCredit": round(credit, 2),
            "currentDebit": round(credit, 2), "maxProfitPerLot": risk.get("maxProfitPerLot"),
            "estimatedRoundTripCosts": round(estimated_costs, 2),
            "maxLossPerUnit": round(max_loss_unit, 2), "maxLossPerLot": round(max_loss_lot, 2),
            "creditToRisk": risk.get("creditToRisk"), "lowerBreakEven": risk.get("lowerBreakEven"),
            "upperBreakEven": risk.get("upperBreakEven"), "shortPutStrike": risk.get("shortPutStrike"),
            "shortCallStrike": risk.get("shortCallStrike"), "score": row.get("score"),
            "status": "OPEN", "enteredAt": now.isoformat(), "updatedAt": now.isoformat(),
            "unrealizedPnl": 0.0, "source": row.get("dataSource"), "execution": "DEFINED_RISK_PAPER_ONLY",
            "entryBasis": "SELL_BID_BUY_ASK", "nakedRisk": False,
        }

    contract = row.get("contract") if isinstance(row.get("contract"), dict) else {}
    premium, lot = _float(contract.get("ltp")), _float(contract.get("lotSize"))
    if not premium or premium <= LONG_PREMIUM_STOP_POINTS or not lot or lot < 1:
        return None
    stop = premium - LONG_PREMIUM_STOP_POINTS
    target = premium + LONG_PREMIUM_TARGET_POINTS
    return {
        "id": f"{now.astimezone(IST_ZONE).date().isoformat()}-{sequence:02d}-{row['key']}",
        "index": row["key"], "bucket": row["bucket"], "direction": row["direction"],
        "symbol": contract.get("symbol"), "strike": contract.get("strike"), "expiry": contract.get("expiry"),
        "token": contract.get("token"), "exchange": contract.get("exchange"),
        "quantity": int(lot), "lotSize": int(lot), "entryPremium": round(premium, 2),
        "currentPremium": round(premium, 2), "peakPremium": round(premium, 2),
        "initialStopPremium": round(stop, 2), "effectiveStopPremium": round(stop, 2),
        "targetPremium": round(target, 2), "expectedR": LONG_PREMIUM_RISK_REWARD, "score": row.get("score"),
        "status": "OPEN", "enteredAt": now.isoformat(), "updatedAt": now.isoformat(), "markedAt": now.isoformat(),
        "nextMarkDueAt": datetime.fromtimestamp(now.timestamp() + LONG_PREMIUM_MARK_INTERVAL_SECONDS, tz=now.tzinfo).isoformat(),
        "unrealizedPnl": 0.0, "source": row.get("dataSource"), "execution": "PAPER_ONLY",
        "riskModel": "FIXED_OPTION_PREMIUM_POINTS_1_TO_2", "markIntervalSeconds": LONG_PREMIUM_MARK_INTERVAL_SECONDS,
        "stopDistancePoints": LONG_PREMIUM_STOP_POINTS, "targetDistancePoints": LONG_PREMIUM_TARGET_POINTS,
        "riskRewardRatio": LONG_PREMIUM_RISK_REWARD,
        "minuteMarks": [{"at": now.isoformat(), "premium": round(premium, 2), "pnl": 0.0, "source": "ENTRY_LOCK"}],
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
        if reason in {"TARGET", "PROFIT_TARGET_50PCT_CREDIT"}:
            mapped = "TARGET"
        elif pnl >= 0:
            mapped = "TRAILING_SL_PROFIT"
        else:
            mapped = "STOP_LOSS"
        if mapped == "STOP_LOSS":
            governor.sl_counts[key] = governor.sl_counts.get(key, 0) + 1
        governor.last_exits[key] = {"time": row.get("exitedAt"), "reason": mapped,
                                    "direction": row.get("direction"),
                                    "price": row.get("exitPremium") if row.get("exitPremium") is not None else row.get("exitDebit")}
    return governor


def reconcile_paper_book(
    radar: dict[str, Any], *, client: Any = None, now: datetime | None = None, persist: bool = True,
) -> dict[str, Any]:
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    session = clock.date().isoformat()
    with _PAPER_LOCK:
        book = _load_book(session)
        buy_candidates = radar.get("candidates") if isinstance(radar.get("candidates"), list) else []
        seller_candidates = radar.get("sellerCandidates") if isinstance(radar.get("sellerCandidates"), list) else []
        candidates = [*buy_candidates, *seller_candidates]
        _hydrate_locked_instruments(book["open"], candidates)

        due_positions = [
            position for position in book["open"]
            if position.get("strategyMode") == "SELL_PREMIUM" or _long_mark_due(position, clock)
        ]
        direct_marks, direct_error = _direct_locked_marks(client, due_positions)
        next_open: list[dict[str, Any]] = []
        closed_now: list[dict[str, Any]] = []
        for position in book["open"]:
            if position.get("strategyMode") == "SELL_PREMIUM":
                debit, marked_legs, mark_source = _credit_close_debit(position, candidates, direct_marks)
                if debit is None:
                    position["markStatus"] = "UNAVAILABLE"
                    position["markError"] = direct_error or "SPREAD_LEG_MARK_UNAVAILABLE"
                    next_open.append(position)
                    continue
                position["markSource"] = mark_source
                position["markedAt"] = clock.isoformat()
                position["markStatus"] = "LIVE"
                position["markError"] = direct_error if mark_source != "RADAR_EXECUTABLE_DEPTH" else None
                active, closed = _update_credit_open(position, debit, marked_legs, _spot_for(position, candidates), clock)
                if active:
                    next_open.append(active)
                if closed:
                    closed_now.append(closed)
                continue

            if not _long_mark_due(position, clock):
                next_open.append(position)
                continue

            mark = direct_marks.get(str(position.get("symbol") or ""))
            mark_source = "ANGEL_DIRECT_LOCKED_CONTRACT"
            if mark is None:
                mark = _mark_for(position, candidates)
                mark_source = "RADAR_CHAIN_FALLBACK"
            if mark is None:
                position["markStatus"] = "UNAVAILABLE"
                position["markError"] = direct_error
                position["lastMarkAttemptAt"] = clock.isoformat()
                next_open.append(position)
                continue
            position["markError"] = direct_error if mark_source != "ANGEL_DIRECT_LOCKED_CONTRACT" else None
            active, closed = _update_open(position, mark, clock, mark_source=mark_source)
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
                if position.get("strategyMode") == "SELL_PREMIUM":
                    open_seller_risk = sum(
                        float(item.get("maxLossPerLot") or 0)
                        for item in book["open"] if item.get("strategyMode") == "SELL_PREMIUM"
                    )
                    if open_seller_risk + float(position.get("maxLossPerLot") or 0) > _seller_portfolio_risk_cap():
                        continue
                book["open"].append(position)
                book["entryCount"] += 1
                open_indexes.add(str(row.get("key")))
                open_buckets.add(str(row.get("bucket")))

        open_pnl = round(sum(float(row.get("unrealizedPnl") or 0) for row in book["open"]), 2)
        realized = round(sum(float(row.get("pnl") or 0) for row in book["closed"]), 2)
        book.update({
            "updatedAt": clock.isoformat(),
            "openPnl": open_pnl,
            "realizedPnl": realized,
            "totalPnl": round(open_pnl + realized, 2),
            "dailyEntryCap": MAX_DAILY_ENTRIES,
            "marketOpen": _market_open(clock),
            "longPremiumRiskPolicy": {
                "markIntervalSeconds": LONG_PREMIUM_MARK_INTERVAL_SECONDS,
                "stopPoints": LONG_PREMIUM_STOP_POINTS,
                "targetPoints": LONG_PREMIUM_TARGET_POINTS,
                "riskReward": LONG_PREMIUM_RISK_REWARD,
            },
            "sellerRiskCaps": {"singleTrade": _seller_single_risk_cap(), "portfolio": _seller_portfolio_risk_cap()},
        })
        if persist:
            atomic_write_json(paper_book_path(), book)
        return book
