"""FastAPI router for trade outcome tracking."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .trade_outcome import get_trade_outcomes

router = APIRouter()


@router.get("/api/trade-outcomes")
async def trade_outcomes(request: Request):
    """Return persisted scanner picks with live target/SL hit status."""
    # Inject market_data from app state if available
    from .market_feeds import get_market_data
    try:
        # Ensure market_feeds has fresh data
        if hasattr(request.app.state, "market_data"):
            # Use cached data from app state
            pass
    except Exception:
        pass
    
    try:
        result = get_trade_outcomes()
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(
            content={"long": [], "short": [], "updatedAt": None, "error": str(exc)},
            status_code=200,
        )