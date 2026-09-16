from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import socket
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp


@dataclass(frozen=True)
class Endpoint:
    name: str
    method: str
    path: str
    weight: int
    body: dict[str, Any] | None = None


@dataclass
class Result:
    endpoint: str
    method: str
    status: int
    elapsed_ms: float
    ok: bool
    error: str | None


READ_ENDPOINTS = (
    Endpoint("health", "GET", "/health", 2),
    Endpoint("market-data", "GET", "/api/market-data?pool=Nifty%20500", 14),
    Endpoint("market-coverage", "GET", "/api/market-data/coverage", 3),
    Endpoint("nse-symbols", "GET", "/api/nse-symbols?universe=nifty500", 3),
    Endpoint("audit-verdicts", "GET", "/api/audit-verdicts", 3),
    Endpoint("intraday-session", "GET", "/api/intraday-session?live=false", 14),
    Endpoint("intraday-candidates", "GET", "/api/intraday-session/candidates", 5),
    Endpoint("intraday-replacements", "GET", "/api/intraday-session/replacements", 5),
    Endpoint("intraday-state", "GET", "/api/intraday/market-state", 5),
    Endpoint("swing-session", "GET", "/api/swing-session?live=false", 14),
    Endpoint("swing-screener", "GET", "/api/swing-screener", 4),
    Endpoint("index-options", "GET", "/api/index-options?live=false", 8),
    Endpoint("fixed-plan", "GET", "/api/fixed-trade-plan", 4),
    Endpoint("trade-outcomes", "GET", "/api/trade-outcomes", 4),
    Endpoint("eod-intraday", "GET", "/api/reports/eod-intraday?date=2026-09-11", 4),
    Endpoint("eod-swing", "GET", "/api/reports/eod-swing?date=2026-09-11", 4),
    Endpoint("eod-options", "GET", "/api/reports/eod-index-options?date=2026-09-11", 4),
)

WRITE_ENDPOINTS = (
    Endpoint("intraday-commit", "POST", "/api/intraday-session/commit?force=false", 5),
    Endpoint("swing-lock", "POST", "/api/swing-session/lock?force=false", 5),
    Endpoint(
        "fixed-plan-write",
        "POST",
        "/api/fixed-trade-plan",
        2,
        {"sessionDate": "2026-09-11", "long": [], "short": [], "qaLoadTest": True},
    ),
)

PROFILES = {
    "smoke": [(10, 10)],
    "load": [(50, 15), (200, 20), (500, 30), (1000, 60)],
    "stress": [(1000, 45), (1500, 45), (2000, 45), (3000, 45)],
}


def percentile(values: list[float], point: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * point
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def is_loopback(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return socket.gethostbyname(host).startswith("127.")
    except OSError:
        return False


def validate_write_safety(base_url: str, allow_writes: bool) -> None:
    if not allow_writes:
        return
    if not is_loopback(base_url):
        raise SystemExit("Write load is restricted to loopback targets")
    if os.getenv("QA_ISOLATED_STATE", "").lower() != "true":
        raise SystemExit("Set QA_ISOLATED_STATE=true after redirecting all mutable state files")
    if os.getenv("QA_CONFIRM_WRITE_LOAD") != "I_UNDERSTAND_THIS_MUTATES_TEST_STATE":
        raise SystemExit("Set QA_CONFIRM_WRITE_LOAD=I_UNDERSTAND_THIS_MUTATES_TEST_STATE")


def choose_endpoint(write_ratio: float, allow_writes: bool) -> Endpoint:
    use_write = allow_writes and random.random() < write_ratio
    pool = WRITE_ENDPOINTS if use_write else READ_ENDPOINTS
    return random.choices(pool, weights=[item.weight for item in pool], k=1)[0]


async def request_once(session: aiohttp.ClientSession, base_url: str, endpoint: Endpoint) -> Result:
    started = time.perf_counter()
    try:
        async with session.request(endpoint.method, base_url + endpoint.path, json=endpoint.body) as response:
            await response.read()
            elapsed = (time.perf_counter() - started) * 1000
            ok = 200 <= response.status < 400
            return Result(endpoint.name, endpoint.method, response.status, elapsed, ok, None if ok else f"HTTP_{response.status}")
    except Exception as exc:
        return Result(endpoint.name, endpoint.method, 0, (time.perf_counter() - started) * 1000, False, type(exc).__name__)


async def virtual_user(
    session: aiohttp.ClientSession,
    base_url: str,
    deadline: float,
    start_gate: asyncio.Event,
    sink: list[Result],
    write_ratio: float,
    allow_writes: bool,
) -> None:
    await start_gate.wait()
    while time.monotonic() < deadline:
        sink.append(await request_once(session, base_url, choose_endpoint(write_ratio, allow_writes)))
        await asyncio.sleep(random.uniform(0.05, 0.25))


def summarize(results: list[Result], users: int, elapsed: float, thresholds: dict[str, float]) -> dict[str, Any]:
    successful = [item for item in results if item.ok]
    latencies = [item.elapsed_ms for item in successful]
    grouped: dict[str, list[Result]] = defaultdict(list)
    for item in results:
        grouped[f"{item.method} {item.endpoint}"].append(item)
    endpoints = {}
    for name, rows in sorted(grouped.items()):
        good = [row.elapsed_ms for row in rows if row.ok]
        endpoints[name] = {
            "requests": len(rows),
            "success": len(good),
            "errorRatePct": round((len(rows) - len(good)) * 100 / len(rows), 3),
            "p50Ms": round(percentile(good, 0.50), 1),
            "p95Ms": round(percentile(good, 0.95), 1),
            "p99Ms": round(percentile(good, 0.99), 1),
        }
    total = len(results)
    error_rate = (total - len(successful)) * 100 / max(1, total)
    p95 = percentile(latencies, 0.95)
    p99 = percentile(latencies, 0.99)
    success_rps = len(successful) / max(0.001, elapsed)
    checks = {
        "errorRate": error_rate <= thresholds["maxErrorRatePct"],
        "p95": p95 <= thresholds["maxP95Ms"],
        "p99": p99 <= thresholds["maxP99Ms"],
        "throughput": success_rps >= thresholds["minSuccessRps"],
    }
    return {
        "users": users,
        "durationSec": round(elapsed, 2),
        "requests": total,
        "success": len(successful),
        "failed": total - len(successful),
        "errorRatePct": round(error_rate, 3),
        "successRps": round(success_rps, 2),
        "latency": {
            "meanMs": round(statistics.mean(latencies), 1) if latencies else 0.0,
            "p50Ms": round(percentile(latencies, 0.50), 1),
            "p95Ms": round(p95, 1),
            "p99Ms": round(p99, 1),
            "maxMs": round(max(latencies), 1) if latencies else 0.0,
        },
        "statuses": dict(Counter(str(item.status) for item in results)),
        "errors": dict(Counter(item.error for item in results if item.error)),
        "checks": checks,
        "passed": all(checks.values()),
        "endpoints": endpoints,
    }


async def openapi_inventory(session: aiohttp.ClientSession, base_url: str) -> dict[str, Any]:
    try:
        async with session.get(base_url + "/openapi.json") as response:
            payload = await response.json()
        operations = sorted(f"{method.upper()} {path}" for path, methods in payload.get("paths", {}).items() for method in methods if method.lower() in {"get", "post", "put", "patch", "delete"})
    except Exception as exc:
        return {"error": type(exc).__name__, "registered": [], "covered": [], "uncovered": []}
    configured = {(item.method, item.path.split("?")[0]) for item in (*READ_ENDPOINTS, *WRITE_ENDPOINTS)}
    covered = [operation for operation in operations if tuple(operation.split(" ", 1)) in configured]
    return {"registeredCount": len(operations), "coveredCount": len(covered), "registered": operations, "covered": covered, "uncovered": [item for item in operations if item not in covered]}


async def run(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    validate_write_safety(base_url, args.allow_writes)
    stages = PROFILES[args.profile] if args.users is None else [(args.users, args.duration)]
    thresholds = {
        "maxErrorRatePct": args.max_error_rate,
        "maxP95Ms": args.max_p95,
        "maxP99Ms": args.max_p99,
        "minSuccessRps": args.min_rps,
    }
    timeout = aiohttp.ClientTimeout(total=args.request_timeout, connect=args.connect_timeout)
    connector = aiohttp.TCPConnector(limit=max(100, max(users for users, _ in stages) + 100), limit_per_host=max(100, max(users for users, _ in stages) + 100), ttl_dns_cache=300)
    report: dict[str, Any] = {"baseUrl": base_url, "profile": args.profile, "allowWrites": args.allow_writes, "thresholds": thresholds, "stages": []}
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers={"user-agent": "alphix-friday-market-qa/1.0"}) as session:
        preflight = await request_once(session, base_url, READ_ENDPOINTS[0])
        if not preflight.ok:
            report.update({"passed": False, "failureReason": asdict(preflight)})
        else:
            report["openapi"] = await openapi_inventory(session, base_url)
            for users, duration in stages:
                sink: list[Result] = []
                gate = asyncio.Event()
                started = time.monotonic()
                deadline = started + duration
                tasks = [asyncio.create_task(virtual_user(session, base_url, deadline, gate, sink, args.write_ratio, args.allow_writes)) for _ in range(users)]
                gate.set()
                await asyncio.gather(*tasks)
                stage = summarize(sink, users, time.monotonic() - started, thresholds)
                report["stages"].append(stage)
                print("STAGE_RESULT=" + json.dumps(stage, separators=(",", ":")), flush=True)
                if args.profile == "stress" and (stage["errorRatePct"] >= 20 or stage["latency"]["p99Ms"] >= args.request_timeout * 1000):
                    report["breakingPoint"] = users
                    break
                await asyncio.sleep(2)
            report["passed"] = bool(report["stages"] and report["stages"][-1]["passed"])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("FINAL_REPORT=" + json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if report.get("passed") else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--base-url", default=os.getenv("LOAD_BASE_URL", "http://127.0.0.1:8014"))
    value.add_argument("--profile", choices=PROFILES, default=os.getenv("LOAD_PROFILE", "load"))
    value.add_argument("--users", type=int)
    value.add_argument("--duration", type=int, default=int(os.getenv("LOAD_DURATION_SECONDS", "60")))
    value.add_argument("--write-ratio", type=float, default=float(os.getenv("LOAD_WRITE_RATIO", "0.10")))
    value.add_argument("--allow-writes", action="store_true", default=os.getenv("LOAD_ALLOW_WRITES", "false").lower() == "true")
    value.add_argument("--request-timeout", type=float, default=float(os.getenv("LOAD_REQUEST_TIMEOUT_SECONDS", "30")))
    value.add_argument("--connect-timeout", type=float, default=float(os.getenv("LOAD_CONNECT_TIMEOUT_SECONDS", "10")))
    value.add_argument("--max-error-rate", type=float, default=float(os.getenv("LOAD_MAX_ERROR_RATE_PCT", "2")))
    value.add_argument("--max-p95", type=float, default=float(os.getenv("LOAD_MAX_P95_MS", "2500")))
    value.add_argument("--max-p99", type=float, default=float(os.getenv("LOAD_MAX_P99_MS", "6000")))
    value.add_argument("--min-rps", type=float, default=float(os.getenv("LOAD_MIN_SUCCESS_RPS", "75")))
    value.add_argument("--output", default="performance/reports/load-report.json")
    return value


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parser().parse_args())))
