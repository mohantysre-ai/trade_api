"""Closed-session index-options replay from 5-minute candles.

Live radar gates (futures OI, greeks, weighted breadth) are not archived.
This module never marks a Friday candidate ELIGIBLE. It reports candle
structure and, when option 5m bars exist, paper long-premium P&L only.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .angel_index_options import (
    INDEXES,
    _contracts,
    _float,
    ist_session_bounds,
    load_angel_scrip_master,
    parse_candle_ts,
    walk_forward_structure,
)
from .eod_engine.ingestion import EOD_DATA_ROOT, atomic_write_json
from .index_options_engine import INDEX_CONFIG, MAX_CONCURRENT_TRADES, MAX_DAILY_ENTRIES
from .json_atomic import load_json_with_fallback

BUY_SIDE_CAP = 10
INDEX_TIE_BREAK = ("NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY")


def previous_friday(today: date) -> date:
    offset = (today.weekday() - 4) % 7
    if offset == 0:
        return today
    return today - timedelta(days=offset)


def parse_session_date(raw: str | None, *, today: date | None = None) -> date:
    now = today or datetime.now(timezone.utc).date()
    text = str(raw or "").strip().lower()
    if not text or text in {"last-friday", "last_friday", "friday"}:
        return previous_friday(now)
    return date.fromisoformat(text)


def _replay_path(session_date: date) -> str:
    return str(Path(EOD_DATA_ROOT) / session_date.isoformat() / "index_options_replay.json")


def load_replay_cache(session_date: date) -> dict[str, Any] | None:
    try:
        payload = load_json_with_fallback(_replay_path(session_date))
    except FileNotFoundError:
        return None
    return payload if isinstance(payload, dict) and payload.get("success") else None


def paper_long_option_pnl(candles: list[list[Any]], confirmed_at: str | None, lot_size: float | None) -> dict[str, Any]:
    parsed = [row for row in candles if isinstance(row, list) and len(row) >= 5 and _float(row[4]) is not None]
    if not parsed:
        return {
            "barCount": 0, "entry": None, "exit": None, "entryAt": None, "exitAt": None,
            "pnlPoints": None, "pnlRupees": None, "limitation": "OPTION_CANDLES_UNAVAILABLE",
        }
    confirm_ts = parse_candle_ts(confirmed_at) if confirmed_at else parse_candle_ts(parsed[0][0])
    entry_row = None
    for row in parsed:
        ts = parse_candle_ts(row[0])
        if ts is None:
            continue
        if confirm_ts is None or ts >= confirm_ts:
            entry_row = row
            break
    if entry_row is None:
        return {
            "barCount": len(parsed), "entry": None, "exit": None, "entryAt": None, "exitAt": None,
            "pnlPoints": None, "pnlRupees": None, "limitation": "NO_BAR_AFTER_CONFIRMATION",
        }
    exit_row = parsed[-1]
    entry = _float(entry_row[4])
    exit_px = _float(exit_row[4])
    points = round(exit_px - entry, 4) if entry is not None and exit_px is not None else None
    rupees = round(points * lot_size, 2) if points is not None and lot_size else None
    return {
        "barCount": len(parsed),
        "entry": entry,
        "exit": exit_px,
        "entryAt": str(entry_row[0]),
        "exitAt": str(exit_row[0]),
        "pnlPoints": points,
        "pnlRupees": rupees,
        "limitation": None if points is not None else "OPTION_MARKS_INCOMPLETE",
    }


def _config_for(key: str) -> dict[str, Any]:
    return next(row for row in INDEXES if row["key"] == key)


def _meta_for(key: str) -> dict[str, str]:
    return next(row for row in INDEX_CONFIG if row["key"] == key)


def _select_correlation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    confirmed = [row for row in rows if row.get("firstDirection") in {"CALL", "PUT"}]
    confirmed.sort(key=lambda row: (INDEX_TIE_BREAK.index(row["key"]) if row["key"] in INDEX_TIE_BREAK else 99))
    selected: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in confirmed:
        bucket = _meta_for(row["key"])["bucket"]
        if bucket in used or len(selected) >= MAX_CONCURRENT_TRADES:
            continue
        selected.append(row)
        used.add(bucket)
    return selected


def _fetch_index_session(client: Any, config: dict[str, Any], session_date: date) -> dict[str, Any]:
    start, end = ist_session_bounds(session_date)
    try:
        candles = client.fetch_candles(config["exchange"], config["spotToken"], "FIVE_MINUTE", start, end) or []
    except Exception as exc:
        return {
            "key": config["key"], "spot": None, "candles": [], "structure": {"status": "SOURCE_UNAVAILABLE", "direction": None, "barCount": 0},
            "firstDirection": None, "confirmedAt": None, "error": str(exc),
        }
    structure = walk_forward_structure(candles)
    spot = _float(structure.get("last"))
    return {
        "key": config["key"],
        "spot": spot,
        "candles": candles,
        "structure": structure,
        "firstDirection": structure.get("firstDirection") or structure.get("direction"),
        "confirmedAt": structure.get("confirmedAt"),
        "error": None,
    }


def _buy_side_contracts(master: list[dict[str, Any]], index_row: dict[str, Any], session_date: date) -> tuple[date | None, list[dict[str, Any]]]:
    config = _config_for(index_row["key"])
    spot = index_row.get("spot")
    if not spot:
        return None, []
    expiry, options, _future = _contracts(master, config, spot, today=session_date)
    wanted = "CE" if index_row.get("firstDirection") == "CALL" else "PE" if index_row.get("firstDirection") == "PUT" else None
    if not wanted or expiry is None:
        return expiry, []
    side = [row for row in options if str(row.get("symbol") or "").upper().endswith(wanted)]
    side.sort(key=lambda row: abs((_float(row.get("_strike")) or 0) - spot))
    return expiry, side


def replay_index_options_session(
    client: Any,
    session_date: date,
    *,
    master: list[dict[str, Any]] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    cached = load_replay_cache(session_date)
    if cached:
        return cached

    rows = master if master is not None else load_angel_scrip_master()
    index_rows = [_fetch_index_session(client, config, session_date) for config in INDEXES]
    selected = _select_correlation(index_rows)
    selected_keys = {row["key"] for row in selected}

    buy_side: list[dict[str, Any]] = []
    start, end = ist_session_bounds(session_date)

    def _append(index_row: dict[str, Any], *, implemented: bool, blocked_by: str | None) -> None:
        expiry, contracts = _buy_side_contracts(rows, index_row, session_date)
        atm = contracts[0] if contracts else None
        remaining = max(0, BUY_SIDE_CAP - len(buy_side))
        for rank, contract in enumerate(contracts[:remaining]):
            token = str(contract.get("token") or "")
            exchange = str(contract.get("exch_seg") or _config_for(index_row["key"])["segment"])
            try:
                option_bars = client.fetch_candles(exchange, token, "FIVE_MINUTE", start, end) or []
            except Exception:
                option_bars = []
            lot_size = _float(contract.get("lotsize"))
            pnl = paper_long_option_pnl(option_bars, index_row.get("confirmedAt"), lot_size)
            buy_side.append({
                "index": index_row["key"],
                "bucket": _meta_for(index_row["key"])["bucket"],
                "symbol": contract.get("symbol"),
                "token": token,
                "strike": contract.get("_strike"),
                "optionType": "CALL" if str(contract.get("symbol") or "").endswith("CE") else "PUT",
                "expiry": expiry.isoformat() if expiry else None,
                "lotSize": lot_size,
                "atmProxy": contract is atm,
                "implemented": implemented and contract is atm,
                "blockedBy": blocked_by,
                "rankFromAtm": rank,
                **pnl,
            })

    for index_row in selected:
        _append(index_row, implemented=True, blocked_by=None)
    for index_row in index_rows:
        if index_row["key"] in selected_keys or index_row.get("firstDirection") not in {"CALL", "PUT"}:
            continue
        if len(buy_side) >= BUY_SIDE_CAP:
            break
        _append(index_row, implemented=False, blocked_by="CORRELATION_GUARD")

    limitations = [
        "HISTORICAL_FUTURES_OI_NOT_ARCHIVED",
        "HISTORICAL_GREEKS_NOT_ARCHIVED",
        "WEIGHTED_CONSTITUENT_BREADTH_NOT_CONFIRMED",
        "RADAR_GATES_NOT_OVERRIDDEN",
    ]
    if not any((row.get("structure") or {}).get("barCount") for row in index_rows):
        limitations.append("INDEX_CANDLES_UNAVAILABLE")
    if any(row.get("limitation") for row in buy_side):
        limitations.append("OPTION_PREMIUM_P&L_PARTIAL_OR_MISSING")

    payload = {
        "success": True,
        "mode": "SESSION_REPLAY",
        "executionPolicy": "MANUAL_ONLY",
        "sessionDate": session_date.isoformat(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "Paper long-premium marks from 5-minute option candles. "
            "This is not live eligibility and does not override hard gates."
        ),
        "limits": {
            "maxDailyEntries": MAX_DAILY_ENTRIES,
            "maxConcurrent": MAX_CONCURRENT_TRADES,
            "buySideCap": BUY_SIDE_CAP,
            "maxPerCorrelationBucket": 1,
        },
        "indices": [
            {
                "key": row["key"],
                **_meta_for(row["key"]),
                "spot": row.get("spot"),
                "firstDirection": row.get("firstDirection"),
                "confirmedAt": row.get("confirmedAt"),
                "structure": row.get("structure"),
                "selected": row["key"] in selected_keys,
                "error": row.get("error"),
            }
            for row in index_rows
        ],
        "implemented": [row for row in buy_side if row.get("implemented")],
        "buySideContracts": buy_side[:BUY_SIDE_CAP],
        "limitations": limitations,
    }
    if persist:
        atomic_write_json(_replay_path(session_date), payload)
    return payload
