"""
Angel One market feed for the IROS terminal.

This service fetches live Angel One quotes, lets the LLM rank the full live
universe using a filter prompt, and exposes the top selected stocks as the
active market list.
"""

from __future__ import annotations

import argparse
import json
import os
import math
import re
import sys
import threading
import time
import httpx # Added for internal API calls
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pyotp
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from SmartApi import SmartConnect

from global_feed import (
    fetch_domestic_index_macro,
    fetch_domestic_yahoo_macro,
    fetch_global_macro,
    fetch_gift_nifty,
)
from symbols import MACRO_INSTRUMENTS, MOCK_TICKERS, WATCHLIST, Instrument
from terminal_intelligence_full import (
    CompleteSecurityAnalysisPayload,
    TOP_SELECTION_COUNT,
    _on_demand_ticker_selection_reason,
    build_ticker_intelligence_map,
    build_ticker_intelligence_report,
    execute_terminal_intelligence_pipeline,
)

_TI_TOP_SELECTION_COUNT = TOP_SELECTION_COUNT

ORCHESTRATION_DELAY = 30


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

NIFTY_500_CACHE_PATH = BASE_DIR / "nifty500_instruments.json"
NIFTY_500_LABEL = "Nifty 500"

IST_ZONE = ZoneInfo("Asia/Kolkata")
SNAPSHOT_PATH = BASE_DIR / "last_market_snapshot.json"
MORNING_REFRESH_START = (8, 0)
MORNING_REFRESH_END = (8, 30)
EVENING_REFRESH_START = (16, 0)
EVENING_REFRESH_END = (16, 30)
REFRESH_TASK_TTL_SECONDS = 600
_REFRESH_TASKS: dict[str, dict[str, Any]] = {}
_REFRESH_TASK_LOCK = threading.Lock()
LLM_UNIVERSE_LIMIT = int(os.getenv("LLM_UNIVERSE_LIMIT", "30"))
NIFTY_100_LABEL = "Nifty 100"
NIFTY_100_CACHE_PATH = BASE_DIR / "nifty100_instruments.json"
ANGEL_API_TIMEOUT_SECONDS = int(os.getenv("ANGEL_API_TIMEOUT_SECONDS", "24"))
LLM_CALL_TIMEOUT_SECONDS = min(max(1, int(os.getenv("LLM_CALL_TIMEOUT_SECONDS", "60"))), 120)
QUOTE_CHUNK_SIZE = int(os.getenv("QUOTE_CHUNK_SIZE", "10"))
INTRADAY_CHUNK_SIZE = int(os.getenv("INTRADAY_CHUNK_SIZE", "10"))

AI_NEWS_API_URL = os.getenv("AI_NEWS_API_URL", "http://127.0.0.1:8001")


def _refresh_task_key(pool_name: str | None, custom_prompt: str | None) -> str:
    return f"refresh:{pool_name or '__all__'}:{(custom_prompt or '').strip()[:64]}"


def _refresh_task_status(task_id: str) -> dict[str, Any] | None:
    with _REFRESH_TASK_LOCK:
        task = _REFRESH_TASKS.get(task_id)
        if not task:
            return None
        if time.time() - task.get("created_at", 0) > REFRESH_TASK_TTL_SECONDS:
            del _REFRESH_TASKS[task_id]
            return None
        return {
            "status": task["status"],
            "progress": task.get("progress"),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "result": task.get("result"),
        }


def _refresh_task_set_done(task_id: str, result: dict[str, Any]) -> None:
    with _REFRESH_TASK_LOCK:
        if task_id in _REFRESH_TASKS:
            _REFRESH_TASKS[task_id]["status"] = "done"
            _REFRESH_TASKS[task_id]["result"] = result


def _refresh_task_set_error(task_id: str, error: str) -> None:
    with _REFRESH_TASK_LOCK:
        if task_id in _REFRESH_TASKS:
            _REFRESH_TASKS[task_id]["status"] = "error"
            _REFRESH_TASKS[task_id]["error"] = error


NEWS_FEEDS: list[tuple[str, str]] = [
    ("Zerodha Pulse", "https://pulse.zerodha.com/"),
    ("Trendlyne", "https://trendlyne.com/"),
    ("Finshots", "https://finshots.in/"),
    ("NSE NIFTY 100", "https://www.nseindia.com/index-tracker/NIFTY%20100"),
]

LIVE_UNIVERSE_LABEL = "Live Universe"


def _news_feed_sources() -> list[str]:
    return [source for source, _ in NEWS_FEEDS]


def _filter_prompt(custom_prompt: str | None = None) -> str:
    parts = []
    env_prompt = os.getenv("MARKET_FILTER_PROMPT", "").strip()
    if env_prompt:
        parts.append(env_prompt)
    if custom_prompt and custom_prompt.strip():
        parts.append(custom_prompt.strip())
    parts.append(
        "Use the live Angel One universe below to select the top "
        f"{_TI_TOP_SELECTION_COUNT} stocks. Prefer the Nifty 100 universe; do not restrict selection to Nifty 50 only. "
        "Do not invent tickers. Return valid JSON only."
    )
    return " ".join(parts)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_mpin() -> str:
    mpin = (os.getenv("ANGEL_MPIN") or os.getenv("REDACTED") or "").strip()
    if not mpin:
        raise RuntimeError("Missing ANGEL_MPIN or REDACTED in backend .env")
    if len(mpin) != 4 or not mpin.isdigit():
        raise RuntimeError("ANGEL_MPIN must be exactly 4 digits")
    return mpin


def _pct_change(ltp: float, close: float | None) -> tuple[str, str]:
    if close in (None, 0):
        return "0.00%", "POSITIVE"
    change = ((ltp - close) / close) * 100
    sign = "+" if change >= 0 else ""
    state = "POSITIVE" if change >= 0 else "NEGATIVE"
    return f"{sign}{change:.2f}%", state


def _format_inr(value: float) -> str:
    return f"₹{value:,.2f}"


def _snapshot_path() -> Path:
    return SNAPSHOT_PATH


def _ist_now() -> datetime:
    return datetime.now(tz=IST_ZONE)


def _within_refresh_window(now: datetime | None = None) -> bool:
    now = now or _ist_now()
    current_minutes = now.hour * 60 + now.minute
    morning_start = MORNING_REFRESH_START[0] * 60 + MORNING_REFRESH_START[1]
    morning_end = MORNING_REFRESH_END[0] * 60 + MORNING_REFRESH_END[1]
    evening_start = EVENING_REFRESH_START[0] * 60 + EVENING_REFRESH_START[1]
    evening_end = EVENING_REFRESH_END[0] * 60 + EVENING_REFRESH_END[1]
    return (morning_start <= current_minutes < morning_end) or (evening_start <= current_minutes < evening_end)


def _normalize_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    payload["rawSources"] = _news_feed_sources()
    available_pools = [pool for pool in payload.get("availablePools", []) if pool != "Nifty 50"]
    if NIFTY_100_LABEL not in available_pools:
        available_pools.insert(0, NIFTY_100_LABEL)
    if LIVE_UNIVERSE_LABEL not in available_pools:
        available_pools.append(LIVE_UNIVERSE_LABEL)
    payload["availablePools"] = available_pools
    payload.setdefault("activePool", NIFTY_100_LABEL)
    payload.setdefault("poolDescription", "Nifty 100 Angel One live universe ranked by your filter prompt.")
    return payload


def _load_watchlist_from_cache(path: Path) -> list[Instrument]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        instruments = raw.get("instruments", []) if isinstance(raw, dict) else []
        return [
            Instrument(
                key=str(item["key"]),
                exchange=str(item.get("exchange", "NSE")),
                tradingsymbol=str(item["tradingsymbol"]),
                token=str(item["token"]),
                label=str(item.get("label") or item["key"]),
            )
            for item in instruments
            if item.get("key") and item.get("token") and item.get("tradingsymbol")
        ]
    except Exception:
        return []


def _pool_watchlist(pool_name: str | None) -> tuple[list[Instrument], str]:
    resolved = pool_name or NIFTY_100_LABEL

    if resolved in ("Nifty 50", NIFTY_500_LABEL):
        resolved = NIFTY_100_LABEL

    if resolved == NIFTY_100_LABEL:
        nifty100 = _load_watchlist_from_cache(NIFTY_100_CACHE_PATH)
        if nifty100:
            return nifty100, NIFTY_100_LABEL
        nifty500 = _load_watchlist_from_cache(NIFTY_500_CACHE_PATH)
        if nifty500:
            return nifty500[:100], NIFTY_100_LABEL

    return WATCHLIST, resolved


def _payload_data_date(payload: dict[str, Any] | None = None) -> str:
    if payload:
        updated_at = payload.get("updatedAt")
        if isinstance(updated_at, str) and updated_at:
            return updated_at[:10]
    return _ist_now().date().isoformat()


def _apply_selection_meta(
    payload: dict[str, Any],
    *,
    mode: str,
    reason: str,
    data_date: str | None = None,
) -> dict[str, Any]:
    payload["selectionMeta"] = {
        "mode": mode,
        "reason": reason,
        "dataDate": data_date or _payload_data_date(payload),
    }
    return payload


def _hydrate_ticker_intelligence_map(payload: dict[str, Any]) -> dict[str, Any]:
    payload["tickerIntelligenceByTicker"] = build_ticker_intelligence_map(payload)
    return payload


def _load_last_snapshot() -> dict[str, Any] | None:
    try:
        payload = json.loads(_snapshot_path().read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return _normalize_snapshot(payload)
        return None
    except Exception:
        return None


def _save_last_snapshot(payload: dict[str, Any]) -> None:
    try:
        _snapshot_path().write_text(json.dumps(_normalize_snapshot(payload), indent=2), encoding="utf-8")
    except Exception:
        pass


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(re.sub(r"<[^>]+>", "", value).split()).strip()


def _parse_rss_datetime(date_text: str | None) -> str | None:
    if not date_text:
        return None
    formats = (
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S GMT",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(date_text.strip(), fmt)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return None


def _clean_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", "", html)


def _extract_html_items(source: str, url: str, limit: int = 3) -> list[dict[str, str]]:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36"}
    response = requests.get(url, timeout=15, headers=headers)
    response.raise_for_status()
    clean = _clean_html(response.text)
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    items: list[dict[str, str]] = []
    for line in lines[:limit]:
        if len(line) < 20:
            continue
        items.append(
            {
                "source": source,
                "title": line[:200],
                "link": url,
                "summary": line[:300],
                "publishedAt": _ist_now().isoformat(),
            }
        )
    return items


def fetch_live_news(limit: int = 10) -> list[dict[str, str]]:
    news: list[dict[str, str]] = []
    for source, url in NEWS_FEEDS:
        try:
            news.extend(_extract_html_items(source, url, limit=3))
        except Exception:
            continue
    news.sort(key=lambda item: item.get("publishedAt", ""), reverse=True)
    return news[:limit]


def _llm_config() -> tuple[str, str, str, str] | None:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    api_key = os.getenv("REDACTED", "").strip()
    gemini_key = os.getenv("REDACTED", "").strip()
    api_url = os.getenv("LLM_API_URL", "").strip()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()

    if provider == "gemini" and not api_key:
        api_key = gemini_key
    if not provider and gemini_key:
        provider = "gemini"
        api_key = gemini_key
    if not provider or not api_key:
        return None
    if not api_url and provider == "openai":
        api_url = "https://api.openai.com/v1/chat/completions"
    return provider, api_key, api_url, model


def _call_openai(prompt: str, api_key: str, api_url: str, model: str, timeout: int) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are an elite institutional financial terminal. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    if response.status_code >= 300:
        raise RuntimeError(f"OpenAI request failed ({response.status_code}): {response.text}")
    data = response.json()
    if not data.get("choices") or not data["choices"][0].get("message"):
        raise RuntimeError("OpenAI response missing expected content")
    return data["choices"][0]["message"]["content"].strip()


def _call_gemini(prompt: str, api_key: str, model: str, system_instruction: str, timeout: int) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("Gemini support requires google-genai. Install it in the backend venv.") from exc

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        response_mime_type="application/json",
        max_output_tokens=2000,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return getattr(response, "text", None) or getattr(response, "output_text", None) or str(response)


class AngelOneClient:
    def __init__(self) -> None:
        self.api_key = _require_env("REDACTED")
        self.client_id = _require_env("REDACTED")
        self.mpin = _get_mpin()
        self.totp_secret = _require_env("REDACTED")
        self._smart: SmartConnect | None = None

    def connect(self) -> SmartConnect:
        if self._smart is not None:
            return self._smart
        smart = SmartConnect(api_key=self.api_key, timeout=ANGEL_API_TIMEOUT_SECONDS)
        totp = pyotp.TOTP(self.totp_secret).now()
        session = smart.generateSession(self.client_id, self.mpin, totp)
        if not session.get("status"):
            raise RuntimeError(f"Angel One login failed: {session.get('message', 'Unknown login error')}")
        self._smart = smart
        return smart

    def fetch_quote(self, exchange: str, tradingsymbol: str, token: str) -> dict[str, Any]:
        smart = self.connect()
        response = smart.ltpData(exchange, tradingsymbol, token)
        if not response.get("status"):
            raise RuntimeError(f"{tradingsymbol}: {response.get('message', 'Quote fetch failed')}")
        return response["data"]

    def fetch_candles(
        self,
        exchange: str,
        symboltoken: str,
        interval: str,
        fromdate: datetime,
        todate: datetime,
    ) -> list[list[Any]]:
        smart = self.connect()
        params = {
            "exchange": exchange,
            "symboltoken": symboltoken,
            "interval": interval,
            "fromdate": fromdate.astimezone(IST_ZONE).strftime("%Y-%m-%d %H:%M"),
            "todate": todate.astimezone(IST_ZONE).strftime("%Y-%m-%d %H:%M"),
        }
        response = smart.getCandleData(params)
        if not response.get("status"):
            return []
        data = response.get("data") or []
        return data if isinstance(data, list) else []

    def fetch_batch_quotes(self, instruments: list[Instrument]) -> dict[str, dict[str, Any]]:
        smart = self.connect()
        token_to_key: dict[str, str] = {}

        for inst in instruments:
            token_to_key[inst.token] = inst.key

        def _chunked(items: list[Instrument], size: int = 25) -> list[list[Instrument]]:
            return [items[i : i + size] for i in range(0, len(items), size)]

        fetched: dict[str, dict[str, Any]] = {}
        for chunk in _chunked(instruments, size=25):
            tokens_by_exchange: dict[str, list[str]] = {}
            for inst in chunk:
                tokens_by_exchange.setdefault(inst.exchange, []).append(inst.token)

            try:
                response = smart.getMarketData("FULL", tokens_by_exchange)
            except Exception:
                response = {"status": False}

            if response.get("status"):
                for item in response.get("data", {}).get("fetched", []):
                    token = str(item.get("symbolToken", ""))
                    key = token_to_key.get(token)
                    if key:
                        fetched[key] = item
                continue

            for inst in chunk:
                try:
                    fetched[inst.key] = self.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
                except Exception:
                    continue

        missing = [inst for inst in instruments if inst.key not in fetched]
        for inst in missing:
            try:
                fetched[inst.key] = self.fetch_quote(inst.exchange, inst.tradingsymbol, inst.token)
            except Exception:
                continue

        return fetched


def _fetch_quote_chunk(
    smart: SmartConnect,
    chunk: list[Instrument],
    token_to_key: dict[str, str],
) -> dict[str, dict[str, Any]]:
    tokens_by_exchange: dict[str, list[str]] = {}
    for inst in chunk:
        tokens_by_exchange.setdefault(inst.exchange, []).append(inst.token)

    fetched: dict[str, dict[str, Any]] = {}
    try:
        response = smart.getMarketData("FULL", tokens_by_exchange)
        if response.get("status"):
            for item in response.get("data", {}).get("fetched", []):
                token = str(item.get("symbolToken", ""))
                key = token_to_key.get(token)
                if key:
                    fetched[key] = item
            return fetched
    except Exception:
        pass

    for inst in chunk:
        try:
            response = smart.ltpData(inst.exchange, inst.tradingsymbol, inst.token)
            if response.get("status"):
                fetched[inst.key] = response["data"]
        except Exception:
            continue
    return fetched


def _fetch_batch_quotes_chunked(
    self: AngelOneClient,
    instruments: list[Instrument],
) -> dict[str, dict[str, Any]]:
    smart = self.connect()
    token_to_key = {inst.token: inst.key for inst in instruments}
    chunks = [instruments[i : i + QUOTE_CHUNK_SIZE] for i in range(0, len(instruments), QUOTE_CHUNK_SIZE)]
    all_fetched: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        all_fetched.update(_fetch_quote_chunk(smart, chunk, token_to_key))

    return all_fetched


AngelOneClient.fetch_batch_quotes = _fetch_batch_quotes_chunked


def _build_stock_row(
    inst: Instrument,
    quote: dict[str, Any],
    active_pool: str,
    intraday: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ltp = float(quote.get("ltp", 0) or 0)
    close = float(quote.get("close", 0) or 0)
    delta, state = _pct_change(ltp, close if close else None)
    return {
        "ticker": inst.key,
        "name": (inst.label or inst.tradingsymbol).replace("-EQ", "").replace("-BE", "").replace("-", " ").strip(),
        "capSize": active_pool,
        "ltp": _format_inr(ltp),
        "ltpRaw": ltp,
        "delta": delta,
        "state": state,
        "volume": quote.get("tradeVolume"),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "intraday": intraday or {},
    }


def _parse_candle_rows(raw: list[list[Any]]) -> list[dict[str, Any]]:
    candles: list[dict[str, Any]] = []
    for row in raw or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        ts, open_, high, low, close, volume = row[:6]
        candles.append(
            {
                "ts": ts,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume or 0),
            }
        )
    return candles


def _ema(values: list[float], period: int = 9) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append((value * k) + (out[-1] * (1 - k)))
    return out


def _atr_percent(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: list[float] = []
    prev_close = candles[0]["close"]
    for candle in candles[1:]:
        tr = max(
            candle["high"] - candle["low"],
            abs(candle["high"] - prev_close),
            abs(candle["low"] - prev_close),
        )
        trs.append(tr)
        prev_close = candle["close"]
    if len(trs) < period:
        return 0.0
    atr = sum(trs[-period:]) / period
    close = candles[-1]["close"] or 1.0
    return (atr / close) * 100


def _vwap(candles: list[dict[str, Any]]) -> float:
    total_pv = 0.0
    total_vol = 0.0
    for candle in candles:
        vol = float(candle["volume"] or 0)
        typical = (candle["high"] + candle["low"] + candle["close"]) / 3.0
        total_pv += typical * vol
        total_vol += vol
    if total_vol <= 0:
        return 0.0
    return total_pv / total_vol


def _wick_noise_ratio(candles: list[dict[str, Any]]) -> float:
    total_range = 0.0
    total_wick = 0.0
    for candle in candles:
        candle_range = max(candle["high"] - candle["low"], 0.0)
        if candle_range <= 0:
            continue
        body_high = max(candle["open"], candle["close"])
        body_low = min(candle["open"], candle["close"])
        wick = (candle["high"] - body_high) + (body_low - candle["low"])
        total_range += candle_range
        total_wick += max(wick, 0.0)
    if total_range <= 0:
        return 1.0
    return total_wick / total_range


def _ema_angle_deg(ema_values: list[float]) -> float:
    if len(ema_values) < 6:
        return 0.0
    base = ema_values[-6] or 1.0
    latest = ema_values[-1] or base
    slope_pct = ((latest - base) / base) * 100.0
    return math.degrees(math.atan(slope_pct))


def _empty_intraday_metrics(reason: str) -> dict[str, Any]:
    return {
        "atr_pct": 0.0,
        "volume_multiplier": 0.0,
        "today_volume": 0.0,
        "avg_daily_volume_20": 0.0,
        "vwap": 0.0,
        "ema9": 0.0,
        "ema_angle_deg": 0.0,
        "orb_high": 0.0,
        "orb_low": 0.0,
        "orb_velocity_pct": 0.0,
        "wick_noise_ratio": 1.0,
        "turnover_cr": 0.0,
        "price_above_vwap": False,
        "price_above_ema9": False,
        "trigger_point": "VWAP Bounce",
        "passes_hard_filters": False,
        "hard_filter_reasons": [reason],
    }


def _intraday_metrics(
    client: AngelOneClient,
    inst: Instrument,
    ltp: float,
    now: datetime,
) -> dict[str, Any]:
    try:
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        daily_from = (now - timedelta(days=45)).replace(hour=9, minute=15, second=0, microsecond=0)
        daily_to = now

        daily_raw = client.fetch_candles(inst.exchange, inst.token, "ONE_DAY", daily_from, daily_to)
        intraday_raw = client.fetch_candles(inst.exchange, inst.token, "FIVE_MINUTE", market_open, now)

        daily_candles = _parse_candle_rows(daily_raw)
        intraday_candles = _parse_candle_rows(intraday_raw)
    except Exception:
        daily_candles = []
        intraday_candles = []

    if not daily_candles or not intraday_candles:
        return _empty_intraday_metrics("insufficient candle data")

    daily_close = daily_candles[-1]["close"] or ltp or 1.0
    daily_volumes = [row["volume"] for row in daily_candles[-20:]]
    avg_daily_volume_20 = (sum(daily_volumes) / len(daily_volumes)) if daily_volumes else 0.0
    atr_pct = _atr_percent(daily_candles)

    today_volume = sum(row["volume"] for row in intraday_candles)
    volume_multiplier = (today_volume / avg_daily_volume_20) if avg_daily_volume_20 > 0 else 0.0

    vwap = _vwap(intraday_candles)
    closes = [row["close"] for row in intraday_candles]
    ema9_values = _ema(closes, period=9)
    ema9 = ema9_values[-1] if ema9_values else 0.0
    ema_angle_deg = _ema_angle_deg(ema9_values)

    orb_window = intraday_candles[:3] if len(intraday_candles) >= 3 else intraday_candles
    orb_high = max((row["high"] for row in orb_window), default=0.0)
    orb_low = min((row["low"] for row in orb_window), default=0.0)
    orb_velocity_pct = ((ltp - orb_high) / orb_high) * 100 if orb_high and ltp >= orb_high else 0.0

    wick_noise_ratio = _wick_noise_ratio(intraday_candles)
    turnover_cr = (ltp * today_volume) / 10_000_000 if ltp and today_volume else 0.0

    price_above_vwap = bool(vwap and ltp > vwap)
    price_above_ema9 = bool(ema9 and ltp > ema9)

    hard_filter_reasons: list[str] = []
    if atr_pct <= 3.0:
        hard_filter_reasons.append("ATR under 3.0%")
    if volume_multiplier <= 3.0:
        hard_filter_reasons.append("opening volume under 3.0x")
    if wick_noise_ratio > 0.25:
        hard_filter_reasons.append("wick noise too high")
    if not price_above_vwap:
        hard_filter_reasons.append("below VWAP")
    if not price_above_ema9:
        hard_filter_reasons.append("below EMA9")
    if ema_angle_deg <= 45.0:
        hard_filter_reasons.append("EMA angle below 45 degrees")
    if turnover_cr < 50.0:
        hard_filter_reasons.append("turnover under 50 Cr")

    passes_hard_filters = len(hard_filter_reasons) == 0
    trigger_point = "VWAP Bounce" if price_above_vwap else "15-min ORB" if ltp >= orb_high else "Flag Breakout"

    return {
        "atr_pct": round(atr_pct, 2),
        "volume_multiplier": round(volume_multiplier, 2),
        "today_volume": round(today_volume, 0),
        "avg_daily_volume_20": round(avg_daily_volume_20, 0),
        "vwap": round(vwap, 2),
        "ema9": round(ema9, 2),
        "ema_angle_deg": round(ema_angle_deg, 2),
        "orb_high": round(orb_high, 2),
        "orb_low": round(orb_low, 2),
        "orb_velocity_pct": round(orb_velocity_pct, 2),
        "wick_noise_ratio": round(wick_noise_ratio, 3),
        "turnover_cr": round(turnover_cr, 2),
        "price_above_vwap": price_above_vwap,
        "price_above_ema9": price_above_ema9,
        "trigger_point": trigger_point,
        "passes_hard_filters": passes_hard_filters,
        "hard_filter_reasons": hard_filter_reasons,
    }


def _fetch_intraday_chunk(
    client: AngelOneClient,
    rows: list[dict[str, Any]],
    stock_universe_by_key: dict[str, Instrument],
    now: datetime,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for row in rows:
        inst = stock_universe_by_key.get(str(row["ticker"]))
        if not inst:
            continue
        try:
            metrics = _intraday_metrics(client, inst, float(row.get("ltpRaw", 0) or 0), now)
        except Exception:
            metrics = _empty_intraday_metrics("fetch error")
        results[str(row["ticker"])] = metrics
    return results


def _fetch_all_intraday_chunked(
    client: AngelOneClient,
    candidate_rows: list[dict[str, Any]],
    stock_universe_by_key: dict[str, Instrument],
    now: datetime,
) -> dict[str, dict[str, Any]]:
    chunks = [
        candidate_rows[i : i + INTRADAY_CHUNK_SIZE]
        for i in range(0, len(candidate_rows), INTRADAY_CHUNK_SIZE)
    ]
    all_metrics: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        all_metrics.update(_fetch_intraday_chunk(client, chunk, stock_universe_by_key, now))

    return all_metrics


def _heuristic_rank(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in stocks:
        ltp = float(row.get("ltpRaw") or 0)
        close = float(row.get("close") or 0)
        pct = abs(((ltp - close) / close) * 100) if close else 0.0
        volume = float(row.get("volume") or 0)
        intraday = row.get("intraday") or {}
        score = round(
            abs(pct) * 2.0
            + (0.0 if volume <= 0 else (len(str(int(volume))) - 1))
            + float(intraday.get("atr_pct") or 0.0)
            + float(intraday.get("volume_multiplier") or 0.0) * 2.0,
            2,
        )
        ranked.append({**row, "score": score})
    ranked.sort(key=lambda item: item.get("score", 0), reverse=True)
    return ranked[:_TI_TOP_SELECTION_COUNT]


def _coarse_pre_rank(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in stocks:
        ltp = float(row.get("ltpRaw") or 0)
        close = float(row.get("close") or 0)
        pct = abs(((ltp - close) / close) * 100) if close else 0.0
        volume = float(row.get("volume") or 0)
        score = round(abs(pct) * 2.0 + (0.0 if volume <= 0 else math.log10(volume + 1)), 2)
        ranked.append({**row, "_coarse_score": score})
    ranked.sort(key=lambda item: item.get("_coarse_score", 0), reverse=True)
    return ranked


def _hard_screen(stock: dict[str, Any]) -> bool:
    intraday = stock.get("intraday") or {}
    return bool(intraday.get("passes_hard_filters"))


def _compile_selection_stream(
    all_stocks: list[dict[str, Any]],
    pool_name: str,
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    hard_screen_count: int,
    custom_prompt: str | None = None,
) -> str:
    lines = [
        f"TOP_N: {_TI_TOP_SELECTION_COUNT}",
        f"ACTIVE_POOL: {pool_name}",
        f"FILTER_PROMPT: {_filter_prompt(custom_prompt)}",
        f"HARD_SCREEN_PASS_COUNT: {hard_screen_count}/{len(all_stocks)}",
        "IMPORTANT: Use only the live Angel One universe below. Do not invent tickers.",
        "Return a valid JSON object matching the terminal intelligence schema.",
        "",
        "--- LIVE ANGEL ONE UNIVERSE ---",
    ]

    for stock in all_stocks:
        intraday = stock.get("intraday") or {}
        hard_status = "PASS" if intraday.get("passes_hard_filters") else "FAIL"
        reasons = "; ".join(intraday.get("hard_filter_reasons") or []) or "none"
        lines.append(
            f"{stock['ticker']} | {stock['name']} | LTP {stock['ltp']} | delta {stock['delta']} | "
            f"state {stock['state']} | close {stock.get('close')} | volume {stock.get('volume')} | "
            f"ATR% {intraday.get('atr_pct', 0)} | volX {intraday.get('volume_multiplier', 0)} | "
            f"VWAP {intraday.get('vwap', 0)} | EMA9 {intraday.get('ema9', 0)} | ORB {intraday.get('orb_high', 0)} | "
            f"turnoverCr {intraday.get('turnover_cr', 0)} | screen {hard_status} | reasons {reasons}"
        )

    if news_items:
        lines.append("")
        lines.append("--- NEWS FEEDS ---")
        for item in news_items[:10]:
            lines.append(f"{item['source']} | {item['title']} | {item['summary']} | {item['link']}")

    if macro_morning:
        lines.append("")
        lines.append("--- MACRO MORNING ---")
        for row in macro_morning[:10]:
            lines.append(f"{row['label']} | {row['val']} | {row['delta']} | {row['state']}")

    if macro_evening:
        lines.append("")
        lines.append("--- MACRO EVENING ---")
        for row in macro_evening[:10]:
            lines.append(f"{row['label']} | {row['val']} | {row['delta']} | {row['state']}")

    return "\n".join(lines)


def _select_dynamic_top_stocks(
    all_stocks: list[dict[str, Any]],
    pool_name: str,
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    custom_prompt: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    if not all_stocks:
        return [], None, None

    try:
        screened = [row for row in all_stocks if _hard_screen(row)]
        selection_universe = screened if len(screened) >= _TI_TOP_SELECTION_COUNT else all_stocks
        llm_universe = selection_universe[:LLM_UNIVERSE_LIMIT]
        compiled = _compile_selection_stream(
            llm_universe,
            pool_name=pool_name,
            news_items=news_items,
            macro_morning=macro_morning,
            macro_evening=macro_evening,
            hard_screen_count=len(screened),
            custom_prompt=custom_prompt,
        )
        ti = execute_terminal_intelligence_pipeline(compiled)
        ti_payload = ti.model_dump()
        selected_tickers = [row.get("ticker") for row in ti_payload.get("ledger_stocks", []) if row.get("ticker")]
        selected_tickers = selected_tickers[:_TI_TOP_SELECTION_COUNT]
        score_by_ticker = {
            row.get("ticker"): row.get("score")
            for row in ti_payload.get("ledger_stocks", [])
            if row.get("ticker") is not None
        }
        by_ticker = {row["ticker"]: row for row in all_stocks}
        for row in ti_payload.get("ledger_stocks", []):
            ticker = row.get("ticker")
            if not ticker:
                continue
            src = by_ticker.get(ticker)
            if src:
                rv = str(row.get("delta") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("delta"):
                    row["delta"] = src["delta"]
                rv = str(row.get("ltp") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("ltp"):
                    row["ltp"] = src["ltp"]
                rv = str(row.get("name") or "").strip().lower()
                if (not rv or rv in {"n/a", "na", "none", "-"}) and src.get("name"):
                    row["name"] = src["name"]
        selected_rows = []
        for ticker in selected_tickers:
            row = by_ticker.get(ticker)
            if row:
                selected_rows.append({**row, "score": score_by_ticker.get(ticker)})

        if not selected_rows:
            selected_rows = _heuristic_rank(selection_universe)
        else:
            if len(selected_rows) < _TI_TOP_SELECTION_COUNT:
                remaining = [row for row in _heuristic_rank(selection_universe) if row["ticker"] not in {r["ticker"] for r in selected_rows}]
                selected_rows.extend(remaining[: _TI_TOP_SELECTION_COUNT - len(selected_rows)])

        news_summary = (
            ti_payload.get("news_catalysts_card") or ti_payload.get("forensic_screen_card") or ti_payload.get("why_interested")
        )
        return selected_rows[:_TI_TOP_SELECTION_COUNT], ti_payload, news_summary
    except Exception as e:
        # Do not return heuristic data. Return error state so system knows to try on-demand later.
        ti_payload = {
            "llmError": str(e),
            "why_interested": "LLM selection failed.",
            "ledger_stocks": [],
            "news_catalysts_card": None,
            "forensic_screen_card": None,
        }
        return [], ti_payload, None


def _build_macro_strips(macro_raw: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    morning: list[dict[str, str]] = []
    evening: list[dict[str, str]] = []
    seen_labels: set[str] = set()

    for inst in MACRO_INSTRUMENTS:
        quote = macro_raw.get(inst.key)
        if not quote:
            continue
        ltp = float(quote.get("ltp", 0) or 0)
        close = float(quote.get("close", 0) or ltp)
        delta, state = _pct_change(ltp, close if close else None)
        label = inst.label or inst.key
        morning.append({"label": label, "val": f"{ltp:,.2f}", "delta": delta, "state": state})
        evening.append({"label": f"{label} Close", "val": f"{ltp:,.2f}", "delta": delta, "state": state})
        seen_labels.add(label.upper())

    for row in fetch_domestic_index_macro():
        label = str(row["label"])
        if label.upper() in seen_labels:
            continue
        morning.append({k: row[k] for k in ("label", "val", "delta", "state")})
        evening.append({"label": f"{row['label']} Close", "val": row["val"], "delta": row["delta"], "state": row["state"]})
        seen_labels.add(label.upper())

    for row in fetch_domestic_yahoo_macro():
        morning.append({k: row[k] for k in ("label", "val", "delta", "state")})
        evening.append({"label": f"{row['label']} Close", "val": row["val"], "delta": row["delta"], "state": row["state"]})

    # GIFT NIFTY from NSE India API
    gift_nifty = fetch_gift_nifty()
    if gift_nifty and gift_nifty["label"].upper() not in seen_labels:
        morning.append({k: gift_nifty[k] for k in ("label", "val", "delta", "state")})
        evening.append({"label": f"{gift_nifty['label']} Close", "val": gift_nifty["val"], "delta": gift_nifty["delta"], "state": gift_nifty["state"]})
        seen_labels.add(gift_nifty["label"].upper())

    return morning, evening


def _build_terminal_payload(
    all_stocks: list[dict[str, Any]],
    news_items: list[dict[str, str]],
    macro_morning: list[dict[str, str]],
    macro_evening: list[dict[str, str]],
    pool_name: str = NIFTY_100_LABEL,
    custom_prompt: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    return _select_dynamic_top_stocks(
        all_stocks=all_stocks,
        pool_name=pool_name,
        news_items=news_items,
        macro_morning=macro_morning,
        macro_evening=macro_evening,
        custom_prompt=custom_prompt,
    )


def _build_payload_from_live_data(
    client: AngelOneClient,
    pool_name: str | None = None,
    custom_prompt: str | None = None,
    force_llm_refresh: bool = False,
) -> dict[str, Any]:
    llm_config = _llm_config()
    now = _ist_now()
    resolved_pool_name = pool_name or NIFTY_100_LABEL
    stock_universe, active_pool_label = _pool_watchlist(resolved_pool_name)

    stock_quotes_raw = client.fetch_batch_quotes(stock_universe)
    macro_raw = client.fetch_batch_quotes(list(MACRO_INSTRUMENTS))

    all_stocks: list[dict[str, Any]] = []
    stock_quotes: dict[str, dict[str, Any]] = {}
    stock_universe_by_key = {inst.key: inst for inst in stock_universe}
    for inst in stock_universe:
        quote = stock_quotes_raw.get(inst.key)
        if not quote:
            continue
        row = _build_stock_row(inst, quote, active_pool_label)
        all_stocks.append(row)
        stock_quotes[inst.key] = row

    candle_limit = int(os.getenv("INTRADAY_CANDIDATE_LIMIT", "20"))
    candidate_rows = _coarse_pre_rank(all_stocks)[:candle_limit]
    candidate_keys = {row["ticker"] for row in candidate_rows}
    row_by_ticker = {row["ticker"]: row for row in all_stocks}

    for row in all_stocks:
        if row["ticker"] not in candidate_keys:
            row["intraday"] = {
                "atr_pct": 0.0,
                "volume_multiplier": 0.0,
                "today_volume": 0.0,
                "avg_daily_volume_20": 0.0,
                "vwap": 0.0,
                "ema9": 0.0,
                "ema_angle_deg": 0.0,
                "orb_high": 0.0,
                "orb_low": 0.0,
                "orb_velocity_pct": 0.0,
                "wick_noise_ratio": 1.0,
                "turnover_cr": 0.0,
                "price_above_vwap": False,
                "price_above_ema9": False,
                "trigger_point": "VWAP Bounce",
                "passes_hard_filters": False,
                "hard_filter_reasons": ["not in intraday candidate set"],
            }

    all_metrics = _fetch_all_intraday_chunked(client, candidate_rows, stock_universe_by_key, now)
    for ticker, metrics in all_metrics.items():
        original = row_by_ticker.get(ticker)
        if original is not None:
            original["intraday"] = metrics
            stock_quotes[ticker] = original

    macro_morning, macro_evening = _build_macro_strips(macro_raw)
    global_macro = fetch_global_macro()
    news_items = fetch_live_news()

    # AI NEWS ANALYSIS: Call once completely & subsequent from cache unless forced or data missing
    snapshot = _load_last_snapshot()
    existing_ti = snapshot.get("terminalIntelligence") if snapshot else None
    existing_summary = snapshot.get("newsSummary") if snapshot else None
    
    # Logic: If we have valid AI data and aren't forcing a refresh, reuse it to avoid timeouts.
    # If existing data is an error message or missing, we trigger the LLM.
    can_reuse_ai = (
        not force_llm_refresh and 
        existing_ti and 
        not existing_ti.get("llmError") and 
        existing_summary
    )

    if can_reuse_ai:
        top_rows, terminal_intel, news_summary = (snapshot.get("stocks") or [], existing_ti, existing_summary)
    else:
        top_rows, terminal_intel, news_summary = _build_terminal_payload(
            all_stocks=all_stocks,
            news_items=news_items,
            macro_morning=macro_morning,
            macro_evening=macro_evening,
            pool_name=resolved_pool_name,
            custom_prompt=custom_prompt,
        )

    payload = {
        "success": True,
        "source": "angel_one+news+llm_dynamic_top20",
        "rawSources": _news_feed_sources(),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "mockTickers": sorted(MOCK_TICKERS),
        "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
        "activePool": resolved_pool_name,
        "poolDescription": (
            "Nifty 100 Angel One live universe ranked by your filter prompt."
            if resolved_pool_name == NIFTY_100_LABEL
            else f"Dynamic live universe label applied for {resolved_pool_name}."
        ),
        "stocks": top_rows,
        "stockQuotes": stock_quotes,
        "macroDataStrip": {"morning": macro_morning, "evening": macro_evening},
        "globalMacro": global_macro,
        "news": news_items,
        "llmProvider": llm_config[0] if llm_config else None,
        "llmConfigured": llm_config is not None,
        "newsSummary": news_summary,
        "llmError": None,
        "terminalIntelligence": terminal_intel,
        "tickerIntelligenceByTicker": {},
        "isSnapshotFallback": False,
    }

    payload = _hydrate_ticker_intelligence_map(payload)
    _apply_selection_meta(
        payload,
        mode="live",
        reason="Live refresh completed during the scheduled IST window.",
        data_date=now.date().isoformat(),
    )

    return payload


def build_market_payload(
    client: AngelOneClient,
    pool_name: str | None = None,
    force_refresh: bool = False,
    custom_prompt: str | None = None,
    allow_fallback: bool = True, # If live fetch fails, allow falling back to snapshot
    prefer_cache: bool = False, # If true, try cache first, then live if cache is empty/stale
) -> dict[str, Any]:
    snapshot = _load_last_snapshot()

    if prefer_cache and snapshot:
        # If preferring cache and a snapshot exists, return it immediately.
        # The frontend can then decide to trigger an on-demand refresh if data is missing.
        snapshot = dict(snapshot)
        snapshot["isSnapshotFallback"] = True
        snapshot["updatedAt"] = datetime.now(timezone.utc).isoformat()
        if pool_name:
            snapshot["activePool"] = pool_name
        _apply_selection_meta(
            snapshot,
            mode="snapshot",
            reason="Cache preferred. Serving the latest saved snapshot.",
            data_date=_payload_data_date(snapshot),
        )
        return _hydrate_ticker_intelligence_map(snapshot)

    # Attempt live data fetch
    try:
        payload = _build_payload_from_live_data(
            client, 
            pool_name=pool_name, 
            custom_prompt=custom_prompt,
            force_llm_refresh=force_refresh # Only refresh LLM if explicitly forced (on-demand)
        )
        _save_last_snapshot(payload)
        return payload
    except Exception as exc:
        if force_refresh and not allow_fallback:
            raise
        if allow_fallback and snapshot is not None:
            snapshot = dict(snapshot)
            snapshot["isSnapshotFallback"] = True
            snapshot["llmError"] = snapshot.get("llmError")
            snapshot["updatedAt"] = datetime.now(timezone.utc).isoformat()
            if pool_name:
                snapshot["activePool"] = pool_name
            # Refresh RSS news even when outside refresh window
            try: # Still try to fetch fresh news even if falling back to old stock data
                fresh_news = fetch_live_news()
                if fresh_news:
                    snapshot["news"] = fresh_news
            except Exception:
                pass
            _apply_selection_meta(
                snapshot,
                mode="snapshot",
                reason=f"Live refresh failed ({exc}). Serving the latest saved snapshot with fresh news.",
                data_date=_payload_data_date(snapshot),
            )
            return _hydrate_ticker_intelligence_map(snapshot)
        if not allow_fallback:
            return {
                "success": False,
                "error": "Live refresh was requested but the scheduled refresh window is not active and fallback is disabled.",
                "rawSources": _news_feed_sources(),
                "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
                "activePool": pool_name or NIFTY_100_LABEL,
                "poolDescription": "Nifty 100 Angel One live universe ranked by your filter prompt.",
                "stocks": [],
                "stockQuotes": {},
                "macroDataStrip": {"morning": [], "evening": []},
                "globalMacro": {"indices": [], "commodities": []},
                "news": [],
                "newsSummary": None,
                "llmError": None,
                "terminalIntelligence": None,
                "tickerIntelligenceByTicker": {},
                "isSnapshotFallback": False,
                "selectionMeta": {
                    "mode": "live",
                    "reason": f"Live refresh failed ({exc}) and fallback is disabled.",
                    "dataDate": _ist_now().date().isoformat(),
                },
            }
        return {
            "success": False,
            "error": "No cached snapshot available. Live refresh runs only during the morning or evening IST windows.",
            "rawSources": _news_feed_sources(),
            "availablePools": [NIFTY_100_LABEL, "Nifty 500", LIVE_UNIVERSE_LABEL],
            "activePool": pool_name or NIFTY_100_LABEL,
            "poolDescription": "Nifty 100 Angel One live universe ranked by your filter prompt.",
            "stocks": [],
            "stockQuotes": {},
            "macroDataStrip": {"morning": [], "evening": []},
            "globalMacro": {"indices": [], "commodities": []},
            "news": [],
            "newsSummary": None,
            "llmError": None,
            "terminalIntelligence": None,
            "tickerIntelligenceByTicker": {},
            "isSnapshotFallback": True,
            "selectionMeta": {
                "mode": "snapshot",
                    "reason": f"Live refresh failed ({exc}) and no cached snapshot is available.",
                "dataDate": _ist_now().date().isoformat(),
            },
        }


def _compile_market_analysis_stream(payload: dict[str, Any], custom_prompt: str | None = None) -> str:
    lines = [
        f"TOP_N: {_TI_TOP_SELECTION_COUNT}",
        f"FILTER_PROMPT: {_filter_prompt(custom_prompt)}",
        "Use the live Angel One universe and return only valid JSON.",
        "",
        "--- NEWS ---",
    ]

    for item in payload.get("news", [])[:10]:
        lines.append(
            f"Source: {item['source']}\nTitle: {item['title']}\nSummary: {item['summary']}\nLink: {item['link']}\n"
        )

    lines.append("--- TOP STOCKS ---")
    for stock in payload.get("stocks", [])[:_TI_TOP_SELECTION_COUNT]:
        lines.append(
            f"{stock['ticker']} ({stock['name']}): LTP {stock['ltp']}, delta {stock['delta']}, "
            f"state {stock['state']}, close {stock.get('close')}, volume {stock.get('volume')}"
        )

    lines.append("--- MACRO MORNING ---")
    for row in payload.get("macroDataStrip", {}).get("morning", [])[:10]:
        lines.append(f"{row['label']}: {row['val']} {row['delta']} {row['state']}")

    return "\n".join(lines)


def create_app() -> FastAPI:
    app = FastAPI(title="IROS Angel One Market Feed", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/market-data")
    def market_data(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            return build_market_payload(AngelOneClient(), pool_name=pool, custom_prompt=prompt, prefer_cache=True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/news")
    def news_feed() -> dict[str, Any]:
        try:
            return {"success": True, "news": fetch_live_news()}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/market-intelligence")
    def market_intelligence(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=pool, custom_prompt=prompt)
            return {
                "success": True,
                "analysis": payload.get("terminalIntelligence"),
                "tickerIntelligenceByTicker": payload.get("tickerIntelligenceByTicker", {}),
                "newsSummary": payload.get("newsSummary"),
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
                "selectionMeta": payload.get("selectionMeta"),
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/terminal-intelligence")
    def terminal_intelligence(ticker: str | None = None, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=pool, custom_prompt=prompt)
            if ticker:
                report = (payload.get("tickerIntelligenceByTicker") or {}).get(ticker)
                if report:
                    report = dict(report)
                else:
                    report = build_ticker_intelligence_report(payload, ticker)
            else:
                report = dict(payload.get("terminalIntelligence") or {})
            return {
                "success": True,
                "terminalIntelligence": report,
                "focusTicker": ticker,
                "tickerIntelligenceByTicker": payload.get("tickerIntelligenceByTicker", {}),
                "newsSummary": payload.get("newsSummary"),
                "selectionMeta": payload.get("selectionMeta"),
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/orchestrated-refresh")
    async def trigger_orchestrated_refresh(background_tasks: BackgroundTasks, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        task_id = f"orchestrated:{int(time.time())}"
        with _REFRESH_TASK_LOCK:
            _REFRESH_TASKS[task_id] = {"status": "running", "progress": "Initializing sequence...", "created_at": time.time()}
        
        background_tasks.add_task(_run_orchestrated_sequence, task_id, pool, prompt)
        return {"success": True, "taskId": task_id, "message": "Sequential orchestrated refresh started."}

    @app.post("/api/refresh-intelligence")
    def refresh_intelligence(pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        task_id = _refresh_task_key(pool, prompt)
        with _REFRESH_TASK_LOCK:
            task = _REFRESH_TASKS.get(task_id)
            start_new = False
            if task is None:
                start_new = True
            elif time.time() - task.get("created_at", 0) > REFRESH_TASK_TTL_SECONDS:
                start_new = True

            if start_new:
                task_id = _refresh_task_key(pool, prompt)
                _REFRESH_TASKS[task_id] = {
                    "status": "running",
                    "progress": "queued",
                    "error": None,
                    "result": None,
                    "created_at": time.time(),
                    "pool": pool,
                    "prompt": prompt,
                }
                thread = threading.Thread(
                    target=_run_refresh_task,
                    args=(task_id, pool, prompt),
                    daemon=True,
                )
                thread.start()

        return {
            "success": True,
            "accepted": True,
            "taskId": task_id,
            "status": "running",
            "statusUrl": f"/api/refresh-intelligence/status?taskId={task_id}",
            "pool": pool or LIVE_UNIVERSE_LABEL,
        }

    @app.get("/api/refresh-intelligence/status")
    def refresh_intelligence_status(taskId: str) -> dict[str, Any]:
        status = _refresh_task_status(taskId)
        if status is None:
            return {
                "success": False,
                "taskId": taskId,
                "status": "expired",
                "error": "Task not found or expired.",
            }
        response: dict[str, Any] = {
            "success": True,
            "taskId": taskId,
            "status": status["status"],
            "progress": status.get("progress"),
            "error": status.get("error"),
            "created_at": status.get("created_at"),
        }
        if status["status"] == "done" and status.get("result"):
            response["result"] = status["result"]
        return response

    @app.post("/api/refresh-data-on-demand")
    async def refresh_data_on_demand(request: Request, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            body: dict[str, Any] = {}
            try:
                parsed_body = await request.json()
                if isinstance(parsed_body, dict):
                    body = parsed_body
            except Exception:
                body = {}

            resolved_pool = pool or body.get("pool")
            resolved_prompt = prompt or body.get("prompt")
            client = AngelOneClient()
            payload = build_market_payload(
                client,
                pool_name=resolved_pool,
                force_refresh=True,
                prefer_cache=False, # Explicitly do not prefer cache for on-demand refresh
                custom_prompt=resolved_prompt,
                allow_fallback=True,
            )
            if not payload.get("success", False):
                raise RuntimeError(payload.get("error") or "Live refresh produced no payload.")
            payload.setdefault("isSnapshotFallback", False)
            if payload.get("selectionMeta", {}).get("mode") != "live":
                payload["selectionMeta"] = {
                    "mode": "live",
                    "reason": payload.get("selectionMeta", {}).get("reason") or "Live refresh explicitly requested by frontend.",
                    "dataDate": payload.get("selectionMeta", {}).get("dataDate") or _payload_data_date(payload),
                }

            refresh_ticker_news = bool(
                body.get("refreshTickerNews", body.get("refresh_ticker_news", False))
            )

            stocks_to_refresh_news = [s for s in (payload.get("stocks") or []) if isinstance(s, dict) and s.get("ticker")]

            if refresh_ticker_news and stocks_to_refresh_news:
                tickers = [s["ticker"] for s in stocks_to_refresh_news]
                try:
                    async with httpx.AsyncClient() as http_client:
                        response = await http_client.post(
                            f"{AI_NEWS_API_URL}/api/ticker-news/batch-check",
                            json={"tickers": tickers, "max_articles": 20, "include_raw": False},
                            timeout=120,
                        )
                        response.raise_for_status()
                        results = response.json().get("results", [])
                        updated = sum(1 for item in results if isinstance(item, dict) and not item.get("error") and not item.get("cached"))
                        print(f"INFO: Refreshed {updated} ticker news reports out of {len(tickers)} in parallel.")
                except Exception as exc:
                    print(f"WARNING: Batch ticker-news refresh failed: {exc}")
            # --- End new logic ---

            _save_last_snapshot(payload)
            return {
                "success": True,
                "payload": payload,
                "selectionMeta": payload.get("selectionMeta"),
                "isSnapshotFallback": False,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/refresh-ticker-reason")
    async def refresh_ticker_reason(request: Request, ticker: str | None = None, pool: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        try:
            body: dict[str, Any] = {}
            try:
                parsed_body = await request.json()
                if isinstance(parsed_body, dict):
                    body = parsed_body
            except Exception:
                body = {}

            resolved_ticker = str(ticker or body.get("ticker") or "").strip().upper()
            if not resolved_ticker:
                raise HTTPException(status_code=400, detail="Missing required ticker parameter.")

            resolved_pool = pool or body.get("pool")
            resolved_prompt = prompt or body.get("prompt")
            client = AngelOneClient()
            payload = build_market_payload(client, pool_name=resolved_pool, custom_prompt=resolved_prompt)

            stock_row = None
            for stock in payload.get("stocks") or []:
                if str(stock.get("ticker", "")).upper() == resolved_ticker:
                    stock_row = stock
                    break
            if stock_row is None:
                quote = (payload.get("stockQuotes") or {}).get(resolved_ticker)
                if isinstance(quote, dict) and quote:
                    stock_row = quote

            if stock_row is None:
                raise HTTPException(status_code=404, detail=f"Ticker {resolved_ticker} not found in current payload.")

            ledger_score = None
            for row in ((payload.get("terminalIntelligence") or {}).get("ledger_stocks") or []):
                if str(row.get("ticker", "")).upper() == resolved_ticker:
                    ledger_score = row.get("score")
                    break
            try:
                score = float(ledger_score if ledger_score is not None else stock_row.get("score") or 0.0)
            except Exception:
                score = 0.0

            reason = _on_demand_ticker_selection_reason(resolved_ticker, stock_row, score)

            ticker_map = payload.get("tickerIntelligenceByTicker") or {}
            ticker_report = ticker_map.get(resolved_ticker)
            if not ticker_report:
                ticker_report = build_ticker_intelligence_report(payload, resolved_ticker)

            ticker_report = dict(ticker_report)
            factor_hub = dict(ticker_report.get("active_factor_hub") or {})
            factor_hub["selection_reason"] = reason
            ticker_report["active_factor_hub"] = factor_hub
            ticker_report["focusTicker"] = resolved_ticker
            ticker_report["ticker"] = resolved_ticker

            ticker_map[resolved_ticker] = ticker_report
            payload["tickerIntelligenceByTicker"] = ticker_map

            terminal = payload.get("terminalIntelligence") or {}
            ledger = terminal.get("ledger_stocks") or []
            for row in ledger:
                if str(row.get("ticker", "")).upper() == resolved_ticker:
                    row["selection_reason"] = reason
                    break
            terminal["ledger_stocks"] = ledger
            payload["terminalIntelligence"] = terminal

            _save_last_snapshot(payload)

            return {
                "success": True,
                "ticker": resolved_ticker,
                "selectionReason": reason,
                "tickerReport": ticker_report,
                "isSnapshotFallback": payload.get("isSnapshotFallback", False),
                "selectionMeta": payload.get("selectionMeta"),
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


def _run_refresh_task(task_id: str, pool_name: str | None, custom_prompt: str | None) -> None:
    try:
        payload = build_market_payload(
            AngelOneClient(),
            pool_name=pool_name,
            force_refresh=True,
            custom_prompt=custom_prompt,
        )
        if not payload.get("success", False):
            _refresh_task_set_error(task_id, payload.get("error", "Market data unavailable."))
            return
        result = {
            "success": True,
            "poolStocks": len(payload.get("stocks", [])),
            "tiLedgerStocks": len((payload.get("terminalIntelligence") or {}).get("ledger_stocks", [])),
            "tiPopulated": bool(payload.get("terminalIntelligence")),
            "newsSummaryPopulated": bool(payload.get("newsSummary")),
            "selectionMeta": payload.get("selectionMeta"),
        }
        _refresh_task_set_done(task_id, result)
    except Exception as exc:
        _refresh_task_set_error(task_id, str(exc))


def _run_orchestrated_sequence(task_id: str, pool_name: str | None, custom_prompt: str | None) -> None:
    """Orchestrates the sequential dashboard update with 30s delays between sections as specified."""
    try:
        client = AngelOneClient()
        
        def update_progress(msg: str, payload: dict[str, Any]):
            with _REFRESH_TASK_LOCK:
                if task_id in _REFRESH_TASKS:
                    _REFRESH_TASKS[task_id]["progress"] = msg
            # Progressive save so frontend can reflect sections being filled
            _save_last_snapshot(payload)
            print(f"[ORCHESTRATION] {msg}")

        # 1. Immediately delete existing dashboard snapshot to start fresh
        if SNAPSHOT_PATH.exists():
            SNAPSHOT_PATH.unlink()
        
        payload: dict[str, Any] = {
            "success": True,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "stocks": [],
            "stockQuotes": {},
            "macroDataStrip": {"morning": [], "evening": []},
            "globalMacro": {"indices": [], "commodities": []},
            "news": [],
            "terminalIntelligence": None,
            "isSnapshotFallback": False
        }

        # Step 1: Update GLOBAL INDICES section
        update_progress("Updating GLOBAL INDICES section...", payload)
        gm = fetch_global_macro()
        payload["globalMacro"]["indices"] = gm.get("indices", [])
        update_progress("GLOBAL INDICES updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 2: Update COMMODITIES & FX section
        update_progress("Updating COMMODITIES & FX section...", payload)
        payload["globalMacro"]["commodities"] = gm.get("commodities", [])
        payload["macroDataStrip"]["morning"].extend(fetch_domestic_yahoo_macro())
        update_progress("COMMODITIES & FX updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 3: Update NIFTY TOP 5 GAINERS & LOSERS
        update_progress("Updating NIFTY TOP 5 GAINERS & LOSERS...", payload)
        resolved_pool = pool_name or NIFTY_100_LABEL
        stock_universe, pool_label = _pool_watchlist(resolved_pool)
        stock_quotes_raw = client.fetch_batch_quotes(stock_universe)
        
        all_stocks = []
        for inst in stock_universe:
            if q := stock_quotes_raw.get(inst.key):
                all_stocks.append(_build_stock_row(inst, q, pool_label))
        
        # Perform intraday fetch for ranking
        candidate_rows = _coarse_pre_rank(all_stocks)[:30]
        all_metrics = _fetch_all_intraday_chunked(client, candidate_rows, {i.key: i for i in stock_universe}, _ist_now())
        
        for row in all_stocks:
            if m := all_metrics.get(row["ticker"]):
                row["intraday"] = m
        
        payload["stocks"] = _heuristic_rank(all_stocks)
        payload["stockQuotes"] = {s["ticker"]: s for s in all_stocks}
        update_progress("NIFTY TOP 5 MOVERS updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 4: Update NIFTY 100 HEAT MAP (gradient data is now in stockQuotes)
        update_progress("Updating NIFTY 100 HEAT MAP data...", payload)
        update_progress("NIFTY 100 HEAT MAP updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 5: Update LIVE NEWS FEED
        update_progress("Updating LIVE NEWS FEED section...", payload)
        payload["news"] = fetch_live_news()
        update_progress("LIVE NEWS FEED updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 6: Update INDIA MARKETS section (TOP MOVERS, ASSET METRICS)
        update_progress("Updating INDIA MARKETS section...", payload)
        macro_raw = client.fetch_batch_quotes(list(MACRO_INSTRUMENTS))
        m, e = _build_macro_strips(macro_raw)
        payload["macroDataStrip"]["morning"].extend(m)
        payload["macroDataStrip"]["evening"].extend(e)
        payload["macroDataStrip"]["morning"].extend(fetch_domestic_index_macro())
        update_progress("INDIA MARKETS section updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 7: Update AI NEWS TERMINAL & SUMMARY
        # Check if we already have this in a valid state from a previous snapshot
        snapshot = _load_last_snapshot()
        if snapshot and snapshot.get("terminalIntelligence") and not snapshot.get("terminalIntelligence", {}).get("llmError"):
            update_progress("AI NEWS TERMINAL & SUMMARY found in cache. Reusing...", payload)
            top_rows = snapshot.get("stocks", [])
            ti_intel = snapshot.get("terminalIntelligence")
            news_summary = snapshot.get("newsSummary")
        else:
            update_progress("AI NEWS TERMINAL & SUMMARY missing or invalid. Calling LLM...", payload)
            top_rows, ti_intel, news_summary = _build_terminal_payload(
                all_stocks=all_stocks,
                news_items=payload["news"],
                macro_morning=payload["macroDataStrip"]["morning"],
                macro_evening=payload["macroDataStrip"]["evening"],
                pool_name=resolved_pool,
                custom_prompt=custom_prompt
            )
            
            if not ti_intel or ti_intel.get("llmError"):
                 update_progress("AI ANALYSIS failed. Panel will remain empty for on-demand retry.", payload)
            else:
                 update_progress("AI ANALYSIS completed successfully.", payload)

        payload["terminalIntelligence"] = ti_intel
        payload["newsSummary"] = news_summary
        update_progress("AI SUMMARY updated. Waiting 30 seconds...", payload)
        time.sleep(ORCHESTRATION_DELAY)

        # Step 8: Update TERMINAL ANALYSIS section
        update_progress("Updating final TERMINAL ANALYSIS section...", payload)
        payload = _hydrate_ticker_intelligence_map(payload)
        _apply_selection_meta(
            payload, 
            mode="live", 
            reason="Sequential orchestrated refresh complete. Rendering final dashboard."
        )
        
        update_progress("Orchestrated refresh sequence complete. Dashboard fully generated.", payload)
        _refresh_task_set_done(task_id, {"success": True, "message": "Sequence finished successfully."})

        # NOTE: At this point, the backend has generated the complete dataset.
        # The 'light-themed image' rendering is handled by the frontend dashboard component
        # when it detects the 'Sequential orchestrated refresh complete' meta state.

    except Exception as exc:
        print(f"[ORCHESTRATION ERROR] {exc}")
        _refresh_task_set_error(task_id, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(description="Angel One market feed for IROS")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--once", action="store_true", help="Fetch once and print/save JSON")
    parser.add_argument("--output", help="Write JSON snapshot to this file")
    parser.add_argument("--pool", default=None, help="Pool label. Defaults to Nifty 100; Live Universe is also supported.")
    parser.add_argument("--prompt", default=None, help="Custom filter prompt override")
    parser.add_argument("--refresh-on-demand", action="store_true", help="Force a non-fallback live refresh and write snapshot")
    parser.add_argument("--orchestrate", action="store_true", help="Run the sequential orchestrated refresh sequence")
    args = parser.parse_args()

    try:
        resolved = _llm_config()
        print(
            f"[LLM-DEBUG] env_path={BASE_DIR / '.env'} "
            f"LLM_PROVIDER={os.getenv('LLM_PROVIDER','')} "
            f"LLM_MODEL={os.getenv('LLM_MODEL','')} "
            f"REDACTED={'set' if os.getenv('REDACTED','').strip() else 'missing'} "
            f"resolved={resolved}"
        )
    except Exception as exc:
        print(f"[LLM-DEBUG] config inspect failed: {exc}")

    if args.serve:
        import uvicorn

        host = os.getenv("MARKET_API_HOST", "0.0.0.0")
        port = int(os.getenv("MARKET_API_PORT", "8000"))
        uvicorn.run(create_app(), host=host, port=port)
        return 0

    if args.orchestrate:
        print("[INFO] Starting orchestrated sequential refresh...")
        _run_orchestrated_sequence("cli_task", args.pool, args.prompt)
        return 0

    if args.refresh_on_demand:
        client = AngelOneClient()
        payload = build_market_payload(
            client,
            pool_name=args.pool,
            force_refresh=True,
            prefer_cache=False, # Explicitly do not prefer cache for on-demand refresh
            custom_prompt=args.prompt,
            allow_fallback=False,
        )
        if not payload.get("success", False):
            raise RuntimeError(payload.get("error") or "Live refresh produced no payload.")
        payload.setdefault("isSnapshotFallback", False)
        if payload.get("selectionMeta", {}).get("mode") != "live":
            payload["selectionMeta"] = {
                "mode": "live",
                "reason": payload.get("selectionMeta", {}).get("reason") or "Live refresh explicitly requested by CLI.",
                "dataDate": payload.get("selectionMeta", {}).get("dataDate") or _payload_data_date(payload),
            }
        _save_last_snapshot(payload)
        text = json.dumps(payload, indent=2)
        print(text)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        return 0

    client = AngelOneClient()
    payload = build_market_payload(client, pool_name=args.pool, custom_prompt=args.prompt)
    text = json.dumps(payload, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
