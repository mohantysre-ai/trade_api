"""Provider-independent NSE equity registry and bulk quote failover.

Dhan is preferred because one quote request supports the complete Nifty 500.
Angel remains the fallback for symbols Dhan does not return.  The module is
deliberately fail-closed: callers receive explicit coverage metadata and decide
whether the universe is complete enough to publish.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

import requests

log = logging.getLogger(__name__)

DHAN_SCRIP_MASTER_URL = os.getenv(
    "DHAN_SCRIP_MASTER_URL",
    "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",
)
DHAN_QUOTE_URL = os.getenv(
    "DHAN_QUOTE_URL", "https://api.dhan.co/v2/marketfeed/quote"
)
DHAN_DAILY_URL = os.getenv("DHAN_DAILY_URL", "https://api.dhan.co/v2/charts/historical")
DHAN_INTRADAY_URL = os.getenv("DHAN_INTRADAY_URL", "https://api.dhan.co/v2/charts/intraday")
DHAN_MASTER_TTL_SECONDS = int(os.getenv("DHAN_MASTER_TTL_SECONDS", "86400"))
MARKET_DATA_MIN_COVERAGE_PCT = float(os.getenv("MARKET_DATA_MIN_COVERAGE_PCT", "99"))

_MASTER_LOCK = threading.Lock()
_DHAN_IDS: dict[str, str] = {}
_DHAN_MASTER_LOADED_AT = 0.0
_DHAN_HISTORY_LOCK = threading.Lock()
_DHAN_HISTORY_LAST_CALL = 0.0


def _norm(value: Any) -> str:
    text = str(value or "").upper().strip()
    for suffix in ("-EQ", "-BE", "-BZ"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.replace(" ", "")


def _first(row: dict[str, Any], *names: str) -> str:
    upper = {str(k).upper(): v for k, v in row.items()}
    for name in names:
        value = upper.get(name.upper())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def load_dhan_security_ids(force: bool = False) -> dict[str, str]:
    """Return NSE cash symbol -> Dhan security id from the official master."""
    global _DHAN_IDS, _DHAN_MASTER_LOADED_AT
    now = time.time()
    if not force and _DHAN_IDS and now - _DHAN_MASTER_LOADED_AT < DHAN_MASTER_TTL_SECONDS:
        return dict(_DHAN_IDS)

    with _MASTER_LOCK:
        if not force and _DHAN_IDS and now - _DHAN_MASTER_LOADED_AT < DHAN_MASTER_TTL_SECONDS:
            return dict(_DHAN_IDS)
        try:
            response = requests.get(DHAN_SCRIP_MASTER_URL, timeout=(10, 90))
            response.raise_for_status()
            rows = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
            mapped: dict[str, str] = {}
            for row in rows:
                exchange = _first(row, "SEM_EXM_EXCH_ID", "EXCH_ID", "EXCHANGE")
                instrument = _first(row, "SEM_INSTRUMENT_NAME", "INSTRUMENT")
                if exchange.upper() != "NSE":
                    continue
                if instrument and instrument.upper() not in {"EQUITY", "EQ"}:
                    continue
                symbol = _norm(_first(row, "SEM_TRADING_SYMBOL", "TRADING_SYMBOL", "SYMBOL"))
                security_id = _first(row, "SEM_SMST_SECURITY_ID", "SECURITY_ID")
                if symbol and security_id:
                    mapped[symbol] = security_id
            if mapped:
                _DHAN_IDS = mapped
                _DHAN_MASTER_LOADED_AT = now
            else:
                log.error("Dhan scrip master contained no NSE equity mappings")
        except Exception as exc:
            log.warning("Dhan scrip master fetch failed: %s", exc)
        return dict(_DHAN_IDS)


def dhan_configured() -> bool:
    return bool(os.getenv("DHAN_CLIENT_ID") and os.getenv("DHAN_ACCESS_TOKEN"))


def _dhan_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "client-id": str(os.environ["DHAN_CLIENT_ID"]),
        "access-token": str(os.environ["DHAN_ACCESS_TOKEN"]),
    }


def _dhan_history_slot() -> None:
    """Keep chart requests below Dhan's documented data-API rate."""
    global _DHAN_HISTORY_LAST_CALL
    with _DHAN_HISTORY_LOCK:
        wait = 0.22 - (time.monotonic() - _DHAN_HISTORY_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _DHAN_HISTORY_LAST_CALL = time.monotonic()


def fetch_dhan_candles(
    security_id: str,
    interval: str,
    fromdate: datetime,
    todate: datetime,
) -> list[list[Any]]:
    """Return Dhan chart arrays in the candle row shape used by the screener."""
    if not dhan_configured() or not security_id:
        return []
    intraday = interval != "ONE_DAY"
    interval_map = {
        "ONE_MINUTE": "1",
        "FIVE_MINUTE": "5",
        "FIFTEEN_MINUTE": "15",
        "THIRTY_MINUTE": "25",
        "ONE_HOUR": "60",
    }
    if intraday and interval not in interval_map:
        return []
    body: dict[str, Any] = {
        "securityId": str(security_id),
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "oi": False,
    }
    if intraday:
        body.update(
            interval=interval_map[interval],
            fromDate=fromdate.strftime("%Y-%m-%d %H:%M:%S"),
            toDate=todate.strftime("%Y-%m-%d %H:%M:%S"),
        )
        url = DHAN_INTRADAY_URL
    else:
        # Dhan's daily toDate is non-inclusive.
        body.update(
            fromDate=fromdate.strftime("%Y-%m-%d"),
            toDate=(todate + timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        url = DHAN_DAILY_URL
    _dhan_history_slot()
    response = requests.post(url, headers=_dhan_headers(), json=body, timeout=(10, 30))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return []
    arrays = [payload.get(name, []) for name in ("timestamp", "open", "high", "low", "close", "volume")]
    if not all(isinstance(values, list) for values in arrays):
        return []
    return [list(row) for row in zip(*arrays)]


def _dhan_quote_to_canonical(raw: dict[str, Any]) -> dict[str, Any] | None:
    ohlc = raw.get("ohlc") if isinstance(raw.get("ohlc"), dict) else {}
    ltp = raw.get("last_price") if raw.get("last_price") is not None else raw.get("ltp")
    if ltp in (None, ""):
        return None
    return {
        "ltp": ltp,
        "open": ohlc.get("open", raw.get("open")),
        "high": ohlc.get("high", raw.get("high")),
        "low": ohlc.get("low", raw.get("low")),
        "close": ohlc.get("close", raw.get("close")),
        "tradeVolume": raw.get("volume", raw.get("trade_volume", 0)),
        "opnInterest": raw.get("oi", 0),
        "previousOI": raw.get("previous_oi", raw.get("prev_oi", 0)),
        "quoteProvider": "dhan",
    }


def fetch_dhan_bulk_quotes(symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Fetch up to the complete Nifty 500 in one Dhan quote request."""
    if not dhan_configured():
        return {}
    ids = load_dhan_security_ids()
    wanted = {_norm(symbol): ids.get(_norm(symbol)) for symbol in symbols}
    reverse = {security_id: symbol for symbol, security_id in wanted.items() if security_id}
    if not reverse:
        return {}
    response = requests.post(
        DHAN_QUOTE_URL,
        headers=_dhan_headers(),
        json={"NSE_EQ": list(reverse)},
        timeout=(10, 30),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else {}
    segment = data.get("NSE_EQ", {}) if isinstance(data, dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for security_id, raw in segment.items():
        if not isinstance(raw, dict):
            continue
        symbol = reverse.get(str(security_id))
        quote = _dhan_quote_to_canonical(raw)
        if symbol and quote:
            out[symbol] = quote
    return out


@dataclass(frozen=True)
class QuoteCoverage:
    expected: int
    received: int
    coverage_pct: float
    selection_allowed: bool
    providers: dict[str, int]
    missing_symbols: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "received": self.received,
            "coveragePct": self.coverage_pct,
            "selectionAllowed": self.selection_allowed,
            "providers": self.providers,
            "missingSymbols": self.missing_symbols,
        }


def fetch_quotes_with_failover(
    symbols: Iterable[str],
    angel_fetch: Callable[[list[str]], dict[str, dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], QuoteCoverage]:
    """Dhan primary; fetch only missing symbols from Angel."""
    ordered = list(dict.fromkeys(_norm(s) for s in symbols if _norm(s)))
    quotes: dict[str, dict[str, Any]] = {}
    providers = {"dhan": 0, "angel": 0}
    try:
        quotes.update(fetch_dhan_bulk_quotes(ordered))
        providers["dhan"] = len(quotes)
    except Exception as exc:
        log.warning("Dhan bulk quote failed; using Angel fallback: %s", exc)

    missing = [symbol for symbol in ordered if symbol not in quotes]
    if missing:
        try:
            angel = angel_fetch(missing)
            for symbol, quote in angel.items():
                if symbol not in quotes and isinstance(quote, dict):
                    quote = dict(quote)
                    quote.setdefault("quoteProvider", "angel")
                    quotes[symbol] = quote
                    providers["angel"] += 1
        except Exception as exc:
            log.warning("Angel quote fallback failed: %s", exc)

    missing = [symbol for symbol in ordered if symbol not in quotes]
    expected = len(ordered)
    coverage_pct = round((len(quotes) / expected * 100.0) if expected else 0.0, 2)
    coverage = QuoteCoverage(
        expected=expected,
        received=len(quotes),
        coverage_pct=coverage_pct,
        selection_allowed=bool(expected and coverage_pct >= MARKET_DATA_MIN_COVERAGE_PCT),
        providers=providers,
        missing_symbols=missing,
    )
    return quotes, coverage
