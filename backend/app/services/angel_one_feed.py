"""
Angel One market feed for the IROS terminal.

This service fetches live Angel One quotes, lets the LLM rank the full live
universe using a filter prompt, and exposes the top selected stocks as the
active market list.
"""

from __future__ import annotations

import argparse
import asyncio
import email
import json
import logging
import math
import os
import re
import sys
import threading
import time
import uuid
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import httpx # Added for internal API calls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pyotp
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from SmartApi import SmartConnect

from .bulk_deals import load_bulk_deals
from .stock_quality import (
    MAX_DAY_MOVE_PCT,
    MAX_WICK_NOISE_RATIO,
    MIN_EMA_ANGLE_DEG,
    MIN_PROMOTER_HOLDING_PCT,
    MIN_RSI_PIVOT,
    MIN_TURNOVER_CR,
    MIN_VOLUME_MULTIPLIER,
    attach_pivot_metrics,
    day_change_pct_from_prices,
    day_change_pct_from_row,
    ensure_promoter_holdings,
    enrich_stock_quality,
    oi_setup_allows_buy,
    pace_volume_multiplier,
)
from .market_feeds import (
    fetch_domestic_index_macro,
    fetch_domestic_yahoo_macro,
    fetch_global_macro,
    fetch_gift_nifty,
)
from .market_data_provider import (
    dhan_configured,
    fetch_dhan_candles,
    fetch_nse_candles,
    fetch_quotes_with_failover,
    load_dhan_security_ids,
)
from ..utils.symbols import MACRO_INSTRUMENTS, MOCK_TICKERS, NIFTY_50_KEYS, WATCHLIST, Instrument
from .llm_client import (
    _call_openai as _llm_openai_chat,
    _llm_config as _llm_config_canonical,
    _get_gemini_oauth_token,
    _llm_quota_available,
    _record_quota_error,
)
from .intelligence_engine import (
    CompleteSecurityAnalysisPayload,
    TOP_SELECTION_COUNT,
    LLM_DISPLAY_COUNT,
    _on_demand_ticker_selection_reason,
    build_ticker_intelligence_map,
    build_ticker_intelligence_report,
    execute_terminal_intelligence_pipeline,
)
from .eod_engine.api import wire_eod_into_app

_TI_TOP_SELECTION_COUNT = TOP_SELECTION_COUNT

ORCHESTRATION_DELAY = 30


BASE_DIR = Path(__file__).resolve().parent
# Load only backend/.env for local development. Explicit process/container
# environment variables retain precedence over values from the file.
load_dotenv(BASE_DIR.parent.parent / ".env", override=False)

NIFTY_500_CACHE_PATH = BASE_DIR / "nifty500_instruments.json"
NIFTY_500_SYMBOLS_PATH = BASE_DIR.parent / "data" / "nifty500_symbols.json"
NIFTY_500_LABEL = "Nifty 500"
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
# Funnel: full Nifty 500 quotes → top N by volume for Asset Matrix (env: VOLUME_PRESELECT_LIMIT).
# Swing hunt candles default to the full 500 (env: SWING_CANDIDATE_LIMIT).
VOLUME_PRESELECT_LIMIT = int(os.getenv("VOLUME_PRESELECT_LIMIT", "200"))
SWING_CANDIDATE_LIMIT = int(os.getenv("SWING_CANDIDATE_LIMIT", "500"))
_NSE_EQ_TOKEN_MAP: dict[str, tuple[str, str]] | None = None
_NSE_EQ_TOKEN_MAP_LOADED_AT = 0.0
_NSE_EQ_TOKEN_MAP_TTL_SECONDS = int(os.getenv("NSE_EQ_TOKEN_MAP_TTL_SECONDS", "86400"))

IST_ZONE = ZoneInfo("Asia/Kolkata")
SNAPSHOT_PATH = BASE_DIR / "last_market_snapshot.json"
REFRESH_TASKS_PATH = BASE_DIR.parent / "data" / "refresh_tasks.json"
MORNING_REFRESH_START = (8, 0)
MORNING_REFRESH_END = (8, 30)
EVENING_REFRESH_START = (16, 0)
EVENING_REFRESH_END = (16, 30)
REFRESH_TASK_TTL_SECONDS = int(os.getenv("REFRESH_TASK_TTL_SECONDS", "1200"))
REFRESH_TASK_RUNNING_MAX_IDLE_SECONDS = int(
    os.getenv("REFRESH_TASK_RUNNING_MAX_IDLE_SECONDS", str(max(REFRESH_TASK_TTL_SECONDS, 1200)))
)
_REFRESH_TASKS: dict[str, dict[str, Any]] = {}
_ONDEMAND_ACTIVE_BY_KEY: dict[str, str] = {}
_REFRESH_TASK_LOCK = threading.Lock()
_MACRO_REFRESH_LOCK = threading.Lock()
LLM_UNIVERSE_LIMIT = int(os.getenv("LLM_UNIVERSE_LIMIT", "30"))
# last_market_snapshot.json: persisted market payload for GET /api/market-data (prefer_cache=True).
# Reused during on-demand refresh for fresh intraday metrics (INTRADAY_METRICS_TTL) and AI output (AI_CACHE_TTL).
INTRADAY_METRICS_TTL_SECONDS = int(os.getenv("INTRADAY_METRICS_TTL_SECONDS", "600"))
AI_CACHE_TTL_SECONDS = int(os.getenv("AI_CACHE_TTL_SECONDS", "900"))
# After morning pre-work (or any successful LLM pass), reuse TI for the IST day
# unless forceLlmRefresh=true. Live Angel/Yahoo/RSS still refresh every cycle.
MARKET_PREWORK_STAMP_PATH = BASE_DIR.parent / "data" / "morning_prework_stamp.json"
# Angel historical (getCandleData) rate-limits hard (AB1021). Keep workers low.
INTRADAY_FETCH_WORKERS = int(os.getenv("INTRADAY_FETCH_WORKERS", "1"))
NIFTY_100_LABEL = "Nifty 100"
NIFTY_100_CACHE_PATH = BASE_DIR / "nifty100_instruments.json"
ANGEL_API_TIMEOUT_SECONDS = int(os.getenv("ANGEL_API_TIMEOUT_SECONDS", "24"))
LLM_CALL_TIMEOUT_SECONDS = min(max(1, int(os.getenv("LLM_CALL_TIMEOUT_SECONDS", "180"))), 300)
QUOTE_CHUNK_SIZE = int(os.getenv("QUOTE_CHUNK_SIZE", "10"))
INTRADAY_CHUNK_SIZE = int(os.getenv("INTRADAY_CHUNK_SIZE", "5"))
# Global candle throttle across all threads (Angel AB1021 / ~3–5 req/s soft limit).
CANDLE_MIN_INTERVAL_SECONDS = float(os.getenv("CANDLE_MIN_INTERVAL_SECONDS", "1.1"))
# Extra POSTs after AB1021 make the flood worse; default is trip the circuit.
CANDLE_RATE_LIMIT_RETRIES = int(os.getenv("CANDLE_RATE_LIMIT_RETRIES", "0"))
ANGEL_CANDLE_CIRCUIT_SECONDS = float(os.getenv("ANGEL_CANDLE_CIRCUIT_SECONDS", "120"))
NIFTY_CACHE_EXPECTED_MIN = int(os.getenv("NIFTY_CACHE_EXPECTED_MIN", "475"))
NIFTY_CACHE_MIN_COVERAGE_PCT = float(os.getenv("NIFTY_CACHE_MIN_COVERAGE_PCT", "99"))
NIFTY_CACHE_MAX_AGE_SECONDS = int(os.getenv("NIFTY_CACHE_MAX_AGE_SECONDS", "86400"))
MARKET_DATA_MIN_CANDLE_COVERAGE_PCT = float(
    os.getenv("MARKET_DATA_MIN_CANDLE_COVERAGE_PCT", "95")
)
_CANDLE_THROTTLE_LOCK = threading.Lock()
_CANDLE_LAST_CALL_MONO = 0.0
_CANDLE_COOLDOWN_UNTIL_MONO = 0.0
_ANGEL_CANDLE_CIRCUIT_UNTIL = 0.0

AI_NEWS_API_URL = os.getenv("AI_NEWS_API_URL", "http://127.0.0.1:8001")


# =============================================================================
# STRICT SAFETY AUDITOR SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """
You are a senior investment banking / sell-side risk auditor and large-portfolio PM
with 20+ years managing institutional books. Capital preservation first.

You are NOT a stock selector / ranker.

You must never:

- rank stocks
- score stocks for alpha
- evaluate technical indicators
- analyze momentum
- infer chart patterns

Audit only:

- News Risk
- Earnings Risk
- Regulatory Risk
- Corporate Action Risk
- Governance Risk
- Macro Event Risk

Every claim requires:

- source
- publication timestamp

No source = No verified evidence.

REJECT only for:

- earnings within 48h
- exchange restrictions
- regulatory actions
- court decisions
- corporate actions causing binary gaps

Also return deskDecision APPROVE|REJECT matching verdict, plus a one-line deskIcNote.

Return JSON only.
"""


def _refresh_task_key(pool_name: str | None, custom_prompt: str | None) -> str:
    return f"refresh:{pool_name or '__all__'}:{(custom_prompt or '').strip()[:64]}"


def _ondemand_refresh_task_key(pool_name: str | None, custom_prompt: str | None) -> str:
    return f"ondemand:{pool_name or '__all__'}:{(custom_prompt or '').strip()[:64]}"


def _refresh_task_status(task_id: str) -> dict[str, Any] | None:
    now = time.time()
    task = _get_refresh_task_record(task_id)
    if not task:
        return None

    with _REFRESH_TASK_LOCK:
        task = _REFRESH_TASKS.get(task_id)
        if not task:
            return None

        created_at = float(task.get("created_at") or 0)
        updated_at = float(task.get("updated_at") or created_at)
        status = str(task.get("status") or "running")
        age = now - created_at
        idle = now - updated_at

        expired = False
        if status == "running":
            expired = idle > REFRESH_TASK_RUNNING_MAX_IDLE_SECONDS
        elif status in ("done", "error"):
            expired = age > REFRESH_TASK_TTL_SECONDS
        else:
            expired = age > REFRESH_TASK_TTL_SECONDS

        if expired:
            dedup_key = task.get("dedup_key")
            if dedup_key and _ONDEMAND_ACTIVE_BY_KEY.get(dedup_key) == task_id:
                del _ONDEMAND_ACTIVE_BY_KEY[dedup_key]
            del _REFRESH_TASKS[task_id]
            _persist_refresh_tasks()
            return None

        result = task.get("result")
        if status == "done" and not result:
            result = _refresh_result_from_snapshot()

        return {
            "status": task["status"],
            "progress": task.get("progress"),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "result": result,
        }


def _refresh_task_touch(task_id: str, progress: str | None = None) -> None:
    with _REFRESH_TASK_LOCK:
        task = _REFRESH_TASKS.get(task_id)
        if not task:
            return
        task["updated_at"] = time.time()
        if progress is not None:
            task["progress"] = progress
    _persist_refresh_tasks()


def _ondemand_status_url(task_id: str) -> str:
    return f"/api/refresh-data-on-demand/status?taskId={quote(task_id, safe='')}"


def _refresh_result_from_snapshot() -> dict[str, Any] | None:
    snapshot = _load_last_snapshot()
    if not snapshot or not snapshot.get("stocks"):
        return None
    return {
        "success": True,
        "payload": snapshot,
        "selectionMeta": snapshot.get("selectionMeta"),
        "isSnapshotFallback": bool(snapshot.get("isSnapshotFallback", False)),
    }


def _serialize_refresh_tasks_for_disk() -> dict[str, Any]:
    with _REFRESH_TASK_LOCK:
        tasks: dict[str, Any] = {}
        for task_id, task in _REFRESH_TASKS.items():
            row = {k: v for k, v in task.items() if k != "result"}
            tasks[task_id] = row
        return {
            "tasks": tasks,
            "activeByKey": dict(_ONDEMAND_ACTIVE_BY_KEY),
        }


def _persist_refresh_tasks() -> None:
    try:
        REFRESH_TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = _serialize_refresh_tasks_for_disk()
        tmp_path = REFRESH_TASKS_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # Windows can briefly lock the destination during concurrent reads/writes.
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                os.replace(tmp_path, REFRESH_TASKS_PATH)
                return
            except OSError as exc:
                last_exc = exc
                time.sleep(0.05 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to persist refresh tasks: %s", exc)


def _reconcile_loaded_refresh_task(task_id: str, task: dict[str, Any]) -> dict[str, Any]:
    if str(task.get("status")) != "running":
        return task
    snapshot = _load_last_snapshot()
    snap_updated = snapshot.get("updatedAt") if snapshot else None
    snap_ts = 0.0
    if snap_updated:
        try:
            snap_ts = datetime.fromisoformat(str(snap_updated).replace("Z", "+00:00")).timestamp()
        except Exception:
            snap_ts = 0.0
    created_at = float(task.get("created_at") or 0)
    if snap_ts > created_at and snapshot and snapshot.get("stocks"):
        task = dict(task)
        task["status"] = "done"
        task["progress"] = "Completed (recovered from snapshot after restart)"
        task["updated_at"] = time.time()
        return task
    task = dict(task)
    task["status"] = "error"
    task["error"] = "Refresh interrupted by server restart; POST /api/refresh-data-on-demand to retry."
    task["updated_at"] = time.time()
    return task


def _load_refresh_tasks_from_disk() -> None:
    if not REFRESH_TASKS_PATH.exists():
        return
    try:
        raw = json.loads(REFRESH_TASKS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to load refresh tasks: %s", exc)
        return
    if not isinstance(raw, dict):
        return
    loaded_tasks = raw.get("tasks") if isinstance(raw.get("tasks"), dict) else {}
    loaded_active = raw.get("activeByKey") if isinstance(raw.get("activeByKey"), dict) else {}
    with _REFRESH_TASK_LOCK:
        for task_id, task in loaded_tasks.items():
            if not isinstance(task, dict):
                continue
            _REFRESH_TASKS[str(task_id)] = _reconcile_loaded_refresh_task(str(task_id), task)
        for dedup_key, active_id in loaded_active.items():
            if active_id in _REFRESH_TASKS:
                _ONDEMAND_ACTIVE_BY_KEY[str(dedup_key)] = str(active_id)


def _get_refresh_task_record(task_id: str) -> dict[str, Any] | None:
    with _REFRESH_TASK_LOCK:
        task = _REFRESH_TASKS.get(task_id)
    if task is not None:
        return task
    _load_refresh_tasks_from_disk()
    with _REFRESH_TASK_LOCK:
        return _REFRESH_TASKS.get(task_id)


def _refresh_task_set_done(task_id: str, result: dict[str, Any]) -> None:
    with _REFRESH_TASK_LOCK:
        if task_id in _REFRESH_TASKS:
            _REFRESH_TASKS[task_id]["status"] = "done"
            _REFRESH_TASKS[task_id]["result"] = result
            _REFRESH_TASKS[task_id]["updated_at"] = time.time()
    _persist_refresh_tasks()


def _refresh_task_set_error(task_id: str, error: str) -> None:
    with _REFRESH_TASK_LOCK:
        if task_id in _REFRESH_TASKS:
            _REFRESH_TASKS[task_id]["status"] = "error"
            _REFRESH_TASKS[task_id]["error"] = error
            _REFRESH_TASKS[task_id]["updated_at"] = time.time()
    _persist_refresh_tasks()


def _snapshot_age_seconds(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    updated_at = snapshot.get("updatedAt")
    if not updated_at:
        return None
    try:
        snap_time = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - snap_time).total_seconds()
    except Exception:
        return None


def _intraday_metrics_usable(intraday: Any) -> bool:
    """True when cached metrics come from 5m or daily candles, not a dummy stub."""
    if not isinstance(intraday, dict):
        return False
    source = str(intraday.get("data_source") or "")
    if source not in ("candles", "daily_candles"):
        return False
    reasons = [str(r) for r in (intraday.get("hard_filter_reasons") or [])]
    if any(r == "not in intraday candidate set" for r in reasons):
        return False

    def _num(key: str) -> float:
        try:
            return float(intraday.get(key) or 0)
        except (TypeError, ValueError):
            return 0.0

    return (
        _num("vwap") > 0
        or _num("rsi") > 0
        or _num("atr_pct") > 0
        or _num("turnover_cr") > 0
    )


def _prefer_intraday_metrics(quote_intra: Any, stock_intra: Any) -> dict[str, Any]:
    """Rank 5m candles over daily_candles; never let a hunt stub replace either."""
    from .desk_ic_criteria import prefer_intraday_blocks

    return prefer_intraday_blocks(quote_intra, stock_intra) or {}


def _apply_ticker_row_to_snapshot(snapshot: dict[str, Any], sym: str, merged: dict[str, Any]) -> dict[str, Any]:
    from .desk_ic_criteria import prefer_intraday_blocks

    quotes = dict(snapshot.get("stockQuotes") or {})
    existing = quotes.get(sym) if isinstance(quotes.get(sym), dict) else {}
    row = dict(merged)
    preferred = prefer_intraday_blocks(row.get("intraday"), (existing or {}).get("intraday"))
    if preferred:
        row["intraday"] = preferred
    quotes[sym] = {**(existing or {}), **row}
    snapshot["stockQuotes"] = quotes
    stocks = list(snapshot.get("stocks") or [])
    for i, srow in enumerate(stocks):
        if isinstance(srow, dict) and str(srow.get("ticker") or "").upper() == sym:
            stocks[i] = {**srow, **row}
            snapshot["stocks"] = stocks
            break
    return snapshot


def _persist_snapshot_ticker_facts(sym: str, merged: dict[str, Any]) -> None:
    """Patch one ticker onto the on-disk snapshot without rewriting an older universe."""
    from .json_atomic import atomic_update_json

    def _mutator(disk: dict[str, Any]) -> dict[str, Any]:
        return _apply_ticker_row_to_snapshot(disk, sym, merged)

    atomic_update_json(_snapshot_path(), _mutator)


def _snapshot_intraday_cache(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Reuse intraday candle metrics from last_market_snapshot when still within TTL."""
    age = _snapshot_age_seconds(snapshot)
    if age is None or age > INTRADAY_METRICS_TTL_SECONDS:
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for ticker, row in (snapshot.get("stockQuotes") or {}).items():
        if not isinstance(row, dict):
            continue
        intraday = row.get("intraday")
        if _intraday_metrics_usable(intraday):
            cache[str(ticker)] = intraday
    return cache


def ensure_snapshot_ticker_facts(snapshot: dict[str, Any], ticker: str) -> dict[str, Any]:
    """Fetch live quote + candle metrics for one ticker and persist into the snapshot."""
    if not isinstance(snapshot, dict):
        snapshot = {}
    sym = str(ticker or "").upper().strip()
    if not sym:
        return snapshot
    quotes = dict(snapshot.get("stockQuotes") or {})
    merged: dict[str, Any] = {}
    for row in snapshot.get("stocks") or []:
        if isinstance(row, dict) and str(row.get("ticker") or "").upper() == sym:
            merged.update(row)
            break
    existing = quotes.get(sym)
    if isinstance(existing, dict):
        intra = merged.get("intraday") if isinstance(merged.get("intraday"), dict) else {}
        q_intra = existing.get("intraday") if isinstance(existing.get("intraday"), dict) else {}
        merged = {**merged, **existing}
        preferred = _prefer_intraday_metrics(q_intra, intra)
        if preferred:
            merged["intraday"] = preferred
    merged["ticker"] = sym

    need_quote = float(merged.get("ltpRaw") or 0) <= 0
    need_intra = not _intraday_metrics_usable(merged.get("intraday"))
    if need_quote or need_intra:
        try:
            client = _get_fixed_plan_client()
            if client is None:
                client = AngelOneClient()
            if need_quote:
                quote = client.fetch_symbol_quote(sym)
                if quote:
                    inst = Instrument(
                        sym,
                        "NSE",
                        str(quote.get("tradingsymbol") or f"{sym}-EQ"),
                        str(quote.get("token") or "0"),
                    )
                    built = _build_stock_row(inst, quote, str(snapshot.get("activePool") or "LIVE"))
                    merged = {**merged, **built}
            if need_intra and float(merged.get("ltpRaw") or 0) > 0:
                universe: dict[str, Instrument] = {}
                try:
                    for inst in _ensure_nifty500_cache(client):
                        universe[inst.key] = inst
                except Exception:
                    universe = {}
                inst = universe.get(sym)
                if inst is None:
                    token = "0"
                    try:
                        q2 = client.fetch_symbol_quote(sym) or {}
                        token = str(q2.get("token") or "0")
                        inst = Instrument(sym, "NSE", str(q2.get("tradingsymbol") or f"{sym}-EQ"), token)
                    except Exception:
                        inst = Instrument(sym, "NSE", f"{sym}-EQ", "0")
                resolved = _resolve_nse_equity(sym, client=client)
                if resolved:
                    token, tradingsymbol = resolved
                    inst = Instrument(sym, "NSE", tradingsymbol, str(token))
                metrics_map = _fetch_intraday_chunk(
                    client,
                    [merged],
                    {sym: inst},
                    _ist_now(),
                    force_angel_fallback=True,
                )
                metrics = metrics_map.get(sym)
                if _intraday_metrics_usable(metrics):
                    merged["intraday"] = metrics
        except Exception as exc:
            logging.getLogger(__name__).warning("ensure_snapshot_ticker_facts failed for %s: %s", sym, exc)

    try:
        pct_map = ensure_promoter_holdings([sym])
        pct = pct_map.get(sym)
        if pct is not None:
            merged["promoter_holding_pct"] = pct
            intra = merged.get("intraday") if isinstance(merged.get("intraday"), dict) else {}
            intra = dict(intra)
            intra["promoter_holding_pct"] = pct
            merged["intraday"] = intra
    except Exception:
        pass

    quotes[sym] = merged
    snapshot["stockQuotes"] = quotes
    stocks = list(snapshot.get("stocks") or [])
    for i, row in enumerate(stocks):
        if isinstance(row, dict) and str(row.get("ticker") or "").upper() == sym:
            stocks[i] = {**row, **merged}
            snapshot["stocks"] = stocks
            break
    try:
        _persist_snapshot_ticker_facts(sym, merged)
    except Exception:
        pass
    return snapshot


def _top_ledger_tickers(snapshot: dict[str, Any] | None, limit: int = LLM_DISPLAY_COUNT) -> list[str]:
    if not snapshot:
        return []
    ledger = (snapshot.get("terminalIntelligence") or {}).get("ledger_stocks") or []
    return [str(row.get("ticker")).upper() for row in ledger[:limit] if row.get("ticker")]


def _ist_today() -> str:
    return _ist_now().date().isoformat()


def _llm_locked_for_today(snapshot: dict[str, Any] | None) -> bool:
    """True when terminal intelligence was locked for today's IST session."""
    if not snapshot:
        return False
    locked = str(snapshot.get("llmLockedForDate") or "").strip()[:10]
    return bool(locked) and locked == _ist_today()


def _ai_payload_reusable(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    existing_ti = snapshot.get("terminalIntelligence")
    existing_summary = snapshot.get("newsSummary")
    return bool(existing_ti) and not existing_ti.get("llmError") and bool(existing_summary)


def _ai_cache_fresh(snapshot: dict[str, Any] | None, top_tickers: list[str]) -> bool:
    """True when snapshot terminal intelligence + news summary can be reused.

    Day-lock: once llmLockedForDate == today IST, skip LLM for the rest of the session
    (external quotes/candles/macro/news still refresh). Override with forceLlmRefresh.
    Pre-lock fallback: 15m TTL + identical top-N set.
    """
    if not _ai_payload_reusable(snapshot):
        return False
    if _llm_locked_for_today(snapshot):
        return True
    age = _snapshot_age_seconds(snapshot)
    if age is None or age > AI_CACHE_TTL_SECONDS:
        return False
    cached = _top_ledger_tickers(snapshot, LLM_DISPLAY_COUNT)
    wanted = [str(t).upper() for t in top_tickers[:LLM_DISPLAY_COUNT]]
    return bool(cached) and cached == wanted


def _stamp_llm_lock(payload: dict[str, Any], *, locked: bool = True) -> dict[str, Any]:
    if locked:
        payload["llmLockedForDate"] = _ist_today()
    return payload


def _load_morning_prework_stamp() -> dict[str, Any]:
    try:
        raw = json.loads(MARKET_PREWORK_STAMP_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_morning_prework_stamp(stamp: dict[str, Any]) -> None:
    try:
        MARKET_PREWORK_STAMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        MARKET_PREWORK_STAMP_PATH.write_text(json.dumps(stamp, indent=2), encoding="utf-8")
    except Exception:
        pass


def morning_prework_done_today() -> bool:
    today = _ist_today()
    stamp = _load_morning_prework_stamp()
    if str(stamp.get("date") or "") == today and str(stamp.get("status") or "") == "done":
        return True
    snapshot = _load_last_snapshot()
    return _llm_locked_for_today(snapshot) and _ai_payload_reusable(snapshot)


def run_scheduled_morning_prework(*, force: bool = False) -> dict[str, Any]:
    """Once-per-day post-09:45 IST pre-work: live Angel refresh + LLM, then day-lock AI.

    Timed after open auction / opening-range settle so the Matrix is not built on
    stale overnight prints. Scheduler env: MARKET_PREWORK_HOUR/MINUTE (default 9:45).
    Subsequent on-demand refreshes keep external API calls live but reuse LLM output
    unless forceLlmRefresh=true.
    """
    today = _ist_today()
    if not force and morning_prework_done_today():
        return {
            "success": True,
            "skipped": True,
            "reason": "morning_prework_already_done",
            "date": today,
            "llm_locked": True,
        }

    _save_morning_prework_stamp(
        {
            "date": today,
            "status": "running",
            "startedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    log = logging.getLogger(__name__)
    pool = (os.getenv("MARKET_PREWORK_POOL") or NIFTY_500_LABEL).strip() or NIFTY_500_LABEL
    refresh_ticker_news = os.getenv("MARKET_PREWORK_TICKER_NEWS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    try:
        client = AngelOneClient()
        payload = build_market_payload(
            client,
            pool_name=pool,
            force_refresh=True,
            prefer_cache=False,
            allow_fallback=True,
            force_llm_refresh=True,
        )
        if not payload.get("success", False):
            err = str(payload.get("error") or "Morning pre-work produced no payload.")
            _save_morning_prework_stamp(
                {
                    "date": today,
                    "status": "error",
                    "error": err,
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                }
            )
            return {"success": False, "date": today, "error": err, "llm_locked": False}

        if refresh_ticker_news:
            try:
                asyncio.run(_refresh_ticker_news_for_payload(payload))
            except Exception as news_exc:
                log.warning("Morning pre-work ticker news failed: %s", news_exc)

        ti = payload.get("terminalIntelligence") or {}
        llm_ok = bool(ti) and not ti.get("llmError") and bool(payload.get("newsSummary"))
        if llm_ok:
            _stamp_llm_lock(payload, locked=True)
        payload.setdefault("selectionMeta", {})
        if isinstance(payload.get("selectionMeta"), dict):
            payload["selectionMeta"]["mode"] = "live"
            payload["selectionMeta"]["reason"] = (
                "Scheduled morning pre-work after 09:45 IST; LLM locked for the session."
            )
            payload["selectionMeta"]["dataDate"] = today
        _save_last_snapshot(payload)
        _save_morning_prework_stamp(
            {
                "date": today,
                "status": "done" if llm_ok else "partial",
                "pool": pool,
                "llm_locked": llm_ok,
                "finishedAt": datetime.now(timezone.utc).isoformat(),
            }
        )
        log.info(
            "Morning pre-work finished: date=%s pool=%s llm_locked=%s",
            today,
            pool,
            llm_ok,
        )
        return {
            "success": True,
            "skipped": False,
            "date": today,
            "pool": pool,
            "llm_locked": llm_ok,
            "universeSize": payload.get("universeSize"),
            "volumeScreenedCount": payload.get("volumeScreenedCount"),
        }
    except Exception as exc:
        log.exception("Morning pre-work failed: %s", exc)
        _save_morning_prework_stamp(
            {
                "date": today,
                "status": "error",
                "error": str(exc),
                "finishedAt": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {"success": False, "date": today, "error": str(exc), "llm_locked": False}


def run_scheduled_live_refresh(*, reason: str = "scheduled_live_refresh") -> dict[str, Any]:
    """Live Angel/Yahoo/RSS refresh with LLM day-lock reuse (no force LLM)."""
    log = logging.getLogger(__name__)
    pool = (os.getenv("MARKET_PREWORK_POOL") or NIFTY_500_LABEL).strip() or NIFTY_500_LABEL
    try:
        prior = _load_last_snapshot()
        client = AngelOneClient()
        payload = build_market_payload(
            client,
            pool_name=pool,
            force_refresh=True,
            prefer_cache=False,
            allow_fallback=True,
            force_llm_refresh=False,
        )
        if not payload.get("success", False):
            return {
                "success": False,
                "error": payload.get("error") or "Live refresh produced no payload.",
                "reason": reason,
            }
        if prior and prior.get("llmLockedForDate") and not payload.get("llmLockedForDate"):
            payload["llmLockedForDate"] = prior.get("llmLockedForDate")
        payload.setdefault("selectionMeta", {})
        if isinstance(payload.get("selectionMeta"), dict):
            payload["selectionMeta"]["mode"] = "live"
            payload["selectionMeta"]["reason"] = f"Scheduled live refresh ({reason}); LLM day-locked."
            payload["selectionMeta"]["dataDate"] = _ist_now().date().isoformat()
        _save_last_snapshot(payload)
        reused = _llm_locked_for_today(payload) or (
            bool(prior)
            and _ai_payload_reusable(prior)
            and str(payload.get("llmLockedForDate") or "") == _ist_today()
        )
        log.info("Scheduled live refresh done reason=%s llm_reused=%s", reason, reused)
        return {
            "success": True,
            "reason": reason,
            "pool": pool,
            "llm_reused": reused,
            "llmLockedForDate": payload.get("llmLockedForDate"),
            "universeSize": payload.get("universeSize"),
        }
    except Exception as exc:
        log.exception("Scheduled live refresh failed: %s", exc)
        return {"success": False, "error": str(exc), "reason": reason}


_thread_local_angel_client = threading.local()


def _candle_api_slot():
    """Hold candle mutex for the full HTTP round-trip (not just start spacing)."""

    @contextmanager
    def _slot():
        global _CANDLE_LAST_CALL_MONO, _CANDLE_COOLDOWN_UNTIL_MONO
        with _CANDLE_THROTTLE_LOCK:
            now = time.monotonic()
            wait = max(
                0.0,
                _CANDLE_COOLDOWN_UNTIL_MONO - now,
                CANDLE_MIN_INTERVAL_SECONDS - (now - _CANDLE_LAST_CALL_MONO),
            )
            if wait > 0:
                time.sleep(wait)
            try:
                yield
            finally:
                _CANDLE_LAST_CALL_MONO = time.monotonic()

    return _slot()


def _throttle_candle_api() -> None:
    """Legacy start-spacing helper — prefer ``_candle_api_slot`` for HTTP calls."""
    global _CANDLE_LAST_CALL_MONO, _CANDLE_COOLDOWN_UNTIL_MONO
    with _CANDLE_THROTTLE_LOCK:
        now = time.monotonic()
        wait = max(
            0.0,
            _CANDLE_COOLDOWN_UNTIL_MONO - now,
            CANDLE_MIN_INTERVAL_SECONDS - (now - _CANDLE_LAST_CALL_MONO),
        )
        if wait > 0:
            time.sleep(wait)
        _CANDLE_LAST_CALL_MONO = time.monotonic()


def _trip_candle_rate_limit_cooldown(seconds: float = 8.0) -> None:
    global _CANDLE_COOLDOWN_UNTIL_MONO
    _CANDLE_COOLDOWN_UNTIL_MONO = max(_CANDLE_COOLDOWN_UNTIL_MONO, time.monotonic() + seconds)


def _angel_candle_calls_allowed() -> bool:
    return time.monotonic() >= _ANGEL_CANDLE_CIRCUIT_UNTIL


def _trip_angel_candle_circuit(seconds: float | None = None) -> None:
    """Stop further Angel getCandleData calls after AB1021 (whole 500-name scan)."""
    global _ANGEL_CANDLE_CIRCUIT_UNTIL
    hold = ANGEL_CANDLE_CIRCUIT_SECONDS if seconds is None else float(seconds)
    until = time.monotonic() + max(1.0, hold)
    if until > _ANGEL_CANDLE_CIRCUIT_UNTIL:
        logging.getLogger(__name__).warning(
            "Angel candle circuit open for %.0fs after AB1021; remaining names use Dhan or stay empty",
            hold,
        )
    _ANGEL_CANDLE_CIRCUIT_UNTIL = max(_ANGEL_CANDLE_CIRCUIT_UNTIL, until)
    _trip_candle_rate_limit_cooldown(hold)


def _is_candle_rate_limited(response_or_exc: Any) -> bool:
    if isinstance(response_or_exc, dict):
        msg = str(response_or_exc.get("message") or "")
        code = str(response_or_exc.get("errorcode") or response_or_exc.get("errorCode") or "")
    else:
        msg = str(response_or_exc or "")
        code = ""
    blob = f"{code} {msg}".lower()
    return "ab1021" in blob or "too many requests" in blob or "rate limit" in blob


def _get_thread_angel_client() -> AngelOneClient:
    client = getattr(_thread_local_angel_client, "client", None)
    if client is None:
        client = AngelOneClient()
        _thread_local_angel_client.client = client
    return client


# -----------------------------------------------------------------------------
# NEWS INGESTION — RSS / Atom feeds (structured, not scraped HTML body text)
# -----------------------------------------------------------------------------
# Each entry: (display_name, rss_or_atom_url, default_category)
# Feeds are fetched concurrently and parsed as XML. A dead feed simply raises
# and is skipped, so it never blanks the whole panel. This replaces the old
# HTML-body scraping which returned nav text instead of real headlines.

# Direct publisher feeds (verified parseable). A number of large Indian
# outlets (ET, Business Standard, FE, CNBC-TV18, Zee, BL) either block
# server-side fetches or dropped public RSS, so we lean on Google News
# topic feeds (which surface the same publishers) for reliable breadth.
NEWS_RSS_FEEDS: list[tuple[str, str, str]] = [
    # --- Direct publisher RSS/Atom feeds ---
    ("Moneycontrol Latest", "https://www.moneycontrol.com/rss/latestnews.xml", "Market"),
    ("Moneycontrol Business", "https://www.moneycontrol.com/rss/business.xml", "Corporate"),
    ("Moneycontrol Economy", "https://www.moneycontrol.com/rss/economy.xml", "Economy"),
    ("Livemint Markets", "https://www.livemint.com/rss/markets", "Market"),
    ("Livemint Companies", "https://www.livemint.com/rss/companies", "Corporate"),
    ("Livemint Money", "https://www.livemint.com/rss/money", "Economy"),
    ("Livemint Opinion", "https://www.livemint.com/rss/opinion", "Market"),
    ("News18 Markets", "https://www.news18.com/rss/markets.xml", "Market"),
    ("News18 Business", "https://www.news18.com/rss/business.xml", "Market"),
    ("Indian Express Business", "https://indianexpress.com/section/business/feed/", "Market"),
    ("Inc42", "https://inc42.com/feed/", "Corporate"),
    ("YourStory", "https://yourstory.com/feed", "Corporate"),
    # --- Google News topic feeds (India-focused, reliably parseable) ---
    # Each entry's <source> element carries the real publisher, so the
    # frontend badge shows the actual outlet, not "Google News".
    ("Google · Markets", "https://news.google.com/rss/search?q=indian+stock+market&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · Sensex Nifty", "https://news.google.com/rss/search?q=sensex+nifty&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · FII DII", "https://news.google.com/rss/search?q=india+FII+DII+market&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
    ("Google · RBI Policy", "https://news.google.com/rss/search?q=RBI+monetary+policy+india&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · SEBI", "https://news.google.com/rss/search?q=SEBI+india&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · Earnings", "https://news.google.com/rss/search?q=indian+company+earnings+results&hl=en-IN&gl=IN&ceid=IN:en", "Earnings"),
    ("Google · Dividend Buyback", "https://news.google.com/rss/search?q=india+dividend+buyback&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · IPO", "https://news.google.com/rss/search?q=indian+IPO+listing&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Corporate Deals", "https://news.google.com/rss/search?q=indian+company+merger+acquisition+deal&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · IT Sector", "https://news.google.com/rss/search?q=indian+IT+sector+stocks&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Pharma", "https://news.google.com/rss/search?q=indian+pharma+stocks&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Auto Sales", "https://news.google.com/rss/search?q=india+auto+sales&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Bank NPA", "https://news.google.com/rss/search?q=indian+banks+NPA&hl=en-IN&gl=IN&ceid=IN:en", "Regulatory"),
    ("Google · GST Budget", "https://news.google.com/rss/search?q=india+GST+budget+economy&hl=en-IN&gl=IN&ceid=IN:en", "Economy"),
    ("Google · Infrastructure", "https://news.google.com/rss/search?q=india+infrastructure+ECONOMIC&hl=en-IN&gl=IN&ceid=IN:en", "Economy"),
    ("Google · Crude Oil", "https://news.google.com/rss/search?q=india+crude+oil+price&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Gold", "https://news.google.com/rss/search?q=india+gold+price&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Rupee Dollar", "https://news.google.com/rss/search?q=indian+rupee+dollar+forex&hl=en-IN&gl=IN&ceid=IN:en", "Commodity"),
    ("Google · Startup Funding", "https://news.google.com/rss/search?q=india+startup+funding&hl=en-IN&gl=IN&ceid=IN:en", "Corporate"),
    ("Google · Mutual Funds", "https://news.google.com/rss/search?q=india+mutual+funds+AMC&hl=en-IN&gl=IN&ceid=IN:en", "Market"),
]

LIVE_UNIVERSE_LABEL = "Live Universe"


def _news_feed_sources() -> list[str]:
    return [name for name, _, _ in NEWS_RSS_FEEDS]


def _filter_prompt(custom_prompt: str | None = None) -> str:
    parts = []
    env_prompt = os.getenv("MARKET_FILTER_PROMPT", "").strip()
    if env_prompt:
        parts.append(env_prompt)
    if custom_prompt and custom_prompt.strip():
        parts.append(custom_prompt.strip())
    parts.append(
        "Short-term investment profile: exclude risky low-promoter names (YES Bank, Ola Electric, etc.). "
        f"Require promoter holding >= {MIN_PROMOTER_HOLDING_PCT:g}%, "
        "high liquidity (turnover + volume multiplier), price above VWAP and EMA9, "
        "pivot R1 breakout with RSI momentum, bullish OI (long buildup / short covering), "
        "and clean wick structure. Prefer quality compounders over speculative momentum."
    )
    parts.append(
        "Use the live Angel One universe below to select the top "
        f"{_TI_TOP_SELECTION_COUNT} stocks. Prefer the Nifty 100 universe; do not restrict selection to Nifty 50 only. "
        "Do not invent tickers. Return valid JSON only."
    )
    return " ".join(parts)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_credential() -> str:
    """Return Angel One credential: prefer ANGEL_MPIN (4-digit), fall back to ANGEL_PASSWORD."""
    mpin = (os.getenv("ANGEL_MPIN") or "").strip()
    if mpin:
        if len(mpin) != 4 or not mpin.isdigit():
            raise RuntimeError("ANGEL_MPIN must be exactly 4 digits")
        return mpin
    password = (os.getenv("ANGEL_PASSWORD") or "").strip()
    if not password:
        raise RuntimeError("Missing ANGEL_MPIN or ANGEL_PASSWORD in backend .env")
    return password


def _pct_change(ltp: float, close: float | None) -> tuple[str, str]:
    """Return absolute pts + signed pct for desk tiles, e.g. ``27.70 (-0.11%)``.

    Percentage is always signed so regime / parsers never confuse pts with %.
    """
    if close in (None, 0):
        return "0.00 (+0.00%)", "POSITIVE"
    pts = float(ltp) - float(close)
    pct = (pts / float(close)) * 100.0
    state = "POSITIVE" if pts >= 0 else "NEGATIVE"
    sign = "+" if pts >= 0 else "-"
    return f"{abs(pts):,.2f} ({sign}{abs(pct):.2f}%)", state


def _format_inr(value: float) -> str:
    return f"₹{value:,.2f}"


def _snapshot_path() -> Path:
    from .market_snapshot_store import market_snapshot_path

    return market_snapshot_path()


def _ist_now() -> datetime:
    return datetime.now(tz=IST_ZONE)


def _within_refresh_window(now: datetime | None = None) -> bool:
    now = now or _ist_now()
    current_minutes = now.hour * 60 + now.minute
    morning_start = MORNING_REFRESH_START[0] * 60 + MORNING_REFRESH_START[1]
    morning_end = MORNING_REFRESH_END[0] * 60 + MORNING_REFRESH_END[1]
    evening_start = EVENING_REFRESH_START[0] * 60 + EVENING_REFRESH_START[1]
    evening_end = EVENING_REFRESH_END[0] * 60 + EVENING_REFRESH_END[1]
    return (morning_start <= current_minutes < morning_end) or (evening_start <= current_minutes < evening_end)


def _normalize_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    payload["rawSources"] = _news_feed_sources()
    available_pools = [pool for pool in payload.get("availablePools", []) if pool != "Nifty 50"]
    if NIFTY_500_LABEL not in available_pools:
        available_pools.insert(0, NIFTY_500_LABEL)
    if NIFTY_100_LABEL not in available_pools:
        available_pools.append(NIFTY_100_LABEL)
    if LIVE_UNIVERSE_LABEL not in available_pools:
        available_pools.append(LIVE_UNIVERSE_LABEL)
    payload["availablePools"] = available_pools
    payload.setdefault("activePool", NIFTY_500_LABEL)
    payload.setdefault("poolDescription", "Nifty 500 Angel One live universe; swing hunt uses the full index.")
    payload.setdefault("tickerNewsByTicker", {})
    return payload


def _load_watchlist_from_cache(path: Path) -> list[Instrument]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        instruments = raw.get("instruments", []) if isinstance(raw, dict) else []
        return [
            Instrument(
                key=str(item["key"]),
                exchange=str(item.get("exchange", "NSE")),
                tradingsymbol=str(item["tradingsymbol"]),
                token=str(item["token"]),
                label=str(item.get("label") or item["key"]),
            )
            for item in instruments
            if item.get("key") and item.get("token") and item.get("tradingsymbol")
        ]
    except Exception:
        return []


def _fetch_nse_index_symbols(index: str = "NIFTY 500") -> list[str]:
    """Fetch EQ symbols for an NSE index (e.g. Nifty 500)."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.nseindia.com/",
        "Accept": "application/json, text/plain, */*",
    })
    try:
        session.get("https://www.nseindia.com", timeout=20)
        response = session.get(
            "https://www.nseindia.com/api/equity-stock-indices",
            params={"index": index},
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        return sorted({
            str(row["symbol"]).upper()
            for row in rows
            if row.get("series") == "EQ" and row.get("symbol")
        })
    except Exception as exc:
        logging.getLogger(__name__).warning("NSE index fetch failed for %s: %s", index, exc)
        return []


def _load_nifty500_symbol_list() -> list[str]:
    """Load Nifty 500 symbols from NSE, falling back to the bundled JSON seed."""
    symbols = _fetch_nse_index_symbols("NIFTY 500")
    if symbols:
        return symbols
    try:
        raw = json.loads(NIFTY_500_SYMBOLS_PATH.read_text(encoding="utf-8"))
        return [str(symbol).upper() for symbol in raw.get("symbols", []) if symbol]
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to load Nifty 500 symbol seed: %s", exc)
        return []


def _persist_nifty500_symbol_seed(symbols: list[str]) -> None:
    if not symbols:
        return
    try:
        NIFTY_500_SYMBOLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        NIFTY_500_SYMBOLS_PATH.write_text(
            json.dumps(
                {
                    "label": NIFTY_500_LABEL,
                    "source": "NSE equity-stock-indices",
                    "refreshedAt": _ist_now().date().isoformat(),
                    "count": len(symbols),
                    "symbols": symbols,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to persist Nifty 500 symbol seed: %s", exc)


def _load_nse_eq_token_map(force_refresh: bool = False) -> dict[str, tuple[str, str]]:
    """Map NSE equity symbol -> (token, tradingsymbol) using Angel scrip master + WATCHLIST."""
    global _NSE_EQ_TOKEN_MAP, _NSE_EQ_TOKEN_MAP_LOADED_AT
    now = time.time()
    if (
        not force_refresh
        and _NSE_EQ_TOKEN_MAP is not None
        and (now - _NSE_EQ_TOKEN_MAP_LOADED_AT) < _NSE_EQ_TOKEN_MAP_TTL_SECONDS
    ):
        return _NSE_EQ_TOKEN_MAP

    token_map: dict[str, tuple[str, str]] = {
        inst.key: (inst.token, inst.tradingsymbol) for inst in WATCHLIST
    }
    try:
        response = requests.get(SCRIP_MASTER_URL, timeout=120)
        response.raise_for_status()
        rows = response.json()
        for row in rows:
            if str(row.get("exch_seg", "")).upper() != "NSE":
                continue
            tradingsymbol = str(row.get("symbol", ""))
            if not tradingsymbol.endswith("-EQ"):
                continue
            name = str(row.get("name", "")).upper()
            token = str(row.get("token", ""))
            if name and token:
                token_map[name] = (token, tradingsymbol)
    except Exception as exc:
        logging.getLogger(__name__).warning("Angel scrip master fetch failed: %s", exc)

    _NSE_EQ_TOKEN_MAP = token_map
    _NSE_EQ_TOKEN_MAP_LOADED_AT = now
    return token_map


def _pick_eq_search_result(data: list[Any], symbol_key: str) -> dict[str, Any] | None:
    """Prefer the NSE cash EQ row when searchScrip returns multiple series."""
    if not data:
        return None
    symbol_key = symbol_key.upper()
    preferred = f"{symbol_key}-EQ"

    def trading_symbol(row: dict[str, Any]) -> str:
        return str(row.get("symbol") or row.get("tradingsymbol") or "").upper()

    for row in data:
        if isinstance(row, dict) and trading_symbol(row) == preferred:
            return row
    for row in data:
        if isinstance(row, dict) and trading_symbol(row).endswith("-EQ"):
            return row
    first = data[0]
    return first if isinstance(first, dict) else None


def _resolve_nse_equity(
    symbol: str,
    client: AngelOneClient | None = None,
    token_map: dict[str, tuple[str, str]] | None = None,
) -> tuple[str, str] | None:
    """Resolve an NSE cash equity symbol to (token, tradingsymbol)."""
    key = symbol.upper()
    mapping = token_map if token_map is not None else _load_nse_eq_token_map()
    if key in mapping:
        return mapping[key]

    if client is None:
        return None

    smart = client.connect()
    for query in (f"{key}-EQ", key):
        try:
            search = smart.searchScrip("NSE", query)
        except Exception:
            continue
        if not isinstance(search, dict) or not search.get("status"):
            continue
        data = search.get("data") or []
        if not isinstance(data, list) or not data:
            continue
        pick = _pick_eq_search_result(data, key)
        if not pick:
            continue
        token = str(pick.get("token") or pick.get("symboltoken") or "")
        tradingsymbol = str(pick.get("symbol") or pick.get("tradingsymbol") or f"{key}-EQ")
        if token:
            return token, tradingsymbol
    return None


def _symbols_to_instruments(
    symbols: list[str],
    token_map: dict[str, tuple[str, str]],
    client: AngelOneClient | None = None,
) -> list[Instrument]:
    instruments: list[Instrument] = []
    missing: list[str] = []

    for symbol in symbols:
        key = symbol.upper()
        entry = token_map.get(key)
        if entry:
            token, tradingsymbol = entry
            instruments.append(Instrument(key, "NSE", tradingsymbol, token, key))
        else:
            missing.append(key)

    if missing and client is not None:
        for key in missing:
            resolved = _resolve_nse_equity(key, client=client, token_map=token_map)
            if not resolved:
                continue
            token, tradingsymbol = resolved
            instruments.append(Instrument(key, "NSE", tradingsymbol, token, key))

    return instruments


def _read_nifty500_cache_raw() -> dict[str, Any]:
    try:
        raw = json.loads(NIFTY_500_CACHE_PATH.read_text(encoding="utf-8-sig"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _nifty500_cache_health(raw: dict[str, Any]) -> dict[str, Any]:
    instruments = raw.get("instruments") if isinstance(raw.get("instruments"), list) else []
    source_count = int(raw.get("sourceSymbols") or raw.get("universeExpected") or 0)
    resolved = len(instruments)
    coverage = (resolved / source_count * 100.0) if source_count else 0.0
    refreshed = raw.get("refreshedAt") or raw.get("exportedAtUtc")
    try:
        refreshed_dt = datetime.fromisoformat(str(refreshed).replace("Z", "+00:00"))
        age = max(0.0, (datetime.now(timezone.utc) - refreshed_dt).total_seconds())
    except Exception:
        age = float("inf")
    healthy = bool(
        source_count >= NIFTY_CACHE_EXPECTED_MIN
        and resolved >= NIFTY_CACHE_EXPECTED_MIN
        and coverage >= NIFTY_CACHE_MIN_COVERAGE_PCT
        and age <= NIFTY_CACHE_MAX_AGE_SECONDS
        and raw.get("partial") is not True
    )
    return {
        "healthy": healthy,
        "expected": source_count,
        "resolved": resolved,
        "coveragePct": round(coverage, 2),
        "ageSeconds": None if math.isinf(age) else round(age, 1),
        "partial": bool(raw.get("partial", not healthy)),
    }


def _ensure_nifty500_cache(client: AngelOneClient | None = None) -> list[Instrument]:
    raw = _read_nifty500_cache_raw()
    health = _nifty500_cache_health(raw)
    if health["healthy"]:
        return _load_watchlist_from_cache(NIFTY_500_CACHE_PATH)
    result = refresh_nifty500_cache(client=client)
    if result.get("success"):
        return _load_watchlist_from_cache(NIFTY_500_CACHE_PATH)
    raise RuntimeError(
        "Nifty 500 cache is incomplete; selection aborted "
        f"(resolved={health['resolved']}, expected={health['expected']}, "
        f"coverage={health['coveragePct']}%). Refresh error: {result.get('error')}"
    )


def _pool_watchlist(pool_name: str | None, client: AngelOneClient | None = None) -> tuple[list[Instrument], str]:
    resolved = pool_name or NIFTY_500_LABEL

    if resolved == "Nifty 50":
        resolved = NIFTY_100_LABEL

    if resolved == NIFTY_500_LABEL:
        nifty500 = _ensure_nifty500_cache(client)
        if nifty500:
            return nifty500, NIFTY_500_LABEL
        logging.getLogger(__name__).warning(
            "Nifty 500 cache empty at %s. Falling back to static WATCHLIST (%d symbols). "
            "Populate the cache via POST /api/refresh-instrument-cache.",
            NIFTY_500_CACHE_PATH, len(WATCHLIST),
        )

    if resolved == NIFTY_100_LABEL:
        # Prefer Nifty 500 with daily rotation so different constituents
        # get surfaced each day instead of the same static Nifty 100 set.
        nifty500 = _ensure_nifty500_cache(client)
        if nifty500:
            return _rotate_nifty500(nifty500), NIFTY_100_LABEL
        nifty100 = _load_watchlist_from_cache(NIFTY_100_CACHE_PATH)
        if nifty100:
            return [inst for inst in nifty100 if inst.key not in NIFTY_50_KEYS], NIFTY_100_LABEL
        logging.getLogger(__name__).warning(
            "Nifty 500 cache empty at %s and Nifty 100 cache empty. Falling back to static WATCHLIST (%d symbols). "
            "Populate the cache via POST /api/refresh-instrument-cache to get a rotating universe.",
            NIFTY_500_CACHE_PATH, len(WATCHLIST),
        )

    if resolved == LIVE_UNIVERSE_LABEL:
        return [inst for inst in WATCHLIST if inst.key not in NIFTY_50_KEYS], LIVE_UNIVERSE_LABEL

    return [inst for inst in WATCHLIST if inst.key not in NIFTY_50_KEYS], resolved


def _rotate_nifty500(nifty500: list[Instrument]) -> list[Instrument]:
    """Return a day-rotated 200-stock window from the Nifty 500 cache."""
    window_size = min(200, len(nifty500))
    idx = _ist_now().day % max(len(nifty500) - window_size, 1)
    rotated = nifty500[idx:] + nifty500[:idx]
    window = rotated[:window_size]
    return [inst for inst in window if inst.key not in NIFTY_50_KEYS]


def _quote_universe(pool_name: str | None, client: AngelOneClient | None = None) -> tuple[list[Instrument], str]:
    """Always quote Nifty 500 so swing hunt is not clipped by the Matrix pool.

    Nifty 100 / Live Universe still keep their display label. Missing 500-cache
    falls back to the display watchlist.
    """
    display, label = _pool_watchlist(pool_name, client)
    if label == NIFTY_500_LABEL:
        return display, label
    swing, swing_label = _pool_watchlist(NIFTY_500_LABEL, client)
    if swing_label != NIFTY_500_LABEL or not swing:
        return display, label
    merged: dict[str, Instrument] = {inst.key: inst for inst in display}
    for inst in swing:
        merged.setdefault(inst.key, inst)
    return list(merged.values()), label


def refresh_nifty500_cache(client: AngelOneClient | None = None) -> dict[str, Any]:
    """Build the Nifty 500 instrument cache from NSE constituents + Angel scrip master.

    Returns a status dict with counts and any errors encountered.
    """
    try:
        symbols = _load_nifty500_symbol_list()
        if not symbols:
            return {"success": False, "error": "No Nifty 500 symbols available from NSE or seed file", "fetched": 0}

        _persist_nifty500_symbol_seed(symbols)
        token_map = _load_nse_eq_token_map(force_refresh=True)
        resolved = _symbols_to_instruments(symbols, token_map, client=client)
        resolved_keys = {inst.key for inst in resolved}
        # Dhan's official master repairs symbols missing from Angel.  Prefixing
        # the provider id prevents accidental use as an Angel token.
        dhan_ids = load_dhan_security_ids(force=True)
        for symbol in symbols:
            key = symbol.upper()
            if key not in resolved_keys and dhan_ids.get(key):
                resolved.append(Instrument(key, "NSE", f"{key}-EQ", f"DHAN:{dhan_ids[key]}", key))
                resolved_keys.add(key)
        if not resolved:
            return {"success": False, "error": "No instruments resolved for Nifty 500 universe", "fetched": 0}

        deduped: list[dict[str, str]] = []
        seen_tokens: set[str] = set()
        seen_keys: set[str] = set()
        for inst in resolved:
            if inst.token in seen_tokens or inst.key in seen_keys:
                continue
            seen_tokens.add(inst.token)
            seen_keys.add(inst.key)
            deduped.append({
                "key": inst.key,
                "exchange": inst.exchange,
                "tradingsymbol": inst.tradingsymbol,
                "token": inst.token,
                "label": inst.label or inst.key,
            })

        missing_symbols = sorted(set(str(s).upper() for s in symbols) - seen_keys)
        coverage_pct = len(deduped) / len(symbols) * 100.0 if symbols else 0.0
        healthy = bool(
            len(symbols) >= NIFTY_CACHE_EXPECTED_MIN
            and len(deduped) >= NIFTY_CACHE_EXPECTED_MIN
            and coverage_pct >= NIFTY_CACHE_MIN_COVERAGE_PCT
        )
        cache_blob = {
            "label": NIFTY_500_LABEL,
            "refreshedAt": datetime.now(timezone.utc).isoformat(),
            "count": len(deduped),
            "sourceSymbols": len(symbols),
            "universeExpected": len(symbols),
            "coveragePct": round(coverage_pct, 2),
            "partial": not healthy,
            "unresolved": missing_symbols,
            "instruments": deduped,
        }
        if not healthy:
            return {
                "success": False,
                "error": (
                    f"Refusing partial Nifty 500 cache: {len(deduped)}/{len(symbols)} "
                    f"resolved ({coverage_pct:.2f}%)"
                ),
                "fetched": len(deduped),
                "sourceSymbols": len(symbols),
                "missing": len(missing_symbols),
                "missingSymbols": missing_symbols,
            }
        try:
            tmp_path = NIFTY_500_CACHE_PATH.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(cache_blob, indent=2), encoding="utf-8")
            os.replace(tmp_path, NIFTY_500_CACHE_PATH)
        except Exception as exc_write:
            logging.getLogger(__name__).error("Failed to write Nifty 500 cache: %s", exc_write)
            return {"success": False, "error": f"Cache write failed: {exc_write}", "fetched": len(deduped)}

        missing = len(missing_symbols)
        if missing > 0:
            logging.getLogger(__name__).warning(
                "Nifty 500 cache built with %d/%d symbols resolved (%d missing tokens).",
                len(deduped), len(symbols), missing,
            )

        return {
            "success": True,
            "fetched": len(deduped),
            "sourceSymbols": len(symbols),
            "missing": missing,
            "cachePath": str(NIFTY_500_CACHE_PATH),
        }
    except Exception as exc:
        logging.getLogger(__name__).error("Nifty 500 cache refresh failed: %s", exc)
        return {"success": False, "error": str(exc), "fetched": 0}


def refresh_nifty100_cache(client: AngelOneClient | None = None) -> dict[str, Any]:
    """Fetch Nifty 100 instruments from Angel One and persist to cache."""
    try:
        own_client = client is None
        if own_client:
            client = AngelOneClient()

        instruments: list[dict[str, str]] = []
        try:
            from ..utils.symbols import WATCHLIST
            seed_symbols = [inst.key for inst in WATCHLIST if inst.key not in ("NIFTY 50", "NIFTY BANK", "NIFTY NXT 50")]
        except Exception:
            seed_symbols = []

        for sym in seed_symbols:
            resolved = _resolve_nse_equity(sym, client=client)
            if not resolved:
                continue
            token, ts = resolved
            instruments.append({
                "key": sym,
                "exchange": "NSE",
                "tradingsymbol": ts,
                "token": token,
                "label": sym,
            })

        if not instruments:
            return {"success": False, "error": "No instruments resolved for Nifty 100 universe", "fetched": 0}

        seen_tokens: set[str] = set()
        seen_keys: set[str] = set()
        deduped: list[dict[str, str]] = []
        for item in instruments:
            tok = item["token"]
            key = item["key"]
            if tok in seen_tokens or key in seen_keys:
                continue
            seen_tokens.add(tok)
            seen_keys.add(key)
            deduped.append(item)

        cache_blob = {
            "label": "Nifty 100",
            "refreshedAt": datetime.now(timezone.utc).isoformat(),
            "count": len(deduped),
            "instruments": deduped,
        }
        try:
            NIFTY_100_CACHE_PATH.write_text(json.dumps(cache_blob, indent=2), encoding="utf-8")
        except Exception as exc_write:
            logging.getLogger(__name__).error("Failed to write Nifty 100 cache: %s", exc_write)
            return {"success": False, "error": f"Cache write failed: {exc_write}", "fetched": len(deduped)}

        if own_client:
            try:
                client._reset_connection()
            except Exception:
                pass

        return {"success": True, "fetched": len(deduped), "cachePath": str(NIFTY_100_CACHE_PATH)}
    except Exception as exc:
        logging.getLogger(__name__).error("Nifty 100 cache refresh failed: %s", exc)
        return {"success": False, "error": str(exc), "fetched": 0}


def _payload_data_date(payload: dict[str, Any] | None = None) -> str:
    if payload:
        meta = payload.get("selectionMeta")
        if isinstance(meta, dict) and meta.get("dataDate"):
            return str(meta["dataDate"])[:10]
    return _ist_now().date().isoformat()


def _apply_selection_meta(
    payload: dict[str, Any],
    *,
    mode: str,
    reason: str,
    data_date: str | None = None,
) -> dict[str, Any]:
    payload["selectionMeta"] = {
        "mode": mode,
        "reason": reason,
        "dataDate": data_date or _payload_data_date(payload),
    }
    return payload


def _hydrate_ticker_intelligence_map(payload: dict[str, Any]) -> dict[str, Any]:
    payload["tickerIntelligenceByTicker"] = build_ticker_intelligence_map(payload)
    return payload


_DHAN_SWING_TTL_SECONDS = 300


def _normalize_dhan_swing_pick(rec: dict[str, Any]) -> dict[str, Any]:
    sym = str(rec.get("symbol") or rec.get("ticker") or "").upper()
    entry = rec.get("buyAbove") or rec.get("entryPrice") or rec.get("entry")
    return {
        "symbol": sym,
        "name": rec.get("name") or sym,
        "direction": str(rec.get("direction") or "LONG").upper(),
        "buyAbove": entry,
        "stopLoss": rec.get("stopLoss"),
        "target1": rec.get("target1"),
        "target2": rec.get("target2"),
        "riskPerShare": rec.get("riskPerShare"),
        "rrT2": rec.get("rrT2"),
        "rsi": rec.get("rsi"),
        "deliveryPct": rec.get("deliveryPct"),
        "score": rec.get("score"),
        "reasons": rec.get("reasons"),
        "scanLtp": rec.get("scanLtp"),
    }


def _fetch_dhan_swing_picks_for_market() -> dict[str, Any]:
    """Dhan LONG swing/scanner picks for Asset Matrix — facts only, no mock fallback."""
    out: dict[str, Any] = {
        "source": "dhan-scanx",
        "picks": [],
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "isMock": False,
    }
    try:
        from .dhan_scanner_service import fetch_dhan_scan_results
        from .trade_outcome import load_persisted_long_scanner_picks

        result = fetch_dhan_scan_results(min_volume=1_000_000, top_n=10)
        if result.get("isMock"):
            persisted = load_persisted_long_scanner_picks()
            out["picks"] = [_normalize_dhan_swing_pick(p) for p in persisted]
            out["fromPersisted"] = bool(out["picks"])
            out["error"] = result.get("error") or "Dhan API unreachable (mock skipped for desk)"
            return out

        picks: list[dict[str, Any]] = []
        for rec in result.get("recommendations") or []:
            if str(rec.get("direction") or "LONG").upper() != "LONG":
                continue
            picks.append(_normalize_dhan_swing_pick(rec))
        out["picks"] = picks
        out["scannedCount"] = result.get("scannedCount")
        out["longPassedCount"] = result.get("longPassedCount")
        return out
    except Exception as exc:
        from .trade_outcome import load_persisted_long_scanner_picks

        persisted = load_persisted_long_scanner_picks()
        out["error"] = str(exc)
        out["picks"] = [_normalize_dhan_swing_pick(p) for p in persisted]
        out["fromPersisted"] = bool(out["picks"])
        return out


def _picks_from_scanner_map(scanner_map: Any) -> list[dict[str, Any]]:
    if not isinstance(scanner_map, dict):
        return []
    picks: list[dict[str, Any]] = []
    for rec in scanner_map.values():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("direction") or "LONG").upper() != "LONG":
            continue
        sym = rec.get("symbol") or rec.get("ticker")
        if sym:
            picks.append(_normalize_dhan_swing_pick(rec))
    return picks


def _dhan_swing_picks_has_data(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    return bool(block.get("picks")) or bool(block.get("fromPersisted"))


def _dhan_swing_picks_is_fresh(block: Any) -> bool:
    if not _dhan_swing_picks_has_data(block):
        return False
    updated = block.get("updatedAt")
    if not isinstance(updated, str):
        return False
    try:
        ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < _DHAN_SWING_TTL_SECONDS
    except Exception:
        return False


def _build_dhan_swing_picks_from_persisted(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fast path: trade_api_snapshot scannerPicks or inline scannerPicks on payload."""
    from .trade_outcome import load_persisted_long_scanner_picks

    persisted = load_persisted_long_scanner_picks()
    if persisted:
        return {
            "source": "scannerPicks-persisted",
            "picks": [_normalize_dhan_swing_pick(p) for p in persisted],
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "isMock": False,
            "fromPersisted": True,
        }

    inline = _picks_from_scanner_map((payload or {}).get("scannerPicks"))
    if inline:
        return {
            "source": "scannerPicks-inline",
            "picks": inline,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "isMock": False,
            "fromPersisted": True,
        }
    return None


def _hydrate_dhan_swing_picks(
    payload: dict[str, Any],
    *,
    force: bool = False,
    prefer_persisted: bool = False,
) -> dict[str, Any]:
    existing = payload.get("dhanSwingPicks")
    if existing and not force and _dhan_swing_picks_is_fresh(existing):
        return payload

    if prefer_persisted or (not force and payload.get("isSnapshotFallback")):
        fast = _build_dhan_swing_picks_from_persisted(payload)
        if fast:
            payload["dhanSwingPicks"] = fast
            return payload

    fetched = _fetch_dhan_swing_picks_for_market()
    if not fetched.get("picks"):
        fast = _build_dhan_swing_picks_from_persisted(payload)
        if fast:
            fetched = fast

    payload["dhanSwingPicks"] = fetched
    return payload


def _load_last_snapshot() -> dict[str, Any] | None:
    from .market_snapshot_store import readable_market_snapshot_path

    for path in (_snapshot_path(), readable_market_snapshot_path()):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return _normalize_snapshot(payload)
        except Exception:
            continue
    return None


def _save_last_snapshot(payload: dict[str, Any]) -> None:
    try:
        payload = _enrich_snapshot_with_fixed_plan(payload)
    except Exception as exc:
        log.warning("Fixed-plan snapshot enrichment failed: %s", exc)
    try:
        existing = payload.get("dhanSwingPicks")
        if not _dhan_swing_picks_has_data(existing):
            payload = _hydrate_dhan_swing_picks(payload, prefer_persisted=True)
        elif not _dhan_swing_picks_is_fresh(existing):
            payload = _hydrate_dhan_swing_picks(payload, prefer_persisted=True)
    except Exception as exc:
        log.warning("dhanSwingPicks snapshot hydration failed: %s", exc)
    try:
        from .json_atomic import atomic_write_json

        path = _snapshot_path()
        atomic_write_json(path, _normalize_snapshot(payload))
    except Exception:
        try:
            path = _snapshot_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_normalize_snapshot(payload), indent=2), encoding="utf-8")
        except Exception:
            pass


def refresh_fixed_plan_close_marks(*, force: bool = True) -> dict[str, Any]:
    """Rewrite last_market_snapshot.json with fresh Angel LTPs for every plan ticker.

    Used post-close (and on demand) so INTRADAY/EOD polls see closing prints
    instead of a frozen pre-15:30 snapshot. Does not invent prices.
    """
    global _FIXED_PLAN_QUOTE_CACHE
    if force:
        _FIXED_PLAN_QUOTE_CACHE = {}
    payload = _load_last_snapshot() or {
        "stockQuotes": {},
        "updatedAt": datetime.now(tz=timezone.utc).isoformat(),
        "activePool": "Fixed Plan",
    }
    payload = _enrich_snapshot_with_fixed_plan(payload)
    payload["updatedAt"] = datetime.now(tz=timezone.utc).isoformat()
    payload["closeMarksRefreshedAt"] = payload["updatedAt"]
    try:
        _snapshot_path().write_text(json.dumps(_normalize_snapshot(payload), indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("close-marks snapshot write failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    n = len(payload.get("stockQuotes") or {})
    log.info("Fixed-plan close marks refreshed · stockQuotes=%s", n)
    return {"ok": True, "quoteCount": n, "updatedAt": payload["updatedAt"]}


# Cache so a single refresh (which may call _save_last_snapshot multiple times)
# only resolves fixed-plan quotes once; TTL also caps background saves.
_FIXED_PLAN_QUOTE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_FIXED_PLAN_QUOTE_TTL = 60  # seconds — keep plan LTPs fresh for INTRADAY/EOD polls
_FIXED_PLAN_CLIENT: "AngelOneClient | None" = None


def _get_fixed_plan_client() -> "AngelOneClient | None":
    global _FIXED_PLAN_CLIENT
    if _FIXED_PLAN_CLIENT is None:
        try:
            _FIXED_PLAN_CLIENT = AngelOneClient()
        except Exception as exc:
            log.warning("Fixed-plan client init failed: %s", exc)
            return None
    return _FIXED_PLAN_CLIENT


def _enrich_snapshot_with_fixed_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge fixed-trade-plan symbols' live LTPs into stockQuotes.

    The fixed plan (fixed_trade_plan.json) may contain symbols that are not in
    the WATCHLIST / Nifty cache, so they never appear in the normal Angel One
    batch quote. This resolves their tokens at runtime (searchScrip) and fetches
    LTPs (ltpData) so get_live_prices_for_plan() can show real prices instead of
    falling back to entry price.
    """
    try:
        from .trade_outcome import load_desk_live_book
    except Exception:
        return payload

    book, _source = load_desk_live_book()
    symbols: list[str] = []
    for p in (book.get("long") or []) + (book.get("short") or []):
        s = (p.get("symbol") or "").upper()
        if s:
            symbols.append(s)
    if not symbols:
        return payload

    quotes = dict(payload.get("stockQuotes") or {})
    now = time.time()
    client = _get_fixed_plan_client()
    if client is None:
        return payload

    for sym in symbols:
        cached = _FIXED_PLAN_QUOTE_CACHE.get(sym)
        if cached and (now - cached[0]) < _FIXED_PLAN_QUOTE_TTL:
            quotes[sym] = cached[1]
            continue
        try:
            quote = client.fetch_symbol_quote(sym)
            if not quote:
                continue
            ltp = float(quote.get("ltp", 0) or 0)
            if not ltp:
                continue
            inst = Instrument(
                sym,
                "NSE",
                str(quote.get("tradingsymbol") or f"{sym}-EQ"),
                str(quote.get("token", "0")),
            )
            row = _build_stock_row(inst, quote, payload.get("activePool", "Fixed Plan"))
            quotes[sym] = row
            _FIXED_PLAN_QUOTE_CACHE[sym] = (now, row)
        except Exception as exc:
            log.debug("Fixed-plan quote fetch failed for %s: %s", sym, exc)
            continue

    payload["stockQuotes"] = quotes
    return payload


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(re.sub(r"<[^>]+>", "", value).split()).strip()


def _parse_rss_datetime(date_text: str | None) -> str | None:
    if not date_text:
        return None
    formats = (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S GMT",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(date_text.strip(), fmt)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return None


def _clean_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


# -----------------------------------------------------------------------------
# RSS / Atom ingestion
# -----------------------------------------------------------------------------
# Real, structured headlines pulled from financial-news feeds. Each article is
# normalized to {source, title, link, summary, publishedAt, sentiment,
# category} and de-duplicated by normalized title across all sources.

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

_BULLISH_WORDS: dict[str, int] = {
    "beats": 30, "beat estimates": 35, "surges": 30, "surge": 28, "rallies": 28,
    "jumps": 25, "gains": 18, "upgrade": 30, "upgraded": 30, "wins order": 32,
    "wins contract": 32, "record profit": 35, "record high": 28, "approval": 25,
    "nod": 20, "raises guidance": 32, "raised guidance": 32, "outperform": 25,
    "buyback": 20, "expansion": 15, "strong demand": 22, "beats street": 32,
    "profit jumps": 30, "profit rises": 25, "revenue growth": 18, "bullish": 22,
    "rally": 24, "soars": 30, "tops estimate": 30, "inflows": 14, "recovery": 15,
}
_BEARISH_WORDS: dict[str, int] = {
    "tumbles": 30, "crashes": 35, "plunges": 32, "slides": 22, "slips": 18,
    "downgrade": 30, "downgraded": 30, "misses estimates": 32, "miss estimates": 30,
    "cancellation": 28, "cancels order": 30, "probe": 28, "fraud": 35, "raid": 30,
    "resigns": 22, "resignation": 22, "npa": 22, "slippage": 25, "governance": 15,
    "pledge": 18, "delay": 15, "weak guidance": 28, "cuts guidance": 30,
    "profit falls": 28, "loss widens": 30, "bearish": 22, "sell-off": 25,
    "selloff": 25, "scam": 32, "slumps": 28, "sinks": 28, "outflows": 14,
    "layoffs": 22, "defaults": 28, "warning": 18,
}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Earnings": ["earnings", "result", "results", "profit", "revenue", "quarter", " q1 ", " q2 ", " q3 ", " q4 ", "eps", "dividend", "guidance", "net profit", "bottomline"],
    "Regulatory": ["sebi", "rbi", "regulator", "regulatory", "supreme court", "cci", "penalty", "probe", "investigation", "ruling", "order", "ban", "nclt", "crackdown", "fine"],
    "Commodity": ["crude", "gold", "silver", "oil", "commodity", "commodities", "brent", "natural gas", "wheat", "rupee", "dollar", "currency", "bullion"],
    "Economy": ["gdp", "inflation", "fiscal", "budget", "economy", "imf", "fii", "dii", "macro", "policy", "repo rate", "monsoon", "trade deficit", "gst"],
    "Global": ["wall street", "nasdaq", "dow", "s&p", "fed ", "us fed", "global", "china", "europe", "japan", "ukraine", "tariff"],
    "Corporate": ["merger", "acquisition", "buyback", "promoter", "board", "ceo", "cfo", "management", "deal", "partnership", "launch", "order win", "contract", "joint venture", "subsidiary"],
}


def _xml_local(tag: str) -> str:
    return tag.split("}")[-1]


def _xml_child(el: "ET.Element", local: str) -> "ET.Element | None":
    for child in el:
        if _xml_local(child.tag) == local:
            return child
    return None


def _xml_text(el: "ET.Element", local: str) -> str:
    child = _xml_child(el, local)
    if child is None:
        return ""
    return _clean_text(child.text or "")


def _xml_link(el: "ET.Element") -> str:
    links = [c for c in el if _xml_local(c.tag) == "link"]
    if not links:
        return ""
    for link in links:
        if link.get("rel") in (None, "alternate"):
            href = link.get("href")
            if href:
                return href
    href = links[0].get("href")
    if href:
        return href
    return _clean_text(links[0].text or "")


def _parse_published(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            return datetime.strptime(value, fmt).astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return None


def _classify_sentiment(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    score = 0
    for word, weight in _BULLISH_WORDS.items():
        if word in text:
            score += weight
    for word, weight in _BEARISH_WORDS.items():
        if word in text:
            score -= weight
    if score >= 12:
        return "Bullish"
    if score <= -12:
        return "Bearish"
    return "Neutral"


def _classify_category(title: str, summary: str, default_category: str) -> str:
    text = (title + " " + summary).lower()
    for category, words in _CATEGORY_KEYWORDS.items():
        if any(word in text for word in words):
            return category
    return default_category or "Market"


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").lower()).strip()


def _fetch_rss_feed(name: str, url: str, default_category: str, limit: int = 5) -> list[dict[str, str]]:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"}
    response = requests.get(url, timeout=10, headers=headers)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    nodes = root.findall(".//item")
    if not nodes:
        nodes = root.findall(f".//{_ATOM_NS}entry")
    items: list[dict[str, str]] = []
    for node in nodes[:limit]:
        title = _xml_text(node, "title")
        if not title or len(title) < 10:
            continue
        link = _xml_link(node)
        summary = (
            _xml_text(node, "description")
            or _xml_text(node, "summary")
            or _xml_text(node, "content")
        )
        # Use the entry's real publisher when present (Google News Atom feeds
        # embed <source>Publisher</source>), otherwise fall back to the feed name.
        source_child = _xml_child(node, "source")
        source = _clean_text(source_child.text) if source_child is not None else ""
        source = source or name
        published = _parse_published(
            _xml_text(node, "pubDate")
            or _xml_text(node, "updated")
            or _xml_text(node, "date")
            or _xml_text(node, "published")
        )
        if not published:
            published = _ist_now().isoformat()
        items.append(
            {
                "source": source,
                "title": title[:300],
                "link": link or url,
                "summary": summary[:400],
                "publishedAt": published,
                "sentiment": _classify_sentiment(title, summary),
                "category": _classify_category(title, summary, default_category),
            }
        )
    return items


def fetch_live_news(limit: int = 40, per_feed: int = 4) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [
            executor.submit(_fetch_rss_feed, name, url, category, per_feed)
            for name, url, category in NEWS_RSS_FEEDS
        ]
        for future in as_completed(futures):
            try:
                items.extend(future.result())
            except Exception:
                continue

    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        key = _normalize_title(item.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(key=lambda item: item.get("publishedAt", ""), reverse=True)
    return deduped[:limit]


# Use the canonical _llm_config from llm_client.py instead of this local one.
# It supports both API key (project quota) and OAuth token (portal quota).


def _call_openai_deprecated(*args, **kwargs):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an elite institutional financial terminal. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    if response.status_code >= 300:
        raise RuntimeError(f"OpenAI request failed ({response.status_code}): {response.text}")
    data = response.json()
    if not data.get("choices") or not data["choices"][0].get("message"):
        raise RuntimeError("OpenAI response missing expected content")
    return data["choices"][0]["message"]["content"].strip()


def _call_gemini_deprecated(*args, **kwargs):
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini support requires google-genai. Install it in the backend venv.") from exc

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=2000,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return getattr(response, "text", None) or getattr(response, "output_text", None) or str(response)


class AngelOneClient:
    def __init__(self) -> None:
        self.api_key = _require_env("ANGEL_API_KEY")
        self.client_id = _require_env("ANGEL_CLIENT_ID")
        self.credential = _get_credential()
        self.totp_secret = _require_env("ANGEL_TOTP_SECRET")
        self._smart: SmartConnect | None = None

    def _reset_connection(self) -> None:
        self._smart = None

    def _is_auth_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(k in msg for k in (
            "unauthorized", "invalid token", "token expired", "access denied",
            "session expired", "login required", "invalid session", "ab1000",
            "ab1001", "ab1002", "ab1003", "authentication", "session invalid",
            "token is expired", "unauthorised"
        ))

    def _call_with_auth_retry(self, method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except Exception as exc:
            if self._is_auth_error(exc):
                logging.getLogger(__name__).warning("Angel One auth error, reconnecting: %s", exc)
                self._reset_connection()
                return method(*args, **kwargs)
            raise

    def connect(self) -> SmartConnect:
        if self._smart is not None:
            return self._smart
        smart = SmartConnect(api_key=self.api_key, timeout=ANGEL_API_TIMEOUT_SECONDS)
        totp = pyotp.TOTP(self.totp_secret).now()
        session = smart.generateSession(self.client_id, self.credential, totp)
        if not session.get("status"):
            raise RuntimeError(f"Angel One login failed: {session.get('message', 'Unknown login error')}")
        # generateSession already calls setAccessToken / setRefreshToken / setFeedToken
        # with the raw token (without Bearer prefix). The returned data has "Bearer "
        # prefixed, so calling the setters again would double-prefix and break auth.
        self._smart = smart
        return smart

    def fetch_quote(self, exchange: str, tradingsymbol: str, token: str) -> dict[str, Any]:
        def _fetch():
            smart = self.connect()
            response = smart.ltpData(exchange, tradingsymbol, token)
            if not response.get("status"):
                raise RuntimeError(f"{tradingsymbol}: {response.get('message', 'Quote fetch failed')}")
            return response["data"]
        try:
            return _fetch()
        except Exception as exc:
            if self._is_auth_error(exc):
                self._reset_connection()
                return _fetch()
            raise

    def fetch_symbol_quote(self, symbol: str) -> dict[str, Any] | None:
        """Resolve an arbitrary NSE symbol's token and fetch its LTP.

        Used to bring fixed-trade-plan symbols (which are not in the WATCHLIST /
        Nifty cache) into the live snapshot so the intraday monitor can show real
        prices instead of falling back to entry price.
        """
        def _try_fetch() -> dict[str, Any] | None:
            smart = self.connect()
            resolved = _resolve_nse_equity(symbol, client=self)
            if not resolved:
                return None
            token, tradingsymbol = resolved
            try:
                resp = smart.ltpData("NSE", tradingsymbol, token)
            except Exception:
                return None
            if not isinstance(resp, dict) or not resp.get("status"):
                return None
            data = resp.get("data") or {}
            if isinstance(data, dict):
                data.setdefault("token", token)
                data.setdefault("tradingsymbol", tradingsymbol)
            return data if isinstance(data, dict) else None

        try:
            return _try_fetch()
        except Exception as exc:
            if self._is_auth_error(exc):
                self._reset_connection()
                return _try_fetch()
            return None

    def fetch_candles(
        self,
        exchange: str,
        symboltoken: str,
        interval: str,
        fromdate: datetime,
        todate: datetime,
    ) -> list[list[Any]]:
        log = logging.getLogger(__name__)
        if symboltoken.startswith("DHAN:"):
            try:
                return fetch_dhan_candles(
                    symboltoken.split(":", 1)[1], interval, fromdate, todate
                )
            except Exception as exc:
                log.warning("Dhan candle request failed for %s: %s", symboltoken, exc)
                return []
        if not _angel_candle_calls_allowed():
            return []
        params = {
            "exchange": exchange,
            "symboltoken": symboltoken,
            "interval": interval,
            "fromdate": fromdate.astimezone(IST_ZONE).strftime("%Y-%m-%d %H:%M"),
            "todate": todate.astimezone(IST_ZONE).strftime("%Y-%m-%d %H:%M"),
        }
        auth_retried = False
        for attempt in range(CANDLE_RATE_LIMIT_RETRIES + 1):
            try:
                with _candle_api_slot():
                    smart = self.connect()
                    response = smart.getCandleData(params)
            except Exception as exc:
                if self._is_auth_error(exc) and not auth_retried:
                    auth_retried = True
                    self._reset_connection()
                    continue
                if _is_candle_rate_limited(exc) and attempt < CANDLE_RATE_LIMIT_RETRIES:
                    delay = min(8.0, (2 ** attempt) + (0.1 * attempt))
                    _trip_angel_candle_circuit(max(delay, ANGEL_CANDLE_CIRCUIT_SECONDS))
                    log.warning(
                        "Angel candle rate-limited (token=%s interval=%s); retry in %.1fs (%d/%d)",
                        symboltoken, interval, delay, attempt + 1, CANDLE_RATE_LIMIT_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                if _is_candle_rate_limited(exc):
                    _trip_angel_candle_circuit()
                    return []
                return []

            if not isinstance(response, dict):
                return []
            if response.get("status"):
                data = response.get("data") or []
                return data if isinstance(data, list) else []
            if _is_candle_rate_limited(response) and attempt < CANDLE_RATE_LIMIT_RETRIES:
                delay = min(8.0, (2 ** attempt) + (0.1 * attempt))
                _trip_angel_candle_circuit(max(delay, ANGEL_CANDLE_CIRCUIT_SECONDS))
                log.warning(
                    "Angel candle AB1021 (token=%s interval=%s); backoff %.1fs (%d/%d)",
                    symboltoken, interval, delay, attempt + 1, CANDLE_RATE_LIMIT_RETRIES,
                )
                time.sleep(delay)
                continue
            if _is_candle_rate_limited(response):
                _trip_angel_candle_circuit()
                return []
            return []
        return []

    def fetch_batch_quotes(self, instruments: list[Instrument]) -> dict[str, dict[str, Any]]:
        smart = self.connect()
        token_to_key: dict[str, str] = {}

        for inst in instruments:
            token_to_key[inst.token] = inst.key

        def _chunked(items: list[Instrument], size: int = 25) -> list[list[Instrument]]:
            return [items[i : i + size] for i in range(0, len(items), size)]

        fetched: dict[str, dict[str, Any]] = {}
        for chunk in _chunked(instruments, size=25):
            tokens_by_exchange: dict[str, list[str]] = {}
            for inst in chunk:
                tokens_by_exchange.setdefault(inst.exchange, []).append(inst.token)

            try:
                response = smart.getMarketData("FULL", tokens_by_exchange)
            except Exception:
                response = {"status": False}

            if response.get("status"):
                for item in response.get("data", {}).get("fetched", []):
                    token = str(item.get("symbolToken", ""))
                    key = token_to_key.get(token)
                    if key:
                        fetched[key] = item
                continue

            for inst in chunk:
                try:
                    fetched[inst.key] = self.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
                except Exception:
                    continue

        missing = [inst for inst in instruments if inst.key not in fetched]
        for inst in missing:
            try:
                fetched[inst.key] = self.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
            except Exception:
                continue

        return fetched


def _fetch_quote_chunk(
    smart: SmartConnect,
    chunk: list[Instrument],
    token_to_key: dict[str, str],
    client: AngelOneClient | None = None,
) -> dict[str, dict[str, Any]]:
    tokens_by_exchange: dict[str, list[str]] = {}
    for inst in chunk:
        tokens_by_exchange.setdefault(inst.exchange, []).append(inst.token)

    fetched: dict[str, dict[str, Any]] = {}
    try:
        response = smart.getMarketData("FULL", tokens_by_exchange)
        if response.get("status"):
            for item in response.get("data", {}).get("fetched", []):
                token = str(item.get("symbolToken", ""))
                key = token_to_key.get(token)
                if key:
                    fetched[key] = item
            return fetched
    except Exception as exc:
        if client and client._is_auth_error(exc):
            raise

    for inst in chunk:
        try:
            response = smart.ltpData(inst.exchange, inst.tradingsymbol, inst.token)
            if response.get("status"):
                fetched[inst.key] = response["data"]
        except Exception as exc:
            if client and client._is_auth_error(exc):
                raise
            continue
    return fetched


def _fetch_batch_quotes_chunked(
    self: AngelOneClient,
    instruments: list[Instrument],
) -> dict[str, dict[str, Any]]:
    def _fetch():
        smart = self.connect()
        token_to_key = {inst.token: inst.key for inst in instruments}
        chunks = [instruments[i : i + QUOTE_CHUNK_SIZE] for i in range(0, len(instruments), QUOTE_CHUNK_SIZE)]
        all_fetched: dict[str, dict[str, Any]] = {}

        for chunk in chunks:
            all_fetched.update(_fetch_quote_chunk(smart, chunk, token_to_key, self))

        return all_fetched

    try:
        return _fetch()
    except Exception as exc:
        if self._is_auth_error(exc):
            self._reset_connection()
            return _fetch()
        raise


AngelOneClient.fetch_batch_quotes = _fetch_batch_quotes_chunked


def _fetch_stock_quotes_with_coverage(
    client: AngelOneClient,
    instruments: list[Instrument],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """NSE primary, then Dhan bulk and Angel for only missing symbols."""
    by_key = {inst.key: inst for inst in instruments}

    def angel_missing(symbols: list[str]) -> dict[str, dict[str, Any]]:
        eligible = [
            by_key[symbol]
            for symbol in symbols
            if symbol in by_key and not str(by_key[symbol].token).startswith("DHAN:")
        ]
        return client.fetch_batch_quotes(eligible) if eligible else {}

    quotes, coverage = fetch_quotes_with_failover(by_key, angel_missing)
    return quotes, coverage.as_dict()


def _build_stock_row(
    inst: Instrument,
    quote: dict[str, Any],
    active_pool: str,
    intraday: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ltp = float(quote.get("ltp", 0) or 0)
    close = float(quote.get("close", 0) or 0)
    delta, state = _pct_change(ltp, close if close else None)
    return {
        "ticker": inst.key,
        "name": (inst.label or inst.tradingsymbol).replace("-EQ", "").replace("-BE", "").replace("-", " ").strip(),
        "capSize": active_pool,
        "ltp": _format_inr(ltp),
        "ltpRaw": ltp,
        "delta": delta,
        "state": state,
        "volume": quote.get("tradeVolume"),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "oi": float(quote.get("opnInterest", 0) or quote.get("oi", 0) or 0),
        "prev_oi": float(quote.get("previousOI", 0) or quote.get("prev_oi", 0) or 0),
        "intraday": intraday or {},
    }


def _parse_candle_rows(raw: list[list[Any]]) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for row in raw or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        ts, open_, high, low, close, volume = row[:6]
        candles.append(
            {
                "ts": ts,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume or 0),
            }
        )
    return candles


def _ema(values: list[float], period: int = 9) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append((value * k) + (out[-1] * (1 - k)))
    return out


def _atr_percent(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: list[float] = []
    prev_close = candles[0]["close"]
    for candle in candles[1:]:
        tr = max(
            candle["high"] - candle["low"],
            abs(candle["high"] - prev_close),
            abs(candle["low"] - prev_close),
        )
        trs.append(tr)
        prev_close = candle["close"]
    if len(trs) < period:
        return 0.0
    atr = sum(trs[-period:]) / period
    close = candles[-1]["close"] or 1.0
    return (atr / close) * 100


def _vwap(candles: list[dict[str, Any]]) -> float:
    total_pv = 0.0
    total_vol = 0.0
    for candle in candles:
        vol = float(candle["volume"] or 0)
        typical = (candle["high"] + candle["low"] + candle["close"]) / 3.0
        total_pv += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return 0.0
    return total_pv / total_vol


def _wick_noise_ratio(candles: list[dict[str, Any]]) -> float:
    total_range = 0.0
    total_wick = 0.0
    for candle in candles:
        candle_range = max(candle["high"] - candle["low"], 0.0)
        if candle_range <= 0:
            continue
        body_high = max(candle["open"], candle["close"])
        body_low = min(candle["open"], candle["close"])
        wick = (candle["high"] - body_high) + (body_low - candle["low"])
        total_range += candle_range
        total_wick += max(wick, 0.0)
    if total_range <= 0:
        return 1.0
    return total_wick / total_range


def _ema_angle_deg(ema_values: list[float]) -> float:
    if len(ema_values) < 6:
        return 0.0
    base = ema_values[-6] or 1.0
    latest = ema_values[-1] or base
    slope_pct = ((latest - base) / base) * 100.0
    return math.degrees(math.atan(slope_pct))


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI. Returns 50.0 (neutral) when there is insufficient history."""
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


# =============================================================================
# OI CLASSIFICATION - Real OI Setup Logic
# =============================================================================

def classify_oi_setup(
    ltp: float,
    prev_close: float,
    current_oi: float,
    prev_oi: float,
) -> str:
    """
    Classify Open Interest setup based on price and OI movement.

    LONG_BUILDUP:   Price UP + OI UP   (Bullish — new longs being added)
    SHORT_COVERING: Price UP + OI DOWN (Bears closing positions)
    SHORT_BUILDUP:  Price DOWN + OI UP (Bearish — new shorts being added)
    LONG_UNWINDING: Price DOWN + OI DOWN (Bulls closing positions)
    NEUTRAL:        No clear signal
    """
    price_up = ltp > prev_close
    if price_up and current_oi > prev_oi:
        return "LONG_BUILDUP"
    if price_up and current_oi < prev_oi:
        return "SHORT_COVERING"
    if not price_up and current_oi > prev_oi:
        return "SHORT_BUILDUP"
    if not price_up and current_oi < prev_oi:
        return "LONG_UNWINDING"
    return "NEUTRAL"


def _intraday_metrics_from_quote(ltp: float, now: datetime, quote: dict[str, Any]) -> dict[str, Any]:
    """Compute best-effort intraday metrics from quote data when candle API fails.
    
    Uses open/high/low/close/volume from the quote snapshot (which is always
    available from Angel One's batch quote API) to approximate the metrics.
    """
    open_ = float(quote.get("open", 0) or 0)
    high = float(quote.get("high", 0) or 0)
    low = float(quote.get("low", 0) or 0)
    close = float(quote.get("close", 0) or 0)
    volume = float(quote.get("tradeVolume", 0) or 0)
    
    # Estimate ATR% from today's range vs close (single-bar proxy for daily ATR)
    daily_range_pct = 0.0
    if close > 0 and high > 0 and low > 0:
        daily_range_pct = ((high - low) / close) * 100
    
    # VWAP approximation using OHL+C/3 typical price (single-bar estimate)
    typical = (high + low + ltp) / 3.0 if high and low and ltp else (open_ + high + low + close) / 4.0
    vwap = typical if typical > 0 else ltp
    
    # EMA9 approximation: use the close price as a different anchor from VWAP.
    # In real intraday data, EMA9 lags VWAP; using close gives a slightly different
    # value that allows price_above_ema9 to be meaningful when ltp > close.
    ema9 = close if close > 0 else ltp
    
    # ORB from quote data (uses today's open as ORB reference)
    orb_high = max(open_, ltp) if open_ else high
    orb_low = min(open_, ltp) if open_ else low
    
    # Today's volume from quote (tradeVolume is cumulative for the day)
    today_volume = volume
    avg_daily_volume_20 = volume  # estimate: use today's volume as proxy (better than 0)
    volume_multiplier = 1.0  # neutral
    
    # Wick noise ratio from single candle (open vs close vs high vs low)
    wick_noise_ratio = 1.0
    if high > low and high > 0:
        body_high = max(open_, close) if open_ and close else open_ or close or ltp
        body_low = min(open_, close) if open_ and close else open_ or close or ltp
        total_range = high - low
        wick = (high - body_high) + (body_low - low)
        if total_range > 0:
            wick_noise_ratio = min(wick / total_range, 1.0)
    
    # EMA angle: cannot compute without history, default neutral
    ema_angle_deg = 0.0
    
    # ORB velocity
    orb_velocity_pct = ((ltp - orb_high) / orb_high) * 100 if orb_high and ltp >= orb_high else 0.0
    
    # Turnover
    turnover_cr = (ltp * today_volume) / 10_000_000 if ltp and today_volume else 0.0
    
    price_above_vwap = bool(vwap and ltp > vwap)
    price_above_ema9 = bool(ema9 and ltp > ema9)
    
    # Hard filter reasons — tightened thresholds for quote-based fallback.
    # volume_multiplier and ema_angle are included for transparency even though
    # they default to placeholder values when candle data is unavailable.
    hard_filter_reasons: list[str] = []
    if daily_range_pct <= 1.5:
        hard_filter_reasons.append("ATR under 1.5%")
    if volume_multiplier < MIN_VOLUME_MULTIPLIER:
        hard_filter_reasons.append(f"volume under {MIN_VOLUME_MULTIPLIER:g}x expected")
    if wick_noise_ratio > 0.70:
        hard_filter_reasons.append("wick noise too high")
    if not price_above_vwap:
        hard_filter_reasons.append("below VWAP")
    if not price_above_ema9:
        hard_filter_reasons.append("below EMA9")
    if ema_angle_deg <= MIN_EMA_ANGLE_DEG:
        hard_filter_reasons.append(f"EMA angle below {MIN_EMA_ANGLE_DEG:g} degrees")
    if turnover_cr < 50.0:
        hard_filter_reasons.append("turnover under 50 Cr")
    day_move_pct = day_change_pct_from_prices(ltp, close)
    if day_move_pct is not None and day_move_pct > MAX_DAY_MOVE_PCT:
        hard_filter_reasons.append(f"day move over {MAX_DAY_MOVE_PCT:g}%")
    
    passes_hard_filters = len(hard_filter_reasons) == 0
    trigger_point = "VWAP Bounce" if price_above_vwap else "15-min ORB" if ltp >= orb_high else "Flag Breakout"

    # Compute real alpha-component values from quote data instead of hardcoding zeros
    # OI classification from quote data
    current_oi = float(quote.get("oi", 0) or quote.get("opnInterest", 0) or 0)
    prev_oi_val = float(quote.get("prev_oi", 0) or quote.get("previousOI", 0) or 0)
    prev_close = float(quote.get("close", 0) or 0)
    if current_oi > 0 or prev_oi_val > 0:
        oi_setup = classify_oi_setup(ltp, prev_close if prev_close > 0 else ltp, current_oi, prev_oi_val)
    else:
        oi_setup = "NEUTRAL"

    # relative_volume: estimate from turnover using Nifty 100 institutional thresholds.
    # With only quote data (no 20d avg), we use turnover_cr as a proxy for volume activity.
    # 50 Cr turnover ≈ average institutional activity; 500+ Cr ≈ 3-5x average.
    if turnover_cr > 0:
        relative_volume = min(max(turnover_cr / 150.0, 0.5), 5.0)
    else:
        relative_volume = 1.0

    # liquidity_score: based on turnover (capped at 20)
    liquidity_score = min(turnover_cr / 2.5, 20.0)

    # breakout_quality: based on candle body ratio and VWAP distance
    body_ratio = (
        abs(close - open_) / max(high - low, 0.001)
    ) if high > low and open_ > 0 and close > 0 else 0.0
    vwap_dist_pct = ((ltp - vwap) / vwap * 100) if vwap > 0 else 0.0
    breakout_quality = min(
        (body_ratio * 10 + vwap_dist_pct * 2) if ltp > vwap else 0.0,
        20.0,
    )

    # sector_strength: based on price position within today's range
    day_range = high - low if high > low else 0.001
    price_position = (ltp - low) / day_range if day_range > 0 else 0.5
    sector_strength = min(price_position * 20, 20.0)

    return {
        "data_source": "quote",
        "atr_pct": round(daily_range_pct, 2),
        "volume_multiplier": round(volume_multiplier, 2),
        "today_volume": round(today_volume, 0),
        "avg_daily_volume_20": round(avg_daily_volume_20, 0),
        "vwap": round(vwap, 2),
        "ema9": round(ema9, 2),
        "ema_angle_deg": round(ema_angle_deg, 2),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_velocity_pct": round(orb_velocity_pct, 2),
        "wick_noise_ratio": round(wick_noise_ratio, 3),
        "turnover_cr": round(turnover_cr, 2),
        "price_above_vwap": price_above_vwap,
        "price_above_ema9": price_above_ema9,
        "trigger_point": trigger_point,
        "rsi": 50.0,
        "oi_setup": oi_setup,
        "oi": current_oi,
        "prev_oi": prev_oi_val,
        "relative_volume": relative_volume,
        "liquidity_score": liquidity_score,
        "breakout_quality": breakout_quality,
        "sector_strength": sector_strength,
        "day_change_pct": None if day_move_pct is None else round(day_move_pct, 2),
        "volume_pace_adjusted": False,
        "passes_hard_filters": passes_hard_filters,
        "hard_filter_reasons": hard_filter_reasons + ["metrics estimated from quote (candle API unavailable)"],
    }


def _empty_intraday_metrics(reason: str) -> dict[str, Any]:
    return {
        "data_source": "none",
        "atr_pct": 0.0,
        "volume_multiplier": 0.0,
        "today_volume": 0.0,
        "avg_daily_volume_20": 0.0,
        "vwap": 0.0,
        "ema9": 0.0,
        "ema_angle_deg": 0.0,
        "orb_high": 0.0,
        "orb_low": 0.0,
        "orb_velocity_pct": 0.0,
        "wick_noise_ratio": 1.0,
        "turnover_cr": 0.0,
        "price_above_vwap": False,
        "price_above_ema9": False,
        "trigger_point": "VWAP Bounce",
        "rsi": 50.0,
        "oi_setup": "NEUTRAL",
        "relative_volume": 0.0,
        "liquidity_score": 0.0,
        "breakout_quality": 0.0,
        "sector_strength": 0.0,
        "passes_hard_filters": False,
        "hard_filter_reasons": [reason],
    }


def _intraday_metrics_from_daily(
    daily_candles: list[dict[str, Any]],
    ltp: float,
    now: datetime,
    quote_fallback: dict[str, Any] | None,
) -> dict[str, Any]:
    """ATR / RSI / turnover from daily candles + quote volume when 5m bars are missing."""
    atr_pct = _atr_percent(daily_candles)
    daily_volumes = [row["volume"] for row in daily_candles[-20:]]
    avg_daily_volume_20 = (sum(daily_volumes) / len(daily_volumes)) if daily_volumes else 0.0
    today_volume = float((quote_fallback or {}).get("tradeVolume") or 0)
    if today_volume <= 0:
        today_volume = float(daily_candles[-1].get("volume") or 0)
    volume_multiplier = pace_volume_multiplier(today_volume, avg_daily_volume_20, now)
    turnover_cr = (ltp * today_volume) / 10_000_000 if ltp and today_volume else 0.0
    rsi_val = _rsi([row["close"] for row in daily_candles], period=14)
    prev_close = float((quote_fallback or {}).get("close") or 0)
    if prev_close <= 0 and len(daily_candles) >= 2:
        prev_close = float(daily_candles[-2].get("close") or 0)
    day_move_pct = day_change_pct_from_prices(ltp, prev_close)
    return {
        "data_source": "daily_candles",
        "atr_pct": round(atr_pct, 2),
        "volume_multiplier": round(volume_multiplier, 2),
        "today_volume": round(today_volume, 0),
        "avg_daily_volume_20": round(avg_daily_volume_20, 0),
        "vwap": 0.0,
        "ema9": 0.0,
        "ema_angle_deg": 0.0,
        "orb_high": 0.0,
        "orb_low": 0.0,
        "orb_velocity_pct": 0.0,
        "wick_noise_ratio": 1.0,
        "turnover_cr": round(turnover_cr, 2),
        "price_above_vwap": False,
        "price_above_ema9": False,
        "trigger_point": None,
        "rsi": rsi_val,
        "passes_hard_filters": False,
        "hard_filter_reasons": ["5m bars unavailable; ATR/RSI/turnover from daily candles + quote volume"],
        "day_change_pct": None if day_move_pct is None else round(day_move_pct, 2),
        "volume_pace_adjusted": False,
    }


def _intraday_metrics(
    client: AngelOneClient,
    inst: Instrument,
    ltp: float,
    now: datetime,
    quote_fallback: dict[str, Any] | None = None,
    *,
    force_angel_fallback: bool = False,
) -> dict[str, Any]:
    try:
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        daily_from = (now - timedelta(days=45)).replace(hour=9, minute=15, second=0, microsecond=0)
        daily_to = now

        dhan_id = load_dhan_security_ids().get(inst.key) if dhan_configured() else None
        tried_dhan = bool(dhan_id)
        if dhan_id:
            # Dhan is the primary chart provider: it avoids Angel's AB1021 burst
            # limits while still letting Angel fill names with no Dhan security id.
            daily_raw = fetch_dhan_candles(dhan_id, "ONE_DAY", daily_from, daily_to)
            intraday_raw = fetch_dhan_candles(dhan_id, "FIVE_MINUTE", market_open, now)
        else:
            daily_raw = []
            intraday_raw = []
        # Public NSE charting fills daily (and T-1 5m) without Angel. Today's
        # 5m is usually empty while the session is open.
        if not daily_raw:
            daily_raw = fetch_nse_candles(inst.key, inst.token, "ONE_DAY", daily_from, daily_to)
        if not intraday_raw:
            intraday_raw = fetch_nse_candles(
                inst.key, inst.token, "FIVE_MINUTE", market_open, now
            )
        # Batch hunt skips Angel when a Dhan id exists (AB1021). Drawer single-name
        # fetches may force Angel so ATR/turnover are not left blank.
        allow_angel = force_angel_fallback or not tried_dhan
        if not daily_raw and allow_angel and _angel_candle_calls_allowed():
            daily_raw = client.fetch_candles(inst.exchange, inst.token, "ONE_DAY", daily_from, daily_to)
        if not intraday_raw and allow_angel and _angel_candle_calls_allowed():
            intraday_raw = client.fetch_candles(inst.exchange, inst.token, "FIVE_MINUTE", market_open, now)

        daily_candles = _parse_candle_rows(daily_raw)
        intraday_candles = _parse_candle_rows(intraday_raw)
    except Exception:
        daily_candles = []
        intraday_candles = []

    if not daily_candles and not intraday_candles:
        if quote_fallback is not None and os.getenv("ALLOW_QUOTE_METRICS_FALLBACK", "0") == "1":
            return _intraday_metrics_from_quote(ltp, now, quote_fallback)
        return _empty_intraday_metrics("insufficient candle data")
    if not intraday_candles and daily_candles:
        return _intraday_metrics_from_daily(daily_candles, ltp, now, quote_fallback)
    if not daily_candles:
        if quote_fallback is not None and os.getenv("ALLOW_QUOTE_METRICS_FALLBACK", "0") == "1":
            return _intraday_metrics_from_quote(ltp, now, quote_fallback)
        return _empty_intraday_metrics("insufficient candle data")

    daily_close = daily_candles[-1]["close"] or ltp or 1.0
    daily_volumes = [row["volume"] for row in daily_candles[-20:]]
    avg_daily_volume_20 = (sum(daily_volumes) / len(daily_volumes)) if daily_volumes else 0.0
    atr_pct = _atr_percent(daily_candles)

    today_volume = sum(row["volume"] for row in intraday_candles)
    volume_multiplier = pace_volume_multiplier(today_volume, avg_daily_volume_20, now)

    vwap = _vwap(intraday_candles)
    closes = [row["close"] for row in intraday_candles]
    ema9_values = _ema(closes, period=9)
    ema9 = ema9_values[-1] if ema9_values else 0.0
    ema_angle_deg = _ema_angle_deg(ema9_values)

    orb_window = intraday_candles[:3] if len(intraday_candles) >= 3 else intraday_candles
    orb_high = max((row["high"] for row in orb_window), default=0.0)
    orb_low = min((row["low"] for row in orb_window), default=0.0)
    orb_velocity_pct = ((ltp - orb_high) / orb_high) * 100 if orb_high and ltp >= orb_high else 0.0

    wick_noise_ratio = _wick_noise_ratio(intraday_candles)
    turnover_cr = (ltp * today_volume) / 10_000_000 if ltp and today_volume else 0.0

    price_above_vwap = bool(vwap and ltp > vwap)
    price_above_ema9 = bool(ema9 and ltp > ema9)

    # RSI(14) from daily closes
    daily_closes = [row["close"] for row in daily_candles]
    rsi_val = _rsi(daily_closes, period=14)

    # OI classification from quote_fallback row (populated by _build_stock_row)
    current_oi = float((quote_fallback or {}).get("oi", 0) or 0)
    prev_oi_val = float((quote_fallback or {}).get("prev_oi", 0) or 0)
    prev_close = daily_candles[-2]["close"] if len(daily_candles) >= 2 else ltp
    if current_oi > 0 or prev_oi_val > 0:
        oi_setup = classify_oi_setup(ltp, prev_close, current_oi, prev_oi_val)
    else:
        oi_setup = "NEUTRAL"

    # Alpha score components (non-filter metrics — separate from hard filter variables)
    relative_volume = volume_multiplier
    liquidity_score = min(turnover_cr / 2.5, 20.0)
    last_candle = intraday_candles[-1] if intraday_candles else {}
    body_ratio = (
        abs(last_candle.get("close", 0) - last_candle.get("open", 0))
        / max(last_candle.get("high", 0) - last_candle.get("low", 0), 0.001)
    ) if last_candle else 0.0
    vwap_dist_pct = ((ltp - vwap) / vwap * 100) if vwap > 0 else 0.0
    breakout_quality = min(
        (body_ratio * 10 + vwap_dist_pct * 2) if ltp > vwap else 0.0,
        20.0,
    )
    highs_5 = [row["high"] for row in daily_candles[-5:]]
    lows_5 = [row["low"] for row in daily_candles[-5:]]
    five_day_range = max(highs_5) - min(lows_5) if highs_5 and lows_5 else 0.0
    price_position = ((ltp - min(lows_5)) / five_day_range) if five_day_range > 0 else 0.5
    sector_strength = min(price_position * 20, 20.0)

    hard_filter_reasons: list[str] = []
    if atr_pct <= 3.0:
        hard_filter_reasons.append("ATR under 3.0%")
    if volume_multiplier < MIN_VOLUME_MULTIPLIER:
        hard_filter_reasons.append(f"volume under {MIN_VOLUME_MULTIPLIER:g}x expected")
    if wick_noise_ratio > MAX_WICK_NOISE_RATIO:
        hard_filter_reasons.append("wick noise too high")
    if not price_above_vwap:
        hard_filter_reasons.append("below VWAP")
    if not price_above_ema9:
        hard_filter_reasons.append("below EMA9")
    if ema_angle_deg <= MIN_EMA_ANGLE_DEG:
        hard_filter_reasons.append(f"EMA angle below {MIN_EMA_ANGLE_DEG:g} degrees")
    if turnover_cr < 50.0:
        hard_filter_reasons.append("turnover under 50 Cr")
    prev_close = float((quote_fallback or {}).get("close") or 0)
    if prev_close <= 0 and len(daily_candles) >= 2:
        prev_close = float(daily_candles[-2].get("close") or 0)
    day_move_pct = day_change_pct_from_prices(ltp, prev_close)
    if day_move_pct is not None and day_move_pct > MAX_DAY_MOVE_PCT:
        hard_filter_reasons.append(f"day move over {MAX_DAY_MOVE_PCT:g}%")

    passes_hard_filters = len(hard_filter_reasons) == 0
    trigger_point = "VWAP Bounce" if price_above_vwap else "15-min ORB" if ltp >= orb_high else "Flag Breakout"

    metrics = {
        "data_source": "candles",
        "atr_pct": round(atr_pct, 2),
        "volume_multiplier": round(volume_multiplier, 2),
        "today_volume": round(today_volume, 0),
        "avg_daily_volume_20": round(avg_daily_volume_20, 0),
        "vwap": round(vwap, 2),
        "ema9": round(ema9, 2),
        "ema_angle_deg": round(ema_angle_deg, 2),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_velocity_pct": round(orb_velocity_pct, 2),
        "wick_noise_ratio": round(wick_noise_ratio, 3),
        "turnover_cr": round(turnover_cr, 2),
        "price_above_vwap": price_above_vwap,
        "price_above_ema9": price_above_ema9,
        "trigger_point": trigger_point,
        "rsi": rsi_val,
        "oi_setup": oi_setup,
        "oi": current_oi,
        "prev_oi": prev_oi_val,
        "relative_volume": relative_volume,
        "liquidity_score": liquidity_score,
        "breakout_quality": breakout_quality,
        "sector_strength": sector_strength,
        "day_change_pct": None if day_move_pct is None else round(day_move_pct, 2),
        "volume_pace_adjusted": True,
        "passes_hard_filters": passes_hard_filters,
        "hard_filter_reasons": hard_filter_reasons,
    }
    return attach_pivot_metrics(metrics, ltp, daily_candles)


def _fetch_intraday_chunk(
    client: AngelOneClient,
    rows: list[dict[str, Any]],
    stock_universe_by_key: dict[str, Instrument],
    now: datetime,
    *,
    force_angel_fallback: bool = False,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for row in rows:
        inst = stock_universe_by_key.get(str(row["ticker"]))
        if not inst:
            continue
        ltp = float(row.get("ltpRaw", 0) or 0)
        # Build quote_fallback from the row data (populated from batch quote API)
        quote_fallback = {
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "tradeVolume": row.get("volume"),
            "ltp": ltp,
            "oi": row.get("oi"),
            "prev_oi": row.get("prev_oi"),
            "opnInterest": row.get("oi"),
            "previousOI": row.get("prev_oi"),
        }
        try:
            metrics = _intraday_metrics(
                client, inst, ltp, now, quote_fallback=quote_fallback, force_angel_fallback=force_angel_fallback,
            )
        except Exception:
            import traceback as _traceback
            logging.getLogger(__name__).error(
                "fetch error for %s: %s", str(row.get("ticker", "?")), _traceback.format_exc()
            )
            metrics = _empty_intraday_metrics("fetch error")
        results[str(row["ticker"])] = metrics
    return results


def _fetch_all_intraday_chunked(
    client: AngelOneClient,
    candidate_rows: list[dict[str, Any]],
    stock_universe_by_key: dict[str, Instrument],
    now: datetime,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, dict[str, Any]]:
    chunks = [
        candidate_rows[i : i + INTRADAY_CHUNK_SIZE]
        for i in range(0, len(candidate_rows), INTRADAY_CHUNK_SIZE)
    ]
    if not chunks:
        return {}

    all_metrics: dict[str, dict[str, Any]] = {}
    workers = min(INTRADAY_FETCH_WORKERS, max(1, len(chunks)))
    total_chunks = len(chunks)
    completed_chunks = 0

    def fetch_chunk(chunk: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        # Thread-local Angel clients avoid sharing SmartConnect state across workers.
        chunk_client = _get_thread_angel_client() if workers > 1 else client
        return _fetch_intraday_chunk(chunk_client, chunk, stock_universe_by_key, now)

    def report_chunk_progress() -> None:
        nonlocal completed_chunks
        completed_chunks += 1
        if on_progress:
            on_progress(f"Fetching intraday candles ({completed_chunks}/{total_chunks})...")

    if workers <= 1:
        for chunk in chunks:
            all_metrics.update(fetch_chunk(chunk))
            report_chunk_progress()
        return all_metrics

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            all_metrics.update(future.result())
            report_chunk_progress()
    return all_metrics


def _heuristic_rank(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in stocks:
        ltp = float(row.get("ltpRaw") or 0)
        close = float(row.get("close") or 0)
        pct = abs(((ltp - close) / close) * 100) if close else 0.0
        volume = float(row.get("volume") or 0)
        intraday = row.get("intraday") or {}
        score = round(
            abs(pct) * 2.0
            + (0.0 if volume <= 0 else (len(str(int(volume))) - 1))
            + float(intraday.get("atr_pct") or 0.0)
            + float(intraday.get("volume_multiplier") or 0.0) * 2.0,
            2,
        )
        ranked.append({**row, "score": score})
    ranked.sort(key=lambda item: item.get("score", 0), reverse=True)
    return ranked[:_TI_TOP_SELECTION_COUNT]


# =============================================================================
# ALPHA SCORE — Non-filter metrics (Stage 1 Quant Engine output)
# =============================================================================

def _calculate_alpha_score(metrics: dict[str, Any]) -> float:
    """
    Alpha Score from non-filter metrics.
    Prevents circular logic by keeping filter variables (ATR, turnover, RSI,
    vol_mult) completely separate from the scoring components.

    Components (max 100 pts):
      relative_volume   x 15  -> capped at 40
      liquidity_score         -> capped at 20
      breakout_quality        -> capped at 20
      sector_strength         -> capped at 20
    """
    score = 0.0
    score += min(metrics.get("relative_volume", 0.0) * 15, 40.0)
    score += min(metrics.get("liquidity_score", 0.0), 20.0)
    score += min(metrics.get("breakout_quality", 0.0), 20.0)
    score += min(metrics.get("sector_strength", 0.0), 20.0)
    score += min(float(metrics.get("bulk_deal_boost") or 0.0), 10.0)
    return round(score, 2)


def _compute_deterministic_pipeline(all_stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Stage 1: Deterministic Quant Engine.

    Applies hard filters 100% mathematically (no LLM) then ranks survivors
    by Alpha Score.  Hard filter variables and Alpha Score variables are kept
    strictly separate to avoid circular scoring logic.

    Hard filter gates:
      ATR > 1.5%  |  turnover > 50 Cr  |  LTP > VWAP
      OI bullish, or cash NEUTRAL with no OI series
      vol_mult >= 1.0 expected-by-now  |  RSI > 55  |  spread < 0.50
      wick <= MAX_WICK_NOISE_RATIO  |  day move <= 6%

    Alpha score uses: relative_volume, liquidity_score,
                      breakout_quality, sector_strength
    """
    ranked_universe: list[dict[str, Any]] = []

    for stock in all_stocks:
        metrics = stock.get("intraday", {})
        ltp = float(stock.get("ltpRaw", 0.0) or 0.0)

        # Hard filter variables (never reused in Alpha Score)
        atr        = metrics.get("atr_pct", 0.0)
        turnover   = metrics.get("turnover_cr", 0.0)
        vwap_val   = metrics.get("vwap", 0.0)
        oi_setup   = metrics.get("oi_setup", "UNKNOWN")
        vol_mult   = metrics.get("volume_multiplier", 1.0)
        rsi_val    = metrics.get("rsi", 50.0)
        spread     = metrics.get("spread_pct", 0.0)
        wick_noise = metrics.get("wick_noise_ratio", 0.0)
        day_move   = day_change_pct_from_row(stock)
        if day_move is None:
            day_move = day_change_pct_from_prices(ltp, stock.get("close"))

        passes = all([
            atr > 1.5,
            turnover >= MIN_TURNOVER_CR,
            ltp > vwap_val,
            oi_setup_allows_buy(
                str(oi_setup or ""),
                oi=float(metrics.get("oi") or stock.get("oi") or 0),
                prev_oi=float(metrics.get("prev_oi") or stock.get("prev_oi") or 0),
            ),
            vol_mult >= MIN_VOLUME_MULTIPLIER,
            rsi_val >= MIN_RSI_PIVOT,
            spread < 0.50,
            wick_noise <= MAX_WICK_NOISE_RATIO,
            metrics.get("price_above_ema9", False),
            metrics.get("pivot_r1_breakout", False),
            stock.get("passes_quality_filters", False),
            day_move is None or day_move <= MAX_DAY_MOVE_PCT,
        ])

        # Always compute alpha_score so every stock shows its quantitative signal strength
        alpha_score = _calculate_alpha_score(metrics)
        stock["passes_hard_filters"] = passes
        stock["alpha_score"] = alpha_score
        # Direction is an explicit deterministic output, never inferred later
        # from alpha score, volume rank, ledger membership, or risk approval.
        stock["deterministicSide"] = "BUY" if passes else None
        stock["deterministicEligibility"] = {
            "side": stock["deterministicSide"],
            "passesHardFilters": passes,
            "passesQualityFilters": stock.get("passes_quality_filters") is True,
            "priceAboveVwap": metrics.get("price_above_vwap") is True,
            "priceAboveEma9": metrics.get("price_above_ema9") is True,
            "rsiPass": rsi_val >= MIN_RSI_PIVOT,
            "breakoutPass": (
                metrics.get("pivot_r1_breakout") is True
                and metrics.get("rsi_pivot_break") is True
            ),
            "oiSetup": oi_setup,
        }

        if passes:
            ranked_universe.append(stock)

    # Deterministic sort: Alpha Score desc, ticker asc (stable tie-break)
    ranked_universe.sort(key=lambda x: (-x["alpha_score"], x["ticker"]))

    # Pad to TOP_SELECTION_COUNT with highest-volume non-qualifiers when too few pass hard filters
    if len(ranked_universe) < _TI_TOP_SELECTION_COUNT:
        non_qualifiers = [s for s in all_stocks if not s.get("passes_hard_filters", False)]
        non_qualifiers.sort(key=lambda x: -(x.get("volume") or 0))
        for stock in non_qualifiers:
            if len(ranked_universe) >= _TI_TOP_SELECTION_COUNT:
                break
            stock.setdefault("alpha_score", 0.0)
            ranked_universe.append(stock)

    return ranked_universe[:_TI_TOP_SELECTION_COUNT]


# =============================================================================
# LLM SAFETY AUDITOR — Stage 2 (risk-only, never a stock ranker)
# =============================================================================

def _execute_llm_risk_audit(
    ranked_stocks: list[dict[str, Any]],
    news_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Stage 2: LLM Safety Audit.

    Audits ONLY the top LLM_DISPLAY_COUNT ranked candidates. Remaining display
    rows keep quant scores but receive HOLD_FOR_DATA, never synthetic approval.
    """
    if not ranked_stocks:
        return []

    audit_targets = ranked_stocks[:LLM_DISPLAY_COUNT]
    audited_by_ticker = {row["ticker"]: dict(row) for row in audit_targets}

    config = _llm_config_canonical()
    provider, api_key, api_url, model, oauth_token_path = config or (None, None, None, None, None)

    if not provider or not api_key or not _llm_quota_available():
        for stock in audit_targets:
            stock["risk_flags"] = ["LLM unavailable -- news risk not audited"]
            stock["riskAuditVerdict"] = "HOLD_FOR_DATA"
            stock["verdict"] = "HOLD_FOR_DATA"
            stock["deskIcSummary"] = {
                "deskDecision": "HOLD_FOR_DATA",
                "conviction": None,
                "oneLiner": "Risk audit unavailable; fail-closed hold.",
                "source": "risk_audit",
            }
            audited_by_ticker[stock["ticker"]] = stock
        return [
            audited_by_ticker.get(
                row["ticker"],
                {
                    **row,
                    "risk_flags": ["Not in top LLM audit set"],
                    "riskAuditVerdict": "HOLD_FOR_DATA",
                    "verdict": "HOLD_FOR_DATA",
                },
            )
            for row in ranked_stocks
        ]
    news_context = "\n".join([
        f"Source: {n.get('source','')} | Title: {n.get('title','')} | "
        f"Summary: {n.get('summary','')} | Link: {n.get('link','')}"
        for n in news_items[:15]
    ])

    # ONLY ticker + alpha_score -- NO technical data sent to LLM
    ticker_context = [
        {"ticker": s["ticker"], "alpha_score": s.get("alpha_score", 0.0)}
        for s in audit_targets
    ]
    ticker_json = json.dumps(ticker_context, indent=2)

    prompt = (
        f"Tickers to audit (top {LLM_DISPLAY_COUNT} BUY candidates):\n{ticker_json}\n\n"
        f"News/Event context:\n{news_context}\n\n"
        "Return a valid JSON object matching this structure exactly:\n"
        "{\"audits\": {\"TICKER_SYMBOL\": {\"risk_flags\": [\"Reason text (Source: name, Timestamp: iso)\"], \"verdict\": \"APPROVE or REJECT\", \"deskDecision\": \"APPROVE or REJECT\", \"deskIcNote\": \"one terse desk sentence\"}}}"
    )

    # Retry logic: try full timeout first (up to 5 mins), then a quick retry
    audit_timeouts = [LLM_CALL_TIMEOUT_SECONDS, min(60, LLM_CALL_TIMEOUT_SECONDS)]
    last_exc = None

    for attempt, timeout in enumerate(audit_timeouts):
        try:
            if provider == "gemini":
                from .llm_client import _call_gemini as _llm_gemini
                res_text = _llm_gemini(
                    prompt=prompt,
                    api_key=api_key,
                    model=model,
                    system_instruction=SYSTEM_PROMPT,
                    timeout=timeout,
                    oauth_token_path=oauth_token_path,
                )
            elif provider == "openai":
                res_text = _llm_openai_chat(
                    f"{SYSTEM_PROMPT.strip()}\n\n{prompt}",
                    api_key,
                    api_url,
                    model,
                    timeout,
                )
            else:
                raise RuntimeError(f"Unsupported LLM provider for audit: {provider}")

            # Strip markdown code fences if present
            _clean_text = res_text.strip()
            if _clean_text.startswith("```"):
                _clean_text = _clean_text.lstrip("`")
                if _clean_text.lower().startswith("json"):
                    _clean_text = _clean_text[4:].lstrip("\n")
                if "```" in _clean_text:
                    _clean_text = _clean_text[:_clean_text.index("```")]
                _clean_text = _clean_text.strip()

            from .ai_ticker_news import _parse_json_response
            parsed = _parse_json_response(_clean_text, ["audits"])
            audits = parsed.get("audits", {})
            if isinstance(audits, str):
                try:
                    audits = json.loads(audits)
                    if not isinstance(audits, dict):
                        audits = {}
                except (json.JSONDecodeError, TypeError):
                    audits = {}
            if not isinstance(audits, dict):
                audits = {}

            for stock in audit_targets:
                ticker = stock["ticker"]
                audit = audits.get(ticker, {"risk_flags": ["Audit result missing"], "verdict": "HOLD_FOR_DATA"})
                stock["risk_flags"] = audit.get("risk_flags", []) or ["None"]
                audit_verdict = str(audit.get("verdict") or "HOLD_FOR_DATA").upper().strip()
                if audit_verdict not in ("APPROVE", "REJECT", "HOLD_FOR_DATA"):
                    audit_verdict = "HOLD_FOR_DATA"
                stock["riskAuditVerdict"] = audit_verdict
                stock["verdict"] = audit_verdict
                desk_decision = str(audit.get("deskDecision") or audit_verdict).upper()
                if desk_decision not in ("APPROVE", "REJECT", "HOLD_FOR_DATA"):
                    desk_decision = audit_verdict
                stock["deskIcSummary"] = {
                    "deskDecision": desk_decision,
                    "conviction": None,
                    "oneLiner": str(audit.get("deskIcNote") or "")[:280] or None,
                    "source": "risk_audit",
                }
                audited_by_ticker[ticker] = stock
            break

        except Exception as exc:
            last_exc = exc
            err = str(exc)
            if "429" in err:
                _record_quota_error(err)
            logging.getLogger(__name__).warning(
                "LLM audit attempt %d/%d failed (timeout=%ds): %s",
                attempt + 1, len(audit_timeouts), timeout, exc,
            )
    else:
        is_timeout = "timeout" in str(last_exc).lower() or "timed out" in str(last_exc).lower()
        flag_msg = (
            f"LLM audit timed out after {sum(audit_timeouts)}s -- news risk not audited"
            if is_timeout
            else f"LLM Audit Error ({last_exc}) -- news risk not audited"
        )
        for stock in audit_targets:
            stock["risk_flags"] = [flag_msg]
            stock["riskAuditVerdict"] = "HOLD_FOR_DATA"
            stock["verdict"] = "HOLD_FOR_DATA"
            stock["deskIcSummary"] = {
                "deskDecision": "HOLD_FOR_DATA",
                "conviction": None,
                "oneLiner": flag_msg[:280],
                "source": "risk_audit",
            }
            audited_by_ticker[stock["ticker"]] = stock

    merged: list[dict[str, Any]] = []
    for row in ranked_stocks:
        ticker = row["ticker"]
        if ticker in audited_by_ticker:
            merged.append(audited_by_ticker[ticker])
        else:
            merged.append({
                **row,
                "risk_flags": ["Not in top LLM audit set"],
                "riskAuditVerdict": "HOLD_FOR_DATA",
                "verdict": "HOLD_FOR_DATA",
            })
    return merged


# =============================================================================
# INSTITUTIONAL AUDIT LEDGER
# =============================================================================

def build_audit_ledger(stocks: list[dict[str, Any]]) -> list[str]:
    """
    Build formatted audit ledger rows for institutional logging.
    Isolated from business logic -- formatting only.
    """
    ts = _ist_now().isoformat()
    return [
        f"{s['ticker']} | "
        f"Alpha Score: {s.get('alpha_score', 0.0)} | "
        f"Risk Flags: [{', '.join(s.get('risk_flags', ['None']))}] | "
        f"Verdict: {s.get('verdict', 'APPROVE')} | "
        f"Timestamp: {ts}"
        for s in stocks
    ]



def _coarse_pre_rank(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in stocks:
        ltp = float(row.get("ltpRaw") or 0)
        close = float(row.get("close") or 0)
        pct = abs(((ltp - close) / close) * 100) if close else 0.0
        volume = float(row.get("volume") or 0)
        score = round(abs(pct) * 2.0 + (0.0 if volume <= 0 else math.log10(volume + 1)), 2)
        ranked.append({**row, "_coarse_score": score})
    ranked.sort(key=lambda item: item.get("_coarse_score", 0), reverse=True)
    return ranked


def _select_top_volume_stocks(stocks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Return the highest same-day volume stocks from the scanned universe."""
    if limit <= 0 or not stocks:
        return []
    ranked = sorted(stocks, key=lambda row: float(row.get("volume") or 0), reverse=True)
    return ranked[:limit]


def _hard_screen(stock: dict[str, Any]) -> bool:
    intraday = stock.get("intraday") or {}
    return bool(intraday.get("passes_hard_filters"))


def _compile_selection_stream(
    all_stocks: list[dict[str, Any]],
    pool_name: str,
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    hard_screen_count: int,
    custom_prompt: str | None = None,
) -> str:
    lines = [
        f"TOP_N: {LLM_DISPLAY_COUNT}",
        f"RANKED_POOL_SIZE: {_TI_TOP_SELECTION_COUNT}",
        f"ACTIVE_POOL: {pool_name}",
        f"FILTER_PROMPT: {_filter_prompt(custom_prompt)}",
        f"HARD_SCREEN_PASS_COUNT: {hard_screen_count}/{len(all_stocks)}",
        "IMPORTANT: Use only the live Angel One universe below. Do not invent tickers.",
        "Return a valid JSON object matching the terminal intelligence schema.",
        "",
        "--- LIVE ANGEL ONE UNIVERSE ---",
    ]

    for stock in all_stocks:
        intraday = stock.get("intraday") or {}
        hard_status = "PASS" if intraday.get("passes_hard_filters") else "FAIL"
        reasons = "; ".join(intraday.get("hard_filter_reasons") or []) or "none"
        lines.append(
            f"{stock['ticker']} | {stock['name']} | LTP {stock['ltp']} | delta {stock['delta']} | "
            f"state {stock['state']} | close {stock.get('close')} | volume {stock.get('volume')} | "
            f"ATR% {intraday.get('atr_pct', 0)} | volX {intraday.get('volume_multiplier', 0)} | "
            f"RSI {intraday.get('rsi', 0)} | pivotR1 {intraday.get('pivot_r1', 0)} | "
            f"promoter {stock.get('promoter_holding_pct', 'n/a')}% | "
            f"VWAP {intraday.get('vwap', 0)} | EMA9 {intraday.get('ema9', 0)} | ORB {intraday.get('orb_high', 0)} | "
            f"turnoverCr {intraday.get('turnover_cr', 0)} | OI {intraday.get('oi_setup', 'NEUTRAL')} | "
            f"bulkDeal {intraday.get('bulk_deal_value_cr', 0)}Cr "
            f"({'Y' if intraday.get('bulk_deal_signal') else 'N'}) | "
            f"screen {hard_status} | quality {'PASS' if intraday.get('passes_quality_filters') else 'FAIL'} | reasons {reasons}"
        )

    if news_items:
        lines.append("")
        lines.append("--- NEWS FEEDS ---")
        for item in news_items[:10]:
            lines.append(f"{item['source']} | {item['title']} | {item['summary']} | {item['link']}")

    if macro_morning:
        lines.append("")
        lines.append("--- MACRO MORNING ---")
        for row in macro_morning[:10]:
            lines.append(f"{row['label']} | {row['val']} | {row['delta']} | {row['state']}")

    if macro_evening:
        lines.append("")
        lines.append("--- MACRO EVENING ---")
        for row in macro_evening[:10]:
            lines.append(f"{row['label']} | {row['val']} | {row['delta']} | {row['state']}")

    return "\n".join(lines)


def _select_dynamic_top_stocks(
    all_stocks: list[dict[str, Any]],
    pool_name: str,
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    custom_prompt: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    if not all_stocks:
        return [], None, None

    try:
        screened = [row for row in all_stocks if _hard_screen(row)]
        selection_universe = screened if len(screened) >= _TI_TOP_SELECTION_COUNT else all_stocks
        llm_universe = selection_universe[:LLM_DISPLAY_COUNT]
        compiled = _compile_selection_stream(
            llm_universe,
            pool_name=pool_name,
            news_items=news_items,
            macro_morning=macro_morning,
            macro_evening=macro_evening,
            hard_screen_count=len(screened),
            custom_prompt=custom_prompt,
        )
        ti = execute_terminal_intelligence_pipeline(compiled)
        ti_payload = ti.model_dump()
        selected_tickers = [row.get("ticker") for row in ti_payload.get("ledger_stocks", []) if row.get("ticker")]
        selected_tickers = selected_tickers[:_TI_TOP_SELECTION_COUNT]
        score_by_ticker = {
            row.get("ticker"): row.get("score")
            for row in ti_payload.get("ledger_stocks", [])
            if row.get("ticker") is not None
        }
        by_ticker = {row["ticker"]: row for row in all_stocks}
        for row in ti_payload.get("ledger_stocks", []):
            ticker = row.get("ticker")
            if not ticker:
                continue
            src = by_ticker.get(ticker)
            if src:
                rv = str(row.get("delta") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("delta"):
                    row["delta"] = src["delta"]
                rv = str(row.get("ltp") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("ltp"):
                    row["ltp"] = src["ltp"]
                rv = str(row.get("name") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("name"):
                    row["name"] = src["name"]
        selected_rows = []
        for ticker in selected_tickers:
            row = by_ticker.get(ticker)
            if row:
                selected_rows.append({**row, "score": score_by_ticker.get(ticker)})

        if not selected_rows:
            selected_rows = _heuristic_rank(selection_universe)
        else:
            if len(selected_rows) < _TI_TOP_SELECTION_COUNT:
                selected_set = {r["ticker"] for r in selected_rows}
                hard_passers = [
                    row for row in _heuristic_rank(selection_universe)
                    if row["ticker"] not in selected_set and _hard_screen(row)
                ]
                selected_rows.extend(hard_passers[: _TI_TOP_SELECTION_COUNT - len(selected_rows)])

        news_summary = (
            ti_payload.get("news_catalysts_card") or ti_payload.get("forensic_screen_card") or ti_payload.get("why_interested")
        )
        return selected_rows[:_TI_TOP_SELECTION_COUNT], ti_payload, news_summary
    except Exception as e:
        # Do not return heuristic data. Return error state so system knows to try on-demand later.
        ti_payload = {
            "llmError": str(e),
            "why_interested": "LLM selection failed.",
            "ledger_stocks": [],
            "news_catalysts_card": None,
            "forensic_screen_card": None,
        }
        return [], ti_payload, None


def _build_macro_strips(macro_raw: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    morning: list[dict[str, Any]] = []
    evening: list[dict[str, Any]] = []
    seen_labels: set[str] = set()

    # Build a map of label -> Yahoo row (with sparkline data) so we can attach
    # sparklines to Angle One instrument rows and avoid losing them.
    yahoo_sparklines: dict[str, list[float]] = {}
    for row in fetch_domestic_index_macro():
        sparkline = row.get("sparkline", [])
        if isinstance(sparkline, list) and len(sparkline) > 1:
            yahoo_sparklines[row["label"].upper()] = sparkline
    for row in fetch_domestic_yahoo_macro():
        sparkline = row.get("sparkline", [])
        if isinstance(sparkline, list) and len(sparkline) > 1:
            yahoo_sparklines[row["label"].upper()] = sparkline

    for inst in MACRO_INSTRUMENTS:
        quote = macro_raw.get(inst.key)
        if not quote:
            continue
        ltp = float(quote.get("ltp", 0) or 0)
        close = float(quote.get("close", 0) or ltp)
        delta, state = _pct_change(ltp, close if close else None)
        label = inst.label or inst.key
        # Attach sparkline from Yahoo if available for this label
        label_upper = label.upper()
        sparkline = yahoo_sparklines.get(label_upper, [])
        morning.append({"label": label, "val": f"{ltp:,.2f}", "delta": delta, "state": state, "sparkline": sparkline})
        evening.append({"label": f"{label} Close", "val": f"{ltp:,.2f}", "delta": delta, "state": state, "sparkline": sparkline})
        seen_labels.add(label_upper)

    for row in fetch_domestic_index_macro():
        label = str(row["label"])
        if label.upper() in seen_labels:
            continue
        morning.append({k: row.get(k) for k in ("label", "val", "delta", "state", "sparkline")})
        evening.append({"label": f"{row['label']} Close", "val": row["val"], "delta": row["delta"], "state": row["state"], "sparkline": row.get("sparkline", [])})
        seen_labels.add(label.upper())

    for row in fetch_domestic_yahoo_macro():
        morning.append({k: row.get(k) for k in ("label", "val", "delta", "state", "sparkline")})
        evening.append({"label": f"{row['label']} Close", "val": row["val"], "delta": row["delta"], "state": row["state"], "sparkline": row.get("sparkline", [])})

    # GIFT NIFTY from NSE India API (has no sparkline data, so default to [])
    gift_nifty = fetch_gift_nifty()
    if gift_nifty and gift_nifty["label"].upper() not in seen_labels:
        gs = gift_nifty.get("sparkline", []) or []
        morning.append({"label": gift_nifty["label"], "val": gift_nifty["val"], "delta": gift_nifty["delta"], "state": gift_nifty["state"], "sparkline": gs})
        evening.append({"label": f"{gift_nifty['label']} Close", "val": gift_nifty["val"], "delta": gift_nifty["delta"], "state": gift_nifty["state"], "sparkline": gs})
        seen_labels.add(gift_nifty["label"].upper())

    return morning, evening


def _build_terminal_payload(
    all_stocks: list[dict[str, Any]],
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    pool_name: str = NIFTY_500_LABEL,
    custom_prompt: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    return _select_dynamic_top_stocks(
        all_stocks=all_stocks,
        pool_name=pool_name,
        news_items=news_items,
        macro_morning=macro_morning,
        macro_evening=macro_evening,
        custom_prompt=custom_prompt,
    )


def _build_payload_from_live_data(
    client: AngelOneClient,
    pool_name: str | None = None,
    custom_prompt: str | None = None,
    force_llm_refresh: bool = False,
    prior_snapshot: dict[str, Any] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    llm_config = _llm_config_canonical()
    now = _ist_now()
    resolved_pool_name = pool_name or NIFTY_500_LABEL
    snapshot = prior_snapshot if prior_snapshot is not None else _load_last_snapshot()
    intraday_cache = _snapshot_intraday_cache(snapshot)

    progress("Fetching live quotes...")
    stock_universe, active_pool_label = _quote_universe(resolved_pool_name, client)

    stock_quotes_raw, quote_coverage = _fetch_stock_quotes_with_coverage(client, stock_universe)
    if not quote_coverage["selectionAllowed"]:
        raise RuntimeError(
            "Market quote coverage below required threshold: "
            f"{quote_coverage['received']}/{quote_coverage['expected']} "
            f"({quote_coverage['coveragePct']}%). Missing: "
            f"{', '.join(quote_coverage['missingSymbols'][:25])}"
        )
    macro_raw = client.fetch_batch_quotes(list(MACRO_INSTRUMENTS))

    all_stocks: list[dict[str, Any]] = []
    stock_quotes: dict[str, dict[str, Any]] = {}
    stock_universe_by_key = {inst.key: inst for inst in stock_universe}
    for inst in stock_universe:
        quote = stock_quotes_raw.get(inst.key)
        if not quote:
            continue
        row = _build_stock_row(inst, quote, active_pool_label)
        all_stocks.append(row)
        stock_quotes[inst.key] = row

    candle_limit = int(os.getenv("INTRADAY_CANDIDATE_LIMIT", str(VOLUME_PRESELECT_LIMIT)))
    volume_limit = int(os.getenv("VOLUME_PRESELECT_LIMIT", str(VOLUME_PRESELECT_LIMIT)))
    swing_limit = int(os.getenv("SWING_CANDIDATE_LIMIT", str(SWING_CANDIDATE_LIMIT)))
    candle_limit = max(candle_limit, volume_limit, swing_limit)
    top_by_volume = _select_top_volume_stocks(all_stocks, candle_limit)
    candidate_rows = top_by_volume[:candle_limit]
    candidate_keys = {row["ticker"] for row in candidate_rows}
    row_by_ticker = {row["ticker"]: row for row in all_stocks}

    for row in all_stocks:
        if row["ticker"] not in candidate_keys:
            row["intraday"] = {
                "atr_pct": 0.0,
                "volume_multiplier": 0.0,
                "today_volume": 0.0,
                "avg_daily_volume_20": 0.0,
                "vwap": 0.0,
                "ema9": 0.0,
                "ema_angle_deg": 0.0,
                "orb_high": 0.0,
                "orb_low": 0.0,
                "orb_velocity_pct": 0.0,
                "wick_noise_ratio": 1.0,
                "turnover_cr": 0.0,
                "price_above_vwap": False,
                "price_above_ema9": False,
                "trigger_point": "VWAP Bounce",
                "passes_hard_filters": False,
                "hard_filter_reasons": ["not in intraday candidate set"],
            }

    rows_to_fetch: list[dict[str, Any]] = []
    for row in candidate_rows:
        cached_intraday = intraday_cache.get(row["ticker"])
        if _intraday_metrics_usable(cached_intraday):
            row["intraday"] = cached_intraday
            stock_quotes[row["ticker"]] = row
        else:
            rows_to_fetch.append(row)

    if rows_to_fetch:
        progress(f"Fetching intraday metrics for {len(rows_to_fetch)} symbols...")
        fetched_metrics = _fetch_all_intraday_chunked(
            client,
            rows_to_fetch,
            stock_universe_by_key,
            now,
            on_progress=on_progress,
        )
        for ticker, metrics in fetched_metrics.items():
            original = row_by_ticker.get(ticker)
            if original is not None:
                original["intraday"] = metrics
                stock_quotes[ticker] = original

    candle_ready = sum(
        1 for row in candidate_rows if _intraday_metrics_usable(row.get("intraday"))
    )
    candle_expected = len(candidate_rows)
    candle_coverage_pct = round(
        (candle_ready / candle_expected * 100.0) if candle_expected else 0.0, 2
    )
    quote_coverage["candles"] = {
        "expected": candle_expected,
        "received": candle_ready,
        "coveragePct": candle_coverage_pct,
        "selectionAllowed": bool(
            candle_expected
            and candle_coverage_pct >= MARKET_DATA_MIN_CANDLE_COVERAGE_PCT
        ),
    }
    if not quote_coverage["candles"]["selectionAllowed"]:
        raise RuntimeError(
            "Candle coverage below required threshold: "
            f"{candle_ready}/{candle_expected} ({candle_coverage_pct}%)"
        )

    bulk_deal_map = load_bulk_deals()
    promoter_map = ensure_promoter_holdings([row["ticker"] for row in candidate_rows])
    for row in all_stocks:
        if row["ticker"] in candidate_keys:
            enrich_stock_quality(row, promoter_map, bulk_deal_map)
            stock_quotes[row["ticker"]] = row

    # ─────────────────────────────────────────────────────────────────────────
    # STAGE 1: Deterministic Quant Engine
    # Applies hard filters and computes Alpha Scores with no LLM involvement.
    # Returns top TOP_SELECTION_COUNT by Alpha Score; pads with volume leaders if needed.
    # ─────────────────────────────────────────────────────────────────────────
    progress("Running quant pipeline...")
    top_ranked = _compute_deterministic_pipeline(all_stocks)

    macro_morning, macro_evening = _build_macro_strips(macro_raw)
    global_macro = fetch_global_macro()
    news_items = fetch_live_news()

    existing_ti = snapshot.get("terminalIntelligence") if snapshot else None
    existing_summary = snapshot.get("newsSummary") if snapshot else None
    existing_ticker_news = snapshot.get("tickerNewsByTicker") if snapshot else {}

    top_llm_tickers = [row["ticker"] for row in top_ranked[:LLM_DISPLAY_COUNT]]
    can_reuse_ai = not force_llm_refresh and _ai_cache_fresh(snapshot, top_llm_tickers)

    reused_llm = False
    if can_reuse_ai:
        cached_stock_by_ticker = {
            str(row.get("ticker") or row.get("symbol") or "").upper(): row
            for row in ((snapshot or {}).get("stocks") or [])
            if isinstance(row, dict) and (row.get("ticker") or row.get("symbol"))
        }
        verdict_by_ticker = {
            str(row.get("ticker")).upper(): row
            for row in ((existing_ti or {}).get("ledger_stocks") or [])
            if row.get("ticker")
        }
        final_audited: list[dict[str, Any]] = []
        for row in top_ranked:
            enriched = dict(row)
            ledger = verdict_by_ticker.get(str(row["ticker"]).upper())
            cached_stock = cached_stock_by_ticker.get(str(row["ticker"]).upper())
            audit_source = cached_stock or ledger or {}
            cached_verdict = str(
                audit_source.get("riskAuditVerdict")
                or audit_source.get("verdict")
                or ""
            ).upper().strip()
            if row["ticker"] not in top_llm_tickers:
                cached_verdict = "HOLD_FOR_DATA"
            elif cached_verdict not in ("APPROVE", "REJECT", "HOLD_FOR_DATA"):
                cached_verdict = "HOLD_FOR_DATA"
            enriched["riskAuditVerdict"] = cached_verdict
            enriched["verdict"] = cached_verdict
            enriched["risk_flags"] = list(audit_source.get("risk_flags") or [
                "Reused cached risk audit" if cached_verdict != "HOLD_FOR_DATA"
                else "No reusable risk audit; fail-closed hold"
            ])
            if isinstance(audit_source.get("deskIcSummary"), dict):
                enriched["deskIcSummary"] = dict(audit_source["deskIcSummary"])
            elif cached_verdict == "HOLD_FOR_DATA":
                enriched["deskIcSummary"] = {
                    "deskDecision": "HOLD_FOR_DATA",
                    "conviction": None,
                    "oneLiner": "No reusable risk audit; fail-closed hold.",
                    "source": "risk_audit",
                }
            final_audited.append(enriched)
        top_rows = final_audited[:_TI_TOP_SELECTION_COUNT]
        terminal_intel = existing_ti
        news_summary = existing_summary
        reused_llm = True
        desk_ic_map = (
            snapshot.get("deskIcByTicker")
            if isinstance(snapshot.get("deskIcByTicker"), dict)
            else {}
        )
        _log = logging.getLogger(__name__)
        _log.info(
            "Reusing snapshot terminalIntelligence/newsSummary (day-lock=%s top-%d)",
            _llm_locked_for_today(snapshot),
            LLM_DISPLAY_COUNT,
        )
    else:
        progress(f"Running LLM risk audit on top {LLM_DISPLAY_COUNT}...")
        final_audited = _execute_llm_risk_audit(top_ranked, news_items)
        try:
            from .desk_ic_criteria import batch_desk_ic_for_stocks

            progress(f"Running Desk IC criteria on top {LLM_DISPLAY_COUNT}...")
            desk_ic_map = batch_desk_ic_for_stocks(
                final_audited[:LLM_DISPLAY_COUNT],
                news_by_ticker=existing_ticker_news or {},
                # Refresh path: deterministic FactPack (incl. risk verdict). Drawer /api/desk-ic uses LLM.
                use_llm=False,
                limit=LLM_DISPLAY_COUNT,
            )
        except Exception as desk_exc:
            logging.getLogger(__name__).warning("Desk IC batch failed: %s", desk_exc)
            desk_ic_map = {}
        progress("Building terminal intelligence...")
        ledger_rows = build_audit_ledger([s for s in final_audited if s.get("ticker") in top_llm_tickers])
        _log = logging.getLogger(__name__)
        _log.info("\n" + "=" * 40 + " INSTITUTIONAL RISK AUDIT LEDGER " + "=" * 40)
        for ledger_row in ledger_rows:
            _log.info(ledger_row)
        _log.info("=" * 113)
        top_rows, terminal_intel, news_summary = _build_terminal_payload(
            all_stocks=final_audited,
            news_items=news_items,
            macro_morning=macro_morning,
            macro_evening=macro_evening,
            pool_name=resolved_pool_name,
            custom_prompt=custom_prompt,
        )

    payload = {
        "success": True,
        "source": f"angel_one+news+llm_dynamic_top{_TI_TOP_SELECTION_COUNT}",
        "rawSources": _news_feed_sources(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "mockTickers": sorted(MOCK_TICKERS),
        "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
        "activePool": resolved_pool_name,
        "poolDescription": (
            "Nifty 500 universe: live quotes on full index, swing candles on top "
            f"{candle_limit} by volume, Asset Matrix volume screen {volume_limit}."
            if resolved_pool_name == NIFTY_500_LABEL
            else (
                "Matrix pool "
                f"{resolved_pool_name}; swing hunt still quotes the full Nifty 500."
            )
        ),
        "universeSize": len(all_stocks),
        "volumeScreenedCount": len(candidate_rows),
        "marketDataCoverage": quote_coverage,
        "stocks": top_rows,
        "stockQuotes": stock_quotes,
        "macroDataStrip": {"morning": macro_morning, "evening": macro_evening},
        "globalMacro": global_macro,
        "news": news_items,
        "llmProvider": llm_config[0] if llm_config else None,
        "llmConfigured": llm_config is not None,
        "newsSummary": news_summary,
        "llmError": None,
        "terminalIntelligence": terminal_intel,
        "tickerIntelligenceByTicker": {},
        "tickerNewsByTicker": existing_ticker_news or {},
        "deskIcByTicker": desk_ic_map if isinstance(desk_ic_map, dict) else {},
        "isSnapshotFallback": False,
    }
    # Day-lock: carry prior lock on reuse; stamp lock after a successful fresh LLM pass.
    if reused_llm and snapshot and snapshot.get("llmLockedForDate"):
        payload["llmLockedForDate"] = snapshot.get("llmLockedForDate")
    elif not reused_llm and terminal_intel and not terminal_intel.get("llmError") and news_summary:
        _stamp_llm_lock(payload, locked=True)

    progress("Fetching Dhan swing picks...")
    payload = _hydrate_dhan_swing_picks(payload, force=True)
    payload = _hydrate_ticker_intelligence_map(payload)
    _apply_selection_meta(
        payload,
        mode="live",
        reason="Live refresh completed during the scheduled IST window.",
        data_date=_ist_now().date().isoformat(),
    )

    return payload


def build_market_payload(
    client: AngelOneClient,
    pool_name: str | None = None,
    force_refresh: bool = False,
    custom_prompt: str | None = None,
    allow_fallback: bool = True, # If live fetch fails, allow falling back to snapshot
    prefer_cache: bool = False, # If true, try cache first, then live if cache is empty/stale
    force_llm_refresh: bool = False,  # When false, reuse day-locked / TTL-fresh snapshot AI
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    snapshot = _load_last_snapshot()

    if prefer_cache and snapshot:
        # If preferring cache and a snapshot exists, return it immediately.
        # The frontend can then decide to trigger an on-demand refresh if data is missing.
        snapshot = dict(snapshot)
        snapshot["isSnapshotFallback"] = True
        snapshot["updatedAt"] = datetime.now(timezone.utc).isoformat()
        snapshot.setdefault("tickerNewsByTicker", {})
        if pool_name:
            snapshot["activePool"] = pool_name
        # Prefer-cache is the SNAPSHOT first-paint path — do not block on RSS.
        # Snapshot already carries news; live RSS can refresh via macros/on-demand.
        _apply_selection_meta(
            snapshot,
            mode="snapshot",
            reason="Cache preferred. Serving the latest saved snapshot.",
            data_date=_payload_data_date(snapshot),
        )
        return _hydrate_ticker_intelligence_map(
            _hydrate_dhan_swing_picks(snapshot, prefer_persisted=True)
        )

    # Attempt live data fetch
    try:
        payload = _build_payload_from_live_data(
            client,
            pool_name=pool_name,
            custom_prompt=custom_prompt,
            force_llm_refresh=force_llm_refresh,
            prior_snapshot=snapshot,
            on_progress=on_progress,
        )
        _save_last_snapshot(payload)
        return payload
    except Exception as exc:
        if force_refresh and not allow_fallback:
            raise
        if allow_fallback and snapshot is not None:
            snapshot = dict(snapshot)
            snapshot["isSnapshotFallback"] = True
            snapshot["llmError"] = snapshot.get("llmError")
            snapshot["updatedAt"] = datetime.now(timezone.utc).isoformat()
            snapshot.setdefault("tickerNewsByTicker", {})
            if pool_name:
                snapshot["activePool"] = pool_name
            # Refresh RSS news even when outside refresh window
            try: # Still try to fetch fresh news even if falling back to old stock data
                fresh_news = fetch_live_news()
                if fresh_news:
                    snapshot["news"] = fresh_news
            except Exception:
                pass
            _apply_selection_meta(
                snapshot,
                mode="snapshot",
                reason=f"Live refresh failed ({exc}). Serving the latest saved snapshot with fresh news.",
                data_date=_payload_data_date(snapshot),
            )
            return _hydrate_ticker_intelligence_map(
                _hydrate_dhan_swing_picks(snapshot, prefer_persisted=True)
            )
        if not allow_fallback:
            return {
                "success": False,
                "error": "Live refresh was requested but the scheduled refresh window is not active and fallback is disabled.",
                "rawSources": _news_feed_sources(),
                "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
                "activePool": pool_name or NIFTY_500_LABEL,
                "poolDescription": "Nifty 500 Angel One live universe; swing hunt uses the full index.",
                "stocks": [],
                "stockQuotes": {},
                "macroDataStrip": {"morning": [], "evening": []},
                "globalMacro": {"indices": [], "commodities": []},
                "news": [],
                "newsSummary": None,
                "llmError": None,
                "terminalIntelligence": None,
                "tickerIntelligenceByTicker": {},
                "tickerNewsByTicker": {},
                "isSnapshotFallback": False,
                "selectionMeta": {
                    "mode": "live",
                    "reason": f"Live refresh failed ({exc}) and fallback is disabled.",
                    "dataDate": _ist_now().date().isoformat(),
                },
            }
        return {
            "success": False,
            "error": "No cached snapshot available. Live refresh runs only during the morning or evening IST windows.",
            "rawSources": _news_feed_sources(),
            "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
            "activePool": pool_name or NIFTY_500_LABEL,
            "poolDescription": "Nifty 500 Angel One live universe; swing hunt uses the full index.",
            "stocks": [],
            "stockQuotes": {},
            "macroDataStrip": {"morning": [], "evening": []},
            "globalMacro": {"indices": [], "commodities": []},
            "news": [],
            "newsSummary": None,
            "llmError": None,
            "terminalIntelligence": None,
            "tickerIntelligenceByTicker": {},
            "tickerNewsByTicker": {},
            "isSnapshotFallback": True,
            "selectionMeta": {
                "mode": "snapshot",
                    "reason": f"Live refresh failed ({exc}) and no cached snapshot is available.",
                "dataDate": _ist_now().date().isoformat(),
            },
        }


def refresh_snapshot_macros(client: AngelOneClient | None = None) -> dict[str, Any]:
    """Light live refresh of SNAPSHOT indices / commodities only (no LLM / stock rebuild).

    Concurrent callers get the last snapshot immediately (no pile-up). Hard-capped
    so a slow Angel/Yahoo path cannot block the desk for a minute+.
    """
    if not _MACRO_REFRESH_LOCK.acquire(blocking=False):
        snapshot = _load_last_snapshot()
        snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
        return {
            "success": True,
            "busy": True,
            "updatedAt": snapshot.get("updatedAt"),
            "macrosRefreshedAt": snapshot.get("macrosRefreshedAt"),
            "macroCount": len((snapshot.get("macroDataStrip") or {}).get("morning") or []),
            "globalIndexCount": len((snapshot.get("globalMacro") or {}).get("indices") or []),
            "commodityCount": len((snapshot.get("globalMacro") or {}).get("commodities") or []),
            "payload": snapshot,
        }

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_refresh_snapshot_macros_body, client)
            try:
                return fut.result(timeout=18)
            except Exception as exc:
                logging.getLogger(__name__).warning("refresh_snapshot_macros timed out/failed: %s", exc)
                snapshot = _load_last_snapshot()
                snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
                return {
                    "success": True,
                    "timedOut": True,
                    "updatedAt": snapshot.get("updatedAt"),
                    "macrosRefreshedAt": snapshot.get("macrosRefreshedAt"),
                    "macroCount": len((snapshot.get("macroDataStrip") or {}).get("morning") or []),
                    "globalIndexCount": len((snapshot.get("globalMacro") or {}).get("indices") or []),
                    "commodityCount": len((snapshot.get("globalMacro") or {}).get("commodities") or []),
                    "payload": snapshot,
                }
    finally:
        _MACRO_REFRESH_LOCK.release()


def _refresh_snapshot_macros_body(client: AngelOneClient | None = None) -> dict[str, Any]:
    """Inner macro refresh body (runs under lock + timeout)."""
    snapshot = _load_last_snapshot()
    if not isinstance(snapshot, dict):
        snapshot = {
            "success": True,
            "stocks": [],
            "stockQuotes": {},
            "macroDataStrip": {"morning": [], "evening": []},
            "globalMacro": {"indices": [], "commodities": []},
            "news": [],
        }
    else:
        snapshot = dict(snapshot)

    used = client or AngelOneClient()
    try:
        macro_raw = used.fetch_batch_quotes(list(MACRO_INSTRUMENTS))
    except Exception as exc:
        logging.getLogger(__name__).warning("macro Angel quotes failed: %s", exc)
        macro_raw = {}

    morning, evening = _build_macro_strips(macro_raw if isinstance(macro_raw, dict) else {})
    try:
        gm = fetch_global_macro()
    except Exception as exc:
        logging.getLogger(__name__).warning("global macro failed: %s", exc)
        gm = snapshot.get("globalMacro") if isinstance(snapshot.get("globalMacro"), dict) else {}
        gm = dict(gm or {})

    now_iso = datetime.now(timezone.utc).isoformat()
    snapshot["macroDataStrip"] = {"morning": morning, "evening": evening}
    snapshot["globalMacro"] = {
        "indices": list(gm.get("indices") or []),
        "commodities": list(gm.get("commodities") or []),
    }
    snapshot["updatedAt"] = now_iso
    snapshot["macrosRefreshedAt"] = now_iso
    snapshot["isSnapshotFallback"] = False
    snapshot["success"] = True
    _save_last_snapshot(snapshot)
    return {
        "success": True,
        "updatedAt": now_iso,
        "macrosRefreshedAt": now_iso,
        "macroCount": len(morning),
        "globalIndexCount": len(snapshot["globalMacro"]["indices"]),
        "commodityCount": len(snapshot["globalMacro"]["commodities"]),
        "payload": snapshot,
    }


def _compile_market_analysis_stream(payload: dict[str, Any], custom_prompt: str | None = None) -> str:
    lines = [
        f"TOP_N: {_TI_TOP_SELECTION_COUNT}",
        f"FILTER_PROMPT: {_filter_prompt(custom_prompt)}",
        "Use the live Angel One universe and return only valid JSON.",
        "",
        "--- NEWS ---",
    ]

    for item in payload.get("news", [])[:10]:
        lines.append(
            f"Source: {item['source']}\nTitle: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n"
        )

    lines.append("--- TOP STOCKS ---")
    for stock in payload.get("stocks", [])[:_TI_TOP_SELECTION_COUNT]:
        lines.append(
            f"{stock['ticker']} ({stock['name']}): LTP {stock['ltp']}, delta {stock['delta']}, "
            f"state {stock['state']}, close {stock.get('close')}, volume {stock.get('volume')}"
        )

    lines.append("--- MACRO MORNING ---")
    for row in payload.get("macroDataStrip", {}).get("morning", [])[:10]:
        lines.append(f"{row['label']}: {row['val']} {row['delta']} {row['state']}")

    return "\n".join(lines)


def create_app() -> FastAPI:
    _load_refresh_tasks_from_disk()
    app = FastAPI(title="IROS Angel One Market Feed", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/market-data")
    def market_data(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            # Prefer-cache path does not need Angel login — avoid constructing client.
            return build_market_payload(
                None,  # type: ignore[arg-type]
                pool_name=pool,
                custom_prompt=prompt,
                prefer_cache=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/refresh-macros")
    def refresh_macros() -> dict[str, Any]:
        """Refresh SNAPSHOT India/global indices + commodities only (fast path)."""
        try:
            return refresh_snapshot_macros()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/nse-symbols")
    def nse_symbols(universe: str = "nifty500") -> dict[str, Any]:
        """Searchable NSE equity tickers for the desk header search bar.

        universe=nifty500 (default): cached Nifty 500 instruments (~500).
        universe=all: Angel NSE -EQ scrip master keys (~2.4k) when available.
        """
        try:
            mode = str(universe or "nifty500").strip().lower()
            items: list[dict[str, str]] = []
            source = "nifty500_instruments"

            if mode in ("all", "full", "nse"):
                try:
                    token_map = _load_nse_eq_token_map(force_refresh=False)
                    for key in sorted(token_map.keys()):
                        items.append({"ticker": key, "name": key})
                    source = "angel_scrip_master_nse_eq"
                except Exception as exc:
                    logging.getLogger(__name__).warning("nse-symbols all-universe failed: %s", exc)

            if not items:
                inst_path = Path(__file__).resolve().parent / "nifty500_instruments.json"
                sym_path = Path(__file__).resolve().parent.parent / "data" / "nifty500_symbols.json"
                if inst_path.is_file():
                    raw = json.loads(inst_path.read_text(encoding="utf-8"))
                    for row in raw.get("instruments") or []:
                        if not isinstance(row, dict):
                            continue
                        key = str(row.get("key") or "").upper().strip()
                        if not key:
                            continue
                        label = str(row.get("label") or key).strip() or key
                        items.append({"ticker": key, "name": label})
                    source = "nifty500_instruments"
                elif sym_path.is_file():
                    raw = json.loads(sym_path.read_text(encoding="utf-8"))
                    for sym in raw.get("symbols") or []:
                        key = str(sym or "").upper().strip()
                        if key:
                            items.append({"ticker": key, "name": key})
                    source = "nifty500_symbols"

            # Merge any snapshot quote names for richer display
            snap = _load_last_snapshot() or {}
            quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
            by_ticker = {r["ticker"]: r for r in items}
            for t, q in quotes.items():
                key = str(t or "").upper().strip()
                if not key:
                    continue
                name = key
                if isinstance(q, dict):
                    name = str(q.get("name") or q.get("ticker") or key).strip() or key
                if key in by_ticker:
                    if name and name != key:
                        by_ticker[key]["name"] = name
                else:
                    by_ticker[key] = {"ticker": key, "name": name}
            items = sorted(by_ticker.values(), key=lambda r: r["ticker"])
            return {
                "success": True,
                "source": source,
                "universe": mode if items else "nifty500",
                "count": len(items),
                "symbols": items,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/audit-verdicts")
    def audit_verdicts() -> dict[str, Any]:
        """Return all ticker risk audit results (Approved or Rejected) in clean JSON."""
        snapshot = _load_last_snapshot()
        if not snapshot:
            return {
                "success": False,
                "error": "No cached market snapshot available. Run a live refresh first."
            }
        
        verdicts = []
        for stock in snapshot.get("stocks", []):
            verdicts.append({
                "ticker": stock.get("ticker"),
                "name": stock.get("name"),
                "alpha_score": stock.get("alpha_score", 0.0),
                "verdict": stock.get("verdict", "APPROVE"),
                "risk_flags": stock.get("risk_flags", ["None"]),
                "deskIcSummary": stock.get("deskIcSummary"),
            })
            
        return {
            "success": True,
            "updatedAt": snapshot.get("updatedAt"),
            "count": len(verdicts),
            "verdicts": verdicts
        }

    @app.get("/api/desk-ic")
    def desk_ic(ticker: str = "", force: bool = False, fast: bool = False) -> dict[str, Any]:
        """Fact-grounded Desk IC criteria (senior IB checklist) for one ticker."""
        sym = (ticker or "").strip().upper()
        if not sym:
            raise HTTPException(status_code=400, detail="Missing required parameter: ticker")
        snapshot = _load_last_snapshot() or {}
        try:
            snapshot = ensure_snapshot_ticker_facts(snapshot, sym)
            from .desk_ic_criteria import evaluate_and_cache_ticker, get_cached_desk_ic

            cached = None if force else get_cached_desk_ic(
                snapshot, sym, require_llm=not fast
            )
            fact = None
            try:
                from .desk_ic_criteria import build_fact_pack, resolve_stock_from_snapshot

                fact = build_fact_pack(sym, resolve_stock_from_snapshot(snapshot, sym))
            except Exception:
                fact = None
            if cached and isinstance(cached.get("factPack"), dict) and isinstance(fact, dict):
                if cached["factPack"].get("ltp") is None and fact.get("ltp") is not None:
                    cached = None
                elif cached["factPack"].get("turnover_cr") is None and fact.get("turnover_cr") is not None:
                    cached = None
            if cached:
                return {"success": True, "ticker": sym, "deskIc": cached, "cached": True}
            result = evaluate_and_cache_ticker(
                snapshot,
                sym,
                use_llm=not fast,
                force=force,
            )
            if snapshot and not fast:
                try:
                    _save_last_snapshot(snapshot)
                except Exception:
                    pass
            return {"success": True, "ticker": sym, "deskIc": result, "cached": False, "fast": fast}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/intraday-matrix")
    def intraday_matrix() -> dict[str, Any]:
        """Return lemonn.co.in intraday stock recommendations (upper panel)."""
        try:
            from .lemonn_recommender import (
                fetch_intraday_recommendations,
                recommendations_to_dict,
            )
            recs = fetch_intraday_recommendations(top_n=10)
            return {
                "success": True,
                "recommendations": recommendations_to_dict(recs),
                "count": len(recs),
                "source": "lemonn.co.in",
            }
        except Exception:
            # Fallback: When lemonn.co.in is unreachable, return mock data
            # so the frontend never shows a 404 error page.
            _mock = [
                {"symbol": "RELIANCE", "name": "Reliance Industries", "direction": "BUY",
                 "buyPrice": 2950.00, "sellPrice": 3070.00, "stopLoss": 2910.00,
                 "riskPerShare": 40.00, "confidence": 82.0, "reasons": ["Strong breakout above 15m high", "RSI momentum bullish"]},
                {"symbol": "TCS", "name": "Tata Consultancy", "direction": "BUY",
                 "buyPrice": 4120.00, "sellPrice": 4280.00, "stopLoss": 4060.00,
                 "riskPerShare": 60.00, "confidence": 78.0, "reasons": ["Above 5m and 15m EMA50", "Delivery volume strong"]},
                {"symbol": "HDFCBANK", "name": "HDFC Bank", "direction": "BUY",
                 "buyPrice": 1680.00, "sellPrice": 1740.00, "stopLoss": 1655.00,
                 "riskPerShare": 25.00, "confidence": 85.0, "reasons": ["Daily SMA50 support held", "Bank Nifty momentum"]},
                {"symbol": "INFY", "name": "Infosys Ltd", "direction": "BUY",
                 "buyPrice": 1520.00, "sellPrice": 1580.00, "stopLoss": 1495.00,
                 "riskPerShare": 25.00, "confidence": 76.0, "reasons": ["IT sector rotation", "Above VWAP"]},
                {"symbol": "BHARTIARTL", "name": "Bharti Airtel", "direction": "BUY",
                 "buyPrice": 1425.00, "sellPrice": 1480.00, "stopLoss": 1400.00,
                 "riskPerShare": 25.00, "confidence": 80.0, "reasons": ["Telecom sector strength", "ARPU upgrade cycle"]},
                {"symbol": "LT", "name": "Larsen & Toubro", "direction": "BUY",
                 "buyPrice": 3650.00, "sellPrice": 3790.00, "stopLoss": 3590.00,
                 "riskPerShare": 60.00, "confidence": 73.0, "reasons": ["Capex cycle play", "Order book momentum"]},
                {"symbol": "SUNPHARMA", "name": "Sun Pharma", "direction": "SELL",
                 "buyPrice": 1580.00, "sellPrice": 1520.00, "stopLoss": 1610.00,
                 "riskPerShare": 30.00, "confidence": 65.0, "reasons": ["RSI overbought", "Pharma sector profit booking"]},
                {"symbol": "TITAN", "name": "Titan Company", "direction": "BUY",
                 "buyPrice": 3760.00, "sellPrice": 3910.00, "stopLoss": 3700.00,
                 "riskPerShare": 60.00, "confidence": 79.0, "reasons": ["Consumer demand recovery", "Gold price tailwind"]},
                {"symbol": "MARUTI", "name": "Maruti Suzuki", "direction": "BUY",
                 "buyPrice": 12450.00, "sellPrice": 12880.00, "stopLoss": 12280.00,
                 "riskPerShare": 170.00, "confidence": 81.0, "reasons": ["Auto sales momentum", "New launch pipeline"]},
                {"symbol": "SBIN", "name": "State Bank of India", "direction": "BUY",
                 "buyPrice": 820.00, "sellPrice": 850.00, "stopLoss": 808.00,
                 "riskPerShare": 12.00, "confidence": 84.0, "reasons": ["PSU banking rally", "Valuation comfort"]},
            ]
            return {
                "success": True,
                "recommendations": _mock,
                "count": len(_mock),
                "source": "lemonn.co.in (mock fallback)",
                "isMock": True,
            }

    @app.get("/api/dhan-scanner-matrix")
    def dhan_scanner_matrix() -> dict[str, Any]:
        """Dhan ScanX → feed_scanner pipeline with Trade Plan + ₹5L capital allocation."""
        try:
            from .dhan_scanner_service import fetch_dhan_scan_results
            return fetch_dhan_scan_results(min_volume=1_000_000, top_n=10)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/trade-outcomes")
    def trade_outcomes() -> dict[str, Any]:
        """Return persisted scanner picks with live target/SL hit status."""
        try:
            from .trade_outcome import get_trade_outcomes
            return get_trade_outcomes()
        except Exception as exc:
            return {"long": [], "short": [], "updatedAt": None, "error": str(exc)}

    @app.get("/api/fixed-trade-plan")
    def fixed_trade_plan() -> dict[str, Any]:
        """Return the fixed/static trade plan persisted as JSON."""
        try:
            from .trade_outcome import load_fixed_trade_plan
            return load_fixed_trade_plan() or {"long": [], "short": [], "updatedAt": None}
        except Exception as exc:
            return {"long": [], "short": [], "updatedAt": None, "error": str(exc)}

    @app.post("/api/fixed-trade-plan")
    def save_fixed_trade_plan(payload: dict[str, Any]) -> dict[str, Any]:
        """Overwrite the fixed trade plan JSON with the provided payload."""
        try:
            from .trade_outcome import save_fixed_trade_plan, _utc_now
            save_fixed_trade_plan(payload)
            return {"success": True, "updatedAt": _utc_now()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/live-prices")
    def live_prices() -> dict[str, Any]:
        """Prices + outcomes for fixed-plan symbols (monitor poll).

        On trading days (session + post-close), every plan ticker is refreshed via
        Angel One ltpData and/or Yahoo last print; snapshot fills the rest.
        See response.ltpSourceMix / priceSourcesNote. Never claims tick-live.
        """
        try:
            from .trade_outcome import get_live_prices_for_plan
            return get_live_prices_for_plan()
        except Exception as exc:
            return {
                "long": [],
                "short": [],
                "updatedAt": None,
                "snapshotUpdatedAt": None,
                "error": str(exc),
                "dataStale": True,
                "marketOpen": False,
                "sessionClosed": True,
                "ltpSourceMix": {"live": 0, "snapshot": 0, "cached": 0, "none": 0},
                "priceSourcesNote": "Error path — external Yahoo may have been attempted before failure",
            }

    @app.get("/api/intraday-session/candidates")
    def intraday_session_candidates() -> dict[str, Any]:
        """Score universe and propose a 5 LONG + 5 SHORT basket (not locked)."""
        try:
            from .intraday_session_engine import generate_candidates
            return generate_candidates()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/sector-heatmap")
    def sector_heatmap() -> dict[str, Any]:
        """Cached NSE Sectoral Indices heat map used by UI and intraday ranking."""
        from .sector_rotation import get_sector_heatmap

        return get_sector_heatmap()

    @app.post("/api/intraday-session/commit")
    def intraday_session_commit(force: bool = False) -> dict[str, Any]:
        """Lock intradAy basket (default 10L+10S) + auto-lock swing portfolio for EOD.

        Manual-broker only — no broker orders. Desk automation may auto-commit after pre-work.
        Symbols immutable until force unlock.
        """
        try:
            from .intraday_session_engine import commit_session
            result = commit_session(force=force)
            if not result.get("success") and result.get("error"):
                raise HTTPException(status_code=409, detail=result.get("error"))
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/swing-screener")
    def swing_screener_get() -> dict[str, Any]:
        """Cached swing pre-filter (Chartink unofficial or Yahoo). Lock gates unchanged."""
        try:
            from .swing_prefilter import load_prefilter_snapshot, refresh_swing_prefilter

            snap = load_prefilter_snapshot()
            if snap.get("symbols"):
                return snap
            return refresh_swing_prefilter(force=False)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/swing-screener/refresh")
    def swing_screener_refresh(force: bool = True) -> dict[str, Any]:
        """Refresh Chartink/Yahoo swing pre-filter snapshot."""
        try:
            from .swing_prefilter import refresh_swing_prefilter

            return refresh_swing_prefilter(force=force)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/swing-session")
    def swing_session_get(live: bool = False) -> dict[str, Any]:
        """Return locked swing portfolio; live=1 enriches LTP/Δ only (symbols fixed)."""
        try:
            from .swing_session import get_swing_session
            return get_swing_session(live=live)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/swing-session/lock")
    def swing_session_lock(force: bool = False) -> dict[str, Any]:
        """Lock Asset Matrix BUY set into swing_session.json for EOD."""
        try:
            from .swing_session import lock_swing_session
            result = lock_swing_session(force=force)
            if not result.get("success") and result.get("error"):
                raise HTTPException(status_code=409, detail=result.get("error"))
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/intraday-session")
    def intraday_session(live: bool = True) -> dict[str, Any]:
        """Return locked session state + mark-to-market (JSON snapshots only)."""
        try:
            from .intraday_session_engine import get_session
            return get_session(include_live=live)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/intraday-session/replacements")
    def intraday_session_replacements() -> dict[str, Any]:
        """GET replacement candidates + applied fills + free capital slots."""
        try:
            from .intraday_session_engine import get_session

            sess = get_session(include_live=True)
            return {
                "success": bool(sess.get("success")),
                "sessionDate": sess.get("sessionDate"),
                "locked": sess.get("locked"),
                "freeSlots": sess.get("freeSlots"),
                "replacementCandidates": sess.get("replacementCandidates") or [],
                "replacementsApplied": sess.get("replacementsApplied") or [],
                "lastReplacementAppliedAt": sess.get("lastReplacementAppliedAt"),
                "replacementBlockedReason": sess.get("replacementBlockedReason"),
                "replacementCutoffIst": sess.get("replacementCutoffIst"),
                "rotationWindow": sess.get("rotationWindow"),
                "rotationWindowCode": sess.get("rotationWindowCode"),
                "rotationWindowOpen": sess.get("rotationWindowOpen"),
                "updatedAt": sess.get("updatedAt"),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/alert-history")
    def alert_history(since: str | None = None) -> dict[str, Any]:
        """Return fired alert history for today, optionally filtered."""
        try:
            from .trade_outcome import get_alert_history
            return get_alert_history(since=since)
        except Exception as exc:
            return {"alerts": [], "total": 0, "error": str(exc)}

    @app.get("/api/reports/eod-intraday")
    def eod_intraday_report(
        date: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Post-close reconciliation of the day's intraday scanner picks.

        Serves ``data/eod/{date}/book_intraday.json`` when present unless force=true.
        """
        try:
            from datetime import date as _date
            from .eod_intraday_report import generate_intraday_eod_report
            from datetime import datetime as _dt
            for_date = (
                _date.fromisoformat(date)
                if date
                else _dt.now(tz=IST_ZONE).date()
            )
            return generate_intraday_eod_report(for_date, force=force)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/reports/eod-swing")
    def eod_swing_report(
        date: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Day-bucketed swing P&L. Cached under book_swing.json unless force=true."""
        try:
            from datetime import date as _date
            from .eod_swing_report import generate_swing_eod_report
            for_date = _date.fromisoformat(date) if date else None
            return generate_swing_eod_report(for_date, force=force)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/news")
    def news_feed() -> dict[str, Any]:
        try:
            return {"success": True, "news": fetch_live_news()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/test-ticker")
    def test_ticker(ticker: str = "RELIANCE") -> dict[str, Any]:
        try:
            client = AngelOneClient()
            ticker_upper = ticker.upper()
            inst = next(
                (i for i in WATCHLIST if i.key.upper() == ticker_upper),
                Instrument(ticker_upper, "NSE", f"{ticker_upper}-EQ", "2885")
            )
            quote = client.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
            return {
                "success": True,
                "ticker": ticker_upper,
                "quote": quote,
                "llmConfigured": _llm_config_canonical()[0] is not None,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/refresh-instrument-cache")
    def refresh_instrument_cache(pool: str = "Nifty 500") -> dict[str, Any]:
        """Refresh the Nifty 500 / Nifty 100 instrument cache from Angel One.

        On-demand cache population for the asset matrix pools.
        """
        try:
            if pool == NIFTY_100_LABEL:
                result = refresh_nifty100_cache()
            else:
                result = refresh_nifty500_cache()
            return {"success": result.get("success"), "pool": pool, "result": result}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/market-data/coverage")
    def market_data_coverage() -> dict[str, Any]:
        """Expose universe and quote coverage; missing symbols never disappear silently."""
        raw = _read_nifty500_cache_raw()
        snapshot = _load_last_snapshot() or {}
        return {
            "success": True,
            "cache": _nifty500_cache_health(raw),
            "cacheRefreshedAt": raw.get("refreshedAt") or raw.get("exportedAtUtc"),
            "cacheMissingSymbols": raw.get("unresolved") or [],
            "quotes": snapshot.get("marketDataCoverage") or {
                "selectionAllowed": False,
                "reason": "No coverage metadata in current snapshot",
            },
            "snapshotUpdatedAt": snapshot.get("updatedAt"),
        }

    @app.get("/api/market-intelligence")
    def market_intelligence(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=pool, custom_prompt=prompt)
            return {
                "success": True,
                "analysis": payload.get("terminalIntelligence"),
                "tickerIntelligenceByTicker": payload.get("tickerIntelligenceByTicker", {}),
                "newsSummary": payload.get("newsSummary"),
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
                "selectionMeta": payload.get("selectionMeta"),
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/terminal-intelligence")
    def terminal_intelligence(ticker: str | None = None, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        """Read-only ticker intelligence from the persisted snapshot (no live Angel refresh)."""
        try:
            snapshot = _load_last_snapshot()
            if not snapshot:
                raise HTTPException(status_code=503, detail="Market snapshot unavailable.")
            snapshot = dict(snapshot)
            if ticker:
                snapshot = ensure_snapshot_ticker_facts(snapshot, str(ticker).strip().upper())
            payload = _hydrate_ticker_intelligence_map(snapshot)
            if pool:
                payload["activePool"] = pool
            sym = str(ticker or "").strip().upper()
            if sym:
                report = (payload.get("tickerIntelligenceByTicker") or {}).get(sym)
                report = dict(report) if isinstance(report, dict) else build_ticker_intelligence_report(payload, sym)
            else:
                report = dict(payload.get("terminalIntelligence") or {})
            return {
                "success": True,
                "terminalIntelligence": report,
                "focusTicker": sym or ticker,
                "tickerIntelligenceByTicker": payload.get("tickerIntelligenceByTicker", {}),
                "newsSummary": payload.get("newsSummary"),
                "selectionMeta": payload.get("selectionMeta"),
                "isSnapshotFallback": bool(payload.get("isSnapshotFallback", False)),
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/orchestrated-refresh")
    async def trigger_orchestrated_refresh(background_tasks: BackgroundTasks, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        task_id = f"orchestrated:{int(time.time())}"
        with _REFRESH_TASK_LOCK:
            _REFRESH_TASKS[task_id] = {"status": "running", "progress": "Initializing sequence...", "created_at": time.time()}
        
        background_tasks.add_task(_run_orchestrated_sequence, task_id, pool, prompt)
        return {"success": True, "taskId": task_id, "message": "Sequential orchestrated refresh started."}

    @app.post("/api/refresh-intelligence")
    def refresh_intelligence(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        task_id = _refresh_task_key(pool, prompt)
        with _REFRESH_TASK_LOCK:
            task = _REFRESH_TASKS.get(task_id)
            start_new = False
            if task is None:
                start_new = True
            elif time.time() - task.get("created_at", 0) > REFRESH_TASK_TTL_SECONDS:
                start_new = True

            if start_new:
                task_id = _refresh_task_key(pool, prompt)
                _REFRESH_TASKS[task_id] = {
                    "status": "running",
                    "progress": "queued",
                    "error": None,
                    "result": None,
                    "created_at": time.time(),
                    "pool": pool,
                    "prompt": prompt,
                }
                thread = threading.Thread(
                    target=_run_refresh_task,
                    args=(task_id, pool, prompt),
                    daemon=True,
                )
                thread.start()

        return {
            "success": True,
            "accepted": True,
            "taskId": task_id,
            "status": "running",
            "statusUrl": f"/api/refresh-intelligence/status?taskId={task_id}",
            "pool": pool or LIVE_UNIVERSE_LABEL,
        }

    @app.get("/api/refresh-intelligence/status")
    def refresh_intelligence_status(taskId: str) -> dict[str, Any]:
        status = _refresh_task_status(taskId)
        if status is None:
            return {
                "success": False,
                "taskId": taskId,
                "status": "expired",
                "error": "Task not found or expired.",
            }
        response: dict[str, Any] = {
            "success": True,
            "taskId": taskId,
            "status": status["status"],
            "progress": status.get("progress"),
            "error": status.get("error"),
            "created_at": status.get("created_at"),
        }
        if status["status"] == "done" and status.get("result"):
            response["result"] = status["result"]
        return response

    @app.get("/api/morning-prework/status")
    def morning_prework_status() -> dict[str, Any]:
        """IST morning pre-work stamp + whether LLM is day-locked."""
        stamp = _load_morning_prework_stamp()
        snapshot = _load_last_snapshot()
        today = _ist_today()
        scheduler_started = False
        desk = {}
        try:
            from .eod_engine import scheduler as _desk_sched

            scheduler_started = bool(_desk_sched._STARTED)
            desk = _desk_sched.desk_automation_status()
        except Exception:
            scheduler_started = False
        return {
            "success": True,
            "date": today,
            "enabled": os.getenv("MARKET_PREWORK_ENABLED", "1").strip().lower()
            not in ("0", "false", "no", "off"),
            "preworkHour": int(os.getenv("MARKET_PREWORK_HOUR", "9")),
            "preworkMinute": int(os.getenv("MARKET_PREWORK_MINUTE", "45")),
            "doneToday": morning_prework_done_today(),
            "llmLockedForDate": (snapshot or {}).get("llmLockedForDate"),
            "llmLockedToday": _llm_locked_for_today(snapshot),
            "schedulerStarted": scheduler_started,
            "stamp": stamp,
            "deskAutomation": desk,
        }

    @app.get("/api/desk-automation/status")
    def desk_automation_status_route() -> dict[str, Any]:
        """Full weekday automation pipeline status."""
        try:
            from .eod_engine.scheduler import desk_automation_status

            return desk_automation_status()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/morning-prework/run")
    def morning_prework_run(force: bool = False) -> dict[str, Any]:
        """Manual morning pre-work (same path as the 09:45 IST scheduler)."""
        try:
            return run_scheduled_morning_prework(force=force)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/refresh-data-on-demand")
    async def refresh_data_on_demand(request: Request, pool: str | None = None, prompt: str | None = None):
        try:
            body: dict[str, Any] = {}
            try:
                parsed_body = await request.json()
                if isinstance(parsed_body, dict):
                    body = parsed_body
            except Exception:
                body = {}

            resolved_pool = pool or body.get("pool")
            resolved_prompt = prompt or body.get("prompt")
            refresh_ticker_news = bool(
                body.get("refreshTickerNews", body.get("refresh_ticker_news", False))
            )
            force_llm_refresh = bool(
                body.get("forceLlmRefresh", body.get("force_llm_refresh", False))
            )

            dedup_key = _ondemand_refresh_task_key(resolved_pool, resolved_prompt)
            now = time.time()
            with _REFRESH_TASK_LOCK:
                active_task_id = _ONDEMAND_ACTIVE_BY_KEY.get(dedup_key)
                task = _REFRESH_TASKS.get(active_task_id) if active_task_id else None
                start_new = True
                if task is not None:
                    status = str(task.get("status") or "running")
                    updated_at = float(task.get("updated_at") or task.get("created_at") or 0)
                    if status == "running" and (now - updated_at) <= REFRESH_TASK_RUNNING_MAX_IDLE_SECONDS:
                        start_new = False
                        task_id = active_task_id
                    elif status in ("done", "error") and (now - float(task.get("created_at") or 0)) <= REFRESH_TASK_TTL_SECONDS:
                        start_new = False
                        task_id = active_task_id

                if start_new:
                    task_id = f"ondemand-{uuid.uuid4().hex}"
                    _REFRESH_TASKS[task_id] = {
                        "status": "running",
                        "progress": "queued",
                        "error": None,
                        "result": None,
                        "created_at": now,
                        "updated_at": now,
                        "pool": resolved_pool,
                        "prompt": resolved_prompt,
                        "force_llm_refresh": force_llm_refresh,
                        "dedup_key": dedup_key,
                    }
                    _ONDEMAND_ACTIVE_BY_KEY[dedup_key] = task_id
                    thread = threading.Thread(
                        target=_run_ondemand_refresh_task,
                        args=(task_id, resolved_pool, resolved_prompt, refresh_ticker_news, force_llm_refresh),
                        daemon=True,
                    )
                    thread.start()

            _persist_refresh_tasks()

            return JSONResponse(
                status_code=202,
                content={
                    "success": True,
                    "accepted": True,
                    "taskId": task_id,
                    "status": "running",
                    "statusUrl": _ondemand_status_url(task_id),
                    "pool": resolved_pool or LIVE_UNIVERSE_LABEL,
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/refresh-data-on-demand/status")
    def refresh_data_on_demand_status(taskId: str) -> dict[str, Any]:
        status = _refresh_task_status(taskId)
        if status is None:
            return {
                "success": False,
                "taskId": taskId,
                "status": "expired",
                "error": "Task not found or expired.",
            }
        response: dict[str, Any] = {
            "success": True,
            "taskId": taskId,
            "status": status["status"],
            "progress": status.get("progress"),
            "error": status.get("error"),
            "created_at": status.get("created_at"),
        }
        if status["status"] == "done" and status.get("result"):
            response["result"] = status["result"]
        return response

    @app.post("/api/refresh-ticker-reason")
    async def refresh_ticker_reason(request: Request, ticker: str | None = None, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            body: dict[str, Any] = {}
            try:
                parsed_body = await request.json()
                if isinstance(parsed_body, dict):
                    body = parsed_body
            except Exception:
                body = {}

            resolved_ticker = str(ticker or body.get("ticker") or "").strip().upper()
            if not resolved_ticker:
                raise HTTPException(status_code=400, detail="Missing required ticker parameter.")

            resolved_pool = pool or body.get("pool")
            resolved_prompt = prompt or body.get("prompt")
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=resolved_pool, custom_prompt=resolved_prompt)

            stock_row = None
            for stock in payload.get("stocks") or []:
                if str(stock.get("ticker", "")).upper() == resolved_ticker:
                    stock_row = stock
                    break
            if stock_row is None:
                quote = (payload.get("stockQuotes") or {}).get(resolved_ticker)
                if isinstance(quote, dict) and quote:
                    stock_row = quote

            if stock_row is None:
                raise HTTPException(status_code=404, detail=f"Ticker {resolved_ticker} not found in current payload.")

            ledger_score = None
            for row in ((payload.get("terminalIntelligence") or {}).get("ledger_stocks") or []):
                if str(row.get("ticker", "")).upper() == resolved_ticker:
                    ledger_score = row.get("score")
                    break
            try:
                score = float(ledger_score if ledger_score is not None else stock_row.get("score") or 0.0)
            except Exception:
                score = 0.0

            reason = _on_demand_ticker_selection_reason(resolved_ticker, stock_row, score)

            ticker_map = payload.get("tickerIntelligenceByTicker") or {}
            ticker_report = ticker_map.get(resolved_ticker)
            if not ticker_report:
                ticker_report = build_ticker_intelligence_report(payload, resolved_ticker)

            ticker_report = dict(ticker_report)
            factor_hub = dict(ticker_report.get("active_factor_hub") or {})
            factor_hub["selection_reason"] = reason
            ticker_report["active_factor_hub"] = factor_hub
            ticker_report["focusTicker"] = resolved_ticker
            ticker_report["ticker"] = resolved_ticker

            ticker_map[resolved_ticker] = ticker_report
            payload["tickerIntelligenceByTicker"] = ticker_map

            terminal = payload.get("terminalIntelligence") or {}
            ledger = terminal.get("ledger_stocks") or []
            for row in ledger:
                if str(row.get("ticker", "")).upper() == resolved_ticker:
                    row["selection_reason"] = reason
                    break
            terminal["ledger_stocks"] = ledger
            payload["terminalIntelligence"] = terminal

            _save_last_snapshot(payload)

            return {
                "success": True,
                "ticker": resolved_ticker,
                "selectionReason": reason,
                "tickerReport": ticker_report,
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
                "selectionMeta": payload.get("selectionMeta"),
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/ticker-news")
    async def get_ticker_news(
        ticker: str,
        company: str | None = None,
        max_articles: int = 8,
        include_raw: bool = False,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        try:
            from .ai_ticker_news import ticker_news_report_is_llm_complete

            resolved_ticker = ticker.strip().upper()
            if not resolved_ticker:
                raise HTTPException(status_code=400, detail="Missing required parameter: ticker")
            capped_articles = max(1, min(int(max_articles or 8), 15))

            snapshot = _load_last_snapshot()
            ticker_news_map = (snapshot.get("tickerNewsByTicker") or {}) if snapshot else {}
            cached_report = ticker_news_map.get(resolved_ticker)

            if (
                not force_refresh
                and ticker_news_report_is_llm_complete(cached_report)
            ):
                cached_report = dict(cached_report)
                cached_report["cached"] = True
                return cached_report

            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(
                    f"{AI_NEWS_API_URL}/api/ticker-news",
                    params={
                        "ticker": resolved_ticker,
                        "company": company or "",
                        "max_articles": capped_articles,
                        "include_raw": include_raw,
                        "force_refresh": force_refresh,
                    },
                    timeout=90,
                )
                response.raise_for_status()
                report_data = response.json()

            report_data["cached"] = False

            if snapshot and ticker_news_report_is_llm_complete(report_data):
                updated_map = dict(snapshot.get("tickerNewsByTicker") or {})
                updated_map[resolved_ticker] = report_data
                snapshot = dict(snapshot)
                snapshot["tickerNewsByTicker"] = updated_map
                _save_last_snapshot(snapshot)

            return report_data
        except HTTPException:
            raise
        except Exception as exc:
            logger = logging.getLogger("angel_one_feed")
            logger.error("ticker-news fetch failed for %s: %s", ticker, exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    wire_eod_into_app(app)

    def _persist_books_on_boot() -> None:
        try:
            from .intraday_session_engine import refresh_session_state

            refresh_session_state()
        except Exception:
            logging.getLogger(__name__).exception("boot persist session JSON failed")
        try:
            from .swing_session import refresh_swing_session_state

            refresh_swing_session_state()
        except Exception:
            logging.getLogger(__name__).exception("boot persist swing session failed")

    threading.Thread(target=_persist_books_on_boot, name="desk-boot-persist", daemon=True).start()

    return app


async def _refresh_ticker_news_for_payload(payload: dict[str, Any]) -> None:
    stocks_to_refresh_news = [
        s for s in (payload.get("stocks") or []) if isinstance(s, dict) and s.get("ticker")
    ]
    if not stocks_to_refresh_news:
        return

    tickers = [s["ticker"] for s in stocks_to_refresh_news]
    companies = {
        str(s["ticker"]).upper(): str(s.get("name") or s["ticker"])
        for s in stocks_to_refresh_news
    }
    logger = logging.getLogger("angel_one_feed")
    try:
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.post(
                f"{AI_NEWS_API_URL}/api/ticker-news/batch-check",
                json={
                    "tickers": tickers,
                    "companies": companies,
                    "max_articles": 8,
                    "include_raw": False,
                },
                timeout=max(60, min(300, len(tickers) * 8)),
            )
            resp.raise_for_status()
            batch_results = resp.json().get("results") or []
            results = {
                str(item.get("ticker") or "").upper(): item
                for item in batch_results
                if isinstance(item, dict) and item.get("ticker")
            }
            ticker_news_map = {
                t.upper(): results.get(t.upper(), {}) for t in tickers
                if results.get(t.upper())
            }
            from .ai_ticker_news import ticker_news_report_is_llm_complete

            ticker_news_map = {
                t: data for t, data in ticker_news_map.items()
                if ticker_news_report_is_llm_complete(data) and data.get("ticker")
            }
            payload["tickerNewsByTicker"] = ticker_news_map
            print(
                f"INFO: Stored {len(ticker_news_map)} ticker news reports out of {len(tickers)} into snapshot."
            )
    except Exception as exc:
        print(f"WARNING: Batch ticker-news refresh failed: {exc}")


def _run_ondemand_refresh_task(
    task_id: str,
    pool_name: str | None,
    custom_prompt: str | None,
    refresh_ticker_news: bool,
    force_llm_refresh: bool = False,
) -> None:
    def update_progress(msg: str) -> None:
        _refresh_task_touch(task_id, msg)

    try:
        update_progress("Starting live market refresh...")
        client = AngelOneClient()
        payload = build_market_payload(
            client,
            pool_name=pool_name,
            force_refresh=True,
            prefer_cache=False,
            custom_prompt=custom_prompt,
            allow_fallback=True,
            force_llm_refresh=force_llm_refresh,
            on_progress=update_progress,
        )
        if not payload.get("success", False):
            _refresh_task_set_error(task_id, payload.get("error") or "Live refresh produced no payload.")
            return

        payload.setdefault("isSnapshotFallback", False)
        if payload.get("selectionMeta", {}).get("mode") != "live":
            payload["selectionMeta"] = {
                "mode": "live",
                "reason": payload.get("selectionMeta", {}).get("reason")
                or "Live refresh explicitly requested by frontend.",
                "dataDate": payload.get("selectionMeta", {}).get("dataDate") or _payload_data_date(payload),
            }

        if refresh_ticker_news:
            update_progress("Refreshing ticker news...")
            asyncio.run(_refresh_ticker_news_for_payload(payload))

        update_progress("Saving snapshot...")
        _save_last_snapshot(payload)
        _refresh_task_set_done(
            task_id,
            {
                "success": True,
                "payload": payload,
                "selectionMeta": payload.get("selectionMeta"),
                "isSnapshotFallback": False,
            },
        )
    except Exception as exc:
        _refresh_task_set_error(task_id, str(exc))


def _run_refresh_task(task_id: str, pool_name: str | None, custom_prompt: str | None) -> None:
    try:
        payload = build_market_payload(
            AngelOneClient(),
            pool_name=pool_name,
            force_refresh=True,
            custom_prompt=custom_prompt,
        )
        if not payload.get("success", False):
            _refresh_task_set_error(task_id, payload.get("error", "Market data unavailable."))
            return
        result = {
            "success": True,
            "poolStocks": len(payload.get("stocks", [])),
            "tiLedgerStocks": len((payload.get("terminalIntelligence") or {}).get("ledger_stocks", [])),
            "tiPopulated": bool(payload.get("terminalIntelligence")),
            "newsSummaryPopulated": bool(payload.get("newsSummary")),
            "selectionMeta": payload.get("selectionMeta"),
        }
        _refresh_task_set_done(task_id, result)
    except Exception as exc:
        _refresh_task_set_error(task_id, str(exc))


def _run_orchestrated_sequence(task_id: str, pool_name: str | None, custom_prompt: str | None) -> None:
    """Orchestrates the sequential dashboard update with 30s delays between sections as specified."""
    try:
        client = AngelOneClient()
        
        def update_progress(msg: str, payload: dict[str, Any]):
            with _REFRESH_TASK_LOCK:
                if task_id in _REFRESH_TASKS:
                    _REFRESH_TASKS[task_id]["progress"] = msg
            # Progressive save so frontend can reflect sections being filled
            _save_last_snapshot(payload)
            print(f"[ORCHESTRATION] {msg}")

        # 1. Immediately delete existing dashboard snapshot to start fresh
        snap_path = _snapshot_path()
        if snap_path.exists():
            snap_path.unlink()
        
        payload: dict[str, Any] = {
            "success": True,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "stocks": [],
            "stockQuotes": {},
            "macroDataStrip": {"morning": [], "evening": []},
            "globalMacro": {"indices": [], "commodities": []},
            "news": [],
            "terminalIntelligence": None,
            "isSnapshotFallback": False
        }

        # Step 1: Update GLOBAL INDICES section
        update_progress("Updating GLOBAL INDICES section...", payload)
        gm = fetch_global_macro()
        payload["globalMacro"]["indices"] = gm.get("indices", [])
        update_progress("GLOBAL INDICES updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 2: Update COMMODITIES & FX section
        update_progress("Updating COMMODITIES & FX section...", payload)
        payload["globalMacro"]["commodities"] = gm.get("commodities", [])
        payload["macroDataStrip"]["morning"].extend(fetch_domestic_yahoo_macro())
        update_progress("COMMODITIES & FX updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 3: Update NIFTY TOP 5 GAINERS & LOSERS
        update_progress("Updating NIFTY TOP 5 GAINERS & LOSERS...", payload)
        resolved_pool = pool_name or NIFTY_500_LABEL
        stock_universe, pool_label = _quote_universe(resolved_pool)
        stock_quotes_raw = client.fetch_batch_quotes(stock_universe)
        
        all_stocks = []
        for inst in stock_universe:
            if q := stock_quotes_raw.get(inst.key):
                all_stocks.append(_build_stock_row(inst, q, pool_label))
        
        # Perform intraday fetch for ranking
        candidate_rows = _coarse_pre_rank(all_stocks)[:30]
        all_metrics = _fetch_all_intraday_chunked(client, candidate_rows, {i.key: i for i in stock_universe}, _ist_now())
        
        for row in all_stocks:
            if m := all_metrics.get(row["ticker"]):
                row["intraday"] = m
        
        # ─────────────────────────────────────────────────────────────────────────
        # STAGE 1: Deterministic Quant Engine
        # Applies hard filters and computes Alpha Scores with no LLM involvement.
        # Returns top TOP_SELECTION_COUNT by Alpha Score; pads with volume leaders if needed.
        # ─────────────────────────────────────────────────────────────────────────
        update_progress("Running deterministic quant pipeline (hard filters + alpha scores)...", payload)
        top_20_quant = _compute_deterministic_pipeline(all_stocks)

        # ─────────────────────────────────────────────────────────────────────────
        # STAGE 2: LLM Safety Auditor
        # Audits ONLY non-technical risk domains using news context.
        # Attaches risk_flags + verdict to each stock; never re-ranks technically.
        # ─────────────────────────────────────────────────────────────────────────
        update_progress(f"Running LLM risk audit on top {_TI_TOP_SELECTION_COUNT} stocks...", payload)
        final_audited = _execute_llm_risk_audit(top_20_quant, payload.get("news", []))

        # Print institutional audit ledger to server log
        ledger_rows = build_audit_ledger(final_audited)
        for ledger_row in ledger_rows:
            print(f"[AUDIT] {ledger_row}")

        payload["stocks"] = final_audited
        payload["stockQuotes"] = {s["ticker"]: s for s in all_stocks}
        update_progress("NIFTY TOP 5 MOVERS updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 4: Update NIFTY 100 HEAT MAP (gradient data is now in stockQuotes)
        update_progress("Updating NIFTY 100 HEAT MAP data...", payload)
        update_progress("NIFTY 100 HEAT MAP updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 5: Update LIVE NEWS FEED
        update_progress("Updating LIVE NEWS FEED section...", payload)
        payload["news"] = fetch_live_news()
        update_progress("LIVE NEWS FEED updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 6: Update INDIA MARKETS section (TOP MOVERS, ASSET METRICS)
        update_progress("Updating INDIA MARKETS section...", payload)
        macro_raw = client.fetch_batch_quotes(list(MACRO_INSTRUMENTS))
        m, e = _build_macro_strips(macro_raw)
        payload["macroDataStrip"]["morning"].extend(m)
        payload["macroDataStrip"]["evening"].extend(e)
        payload["macroDataStrip"]["morning"].extend(fetch_domestic_index_macro())
        update_progress("INDIA MARKETS section updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 7: Update AI NEWS TERMINAL & SUMMARY
        # Check if we already have this in a valid state from a previous snapshot
        snapshot = _load_last_snapshot()
        if snapshot and snapshot.get("terminalIntelligence") and not snapshot.get("terminalIntelligence", {}).get("llmError"):
            update_progress("AI NEWS TERMINAL & SUMMARY found in cache. Reusing...", payload)
            top_rows = snapshot.get("stocks", [])
            ti_intel = snapshot.get("terminalIntelligence")
            news_summary = snapshot.get("newsSummary")
        else:
            update_progress("AI NEWS TERMINAL & SUMMARY missing or invalid. Calling LLM...", payload)
            top_rows, ti_intel, news_summary = _build_terminal_payload(
                all_stocks=final_audited,
                news_items=payload["news"],
                macro_morning=payload["macroDataStrip"]["morning"],
                macro_evening=payload["macroDataStrip"]["evening"],
                pool_name=resolved_pool,
                custom_prompt=custom_prompt
            )
            
            if not ti_intel or ti_intel.get("llmError"):
                 update_progress("AI ANALYSIS failed. Panel will remain empty for on-demand retry.", payload)
            else:
                 update_progress("AI ANALYSIS completed successfully.", payload)

        payload["terminalIntelligence"] = ti_intel
        payload["newsSummary"] = news_summary
        update_progress("AI SUMMARY updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 8: Update TERMINAL ANALYSIS section
        update_progress("Updating final TERMINAL ANALYSIS section...", payload)
        payload = _hydrate_dhan_swing_picks(payload, force=True)
        payload = _hydrate_ticker_intelligence_map(payload)
        _apply_selection_meta(
            payload, 
            mode="live", 
            reason="Sequential orchestrated refresh complete. Rendering final dashboard."
        )
        
        update_progress("Orchestrated refresh sequence complete. Dashboard fully generated.", payload)
        _refresh_task_set_done(task_id, {"success": True, "message": "Sequence finished successfully."})

        # NOTE: At this point, the backend has generated the complete dataset.
        # The 'light-themed image' rendering is handled by the frontend dashboard component
        # when it detects the 'Sequential orchestrated refresh complete' meta state.

    except Exception as exc:
        print(f"[ORCHESTRATION ERROR] {exc}")
        _refresh_task_set_error(task_id, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Angel One market feed for IROS")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--once", action="store_true", help="Fetch once and print/save JSON")
    parser.add_argument("--output", help="Write JSON snapshot to this file")
    parser.add_argument("--pool", default=None, help="Pool label. Defaults to Nifty 500; Nifty 100 and Live Universe are also supported.")
    parser.add_argument("--prompt", default=None, help="Custom filter prompt override")
    parser.add_argument("--refresh-on-demand", action="store_true", help="Force a non-fallback live refresh and write snapshot")
    parser.add_argument("--orchestrate", action="store_true", help="Run the sequential orchestrated refresh sequence")
    parser.add_argument("--audit-verdicts", action="store_true", help="Print all ticker audit verdicts (Approved/Rejected) from the latest snapshot")
    args = parser.parse_args()

    try:
        resolved = _llm_config_canonical()
        print(
            f"[LLM-DEBUG] env_path={BASE_DIR / '.env'} "
            f"LLM_PROVIDER={os.getenv('LLM_PROVIDER','')} "
            f"LLM_MODEL={os.getenv('LLM_MODEL','')} "
            f"ANGEL_PASSWORD={'set' if os.getenv('ANGEL_PASSWORD','').strip() else 'missing'} "
            f"resolved={resolved}"
        )
    except Exception as exc:
        print(f"[LLM-DEBUG] config inspect failed: {exc}")

    if args.serve:
        import uvicorn

        host = os.getenv("MARKET_API_HOST", "0.0.0.0")
        port = int(os.getenv("MARKET_API_PORT", "8000"))
        uvicorn.run(create_app(), host=host, port=port)
        return 0

    if args.orchestrate:
        print("[INFO] Starting orchestrated sequential refresh...")
        _run_orchestrated_sequence("cli_task", args.pool, args.prompt)
        return 0

    if args.audit_verdicts:
        snapshot = _load_last_snapshot()
        if not snapshot:
            print(json.dumps({"success": False, "error": "No cached snapshot available."}, indent=2))
            return 1
        verdicts = []
        for s in snapshot.get("stocks", []):
            verdicts.append({
                "ticker": s.get("ticker"),
                "name": s.get("name"),
                "alpha_score": s.get("alpha_score", 0.0),
                "verdict": s.get("verdict", "APPROVE"),
                "risk_flags": s.get("risk_flags", ["None"])
            })
        print(json.dumps({"success": True, "verdicts": verdicts}, indent=2))
        return 0

    if args.refresh_on_demand:
        client = AngelOneClient()
        payload = build_market_payload(
            client,
            pool_name=args.pool,
            force_refresh=True,
            prefer_cache=False, # Explicitly do not prefer cache for on-demand refresh
            custom_prompt=args.prompt,
            allow_fallback=False,
        )
        if not payload.get("success", False):
            raise RuntimeError(payload.get("error") or "Live refresh produced no payload.")
        payload.setdefault("isSnapshotFallback", False)
        if payload.get("selectionMeta", {}).get("mode") != "live":
            payload["selectionMeta"] = {
                "mode": "live",
                "reason": payload.get("selectionMeta", {}).get("reason") or "Live refresh explicitly requested by CLI.",
                "dataDate": payload.get("selectionMeta", {}).get("dataDate") or _payload_data_date(payload),
            }
        _save_last_snapshot(payload)
        text = json.dumps(payload, indent=2)
        print(text)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        return 0

    client = AngelOneClient()
    payload = build_market_payload(client, pool_name=args.pool, custom_prompt=args.prompt)
    text = json.dumps(payload, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
