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

# Load environment variables from backend/.env
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

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