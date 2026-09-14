from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp


ENDPOINTS = {
    "equities": "/api/market-data?pool=Nifty%20500",
    "indices-options": "/api/index-options?live=false",
    "intraday": "/api/intraday-session?live=false",
    "swing": "/api/swing-session?live=false",
    "eod-intraday": "/api/reports/eod-intraday?date={date}",
    "eod-swing": "/api/reports/eod-swing?date={date}",
    "eod-options": "/api/reports/eod-index-options?date={date}",
}


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def timestamps(payload: Any) -> list[datetime]:
    found: list[datetime] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in {"updatedat", "timestamp", "asof", "generatedat", "snapshotupdatedat", "lastticktime"}:
                parsed = parse_timestamp(value)
                if parsed:
                    found.append(parsed)
            found.extend(timestamps(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(timestamps(value))
    return found


def rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = []
    for key in ("long", "short", "positions", "picks", "trades"):
        if isinstance(payload.get(key), list):
            values.extend(item for item in payload[key] if isinstance(item, dict))
    return values


def pnl_errors(payload: dict[str, Any], endpoint: str) -> list[str]:
    errors = []
    items = rows(payload)
    for item in items:
        realized = item.get("realizedPnl")
        unrealized = item.get("unrealizedPnl")
        total = item.get("totalPnl") if item.get("totalPnl") is not None else item.get("pnl")
        if total is not None and realized is not None and unrealized is not None and abs(float(total) - float(realized) - float(unrealized)) > 0.02:
            errors.append(f"{endpoint}:{item.get('symbol') or item.get('ticker')}:totalPnl mismatch")
    portfolio = payload.get("portfolio")
    if isinstance(portfolio, dict) and portfolio.get("totalPnl") is not None and items:
        computed = sum(float(item.get("totalPnl") or item.get("pnl") or 0) for item in items)
        if abs(float(portfolio["totalPnl"]) - computed) > 0.02:
            errors.append(f"{endpoint}:portfolio totalPnl mismatch")
    return errors


async def fetch(session: aiohttp.ClientSession, base_url: str, name: str, path: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with session.get(base_url + path) as response:
            payload = await response.json(content_type=None)
        return {"name": name, "status": response.status, "latencyMs": (time.perf_counter() - started) * 1000, "payload": payload, "error": None}
    except Exception as exc:
        return {"name": name, "status": 0, "latencyMs": (time.perf_counter() - started) * 1000, "payload": {}, "error": type(exc).__name__}


async def run(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    endpoint_paths = {name: path.format(date=args.date) for name, path in ENDPOINTS.items()}
    report: dict[str, Any] = {"baseUrl": base_url, "date": args.date, "samples": [], "violations": []}
    previous_session_dates: dict[str, Any] = {}
    deadline = time.monotonic() + args.duration
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while time.monotonic() < deadline:
            cycle = await asyncio.gather(*(fetch(session, base_url, name, path) for name, path in endpoint_paths.items()))
            now = datetime.now(timezone.utc)
            sample = {"at": now.isoformat(), "endpoints": {}}
            for result in cycle:
                name = result["name"]
                payload = result["payload"] if isinstance(result["payload"], dict) else {}
                stamps = timestamps(payload)
                ages = [(now - stamp).total_seconds() for stamp in stamps if stamp <= now]
                newest_age = min(ages) if ages else None
                item = {"status": result["status"], "latencyMs": round(result["latencyMs"], 2), "newestDataAgeSec": round(newest_age, 2) if newest_age is not None else None, "error": result["error"]}
                sample["endpoints"][name] = item
                if result["status"] != 200:
                    report["violations"].append(f"{name}:HTTP {result['status']} or {result['error']}")
                if result["latencyMs"] > args.max_response_ms:
                    report["violations"].append(f"{name}:response {result['latencyMs']:.1f}ms")
                if name in {"equities", "indices-options", "intraday", "swing"} and newest_age is not None and newest_age > args.max_data_age:
                    report["violations"].append(f"{name}:data age {newest_age:.1f}s")
                report["violations"].extend(pnl_errors(payload, name))
                session_date = payload.get("sessionDate")
                if name in previous_session_dates and session_date != previous_session_dates[name]:
                    report["violations"].append(f"{name}:sessionDate changed during rapid switching")
                previous_session_dates[name] = session_date
            report["samples"].append(sample)
            await asyncio.sleep(args.interval)
    unique = sorted(set(report["violations"]))
    report["violations"] = unique
    report["passed"] = not unique
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "samples": len(report["samples"]), "violations": unique}, indent=2))
    return 0 if report["passed"] else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--base-url", default=os.getenv("LOAD_BASE_URL", "http://127.0.0.1:8014"))
    value.add_argument("--date", default=os.getenv("QA_EOD_DATE", "2026-09-11"))
    value.add_argument("--duration", type=int, default=int(os.getenv("MARKET_VALIDATION_DURATION_SECONDS", "60")))
    value.add_argument("--interval", type=float, default=float(os.getenv("MARKET_POLL_INTERVAL_SECONDS", "1")))
    value.add_argument("--max-response-ms", type=float, default=float(os.getenv("MARKET_MAX_RESPONSE_MS", "1000")))
    value.add_argument("--max-data-age", type=float, default=float(os.getenv("MARKET_MAX_DATA_AGE_SECONDS", "2")))
    value.add_argument("--timeout", type=float, default=15)
    value.add_argument("--output", default="performance/reports/realtime-report.json")
    return value


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parser().parse_args())))
