"""EOD ingestion: load day's picks and persist 1-min candle timelines."""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..eod_archive import load_archive

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

_SERVICES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_DIR = os.path.dirname(_SERVICES_DIR)
_BACKEND_DIR = os.path.dirname(_APP_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

EOD_DATA_ROOT = os.path.join(_APP_DIR, "data", "eod")
_FIXED_PLAN_PATH = os.environ.get(
    "FIXED_PLAN_FILE",
    os.path.join(_REPO_ROOT, "fixed_trade_plan.json"),
)
_INTRADAY_SESSION_PATH = os.environ.get(
    "INTRADAY_SESSION_FILE",
    os.path.join(_REPO_ROOT, "intraday_session.json"),
)
_LAST_SNAPSHOT_PATH = os.path.join(_SERVICES_DIR, "last_market_snapshot.json")


def eod_day_dir(for_date: date) -> str:
    path = os.path.join(EOD_DATA_ROOT, for_date.isoformat())
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "timeline_ticks"), exist_ok=True)
    return path


def atomic_write_json(path: str, payload: Any) -> None:
    """Atomic JSON write via .tmp + os.replace (fallback to overwrite)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    try:
        os.replace(tmp, path)
    except OSError:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_market_snapshot() -> dict[str, Any]:
    return _read_json(_LAST_SNAPSHOT_PATH)


def load_fixed_trade_plan(for_date: date | None = None) -> dict[str, Any]:
    plan = _read_json(_FIXED_PLAN_PATH)
    if for_date is None:
        return plan
    session = str(plan.get("sessionDate") or "")
    if session and session != for_date.isoformat():
        # Plan is for a different day — still usable if archive empty; caller notes it.
        return plan
    return plan


def load_intraday_session(for_date: date | None = None) -> dict[str, Any]:
    session = _read_json(_INTRADAY_SESSION_PATH)
    if for_date is None:
        return session
    return session


def _normalize_pick(raw: dict[str, Any], source: str, *, book: str | None = None) -> dict[str, Any] | None:
    symbol = str(raw.get("symbol") or raw.get("ticker") or "").upper().strip()
    if not symbol:
        return None
    direction = str(raw.get("direction") or "LONG").upper()
    if direction not in ("LONG", "SHORT"):
        direction = "LONG"
    entry = _f(
        raw.get("entryPrice")
        or raw.get("entry")
        or raw.get("buyAbove")
        or raw.get("ltp")
        or raw.get("scanLtp")
    )
    stop = _f(raw.get("stopLoss"))
    t1 = _f(raw.get("target1") or raw.get("target_price") or raw.get("sellPrice"))
    t2 = _f(raw.get("target2"))
    if entry is None or stop is None or t1 is None:
        return None
    score = _f(raw.get("score") or raw.get("alpha_score") or raw.get("confidence"))
    risk = _f(raw.get("riskPerShare") or raw.get("risk_per_share"))
    if risk is None and entry is not None and stop is not None:
        risk = abs(entry - stop)
    qty = int(raw.get("approxQty") or raw.get("approx_qty") or 0)
    deployed = _f(raw.get("deployedCapital") or raw.get("deployed_capital")) or 0.0
    resolved_book = str(
        book
        or raw.get("book")
        or ("SWING" if "swing" in source.lower() else "INTRADAY")
    ).upper()
    if resolved_book not in ("SWING", "INTRADAY"):
        resolved_book = "INTRADAY"
    return {
        "symbol": symbol,
        "name": raw.get("name") or symbol,
        "direction": direction,
        "book": resolved_book,
        "entryPrice": entry,
        "stopLoss": stop,
        "target1": t1,
        "target2": t2,
        "score": score,
        "sector": raw.get("sector"),
        "rewardRisk": _f(raw.get("rewardRisk") or raw.get("rrT2")),
        "approxQty": qty,
        "deployedCapital": deployed,
        "riskPerShare": risk,
        "factorBreakdown": raw.get("factorBreakdown") or raw.get("components"),
        "outcome": raw.get("outcome"),
        "atrPct": _f(raw.get("atrPct") or raw.get("atr_pct")),
        "vwap": _f(raw.get("vwap")),
        "source": source,
        "raw": raw,
    }


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_day_picks(for_date: date) -> dict[str, Any]:
    """Union locked Swing + Intraday baskets for EOD (target ~10 + 10 + 10 = 30).

    Sources (facts only, no invented symbols):
      - swing_session.json (Asset Matrix BUY lock) -> book=SWING when sessionDate matches
      - intradAy_session.json long/short -> book=INTRADAY when sessionDate matches
      - fixed_trade_plan.json only if intradAy session empty (legacy mirror)
      - eod_archive fills gaps for missing keys only
    Stale cross-day session files are rejected for Book symbol parity.
    Read-only: never calls ensure_* lock/rotate — that belongs to scheduler / explicit lock APIs.
    """
    from ..swing_session import load_swing_session

    plan = load_fixed_trade_plan(for_date)
    session = load_intraday_session(for_date)
    archive = load_archive(for_date)
    snapshot = load_market_snapshot()

    swing = load_swing_session()
    day_key = for_date.isoformat()
    swing_date = str(swing.get("sessionDate") or "").strip()[:10]
    session_date = str(session.get("sessionDate") or "").strip()[:10]
    swing_ok = bool(swing.get("locked") and swing_date == day_key)
    session_ok = bool(session.get("locked") and session_date == day_key)

    by_key: dict[str, dict[str, Any]] = {}

    def _ingest(items: list[Any], source: str, *, book: str) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            pick = _normalize_pick(item, source, book=book)
            if not pick:
                continue
            key = f"{pick['symbol']}:{pick['direction']}:{pick['book']}"
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = pick
                continue
            if pick.get("factorBreakdown") and not existing.get("factorBreakdown"):
                existing["factorBreakdown"] = pick["factorBreakdown"]
            if existing.get("score") is None and pick.get("score") is not None:
                existing["score"] = pick["score"]
            if pick.get("outcome") and not existing.get("outcome"):
                existing["outcome"] = pick["outcome"]
            if pick.get("approxQty") and not existing.get("approxQty"):
                existing["approxQty"] = pick["approxQty"]
                existing["deployedCapital"] = pick.get("deployedCapital")

    if swing_ok:
        _ingest(list(swing.get("long") or []), "swing_session", book="SWING")
        _ingest(list(swing.get("short") or []), "swing_session", book="SWING")
    elif swing.get("locked") and swing_date and swing_date != day_key:
        log.info(
            "Rejecting stale swing_session for Book (%s != %s) — date parity",
            swing_date,
            day_key,
        )

    # No dhanSwingPicks fallback — swing lock source is Asset Matrix only.

    session_long = list(session.get("long") or []) if session_ok else []
    session_short = list(session.get("short") or []) if session_ok else []
    if not session_ok and session.get("locked") and session_date and session_date != day_key:
        log.info(
            "Rejecting stale intradAy_session for Book (%s != %s) — date parity",
            session_date,
            day_key,
        )
    if session_long or session_short:
        _ingest(session_long, "intraday_session", book="INTRADAY")
        _ingest(session_short, "intraday_session", book="INTRADAY")
    else:
        _ingest(list(plan.get("long") or []), "fixed_trade_plan", book="INTRADAY")
        _ingest(list(plan.get("short") or []), "fixed_trade_plan", book="INTRADAY")

    # Archive fills gaps for forensic engines only — Book P&L uses locked desks.
    # Keep archive merge for scorecards / missed-opportunity scan via load_day_picks.
    archived = archive.get("intradayPicks") or {}
    if isinstance(archived, dict):
        locked_intra = any(p.get("book") == "INTRADAY" for p in by_key.values())
        for item in archived.values():
            if not isinstance(item, dict):
                continue
            book = str(item.get("book") or "INTRADAY").upper()
            if book not in ("SWING", "INTRADAY"):
                book = "INTRADAY"
            # Do not dilute a locked intraday desk with older archive names
            if book == "INTRADAY" and locked_intra:
                continue
            if book == "SWING" and swing_ok:
                continue
            pick = _normalize_pick(item, "eod_archive", book=book)
            if not pick:
                continue
            key = f"{pick['symbol']}:{pick['direction']}:{pick['book']}"
            if key not in by_key:
                by_key[key] = pick

    picks = list(by_key.values())

    # Cross-book uniqueness: intradAy wins; drop colliding SWING rows for this date.
    intra_syms = {
        str(p.get("symbol") or "").upper().strip()
        for p in picks
        if p.get("book") == "INTRADAY" and p.get("symbol")
    }
    cross_dropped: list[str] = []
    if intra_syms:
        kept: list[dict[str, Any]] = []
        for p in picks:
            sym = str(p.get("symbol") or "").upper().strip()
            if p.get("book") == "SWING" and sym in intra_syms:
                cross_dropped.append(sym)
                continue
            kept.append(p)
        if cross_dropped:
            picks = kept
            log.info(
                "Dropped %d swing pick(s) already on intradAy for %s: %s",
                len(cross_dropped),
                day_key,
                ",".join(sorted(set(cross_dropped))),
            )

    swing_n = sum(1 for p in picks if p.get("book") == "SWING")
    intra_long = sum(1 for p in picks if p.get("book") == "INTRADAY" and p.get("direction") == "LONG")
    intra_short = sum(1 for p in picks if p.get("book") == "INTRADAY" and p.get("direction") == "SHORT")

    regime = plan.get("regime") or session.get("regime") or swing.get("regime") or {}
    capital = plan.get("capital") or session.get("capital") or {}

    return {
        "date": for_date.isoformat(),
        "picks": picks,
        "regime": regime,
        "capital": capital,
        "plan": plan,
        "session": session,
        "swingSession": swing,
        "archive": archive,
        "snapshot": snapshot,
        "deskCounts": {
            "swing": swing_n,
            "intradayLong": intra_long,
            "intradayShort": intra_short,
            "total": len(picks),
        },
        "sources": {
            "planSessionDate": plan.get("sessionDate"),
            "sessionDate": session.get("sessionDate"),
            "swingSessionDate": swing.get("sessionDate"),
            "archiveDate": archive.get("date"),
            "pickCount": len(picks),
            "swingLocked": bool(swing.get("locked")),
            "intradayLocked": bool(session.get("locked")),
            "swingDateParity": swing_ok,
            "intradayDateParity": session_ok,
            "crossBookDropped": sorted(set(cross_dropped)),
        },
    }


def _session_bounds(for_date: date) -> tuple[datetime, datetime]:
    open_dt = datetime.combine(for_date, time(9, 15), tzinfo=IST)
    close_dt = datetime.combine(for_date, time(15, 30), tzinfo=IST)
    return open_dt, close_dt


def fetch_and_persist_candles(
    for_date: date,
    symbols: list[str],
    client: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch ONE_MINUTE candles per ticker; persist to timeline_ticks/{TICKER}.json."""
    day_dir = eod_day_dir(for_date)
    ticks_dir = os.path.join(day_dir, "timeline_ticks")
    open_dt, close_dt = _session_bounds(for_date)
    results: dict[str, list[dict[str, Any]]] = {}

    # Prefer existing persisted candles (idempotent re-runs)
    unique_syms = sorted({s.upper() for s in symbols if s})
    pending: list[str] = []
    for sym in unique_syms:
        path = os.path.join(ticks_dir, f"{sym}.json")
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as fh:
                    payload = json.load(fh)
                candles = payload.get("candles") if isinstance(payload, dict) else None
                if isinstance(candles, list) and candles:
                    results[sym] = candles
                    continue
            except Exception:
                pass
        pending.append(sym)

    if not pending:
        return results

    ao_client = client
    token_map: dict[str, tuple[str, str]] = {}
    resolve_fn = None
    parse_fn = None
    # Deferred import: angel_one_feed imports eod_engine at app startup (circular).
    try:
        from ..angel_one_feed import (
            AngelOneClient,
            _load_nse_eq_token_map,
            _parse_candle_rows,
            _resolve_nse_equity,
        )

        parse_fn = _parse_candle_rows
        resolve_fn = _resolve_nse_equity
        token_map = _load_nse_eq_token_map()
        if ao_client is None:
            ao_client = AngelOneClient()
    except Exception as exc:
        log.warning("Candle client unavailable: %s", exc)
        for sym in pending:
            empty = {
                "ticker": sym,
                "date": for_date.isoformat(),
                "interval": "ONE_MINUTE",
                "candles": [],
                "error": "candle_client_unavailable",
            }
            atomic_write_json(os.path.join(ticks_dir, f"{sym}.json"), empty)
            results[sym] = []
        return results

    for sym in pending:
        candles: list[dict[str, Any]] = []
        err: str | None = None
        try:
            resolved = resolve_fn(sym, client=ao_client, token_map=token_map) if resolve_fn else None
            if not resolved:
                err = "token_unresolved"
            else:
                token, _tsym = resolved
                raw = ao_client.fetch_candles(
                    "NSE",
                    token,
                    "ONE_MINUTE",
                    open_dt,
                    close_dt + timedelta(minutes=1),
                )
                parsed = parse_fn(raw) if parse_fn else []
                candles = parsed or []
                if not candles:
                    err = "empty_candles"
        except Exception as exc:
            err = str(exc)
            log.warning("Candle fetch failed for %s: %s", sym, exc)

        payload = {
            "ticker": sym,
            "date": for_date.isoformat(),
            "interval": "ONE_MINUTE",
            "from": open_dt.isoformat(),
            "to": close_dt.isoformat(),
            "candle_count": len(candles),
            "candles": candles,
            "error": err,
        }
        atomic_write_json(os.path.join(ticks_dir, f"{sym}.json"), payload)
        results[sym] = candles

    return results


def load_persisted_candles(for_date: date, ticker: str) -> dict[str, Any]:
    path = os.path.join(
        eod_day_dir(for_date), "timeline_ticks", f"{ticker.upper()}.json"
    )
    return _read_json(path)


def list_eod_dates() -> list[str]:
    if not os.path.isdir(EOD_DATA_ROOT):
        return []
    dates: list[str] = []
    for name in os.listdir(EOD_DATA_ROOT):
        day_path = os.path.join(EOD_DATA_ROOT, name)
        if not os.path.isdir(day_path):
            continue
        master = os.path.join(day_path, "master_eod_payload.json")
        if os.path.isfile(master):
            dates.append(name)
    return sorted(dates)
