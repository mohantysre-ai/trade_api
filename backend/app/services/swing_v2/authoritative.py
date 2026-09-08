"""Single-writer orchestration for the paper-authoritative Swing V2 book.

The service deliberately never sends a broker order.  It turns the immutable
V2 ledger into the compatibility session consumed by the existing dashboard
and EOD routes, while enforcing the 14:30/15:10/15:20 IST decision clock.
"""
from __future__ import annotations

import json
import os
import threading
import time as monotonic_time
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .calendar import session_age, time_exit_due
from .config import SwingV2Config, load_config
from .engine import execute_paper_order, process_position_bar
from .facade import build_from_market_snapshot
from .ledger import SwingLedger, materialize_position
from .reporting import ledger_eod_report

IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.RLock()
_DATA_REFRESH_LOCK = threading.Lock()
_LAST_SCAN_REFRESH_KICK = 0.0


def is_v2_authoritative(config: SwingV2Config | None = None) -> bool:
    return (config or load_config()).paper_authoritative


def _state_path() -> Path:
    configured = os.getenv("SWING_V2_SESSION_FILE", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "swing_v2_session.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(payload: dict[str, Any]) -> None:
    target = _state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, target)


def _snapshot() -> dict[str, Any]:
    from ..market_snapshot_store import readable_market_snapshot_path

    return _read_json(readable_market_snapshot_path())


def _clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def _position_groups(ledger: SwingLedger) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in ledger.events():
        if event.get("positionId"):
            grouped[str(event["positionId"])].append(event)
    return grouped


def _positions(ledger: SwingLedger) -> list[dict[str, Any]]:
    return [materialize_position(events) for events in _position_groups(ledger).values()]


def _position_row(position: dict[str, Any], mark: float | None = None) -> dict[str, Any]:
    entry = float(position.get("entryPrice") or position.get("decisionPrice") or 0)
    qty = int(position.get("filledQty") or position.get("qty") or 0)
    remaining = int(position.get("remainingQty") if position.get("remainingQty") is not None else qty)
    try:
        holding_age = session_age(date.fromisoformat(str(position.get("sessionDate"))[:10]), datetime.now(IST).date())
    except (TypeError, ValueError):
        holding_age = None
    row = {
        **position,
        "book": "SWING",
        "strategyId": "SWING_2S_MOMENTUM_V2",
        "selectionContract": "SWING_2S_MOMENTUM_V2",
        "direction": "LONG",
        "buyAbove": position.get("limitPrice") or position.get("decisionPrice"),
        "stopLoss": position.get("effectiveStop") or position.get("initialStop"),
        "target1": position.get("t1"),
        "target2": position.get("t2"),
        "approxQty": qty,
        "remainingQty": remaining,
        "deployedCapital": float(position.get("deployedCapital") or entry * qty),
        "executionStatus": position.get("executionStatus") or (
            "FILLED" if position.get("entryTimestamp") else "LOCKED"
        ),
        "locked": True,
        "source": "swing_v2_ledger",
        "holdingSessionAge": holding_age,
        "overnightCount": holding_age,
    }
    if mark is not None and mark > 0:
        row["currentPrice"] = mark
        row["ltp"] = mark
        if entry > 0 and remaining > 0 and not position.get("terminal"):
            unrealized = remaining * (mark - entry)
            row["unrealizedPnl"] = round(unrealized, 2)
            row["totalPnl"] = round(float(position.get("realizedPnl") or 0) + unrealized, 2)
    return row


def _marks(snapshot: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    quotes = snapshot.get("stockQuotes") if isinstance(snapshot.get("stockQuotes"), dict) else {}
    for symbol, row in quotes.items():
        if not isinstance(row, dict):
            continue
        try:
            price = float(row.get("ltpRaw") or row.get("ltp") or row.get("close") or 0)
        except (TypeError, ValueError):
            price = 0
        if price > 0:
            result[str(symbol).upper()] = price
    return result


def _session(scan: dict[str, Any] | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    cfg = load_config()
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    day = now.date().isoformat()
    ledger = SwingLedger(cfg.ledger_path)
    positions = _positions(ledger)
    snapshot = _snapshot()
    marks = _marks(snapshot)
    today_positions = [row for row in positions if str(row.get("sessionDate") or "") == day]
    active = [row for row in positions if row.get("positionId") and not row.get("terminal")]
    closed_today = []
    for row in positions:
        if not row.get("terminal"):
            continue
        try:
            closed_day = datetime.fromisoformat(str(row.get("lastEventAt") or "").replace("Z", "+00:00")).astimezone(IST).date().isoformat()
        except (TypeError, ValueError):
            closed_day = None
        if str(row.get("sessionDate") or "") == day or closed_day == day:
            closed_today.append(row)
    rows = [_position_row(row, marks.get(str(row.get("symbol") or "").upper())) for row in active]
    final_state = _read_json(_state_path())
    if str(final_state.get("sessionDate") or "") != day:
        final_state = {}
    effective_scan = scan if isinstance(scan, dict) else final_state.get("scan")
    freeze_reached = now.time().replace(tzinfo=None) >= _clock(cfg.decision_freeze_ist)
    finalized = bool(final_state.get("selectionFinalized"))
    locked_today = any(str(row.get("sessionDate") or "") == day for row in positions)
    blocked = bool((effective_scan or {}).get("blocked"))
    cash_held = finalized and not locked_today
    realized = sum(float(row.get("realizedPnl") or 0) for row in rows)
    unrealized = sum(float(row.get("unrealizedPnl") or 0) for row in rows)
    return {
        "success": True,
        "book": "SWING",
        "strategyId": cfg.strategy_id,
        "policyVersion": cfg.policy_version,
        "featureVersion": cfg.feature_version,
        "validationState": "RESEARCH_HYPOTHESIS",
        "authority": "V2",
        "authoritative": True,
        "executionMode": "PAPER",
        "manualBrokerOrderPlaced": False,
        "v1Enabled": False,
        "sessionDate": day,
        "locked": bool(active) or locked_today or cash_held,
        "hunting": not finalized and not freeze_reached,
        "selectionFinalized": finalized,
        "cashHeld": cash_held,
        "cashReason": (effective_scan or {}).get("blockReason") if cash_held or blocked else None,
        "source": "swing_v2_ledger",
        "selectionContract": cfg.strategy_id,
        "long": rows,
        "short": [],
        "closedPositions": [_position_row(row) for row in closed_today],
        "counts": {"long": len(rows), "short": 0, "total": len(rows)},
        "capital": {
            "swingCapital": cfg.nav,
            "slots": len(rows),
            "deployedCapital": round(sum(float(row.get("deployedCapital") or 0) for row in rows), 2),
            "remainingCapital": round(max(0.0, cfg.nav - sum(float(row.get("deployedCapital") or 0) for row in rows)), 2),
            "portfolioRisk": round(sum(float(row.get("initialRiskRupees") or 0) for row in rows), 2),
        },
        "portfolio": {"swingCapital": cfg.nav, "realizedPnl": round(realized, 2), "unrealizedPnl": round(unrealized, 2), "totalPnl": round(realized + unrealized, 2), "lockedCount": len(rows)},
        "v2": effective_scan or {"enabled": True, "authoritative": True, "candidates": []},
        "entryHuntDiagnostics": (effective_scan or {}).get("funnel"),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }


def _refresh_snapshot(reason: str) -> dict[str, Any]:
    try:
        from ..angel_one_feed import run_scheduled_live_refresh

        with _DATA_REFRESH_LOCK:
            run_scheduled_live_refresh(reason=reason)
    except Exception:
        pass
    return _snapshot()


def _kick_candidate_refresh() -> None:
    global _LAST_SCAN_REFRESH_KICK
    current = monotonic_time.monotonic()
    if current - _LAST_SCAN_REFRESH_KICK < 300 or _DATA_REFRESH_LOCK.locked():
        return
    _LAST_SCAN_REFRESH_KICK = current

    def job() -> None:
        _refresh_snapshot("swing_v2_candidate_scan")

    threading.Thread(target=job, name="swing-v2-candidate-refresh", daemon=True).start()


def _quote_observations(symbols: list[str], now: datetime) -> dict[str, dict[str, Any]]:
    """Fetch a small Angel FULL quote batch for post-decision paper evidence."""
    if not symbols:
        return {}
    try:
        from ..angel_one_feed import AngelOneClient, NIFTY_500_LABEL, _pool_watchlist

        client = AngelOneClient()
        instruments, _ = _pool_watchlist(NIFTY_500_LABEL, client)
        wanted = {value.upper() for value in symbols}
        selected = [item for item in instruments if item.key.upper() in wanted]
        quotes = client.fetch_batch_quotes(selected)
    except Exception:
        return {}
    result: dict[str, dict[str, Any]] = {}
    # Receipt time must be the real observation time, never a scheduler tick
    # captured before a potentially slow broker request.
    stamp = datetime.now(timezone.utc).isoformat()
    for symbol, quote in quotes.items():
        if not isinstance(quote, dict):
            continue
        depth = quote.get("depth") if isinstance(quote.get("depth"), dict) else {}
        sell = depth.get("sell") if isinstance(depth.get("sell"), list) else []
        best = sell[0] if sell and isinstance(sell[0], dict) else {}
        ask = quote.get("bestAskPrice") or best.get("price") or quote.get("ltp")
        ask_depth = best.get("quantity") or best.get("qty") or quote.get("tradeVolume")
        try:
            ask_value, depth_value = float(ask or 0), int(float(ask_depth or 0))
        except (TypeError, ValueError):
            continue
        if ask_value > 0 and depth_value > 0:
            result[symbol.upper()] = {"timestamp": stamp, "ask": ask_value, "askDepth": depth_value, "open": ask_value, "high": ask_value, "low": ask_value, "close": ask_value, "source": "ANGEL_ONE_FULL_QUOTE"}
    return result


def _refresh_final_candidate_facts(snapshot: dict[str, Any], scan: dict[str, Any], now: datetime) -> dict[str, Any]:
    symbols = [str(row.get("symbol") or "").upper() for row in scan.get("candidates") or []]
    observations = _quote_observations(symbols, now)
    quotes = snapshot.get("stockQuotes") if isinstance(snapshot.get("stockQuotes"), dict) else {}
    for symbol, observation in observations.items():
        raw = quotes.get(symbol)
        if not isinstance(raw, dict) or not isinstance(raw.get("swingV2"), dict):
            continue
        fact = dict(raw["swingV2"])
        bid = float(raw.get("bestBid") or observation["ask"])
        ask = float(observation["ask"])
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else ask
        fact.update({
            "decisionPrice": ask,
            "bestAsk": ask,
            "availableAskDepth": observation["askDepth"],
            "spreadPct": max(0.0, (ask - bid) / mid * 100) if mid else None,
            "sourceTimestamps": {**(fact.get("sourceTimestamps") or {}), "quote": observation["timestamp"], "depth": observation["timestamp"]},
        })
        raw["swingV2"] = fact
    return snapshot


def _fill_locked_orders(ledger: SwingLedger, now: datetime, cfg: SwingV2Config) -> None:
    groups = _position_groups(ledger)
    locked = []
    for position_id, events in groups.items():
        state = materialize_position(events)
        if state.get("terminal") or state.get("entryTimestamp"):
            continue
        if str(state.get("lastEventType") or "") == "POSITION_LOCKED":
            locked.append((position_id, state))
    observations = _quote_observations([state["symbol"] for _, state in locked], now)
    expiry_local = datetime.combine(now.astimezone(IST).date(), _clock(cfg.order_expire_ist), tzinfo=IST)
    for _, candidate in locked:
        observation = observations.get(str(candidate.get("symbol") or "").upper())
        valid_observation = None
        if observation:
            try:
                observed_at = datetime.fromisoformat(str(observation["timestamp"]).replace("Z", "+00:00"))
                decided_at = datetime.fromisoformat(str(candidate["decisionTimestamp"]).replace("Z", "+00:00"))
                if observed_at > decided_at:
                    valid_observation = observation
            except (KeyError, TypeError, ValueError):
                valid_observation = None
        if valid_observation or now.astimezone(IST) >= expiry_local:
            execute_paper_order(
                ledger,
                candidate,
                [valid_observation] if valid_observation else [],
                expiry=expiry_local,
            )


def _manage_open_positions(ledger: SwingLedger, now: datetime, cfg: SwingV2Config) -> None:
    open_positions = []
    for position_id, events in _position_groups(ledger).items():
        state = materialize_position(events)
        if state.get("entryTimestamp") and not state.get("terminal"):
            open_positions.append((position_id, state))
    observations = _quote_observations([state["symbol"] for _, state in open_positions], now)
    minute_bars: dict[str, list[dict[str, Any]]] = {}
    try:
        from ..angel_one_feed import AngelOneClient, NIFTY_500_LABEL, _parse_candle_rows, _pool_watchlist

        client = AngelOneClient()
        instruments, _ = _pool_watchlist(NIFTY_500_LABEL, client)
        wanted = {str(state.get("symbol") or "").upper() for _, state in open_positions}
        by_symbol = {item.key.upper(): item for item in instruments if item.key.upper() in wanted}
        start = now - timedelta(minutes=12)
        for symbol, instrument in by_symbol.items():
            raw = client.fetch_candles(instrument.exchange, instrument.token, "ONE_MINUTE", start, now)
            bars = []
            for candle in _parse_candle_rows(raw):
                timestamp = candle.pop("ts", None)
                bars.append({**candle, "timestamp": str(timestamp), "source": "ANGEL_ONE_1M"})
            minute_bars[symbol] = bars
    except Exception:
        minute_bars = {}
    for position_id, state in open_positions:
        symbol = str(state.get("symbol") or "").upper()
        bars = minute_bars.get(symbol) or ([observations[symbol]] if symbol in observations else [])
        try:
            cursor = datetime.fromisoformat(str(state.get("lastEventAt") or state.get("entryTimestamp") or "").replace("Z", "+00:00"))
            bars = [bar for bar in bars if datetime.fromisoformat(str(bar.get("timestamp") or "").replace("Z", "+00:00")) > cursor]
        except (TypeError, ValueError):
            pass
        if not bars:
            continue
        try:
            entry_day = date.fromisoformat(str(state.get("sessionDate"))[:10])
        except ValueError:
            continue
        age = session_age(entry_day, now.astimezone(IST).date())
        due = time_exit_due(now, age, max_overnights=cfg.max_overnights, exit_clock=cfg.mandatory_exit_ist)
        for index, bar in enumerate(bars):
            state = process_position_bar(
                ledger,
                position_id,
                bar,
                is_d2_exit=due and index == len(bars) - 1,
            )
            if state.get("terminal"):
                break


def run_authoritative_cycle(*, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
    cfg = load_config()
    if not cfg.paper_authoritative:
        raise RuntimeError("Swing V2 is not configured as paper authority")
    supplied_now = now is not None
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    with _LOCK:
        ledger = SwingLedger(cfg.ledger_path)
        _manage_open_positions(ledger, now, cfg)
        current = _read_json(_state_path())
        day = now.date().isoformat()
        if str(current.get("sessionDate") or "") != day:
            current = {"sessionDate": day, "selectionFinalized": False}
        local_time = now.time().replace(tzinfo=None)
        from ..desk_book_symbols import intraday_locked_symbols
        occupied = intraday_locked_symbols(day)
        existing_open = [row for row in _positions(ledger) if not row.get("terminal")]
        start, freeze, expiry = (_clock(cfg.decision_start_ist), _clock(cfg.decision_freeze_ist), _clock(cfg.order_expire_ist))
        scan: dict[str, Any] | None = current.get("scan") if isinstance(current.get("scan"), dict) else None
        if start <= local_time < freeze and not current.get("selectionFinalized"):
            _kick_candidate_refresh()
            scan = build_from_market_snapshot(_snapshot(), final_lock=False, persist_events=False, occupied_symbols=occupied, existing_positions=existing_open, now=now)
            current.update({"scan": scan, "lastScanAt": now.astimezone(timezone.utc).isoformat()})
        elif freeze <= local_time and not current.get("selectionFinalized"):
            snapshot = _refresh_snapshot("swing_v2_final_lock")
            if not supplied_now:
                now = datetime.now(timezone.utc).astimezone(IST)
                local_time = now.time().replace(tzinfo=None)
            if local_time > expiry:
                scan = {
                    "strategyId": cfg.strategy_id, "policyVersion": cfg.policy_version,
                    "enabled": True, "authoritative": True, "mode": "PAPER",
                    "blocked": True, "blockReason": "FINAL_DATA_REFRESH_MISSED_ORDER_WINDOW",
                    "candidates": [], "funnel": {"universe": 0},
                }
                current.update({"scan": scan, "selectionFinalized": True, "finalizedAt": now.astimezone(timezone.utc).isoformat()})
                _write_state(current)
                return _session(scan, now=now)
            quote_rows = snapshot.get("stockQuotes") if isinstance(snapshot.get("stockQuotes"), dict) else {}
            seed = {"candidates": [
                {"symbol": str(row.get("ticker") or symbol).upper()}
                for symbol, row in quote_rows.items()
                if isinstance(row, dict) and isinstance(row.get("swingV2"), dict)
            ]}
            snapshot = _refresh_final_candidate_facts(snapshot, seed, now)
            prelock = build_from_market_snapshot(snapshot, final_lock=False, persist_events=False, occupied_symbols=occupied, existing_positions=existing_open, now=now)
            snapshot = _refresh_final_candidate_facts(snapshot, prelock, now)
            scan = build_from_market_snapshot(snapshot, final_lock=True, persist_events=True, occupied_symbols=occupied, existing_positions=existing_open, now=now)
            current.update({"scan": scan, "selectionFinalized": True, "finalizedAt": now.astimezone(timezone.utc).isoformat()})
        if freeze <= local_time <= expiry:
            _fill_locked_orders(ledger, now, cfg)
        elif local_time > expiry:
            _fill_locked_orders(ledger, now, cfg)
        _write_state(current)
        return _session(scan, now=now)


def get_authoritative_session(*, live: bool = False) -> dict[str, Any]:
    # GET remains read-only. The desk scheduler is the single writer.
    return _session()


def lock_authoritative_session(*, force: bool = False) -> dict[str, Any]:
    session = run_authoritative_cycle(force=force)
    return {"success": True, "alreadyLocked": bool(session.get("locked")), "session": session}


def authoritative_eod_report(for_date: date) -> dict[str, Any]:
    cfg = load_config()
    report = ledger_eod_report(SwingLedger(cfg.ledger_path), for_date.isoformat())
    picks = []
    for position in report.get("positions") or []:
        entry = float(position.get("entryPrice") or position.get("decisionPrice") or 0)
        current = position.get("exitPrice") or position.get("currentPrice") or entry or None
        qty = int(position.get("filledQty") or position.get("qty") or 0)
        total_pnl = float(position.get("totalPnl") or 0)
        deployed = float(position.get("deployedCapital") or entry * qty)
        picks.append({
            **position,
            "direction": "LONG",
            "entryDate": position.get("sessionDate"),
            "daysHeld": session_age(date.fromisoformat(str(position.get("sessionDate"))[:10]), for_date) if position.get("sessionDate") else None,
            "dayBucket": session_age(date.fromisoformat(str(position.get("sessionDate"))[:10]), for_date) if position.get("sessionDate") else None,
            "holdingSessionAge": session_age(date.fromisoformat(str(position.get("sessionDate"))[:10]), for_date) if position.get("sessionDate") else None,
            "status": position.get("status") or position.get("lastEventType") or "LOCKED",
            "exitReason": position.get("exitReason") or position.get("lastEventType"),
            "entryPrice": entry,
            "refPrice930": entry,
            "currentPrice": current,
            "stopLoss": position.get("effectiveStop") or position.get("initialStop"),
            "target1": position.get("t1"),
            "target2": position.get("t2"),
            "qty": qty,
            "deployedCapital": deployed,
            "pnl": total_pnl,
            "pnlPct": round(total_pnl / deployed * 100, 4) if deployed else 0.0,
            "alertsFired": [],
            "pnlKind": "realised" if position.get("terminal") else "unrealised",
            "executionStatus": position.get("executionStatus") or ("FILLED" if position.get("entryTimestamp") else "LOCKED"),
        })
    total_deployed = sum(float(row.get("deployedCapital") or 0) for row in picks)
    total_pnl = float(report.get("totalPnl") or 0)
    report.update({
        "symbolSource": "swing_v2_ledger", "source": "swing_v2_ledger",
        "isMock": False, "authoritative": True, "executionMode": "PAPER",
        "executionBasis": "MODELED_PAPER", "marketPhase": "CLOSED",
        "picks": picks, "totalPicks": len(picks),
        "activePicks": sum(not bool(row.get("terminal")) for row in picks),
        "skippedNotTriggered": sum(row.get("executionStatus") in {"LOCKED", "EXPIRED_UNFILLED"} for row in picks),
        "totalDeployed": round(total_deployed, 2), "totalPnl": round(total_pnl, 2),
        "totalPnlPct": round(total_pnl / total_deployed * 100, 4) if total_deployed else 0.0,
        "winCount": sum(float(row.get("pnl") or 0) > 0 for row in picks),
        "lossCount": sum(float(row.get("pnl") or 0) < 0 for row in picks),
        "pnlByDayBucket": {},
        "attribution": {"locked": len(picks), "triggered": sum(bool(row.get("entryTimestamp")) for row in picks), "skipped": sum(not bool(row.get("entryTimestamp")) for row in picks), "wins": sum(float(row.get("pnl") or 0) > 0 for row in picks), "losses": sum(float(row.get("pnl") or 0) < 0 for row in picks), "deployed": round(total_deployed, 2)},
    })
    return report


__all__ = ["authoritative_eod_report", "get_authoritative_session", "is_v2_authoritative", "lock_authoritative_session", "run_authoritative_cycle"]
