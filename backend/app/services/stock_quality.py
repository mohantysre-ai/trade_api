"""Short-term investment quality gates for the Asset Matrix pipeline.

Combines promoter-holding checks (NSE), liquidity/momentum technicals,
pivot + RSI breakout, and OI/bulk-style volume signals.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .bulk_deals import (
    BULK_DEAL_LOOKBACK_HOURS,
    MIN_BULK_DEAL_VALUE_CR,
    REQUIRE_BULK_DEAL,
    attach_bulk_deal_metrics,
)

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PROMOTER_HOLDINGS_PATH = BASE_DIR.parent / "data" / "promoter_holdings.json"

MIN_PROMOTER_HOLDING_PCT = float(os.getenv("MIN_PROMOTER_HOLDING_PCT", "60"))
MIN_VOLUME_MULTIPLIER = float(os.getenv("MIN_VOLUME_MULTIPLIER", "1.5"))
MIN_TURNOVER_CR = float(os.getenv("MIN_TURNOVER_CR", "50"))
MIN_RSI_PIVOT = float(os.getenv("MIN_RSI_PIVOT", "55"))
REQUIRE_PIVOT_R1_BREAKOUT = os.getenv("REQUIRE_PIVOT_R1_BREAKOUT", "true").strip().lower() in {
    "1",
    "true",
    "yes",
}
ALLOW_UNKNOWN_PROMOTER = os.getenv("ALLOW_UNKNOWN_PROMOTER", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}

_DEFAULT_RISKY_SYMBOLS = {
    "YESBANK",
    "OLAELEC",
    "PAYTM",
    "NYKAA",
    "ZOMATO",
    "DELHIVERY",
    "IRCON",
    "SUZLON",
    "IDEA",
    "VODAFONE",
}


def risky_symbol_denylist() -> set[str]:
    extra = os.getenv("RISKY_SYMBOL_DENYLIST", "")
    symbols = set(_DEFAULT_RISKY_SYMBOLS)
    for token in extra.split(","):
        cleaned = token.strip().upper()
        if cleaned:
            symbols.add(cleaned)
    return symbols


def is_risky_symbol(symbol: str) -> bool:
    return symbol.upper() in risky_symbol_denylist()


def classic_pivots(prev_high: float, prev_low: float, prev_close: float) -> dict[str, float]:
    pivot = (prev_high + prev_low + prev_close) / 3.0
    range_ = prev_high - prev_low
    return {
        "pivot": round(pivot, 2),
        "r1": round((2 * pivot) - prev_low, 2),
        "s1": round((2 * pivot) - prev_high, 2),
        "r2": round(pivot + range_, 2),
        "s2": round(pivot - range_, 2),
    }


def _load_promoter_cache() -> dict[str, float]:
    try:
        raw = json.loads(PROMOTER_HOLDINGS_PATH.read_text(encoding="utf-8"))
        holdings = raw.get("holdings") or {}
        return {str(k).upper(): float(v) for k, v in holdings.items() if v is not None}
    except Exception:
        return {}


def _save_promoter_cache(holdings: dict[str, float]) -> None:
    PROMOTER_HOLDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMOTER_HOLDINGS_PATH.write_text(
        json.dumps(
            {
                "refreshedAt": datetime.now(timezone.utc).isoformat(),
                "count": len(holdings),
                "holdings": holdings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def fetch_promoter_holding_pct(symbol: str) -> float | None:
    """Fetch latest promoter + promoter-group holding % from NSE."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
            "Accept": "application/json, text/plain, */*",
        }
    )
    try:
        session.get("https://www.nseindia.com", timeout=20)
        response = session.get(
            "https://www.nseindia.com/api/corporate-share-holdings-master",
            params={"index": "equities", "symbol": symbol.upper()},
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            return None
        latest = rows[0]
        raw_pct = latest.get("pr_and_prgrp")
        if raw_pct in (None, "", "-"):
            return None
        return float(str(raw_pct).replace(",", "").strip())
    except Exception as exc:
        log.debug("Promoter holding fetch failed for %s: %s", symbol, exc)
        return None


def ensure_promoter_holdings(symbols: list[str]) -> dict[str, float]:
    """Return promoter % map for symbols, fetching and caching any missing entries."""
    cache = _load_promoter_cache()
    updated = False
    for symbol in symbols:
        key = symbol.upper()
        if key in cache:
            continue
        pct = fetch_promoter_holding_pct(key)
        if pct is not None:
            cache[key] = pct
            updated = True
        time.sleep(0.2)
    if updated:
        _save_promoter_cache(cache)
    return cache


def attach_pivot_metrics(
    metrics: dict[str, Any],
    ltp: float,
    daily_candles: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(daily_candles) >= 2:
        prev = daily_candles[-2]
        pivots = classic_pivots(
            float(prev.get("high") or 0),
            float(prev.get("low") or 0),
            float(prev.get("close") or 0),
        )
    else:
        pivots = {"pivot": 0.0, "r1": 0.0, "s1": 0.0, "r2": 0.0, "s2": 0.0}

    rsi_val = float(metrics.get("rsi") or 0)
    pivot = float(pivots["pivot"] or 0)
    r1 = float(pivots["r1"] or 0)

    metrics.update(
        {
            "pivot": pivots["pivot"],
            "pivot_r1": pivots["r1"],
            "pivot_s1": pivots["s1"],
            "pivot_r2": pivots["r2"],
            "pivot_s2": pivots["s2"],
            "above_pivot": bool(pivot and ltp > pivot),
            "pivot_r1_breakout": bool(r1 and ltp > r1),
            "rsi_pivot_break": bool(rsi_val >= MIN_RSI_PIVOT and pivot and ltp > pivot),
        }
    )
    return metrics


def evaluate_short_term_quality(
    symbol: str,
    intraday: dict[str, Any],
    promoter_holding_pct: float | None,
) -> tuple[bool, list[str]]:
    """Apply short-term investment buy gates on top of intraday metrics."""
    reasons: list[str] = []
    key = symbol.upper()

    if is_risky_symbol(key):
        reasons.append("symbol on risky denylist")

    if promoter_holding_pct is None:
        if not ALLOW_UNKNOWN_PROMOTER:
            reasons.append("promoter holding unknown")
    elif promoter_holding_pct < MIN_PROMOTER_HOLDING_PCT:
        reasons.append(f"promoter holding under {MIN_PROMOTER_HOLDING_PCT:g}%")

    if not intraday.get("price_above_vwap"):
        reasons.append("below VWAP")
    if not intraday.get("price_above_ema9"):
        reasons.append("below EMA9")

    rsi_val = float(intraday.get("rsi") or 0)
    if rsi_val < MIN_RSI_PIVOT:
        reasons.append(f"RSI below {MIN_RSI_PIVOT:g}")

    if REQUIRE_PIVOT_R1_BREAKOUT and not intraday.get("pivot_r1_breakout"):
        reasons.append("no pivot R1 breakout")
    elif not intraday.get("rsi_pivot_break"):
        reasons.append("no RSI pivot confirmation")

    vol_mult = float(intraday.get("volume_multiplier") or 0)
    if vol_mult < MIN_VOLUME_MULTIPLIER:
        reasons.append(f"volume multiplier under {MIN_VOLUME_MULTIPLIER:g}x")

    turnover = float(intraday.get("turnover_cr") or 0)
    if turnover < MIN_TURNOVER_CR:
        reasons.append(f"turnover under {MIN_TURNOVER_CR:g} Cr")

    oi_setup = str(intraday.get("oi_setup") or "NEUTRAL")
    if oi_setup not in {"LONG_BUILDUP", "SHORT_COVERING"}:
        reasons.append(f"OI setup not bullish ({oi_setup})")

    ema_angle = float(intraday.get("ema_angle_deg") or 0)
    if ema_angle <= 45.0:
        reasons.append("EMA angle below 45 degrees")

    wick_noise = float(intraday.get("wick_noise_ratio") or 1.0)
    if wick_noise > 0.25:
        reasons.append("wick noise too high")

    if REQUIRE_BULK_DEAL and not intraday.get("bulk_deal_signal"):
        reasons.append(
            f"no bulk/block deal >= {MIN_BULK_DEAL_VALUE_CR:g} Cr "
            f"in last {BULK_DEAL_LOOKBACK_HOURS}h"
        )

    return len(reasons) == 0, reasons


def enrich_stock_quality(
    stock: dict[str, Any],
    promoter_map: dict[str, float],
    bulk_deal_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach promoter + quality flags to a stock row."""
    ticker = str(stock.get("ticker") or "").upper()
    intraday = dict(stock.get("intraday") or {})
    promoter_pct = promoter_map.get(ticker)
    intraday["promoter_holding_pct"] = promoter_pct
    attach_bulk_deal_metrics(intraday, (bulk_deal_map or {}).get(ticker))

    passes_quality, quality_reasons = evaluate_short_term_quality(ticker, intraday, promoter_pct)
    intraday["passes_quality_filters"] = passes_quality
    intraday["quality_filter_reasons"] = quality_reasons

    # Short-term profile: technical + quality gates must both pass.
    intraday["passes_hard_filters"] = bool(
        intraday.get("passes_hard_filters") and passes_quality
    )
    if not passes_quality:
        merged = list(intraday.get("hard_filter_reasons") or [])
        for reason in quality_reasons:
            if reason not in merged:
                merged.append(reason)
        intraday["hard_filter_reasons"] = merged

    stock["intraday"] = intraday
    stock["promoter_holding_pct"] = promoter_pct
    stock["passes_quality_filters"] = passes_quality
    stock["bulk_deal_value_cr"] = intraday.get("bulk_deal_value_cr", 0.0)
    stock["bulk_deal_signal"] = bool(intraday.get("bulk_deal_signal"))
    return stock
