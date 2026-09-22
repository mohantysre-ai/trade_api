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
from .angel_index_stream import ANGEL_INDEX_STREAM
from .index_options_engine import (
    BUY_SLEEVE,
    MAX_CONCURRENT_TRADES,
    MAX_DAILY_ENTRIES,
    MIN_ELIGIBLE_SCORE,
    SELL_SLEEVE,
    IndexOptionReEntryGovernor,
    can_reenter_index_option,
    sleeve_of,
)
from .index_options_seller import SELLER_ENTRY_CUTOFF, SELLER_MIN_SCORE
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
# A locked contract is marked from the WebSocket cache while its last tick is
# younger than this. Only then does marking fall back to a REST quote, so a
# minute cycle no longer issues batch REST requests for every open position.
DEFAULT_MARK_STALE_SECONDS = 15.0
SUBSCRIPTION_OWNER_PREFIX = "paper:"


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


def _daily_entries_total(session_date: str, book_count: int) -> int:
    """Paper + durable strategy entries share one daily cap."""
    try:
        from .index_options.runtime import daily_entry_count
        return book_count + daily_entry_count(session_date)
    except Exception:
        return book_count


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


def _hydrate_locked_instruments(positions: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> int:
    """Resolve token/exchange for every locked contract; return resolved count.

    The contract identity is always taken from exchange evidence (radar chain or
    the Angel scrip master). Nothing is invented, and hydration works without
    today's radar candidates so the supervisor can mark an existing lock.
    """
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in candidates:
        for contract in row.get("chain") or []:
            if isinstance(contract, dict) and contract.get("symbol"):
                by_symbol[str(contract["symbol"])] = contract
    locked_instruments = [
        instrument
        for row in positions
        for instrument in _position_instruments(row)
        if isinstance(instrument, dict)
    ]
    unresolved = [row for row in locked_instruments if not row.get("token") or not row.get("exchange")]
    if unresolved:
        try:
            for raw in load_angel_scrip_master():
                symbol = str(raw.get("symbol") or "")
                if not symbol:
                    continue
                master_entry = {"token": raw.get("token"), "exchange": raw.get("exch_seg")}
                if symbol in by_symbol:
                    existing = by_symbol[symbol]
                    if not existing.get("token") or not existing.get("exchange"):
                        if raw.get("token"):
                            existing["token"] = raw.get("token")
                        if raw.get("exch_seg"):
                            existing["exchange"] = raw.get("exch_seg")
                else:
                    by_symbol[symbol] = master_entry
        except Exception:
            pass
    resolved = 0
    for position in positions:
        instruments = [position, *(leg for leg in (position.get("legs") or []) if isinstance(leg, dict))]
        for instrument in instruments:
            contract = by_symbol.get(str(instrument.get("symbol") or "")) or {}
            if not instrument.get("token") and contract.get("token"):
                instrument["token"] = str(contract["token"])
                resolved += 1
            if not instrument.get("exchange") and (contract.get("exchange") or contract.get("exch_seg")):
                instrument["exchange"] = str(contract.get("exchange") or contract.get("exch_seg"))
                resolved += 1
    return resolved


def _mark_stale_seconds() -> float:
    return _positive_env_float("INDEX_OPTIONS_MARK_STALE_SECONDS", DEFAULT_MARK_STALE_SECONDS)


def _position_instruments(position: dict[str, Any]) -> list[dict[str, Any]]:
    """Every contract that backs one position (all legs for a seller spread)."""
    if sleeve_of(position) == SELL_SLEEVE:
        return [leg for leg in (position.get("legs") or []) if isinstance(leg, dict)]
    return [position]


def _locked_instruments(positions: list[dict[str, Any]]) -> list[Instrument]:
    instruments: list[Instrument] = []
    seen: set[str] = set()
    for position in positions:
        for leg in _position_instruments(position):
            symbol, token, exchange = (
                str(leg.get("symbol") or ""), str(leg.get("token") or ""), str(leg.get("exchange") or ""),
            )
            if symbol and token and exchange and symbol not in seen:
                instruments.append(Instrument(f"PAPER:{symbol}", exchange, symbol, token, symbol))
                seen.add(symbol)
    return instruments


def _stream_marks(
    instruments: list[Instrument], *, max_age_seconds: float,
) -> tuple[dict[str, float], dict[str, dict[str, Any]], list[Instrument]]:
    """Read the in-memory WebSocket cache; return fresh marks plus stale contracts."""
    marks: dict[str, float] = {}
    depth: dict[str, dict[str, Any]] = {}
    pending: list[Instrument] = []
    for instrument in instruments:
        row = ANGEL_INDEX_STREAM.quote_row(instrument.token)
        mark = _float((row or {}).get("ltp"))
        age = (row or {}).get("ageSeconds")
        fresh = bool(row) and isinstance(age, (int, float)) and age <= max_age_seconds and mark is not None and mark > 0
        if not fresh:
            pending.append(instrument)
            continue
        marks[instrument.tradingsymbol] = mark
        depth[instrument.tradingsymbol] = {
            "mark": mark,
            "bid": _float(row.get("bestBidPrice")),
            "ask": _float(row.get("bestAskPrice")),
            "source": "ANGEL_WEBSOCKET",
            "ageSeconds": age,
            "stale": False,
        }
    return marks, depth, pending


def _rest_marks(client: Any, instruments: list[Instrument]) -> tuple[dict[str, float], str | None]:
    """REST quote for the stale or missing contracts only."""
    if client is None or not instruments:
        return {}, None
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


def _locked_marks(
    client: Any, positions: list[dict[str, Any]],
) -> tuple[dict[str, float], dict[str, dict[str, Any]], str | None, dict[str, Any]]:
    """Mark locked contracts: WebSocket cache first, REST only when stale.

    An open position whose contracts are still streaming live depth never
    triggers a batch REST quote, so the minute cadence no longer re-quotes every
    locked contract over REST.
    """
    instruments = _locked_instruments(positions)
    pipeline = {"streamMarks": 0, "restMarks": 0, "staleContracts": 0, "restRequested": 0}
    if not instruments:
        return {}, {}, ("LOCKED_CONTRACT_TOKEN_UNAVAILABLE" if positions else None), pipeline
    stream_marks, depth, pending = _stream_marks(instruments, max_age_seconds=_mark_stale_seconds())
    rest_marks: dict[str, float] = {}
    rest_error: str | None = None
    if pending and client is not None:
        rest_marks, rest_error = _rest_marks(client, pending)
    for instrument in pending:
        mark = rest_marks.get(instrument.tradingsymbol)
        if mark is None:
            continue
        depth[instrument.tradingsymbol] = {
            "mark": mark, "bid": None, "ask": None,
            "source": "ANGEL_DIRECT_LOCKED_CONTRACT", "ageSeconds": None, "stale": True,
        }
    pipeline.update({
        "streamMarks": len(stream_marks),
        "restMarks": len(rest_marks),
        "staleContracts": len(pending),
        "restRequested": len(pending) if client is not None else 0,
    })
    return {**rest_marks, **stream_marks}, depth, rest_error, pipeline


def _direct_locked_marks(client: Any, positions: list[dict[str, Any]]) -> tuple[dict[str, float], str | None]:
    """Compatibility wrapper returning only the mark map and error."""
    marks, _, error, _ = _locked_marks(client, positions)
    return marks, error


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


def _record_long_mark(
    position: dict[str, Any], mark: float, now: datetime, source: str,
    *, quality: str = "LIVE", data_age_seconds: float | None = None,
    bid: float | None = None, ask: float | None = None,
) -> dict[str, Any]:
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
        "markQuality": quality,
        "markDataAgeSeconds": round(data_age_seconds, 3) if isinstance(data_age_seconds, (int, float)) else None,
        "executableBid": round(bid, 2) if isinstance(bid, (int, float)) else None,
        "executableAsk": round(ask, 2) if isinstance(ask, (int, float)) else None,
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
    quality: str = "LIVE", data_age_seconds: float | None = None,
    bid: float | None = None, ask: float | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    stop = float(position["initialStopPremium"])
    target = float(position["targetPremium"])
    updated = _record_long_mark(
        position, mark, now, mark_source,
        quality=quality, data_age_seconds=data_age_seconds, bid=bid, ask=ask,
    )
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
    position: dict[str, Any], candidates: list[dict[str, Any]],
    direct_marks: dict[str, float], depth: dict[str, dict[str, Any]] | None = None,
) -> tuple[float | None, list[dict[str, Any]], str, list[str]]:
    """Price seller exits conservatively: buy shorts at ask, sell hedges at bid.

    Every leg is repriced from one consistent source ladder: WebSocket depth →
    radar executable depth → direct REST LTP → the leg's last known booked
    price. A single stale leg therefore no longer invalidates an otherwise valid
    spread; it is reused and reported instead, and only a leg with no price at
    all makes the spread unpriceable.
    """
    depth = depth or {}
    marked: list[dict[str, Any]] = []
    stale_legs: list[str] = []
    stream_used = False
    fallback_used = False
    for leg in position.get("legs") or []:
        if not isinstance(leg, dict):
            return None, [], "UNAVAILABLE", []
        symbol = str(leg.get("symbol") or "")
        action = str(leg.get("action") or "").upper()
        executable = _float((depth.get(symbol) or {}).get("ask" if action == "SELL" else "bid"))
        source = "ANGEL_WEBSOCKET_DEPTH"
        stream_used = stream_used or executable is not None
        if executable is None:
            quote = _candidate_contract(symbol, candidates)
            executable = _float(quote.get("bestAsk" if action == "SELL" else "bestBid"))
            source = "RADAR_EXECUTABLE_DEPTH"
        if executable is None:
            executable = direct_marks.get(symbol)
            source = "ANGEL_DIRECT_LTP_FALLBACK"
        if executable is None:
            executable = _float(leg.get("currentPrice"))
            source = "BOOK_LAST_KNOWN_LEG"
        if executable is None or executable <= 0:
            return None, [], "UNAVAILABLE", []
        if source == "BOOK_LAST_KNOWN_LEG":
            stale_legs.append(symbol)
        fallback_used = fallback_used or source != "ANGEL_WEBSOCKET_DEPTH"
        marked.append({**leg, "currentPrice": round(executable, 2), "markSource": source})
    debit = sum(float(leg["currentPrice"]) for leg in marked if leg.get("action") == "SELL") \
        - sum(float(leg["currentPrice"]) for leg in marked if leg.get("action") == "BUY")
    if stale_legs:
        spread_source = "DEGRADED_LAST_KNOWN_LEG"
    elif stream_used and not fallback_used:
        spread_source = "ANGEL_WEBSOCKET_DEPTH"
    elif stream_used:
        spread_source = "ANGEL_WEBSOCKET_WITH_FALLBACK"
    else:
        spread_source = "RADAR_EXECUTABLE_DEPTH"
    return round(max(0.0, debit), 2), marked, spread_source, stale_legs


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
    *, mark_source: str = "RADAR_EXECUTABLE_DEPTH", stale_legs: list[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    credit, qty = float(position["entryCredit"]), int(position["quantity"])
    costs = float(position.get("estimatedRoundTripCosts") or 0)
    max_loss_unit = float(position["maxLossPerUnit"])
    profit_debit = credit * 0.50
    loss_budget = min(credit * 1.50, max_loss_unit * 0.35)
    stop_debit = credit + loss_budget
    pnl = round((credit - debit) * qty - costs, 2)
    stale = list(stale_legs or [])
    updated = {
        **position,
        "legs": marked_legs,
        "currentDebit": round(debit, 2),
        "profitTargetDebit": round(profit_debit, 2),
        "stopDebit": round(stop_debit, 2),
        "currentUnderlying": round(spot, 2) if spot is not None else None,
        "unrealizedPnl": pnl,
        "updatedAt": now.isoformat(),
        "markSource": mark_source,
        "spreadMarkQuality": "DEGRADED_STALE_LEG" if stale else "FRESH",
        "spreadStaleLegs": stale,
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


def _new_position(
    row: dict[str, Any], now: datetime, sequence: int, *,
    depth: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if sleeve_of(row) == SELL_SLEEVE:
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
            "markQuality": "FRESH", "spreadMarkQuality": "FRESH", "spreadStaleLegs": [],
        }

    contract = row.get("contract") if isinstance(row.get("contract"), dict) else {}
    quote = (depth or {}).get(str(contract.get("symbol") or "")) or {}
    lot = _float(contract.get("lotSize"))
    # Executable buy price: pay the streamed ask when live depth exists, else the
    # locked contract LTP. The fixed 20/40 premium points stay relative to the
    # price actually used for the entry.
    ask = _float(quote.get("ask"))
    bid = _float(quote.get("bid"))
    if ask is not None and ask > 0:
        premium, pricing = ask, "ANGEL_WEBSOCKET_ASK"
    else:
        premium, pricing = _float(contract.get("ltp")), "LOCKED_CONTRACT_LTP"
    if not premium or premium <= LONG_PREMIUM_STOP_POINTS or not lot or lot < 1:
        return None
    stop = premium - LONG_PREMIUM_STOP_POINTS
    target = premium + LONG_PREMIUM_TARGET_POINTS
    return {
        "id": f"{now.astimezone(IST_ZONE).date().isoformat()}-{sequence:02d}-{row['key']}",
        "index": row["key"], "bucket": row["bucket"], "direction": row["direction"],
        "strategyMode": BUY_SLEEVE, "strategyType": row.get("strategyType"),
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
        "entryPricingSource": pricing,
        "entryBid": round(bid, 2) if bid is not None else None,
        "entryAsk": round(ask, 2) if ask is not None else None,
        "markQuality": "FRESH_WEBSOCKET" if pricing == "ANGEL_WEBSOCKET_ASK" else "CONTRACT_LTP",
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


def _cross_book_owner(row: dict[str, Any], session_date: str) -> str | None:
    symbol = str(row.get("ownershipSymbol") or row.get("key") or "").upper().strip()
    if not symbol:
        return "INVALID"
    from .cross_book_resolution import (
        intraday_blocks_swing_symbol,
        swing_locked_symbols_for_day,
    )

    if symbol in swing_locked_symbols_for_day(session_date):
        return "SWING"
    if intraday_blocks_swing_symbol(symbol, session_date):
        return "INTRADAY"
    return None


def _reentry_confirmations(row: dict[str, Any]) -> dict[str, bool]:
    gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
    breakout = all(gates.get(name) is True for name in ("fresh", "structure", "breakout"))
    oi = gates.get("futuresOi") is True
    breadth = gates.get("breadth") is True
    return {
        "fresh_breakout_confirmed": breakout,
        "oi_aligned": oi,
        "breadth_aligned": breadth,
        "opposite_confirmation": breakout,
    }


def _position_id(now: datetime, sequence: int, row: dict[str, Any]) -> str:
    stamp = now.astimezone(IST_ZONE).date().isoformat()
    suffix = "-SELL" if sleeve_of(row) == SELL_SLEEVE else ""
    return f"{stamp}-{sequence:02d}-{row['key']}{suffix}"


def _score_lock_ok(row: dict[str, Any], sleeve: str) -> bool:
    """Lock immediately once the score is at or above the sleeve's own floor.

    The floor is the row's audited ``scoreFloor`` (the seller sleeve keeps its
    stricter floor); the long-premium floor is the documented 70.
    """
    score = _float(row.get("score"))
    if score is None:
        return False
    floor = _float(row.get("scoreFloor"))
    if floor is None:
        floor = SELLER_MIN_SCORE if sleeve == SELL_SLEEVE else MIN_ELIGIBLE_SCORE
    return score >= floor


def _duplicate_open_position(positions: list[dict[str, Any]], row: dict[str, Any]) -> str | None:
    """Return the open position id when this strategy is already open."""
    index = str(row.get("key") or "")
    sleeve = sleeve_of(row)
    identity = str(row.get("strategyType") or row.get("strategyId") or "")
    contract = row.get("contract") if isinstance(row.get("contract"), dict) else {}
    symbol = str(contract.get("symbol") or row.get("symbol") or "")
    for position in positions:
        if sleeve_of(position) != sleeve or str(position.get("index") or "") != index:
            continue
        if identity and identity == str(position.get("strategyType") or ""):
            return str(position.get("id") or "OPEN")
        if symbol and symbol == str(position.get("symbol") or ""):
            return str(position.get("id") or "OPEN")
    return None


def _sleeve_locks(positions: list[dict[str, Any]]) -> dict[str, dict[str, set[str]]]:
    """Per-sleeve index and correlation-bucket locks from the open book.

    BUY and SELL never share a lock, which is what allows a long-premium paper
    position and a defined-risk premium-selling structure on the same index.
    """
    locks: dict[str, dict[str, set[str]]] = {
        BUY_SLEEVE: {"indexes": set(), "buckets": set()},
        SELL_SLEEVE: {"indexes": set(), "buckets": set()},
    }
    for position in positions:
        lock = locks[sleeve_of(position)]
        lock["indexes"].add(str(position.get("index") or ""))
        lock["buckets"].add(str(position.get("bucket") or ""))
    return locks


def _unique_radar_rows(radar: dict[str, Any]) -> list[dict[str, Any]]:
    """Deduplicate the radar's selected and modular pools by strategy identity."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*(radar.get("selected") or []), *(radar.get("modularSelected") or [])]:
        if not isinstance(row, dict):
            continue
        identity = str(row.get("strategyId") or row.get("strategyType") or "") + "|" + str(row.get("key") or "")
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(row)
    return rows


def _select_sleeve_entries(
    rows: list[dict[str, Any]], book: dict[str, Any], locks: dict[str, set[str]], *,
    session: str, clock: datetime, depth: dict[str, dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Select one sleeve's own best entries, consulting only that sleeve.

    Portfolio limits are deliberately absent here: they are applied after both
    sleeves have independently finished selecting, so a BUY can never consume
    the index/bucket or the admission slot a SELL candidate needs.
    """
    ranked = sorted(
        (row for row in rows if isinstance(row, dict)),
        key=lambda row: _float(row.get("score")) or 0.0,
        reverse=True,
    )
    entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    used_indexes: set[str] = set()
    used_buckets: set[str] = set()
    governor = _governor(book)
    for row in ranked:
        sleeve = sleeve_of(row)
        index, bucket = str(row.get("key") or ""), str(row.get("bucket") or "")
        if row.get("state") != "ELIGIBLE":
            continue
        if not _score_lock_ok(row, sleeve):
            row["entryBlockedBy"] = "SCORE_BELOW_LOCK_THRESHOLD"
            continue
        if index in locks["indexes"] or index in used_indexes:
            row["entryBlockedBy"] = "SLEEVE_INDEX_ALREADY_LOCKED"
            continue
        if bucket in locks["buckets"] or bucket in used_buckets:
            row["entryBlockedBy"] = "SLEEVE_CORRELATION_BUCKET_LOCKED"
            continue
        duplicate = _duplicate_open_position(book["open"], row)
        if duplicate:
            row["entryBlockedBy"] = "DUPLICATE_STRATEGY_OPEN"
            row["duplicateOfPositionId"] = duplicate
            continue
        owner = _cross_book_owner(row, session)
        if owner:
            row["ownershipBlockedBy"] = owner
            continue
        decision = can_reenter_index_option(
            index, str(row.get("direction") or ""), clock, governor,
            **_reentry_confirmations(row),
        )
        if not decision.get("allowed"):
            row["entryBlockedBy"] = str(decision.get("reason") or "REENTRY_BLOCKED")
            continue
        position = _new_position(row, clock, 1, depth=depth)
        if position is None:
            row["entryBlockedBy"] = "POSITION_CONSTRUCTION_FAILED"
            continue
        entries.append((row, position))
        used_indexes.add(index)
        used_buckets.add(bucket)
    return entries


def _interleave_sleeve_entries(
    entries_by_sleeve: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Round-robin the sleeves so each sleeve's best candidate is admitted first."""
    ordered: list[tuple[dict[str, Any], dict[str, Any]]] = []
    deepest = max((len(entries) for entries in entries_by_sleeve.values()), default=0)
    for rank in range(deepest):
        for sleeve in (BUY_SLEEVE, SELL_SLEEVE):
            entries = entries_by_sleeve.get(sleeve) or []
            if rank < len(entries):
                ordered.append(entries[rank])
    return ordered


def _candidate_instruments(rows: list[dict[str, Any]]) -> list[Instrument]:
    """Long-premium candidate contracts that can be priced from the stream."""
    instruments: list[Instrument] = []
    seen: set[str] = set()
    for row in rows:
        contract = row.get("contract") if isinstance(row.get("contract"), dict) else {}
        symbol, token, exchange = (
            str(contract.get("symbol") or ""), str(contract.get("token") or ""), str(contract.get("exchange") or ""),
        )
        if symbol and token and exchange and symbol not in seen:
            instruments.append(Instrument(f"PAPER:{symbol}", exchange, symbol, token, symbol))
            seen.add(symbol)
    return instruments


def _candidate_stream_depth(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Executable depth for candidate contracts, straight from the WebSocket cache."""
    _, depth, _ = _stream_marks(_candidate_instruments(rows), max_age_seconds=_mark_stale_seconds())
    return depth


def _subscription_instruments(position: dict[str, Any]) -> list[dict[str, Any]]:
    """Stream instrument descriptors for one open position (all spread legs)."""
    instruments: list[dict[str, Any]] = []
    for leg in _position_instruments(position):
        token, exchange = str(leg.get("token") or ""), str(leg.get("exchange") or "")
        if not token or not exchange:
            continue
        instruments.append({
            "exchange": exchange, "token": token, "symbol": leg.get("symbol"),
            "indexKey": position.get("index"), "kind": "OPTION",
        })
    return instruments


def _sync_position_subscriptions(
    client: Any, positions: list[dict[str, Any]], closed_positions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Reference-count stream subscriptions for every open paper position.

    A locked contract stays subscribed until the last position holding it closes:
    re-retaining is idempotent across reconnects, and nothing is unsubscribed
    while a position on that contract is still open.
    """
    for closed in closed_positions or []:
        ANGEL_INDEX_STREAM.release_owner(f"{SUBSCRIPTION_OWNER_PREFIX}{closed.get('id')}")
    payload: dict[str, Any] = {
        "owners": len(ANGEL_INDEX_STREAM.retained_owners()),
        "contracts": 0,
        "released": len(closed_positions or []),
    }
    if not positions:
        return payload
    if client is None or not callable(getattr(client, "connect", None)):
        payload["reason"] = "CLIENT_UNAVAILABLE"
        return payload
    for position in positions:
        instruments = _subscription_instruments(position)
        if not instruments:
            continue
        payload["contracts"] += ANGEL_INDEX_STREAM.retain(
            client, instruments, owner=f"{SUBSCRIPTION_OWNER_PREFIX}{position.get('id')}",
        )
    return payload


def hydrate_open_position_subscriptions(
    client: Any, *, now: datetime | None = None, persist: bool = True,
) -> dict[str, Any]:
    """Resolve locked tokens and take stream references before marking.

    Reads the durable paper book only, so an existing position is always marked
    from live WebSocket data even when today's radar candidates are empty.
    """
    clock = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    session = clock.date().isoformat()
    with _PAPER_LOCK:
        book = _load_book(session)
        if not book["open"]:
            return {"openPositions": 0, "resolvedInstruments": 0, "retainedContracts": 0,
                    "stream": ANGEL_INDEX_STREAM.status()}
        resolved = _hydrate_locked_instruments(book["open"], [])
        subscriptions = _sync_position_subscriptions(client, book["open"])
        if resolved and persist:
            atomic_write_json(paper_book_path(), book)
    return {
        "openPositions": len(book["open"]),
        "resolvedInstruments": resolved,
        "retainedContracts": subscriptions.get("contracts", 0),
        "stream": ANGEL_INDEX_STREAM.status(),
    }


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
            if sleeve_of(position) == SELL_SLEEVE or _long_mark_due(position, clock)
        ]
        locked_marks, mark_depth, mark_error, mark_pipeline = _locked_marks(client, due_positions)
        next_open: list[dict[str, Any]] = []
        closed_now: list[dict[str, Any]] = []
        for position in book["open"]:
            if sleeve_of(position) == SELL_SLEEVE:
                debit, marked_legs, spread_source, stale_legs = _credit_close_debit(
                    position, candidates, locked_marks, mark_depth,
                )
                if debit is None:
                    position["markStatus"] = "UNAVAILABLE"
                    position["markError"] = mark_error or "SPREAD_LEG_MARK_UNAVAILABLE"
                    next_open.append(position)
                    continue
                position["markSource"] = spread_source
                position["markedAt"] = clock.isoformat()
                position["markStatus"] = "LIVE"
                position["markError"] = (
                    mark_error if mark_error and spread_source not in {"RADAR_EXECUTABLE_DEPTH", "ANGEL_WEBSOCKET_DEPTH"}
                    else None
                )
                active, closed = _update_credit_open(
                    position, debit, marked_legs, _spot_for(position, candidates), clock,
                    mark_source=spread_source, stale_legs=stale_legs,
                )
                if active:
                    next_open.append(active)
                if closed:
                    closed_now.append(closed)
                continue

            if not _long_mark_due(position, clock):
                next_open.append(position)
                continue

            symbol = str(position.get("symbol") or "")
            meta = mark_depth.get(symbol) or {}
            mark = locked_marks.get(symbol)
            if mark is None:
                mark = _mark_for(position, candidates)
                mark_source = "RADAR_CHAIN_FALLBACK"
            elif meta.get("source") == "ANGEL_WEBSOCKET":
                mark_source = "ANGEL_WEBSOCKET_LOCKED_CONTRACT"
            else:
                mark_source = "ANGEL_DIRECT_LOCKED_CONTRACT"
            if mark is None:
                position["markStatus"] = "UNAVAILABLE"
                position["markError"] = mark_error
                position["lastMarkAttemptAt"] = clock.isoformat()
                next_open.append(position)
                continue
            position["markError"] = mark_error if mark_source != "ANGEL_DIRECT_LOCKED_CONTRACT" else None
            quality = (
                "FRESH_WEBSOCKET" if mark_source == "ANGEL_WEBSOCKET_LOCKED_CONTRACT"
                else "REST_FALLBACK" if mark_source == "ANGEL_DIRECT_LOCKED_CONTRACT"
                else "RADAR_FALLBACK"
            )
            active, closed = _update_open(
                position, mark, clock, mark_source=mark_source, quality=quality,
                data_age_seconds=meta.get("ageSeconds"),
                bid=_float(meta.get("bid")), ask=_float(meta.get("ask")),
            )
            if active:
                next_open.append(active)
            if closed:
                closed_now.append(closed)

        book["open"] = next_open
        book["closed"].extend(closed_now)
        book["entryCount"] = len(book["open"]) + len(book["closed"])

        sleeve_locks = _sleeve_locks(book["open"])
        entries_by_sleeve: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {
            BUY_SLEEVE: [], SELL_SLEEVE: [],
        }
        if _market_open(clock):
            radar_rows = _unique_radar_rows(radar)
            # Executable entry depth for the BUY sleeve straight from the stream
            # cache; no REST quote is issued for candidates.
            buy_rows = [row for row in radar_rows if sleeve_of(row) == BUY_SLEEVE]
            entry_depth = {**_candidate_stream_depth(buy_rows), **mark_depth}
            # 1. Each sleeve independently selects its own best candidate(s)
            #    against its own index/bucket locks.
            for sleeve in (BUY_SLEEVE, SELL_SLEEVE):
                entries_by_sleeve[sleeve] = _select_sleeve_entries(
                    [row for row in radar_rows if sleeve_of(row) == sleeve],
                    book, sleeve_locks[sleeve],
                    session=session, clock=clock, depth=entry_depth,
                )
            # 2. Only now are the portfolio limits applied, round-robin across
            #    sleeves so one sleeve's second pick cannot starve the other
            #    sleeve's first pick.
            for row, position in _interleave_sleeve_entries(entries_by_sleeve):
                sleeve = sleeve_of(row)
                if _daily_entries_total(session, book["entryCount"]) >= MAX_DAILY_ENTRIES:
                    row["entryBlockedBy"] = "MAX_DAILY_ENTRIES_REACHED"
                    continue
                if len(book["open"]) >= MAX_CONCURRENT_TRADES:
                    row["entryBlockedBy"] = "MAX_CONCURRENT_TRADES_REACHED"
                    continue
                if sleeve == SELL_SLEEVE:
                    open_seller_risk = sum(
                        float(item.get("maxLossPerLot") or 0)
                        for item in book["open"] if sleeve_of(item) == SELL_SLEEVE
                    )
                    if open_seller_risk + float(position.get("maxLossPerLot") or 0) > _seller_portfolio_risk_cap():
                        row["entryBlockedBy"] = "SELLER_PORTFOLIO_RISK_CAP"
                        continue
                position["id"] = _position_id(clock, book["entryCount"] + 1, row)
                book["open"].append(position)
                book["entryCount"] += 1
                sleeve_locks[sleeve]["indexes"].add(str(row.get("key")))
                sleeve_locks[sleeve]["buckets"].add(str(row.get("bucket")))

        subscriptions = _sync_position_subscriptions(client, book["open"], closed_now)

        open_pnl = round(sum(float(row.get("unrealizedPnl") or 0) for row in book["open"]), 2)
        realized = round(sum(float(row.get("pnl") or 0) for row in book["closed"]), 2)
        book.update({
            "updatedAt": clock.isoformat(),
            "openPnl": open_pnl,
            "realizedPnl": realized,
            "totalPnl": round(open_pnl + realized, 2),
            "dailyEntryCap": MAX_DAILY_ENTRIES,
            "marketOpen": _market_open(clock),
            "sleeveLocks": {
                sleeve: {
                    "indexes": sorted(lock["indexes"]),
                    "buckets": sorted(lock["buckets"]),
                }
                for sleeve, lock in sleeve_locks.items()
            },
            "markPipeline": mark_pipeline,
            "subscriptions": subscriptions,
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
