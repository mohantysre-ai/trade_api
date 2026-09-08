"""Governed adapter from the market feed into Swing V2 facts.

This module may perform I/O; the feature, setup, rank and risk modules remain
pure.  Any failed official-source refresh leaves the corresponding current-day
flag false so the decision engine fails closed.
"""
from __future__ import annotations

import csv
import io
import math
import os
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from .config import load_config
from .regime import classify_regime
from .universe import point_in_time_members, refresh_official_membership

ASM_URLS = (
    "https://archives.nseindia.com/content/equities/ASM.csv",
    "https://archives.nseindia.com/content/equities/GSM.csv",
    "https://archives.nseindia.com/content/equities/ESM.csv",
)
NSE_BOARD_MEETINGS_URL = "https://www.nseindia.com/api/corporate-board-meetings"
_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-board-meetings",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
}


def _universe_dir() -> Path:
    return Path(os.getenv("SWING_V2_UNIVERSE_DIR", str(Path(__file__).resolve().parents[2] / "data" / "swing_v2_universe")))


def _membership(day: date) -> tuple[list[dict[str, Any]], bool, str | None]:
    target = _universe_dir() / f"{day.isoformat()}.json"
    try:
        if target.is_file():
            import json

            payload = json.loads(target.read_text(encoding="utf-8-sig"))
        else:
            payload = refresh_official_membership(str(_universe_dir()), effective_date=day)
        rows = point_in_time_members(payload.get("constituents") or [], day)
        count = len({str(row.get("symbol") or "") for row in rows})
        return rows, 745 <= count <= 755, None
    except Exception as exc:
        return [], False, str(exc)


def _surveillance() -> tuple[set[str], bool, str | None]:
    restricted: set[str] = set()
    try:
        for url in ASM_URLS:
            response = requests.get(url, headers=_HEADERS, timeout=(5, 20))
            response.raise_for_status()
            for row in csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))):
                upper = {str(key).upper(): value for key, value in row.items()}
                symbol = upper.get("SYMBOL") or upper.get("SYMBOL NAME") or upper.get("SCRIP")
                if symbol:
                    restricted.add(str(symbol).replace("-EQ", "").strip().upper())
        return restricted, True, None
    except Exception as exc:
        return set(), False, str(exc)


def _result_events(day: date) -> tuple[set[str], bool, str | None]:
    through = day + timedelta(days=5)
    try:
        session = requests.Session()
        session.headers.update(_HEADERS)
        session.get("https://www.nseindia.com/", timeout=(5, 15))
        response = session.get(
            NSE_BOARD_MEETINGS_URL,
            params={"index": "equities", "from_date": day.strftime("%d-%m-%Y"), "to_date": through.strftime("%d-%m-%Y")},
            timeout=(5, 20),
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        symbols = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            purpose = str(row.get("bm_desc") or row.get("purpose") or row.get("bmPurpose") or "").lower()
            symbol = str(row.get("symbol") or row.get("sm_name") or "").replace("-EQ", "").strip().upper()
            if symbol and any(term in purpose for term in ("financial result", "quarterly result", "annual result")):
                symbols.add(symbol)
        return symbols, True, None
    except Exception as exc:
        return set(), False, str(exc)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _percentiles(values: dict[str, float], *, ascending: bool = True) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]), reverse=not ascending)
    denominator = max(1, len(ordered) - 1)
    return {symbol: round(index / denominator * 100.0, 4) for index, (symbol, _) in enumerate(ordered)}


def _iso_timestamp(value: Any, fallback: str) -> str:
    if isinstance(value, (int, float)) or str(value or "").isdigit():
        raw = float(value)
        if raw > 1e12:
            raw /= 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return fallback


def _regime_from_market(prepared: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [row for row in prepared if _number(row.get("ema20Daily")) and _number(row.get("decisionPrice")) and _number(row.get("return5dRaw")) is not None]
    breadth = 100.0 * sum(float(row["decisionPrice"]) > float(row["ema20Daily"]) for row in usable) / len(usable) if usable else None
    market_5d = statistics.median(float(row["return5dRaw"]) for row in usable) * 100 if usable else None
    try:
        import yfinance as yf

        index = yf.Ticker("^CRSLDX").history(period="3mo", interval="1d")["Close"].dropna().tolist()
        vix = yf.Ticker("^INDIAVIX").history(period="18mo", interval="1d")["Close"].dropna().tolist()
        index_close = float(index[-1]) if len(index) >= 20 else None
        alpha = 2 / 21
        ema = float(index[0]) if index else 0.0
        for value in index:
            ema = float(value) * alpha + ema * (1 - alpha)
        vix_current = float(vix[-1]) if vix else None
        vix_percentile = 100.0 * sum(float(value) <= vix_current for value in vix[-252:]) / len(vix[-252:]) if vix_current and vix else None
        vix_change = (vix[-1] / vix[-2] - 1) * 100 if len(vix) >= 2 else None
    except Exception:
        index_close = ema = vix_percentile = vix_change = None
    return classify_regime({"nifty500Close": index_close, "nifty500Ema20": ema or None, "breadthAboveEma20Pct": breadth, "nifty500Return5dPct": market_5d, "vixPercentile": vix_percentile, "vixChange1dPct": vix_change})


def enrich_v2_market_snapshot(payload: dict[str, Any], all_stocks: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    cfg = load_config()
    if not cfg.enabled:
        return payload
    members, universe_current, universe_error = _membership(now.date())
    member_by = {str(row.get("symbol") or "").upper(): row for row in members}
    active_members = {symbol for symbol, row in member_by.items() if str(row.get("universeSegment") or "").upper() in set(cfg.active_segments)}
    if not active_members:
        active_members = {str(row.get("ticker") or "").upper() for row in all_stocks}
    restricted, surveillance_current, surveillance_error = _surveillance()
    result_events, corporate_current, corporate_error = _result_events(now.date())
    quote_symbols = {str(row.get("ticker") or "").upper() for row in all_stocks if _number(row.get("ltpRaw"))}
    coverage = len(active_members & quote_symbols) / len(active_members) if active_members else 0.0
    prepared: list[dict[str, Any]] = []
    for row in all_stocks:
        symbol = str(row.get("ticker") or "").upper()
        raw = (row.get("intraday") or {}).get("swingV2Raw")
        if not isinstance(raw, dict):
            continue
        membership = member_by.get(symbol) or {}
        segment = str(membership.get("universeSegment") or "").upper()
        if segment not in set(cfg.active_segments) and segment != "NIFTY_MICROCAP250":
            continue
        price = _number(row.get("ltpRaw")) or 0.0
        high, low = _number(row.get("high")), _number(row.get("low"))
        vwap = _number((row.get("intraday") or {}).get("vwap"))
        atr = _number(raw.get("atr14"))
        prior_high = _number(raw.get("prior20dHigh"))
        bid, ask = _number(row.get("bestBid")), _number(row.get("bestAsk"))
        spread = ((ask - bid) / ((ask + bid) / 2) * 100) if ask and bid and ask >= bid else None
        day_range = (high - low) if high is not None and low is not None and high > low else None
        clv = ((price - low) / day_range) if day_range else None
        structure_stop = None
        if atr and price > 0:
            candidates = [value for value in (vwap, prior_high - 0.25 * atr if prior_high else None) if value and value < price]
            structure_stop = max(candidates) if candidates else price - atr
        risk_distance = max(price - structure_stop, 0.8 * atr) if structure_stop and atr else None
        next_high = _number(raw.get("previous52wHigh"))
        capacity = max(1.5, (next_high - price) / risk_distance) if next_high and risk_distance and next_high > price else (1.5 if risk_distance else 0.0)
        upper, lower = _number(row.get("upperCircuit")), _number(row.get("lowerCircuit"))
        last3 = raw.get("last3Closes") if isinstance(raw.get("last3Closes"), list) else []
        quote_stamp = str(row.get("quoteReceivedAt") or now.astimezone(timezone.utc).isoformat())
        bars_stamp = _iso_timestamp(raw.get("last5mTimestamp"), quote_stamp)
        record = {
            **raw, "symbol": symbol, "universeSegment": segment,
            "sector": membership.get("industry") or "UNKNOWN", "decisionPrice": price,
            "bestAsk": ask, "availableAskDepth": row.get("availableAskDepth"), "spreadPct": spread,
            "modeledRoundTripCostPct": (spread * 2 + 0.12) if spread is not None else None,
            "dayLow": low, "dayHigh": high, "tickSize": 0.05, "vwap": vwap,
            "clv": clv, "rvolPaced": _number((row.get("intraday") or {}).get("volume_multiplier")),
            "breakoutDistanceAtr": ((price - prior_high) / atr) if prior_high and atr else None,
            "distanceToPrior20dHighAtr": ((price - prior_high) / atr) if prior_high and atr else None,
            "extensionAtr": ((price - float(raw["ema20Daily"])) / atr) if raw.get("ema20Daily") and atr else None,
            "intradayLowToVwapAtr": ((float(raw["intradayLow"]) - vwap) / atr) if raw.get("intradayLow") and vwap and atr else None,
            "last3ClosesAboveVwap": bool(len(last3) == 3 and vwap and all(float(value) > vwap for value in last3)),
            "lastCloseAboveEma9": bool(last3 and _number((row.get("intraday") or {}).get("ema9")) and float(last3[-1]) > float((row.get("intraday") or {})["ema9"])),
            "decisionAboveVwap": bool(vwap and price > vwap), "structureStop": structure_stop,
            "upsideCapacityR": capacity, "plannedMaxBlendedR": 1.5,
            "expectedNetR": None, "expectedNetRStatus": "UNRATED",
            "dailyBarsThroughPreviousClose": bool(raw.get("dailyBarsThroughPreviousClose")),
            "corporateEventsCurrent": corporate_current, "surveillanceCurrent": surveillance_current,
            "universeCurrent": universe_current, "surveillanceRestricted": symbol in restricted,
            "scheduledResultBeforeD2": symbol in result_events,
            "nearPriceBand": bool(price and ((upper and abs(upper - price) / price <= .01) or (lower and abs(price - lower) / price <= .01))),
            "stressedExitCapacityFailed": False,
            "sourceTimestamps": {"quote": quote_stamp, "depth": quote_stamp if ask and row.get("availableAskDepth") else None, "bars5m": bars_stamp},
        }
        prepared.append(record)
    sector_returns: dict[str, list[float]] = defaultdict(list)
    for row in prepared:
        if _number(row.get("return5dRaw")) is not None:
            sector_returns[str(row.get("sector") or "UNKNOWN")].append(float(row["return5dRaw"]))
    sector_medians = {key: statistics.median(values) for key, values in sector_returns.items() if values}
    for row in prepared:
        sector_value = sector_medians.get(str(row.get("sector") or "UNKNOWN"))
        return5 = _number(row.get("return5dRaw"))
        row["trendPriorRaw"] = statistics.mean([value for value in (_number(row.get("mom6mRaw")), _number(row.get("mom12mRaw"))) if value is not None]) if any(value is not None for value in (_number(row.get("mom6mRaw")), _number(row.get("mom12mRaw"))) ) else None
        row["residualStrengthRaw"] = return5 - sector_value if return5 is not None and sector_value is not None else None
        row["sectorStrengthRaw"] = sector_value
    factor_map = {
        "trendPriorPctile": ("trendPriorRaw", True), "residualStrengthPctile": ("residualStrengthRaw", True),
        "setupQualityPctile": ("breakoutDistanceAtr", False), "rvolPctile": ("rvolPaced", True),
        "clvPctile": ("clv", True), "sectorStrengthPctile": ("sectorStrengthRaw", True),
        "liquidityPctile": ("modeledRoundTripCostPct", False),
    }
    by_symbol = {row["symbol"]: row for row in prepared}
    for output, (source, higher_better) in factor_map.items():
        values = {row["symbol"]: float(row[source]) for row in prepared if _number(row.get(source)) is not None}
        pct = _percentiles(values, ascending=higher_better)
        for symbol, value in pct.items():
            by_symbol[symbol][output] = value
    for row in all_stocks:
        enriched = by_symbol.get(str(row.get("ticker") or "").upper())
        if enriched:
            row["swingV2"] = enriched
    regime = _regime_from_market(prepared)
    payload.update({
        "swingV2SchemaVersion": "swing_market_facts_v2", "swingV2UniverseSize": len(active_members),
        "swingV2UniverseCoverage": coverage, "swingV2DiscoveryUniverseSize": len(member_by),
        "swingV2Regime": regime.get("state"), "swingV2RegimeDetail": regime,
        "swingV2DataStatus": {"universeCurrent": universe_current, "surveillanceCurrent": surveillance_current, "corporateEventsCurrent": corporate_current, "featureRows": len(prepared), "errors": [value for value in (universe_error, surveillance_error, corporate_error) if value]},
    })
    return payload


__all__ = ["enrich_v2_market_snapshot"]
