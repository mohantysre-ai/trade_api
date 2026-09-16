# Friday Market QA Report

## Build and environment

| Field | Value |
|---|---|
| Date/time | |
| Branch | `intradayv2` |
| Commit SHA | |
| Dirty worktree | |
| Host/CPU/RAM | |
| API/frontend workers | |
| Dataset/replay date | |
| Feed mode | Live / replay / cached |
| Write state isolation path | |

## Executive result

Overall: PASS / CONDITIONAL / FAIL

Release blockers:

1. 

## Automated checks

| Check | Result | Duration | Evidence |
|---|---|---:|---|
| Backend integration | | | |
| Smoke | | | |
| Frontend lint | | | |
| Frontend build | | | |
| Real-time validation | | | |
| UI timing | | | |

## Load and stress results

| Users | Read/write ratio | Requests | Success RPS | Error rate | p50 | p95 | p99 | Max | Result |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 50 | | | | | | | | | |
| 200 | | | | | | | | | |
| 500 | | | | | | | | | |
| 1,000 | | | | | | | | | |
| 1,500 | | | | | | | | | |
| 2,000 | | | | | | | | | |
| 3,000 | | | | | | | | | |

Breaking point: ___ concurrent users

## Endpoint bottlenecks

| Method/path | Requests | Error rate | p95 | p99 | Bottleneck evidence | Owner |
|---|---:|---:|---:|---:|---|---|
| | | | | | | |

## Market-data and P&L integrity

| Section | Freshness max | Price update interval | P&L difference | EOD difference | Ownership conflict | Result |
|---|---:|---:|---:|---:|---:|---|
| Equities | | | | | | |
| Indices | | | | | | |
| Options | | | | | | |
| Intraday | | | | | | |
| Swing | | | | | | |

## UI results

| Screen | p50 | p95 | Max | HTTP 5xx | Result |
|---|---:|---:|---:|---:|---|
| Snapshot | | | | | |
| Heatmap | | | | | |
| Swing | | | | | |
| Intraday | | | | | |
| Index Options | | | | | |
| EOD | | | | | |

## Edge-condition observations

| Scenario | Expected | Actual | Evidence | Result |
|---|---|---|---|---|
| Data spike | | | | |
| Network delay/loss | | | | |
| Upstream 429/500 | | | | |
| Rapid ticker switching | | | | |
| Concurrent write collision | | | | |
| Restart recovery | | | | |

## Resource bottlenecks

| Timestamp | CPU | Memory | Connections | Event-loop lag | Disk/DB wait | Notes |
|---|---:|---:|---:|---:|---:|---|
| | | | | | | |

## Defects and remediation

| Severity | Defect | Reproduction | Impact | Recommended fix | Retest status |
|---|---|---|---|---|---|
| | | | | | |

## Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| QA | | | |
| Engineering | | | |
| Trading operations | | | |
