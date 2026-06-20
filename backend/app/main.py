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
from app.services.angel_one_feed import create_app

app = create_app()


if __name__ == "__main__":
    host = os.getenv("MARKET_API_HOST", "0.0.0.0")
    port = int(os.getenv("MARKET_API_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=True)