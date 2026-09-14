from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def run(requests: int) -> dict:
    from app.services.shared_state import get_view_store
    import app.services.angel_one_feed as feed
    import app.services.index_options.radar_builder as radar
    import app.services.index_options.runtime as runtime

    get_view_store().set("index_options", {
        "success": True,
        "selected": [],
        "sellerCandidates": [],
        "sessionStatus": "OPEN",
        "huntActive": True,
        "limits": {"huntMode": "CONTINUOUS_MARKET_SESSION"},
    })
    counters = {"brokerCalls": 0, "strategyEvaluations": 0, "dbWrites": 0}
    original_client = feed.AngelOneClient
    original_build = radar.build_index_options_radar_v2
    original_cycle = runtime.process_strategy_cycle

    def broker(*args, **kwargs):
        counters["brokerCalls"] += 1
        return original_client(*args, **kwargs)

    def build(*args, **kwargs):
        counters["strategyEvaluations"] += 1
        return original_build(*args, **kwargs)

    def cycle(*args, **kwargs):
        counters["dbWrites"] += 1
        return original_cycle(*args, **kwargs)

    feed.AngelOneClient = broker
    radar.build_index_options_radar_v2 = build
    runtime.process_strategy_cycle = cycle
    app = feed.create_app()
    transport = httpx.ASGITransport(app=app)
    latencies = []
    statuses = []

    async def request(client):
        started = time.perf_counter()
        response = await client.get("/api/index-options")
        latencies.append((time.perf_counter() - started) * 1000)
        statuses.append(response.status_code)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30) as client:
            await asyncio.gather(*(request(client) for _ in range(requests)))
    finally:
        feed.AngelOneClient = original_client
        radar.build_index_options_radar_v2 = original_build
        runtime.process_strategy_cycle = original_cycle

    ordered = sorted(latencies)
    percentile = lambda fraction: ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]
    successful = sum(status == 200 for status in statuses)
    return {
        "requests": requests,
        "successful": successful,
        "failed": requests - successful,
        "p50Ms": round(statistics.median(ordered), 3),
        "p95Ms": round(percentile(0.95), 3),
        "p99Ms": round(percentile(0.99), 3),
        **counters,
        "passed": successful == requests and not any(counters.values()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=1000)
    args = parser.parse_args()
    result = asyncio.run(run(args.requests))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
