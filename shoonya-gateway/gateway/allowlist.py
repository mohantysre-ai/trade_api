"""Hard allowlist: this gateway is market-data only."""
from __future__ import annotations

ALLOWED_REST_PATHS = frozenset(
    {
        "/NorenWClientAPI/GetQuotes",
        "/NorenWClientAPI/TPSeries",
        "/NorenWClientAPI/SearchScrip",
        "/NSE_symbols.txt.zip",
    }
)

FORBIDDEN_FRAGMENTS = (
    "PlaceOrder",
    "ModifyOrder",
    "CancelOrder",
    "ExitOrder",
    "OrderBook",
    "TradeBook",
    "PositionBook",
    "Holdings",
    "Limits",
    "GTT",
    "ProductConversion",
    "SingleOrdHist",
)


class EndpointNotAllowed(RuntimeError):
    pass


def assert_allowed(path: str) -> str:
    if path not in ALLOWED_REST_PATHS:
        raise EndpointNotAllowed(f"endpoint not allowlisted: {path}")
    return path
