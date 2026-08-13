"""Swing universe pre-filter. DETERMINISTIC_BUY_V1 lock gates are unchanged.

Chartink has no official free API. This module tries Chartink's public
screener/process endpoint (CSRF session, same as the website) then falls
back to Yahoo Finance via yfinance on Nifty 500 snapshot symbols.

Passing names only reorder the hunt. Lock still requires desk VWAP/EMA9/RSI,
R1, bullish OI, promoter, wick, angle, turnover, and risk veto.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional runtime dependency
    yf = None

from .feed_scanner import SWING_MIN_PRICE
from .market_snapshot_store import readable_market_snapshot_path
from .stock_quality import MIN_RSI_PIVOT, MIN_VOLUME_MULTIPLIER

log = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parent.parent
_SNAPSHOT_PATH = _APP_DIR / "data" / "swing_prefilter_snapshot.json"
_TTL_SEC = float(os.environ.get("SWING_PREFILTER_TTL_SEC", "900"))
_CHARTINK_SCAN = (
    "( {cash} ( latest close > 50 and latest close > latest ema( close , 9 ) "
    "and latest rsi( 14 ) > 55 and latest rsi( 14 ) < 75 "
    "and latest volume > 1.5 * latest sma( volume , 20 ) "
    "and latest close > latest vwap ) )"
)
_CHARTINK_URL = "https://chartink.com/screener/process"
_CHARTINK_HOME = "https://chartink.com/screener/"

def snapshot_path() -> Path:
    return _SNAPSHOT_PATH


def passes_prefilter_metrics(
    *,
    close: float | None,
    ema9: float | None,
    rsi: float | None,
    volume: float | None,
    volume_sma20: float | None,
) -> bool:
    if close is None or close < SWING_MIN_PRICE:
        return False
    if ema9 is None or close <= ema9:
        return False
    if rsi is None or rsi < MIN_RSI_PIVOT:
        return False
    if volume is None or volume_sma20 is None or volume_sma20 <= 0:
        return False
    return volume >= MIN_VOLUME_MULTIPLIER * volume_sma20


def load_prefilter_snapshot() -> dict[str, Any]:
    try:
        if not _SNAPSHOT_PATH.is_file():
            return {}
        raw = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        log.warning("swing prefilter snapshot read failed: %s", exc)
        return {}


def load_prefilter_symbols() -> set[str]:
    snap = load_prefilter_snapshot()
    symbols = snap.get("symbols") if isinstance(snap.get("symbols"), list) else []
    return {str(s).upper().strip() for s in symbols if str(s).strip()}


def _universe_from_matrix() -> list[str]:
    path = readable_market_snapshot_path()
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        snap = {}
    out: list[str] = []
    seen: set[str] = set()
    stocks = snap.get("stocks") if isinstance(snap.get("stocks"), list) else []
    quotes = snap.get("stockQuotes") if isinstance(snap.get("stockQuotes"), dict) else {}
    for row in list(stocks) + list(quotes.values()):
        if not isinstance(row, dict):
            continue
        sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    seed = _APP_DIR / "data" / "nifty500_symbols.json"
    if not out and seed.is_file():
        try:
            raw = json.loads(seed.read_text(encoding="utf-8"))
            for sym in raw.get("symbols") or []:
                key = str(sym).upper().strip()
                if key and key not in seen:
                    seen.add(key)
                    out.append(key)
        except Exception as exc:
            log.warning("nifty500 seed read failed: %s", exc)
    return out


def _write_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _chartink_scan(universe: set[str], timeout: float = 12.0) -> dict[str, Any] | None:
    try:
        with requests.Session() as session:
            home = session.get(_CHARTINK_HOME, timeout=timeout)
            home.raise_for_status()
            csrf_match = re.search(
                r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
                home.text,
                flags=re.I,
            )
            if not csrf_match:
                csrf_match = re.search(r'csrf-token["\']\s+content=["\']([^"\']+)', home.text, flags=re.I)
            if not csrf_match:
                return None
            session.headers.update({
                "X-CSRF-TOKEN": csrf_match.group(1),
                "X-Requested-With": "XMLHttpRequest",
                "Referer": _CHARTINK_HOME,
            })
            resp = session.post(_CHARTINK_URL, data={"scan_clause": _CHARTINK_SCAN}, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        log.info("Chartink prefilter unavailable: %s", exc)
        return None
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return None
    symbols: list[str] = []
    details: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("nsecode") or row.get("symbol") or row.get("nse_code") or "").upper().strip()
        if not sym:
            continue
        if universe and sym not in universe:
            continue
        symbols.append(sym)
        details.append({
            "symbol": sym,
            "close": row.get("close"),
            "perChange": row.get("per_chg") or row.get("perChange"),
            "volume": row.get("volume"),
        })
    return {
        "source": "chartink_process",
        "scanClause": _CHARTINK_SCAN,
        "symbols": symbols,
        "rows": details,
        "rawCount": len(rows),
    }


def _yahoo_scan(universe: list[str]) -> dict[str, Any] | None:
    if not universe or yf is None:
        if yf is None:
            log.warning("yfinance missing")
        return None
    tickers = [f"{sym}.NS" for sym in universe]
    try:
        frame = yf.download(
            tickers,
            period="60d",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=False,
        )
    except Exception as exc:
        log.warning("yfinance download failed: %s", exc)
        return None
    if frame is None or getattr(frame, "empty", True):
        return None

    symbols: list[str] = []
    details: list[dict[str, Any]] = []
    for sym in universe:
        col = f"{sym}.NS"
        try:
            if col in frame.columns.get_level_values(0):
                hist = frame[col].dropna(how="all")
            elif len(universe) == 1:
                hist = frame.dropna(how="all")
            else:
                continue
            if hist is None or len(hist) < 21:
                continue
            close_s = hist["Close"].astype(float)
            vol_s = hist["Volume"].astype(float)
            close = float(close_s.iloc[-1])
            ema9 = float(close_s.ewm(span=9, adjust=False).mean().iloc[-1])
            delta = close_s.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi_s = 100 - (100 / (1 + rs))
            rsi_val = float(rsi_s.iloc[-1]) if rsi_s.notna().iloc[-1] else None
            vol = float(vol_s.iloc[-1])
            vol_sma = float(vol_s.rolling(20).mean().iloc[-1]) if len(vol_s) >= 20 else None
        except Exception:
            continue
        if not passes_prefilter_metrics(
            close=close, ema9=ema9, rsi=rsi_val, volume=vol, volume_sma20=vol_sma,
        ):
            continue
        symbols.append(sym)
        details.append({
            "symbol": sym,
            "close": round(close, 2),
            "ema9": round(ema9, 2),
            "rsi": None if rsi_val is None else round(rsi_val, 2),
            "volume": int(vol),
            "volumeSma20": None if vol_sma is None else round(vol_sma, 2),
        })
    return {
        "source": "yfinance",
        "symbols": symbols,
        "rows": details,
        "universeCount": len(universe),
    }


def refresh_swing_prefilter(*, force: bool = False) -> dict[str, Any]:
    existing = load_prefilter_snapshot()
    if not force and existing:
        try:
            epoch = float(existing.get("refreshedAtEpoch") or 0)
        except (TypeError, ValueError):
            epoch = 0.0
        if epoch <= 0:
            try:
                epoch = datetime.fromisoformat(str(existing.get("refreshedAt")).replace("Z", "+00:00")).timestamp()
            except Exception:
                epoch = 0.0
        if epoch > 0 and (time.time() - epoch) < _TTL_SEC and existing.get("symbols"):
            return {**existing, "cacheHit": True}

    universe = _universe_from_matrix()
    universe_set = set(universe)
    chartink = _chartink_scan(universe_set)
    yahoo = None if chartink and chartink.get("symbols") else _yahoo_scan(universe)
    chosen = chartink if chartink and chartink.get("symbols") else yahoo
    if not chosen:
        payload = {
            "success": False,
            "error": "No free screener source returned symbols",
            "refreshedAt": datetime.now(timezone.utc).isoformat(),
            "refreshedAtEpoch": time.time(),
            "symbols": [],
            "rows": [],
            "universeCount": len(universe),
            "tried": ["chartink_process", "yfinance"],
            "lockContract": "DETERMINISTIC_BUY_V1",
            "note": "Pre-filter only. Desk lock gates unchanged.",
        }
        return _write_snapshot(payload)

    payload = {
        "success": True,
        "cacheHit": False,
        "refreshedAt": datetime.now(timezone.utc).isoformat(),
        "refreshedAtEpoch": time.time(),
        "source": chosen.get("source"),
        "symbols": chosen.get("symbols") or [],
        "rows": chosen.get("rows") or [],
        "count": len(chosen.get("symbols") or []),
        "universeCount": len(universe),
        "scanClause": chosen.get("scanClause"),
        "lockContract": "DETERMINISTIC_BUY_V1",
        "note": "Pre-filter only. DETERMINISTIC_BUY_V1 lock gates unchanged.",
    }
    return _write_snapshot(payload)
