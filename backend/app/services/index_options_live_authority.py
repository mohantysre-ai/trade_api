"""Runtime authority patch for Index Options V2.

Keeps the existing deterministic scoring/construction code, but fixes three
execution-boundary defects in one place:
* BUY_PREMIUM and SELL_PREMIUM get independent selection/correlation sleeves.
* the durable paper book uses strategy-mode aware ownership/governor identities.
* already-locked option legs are subscribed/marked WebSocket-first, with REST
  retained only as a cold/stale fallback.

Paper only: this module never invokes a broker order API.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

_INSTALLED = False


def _mode(row: dict[str, Any]) -> str:
    return str(row.get("strategyMode") or "BUY_PREMIUM").upper()


def _identity(row: dict[str, Any]) -> str:
    return f"{_mode(row)}:{str(row.get('key') or row.get('index') or '').upper()}"


def _rebalance_radar(radar: dict[str, Any], max_concurrent: int) -> dict[str, Any]:
    """Prevent one strategy sleeve from starving the other at selection time."""
    eligible = [
        row for row in [*(radar.get("candidates") or []), *(radar.get("sellerCandidates") or [])]
        if isinstance(row, dict) and row.get("eligible") and row.get("state") == "ELIGIBLE"
    ]
    by_mode: dict[str, list[dict[str, Any]]] = {"BUY_PREMIUM": [], "SELL_PREMIUM": []}
    for row in eligible:
        by_mode.setdefault(_mode(row), []).append(row)
    for rows in by_mode.values():
        rows.sort(key=lambda item: float(item.get("score") or 0), reverse=True)

    selected: list[dict[str, Any]] = []
    used: dict[str, dict[str, set[str]]] = {}

    def admit(row: dict[str, Any]) -> bool:
        mode = _mode(row)
        state = used.setdefault(mode, {"indexes": set(), "buckets": set()})
        key, bucket = str(row.get("key") or ""), str(row.get("bucket") or "")
        if key in state["indexes"] or bucket in state["buckets"]:
            return False
        selected.append(row)
        state["indexes"].add(key)
        state["buckets"].add(bucket)
        return True

    # Reserve opportunity for both sleeves when both have a safe executable setup.
    for mode in ("BUY_PREMIUM", "SELL_PREMIUM"):
        if len(selected) >= max_concurrent:
            break
        rows = by_mode.get(mode) or []
        if rows:
            admit(rows[0])

    # Fill unused capacity by score, while retaining per-sleeve correlation limits.
    remainder = sorted(eligible, key=lambda item: float(item.get("score") or 0), reverse=True)
    for row in remainder:
        if len(selected) >= max_concurrent:
            break
        if row in selected:
            continue
        admit(row)

    radar["selected"] = selected
    radar["selectedBySleeve"] = {
        mode: [row for row in selected if _mode(row) == mode]
        for mode in ("BUY_PREMIUM", "SELL_PREMIUM")
    }
    radar["selectionPolicy"] = "INDEPENDENT_BUY_SELL_SLEEVES_GLOBAL_MAX_2"
    return radar


def _stream_marks(paper: Any, client: Any, positions: list[dict[str, Any]]) -> tuple[dict[str, float], str | None]:
    """Subscribe locked legs and consume fresh in-memory ticks before REST."""
    from .angel_index_stream import ANGEL_INDEX_STREAM

    instruments: list[dict[str, str]] = []
    symbols_by_token: dict[str, str] = {}
    for position in positions:
        legs = (position.get("legs") or []) if _mode(position) == "SELL_PREMIUM" else [position]
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            symbol = str(leg.get("symbol") or "")
            token = str(leg.get("token") or "")
            exchange = str(leg.get("exchange") or "")
            if symbol and token and exchange:
                instruments.append({
                    "exchange": exchange,
                    "token": token,
                    "indexKey": str(position.get("index") or ""),
                    "kind": "OPTION",
                })
                symbols_by_token[token] = symbol
    if client is not None and instruments:
        ANGEL_INDEX_STREAM.ensure(client, instruments)

    marks: dict[str, float] = {}
    for token, symbol in symbols_by_token.items():
        quote = ANGEL_INDEX_STREAM.quote(token)
        mark = paper._float((quote or {}).get("ltp"))
        if mark is not None and mark > 0:
            marks[symbol] = mark

    missing_positions: list[dict[str, Any]] = []
    for position in positions:
        legs = (position.get("legs") or []) if _mode(position) == "SELL_PREMIUM" else [position]
        if any(str(leg.get("symbol") or "") not in marks for leg in legs if isinstance(leg, dict)):
            missing_positions.append(position)
    if missing_positions:
        fallback, error = paper._direct_locked_marks(client, missing_positions)
        for symbol, mark in fallback.items():
            marks.setdefault(symbol, mark)
        return marks, error
    return marks, None


def _try_new_position(paper: Any, row: dict[str, Any], now: datetime, sequence: int) -> tuple[dict[str, Any] | None, str]:
    position = paper._new_position(row, now, sequence)
    if position is not None:
        return position, "LOCKED"
    if _mode(row) == "SELL_PREMIUM":
        if now.astimezone(paper.IST_ZONE).time().replace(tzinfo=None) > paper.SELLER_ENTRY_CUTOFF:
            return None, "SELLER_ENTRY_CUTOFF"
        risk = row.get("risk") if isinstance(row.get("risk"), dict) else {}
        max_loss = paper._float(risk.get("maxLossPerLot"))
        if max_loss and max_loss > paper._seller_single_risk_cap():
            return None, "SELLER_SINGLE_RISK_CAP"
        return None, "SELLER_CONSTRUCTION_OR_RISK_INVALID"
    contract = row.get("contract") if isinstance(row.get("contract"), dict) else {}
    premium, lot = paper._float(contract.get("ltp")), paper._float(contract.get("lotSize"))
    if not premium or premium <= 0:
        return None, "BUY_PREMIUM_INVALID_PRICE"
    if not lot or lot < 1:
        return None, "BUY_PREMIUM_INVALID_LOT"
    # A score-qualified executable contract must not silently disappear merely
    # because premium is <= the legacy fixed 20-point stop. Preserve 1:2 risk
    # while capping the stop at 50% of premium and at the legacy 20-point max.
    distance = min(paper.LONG_PREMIUM_STOP_POINTS, max(0.5, premium * 0.50))
    target_distance = distance * paper.LONG_PREMIUM_RISK_REWARD
    stop, target = premium - distance, premium + target_distance
    return {
        "id": f"{now.astimezone(paper.IST_ZONE).date().isoformat()}-{sequence:02d}-{row['key']}",
        "index": row["key"], "bucket": row["bucket"], "direction": row["direction"],
        "strategyMode": "BUY_PREMIUM", "strategyType": row.get("strategyType"),
        "symbol": contract.get("symbol"), "strike": contract.get("strike"), "expiry": contract.get("expiry"),
        "token": contract.get("token"), "exchange": contract.get("exchange"),
        "quantity": int(lot), "lotSize": int(lot), "entryPremium": round(premium, 2),
        "currentPremium": round(premium, 2), "peakPremium": round(premium, 2),
        "initialStopPremium": round(stop, 2), "effectiveStopPremium": round(stop, 2),
        "targetPremium": round(target, 2), "expectedR": paper.LONG_PREMIUM_RISK_REWARD,
        "score": row.get("score"), "status": "OPEN", "enteredAt": now.isoformat(),
        "updatedAt": now.isoformat(), "markedAt": now.isoformat(), "unrealizedPnl": 0.0,
        "source": row.get("dataSource"), "execution": "PAPER_ONLY",
        "riskModel": "ADAPTIVE_OPTION_PREMIUM_POINTS_1_TO_2",
        "markIntervalSeconds": paper.LONG_PREMIUM_MARK_INTERVAL_SECONDS,
        "stopDistancePoints": round(distance, 2), "targetDistancePoints": round(target_distance, 2),
        "riskRewardRatio": paper.LONG_PREMIUM_RISK_REWARD,
        "minuteMarks": [{"at": now.isoformat(), "premium": round(premium, 2), "pnl": 0.0, "source": "ENTRY_LOCK"}],
    }, "LOCKED_ADAPTIVE_LOW_PREMIUM_RISK"


def _governor_for_mode(paper: Any, book: dict[str, Any], mode: str) -> Any:
    filtered = {
        "open": [row for row in (book.get("open") or []) if _mode(row) == mode],
        "closed": [row for row in (book.get("closed") or []) if _mode(row) == mode],
    }
    return paper._governor(filtered)


def _reconcile(radar: dict[str, Any], *, client: Any = None, now: datetime | None = None, persist: bool = True) -> dict[str, Any]:
    from . import index_options_paper as paper

    clock = (now or datetime.now(paper.IST_ZONE)).astimezone(paper.IST_ZONE)
    session = clock.date().isoformat()
    with paper._PAPER_LOCK:
        book = paper._load_book(session)
        book.setdefault("entryAudit", [])
        buy_candidates = radar.get("candidates") if isinstance(radar.get("candidates"), list) else []
        seller_candidates = radar.get("sellerCandidates") if isinstance(radar.get("sellerCandidates"), list) else []
        candidates = [*buy_candidates, *seller_candidates]
        paper._hydrate_locked_instruments(book["open"], candidates)
        due = [p for p in book["open"] if _mode(p) == "SELL_PREMIUM" or paper._long_mark_due(p, clock)]
        direct_marks, direct_error = _stream_marks(paper, client, due)

        next_open: list[dict[str, Any]] = []
        closed_now: list[dict[str, Any]] = []
        for position in book["open"]:
            if _mode(position) == "SELL_PREMIUM":
                debit, marked_legs, source, _stale = paper._credit_close_debit(position, candidates, direct_marks)
                if debit is None:
                    position.update({"markStatus": "UNAVAILABLE", "markError": direct_error or "SPREAD_LEG_MARK_UNAVAILABLE"})
                    next_open.append(position)
                    continue
                position.update({"markSource": "ANGEL_WEBSOCKET" if source != "RADAR_EXECUTABLE_DEPTH" and all(
                    str(leg.get("symbol") or "") in direct_marks for leg in (position.get("legs") or [])
                ) else source, "markedAt": clock.isoformat(), "markStatus": "LIVE", "markError": direct_error})
                active, closed = paper._update_credit_open(position, debit, marked_legs, paper._spot_for(position, candidates), clock)
            else:
                if not paper._long_mark_due(position, clock):
                    next_open.append(position)
                    continue
                symbol = str(position.get("symbol") or "")
                mark = direct_marks.get(symbol)
                source = "ANGEL_WEBSOCKET_LOCKED_CONTRACT" if mark is not None else "RADAR_CHAIN_FALLBACK"
                if mark is None:
                    mark = paper._mark_for(position, candidates)
                if mark is None:
                    position.update({"markStatus": "UNAVAILABLE", "markError": direct_error, "lastMarkAttemptAt": clock.isoformat()})
                    next_open.append(position)
                    continue
                active, closed = paper._update_open(position, mark, clock, mark_source=source)
            if active:
                next_open.append(active)
            if closed:
                closed_now.append(closed)

        book["open"] = next_open
        book["closed"].extend(closed_now)
        book["entryCount"] = len(book["open"]) + len(book["closed"])
        open_ids = {_identity(row) for row in book["open"]}
        open_buckets = {(_mode(row), str(row.get("bucket") or "")) for row in book["open"]}

        if paper._market_open(clock):
            for row in radar.get("selected") or []:
                audit = {"at": clock.isoformat(), "index": row.get("key"), "bucket": row.get("bucket"),
                         "strategyMode": _mode(row), "score": row.get("score")}
                if book["entryCount"] >= paper.MAX_DAILY_ENTRIES:
                    book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": "DAILY_ENTRY_CAP"}); continue
                if len(book["open"]) >= paper.MAX_CONCURRENT_TRADES:
                    book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": "MAX_CONCURRENT"}); continue
                if row.get("state") != "ELIGIBLE":
                    book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": "NOT_ELIGIBLE"}); continue
                identity, bucket_id = _identity(row), (_mode(row), str(row.get("bucket") or ""))
                if identity in open_ids:
                    book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": "SLEEVE_INDEX_ALREADY_OPEN"}); continue
                if bucket_id in open_buckets:
                    book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": "SLEEVE_BUCKET_ALREADY_OPEN"}); continue
                governor = _governor_for_mode(paper, book, _mode(row))
                decision = paper.can_reenter_index_option(str(row.get("key") or ""), str(row.get("direction") or ""), clock, governor,
                    fresh_breakout_confirmed=True, oi_aligned=True, breadth_aligned=True)
                if not decision.get("allowed"):
                    book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": f"REENTRY:{decision.get('reason')}"}); continue
                position, reason = _try_new_position(paper, row, clock, book["entryCount"] + 1)
                if position is None:
                    book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": reason}); continue
                if _mode(position) == "SELL_PREMIUM":
                    seller_risk = sum(float(item.get("maxLossPerLot") or 0) for item in book["open"] if _mode(item) == "SELL_PREMIUM")
                    if seller_risk + float(position.get("maxLossPerLot") or 0) > paper._seller_portfolio_risk_cap():
                        book["entryAudit"].append({**audit, "outcome": "REJECTED", "reason": "SELLER_PORTFOLIO_RISK_CAP"}); continue
                book["open"].append(position)
                book["entryCount"] += 1
                open_ids.add(identity); open_buckets.add(bucket_id)
                book["entryAudit"].append({**audit, "outcome": "LOCKED", "reason": reason, "positionId": position.get("id")})

        book["entryAudit"] = book["entryAudit"][-200:]
        open_pnl = round(sum(float(row.get("unrealizedPnl") or 0) for row in book["open"]), 2)
        realized = round(sum(float(row.get("pnl") or 0) for row in book["closed"]), 2)
        from .angel_index_stream import ANGEL_INDEX_STREAM
        book.update({"updatedAt": clock.isoformat(), "openPnl": open_pnl, "realizedPnl": realized,
                     "totalPnl": round(open_pnl + realized, 2), "dailyEntryCap": paper.MAX_DAILY_ENTRIES,
                     "marketOpen": paper._market_open(clock), "streamStatus": ANGEL_INDEX_STREAM.status(),
                     "executionAuthority": "INDEX_OPTIONS_LIVE_AUTHORITY_V2",
                     "sellerRiskCaps": {"singleTrade": paper._seller_single_risk_cap(), "portfolio": paper._seller_portfolio_risk_cap()},
                     "longPremiumRiskPolicy": {"markIntervalSeconds": paper.LONG_PREMIUM_MARK_INTERVAL_SECONDS,
                         "stopPointsMax": paper.LONG_PREMIUM_STOP_POINTS, "targetPointsMax": paper.LONG_PREMIUM_TARGET_POINTS,
                         "riskReward": paper.LONG_PREMIUM_RISK_REWARD, "lowPremiumAdaptive": True}})
        if persist:
            paper.atomic_write_json(paper.paper_book_path(), book)
        return book


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import index_options_engine as engine
    from . import index_options_paper as paper

    original_build = engine.build_index_options_radar

    def build(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        radar = original_build(snapshot)
        return _rebalance_radar(radar, engine.MAX_CONCURRENT_TRADES)

    engine.build_index_options_radar = build
    paper.reconcile_paper_book = _reconcile
    _INSTALLED = True
