# Provider Router Acceptance Report
**Date:** 2026-09-25
**Branch:** intradayv2

## Implementation Summary

### New Files
- `backend/app/services/provider_router.py` — Central provider router with lease-based allocation
- `backend/tests/test_provider_router.py` — 33 comprehensive tests
- `backend/scripts/shoonya_real_validation.py` — Real Shoonya validation script
- `backend/app/main.py` — Added `/api/diagnostics/provider-router` endpoint

### Capability Matrix

| Capability | Angel | Shoonya | Dhan | NSE |
|---|---|---|---|---|
| Equity WS quotes | YES | YES | NO | NO |
| Equity REST quotes | YES | YES | YES | YES |
| Equity candles | YES | YES | YES | YES |
| Index underlying | YES | YES | NO | YES |
| NFO quote | YES | YES | NO | NO |
| Option chain | YES | NO | NO | NO |
| Greeks | YES | NO | NO | NO |
| Bulk historical candles | YES (last) | YES | YES (first) | YES (second) |
| Open position marks | YES | YES | YES | YES |

### Routing Policies

- **Candles:** DHAN → SHOONYA → NSE → ANGEL (Angel last to avoid AB1021)
- **Live Quotes:** ANGEL → SHOONYA → DHAN → NSE
- **NFO Quotes:** ANGEL → SHOONYA (bounded wait if both busy)
- **Bulk Historical:** DHAN → SHOONYA → NSE → ANGEL

## Test Results

### Provider Router Tests: 33/33 PASSED

| Test Category | Status |
|---|---|
| Provider Capabilities | VERIFIED |
| Lease Acquisition | VERIFIED |
| Concurrent Routing | VERIFIED |
| Circuit Breaker | VERIFIED |
| Provider Health | VERIFIED |
| Diagnostics | VERIFIED |
| P0 Priority | VERIFIED |
| Shared Market State | VERIFIED |
| Angel Busy → Shoonya | VERIFIED |
| Angel+Shoonya Busy → Dhan/NSE | VERIFIED |
| NFO Bounded Wait | VERIFIED |

### Regression Tests: 862 PASSED, 1 FAILED (pre-existing)

The single failure (`test_issue3_e2e_low_coverage_lock_multileg_options_and_full_parity`) is pre-existing and unrelated to this change.

## Concurrency Validation

| Scenario | Expected | Observed |
|---|---|---|
| Swing requests candles | SWING → DHAN | VERIFIED |
| Intraday requests candles while DHAN busy | INTRADAY → SHOONYA | VERIFIED |
| Index Options requests candles while both busy | INDEX → NSE | VERIFIED |
| Swing requests NFO | SWING → ANGEL | VERIFIED |
| Intraday requests NFO while ANGEL busy | INTRADAY → SHOONYA | VERIFIED |
| Index Options requests NFO while both busy | BOUNDED WAIT → ACQUIRE AFTER RELEASE | VERIFIED |

## Observability

Endpoint: `GET /api/diagnostics/provider-router`

Returns:
```json
{
  "success": true,
  "router": {
    "providers": {
      "ANGEL": {"state": "free", "owner": null, "calls": 0, "rateLimits": 0},
      "SHOONYA": {"state": "free", "owner": null, "calls": 0, "rateLimits": 0},
      "DHAN": {"state": "free", "owner": null, "calls": 0, "rateLimits": 0},
      "NSE": {"state": "free", "owner": null, "calls": 0, "rateLimits": 0}
    },
    "activeLeases": 0,
    "totalCalls": 0
  }
}
```

## Production Readiness

| Capability | Status |
|---|---|
| Provider router lease acquisition | VERIFIED |
| Concurrent provider selection | VERIFIED |
| Angel busy → Shoonya fallback | VERIFIED |
| Angel+Shoonya busy → Dhan/NSE fallback | VERIFIED |
| NFO bounded wait | VERIFIED |
| Rate-limit circuit breaker | VERIFIED |
| Provider health degradation | VERIFIED |
| Exception-safe lease release | VERIFIED |
| Diagnostics endpoint | VERIFIED |
| Shoonya authentication | BLOCKED — credentials not in runtime environment |
| Shoonya historical candles | BLOCKED — authentication required |
| Shoonya option mapping | BLOCKED — authentication required |
| Live Shoonya WS ticks | BLOCKED — authentication required |
