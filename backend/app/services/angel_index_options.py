"""Angel One option-chain ingestion for the deterministic index-options radar."""
from __future__ import annotations

import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time, timezone
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
_OPTION_CACHE: tuple[float, dict[str, Any]] = (0.0, {})
_RADAR_REFRESH_LOCK = threading.Lock()


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


def index_structure_from_candles(candles: list[list[Any]]) -> dict[str, Any]:
    """Derive direction only after a 5-minute close clears ORB and aligned EMAs."""
    parsed = [row for row in candles if isinstance(row, list) and len(row) >= 5 and _float(row[4]) is not None]
    closes = [_float(row[4]) for row in parsed]
    closes = [value for value in closes if value is not None]
    ema9, ema20 = _ema(closes, 9), _ema(closes, 20)
    incomplete = {"status": "DATA_INCOMPLETE", "direction": None, "barCount": len(parsed), "last": closes[-1] if closes else None}
    if len(parsed) < 20 or ema9 is None or ema20 is None:
        return incomplete
    orb_rows = parsed[:3]
    orb_high = max(_float(row[2]) or -math.inf for row in orb_rows)
    orb_low = min(_float(row[3]) or math.inf for row in orb_rows)
    last = closes[-1]
    call = last > orb_high and last > ema9 > ema20
    put = last < orb_low and last < ema9 < ema20
    return {
        "status": "CONFIRMED" if call or put else "NO_BREAKOUT",
        "direction": "CALL" if call else "PUT" if put else None,
        "last": last, "ema9": round(ema9, 4), "ema20": round(ema20, 4),
        "orbHigh": orb_high, "orbLow": orb_low, "barCount": len(parsed),
    }


def walk_forward_structure(candles: list[list[Any]]) -> dict[str, Any]:
    """First 5m close that confirms ORB+EMA, plus the end-of-window structure."""
    parsed = [row for row in candles if isinstance(row, list) and len(row) >= 5 and _float(row[4]) is not None]
    eod = index_structure_from_candles(parsed)
    confirmed_at = None
    first_direction = None
    for index in range(19, len(parsed)):
        snapshot = index_structure_from_candles(parsed[: index + 1])
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
        session_start, _session_end = ist_session_bounds(now_ist.date())
        try:
            candles = client.fetch_candles(config["exchange"], config["spotToken"], "FIVE_MINUTE", session_start, now_ist)
        except Exception:
            candles = []
        return key, {
            "source": "ANGEL_ONE", "status": "LIVE" if chain else "DATA_INCOMPLETE",
            "fetchedAt": datetime.now(timezone.utc).isoformat(), "spot": spot, "spotClose": _float(spot_quote.get("close")),
            "expiry": expiry.isoformat(), "chain": chain,
            "structure": walk_forward_structure(candles) if candles else index_structure_from_candles(candles),
            "future": ({"symbol": future.get("symbol"), "ltp": _float((future_quote or {}).get("ltp")),
                        "close": _float((future_quote or {}).get("close")),
                        "oi": _float((future_quote or {}).get("opnInterest") or (future_quote or {}).get("oi")),
                        "previousOi": _float((future_quote or {}).get("previousOI") or (future_quote or {}).get("prev_oi"))} if future else None),
            "greeksStatus": "LIVE" if greek_rows else "UNAVAILABLE", "greeksError": greek_error,
        }
    except Exception as exc:
        return key, {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "error": str(exc), "chain": []}


def fetch_angel_index_option_snapshot(client: Any, *, master: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = master if master is not None else load_angel_scrip_master()
    output: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(INDEXES)) as pool:
        futures = [pool.submit(_fetch_one_index, client, rows, config) for config in INDEXES]
        for future in as_completed(futures):
            key, payload = future.result()
            output[key] = payload
    ordered = {config["key"]: output.get(config["key"]) or {"source": "ANGEL_ONE", "status": "SOURCE_UNAVAILABLE", "chain": []} for config in INDEXES}
    return {"source": "ANGEL_ONE", "fetchedAt": datetime.now(timezone.utc).isoformat(), "indices": ordered}


def radar_cache_path() -> Path:
    env = (os.environ.get("INDEX_OPTIONS_RADAR_FILE") or "").strip()
    if env:
        return Path(env)
    return market_snapshot_path().with_name("index_options_radar.json")


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
    quotes = snapshot.get("stockQuotes") if isinstance(snapshot.get("stockQuotes"), dict) else {}
    if not isinstance(weights, list) or not weights:
        return {"status": "WEIGHTS_UNAVAILABLE", "aligned": None, "score": None, "coveragePct": 0.0}
    total_weight = sum(_float(row.get("weight")) or 0 for row in weights if isinstance(row, dict))
    covered = 0.0
    signed = 0.0
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
        if not ltp or not vwap or not ema9:
            continue
        covered += weight
        signed += weight * (1.0 if ltp > vwap and ltp > ema9 else -1.0 if ltp < vwap and ltp < ema9 else 0.0)
    coverage = covered / total_weight * 100.0 if total_weight > 0 else 0.0
    breadth = signed / covered if covered > 0 else None
    aligned = None if coverage < 90 or breadth is None or direction is None else breadth >= 0.55 if direction == "CALL" else breadth <= -0.55
    return {"status": "LIVE" if coverage >= 90 else "COVERAGE_INCOMPLETE", "aligned": aligned, "score": breadth, "coveragePct": round(coverage, 2)}


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


def _contract_risk_reward(selected: dict[str, Any] | None, structure: dict[str, Any], direction: str | None) -> float | None:
    if not selected or direction not in {"CALL", "PUT"}:
        return None
    last, ema9 = _float(structure.get("last")), _float(structure.get("ema9"))
    delta, gamma = abs(_float(selected.get("delta")) or 0), abs(_float(selected.get("gamma")) or 0)
    premium = _float(selected.get("ltp"))
    if not last or not ema9 or delta <= 0 or not premium:
        return None
    underlying_risk = abs(last - ema9)
    if underlying_risk <= 0:
        return None
    projected = underlying_risk * 1.5
    loss = max(delta * underlying_risk, premium * 0.20)
    gain = delta * projected + 0.5 * gamma * projected * projected
    return round(gain / loss, 3) if loss > 0 else None


def option_data_to_strategy_inputs(option_data: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    market_snapshot = snapshot if isinstance(snapshot, dict) else {}
    converted: dict[str, Any] = {}
    for key, row in (option_data.get("indices") or {}).items():
        chain = row.get("chain") if isinstance(row.get("chain"), list) else []
        spot, close = _float(row.get("spot")), _float(row.get("spotClose"))
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
        f_ltp, f_close = _float(future.get("ltp")), _float(future.get("close"))
        f_oi, f_prev_oi = _float(future.get("oi")), _float(future.get("previousOi"))
        oi_aligned = None
        if direction and f_ltp and f_close and f_oi is not None and f_prev_oi is not None:
            oi_aligned = (direction == "CALL" and f_ltp > f_close and f_oi > f_prev_oi) or (direction == "PUT" and f_ltp < f_close and f_oi > f_prev_oi)
        breadth = _weighted_breadth(market_snapshot, key, direction)
        regime, vix = _vix_regime(market_snapshot)
        expected_r = _contract_risk_reward(selected, structure, direction)
        premium_buildup = bool(selected and (_float(selected.get("ltp")) or 0) > (_float(selected.get("close")) or math.inf) and (_float(selected.get("oiChange")) or 0) > 0)
        structure_gate = True if direction else False if structure.get("status") == "NO_BREAKOUT" else None
        contract_gate = True if selected else False if row.get("greeksStatus") == "LIVE" and direction else None
        converted[key] = {
            "spot": spot, "direction": direction, "source": row.get("source") or "ANGEL_ONE", "providerStatus": row.get("status"),
            "expiry": row.get("expiry"), "rawChain": chain,
            "scores": {"trend": 100.0 if direction else None, "breakout": 100.0 if direction else None,
                       "futuresOi": 100.0 if oi_aligned is True else 0.0 if oi_aligned is False else None,
                       "contract": 100.0 if selected else None,
                       "optionChain": 100.0 if premium_buildup else 0.0 if selected else None,
                       "breadth": (50.0 + 50.0 * abs(_float(breadth.get("score")) or 0)) if breadth.get("score") is not None else None,
                       "regime": 100.0 if regime in {"NORMAL", "ELEVATED"} else 70.0 if regime == "CALM" else 0.0 if regime == "FEAR" else None},
            "gates": {"fresh": True if row.get("status") == "LIVE" else False, "structure": structure_gate, "breakout": structure_gate,
                      "futuresOi": oi_aligned, "optionChain": premium_buildup if selected else None, "breadth": breadth.get("aligned"),
                      "contractEconomics": contract_gate, "riskReward": (expected_r >= 1.5) if expected_r is not None else None},
            "contract": ({"symbol": selected.get("symbol"), "strike": selected.get("strike"), "expiry": row.get("expiry"),
                          "ltp": selected.get("ltp"), "delta": selected.get("delta"), "gamma": selected.get("gamma"),
                          "theta": selected.get("theta"), "vega": selected.get("vega"), "iv": selected.get("iv")} if selected else None),
            "breadth": breadth, "structure": structure, "vixRegime": regime, "indiaVix": vix, "expectedR": expected_r,
            "dataLimitations": [value for value in (row.get("greeksError"),
                               None if direction else "INDEX_CANDLE_STRUCTURE_NOT_CONFIRMED",
                               None if breadth.get("aligned") is not None else "WEIGHTED_CONSTITUENT_BREADTH_NOT_CONFIRMED",
                               "RISK_REWARD_NOT_YET_CONFIRMED") if value],
        }
    return {"indices": converted}
