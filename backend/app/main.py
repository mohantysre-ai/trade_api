"""
IROS Trade API - FastAPI Application Entry Point
=================================================
Serves the IROS terminal backend API.
Routes are defined in services/angel_one_feed.py via create_app().

Run with:  python -m uvicorn app.main:app --reload
"""

import os
import sys
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

def _load_env(path: Path) -> None:
    for enc in ("utf-8", "cp1252"):
        try:
            load_dotenv(path, encoding=enc)
            return
        except UnicodeDecodeError:
            continue
        except Exception:
            raise

# Load environment variables from backend/.env
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    _load_env(_env_path)

# Import the create_app function from the market feed service
# which registers all API routes (market-data, news, intelligence, refresh, etc.)
from app.services.angel_one_feed import AngelOneClient, create_app
from app.services.index_options_hunt_supervisor import (
    index_options_hunt_status,
    start_index_options_hunt_supervisor,
)
from app.services.index_options_paper_supervisor import (
    paper_supervisor_status,
    start_paper_supervisor,
)

app = create_app()

# Position safety: mark already-locked index-option paper positions every minute,
# independent of any dashboard/browser.
start_paper_supervisor(AngelOneClient)

# Candidate discovery: run the existing index-options BUY/SELL radar every minute.
# This supervisor contains no trading rules; compose_live_index_options_radar remains
# the single source of truth for scores, gates, selection, entry and risk controls.
start_index_options_hunt_supervisor(AngelOneClient)


def _start_intraday_stream() -> bool:
    """Start the process-wide Intraday WS live state (all 750 -> WebSocket).

    Async startup: REST bootstrap/recovery continues in the background and the
    API never blocks on 750-symbol hydration (spec V5 §30). Disabled cleanly
    when the env opt-out is set or the client/credentials are unavailable.
    """
    if os.getenv("INTRADAY_WS_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
        return False
    try:
        from app.services.intraday_market_state import get_intraday_stream

        return bool(get_intraday_stream().ensure(AngelOneClient))
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "intraday live stream failed to start; REST recovery path remains active"
        )
        return False


INTRADAY_STREAM_STARTED = _start_intraday_stream()

# REST becomes an exceptional/recovery path: targeted recovery for symbols the
# WS stream left stale (bounded batches, existing limiter), never a heartbeat.
INTRADAY_RECOVERY_STARTED = False
try:
    if os.getenv("INTRADAY_WS_ENABLED", "1").strip().lower() not in {"0", "false", "no"}:
        from app.services.intraday_market_state import start_intraday_recovery_worker

        start_intraday_recovery_worker(AngelOneClient)
        INTRADAY_RECOVERY_STARTED = True
except Exception:
    import logging as _logging

    _logging.getLogger(__name__).exception("intraday recovery worker failed to start")


@app.get("/api/index-options/paper-supervisor")
def index_options_paper_supervisor_status() -> dict:
    """Read-only operational health for the autonomous paper-position marker."""
    return {"success": True, "supervisor": paper_supervisor_status()}


@app.get("/api/index-options/hunt-supervisor")
def index_options_hunt_supervisor_status() -> dict:
    """Read-only health for autonomous BUY/SELL index-option discovery."""
    return {"success": True, "supervisor": index_options_hunt_status()}


if __name__ == "__main__":
    host = os.getenv("MARKET_API_HOST", "0.0.0.0")
    port = int(os.getenv("MARKET_API_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=True)