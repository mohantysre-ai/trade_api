#!/usr/bin/env python3
"""Staged read-only production load test for SIGQ/IROS.

Targets only GET endpoints. Designed to answer: can the public app survive
1,000 concurrent clients without unacceptable latency/error rate?
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import random
import statistics
import time
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Any

import aiohttp

BASE_URL = os.getenv("LOAD_BASE_URL", "https://sigq.in").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("LOAD_REQUEST_TIMEOUT", "20"))
CONNECT_TIMEOUT = float(os.getenv("LOAD_CONNECT_TIMEOUT", "8"))

# Progressive capacity test. Final stage holds 1,000 concurrent users for 60s.
STAGES = [
    (50, 20),
    (200, 25),
    (500, 30),
    (1000, 60),
]

# Read-only mix approximating dashboard clients without intentionally triggering
# refresh/trading side effects.
ENDPOINTS = [
    ("/", 0.70),
    ("/api/market-data.csv", 0.30),
]

# Production survival thresholds.
MAX_ERROR_RATE = float(os.getenv("LOAD_MAX_ERROR_RATE", "0.02"))       # 2%
MAX_P95_MS = float(os.getenv("LOAD_MAX_P95_MS", "2500"))              # 2.5s
MAX_P99_MS = float(os.getenv("LOAD_MAX_P99_MS", "6000"))              # 6s
MIN_SUCCESS_RPS_AT_1000 = float(os.getenv("LOAD_MIN_RPS_1000", "75")) # conservative


@dataclass
class Result:
    stage_users: int
    endpoint: str
    status: int
    elapsed_ms: float
    ok: bool
    error: str | None = None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    data = sorted(values)
    k = (len(data) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return data[lo]
    return data[lo] * (hi - k) + data[hi] * (k - lo)


def choose_endpoint() -> str:
    r = random.random()
    acc = 0.0
    for path, weight in ENDPOINTS:
        acc += weight
        if r <= acc:
            return path
    return ENDPOINTS[-1][0]


async def one_request(session: aiohttp.ClientSession, stage_users: int) -> Result:
    path = choose_endpoint()
    start = time.perf_counter()
    try:
        async with session.get(
            f"{BASE_URL}{path}",
            headers={
                "accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "user-agent": "sigq-authorized-load-test/1.0",
            },
            allow_redirects=True,
        ) as resp:
            # Drain the response so connection reuse reflects real client behavior.
            await resp.read()
            elapsed = (time.perf_counter() - start) * 1000.0
            ok = 200 <= resp.status < 400
            return Result(stage_users, path, resp.status, elapsed, ok, None if ok else f"HTTP {resp.status}")
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000.0
        return Result(stage_users, path, 0, elapsed, False, type(exc).__name__)


async def virtual_user(
    user_id: int,
    stage_users: int,
    deadline: float,
    session: aiohttp.ClientSession,
    sink: list[Result],
) -> None:
    # Small jitter avoids an artificial single-millisecond thundering herd while
    # still reaching the requested concurrency rapidly.
    await asyncio.sleep(random.random() * 0.4)
    while time.monotonic() < deadline:
        sink.append(await one_request(session, stage_users))
        # Browser/dashboard think time. Keeps concurrency high without becoming a
        # raw packet flood detached from application behavior.
        await asyncio.sleep(random.uniform(0.15, 0.65))


async def run_stage(users: int, duration_s: int, session: aiohttp.ClientSession) -> dict[str, Any]:
    results: list[Result] = []
    started = time.monotonic()
    deadline = started + duration_s
    tasks = [
        asyncio.create_task(virtual_user(i, users, deadline, session, results))
        for i in range(users)
    ]
    await asyncio.gather(*tasks)
    actual = max(time.monotonic() - started, 0.001)

    good = [r for r in results if r.ok]
    latencies = [r.elapsed_ms for r in good]
    statuses = Counter(str(r.status) for r in results)
    errors = Counter(r.error or "" for r in results if not r.ok)
    per_endpoint: dict[str, Any] = {}
    for path, _ in ENDPOINTS:
        rows = [r for r in results if r.endpoint == path]
        oks = [r for r in rows if r.ok]
        vals = [r.elapsed_ms for r in oks]
        per_endpoint[path] = {
            "requests": len(rows),
            "success": len(oks),
            "errorRatePct": round(((len(rows) - len(oks)) / len(rows) * 100.0) if rows else 0.0, 3),
            "p50Ms": round(percentile(vals, 0.50), 1),
            "p95Ms": round(percentile(vals, 0.95), 1),
            "p99Ms": round(percentile(vals, 0.99), 1),
        }

    total = len(results)
    summary = {
        "users": users,
        "durationSec": round(actual, 2),
        "requests": total,
        "success": len(good),
        "failed": total - len(good),
        "errorRatePct": round(((total - len(good)) / total * 100.0) if total else 100.0, 3),
        "requestsPerSec": round(total / actual, 2),
        "successRps": round(len(good) / actual, 2),
        "latency": {
            "meanMs": round(statistics.mean(latencies), 1) if latencies else 0.0,
            "p50Ms": round(percentile(latencies, 0.50), 1),
            "p95Ms": round(percentile(latencies, 0.95), 1),
            "p99Ms": round(percentile(latencies, 0.99), 1),
            "maxMs": round(max(latencies), 1) if latencies else 0.0,
        },
        "statuses": dict(statuses),
        "errors": dict(errors),
        "endpoints": per_endpoint,
    }
    print("STAGE_RESULT=" + json.dumps(summary, separators=(",", ":")), flush=True)
    return summary


async def main() -> int:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
    connector = aiohttp.TCPConnector(
        limit=1300,
        limit_per_host=1300,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )

    report: dict[str, Any] = {
        "target": BASE_URL,
        "startedAtEpoch": int(time.time()),
        "stages": [],
        "thresholds": {
            "maxErrorRatePct": MAX_ERROR_RATE * 100.0,
            "maxP95Ms": MAX_P95_MS,
            "maxP99Ms": MAX_P99_MS,
            "minSuccessRpsAt1000": MIN_SUCCESS_RPS_AT_1000,
        },
    }

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        # Preflight: refuse to launch 1,000 concurrency if the target is not healthy.
        preflight = await one_request(session, 1)
        if not preflight.ok:
            report["survived"] = False
            report["failureReason"] = f"preflight failed: {preflight.error}"
            with open("load-test-report.json", "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
            print(json.dumps(report, indent=2))
            return 2

        for users, duration in STAGES:
            stage = await run_stage(users, duration, session)
            report["stages"].append(stage)
            # Abort escalation if a lower stage is already catastrophically failing.
            if stage["errorRatePct"] >= 20.0:
                report["abortedAfterUsers"] = users
                break
            await asyncio.sleep(3)

    final = report["stages"][-1] if report["stages"] else {}
    reached_1000 = final.get("users") == 1000
    error_rate = float(final.get("errorRatePct", 100.0)) / 100.0
    p95 = float((final.get("latency") or {}).get("p95Ms", 0.0))
    p99 = float((final.get("latency") or {}).get("p99Ms", 0.0))
    success_rps = float(final.get("successRps", 0.0))

    survived = bool(
        reached_1000
        and error_rate <= MAX_ERROR_RATE
        and p95 <= MAX_P95_MS
        and p99 <= MAX_P99_MS
        and success_rps >= MIN_SUCCESS_RPS_AT_1000
    )
    report["survived"] = survived
    report["finalAssessment"] = {
        "reached1000": reached_1000,
        "errorRatePass": error_rate <= MAX_ERROR_RATE,
        "p95Pass": p95 <= MAX_P95_MS,
        "p99Pass": p99 <= MAX_P99_MS,
        "throughputPass": success_rps >= MIN_SUCCESS_RPS_AT_1000,
    }

    with open("load-test-report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print("FINAL_REPORT=" + json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if survived else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
