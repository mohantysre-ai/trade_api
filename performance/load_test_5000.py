#!/usr/bin/env python3
from __future__ import annotations

import asyncio, json, math, os, random, statistics, time
from collections import Counter
from dataclasses import dataclass
from typing import Any
import aiohttp

BASE_URL = os.getenv("LOAD_BASE_URL", "https://sigq.in").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("LOAD_REQUEST_TIMEOUT", "20"))
CONNECT_TIMEOUT = float(os.getenv("LOAD_CONNECT_TIMEOUT", "8"))
STAGES = [(1000, 20), (2000, 25), (3500, 30), (5000, 40)]
ENDPOINTS = [("/", 0.70), ("/api/market-data.csv", 0.30)]
MAX_ERROR_RATE = float(os.getenv("LOAD_MAX_ERROR_RATE", "0.02"))
MAX_P95_MS = float(os.getenv("LOAD_MAX_P95_MS", "2500"))
MAX_P99_MS = float(os.getenv("LOAD_MAX_P99_MS", "6000"))
MIN_SUCCESS_RPS_AT_5000 = float(os.getenv("LOAD_MIN_RPS_5000", "300"))
ABORT_ERROR_RATE_PCT = float(os.getenv("LOAD_ABORT_ERROR_RATE_PCT", "5"))

@dataclass
class Result:
    endpoint: str
    status: int
    elapsed_ms: float
    ok: bool
    error: str | None = None

def percentile(values: list[float], p: float) -> float:
    if not values: return 0.0
    data = sorted(values)
    k = (len(data)-1)*p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi: return data[lo]
    return data[lo]*(hi-k)+data[hi]*(k-lo)

def choose_endpoint() -> str:
    r=random.random(); acc=0.0
    for path,weight in ENDPOINTS:
        acc += weight
        if r <= acc: return path
    return ENDPOINTS[-1][0]

async def one_request(session: aiohttp.ClientSession) -> Result:
    path=choose_endpoint(); start=time.perf_counter()
    try:
        async with session.get(f"{BASE_URL}{path}", headers={"accept":"text/html,application/json;q=0.9,*/*;q=0.8","user-agent":"sigq-authorized-load-test/2.0"}, allow_redirects=True) as resp:
            await resp.read(); elapsed=(time.perf_counter()-start)*1000
            ok=200 <= resp.status < 400
            return Result(path,resp.status,elapsed,ok,None if ok else f"HTTP {resp.status}")
    except Exception as exc:
        return Result(path,0,(time.perf_counter()-start)*1000,False,type(exc).__name__)

async def virtual_user(deadline: float, session: aiohttp.ClientSession, sink: list[Result]) -> None:
    await asyncio.sleep(random.random()*0.8)
    while time.monotonic() < deadline:
        sink.append(await one_request(session))
        await asyncio.sleep(random.uniform(0.25,0.9))

async def run_stage(users:int,duration:int,session:aiohttp.ClientSession)->dict[str,Any]:
    results:list[Result]=[]; started=time.monotonic(); deadline=started+duration
    tasks=[asyncio.create_task(virtual_user(deadline,session,results)) for _ in range(users)]
    await asyncio.gather(*tasks)
    actual=max(time.monotonic()-started,0.001)
    good=[r for r in results if r.ok]; vals=[r.elapsed_ms for r in good]
    endpoints={}
    for path,_ in ENDPOINTS:
        rows=[r for r in results if r.endpoint==path]; oks=[r for r in rows if r.ok]; pvals=[r.elapsed_ms for r in oks]
        endpoints[path]={"requests":len(rows),"success":len(oks),"errorRatePct":round(((len(rows)-len(oks))/len(rows)*100) if rows else 0,3),"p50Ms":round(percentile(pvals,.5),1),"p95Ms":round(percentile(pvals,.95),1),"p99Ms":round(percentile(pvals,.99),1)}
    total=len(results)
    out={"users":users,"durationSec":round(actual,2),"requests":total,"success":len(good),"failed":total-len(good),"errorRatePct":round(((total-len(good))/total*100) if total else 100,3),"requestsPerSec":round(total/actual,2),"successRps":round(len(good)/actual,2),"latency":{"meanMs":round(statistics.mean(vals),1) if vals else 0,"p50Ms":round(percentile(vals,.5),1),"p95Ms":round(percentile(vals,.95),1),"p99Ms":round(percentile(vals,.99),1),"maxMs":round(max(vals),1) if vals else 0},"statuses":dict(Counter(str(r.status) for r in results)),"errors":dict(Counter(r.error or "" for r in results if not r.ok)),"endpoints":endpoints}
    print("STAGE_RESULT="+json.dumps(out,separators=(",",":")),flush=True)
    return out

async def main()->int:
    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT,connect=CONNECT_TIMEOUT)
    connector=aiohttp.TCPConnector(limit=6000,limit_per_host=6000,ttl_dns_cache=300,enable_cleanup_closed=True)
    report={"target":BASE_URL,"startedAtEpoch":int(time.time()),"stages":[],"thresholds":{"maxErrorRatePct":MAX_ERROR_RATE*100,"maxP95Ms":MAX_P95_MS,"maxP99Ms":MAX_P99_MS,"minSuccessRpsAt5000":MIN_SUCCESS_RPS_AT_5000,"abortErrorRatePct":ABORT_ERROR_RATE_PCT}}
    async with aiohttp.ClientSession(timeout=timeout,connector=connector) as session:
        pre=await one_request(session)
        if not pre.ok:
            report.update({"survived":False,"failureReason":pre.error}); json.dump(report,open("load-test-5000-report.json","w"),indent=2); return 2
        for users,duration in STAGES:
            stage=await run_stage(users,duration,session); report["stages"].append(stage)
            if stage["errorRatePct"] >= ABORT_ERROR_RATE_PCT:
                report["abortedAfterUsers"]=users; break
            await asyncio.sleep(5)
    final=report["stages"][-1] if report["stages"] else {}
    reached=final.get("users")==5000
    err=float(final.get("errorRatePct",100))/100; p95=float((final.get("latency") or {}).get("p95Ms",0)); p99=float((final.get("latency") or {}).get("p99Ms",0)); rps=float(final.get("successRps",0))
    survived=bool(reached and err<=MAX_ERROR_RATE and p95<=MAX_P95_MS and p99<=MAX_P99_MS and rps>=MIN_SUCCESS_RPS_AT_5000)
    report["survived"]=survived; report["finalAssessment"]={"reached5000":reached,"errorRatePass":err<=MAX_ERROR_RATE,"p95Pass":p95<=MAX_P95_MS,"p99Pass":p99<=MAX_P99_MS,"throughputPass":rps>=MIN_SUCCESS_RPS_AT_5000}
    with open("load-test-5000-report.json","w",encoding="utf-8") as fh: json.dump(report,fh,indent=2)
    print("FINAL_REPORT="+json.dumps(report,separators=(",",":")),flush=True)
    return 0 if survived else 1

if __name__=="__main__": raise SystemExit(asyncio.run(main()))
