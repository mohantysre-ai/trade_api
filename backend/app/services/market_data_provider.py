"""Provider-independent NSE equity registry and bulk quote failover.

The official NSE Nifty 500 index payload is the primary quote source. Angel is
used only for symbols NSE does not return. Dhan is limited to instrument-id and
historical-candle recovery. NSE charting supplies public daily (and T-1
intraday) OHLCV without broker credentials. The module is deliberately
fail-closed.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)

DHAN_SCRIP_MASTER_URL = os.getenv(
    "DHAN_SCRIP_MASTER_URL",
    # The compact master contains SEM_TRADING_SYMBOL; the newer detailed file
    # contains company display names instead and cannot reliably map NSE tickers.
    "https://images.dhan.co/api-data/api-scrip-master.csv",
)
DHAN_SCANX_URL = os.getenv(
    "DHAN_SCANX_URL", "https://ow-scanx-analytics.dhan.co/customscan/fetchdt"
)
NSE_EQUITY_STOCK_INDICES_URL = os.getenv(
    "NSE_EQUITY_STOCK_INDICES_URL",
    "https://www.nseindia.com/api/equity-stock-indices?index=NIFTY%20500",
)
DHAN_DAILY_URL = os.getenv("DHAN_DAILY_URL", "https://api.dhan.co/v2/charts/historical")
DHAN_INTRADAY_URL = os.getenv("DHAN_INTRADAY_URL", "https://api.dhan.co/v2/charts/intraday")
DHAN_MASTER_TTL_SECONDS = int(os.getenv("DHAN_MASTER_TTL_SECONDS", "86400"))
NSE_CHARTING_BASE_URL = os.getenv("NSE_CHARTING_BASE_URL", "https://charting.nseindia.com")
NSE_CHARTING_HISTORY_URL = os.getenv(
    "NSE_CHARTING_HISTORY_URL",
    f"{NSE_CHARTING_BASE_URL.rstrip('/')}/v1/charts/symbolHistoricalData",
)
NSE_CANDLE_MIN_INTERVAL_SECONDS = float(os.getenv("NSE_CANDLE_MIN_INTERVAL_SECONDS", "0.15"))
NSE_CANDLE_CIRCUIT_SECONDS = float(os.getenv("NSE_CANDLE_CIRCUIT_SECONDS", "60"))
MARKET_DATA_MIN_COVERAGE_PCT = float(os.getenv("MARKET_DATA_MIN_COVERAGE_PCT", "99"))
_IST_ZONE = ZoneInfo("Asia/Kolkata")

_MASTER_LOCK = threading.Lock()
_DHAN_IDS: dict[str, str] = {}
_DHAN_MASTER_LOADED_AT = 0.0
_DHAN_HISTORY_LOCK = threading.Lock()
_DHAN_HISTORY_LAST_CALL = 0.0
_NSE_CHART_LOCK = threading.Lock()
_NSE_CHART_SESSION: requests.Session | None = None
_NSE_CHART_LAST_CALL = 0.0
_NSE_CANDLE_CIRCUIT_UNTIL = 0.0
_NSE_CHART_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{NSE_CHARTING_BASE_URL.rstrip('/')}/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}
_NSE_INTERVAL = {
    "ONE_DAY": ("D", "1"),
    "ONE_MINUTE": ("I", "1"),
    "FIVE_MINUTE": ("I", "5"),
    "FIFTEEN_MINUTE": ("I", "15"),
    "THIRTY_MINUTE": ("I", "30"),
    "ONE_HOUR": ("I", "60"),
}


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


def _as_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_IST_ZONE)
    return value.astimezone(_IST_ZONE)


def _nse_candle_calls_allowed() -> bool:
    return time.monotonic() >= _NSE_CANDLE_CIRCUIT_UNTIL


def _trip_nse_candle_circuit(seconds: float | None = None) -> None:
    global _NSE_CANDLE_CIRCUIT_UNTIL, _NSE_CHART_SESSION
    hold = NSE_CANDLE_CIRCUIT_SECONDS if seconds is None else float(seconds)
    _NSE_CANDLE_CIRCUIT_UNTIL = max(_NSE_CANDLE_CIRCUIT_UNTIL, time.monotonic() + max(1.0, hold))
    _NSE_CHART_SESSION = None
    log.warning("NSE charting circuit open for %.0fs", hold)


def _nse_history_slot() -> None:
    global _NSE_CHART_LAST_CALL
    with _NSE_CHART_LOCK:
        wait = NSE_CANDLE_MIN_INTERVAL_SECONDS - (time.monotonic() - _NSE_CHART_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _NSE_CHART_LAST_CALL = time.monotonic()


def _nse_chart_session() -> requests.Session:
    global _NSE_CHART_SESSION
    with _NSE_CHART_LOCK:
        if _NSE_CHART_SESSION is None:
            session = requests.Session()
            session.headers.update(_NSE_CHART_HEADERS)
            session.get(f"{NSE_CHARTING_BASE_URL.rstrip('/')}/", timeout=(5, 15))
            _NSE_CHART_SESSION = session
        return _NSE_CHART_SESSION


def _nse_bar_dt(ms: Any) -> datetime:
    """Charting `time` is IST wall-clock stored as UTC epoch milliseconds."""
    raw = datetime.fromtimestamp(float(ms) / 1000.0, timezone.utc)
    return raw.replace(tzinfo=_IST_ZONE)


def _nse_chart_get(params: dict[str, Any]) -> dict[str, Any] | None:
    if not _nse_candle_calls_allowed():
        return None
    _nse_history_slot()
    try:
        response = _nse_chart_session().get(
            NSE_CHARTING_HISTORY_URL, params=params, timeout=(8, 20)
        )
    except Exception as exc:
        log.warning("NSE charting request failed: %s", exc)
        return None
    if response.status_code in {401, 403, 429, 503}:
        _trip_nse_candle_circuit()
        log.warning("NSE charting HTTP %s", response.status_code)
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def fetch_nse_candles(
    symbol: str,
    token: str,
    interval: str,
    fromdate: datetime,
    todate: datetime,
) -> list[list[Any]]:
    """Return NSE charting OHLCV in the candle row shape used by the screener.

    Daily bars work during the session. Intraday 1m/5m is typically T-1 while
    the market is open — empty today is expected, not an error.
    """
    mapped = _NSE_INTERVAL.get(interval)
    if not mapped or not token:
        return []
    chart_type, time_interval = mapped
    start = _as_ist(fromdate)
    end = _as_ist(todate)
    payload = _nse_chart_get(
        {
            "fromDate": int(start.timestamp()),
            "toDate": int(end.timestamp()),
            "symbol": f"{_norm(symbol)}-EQ",
            "token": str(token),
            "symbolType": "Equity",
            "chartType": chart_type,
            "timeInterval": time_interval,
        }
    )
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            bar_dt = _nse_bar_dt(row.get("time"))
            open_ = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
            volume = float(row.get("volume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if interval != "ONE_DAY" and (bar_dt < start or bar_dt > end):
            continue
        out.append(
            [bar_dt.strftime("%Y-%m-%d %H:%M:%S"), open_, high, low, close, volume]
        )
    out.sort(key=lambda item: item[0])
    return out


def _nse_quote_to_canonical(raw: dict[str, Any]) -> dict[str, Any] | None:
    ltp = raw.get("lastPrice")
    if ltp in (None, "", "-"):
        return None
    return {
        "ltp": ltp,
        "open": raw.get("open"),
        "high": raw.get("dayHigh"),
        "low": raw.get("dayLow"),
        "close": raw.get("previousClose"),
        "tradeVolume": raw.get("totalTradedVolume", 0),
        "totalTradedValue": raw.get("totalTradedValue", 0),
        "percentChange": raw.get("pChange"),
        "quoteProvider": "nse",
    }


def _dhan_quote_to_canonical(raw: dict[str, Any]) -> dict[str, Any] | None:
    ltp = raw.get("Ltp") if raw.get("Ltp") is not None else raw.get("last_price")
    if ltp in (None, ""):
        return None
    change = raw.get("Pchange")
    try:
        previous_close = float(ltp) - float(change)
    except (TypeError, ValueError):
        previous_close = None
    return {
        "ltp": ltp,
        "open": None,
        "high": None,
        "low": None,
        "close": previous_close,
        "tradeVolume": raw.get("Volume", 0),
        "percentChange": raw.get("PPerchange"),
        "securityId": str(raw.get("Sid") or ""),
        "quoteProvider": "dhan_scanx",
    }


def fetch_nse500_quotes(symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Fetch the official NSE Nifty 500 snapshot used by the heat map."""
    wanted = {_norm(symbol) for symbol in symbols if _norm(symbol)}
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/market-data/live-equity-market",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    }
    session = requests.Session()
    session.get("https://www.nseindia.com/", headers=headers, timeout=(5, 15))
    response = session.get(
        NSE_EQUITY_STOCK_INDICES_URL, headers=headers, timeout=(10, 30)
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    out: dict[str, dict[str, Any]] = {}
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            continue
        symbol = _norm(raw.get("symbol"))
        quote = _nse_quote_to_canonical(raw)
        if symbol in wanted and quote:
            out[symbol] = quote
    return out


def fetch_dhan_bulk_quotes(symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Fetch NSE-missing quotes from Dhan ScanX without broker authentication."""
    ids = load_dhan_security_ids()
    wanted = {_norm(symbol): ids.get(_norm(symbol)) for symbol in symbols}
    reverse = {security_id: symbol for symbol, security_id in wanted.items() if security_id}
    if not reverse:
        return {}
    headers = {
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://dhan.co",
        "Referer": "https://dhan.co/",
    }
    out: dict[str, dict[str, Any]] = {}
    page = 1
    total_pages = 1
    while page <= total_pages and page <= 20 and len(out) < len(reverse):
        body = {
            "data": {
                "sort": "Volume",
                "sorder": "desc",
                "count": 1000,
                "pgno": page,
                "params": [
                    {"field": "Seg", "op": "", "val": "E"},
                    {"field": "Exch", "op": "", "val": "NSE"},
                ],
                "fields": ["Isin", "DispSym", "Sid", "Ltp", "Volume", "Pchange", "PPerchange"],
            }
        }
        response = requests.post(
            DHAN_SCANX_URL, headers=headers, json=body, timeout=(10, 30)
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise RuntimeError(f"Dhan ScanX error: {payload}")
        try:
            total_pages = max(1, int(payload.get("tot_pg") or 1))
        except (TypeError, ValueError):
            total_pages = 1
        for raw in payload.get("data", []):
            if not isinstance(raw, dict):
                continue
            symbol = reverse.get(str(raw.get("Sid") or ""))
            quote = _dhan_quote_to_canonical(raw)
            if symbol and quote:
                out[symbol] = quote
        page += 1
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
    """NSE primary, Dhan missing-symbol fallback, then Angel final fallback."""
    ordered = list(dict.fromkeys(_norm(s) for s in symbols if _norm(s)))
    quotes: dict[str, dict[str, Any]] = {}
    providers = {"nse": 0, "dhan": 0, "angel": 0}
    try:
        quotes.update(fetch_nse500_quotes(ordered))
        providers["nse"] = len(quotes)
    except Exception as exc:
        log.warning("NSE Nifty 500 quote fetch failed; using Dhan fallback: %s", exc)

    missing = [symbol for symbol in ordered if symbol not in quotes]
    if missing:
        try:
            dhan = fetch_dhan_bulk_quotes(missing)
            for symbol, quote in dhan.items():
                if symbol not in quotes and isinstance(quote, dict):
                    quotes[symbol] = quote
                    providers["dhan"] += 1
        except Exception as exc:
            log.warning("Dhan bulk quote fallback failed; using Angel: %s", exc)

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
