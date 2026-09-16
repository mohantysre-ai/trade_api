# Friday Market QA Execution Plan

## Objective

Validate the `intradayv2` branch under a Friday-market-open workload while preserving production trading state. The release gate covers backend correctness, mixed read/write concurrency, real-time freshness, P&L integrity, EOD consistency, frontend build quality, UI responsiveness, and failure recovery.

Zero latency is not physically measurable. The suite treats the configured data-age and response-time limits as the zero-lag service-level objective.

## Environment

Use a production-sized staging host with the same worker count, CPU, memory, database, reverse proxy, cache settings, and network path as production. Never run write load against `sigq.in` or port 8000 using live state.

Install dependencies:

```powershell
python -m pip install -r backend/requirements.txt -r performance/requirements.txt pytest pytest-asyncio
Set-Location performance
npm install
npx playwright install chromium
Set-Location ..
```

Set the variables from `performance/friday-market.env.example`. For write tests, redirect every mutable artifact before starting the API:

```powershell
$QaState = Join-Path $env:TEMP "alphix-friday-qa"
New-Item -ItemType Directory -Path $QaState -Force | Out-Null
Copy-Item intraday_session.json (Join-Path $QaState "intraday_session.json") -Force
Copy-Item swing_session.json (Join-Path $QaState "swing_session.json") -Force
Copy-Item fixed_trade_plan.json (Join-Path $QaState "fixed_trade_plan.json") -Force
$env:INTRADAY_SESSION_FILE = Join-Path $QaState "intraday_session.json"
$env:SWING_SESSION_FILE = Join-Path $QaState "swing_session.json"
$env:FIXED_PLAN_FILE = Join-Path $QaState "fixed_trade_plan.json"
$env:SWING_V2_LEDGER_PATH = Join-Path $QaState "swing_v2_ledger.sqlite3"
$env:INDEX_OPTIONS_RADAR_FILE = Join-Path $QaState "index_options_radar.json"
$env:INDEX_OPTIONS_PAPER_BOOK_FILE = Join-Path $QaState "index_options_paper_book.json"
$env:QA_ISOLATED_STATE = "true"
$env:QA_CONFIRM_WRITE_LOAD = "I_UNDERSTAND_THIS_MUTATES_TEST_STATE"
$env:SWING_STRATEGY_AUTHORITY = "V2"
$env:SWING_V2_ENABLED = "true"
$env:SWING_V2_MODE = "PAPER"
```

Start the backend and frontend in separate terminals:

```powershell
Set-Location backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8014 --workers 1
```

```powershell
Set-Location iros-terminal
$env:MARKET_API_URL = "http://127.0.0.1:8014"
npm run dev
```

## Execution order

1. Confirm `git branch --show-current` returns `intradayv2` and capture the commit SHA and dirty-worktree status.
2. Run `python -m pytest tests -q` from the `backend` directory.
3. Run `npm run lint` and `npm run build` in `iros-terminal`.
4. Run smoke profile without writes.
5. Run real-time validation for at least 15 minutes during the market-open replay or live staging feed.
6. Run the 1,000-user mixed read/write load profile against isolated state.
7. Run the stress profile until the first stage breaches the error or latency threshold.
8. Inject network delay, connection resets, stale snapshots, burst ticker changes, and upstream 429/500 responses.
9. Run UI timing while the 1,000-user backend stage is active.
10. Compare Intraday, Swing, and Index Options session totals with their corresponding EOD books by symbol, quantity, stop/target state, realized P&L, unrealized P&L, and ownership history.

Run the orchestrator:

```powershell
.\performance\run_friday_qa.ps1 -Profile load -AllowWrites
```

Run stress independently:

```powershell
python performance/market_load_test.py --profile stress --allow-writes --output performance/reports/stress-report.json
```

## Workload model

The load runner starts all virtual users through one gate, then executes a weighted Friday-dashboard mix. Reads cover Equities, Intraday, Swing, Index Options, live outcomes, market state, and EOD books. Writes cover Intraday commit, Swing lock, and atomic fixed-plan persistence. The default write ratio is 10%.

The OpenAPI inventory in the report lists registered, covered, and uncovered operations. External refresh, LLM, administrative, and parameterized forensic routes remain separate scenarios because indiscriminate high-concurrency execution would test third-party rate limits or cause expensive external side effects rather than application capacity.

## Edge and chaos matrix

| Scenario | Injection | Required behavior |
|---|---|---|
| Opening spike | 1,000 users released simultaneously | No corruption, deadlock, duplicate ownership, or error-rate breach |
| Breaking point | 1,000 → 1,500 → 2,000 → 3,000 users | Record first failed SLO and recover without restart |
| Data burst | Tenfold quote/ticker update rate | Bounded CPU/memory and no full-universe scan per tick |
| Network jitter | 50–500 ms delay and 1–5% packet loss | Stale status exposed; no false live claim |
| Upstream failure | Broker/NSE 429, 500, timeout | Cached/stale fallback or explicit unavailable state |
| Rapid switching | Equities → Options → Intraday → Swing repeatedly | No symbol, session, or P&L cross-contamination |
| Concurrent writes | Commit/lock/fixed-plan writes | Atomic files, idempotent ledger, one owner per symbol |
| EOD overlap | Live polling while EOD generation runs | Stable live book and reconciled EOD output |
| Restart | Kill API during writes and restart | Recover valid JSON/ledger and ownership history |

## Release gates

- Backend tests, frontend lint, frontend build, and smoke tests pass.
- HTTP error rate ≤2% at 1,000 users.
- Overall p95 ≤2.5 seconds and p99 ≤6 seconds.
- Successful throughput ≥75 requests/second.
- No malformed JSON, lost updates, duplicate symbol ownership, or P&L mismatch above ₹0.02 rounding tolerance.
- Market response ≤1 second and live data age ≤2 seconds unless explicitly marked stale/degraded/unavailable.
- Every UI screen p95 interaction ≤500 ms and initial page load ≤2.5 seconds.
- Service returns to baseline latency within two minutes after stress removal.
