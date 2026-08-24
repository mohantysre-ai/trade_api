"""Angel One option-chain ingestion for the deterministic index-options radar."""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..utils.symbols import Instrument
from .json_atomic import atomic_write_json, load_json_with_fallback
from .market_snapshot_store import market_snapshot_path

IST_ZONE = ZoneInfo("Asia/Kolkata")

SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
INDEXES: tuple[dict[str, Any], ...] = (
    {"key": "NIFTY", "name": "NIFTY", "exchange": "NSE", "spotToken": "99926000", "spotSymbol": "Nifty 50", "segment": "NFO"},
    {"key": "BANKNIFTY", "name": "BANKNIFTY", "exchange": "NSE", "spotToken": "99926009", "spotSymbol": "Nifty Bank", "segment": "NFO"},
    {"key": "FINNIFTY", "name": "FINNIFTY", "exchange": "NSE", "spotToken": "99926037", "spotSymbol": "Nifty Fin Service", "segment": "NFO"},
    {"key": "SENSEX", "name": "SENSEX", "exchange": "BSE", "spotToken": "99919000", "spotSymbol": "SENSEX", "segment": "BFO"},
)

_MASTER_LOCK = threading.Lock()
_MASTER_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])
_OPTION_LOCK = threading.Lock()
_OI_BASELINE_LOCK = threading.Lock()
_OPTION_CACHE: tuple[float, dict[str, Any]] = (0.0, {})
_RADAR_REFRESH_LOCK = threading.Lock()

# A transparent fallback when an official weight file has not yet been attached
# to the market snapshot. Values are relative leader weights, not claimed as the
# complete official index composition. Deployments can override these by
# populating snapshot["indexConstituentWeights"] from their licensed source.
INDEX_LEADER_WEIGHTS: dict[str, tuple[tuple[str, float], ...]] = {
    "NIFTY": (("HDFCBANK", 13.0), ("ICICIBANK", 9.0), ("RELIANCE", 8.5), ("BHARTIARTL", 4.8),
              ("INFY", 4.5), ("LT", 3.2), ("ITC", 3.0), ("SBIN", 2.9), ("AXISBANK", 2.8), ("KOTAKBANK", 2.5)),
    "BANKNIFTY": (("HDFCBANK", 29.0), ("ICICIBANK", 23.0), ("SBIN", 11.0), ("KOTAKBANK", 10.0),
                  ("AXISBANK", 9.0), ("INDUSINDBK", 3.0), ("BANKBARODA", 3.0), ("FEDERALBNK", 2.0)),
    "FINNIFTY": (("HDFCBANK", 24.0), ("ICICIBANK", 20.0), ("SBIN", 9.0), ("BAJFINANCE", 8.0),
                 ("KOTAKBANK", 8.0), ("AXISBANK", 7.0), ("BAJAJFINSV", 5.0), ("HDFCLIFE", 3.0), ("SBILIFE", 3.0)),
    "SENSEX": (("HDFCBANK", 14.0), ("ICICIBANK", 10.0), ("RELIANCE", 9.0), ("BHARTIARTL", 6.0),
                ("INFY", 5.5), ("LT", 4.0), ("ITC", 3.5), ("SBIN", 3.5), ("AXISBANK", 3.0), ("KOTAKBANK", 3.0)),
}


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _expiry(value: Any) -> date | None:
    text = str(value or "").strip().upper()
    for fmt in ("%d%b%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def load_angel_scrip_master(*, force: bool = False) -> list[dict[str, Any]]:
    global _MASTER_CACHE
    now = time.time()
    with _MASTER_LOCK:
        cached_at, rows = _MASTER_CACHE
        if rows and not force and now - cached_at < 21_600:
            return rows
        request = Request(SCRIP_MASTER_URL, headers={"User-Agent": "Alphix-Terminal/1.0"})
        with urlopen(request, timeout=20) as response:  # nosec - fixed Angel One URL
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError("Angel scrip master returned an invalid payload")
        rows = [row for row in payload if isinstance(row, dict)]
        _MASTER_CACHE = (now, rows)
        return rows


def _strike(raw: Any, spot: float) -> float | None:
    value = _float(raw)
    if value is None:
        return None
    return value / 100.0 if spot > 0 and value > spot * 20 else value


def _contracts(master: list[dict[str, Any]], config: dict[str, Any], spot: float, *, today: date | None = None) -> tuple[date | None, list[dict[str, Any]], dict[str, Any] | None]:
    session_date = today or datetime.now(timezone.utc).date()
    options: list[dict[str, Any]] = []
    futures: list[dict[str, Any]] = []
    for row in master:
        if str(row.get("exch_seg") or "").upper() != config["segment"]:
            continue
        name = str(row.get("name") or "").upper().strip()
        symbol = str(row.get("symbol") or "").upper().strip()
        if name != config["name"] and not symbol.startswith(config["name"]):
            continue
        expiry = _expiry(row.get("expiry"))
        if expiry is None or expiry < session_date:
            continue
        kind = str(row.get("instrumenttype") or "").upper()
        normalized = {**row, "_expiry": expiry, "_strike": _strike(row.get("strike"), spot)}
        if kind == "OPTIDX" and (symbol.endswith("CE") or symbol.endswith("PE")):
            options.append(normalized)
        elif kind == "FUTIDX":
            futures.append(normalized)
    expiries = sorted({row["_expiry"] for row in options})
    selected_expiry = expiries[0] if expiries else None
    selected = [row for row in options if row["_expiry"] == selected_expiry]
    nearest = sorted({row["_strike"] for row in selected if row.get("_strike") is not None}, key=lambda strike: abs(strike - spot))[:7]
    selected = [row for row in selected if row.get("_strike") in nearest]
    future = min(futures, key=lambda row: row["_expiry"]) if futures else None
    return selected_expiry, selected, future


def _instrument(row: dict[str, Any], key: str) -> Instrument:
    return Instrument(key, str(row.get("exch_seg") or "NFO"), str(row.get("symbol") or ""), str(row.get("token") or ""), str(row.get("symbol") or key))


def _best_price(quote: dict[str, Any], side: str) -> float | None:
    direct = quote.get("bestBidPrice" if side == "buy" else "bestAskPrice")
    if direct is not None:
        return _float(direct)
    depth = quote.get("depth") if isinstance(quote.get("depth"), dict) else {}
    rows = depth.get(side) if isinstance(depth.get(side), list) else []
    return _float(rows[0].get("price")) if rows and isinstance(rows[0], dict) else None


def _quote_row(contract: dict[str, Any], quote: dict[str, Any], greek: dict[str, Any] | None) -> dict[str, Any]:
    symbol = str(contract.get("symbol") or "")
    current_oi = _float(quote.get("opnInterest") or quote.get("oi"))
    previous_oi = _float(quote.get("previousOI") or quote.get("prev_oi"))
    return {
        "symbol": symbol, "token": str(contract.get("token") or ""), "strike": contract.get("_strike"),
        "optionType": "CALL" if symbol.endswith("CE") else "PUT", "ltp": _float(quote.get("ltp")),
        "close": _float(quote.get("close")), "volume": _float(quote.get("tradeVolume") or quote.get("volume")),
        "oi": current_oi, "previousOi": previous_oi,
        "oiChange": current_oi - previous_oi if current_oi is not None and previous_oi is not None else None,
        "bestBid": _best_price(quote, "buy"), "bestAsk": _best_price(quote, "sell"),
        "delta": _float((greek or {}).get("delta")), "gamma": _float((greek or {}).get("gamma")),
        "theta": _float((greek or {}).get("theta")), "vega": _float((greek or {}).get("vega")),
        "iv": _float((greek or {}).get("impliedVolatility")), "greeksSource": "ANGEL_ONE" if greek else None,
        "lotSize": _float(contract.get("lotsize")),
        "exchange": str(contract.get("exch_seg") or ""),
    }


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    multiplier = 2.0 / (period + 1.0)
    for price in values[period:]:
        value = (price - value) * multiplier + value
    return value


def parse_candle_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text.replace("Z", "+0000").replace("+05:30", "+0530"), fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST_ZONE)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST_ZONE)


def ist_session_bounds(session_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(session_date, dt_time(9, 15), tzinfo=IST_ZONE)
    end = datetime.combine(session_date, dt_time(15, 30), tzinfo=IST_ZONE)
    return start, end


def index_structure_from_candles(candles: list[list[Any]], *, session_date: date | None = None) -> dict[str, Any]:
    """Derive direction from today's ORB, with prior bars allowed to seed EMA20."""
    parsed = [row for row in candles if isinstance(row, list) and len(row) >= 5 and _float(row[4]) is not None]
    current = parsed
    if session_date is not None:
        current = [row for row in parsed if (parse_candle_ts(row[0]) and parse_candle_ts(row[0]).astimezone(IST_ZONE).date() == session_date)]
    closes = [_float(row[4]) for row in parsed]
    closes = [value for value in closes if value is not None]
    ema9, ema20 = _ema(closes, 9), _ema(closes, 20)
    current_closes = [_float(row[4]) for row in current]
    current_closes = [value for value in current_closes if value is not None]
    true_ranges: list[float] = []
    previous_close: float | None = None
    for row in current:
        high, low, close = _float(row[2]), _float(row[3]), _float(row[4])
        if high is None or low is None or close is None:
            continue
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)) if previous_close is not None else high - low)
        previous_close = close
    atr5 = (sum(true_ranges[-14:]) / min(14, len(true_ranges))) if true_ranges else None
    incomplete = {"status": "DATA_INCOMPLETE", "direction": None, "barCount": len(current),
                  "seedBarCount": max(0, len(parsed) - len(current)), "last": current_closes[-1] if current_closes else None,
                  "atr5m": round(atr5, 4) if atr5 is not None else None}
    if len(current) < 3 or len(parsed) < 20 or ema9 is None or ema20 is None:
        return incomplete
    orb_rows = current[:3]
    orb_high = max(_float(row[2]) or -math.inf for row in orb_rows)
    orb_low = min(_float(row[3]) or math.inf for row in orb_rows)
    last = current_closes[-1]
    call = last > orb_high and last > ema9 > ema20
    put = last < orb_low and last < ema9 < ema20
    return {
        "status": "CONFIRMED" if call or put else "NO_BREAKOUT",
        "direction": "CALL" if call else "PUT" if put else None,
        "last": last, "ema9": round(ema9, 4), "ema20": round(ema20, 4),
        "orbHigh": orb_high, "orbLow": orb_low, "barCount": len(current),
        "atr5m": round(atr5, 4) if atr5 is not None else None,
        "seedBarCount": max(0, len(parsed) - len(current)),
    }


def walk_forward_structure(candles: list[list[Any]], *, session_date: date | None = None) -> dict[str, Any]:
    """First 5m close that confirms ORB+EMA, plus the end-of-window structure."""
    parsed = [row for row in candles if isinstance(row, list) and len(row) >= 5 and _float(row[4]) is not None]
    eod = index_structure_from_candles(parsed, session_date=session_date)
    confirmed_at = None
    first_direction = None
    for index in range(len(parsed)):
        stamp = parse_candle_ts(parsed[index][0])
        if session_date is not None and (stamp is None or stamp.astimezone(IST_ZONE).date() != session_date):
            continue
        snapshot = index_structure_from_candles(parsed[: index + 1], session_date=session_date)
        direction = snapshot.get("direction")
        if direction in {"CALL", "PUT"}:
            confirmed_at = parse_candle_ts(parsed[index][0])
            first_direction = direction
            break
    return {
        **eod,
        "firstDirection": first_direction,
        "confirmedAt": confirmed_at.isoformat() if confirmed_at else None,
    }


def _fetch_candles_with_retry(
    client: Any,
    exchange: str,
    token: str,
    start: datetime,
    end: datetime,
    *,
    attempts: int = 3,
) -> tuple[list[list[Any]], str | None]:
    """Angel historical calls are per token; retry transient/empty responses."""
    last_error: str | None = None
    for attempt in range(max(1, attempts)):
        try:
            rows = client.fetch_candles(exchange, token, "FIVE_MINUTE", start, end)
            if rows:
                return rows, None
            last_error = "EMPTY_CANDLE_RESPONSE"
        except Exception as exc:
            last_error = str(exc)
        if attempt + 1 < attempts:
            time.sleep(0.25 * (attempt + 1))
    return [], last_error


def _fetch_one_index(client: Any, rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    key = config["key"]
    try:
        spot_quote = client.fetch_quote(config["exchange"], config["spotSymbol"], config["spotToken"])
        spot = _float(spot_quote.get("ltp"))
        if spot is None or spot <= 0:
            raise RuntimeError("spot quote unavailable")
        expiry, contracts, future = _contracts(rows, config, spot)
        if expiry is None or not contracts:
            raise RuntimeError("active option contracts unavailable in Angel scrip master")
        instruments = [_instrument(row, f"{key}:{row.get('token')}") for row in contracts]
        if future:
            instruments.append(_instrument(future, f"{key}:FUT"))
        quotes = client.fetch_batch_quotes(instruments)
        greek_rows: list[dict[str, Any]] = []
        greek_error = None
        if config["segment"] == "NFO":
            try:
                greek_rows = client.fetch_option_greeks(config["name"], expiry.strftime("%d%b%Y").upper())
            except Exception as exc:
                greek_error = str(exc)
        else:
            greek_error = "ANGEL_GREEKS_NSE_ONLY"
        greek_map = {(round(_float(row.get("strikePrice")) or -1, 4), str(row.get("optionType") or "").upper()): row for row in greek_rows}
        chain = []
        for contract in contracts:
            option_type = "CE" if str(contract.get("symbol") or "").endswith("CE") else "PE"
            greek = greek_map.get((round(contract.get("_strike") or -1, 4), option_type))
            chain.append(_quote_row(contract, quotes.get(f"{key}:{contract.get('token')}") or {}, greek))
        future_quote = quotes.get(f"{key}:FUT") if future else None
        now_ist = datetime.now(IST_ZONE)
        # Seed EMA20 from recent history while ORB/direction remains restricted
        # to the current IST session. Angel candle history is per token, not a
        # multi-symbol batch endpoint.
        history_start = datetime.combine(now_ist.date() - timedelta(days=7), dt_time(9, 15), tzinfo=IST_ZONE)
        candles, candle_error = _fetch_candles_with_retry(
            client, config["exchange"], config["spotToken"], history_start, now_ist,
        )
        structure_source = "INDEX_SPOT"
        if not candles and future:
            candles, future_error = _fetch_candles_with_retry(
                client, str(future.get("exch_seg") or config["segment"]), str(future.get("token") or ""), history_start, now_ist,
            )
            if candles:
                structure_source = "INDEX_FUTURES_PROXY"
            elif future_error:
                candle_error = f"SPOT:{candle_error}; FUTURE:{future_error}"
        structure = walk_forward_structure(candles, session_date=now_ist.date()) if candles else index_structure_from_candles([], session_date=now_ist.date())
        return key, {
            "source": "ANGEL_ONE", "status": "LIVE" if chain else "DATA_INCOMPLETE",
            "fetchedAt": datetime.now(timezone.utc).isoformat(), "spot": spot, "spotClose": _float(spot_quote.get("close")),
            "expiry": expiry.isoformat(), "chain": chain,
            "structure": {**structure, "source": structure_source},
            "candleStatus": "LIVE" if candles else "SOURCE_UNAVAILABLE",
            "candleError": candle_error,
            "future": ({"symbol": future.get("symbol"), "ltp": _float((future_quote or {}).get("ltp")),
                        "close": _float((future_quote or {}).get("close")),
                        "oi": _float((future_quote or {}).get("opnInterest") or (future_quote or {}).get("oi")),
                        "previousOi": _float((future_quote or {}).get("previousOI") or (future_quote or {}).get("prev_oi"))} if future else None),
            "greeksStatus": "LIVE" if greek_rows else "UNAVAILABLE", "greeksError": greek_error,
        }
    except Exception as exc:
        return key, {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "error": str(exc), "chain": []}


def fetch_angel_index_option_snapshot(client: Any, *, master: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Fetch four indexes sequentially.

    AngelOneClient holds one SmartConnect/TOTP session with no safe concurrent
    use. Parallel submits on the same client race login, reset, and in-flight
    quotes.
    """
    rows = master if master is not None else load_angel_scrip_master()
    output: dict[str, Any] = {}
    for config in INDEXES:
        key, payload = _fetch_one_index(client, rows, config)
        output[key] = payload
    return {"source": "ANGEL_ONE", "fetchedAt": datetime.now(timezone.utc).isoformat(), "indices": output}


def radar_cache_path() -> Path:
    env = (os.environ.get("INDEX_OPTIONS_RADAR_FILE") or "").strip()
    if env:
        return Path(env)
    return market_snapshot_path().with_name("index_options_radar.json")


def oi_baseline_path() -> Path:
    env = (os.environ.get("INDEX_OPTIONS_OI_BASELINE_FILE") or "").strip()
    if env:
        return Path(env)
    return market_snapshot_path().with_name("index_options_oi_baseline.json")


def _apply_oi_baselines(option_data: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Add a labelled intraday OI comparison when Angel omits previous OI."""
    stamp = (now or datetime.now(timezone.utc)).astimezone(IST_ZONE)
    session = stamp.date().isoformat()
    with _OI_BASELINE_LOCK:
        try:
            stored = load_json_with_fallback(oi_baseline_path())
        except (FileNotFoundError, ValueError, TypeError):
            stored = {}
        if not isinstance(stored, dict) or stored.get("sessionDate") != session:
            stored = {"sessionDate": session, "instruments": {}}
        instruments = stored.setdefault("instruments", {})
        changed = False
        for key, row in (option_data.get("indices") or {}).items():
            if not isinstance(row, dict):
                continue
            observations: list[tuple[str, dict[str, Any]]] = []
            future = row.get("future")
            if isinstance(future, dict):
                observations.append((f"{key}:FUT:{future.get('symbol') or ''}", future))
            for contract in row.get("chain") or []:
                if isinstance(contract, dict):
                    observations.append((f"{key}:OPT:{contract.get('symbol') or contract.get('token') or ''}", contract))
            for instrument_key, quote in observations:
                current = _float(quote.get("oi"))
                provider_previous = _float(quote.get("previousOi"))
                if current is None or current < 0:
                    continue
                if provider_previous is not None and provider_previous > 0:
                    quote["oiChange"] = current - provider_previous
                    quote["oiBaseline"] = {"basis": "PROVIDER_PREVIOUS_OI", "oi": provider_previous,
                                           "ageSeconds": None, "capturedAt": None}
                    continue
                baseline = instruments.get(instrument_key)
                if not isinstance(baseline, dict) or _float(baseline.get("oi")) is None:
                    instruments[instrument_key] = {"oi": current, "capturedAt": stamp.isoformat()}
                    quote["oiBaseline"] = {"basis": "WARMING_UP", "oi": current, "ageSeconds": 0,
                                           "capturedAt": stamp.isoformat()}
                    changed = True
                    continue
                captured = parse_candle_ts(baseline.get("capturedAt"))
                age = max(0.0, (stamp - captured.astimezone(IST_ZONE)).total_seconds()) if captured else 0.0
                basis = "INTRADAY_SESSION_BASELINE" if age >= 60.0 else "WARMING_UP"
                quote["oiBaseline"] = {"basis": basis, "oi": _float(baseline.get("oi")),
                                       "ageSeconds": round(age), "capturedAt": baseline.get("capturedAt")}
                if age >= 60.0:
                    quote["previousOi"] = _float(baseline.get("oi"))
                    quote["oiChange"] = current - (_float(baseline.get("oi")) or 0.0)
        if changed:
            atomic_write_json(oi_baseline_path(), stored)
    return option_data


def load_persisted_radar(*, max_age_seconds: float | None = None) -> dict[str, Any] | None:
    try:
        payload = load_json_with_fallback(radar_cache_path())
    except FileNotFoundError:
        return None
    if not isinstance(payload, dict) or not payload.get("success"):
        return None
    if max_age_seconds is None:
        return payload
    fetched = payload.get("persistedAt") or payload.get("updatedAt")
    if not fetched:
        return None
    try:
        stamp = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
    return payload if age <= max_age_seconds else None


def persist_radar(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or not payload.get("success"):
        return
    stamped = {**payload, "persistedAt": datetime.now(timezone.utc).isoformat()}
    atomic_write_json(radar_cache_path(), stamped)


def cached_angel_index_option_snapshot(client: Any, *, ttl_seconds: float = 15.0) -> dict[str, Any]:
    """Coalesce UI polling so it cannot fan out repeated Angel chain calls."""
    global _OPTION_CACHE
    now = time.monotonic()
    with _OPTION_LOCK:
        cached_at, payload = _OPTION_CACHE
        if payload and now - cached_at < max(1.0, ttl_seconds):
            return payload
        payload = fetch_angel_index_option_snapshot(client)
        _OPTION_CACHE = (now, payload)
        return payload


def unavailable_provider_snapshot(error: Exception | str) -> dict[str, Any]:
    message = str(error)
    return {
        "source": "ANGEL_ONE",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "indices": {config["key"]: {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "error": message, "chain": []} for config in INDEXES},
    }


def active_index_expiries(master: list[dict[str, Any]] | None = None) -> dict[str, date]:
    """Nearest live expiry per supported index from Angel's current master."""
    rows = master if master is not None else load_angel_scrip_master()
    today = datetime.now(timezone.utc).date()
    result: dict[str, date] = {}
    for config in INDEXES:
        expiries = []
        for row in rows:
            if str(row.get("exch_seg") or "").upper() != config["segment"]:
                continue
            name = str(row.get("name") or "").upper().strip()
            symbol = str(row.get("symbol") or "").upper().strip()
            if name != config["name"] and not symbol.startswith(config["name"]):
                continue
            if str(row.get("instrumenttype") or "").upper() != "OPTIDX":
                continue
            value = _expiry(row.get("expiry"))
            if value and value >= today:
                expiries.append(value)
        if expiries:
            result[config["key"]] = min(expiries)
    return result


def _weighted_breadth(snapshot: dict[str, Any], key: str, direction: str | None) -> dict[str, Any]:
    weights = ((snapshot.get("indexConstituentWeights") or {}).get(key) or [])
    weight_source = "OFFICIAL_SNAPSHOT"
    if not isinstance(weights, list) or not weights:
        weights = [{"symbol": symbol, "weight": weight} for symbol, weight in INDEX_LEADER_WEIGHTS.get(key, ())]
        weight_source = "LEADER_BASKET_PROXY"
    quotes = snapshot.get("stockQuotes") if isinstance(snapshot.get("stockQuotes"), dict) else {}
    if not isinstance(weights, list) or not weights:
        return {"status": "WEIGHTS_UNAVAILABLE", "aligned": None, "score": None, "coveragePct": 0.0, "source": weight_source}
    total_weight = sum(_float(row.get("weight")) or 0 for row in weights if isinstance(row, dict))
    covered = 0.0
    signed = 0.0
    quote_proxy_weight = 0.0
    for item in weights:
        if not isinstance(item, dict):
            continue
        symbol, weight = str(item.get("symbol") or "").upper(), _float(item.get("weight"))
        quote = quotes.get(symbol) if isinstance(quotes.get(symbol), dict) else None
        if not quote or not weight:
            continue
        intra = quote.get("intraday") if isinstance(quote.get("intraday"), dict) else {}
        ltp = _float(quote.get("ltpRaw") or quote.get("ltp"))
        vwap, ema9 = _float(intra.get("vwap")), _float(intra.get("ema9"))
        signal = None
        if ltp and vwap and ema9:
            signal = 1.0 if ltp > vwap and ltp > ema9 else -1.0 if ltp < vwap and ltp < ema9 else 0.0
        elif ltp:
            # Angel batch quotes always carry open/previous close even when a
            # constituent candle call is not in the scanner's top-volume set.
            open_price, previous_close = _float(quote.get("open")), _float(quote.get("close"))
            if open_price and previous_close:
                signal = 1.0 if ltp > open_price and ltp > previous_close else -1.0 if ltp < open_price and ltp < previous_close else 0.0
                quote_proxy_weight += weight
        if signal is None:
            continue
        covered += weight
        signed += weight * signal
    coverage = covered / total_weight * 100.0 if total_weight > 0 else 0.0
    breadth = signed / covered if covered > 0 else None
    uses_quote_proxy = quote_proxy_weight > 0
    minimum_coverage = 90.0 if weight_source == "OFFICIAL_SNAPSHOT" or uses_quote_proxy else 80.0
    alignment_floor = 0.70 if uses_quote_proxy else 0.55
    aligned = None if coverage < minimum_coverage or breadth is None or direction is None else breadth >= alignment_floor if direction == "CALL" else breadth <= -alignment_floor
    return {"status": "LIVE" if coverage >= minimum_coverage else "COVERAGE_INCOMPLETE", "aligned": aligned,
            "score": breadth, "coveragePct": round(coverage, 2), "source": weight_source,
            "minimumCoveragePct": minimum_coverage, "alignmentFloor": alignment_floor,
            "quoteProxyPct": round(quote_proxy_weight / total_weight * 100.0, 2) if total_weight > 0 else 0.0}


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _bs_price(spot: float, strike: float, years: float, rate: float, sigma: float, option_type: str) -> float:
    if min(spot, strike, years, sigma) <= 0:
        return 0.0
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    discounted = strike * math.exp(-rate * years)
    if option_type == "CALL":
        return spot * _normal_cdf(d1) - discounted * _normal_cdf(d2)
    return discounted * _normal_cdf(-d2) - spot * _normal_cdf(-d1)


def _local_greeks(item: dict[str, Any], spot: float | None, expiry_value: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Fill missing IV/Greeks from live premium; never overwrite provider values."""
    strike, premium = _float(item.get("strike")), _float(item.get("ltp"))
    option_type = str(item.get("optionType") or "").upper()
    expiry_date = _expiry(expiry_value)
    now_ist = (now or datetime.now(IST_ZONE)).astimezone(IST_ZONE)
    if not spot or not strike or not premium or expiry_date is None or option_type not in {"CALL", "PUT"}:
        return item
    expiry_at = datetime.combine(expiry_date, dt_time(15, 30), tzinfo=IST_ZONE)
    years = max((expiry_at - now_ist).total_seconds(), 60.0) / (365.0 * 24.0 * 3600.0)
    rate = 0.065
    sigma = _float(item.get("iv"))
    sigma = sigma / 100.0 if sigma and sigma > 1 else sigma
    if not sigma or sigma <= 0:
        low, high = 0.01, 5.0
        for _ in range(64):
            mid = (low + high) / 2.0
            if _bs_price(spot, strike, years, rate, mid, option_type) > premium:
                high = mid
            else:
                low = mid
        sigma = (low + high) / 2.0
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    delta = _normal_cdf(d1) if option_type == "CALL" else _normal_cdf(d1) - 1.0
    gamma = _normal_pdf(d1) / (spot * sigma * root_t)
    vega = spot * _normal_pdf(d1) * root_t / 100.0
    first = -(spot * _normal_pdf(d1) * sigma) / (2.0 * root_t)
    discounted = strike * math.exp(-rate * years)
    theta_year = first - rate * discounted * _normal_cdf(d2) if option_type == "CALL" else first + rate * discounted * _normal_cdf(-d2)
    enriched = dict(item)
    defaults = {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta_year / 365.0, "iv": sigma * 100.0}
    changed = False
    for name, value in defaults.items():
        if _float(enriched.get(name)) is None:
            enriched[name] = round(value, 6)
            changed = True
    if changed:
        enriched["greeksSource"] = enriched.get("greeksSource") or "LOCAL_BLACK_SCHOLES"
    return enriched


def _futures_oi_state(future: dict[str, Any]) -> dict[str, Any]:
    ltp, close = _float(future.get("ltp")), _float(future.get("close"))
    oi, previous_oi = _float(future.get("oi")), _float(future.get("previousOi"))
    baseline = future.get("oiBaseline") if isinstance(future.get("oiBaseline"), dict) else {}
    if not ltp or not close or oi is None or previous_oi is None or previous_oi <= 0:
        return {"state": "BASELINE_WARMING_UP" if baseline.get("basis") == "WARMING_UP" else "UNAVAILABLE",
                "priceChangePct": round((ltp - close) / close * 100.0, 3) if ltp and close else None,
                "oiChangePct": None, "baseline": baseline or None}
    price_up, oi_up = ltp > close, oi > previous_oi
    state = "LONG_BUILDUP" if price_up and oi_up else "SHORT_COVERING" if price_up else "SHORT_BUILDUP" if oi_up else "LONG_UNWINDING"
    return {"state": state, "priceChangePct": round((ltp - close) / close * 100.0, 3),
            "oiChangePct": round((oi - previous_oi) / previous_oi * 100.0, 3), "baseline": baseline or None}


def _chain_confirmation(chain: list[dict[str, Any]], direction: str | None, selected: dict[str, Any] | None) -> dict[str, Any]:
    if direction not in {"CALL", "PUT"} or not selected:
        return {"aligned": None, "score": None, "reason": "DIRECTION_OR_CONTRACT_UNAVAILABLE"}
    side = [row for row in chain if row.get("optionType") == direction]
    opposite_type = "PUT" if direction == "CALL" else "CALL"
    opposite = [row for row in chain if row.get("optionType") == opposite_type]
    usable = [row for row in chain if _float(row.get("oiChange")) is not None]
    if not usable:
        warming = any(((row.get("oiBaseline") or {}).get("basis") == "WARMING_UP") for row in chain if isinstance(row, dict))
        return {"aligned": None, "score": None, "reason": "OI_BASELINE_WARMING_UP" if warming else "OI_CHANGE_UNAVAILABLE"}
    selected_change = _float(selected.get("oiChange"))
    selected_ltp, selected_close = _float(selected.get("ltp")), _float(selected.get("close"))
    premium_buildup = bool(selected_change is not None and selected_change > 0 and selected_ltp and selected_close and selected_ltp > selected_close)
    side_change = sum(_float(row.get("oiChange")) or 0.0 for row in side)
    opposite_change = sum(_float(row.get("oiChange")) or 0.0 for row in opposite)
    wall_shift = opposite_change > 0 and side_change < 0
    aligned = premium_buildup or wall_shift
    reason = "DIRECTIONAL_PREMIUM_OI_BUILDUP" if premium_buildup else "OPPOSING_WALL_BUILDUP_AND_SUPPORT_UNWIND" if wall_shift else "CHAIN_NOT_ALIGNED"
    return {"aligned": aligned, "score": 100.0 if premium_buildup else 85.0 if wall_shift else 0.0,
            "reason": reason, "directionalOiChange": round(side_change, 2), "opposingOiChange": round(opposite_change, 2)}


def _vix_regime(snapshot: dict[str, Any]) -> tuple[str | None, float | None]:
    rows = ((snapshot.get("macroDataStrip") or {}).get("morning") or [])
    for row in rows:
        label = str(row.get("label") or row.get("name") or "").upper()
        if "VIX" not in label:
            continue
        value = _float(row.get("val") or row.get("value") or row.get("ltp"))
        if value is None:
            return None, None
        return ("CALM" if value < 13 else "NORMAL" if value < 18 else "ELEVATED" if value < 25 else "FEAR"), value
    return None, None


def _contract_risk_reward(selected: dict[str, Any] | None, structure: dict[str, Any], direction: str | None) -> dict[str, Any]:
    """Project option R from ORB invalidation and the nearest ATR/ORB target."""
    if not selected or direction not in {"CALL", "PUT"}:
        return {"expectedR": None, "basis": "STRUCTURE_UNAVAILABLE"}
    last, ema9 = _float(structure.get("last")), _float(structure.get("ema9"))
    orb_high, orb_low, atr = _float(structure.get("orbHigh")), _float(structure.get("orbLow")), _float(structure.get("atr5m"))
    delta, gamma = abs(_float(selected.get("delta")) or 0), abs(_float(selected.get("gamma")) or 0)
    premium = _float(selected.get("ltp"))
    if not last or not ema9 or not orb_high or not orb_low or not atr or delta <= 0 or not premium:
        return {"expectedR": None, "basis": "STRUCTURE_OR_ATR_UNAVAILABLE"}
    opening_range = orb_high - orb_low
    if opening_range <= 0:
        return {"expectedR": None, "basis": "OPENING_RANGE_INVALID"}
    if direction == "CALL":
        stop = max(level for level in (orb_high, ema9) if level < last) if any(level < last for level in (orb_high, ema9)) else None
        targets = [orb_high + opening_range, last + atr]
        target = min(level for level in targets if level > last) if any(level > last for level in targets) else None
    else:
        stop = min(level for level in (orb_low, ema9) if level > last) if any(level > last for level in (orb_low, ema9)) else None
        targets = [orb_low - opening_range, last - atr]
        target = max(level for level in targets if level < last) if any(level < last for level in targets) else None
    if stop is None or target is None:
        return {"expectedR": 0.0, "basis": "STRUCTURAL_TARGET_ALREADY_EXHAUSTED", "stop": stop, "target": target}
    risk_move, reward_move = abs(stop - last), abs(target - last)
    option_loss = max(delta * risk_move - 0.5 * gamma * risk_move * risk_move, premium * 0.20)
    option_gain = delta * reward_move + 0.5 * gamma * reward_move * reward_move
    expected_r = round(option_gain / option_loss, 3) if option_loss > 0 else None
    return {"expectedR": expected_r, "basis": "ORB_INVALIDATION_NEAREST_ATR_OR_MEASURED_MOVE",
            "entryUnderlying": round(last, 4), "stop": round(stop, 4), "target": round(target, 4),
            "riskPoints": round(risk_move, 4), "rewardPoints": round(reward_move, 4),
            "atr5m": round(atr, 4), "openingRangePoints": round(opening_range, 4)}


def option_data_to_strategy_inputs(option_data: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    market_snapshot = snapshot if isinstance(snapshot, dict) else {}
    converted: dict[str, Any] = {}
    for key, row in (option_data.get("indices") or {}).items():
        raw_chain = row.get("chain") if isinstance(row.get("chain"), list) else []
        spot, close = _float(row.get("spot")), _float(row.get("spotClose"))
        chain = [_local_greeks(item, spot, row.get("expiry")) for item in raw_chain if isinstance(item, dict)]
        change_pct = ((spot - close) / close * 100.0) if spot and close else None
        structure = row.get("structure") if isinstance(row.get("structure"), dict) else {}
        direction = structure.get("direction")
        side = [item for item in chain if item.get("optionType") == direction]
        liquid = [item for item in side if (_float(item.get("ltp")) or 0) > 0 and (_float(item.get("volume")) or 0) > 0]
        delta_ok = []
        for item in liquid:
            bid, ask = _float(item.get("bestBid")), _float(item.get("bestAsk"))
            mid = (bid + ask) / 2.0 if bid and ask else None
            spread_pct = ((ask - bid) / mid * 100.0) if mid and ask >= bid else None
            if 0.45 <= abs(_float(item.get("delta")) or -1) <= 0.65 and spread_pct is not None and spread_pct <= 1.5:
                item["spreadPct"] = round(spread_pct, 3)
                delta_ok.append(item)
        selected = min(delta_ok, key=lambda item: abs(abs(_float(item.get("delta")) or 0) - 0.55)) if delta_ok else None
        future = row.get("future") if isinstance(row.get("future"), dict) else {}
        breadth = _weighted_breadth(market_snapshot, key, direction)
        futures_oi = _futures_oi_state(future)
        oi_state = futures_oi["state"]
        strong_oi = (direction == "CALL" and oi_state == "LONG_BUILDUP") or (direction == "PUT" and oi_state == "SHORT_BUILDUP")
        secondary_oi = (direction == "CALL" and oi_state == "SHORT_COVERING") or (direction == "PUT" and oi_state == "LONG_UNWINDING")
        strong_breadth = breadth.get("aligned") is True and abs(_float(breadth.get("score")) or 0) >= 0.70
        oi_aligned = True if strong_oi or (secondary_oi and strong_breadth) else False if direction and oi_state != "UNAVAILABLE" else None
        regime, vix = _vix_regime(market_snapshot)
        risk_reward = _contract_risk_reward(selected, structure, direction)
        expected_r = _float(risk_reward.get("expectedR"))
        chain_evidence = _chain_confirmation(chain, direction, selected)
        chain_aligned = chain_evidence.get("aligned")
        structure_gate = True if direction else False if structure.get("status") == "NO_BREAKOUT" else None
        contract_gate = True if selected else False if direction and any(_float(item.get("delta")) is not None for item in chain) else None
        greeks_source = selected.get("greeksSource") if selected else None
        converted[key] = {
            "spot": spot, "direction": direction, "source": row.get("source") or "ANGEL_ONE", "providerStatus": row.get("status"),
            "expiry": row.get("expiry"), "rawChain": chain,
            "scores": {"trend": 100.0 if direction else None, "breakout": 100.0 if direction else None,
                       "futuresOi": 100.0 if strong_oi else 75.0 if oi_aligned is True else 0.0 if oi_aligned is False else None,
                       "contract": 100.0 if selected else None,
                       "optionChain": chain_evidence.get("score"),
                       "breadth": (50.0 + 50.0 * abs(_float(breadth.get("score")) or 0)) if breadth.get("score") is not None else None,
                       "regime": 100.0 if regime in {"NORMAL", "ELEVATED"} else 70.0 if regime == "CALM" else 0.0 if regime == "FEAR" else None},
            "gates": {"fresh": True if row.get("status") == "LIVE" else False, "structure": structure_gate, "breakout": structure_gate,
                      "futuresOi": oi_aligned, "optionChain": chain_aligned, "breadth": breadth.get("aligned"),
                      "contractEconomics": contract_gate, "riskReward": (expected_r >= 1.5) if expected_r is not None else None},
            "contract": ({"symbol": selected.get("symbol"), "strike": selected.get("strike"), "expiry": row.get("expiry"),
                          "ltp": selected.get("ltp"), "delta": selected.get("delta"), "gamma": selected.get("gamma"),
                          "theta": selected.get("theta"), "vega": selected.get("vega"), "iv": selected.get("iv")} if selected else None),
            "breadth": breadth, "structure": structure, "vixRegime": regime, "indiaVix": vix, "expectedR": expected_r,
            "gateEvidence": {
                "futuresOi": {**futures_oi, "aligned": oi_aligned, "secondaryConfirmation": bool(secondary_oi and strong_breadth)},
                "optionChain": chain_evidence,
                "breadth": breadth,
                "contractEconomics": {"aligned": contract_gate, "greeksSource": greeks_source,
                                      "spreadPct": selected.get("spreadPct") if selected else None},
                "riskReward": {**risk_reward, "aligned": (expected_r >= 1.5) if expected_r is not None else None,
                               "minimumR": 1.5},
            },
            "dataLimitations": [value for value in (None if greeks_source else row.get("greeksError"),
                               None if direction else "INDEX_CANDLE_STRUCTURE_NOT_CONFIRMED",
                               None if breadth.get("aligned") is not None else "WEIGHTED_CONSTITUENT_BREADTH_NOT_CONFIRMED",
                               None if expected_r is not None else "RISK_REWARD_NOT_YET_CONFIRMED") if value],
        }
    return {"indices": converted}
