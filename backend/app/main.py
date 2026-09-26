"""
IROS Trade API - FastAPI Application Entry Point
=================================================
Serves the IROS terminal backend API.
Routes are defined in services/angel_one_feed.py via create_app().

Run with:  python -m uvicorn app.main:app --reload
"""

import json
import os
import sys
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

from app.services.shared_state import (
    get_event_bus,
    get_market_state,
    get_persistence_worker,
    get_view_store,
    hydrate_from_sqlite,
    init_shared_state,
)
from app.services.angel_one_feed import AngelOneClient, create_app
from app.services.angel_index_options import _float
from app.services.index_options_hunt_supervisor import (
    index_options_hunt_status,
    start_index_options_hunt_supervisor,
)
from app.services.index_options_paper_supervisor import (
    paper_supervisor_status,
    start_paper_supervisor,
)


def _load_env(path: Path) -> None:
    for enc in ("utf-8", "cp1252"):
        try:
            load_dotenv(path, encoding=enc)
            return
        except UnicodeDecodeError:
            continue
        except Exception:
            raise


_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    _load_env(_env_path)

app = create_app()
_shared = init_shared_state()
hydrate_from_sqlite()

_SNAPSHOT_ROUTER = APIRouter()


@_SNAPSHOT_ROUTER.get("/api/live/summary")
def live_summary() -> dict[str, Any]:
    view_store = get_view_store()
    market_state = get_market_state()
    market = market_state.get_metrics()
    market["feed_status"] = market_state.get_feed_status().value
    return {
        "version": int(time.time() * 1000),
        "asOf": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "intraday": _namespace_summary("intraday"),
        "swing": _namespace_summary("swing"),
        "indexOptions": _namespace_summary("index_options"),
        "eod": _namespace_summary("eod"),
    }


def _namespace_summary(namespace: str) -> dict[str, Any]:
    view = get_view_store().get(namespace)
    if not view:
        return {"version": 0, "updatedAt": None, "available": False}
    payload = view.get("payload") or {}
    compact = {
        "success": payload.get("success"),
        "updatedAt": view.get("updatedAt"),
        "version": view.get("version", 0),
    }
    if namespace == "index_options":
        compact["selectedCount"] = len(payload.get("selected") or [])
        compact["sellerCount"] = len(payload.get("sellerCandidates") or [])
        compact["sessionStatus"] = payload.get("sessionStatus")
        compact["huntActive"] = payload.get("huntActive")
        compact["limits"] = payload.get("limits")
    elif namespace in {"intraday", "swing"}:
        compact["locked"] = payload.get("locked")
        compact["counts"] = payload.get("counts")
    elif namespace == "eod":
        compact["date"] = payload.get("date") or payload.get("analysis_date")
        compact["status"] = payload.get("status")
    return compact


@_SNAPSHOT_ROUTER.get("/api/stream")
async def sse_stream(request: Request) -> StreamingResponse:
    from app.services.shared_state.schemas import EventType

    bus = get_event_bus()
    queue: Queue[str] = Queue(maxsize=512)
    disconnected = False

    def _on_event(event: Any) -> None:
        if disconnected:
            return
        try:
            data = json.dumps({
                "type": event.type.value,
                "timestamp": event.timestamp,
                "payload": event.payload,
            })
            try:
                queue.put_nowait(f"data: {data}\n\n")
            except Exception:
                pass
        except Exception:
            pass

    subscriptions = []
    for ev in (
        EventType.MARKET_QUOTE,
        EventType.INTRADAY_STATE_CHANGED,
        EventType.SWING_STATE_CHANGED,
        EventType.INDEX_OPTIONS_STATE_CHANGED,
        EventType.TRADE_EVENT,
        EventType.EOD_READY,
        EventType.HEALTH_CHANGED,
    ):
        bus.subscribe(ev, _on_event)
        subscriptions.append(ev)

    async def _gen():
        nonlocal disconnected
        try:
            yield b": heartbeat\n\n"
            last_heartbeat = time.monotonic()
            while not disconnected:
                if await request.is_disconnected():
                    break
                try:
                    msg = queue.get(timeout=0.5)
                    yield msg.encode()
                except Exception:
                    pass
                now = time.monotonic()
                if now - last_heartbeat >= 15.0:
                    yield b": heartbeat\n\n"
                    last_heartbeat = now
        finally:
            disconnected = True
            for ev in subscriptions:
                try:
                    bus._subscribers.get(ev, []).remove(_on_event)
                except ValueError:
                    pass

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


app.include_router(_SNAPSHOT_ROUTER)

start_paper_supervisor(AngelOneClient)
start_index_options_hunt_supervisor(AngelOneClient)


def _start_intraday_stream() -> bool:
    if os.getenv("INTRADAY_WS_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
        return False
    try:
        from app.services.intraday_market_state import get_intraday_stream
        global INTRADAY_CLIENT
        INTRADAY_CLIENT = AngelOneClient()
        return bool(get_intraday_stream().ensure(INTRADAY_CLIENT))
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "intraday live stream failed to start; REST recovery path remains active"
        )
        return False


INTRADAY_CLIENT: AngelOneClient | None = None
INTRADAY_STREAM_STARTED = _start_intraday_stream()

STANDBY_FEED_STARTED = False
try:
    from app.services.standby_feed.client import start_standby_feed
    STANDBY_FEED_STARTED = start_standby_feed()
except Exception:
    import logging as _logging_standby
    _logging_standby.getLogger(__name__).exception(
        "shoonya standby feed failed to start; primary (Angel) path is unaffected"
    )

INTRADAY_RECOVERY_STARTED = False
try:
    if os.getenv("INTRADAY_WS_ENABLED", "1").strip().lower() not in {"0", "false", "no"}:
        from app.services.intraday_market_state import start_intraday_recovery_worker
        if INTRADAY_CLIENT is not None:
            start_intraday_recovery_worker(INTRADAY_CLIENT)
        INTRADAY_RECOVERY_STARTED = True
except Exception:
    import logging as _logging
    _logging.getLogger(__name__).exception("intraday recovery worker failed to start")


@app.get("/api/index-options/paper-supervisor")
def index_options_paper_supervisor_status() -> dict:
    return {"success": True, "supervisor": paper_supervisor_status()}


@app.get("/api/index-options/hunt-supervisor")
def index_options_hunt_supervisor_status() -> dict:
    return {"success": True, "supervisor": index_options_hunt_status()}


@app.get("/api/diagnostics/angel-circuit-state")
def angel_circuit_state() -> dict[str, Any]:
    try:
        from app.services.angel_one_feed import (
            _ANGEL_CANDLE_CIRCUIT_UNTIL,
            _CANDLE_COOLDOWN_UNTIL_MONO,
            _CANDLE_LAST_CALL_MONO,
            ANGEL_CANDLE_CIRCUIT_SECONDS,
            _angel_candle_calls_allowed,
        )
        now = time.monotonic()
        circuit_remaining = max(0.0, _ANGEL_CANDLE_CIRCUIT_UNTIL - now)
        cooldown_remaining = max(0.0, _CANDLE_COOLDOWN_UNTIL_MONO - now)
        last_call_age = max(0.0, now - _CANDLE_LAST_CALL_MONO)
        return {
            "success": True,
            "circuitOpen": circuit_remaining > 0,
            "circuitRemainingSeconds": round(circuit_remaining, 2),
            "cooldownRemainingSeconds": round(cooldown_remaining, 2),
            "lastCandleCallAgeSeconds": round(last_call_age, 2),
            "callsAllowed": _angel_candle_calls_allowed(),
            "configuredCircuitSeconds": ANGEL_CANDLE_CIRCUIT_SECONDS,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/diagnostics/angel-option-chain")
def angel_option_chain_diagnostic() -> dict[str, Any]:
    try:
        from app.services.angel_index_options import fetch_angel_index_option_snapshot
        from app.services.angel_one_feed import AngelOneClient
        client = AngelOneClient()
        snapshot = fetch_angel_index_option_snapshot(client)
        indices = snapshot.get("indices") or {}
        results = {}
        for key, payload in indices.items():
            chain = payload.get("chain") or []
            results[key] = {
                "source": payload.get("source"),
                "status": payload.get("status"),
                "error": payload.get("error"),
                "spot": payload.get("spot"),
                "expiry": payload.get("expiry"),
                "chainContracts": len(chain),
                "hasDepth": any(
                    _float(row.get("bestBid")) is not None and _float(row.get("bestAsk")) is not None
                    for row in chain if isinstance(row, dict)
                ),
                "hasGreeks": any(
                    _float(row.get("delta")) is not None for row in chain if isinstance(row, dict)
                ),
                "componentFreshness": payload.get("componentFreshness") or {},
            }
        return {"success": True, "fetchedAt": snapshot.get("fetchedAt"), "indices": results}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/api/eod/warm-caches")
def eod_warm_caches(date: str | None = None) -> dict[str, Any]:
    try:
        from datetime import date as _date
        from app.services.eod_book_cache import warm_book_caches
        for_date = _date.fromisoformat(date) if date else datetime.now(tz=timezone.utc).date()
        result = warm_book_caches(for_date)
        return {"success": True, "date": for_date.isoformat(), "warmResult": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


if __name__ == "__main__":
    host = os.getenv("MARKET_API_HOST", "0.0.0.0")
    port = int(os.getenv("MARKET_API_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
