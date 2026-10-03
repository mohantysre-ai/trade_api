# Post-Mortem — 2026-09-28 Trading Session

**Date:** 2026-09-28 (Monday, IST)
**Scope:** Intraday / Swing / Option Index live-update failure, persistence and rate-limit
resilience, and Stop-Loss execution correctness.
**Evidence basis:** live runtime inspection of the running stack
(`iros-market-api` container, project `sigq`, started `2026-09-28T09:41:39Z` / 15:11 IST),
source reads, and the persisted state stores. Times below are IST unless noted.

---

## 0. TL;DR

Three independent, compounding defects — not one bug.

| # | Defect | Class | Blast radius |
|---|--------|-------|--------------|
| **1** | **Swing is the only panel priced from a file.** Intraday and Index Options read the in-memory Angel WebSocket; Swing reads `last_market_snapshot.json`. When the snapshot write stalls, Swing freezes — and `authoritative.py:66-67` keeps the last persisted price, so a frozen panel looks live. | Architectural asymmetry | **Swing only** |
| **2** | The **EOD stage runs synchronously on the scheduler thread** for ≥13 min (750 candles × 1.1 s serialised throttle), so the 30-second Swing tick never fires. Amplified by a shared AnyIO 40-thread pool under `cpus: 2.0`. | Concurrency | **All three at EOD** |
| **3** | Quote-chunk loop has **no rotating cursor** — every refresh restarts at chunk 0, so an Angel cooldown skips the tail of the 750-symbol universe forever. Plus a REST recovery treadmill repairing 25 symbols/60 s against a 60 s staleness window. | Rate-limit design | Feed starvation |
| **4** | Three stacked layers of **silent staleness**: client `lastGood` returned forever, shared `pendingSnapshot` that one hung Swing fetch blocks, and a BFF that returns **HTTP 200 with up to 5-minute-old data**. | Frontend resilience | Freeze rendered as "healthy" |
| **5** | SL evaluation runs on an **ungated price** (`_resolve_ltp` has no staleness check; the 120 s TTL guard `_price_age_ok` is dead code) and books a **synthetic full-size fill at exactly the stop price**, pinning realised P&L to exactly −1 R. | Execution correctness | Wrong P&L and wrong exit prices |

Plus, for the Option Index specifically: **the desk has no −20-point SL at all.** That
threshold belongs to a different sleeve that never traded today, and even there it is silently
shortened for low-premium contracts while the API still advertises `stopPoints: 20.0`.

---

## 1. Incident timeline (reconstructed)

| Time (IST) | Event | Source |
|---|---|---|
| 10:11:50 | Intraday session committed, 5 SHORTs locked: BHEL, KALYANKJIL, HINDALCO, ADANIGREEN, ONGC. `executionPolicy: MANUAL_ONLY` | `intraday_session.json` `committedAt` |
| 10:14:32 | HINDALCO `INITIAL_SL` — genuine, session high 962.4 > stop 962.29 | `outcome.resolvedAt` |
| 10:37:44 | ADANIGREEN `TRAIL_SL` — genuine, +2.97 R | `outcome.resolvedAt` |
| **13:40:40** | **BHEL, KALYANKJIL, ONGC all closed in the same millisecond** (`…002763/002855/002919`), full remaining qty, filled at *exactly* the stop price | `events[].at` |
| 13:41:12–14 | `outcome.resolvedAt` written 32 s **after** `closedAt` for the same three | `outcome` |
| 12:55–15:16 | Option Index: 3 positions opened (NIFTY/BANKNIFTY/FINNIFTY LONG_STRANGLE), 2 more at 15:12. All 5 closed at **15:16:00 with `exitReason: TIME_EXIT`** | `index_option_positions` |
| 15:04:57 | `swing_v2_session.json` last write on the **host** tree — `refreshError: "market_refresh_already_running"` | host `backend/app/data/` |
| 15:11:39 | **Container `iros-market-api` restarted** (no crash, `RestartCount=0` → clean `compose` recreate) | `docker inspect` |
| 15:16:00 | All 5 index-option positions written CLOSED to SQLite | container `shared_state.db` |
| 15:25–15:42 | `markPipeline: {streamMarks: 0, restMarks: 0, restRequested: 0}` — the mark pipeline delivered **nothing** | `/app/state/index_options_paper_book.json` |
| 15:28:43 | `/api/index-options` `updatedAt` freezes at `09:58:43Z`; `cacheStatus: STALE` — never advances again | live API |
| 15:35 | EOD stage runs and writes `master_eod_payload.json` (28 KB), `book_index_options.json` (90 KB), `book_intraday.json` (21 KB), **`book_swing.json` (573 B — zero trades)** | container `eod/2026-09-28/` |
| 15:41:22 | Intraday feed: `WS Connected: YES`, **`WS Live: 210`, `WS Stale: 535`**, `Data Health: DEGRADED` | `/api/intraday/market-state` |
| 15:42:43 | `REST_RECOVERY … progress=225/529` — the recovery sweep is still grinding | `docker logs` |
| — | `desk_automation_stamp.json` **does not exist** — the stage ledger that records which pipeline stages ran today was never written | container filesystem |

### Observed end-state of the three panels

| Panel | Live state at 15:45 | Apparent symptom |
|---|---|---|
| **Intraday** | `ltpSourceMix: {"live": 0, "snapshot": 5}` — **zero** live marks, all 5 from the snapshot file. `liveRefreshPending: true`, `feedStatus: "OK"` (contradicts `DEGRADED` on the feed status endpoint) | "Prices updated but wrong/stuck" |
| **Swing** | `locked: true`, `cashHeld: true`, `cashReason: UNIVERSE_COVERAGE_BELOW_90PCT`, `long: []`, `counts.total: 0`, `effectiveRiskScale: 0.0` | **"System lock"** — this is the reported lock |
| **Option Index** | `cacheStatus: STALE`, `updatedAt` frozen 15:28, `sessionStatus: CLOSED`, `streamStatus.lastTickAt 15:29`, `retainedContracts: 0` | "Stopped updating" |

---

## 2. Issue 1 — Data synchronisation and the "system lock"

### 2.1 Root cause A (the swing-only asymmetry): Swing is the only panel priced from a file

This is the structural fact that best explains why Intraday and Option Index kept moving while
Swing did not.

| Panel | Price source | Type |
|---|---|---|
| **Swing** | `swing_v2/authoritative.py:100` → `_marks(snapshot)` at `:71-78` reads `snapshot["stockQuotes"][sym]["ltpRaw"]` from `last_market_snapshot.json` | **file read** |
| **Intraday** | `trade_outcome.py:1113-1147` `_intraday_ws_live_quotes()` reads the **in-memory Angel WebSocket** (`intraday_market_state`); primary authority at `:1242`, REST only fills gaps at `:1248-1261` | in-memory WS |
| **Index Options** | `index_options_live.py:152-160` reads `ANGEL_INDEX_STREAM` WebSocket + `cached_angel_index_option_snapshot` | in-memory WS |

Swing's **only** writer for those prices is `_save_last_snapshot` (`angel_one_feed.py:2363-2387`),
driven by `run_scheduled_live_refresh` (`:1036`). If that path stalls, Swing freezes while the other
two keep streaming from their own WebSockets. Nothing about Swing degrades gracefully — it just
quietly stops.

It gets worse, because `_position_row` only assigns a mark when it is truthy and positive:

```python
if mark and mark > 0:  row["currentPrice"] = …      # authoritative.py:66-67
```

So a dead snapshot leaves each Swing row holding its **last persisted price** — a plausible-looking
number with no visible gap. A frozen Swing panel looks like a working one, and the same stale mark
would feed any Swing-side P&L or exit evaluation.

### 2.2 Root cause B (primary enabler): no rotating cursor in the quote-chunk loop

`backend/app/services/angel_one_feed.py:3167-3196` (`_fetch_batch_quotes_chunked`)

```python
chunks = [instruments[i:i+QUOTE_CHUNK_SIZE] for i in range(0, len(instruments), QUOTE_CHUNK_SIZE)]
for chunk in chunks:
    if _angel_cooldown_active("marketdata"):
        logging.warning("Angel marketdata cooldown active; skipping %d remaining quote chunk(s)", ...)
        break                                    # :3185
    all_fetched.update(_fetch_quote_chunk(smart, chunk, token_to_key, self))
```

Chunks are **always rebuilt from index 0**. There is no `cursor`, `nextChunkIndex` or coverage
bookkeeping anywhere in the module. When a cooldown trips at chunk *k*, chunks *k+1…N* are
skipped — and the next refresh cycle **re-runs the same chunks from 0**, burning the same budget
on the same symbols. The log message claiming the remainder is "picked up by the next refresh
cycle" is factually wrong; they are *retried*, never *reached*.

For a 750-symbol universe (`QUOTE_CHUNK_SIZE = 25`, `angel_one_feed.py:181`) that is 30 chunks.
If the circuit trips consistently around chunk 5, chunks 6–29 — roughly 600 symbols — are never
fetched in any cycle. This is precisely the observed `WS Live: 210 / WS Stale: 535`.

**This corrects a saved project memory note** which claimed a "paced 25-symbol chunks with a
rotating cursor until cumulative coverage reaches 750/750". That behaviour does not exist.

### 2.3 Root cause C: the REST recovery sweep is a losing race

`backend/app/services/intraday_market_state.py`

```python
FRESH_SECONDS    = 8     # :36
STALE_SECONDS    = 30    # :37
RECOVERY_SECONDS = 60    # :38
...
interval   = float(os.getenv("INTRADAY_RECOVERY_INTERVAL_SEC", "60"))   # :1208
batch_size = int(os.getenv("INTRADAY_RECOVERY_BATCH", "25"))            # :1209
```

Each cycle repairs at most **25 symbols per 60 s = 0.42 symbols/s**. Each symbol goes stale again
after `RECOVERY_SECONDS = 60` without a WebSocket tick. To hold 745 symbols inside a 60 s window
requires **≥ 12.4 repairs/second**. The worker can deliver 0.42/s. The sweep is arithmetically
incapable of catching up and will run forever at `DEGRADED`.

Confirmed live: `REST_RECOVERY repaired=25/25 progress=225/529` — 225 of 529 stale symbols
repaired in ~30 minutes of runtime.

The state object *does* have a rotating cursor (`_RecoverySweep`, `:1111-1146`) — but it is a
function-local (`rest_sweep = _RecoverySweep()` at `:1211`), so it is garbage on restart and the
rotation restarts from the head of the stale list.

### 2.4 Root cause D (the actual "lock"): Swing is blocked, not broken

`backend/app/services/swing_v2/authoritative.py:123-155` (`_v2_readiness`) — Swing V2 fail-closes
unless data readiness passes. Live state in the container:

```
scan.blocked        = True
scan.blockReason    = UNIVERSE_COVERAGE_BELOW_90PCT
scan.coverage       = 0.980        <- passes the 0.9 numeric gate
scan.effectiveRiskScale = 0.0
```

`_session()` then derives `cashHeld = finalized and not locked_today` and surfaces
`cashReason = UNIVERSE_COVERAGE_BELOW_90PCT` (`:107`). Because `effectiveRiskScale == 0.0`, the
scan selects **zero** candidates, so the book stays empty all afternoon.

The user-visible "system lock" is therefore **not** a deadlock — it is the readiness gate
correctly refusing to trade on a starved feed, combined with a locked/cash book that never fills.
The defect is upstream: the gate is reading coverage from a feed that 2.1 and 2.2 had already
starved.

A second, latent hazard: the persisted host copy of `swing_v2_session.json` recorded
`refreshError: "market_refresh_already_running"` at 15:04:57. `run_scheduled_live_refresh`
(`angel_one_feed.py:958-972`) takes a non-reentrant global mutex; on detecting a stale owner it
calls `_clear_stale_refresh_lock()` (`:942-955`), which **records** staleness and explicitly
**does not release the mutex** (`return False`, comment: "mutex remains owned"). One hung refresh
therefore wedges every future refresh permanently with `market_refresh_stale_running`.

### 2.5 Root cause E: the EOD stage monopolises the scheduler thread

`backend/app/services/eod_engine/scheduler.py:186-195` — the EOD window is confirmed at 15:31 (close
marks) and 15:35–15:40 (EOD analysis):

```python
if now.hour == 15:
    if 31 <= now.minute < 35:  _maybe_refresh_close_marks(now); _STOP.wait(30); continue
    if 35 <= now.minute < 40:  _maybe_refresh_close_marks(now); _maybe_run_today(); _STOP.wait(300); continue
```

`_maybe_run_today()` calls `run_eod_analysis()` **synchronously on the scheduler thread**. That runs
`fetch_and_persist_candles` for up to 750 symbols with `EOD_CANDLE_FETCH_WORKERS=12`, each worker
holding `_CANDLE_THROTTLE_LOCK` for the **full HTTP round trip** at
`CANDLE_MIN_INTERVAL_SECONDS = 1.1` (`angel_one_feed.py:1075-1100`) — a **≥13-minute** serialised
fetch — plus `_ensure_book_reports_cached` joining up to `EOD_HARD_TIMEOUT_SEC = 300`
(`runner.py:376`).

During that whole window the scheduler thread is blocked, so `refresh_swing_session_state()`
(`scheduler.py:177-181`) — the 30-second Swing tick — **never runs**. This is the concrete
mechanism by which "everything stopped at EOD": not a global market-closed flag, but one very
long synchronous stage occupying the only thread that services the Swing loop.

Compounding it, all three panel routes are **sync `def`**
(`angel_one_feed.py:5707, 5748, 5498, 5625`), so they execute on **AnyIO's default 40-thread
limiter** — not the 256 uvicorn `--limit-concurrency` in `docker-compose.yml:88-91` — against a
`cpus: "2.0", memory: 3g` cap (`:97-101`) and `--workers 1`. All three share that one pool, so they
stall together.

### 2.6 Root cause F (frontend): three independent layers of silent staleness

`iros-terminal/lib/live-desk.ts`

```ts
const LIVE_KEYS: LiveDeskKey[] = ['live-prices', 'intraday-session', 'swing-session'];   // :8
```

```ts
async function fetchDeskKey(key) {
  try { const response = await fetch(urls[key], { cache: 'no-store' }); …
        lastGood.set(key, data); return data; }
  catch (error) { const fallback = lastGood.get(key); if (fallback) return fallback; throw error; }  // :33
}
```

1. **Silent eternal fallback.** Any error returns the last-good payload with no failure counter, no
   staleness ceiling and no UI signal. A dead backend is visually identical to a healthy one.
2. **No fetch timeout and a sticky in-flight promise.** There is no `AbortController`.
   `if (pendingSnapshot) return pendingSnapshot;` (`:38`) combined with
   `Promise.allSettled(LIVE_KEYS.map(fetchDeskKey))` (`:39`) means `pendingSnapshot` is only cleared
   in `.finally()` (`:44`) after **all three** keys settle. **One hung Swing fetch blocks the entire
   shared snapshot for Intraday and live-prices** — and Swing's BFF timeout is 60 s
   (`server-live-cache.ts:17` default, not overridden by `app/api/swing-session/route.ts`), so a hung
   Swing endpoint can freeze the shared panel set for a minute per cycle, indefinitely.
3. **A second, server-side staleness layer.** `iros-terminal/lib/server-live-cache.ts:62-74` sets
   `MAX_STALE_IF_ERROR_MS = 5 * 60_000`: a backend 500 or timeout returns **HTTP 200 with up to
   five-minute-old data** (`cacheStatus: "STALE_IF_ERROR"`). The client cannot distinguish that from
   a live response.

**Correction to an earlier reading in this document:** Index Options is *deliberately* not in
`LIVE_KEYS` — `QuantIndexOptionsPanel.tsx:392-420` runs its own fixed 5 s `setTimeout` poller with
`maxDuration = 90` on its BFF route (`app/api/index-options/route.ts:6,17`). So the shared-poller
freeze does **not** explain its 15:28 stall. Its freeze is more likely its own `busy` gate piling up
behind a slow 90 s route, compounded by the view-store tiering at `angel_one_feed.py:5548-5584`
(`age < 90` → `HIT`, `< 300` → `REFRESHING`, else `STALE`) — all three served as **200s**.

**A feedback loop worth naming:** `pollingPeriod()` (`:28`) derives the poll rate for **all** shared
panels from the *Swing* state. `hasLockedSwing()` true (`:24-27`) → `LOCKED_SWING_POLL_MS = 1_000`.
When Swing is stuck and locked — precisely today's state — the whole desk accelerates to 1 s polls,
**tripling** request pressure against a backend that is already the bottleneck. This also matches
the `GET /api/swing-session?live=1` 200s visible every few seconds in the container log.

### 2.7 Issue 1 — ranked

| # | Cause | Explains |
|---|---|---|
| 1 | Swing is the only panel priced from a file (`authoritative.py:100, 71-78`); a stalled snapshot write freezes it invisibly, and `authoritative.py:66-67` keeps stale prices looking live | **Swing-only** |
| 2 | `_SCHEDULED_REFRESH_LOCK` is never released on stale detection (`angel_one_feed.py:942-955`) and has no watchdog → permanent refresh wedge | **Swing-only** |
| 3 | Quote-chunk loop restarts at index 0 → tail starvation | Enabler for both panels |
| 4 | EOD stage runs synchronously on the scheduler thread for ≥13 min → Swing tick never runs | **Full EOD stall** |
| 5 | AnyIO 40-thread pool + `cpus: 2.0` + `--workers 1`; all three routes sync `def` | **Full EOD stall** |
| 6 | Swing readiness gate correctly fail-closed on the starved feed (`UNIVERSE_COVERAGE_BELOW_90PCT`) | The visible "lock" |
| 7 | `live-desk.ts` shared `pendingSnapshot` + client `lastGood` + BFF 5-min `STALE_IF_ERROR` | Freeze rendered as "healthy" |
| 8 | Poll-rate feedback loop: locked Swing accelerates the whole desk to 1 s | Amplifier |

---

## 3. Issue 2 — Persistence and rate-limit resilience

### 3.1 Persistence inventory (as actually running)

All live state lives in **named volumes**, which do survive `docker compose down` and
`--force-recreate`:

| Store | Path | Volume | Atomic? |
|---|---|---|---|
 | Intraday session | `/app/state/intraday_session.json` | `sigq_iros-desk-state` | Yes — `json_atomic.py:34-76` |
 | Swing V2 session | `/app/state/swing_v2_session.json` | `sigq_iros-desk-state` | Yes |
 | Market snapshot (~2.2 MB) | `/app/state/last_market_snapshot.json` | `sigq_iros-desk-state` | **No** on the 15:31 path |
| Index-options radar / candles / OI / paper book | `/app/state/index_options_*.json` | `sigq_iros-desk-state` | Yes |
| **Index-options strategy book** | `shared_state.db` → `index_option_positions/events/shadows/decision_audit` | `sigq_iros-backend-data` | SQLite WAL |
| Swing V2 ledger | `swing_v2_ledger.sqlite3` | `sigq_iros-backend-data` | WAL, `synchronous=FULL` |
| EOD books / master payload | `data/eod/{date}/*.json` | `sigq_iros-backend-data` | Yes |
| **Desk automation stage ledger** | `data/desk_automation_stamp.json` | `sigq_iros-backend-data` | **No** — and the file does not exist |
| Instrument caches (`nifty500/750/100_instruments.json`) | `/app/backend/app/services/` | **ephemeral container layer** | Mixed |

**The critical gap: SQLite is *not* the system of record for sessions.** Sessions are 100 % JSON.
SQLite holds only the index-options strategy book, the Swing V2 ledger, and a disposable
quote/view cache.

### 3.2 Persistence findings, ranked

**P0 — Two orphaned volume sets from a compose project rename.**
`docker-compose.yml:2` declares `name: sigq`, so live volumes are `sigq_iros-*`. A second,
**orphaned** set still exists on this host:

| Volume | Last content |
|---|---|
| `sigq_iros-backend-data` | live (2026-09-28) |
| `trade_api_iros-backend-data` | 2026-08-26 |
| `sigq_iros-desk-state` | live (2026-09-28) |
| `trade_api_iros-desk-state` | **2026-08-15 — and it contains a full copy of the repo** (`.git`, `.cursor`, `.dockerignore`) |

Any `docker compose -p trade_api up` — or any checkout without the `name: sigq` line — binds the
**August** volume set and presents a completely empty desk. `trade_api_iros-desk-state` is also
polluted with a 9 MB repo copy. Neither is referenced by the running stack; both are landmines.

**P1 — A second, divergent copy of the state tree exists on the host.**
`D:\trade_api\backend\app\data\` holds its own `shared_state.db` (139 MB), `swing_v2_session.json`
and `eod/2026-09-28/` — **not** the volumes the container uses. The host copy's
`index_option_positions` still shows **4 rows `OPEN`** for 2026-09-28 while the live volume
correctly shows all 5 `CLOSED` at 15:16. The host `eod/2026-09-28/` has only 12:57–13:23 warm-up
books and **no** EOD output at all.

I hit this trap during the investigation: reading the host tree first produced a completely wrong
picture of the Option Index. **Any operator debugging from the working tree is reading the wrong
desk.**

**P2 — `desk_automation_stamp.json` is missing, and its writer is unsafe.**
`backend/app/services/eod_engine/scheduler.py:64-65, 233-246`

```python
_STAMP_PATH = _DATA_DIR / "desk_automation_stamp.json"
def _save_stamp(stamp):
    try:
        _STAMP_PATH.write_text(json.dumps(stamp, indent=2), encoding="utf-8")   # :244 non-atomic
    except Exception:
        pass                                                                     # :245-246 silent
def _load_stamp():
    try: ... except Exception: return {}                                          # :233-238 silent
```

The file does not exist in the live container. The ledger that records which pipeline stages ran
today is therefore non-functional across restarts, and a torn write silently degrades to
"nothing ran" with no alarm.

**P3 — The 15:31 close-marks write is non-atomic on the primary snapshot.**
`angel_one_feed.py:2408` — `refresh_fixed_plan_close_marks` does a bare `write_text` on the
~2.2 MB `last_market_snapshot.json`, invoked by the scheduler at 15:31. `_load_last_snapshot`
(`:2322-2360`) uses raw `read_text()` and does **not** consult the `.bak` that `json_atomic`
maintains, so the safety net is written but never read for this file. A kill mid-write leaves a
truncated snapshot and the desk returns `None` for `prior`, defeating the `swingV2*` carry-forward
guard at `:1027-1030`.

**P4 — `fetch_candles` returns `[]` on rate limit — silent data loss.**
`angel_one_feed.py:2994-2995, 3012-3013`. With `CANDLE_RATE_LIMIT_RETRIES: "0"`
(`docker-compose.yml:46`) the retry ladder at `:2985-2993` is **unreachable in production**; the
first AB1021 returns an empty list. An empty list is indistinguishable from "this symbol has no
data", so throttling is read downstream as missing data → coverage collapse → the Swing readiness
gate of §2.3.

**P5 — Every rate limiter is process memory and dies with the container.**
`_CANDLE_COOLDOWN_UNTIL_MONO` (`:196`), `_ANGEL_CANDLE_CIRCUIT_UNTIL` (`:197`),
`_ANGEL_COOLDOWN_BY_CLASS` (`:207`), `_ANGEL_TRIP_COUNT` / `_ANGEL_LAST_TRIP_AT_MONO` (`:231-232`),
`_CANDLE_PRIORITY_OFFSET`, `_RecoverySweep.pending`. All are `time.monotonic()` values — undefined
across process boundaries, so a naive serialisation would also be wrong; wall-clock epoch is
required.

Consequence: `docker compose restart market-api` **thirty seconds into a live AB1021 block**
resets the 120 s candle circuit, resets the 30 → 300 s escalation ladder
(`_next_quote_circuit_hold`, `:1150-1161` — `_ANGEL_TRIP_COUNT` resets to 0 on restart), and
restarts the recovery sweep cursor. A restart is currently the *cheapest way to make rate
limiting worse*. Today's container restarted at 15:11.

**P6 — The durable index-options book shares a file with a disposable cache.**
`index_options/runtime.py:10-14` falls back to `shared_state.sqlite_store._DB_PATH` because
`INDEX_OPTIONS_STRATEGY_DB` is unset in compose. The strategy book is written into the same file
as `quotes_latest` / `view_snapshot`, on a connection opened at `synchronous=NORMAL`.

**P7 — The SQLite writer thread silently drops batches and is never shut down.**
`shared_state/sqlite_store.py:72-78` — `except Exception: pass` discards up to 50 queued
statements with no log or metric. There is **no lifespan/shutdown hook anywhere** in `backend/app`,
so `SQLiteStore.shutdown()` and `PersistenceWorker.shutdown()` are never called; under
`restart: unless-stopped` the queue is discarded on SIGTERM.

**P8 — Silent empty-reset on every load path.**
`intraday_session_engine.load_session:388-398`, `swing_session._read_json:126-132`,
`trade_outcome._load_snapshot:215-221`, `trade_outcome._load_alert_history:830-839` all
`return {}` / `return []` on parse failure. A corrupt session therefore looks like an *empty*
book, which bypasses the validity guards in `save_session` and lets the next writer overwrite
recoverable state.

**P9 — `start_docker.bat` snapshots a live, writing container.**
`start_docker.bat:103` runs `pack-desk-state.ps1` **before** `:112` (`compose stop`).
`rebuild_docker.bat:85` does it in the correct order. The `start_docker` path can capture a
torn JSON set.

### 3.3 How to handle Angel One rate limits gracefully — target design

The current design is *reactive* (trip a global circuit, return nothing) with no durable memory.
Four changes, in order of leverage:

1. **Persist the limiter.** New table `angel_limiter_state(klass TEXT PK, cooldown_until_epoch REAL,
   trip_count INT, last_trip_epoch REAL, sweep_pending TEXT)`. Rehydrate in `main.py` beside
   `hydrate_from_sqlite()`. Use **wall-clock epoch**, never `monotonic()`. A restart must inherit
   the cooldown, not forget it.
2. **Add a real cursor.** `next_chunk_index` per pool, advanced on every chunk *attempt* (not just
   success), wrapping modulo chunk count, persisted with the limiter state. Log the true message:
   "chunk 6/30 deferred, resuming at 7 next cycle" — not "picked up by the next refresh cycle".
3. **Return a distinct rate-limited signal.** `fetch_candles` should raise `AngelRateLimited` (or
   return a sentinel) instead of `[]`, so callers can distinguish throttling from "no data" and
   skip the coverage gate rather than fail-closed on it.
4. **Replace the recovery treadmill.** 25-per-60 s cannot cover 745 symbols with a 60 s window.
   Either raise `INTRADAY_RECOVERY_BATCH` to ≈ `ceil(expected / (RECOVERY_SECONDS / interval))`
   (≈ 750 for a 60 s window), or lengthen `RECOVERY_SECONDS` to the real tick cadence, or — best —
   fix the WebSocket subscription rather than patching REST over it. Persist `_RecoverySweep.pending`.

---

## 4. Issue 3 — Logic errors and Stop-Loss failures

### 4.1 The 13:40:40 batch resolution

`intraday_session.json` events, all within 1 ms:

```json
{"type":"POSITION_CLOSED","at":"2026-09-28T08:10:40.002830+00:00","symbol":"BHEL",      "closedAt":"…002763","exitKind":"INITIAL_STOP"}
{"type":"POSITION_CLOSED","at":"2026-09-28T08:10:40.002899+00:00","symbol":"KALYANKJIL","closedAt":"…002855","exitKind":"INITIAL_STOP"}
{"type":"POSITION_CLOSED","at":"2026-09-28T08:10:40.002959+00:00","symbol":"ONGC",      "closedAt":"…002919","exitKind":"INITIAL_STOP"}
```

Each `exitState.legsFilled` records the **entire remaining quantity at exactly the stop price**:

| Symbol | Entry | Stop | Fill qty | Fill price | Realised |
|---|---|---|---|---|---|
| BHEL | 409.50 | 411.55 | 244 (100 %) | 411.55 | −500.20 |
| KALYANKJIL | 563.60 | 566.42 | 177 (100 %) | 566.42 | −499.14 |
| ONGC | 233.88 | 235.05 | 256 (60 %) | 235.05 | −299.52 |

A real stop is a **market order**: it fills at or through the stop, never exactly at it. Filling
100 % of the remaining position at the threshold is a threshold *crossing*, not an execution. The
consequence is arithmetic: realised P&L is pinned to exactly −1 R (−500.20 = 244 × 2.05;
−499.14 = 177 × 2.82). **A gap-through-stop is systematically under-reported**, which is why these
exits looked "wrong" even where the trigger itself was legitimate (BHEL session high 422.0 vs stop
411.55; KALYANKJIL 573.8 vs 566.42; HINDALCO 962.4 vs 962.29 — the last by 0.11 points).

ONGC is the clearest artefact: it had already booked T1 (+100.62) and T2 (+149.60), reached
`mfeR: 1.744`, and was then reported as a plain `INITIAL_STOP` with `pathR: -1.0`. The scale-trail
state machine collapsed a 2.5 R swing into a −1 R stop because all three positions were resolved in
one pass against a single mark.

### 4.2 Why the mark feeding that pass was untrustworthy

`backend/app/services/trade_outcome.py:359-373`

```python
def _resolve_ltp(pick: dict[str, Any]) -> float:
    """Resolve the best available last traded price for a pick."""
    entry = float(pick.get("entryPrice") or 0)
    raw = pick.get("scanLtp")
    ltp = _fetch_live_price(pick["symbol"])          # snapshot file, NO age check, NO >0 check
    if ltp is None and raw is not None: ltp = float(raw)
    if ltp is None: ltp = pick.get("currentPrice")   # previous cycle's mark — sticky
    if ltp is None: ltp = entry                     # last-ditch: entry price
    return float(ltp)
```

**The 120-second price TTL guard exists and is never called.**

```python
_PRICE_TTL = 120                                    # :46
def _price_age_ok(pick) -> bool:                    # :347-356
    ...
    return age < _PRICE_TTL
```

Full-module grep: `_price_age_ok` has **exactly one occurrence — its own definition**. It is dead
code. Consequences:

- A stale snapshot mark is used for an SL comparison with no age gate.
- `if ltp is None: ltp = entry` makes the SL **permanently unreachable** (zero distance to stop).
- `pick["currentPrice"] = ltp` (`:501, 630, 672`) writes the resolved mark back into the pick, so
  one bad read becomes **sticky** across cycles via fallback #3.
- `dataStale` / `liveMarksStatus` **are computed but never gate the exit path** — they are display
  only (`:1310-1313, 1508-1515`).

Live confirmation: `/api/intraday-session` reports `ltpSourceMix: {"live": 0, "snapshot": 5}`.
**Every one of the five positions was marked from the snapshot file, none from the WebSocket**,
while the feed reported `DEGRADED` with 535 stale symbols. SL decisions were being taken on
`DEGRADED` marks with no staleness gate.

`evaluate_outcome` (`:623-634`) calls `_resolve_ltp` then `_evaluate_live_scale_trail`
unconditionally. Note the spike guard at `:417-444` (`_plausible_live_mark`, an 8 % band) rejects
outliers — but it explicitly **accepts any move through the stop** (`:435-440` returns `True`),
and when it rejects it falls back to `mark = last_mark or entry` (`:464`), which is the
non-triggering direction.

### 4.3 Option Index — the −20-point Stop-Loss

**There is no −20-point stop-loss on the Option Index desk.** Two separate, incompatible SL regimes
exist and only one was ever in play today.

**Regime A — the advertised one (`BUY_PREMIUM` single-leg sleeve).**
`index_options_paper.py:38-41, 549-552` and `index_options_live_authority.py:147`:

```python
distance = min(LONG_PREMIUM_STOP_POINTS, max(0.5, premium * 0.50))   # 20.0
target_distance = distance * LONG_PREMIUM_RISK_REWARD               # ×2
```

The 20 points is a **floor-suppressing clamp**: for any premium below ₹40 the stop is silently
*shortened* to 50 % of premium. The comment at `index_options_live_authority.py:144-146` says so
explicitly. Meanwhile the desk-level payload always advertises the constant:

```python
"longPremiumRiskPolicy": {"markIntervalSeconds": …, "stopPoints": 20.0, "targetPoints": 40.0,
                          "stopPointsMax": 20.0, "targetPointsMax": 40.0, …}   # :312-315
```

Live: `stopPoints: 20.0, targetPoints: 40.0` is what the UI shows, regardless of the actual
per-position `stopDistancePoints`. A user reading 20 on a ₹18-premium trade is looking at a 9-point
stop. That is the direct mechanism for a "20-point SL" appearing to be bypassed — or to firing
early — on any low-premium contract.

**Regime B — what actually traded today.** All five positions were 2-leg `LONG_STRADDLE` /
`LONG_STRANGLE`, `family: VOLATILITY_EXPANSION`, with **`riskModel: None` and
`stopDistancePoints: None`** — i.e. no point-based stop whatsoever. Their only loss exit is
`index_options/runtime.py:54-61`:

```python
def _exit_reason(p, now):
    family = str(p.get("family") or ""); pnl = float(p.get("unrealizedPnl") or 0)
    ml = abs(float(p.get("maxLoss") or 0)); mp = abs(float(p.get("maxProfit") or 0))
    limits = {"DIRECTIONAL":(.5,.5,time(15,20)), "VOLATILITY_EXPANSION":(.4,.35,time(15,15)),
              "RANGE":(.4,.5,time(15,0)), "TERM_STRUCTURE":(.25,.3,time(15,0))}
    pf, lf, cut = limits.get(family, (.5,.35,time(15,20)))
    if p.get("structuralInvalidated"): return "STRUCTURAL_INVALIDATION"
    if mp and pnl >=  mp*pf: return "PROFIT_TARGET"
    if ml and pnl <= -(ml*lf): return "STRUCTURE_RISK_STOP"     # pnl ≤ -(maxLoss × 0.35)
    if str(p.get("expiryState") or "")=="EXPIRY_CUTOFF": return "EXPIRY_CUTOFF"
    if now.timetz().replace(tzinfo=None) >= cut: return "TIME_EXIT"
    return None
```

All five exited on `TIME_EXIT` at 15:16 (the `VOLATILITY_EXPANSION` cut is 15:15). Their
`unrealizedPnl` at 13:21 was −195.00 / −235.50 / −198.25 against thresholds of
−1783.95 / −1995.00 / −1564.06 — so on those numbers the stop was **correctly** not triggered. The
positions rode to the time cut, which is the designed behaviour.

**Four fail-open defects in `_exit_reason` that can silently disable the stop:**

1. `pnl = float(p.get("unrealizedPnl") or 0)` — a `None`/missing mark becomes **0**, and
   `0 <= -(ml*0.35)` is `False`. **A missing mark disables the stop instead of raising a risk halt.**
2. `if ml and …` — if `maxLoss` is absent or zero, the entire stop branch is skipped. Only
   `TIME_EXIT` remains.
3. `_mark_position` (`:46-53`) does `if r is None: complete=False; legs.append(l); continue` —
   **a leg with no quote contributes 0 to P&L**, so a partial mark understates the loss and the
   stop under-fires. It sets `markStatus: "INCOMPLETE"`, but `_exit_reason` never checks it.
4. `limits.get(family, (.5, .35, time(15,20)))` — an unknown/empty `family` silently gets a
   *looser* stop (35 % vs 40 %) and a later time cut (15:20 vs 15:15).

**Plus a transaction-scope defect.** `runtime.py:326-330`:

```python
with _connect() as db:
    db.execute("BEGIN IMMEDIATE")
    for row in db.execute("SELECT payload_json FROM index_option_positions WHERE session_date=? AND status='OPEN'",(d,)):
        stored = json.loads(row[0]); market = …
        marked  = _mark_position(stored, q, now, market)
        reason  = _exit_reason(marked, now)
        updated = _close(marked, reason, now) if reason else marked
        _save_position(db, updated)
        …
    # … then the whole candidate scan + decision-audit block, same transaction
```

Every mark, every stop evaluation and every close is committed in the **same transaction** as the
entire candidate/audit sweep. Any exception anywhere in the audit section rolls back the marks and
closes for that cycle. Risk management should never share a transaction boundary with selection
logging.

### 4.4 A third durability defect on the Option Index

Live: `paperBook.openCount = 0`, `closedCount = 5`, `entryCount = 5`, `executionAuthority:
INDEX_OPTIONS_LIVE_AUTHORITY_V2` — but the file on disk, `/app/state/index_options_paper_book.json`,
has `open: []`, `closed: []`, `entryCount: 0`, `totalPnl: 0`, with the **same** `updatedAt`
(15:42:43.243). The `persist` branch at `index_options_live_authority.py:316-317` is not reaching
disk. The only durable record of today's index-options positions is SQLite. Combined with
`symbols` `retainedContracts: 0` and `markPipeline: {streamMarks: 0, restMarks: 0, restRequested: 0}`
at 15:42, the paper book had no price feed and no durable mirror.

### 4.5 Issue 3 — ranked

1. **No −20-point SL exists on this desk.** The advertised constant belongs to a sleeve that never
   traded; the five positions that traded were governed by `maxLoss × 0.35` and correctly rode to
   `TIME_EXIT`. Fix the product semantics before fixing code.
2. `_price_age_ok` is dead code and `_resolve_ltp` has no staleness gate or `> 0` check → SL
   decisions on unvalidated, possibly sticky marks.
3. SL fills are synthetic: full remaining qty at exactly the stop price → realised P&L pinned to
   exactly −1 R, gap losses under-reported.
4. `_exit_reason` fails open on a missing mark, a missing `maxLoss`, or a partial mark.
5. Risk management shares one transaction with the selection/audit sweep.
6. `longPremiumRiskPolicy` reports the constant, not the enforced per-position distance.

---

## 5. Cross-cutting architectural defects

1. **Two sources of truth for the same desk.** The repo working tree and the Docker volumes hold
   divergent copies of `shared_state.db`, the session JSONs and the EOD books. The working tree is
   gitignored "state" but is actively misleading during an incident.
2. **Fail-open everywhere in the risk path.** Missing data disables stops rather than halting
   trading. The desk is fail-*closed* on entry (readiness gates) and fail-*open* on exit (risk).
   That asymmetry is backwards.
3. **Health is reported, never acted on.** `dataStale`, `liveMarksStatus: DEGRADED`,
   `cacheStatus: STALE`, `WS Stale: 535`, `markPipeline: 0` were all present in the payloads the
   whole time. Nothing consumed them. The desk advertises its own failure and nobody listens.
4. **No observability that survives a restart.** Every limiter, cursor and circuit-breaker counter
   is in-memory, and the only live diagnostics endpoints (`/api/diagnostics/angel-gate`,
   `/api/diagnostics/angel-circuit-state`) reset with the process.
5. **Single uvicorn worker, no supervision.** `--workers 1` (`docker-compose.yml:88-89`) is correct
   given process-local state, but it means one wedged thread — e.g. the never-released
   `run_scheduled_live_refresh` mutex, or the EOD stage blocking the scheduler thread — takes down
   the whole desk with no failover.
6. **Staleness is expressed in HTTP 200.** `STALE`, `STALE_IF_ERROR`, `cacheStatus`, `dataStale`,
   `liveRefreshPending` all return 200. Nothing in the stack can fail a request on stale data, so
   no layer above can detect it. Staleness must be a *status*, not a *hint in the body*.
7. **Amplification instead of backoff.** When Swing is stuck and locked, `hasLockedSwing()` selects
   `LOCKED_SWING_POLL_MS = 1_000` for the whole desk — tripling request rate against a backend that
   is already the constraint. The one panel that is broken makes the others worse.

---

## 6. Roadmap

### P0 — today, before the next session

| # | Change | Where |
|---|---|---|
| 1 | Gate **every** exit evaluation on price freshness. Wire `_price_age_ok` (or replace it) into `evaluate_outcome`; if the mark is stale or `> 0` fails, **halt the position and raise an alert** — never fall through to `scanLtp` → `currentPrice` → `entryPrice`. Stop writing the resolved mark back into `pick["currentPrice"]` unless it was validated. | `trade_outcome.py:359-373, 623-634` |
| 2 | Make `_exit_reason` fail **closed**: return `"MARK_UNAVAILABLE"` when `unrealizedPnl is None` or `markStatus != "LIVE"`, and when `maxLoss` is falsy. Check `markStatus` in `_exit_reason`, not just set it in `_mark_position`. | `index_options/runtime.py:46-61` |
| 3 | Split the transaction: commit marks + exits in their own `BEGIN IMMEDIATE` before the candidate/audit sweep. | `index_options/runtime.py:326-330` |
| 4 | Surface staleness to the user. `live-desk.ts` must stop returning `lastGood` unconditionally — add a consecutive-failure counter, a staleness ceiling, and an `AbortController` timeout on every fetch. Clear `pendingSnapshot` on timeout. A panel must be able to say "no data for 4 minutes", not render stale rows forever. | `iros-terminal/lib/live-desk.ts:31-46` |
| 5 | Persist the Angel limiter state (wall-clock epoch) and the chunk cursor. | new `angel_limiter_state` table + `main.py` rehydrate |
| 6 | Fix the recovery arithmetic. 25 per 60 s cannot cover 745 symbols with a 60 s staleness window. Either raise the batch to match the window, lengthen the window, or fix the WebSocket subscription. Persist `_RecoverySweep.pending`. | `intraday_market_state.py:1208-1209, 1211` |
| 7 | Delete the orphaned `trade_api_iros-*` volumes, and either remove `name: sigq` or add a guard that fails loudly if the resolved project name is not `sigq`. | `docker-compose.yml:2` |
| 8 | Reconcile the host `backend/app/data` tree with the volumes, or add a README banner stating the working tree is **not** the live store. | repo root |
| 9 | **Stop the EOD stage from monopolising the scheduler thread.** Run `run_eod_analysis` on its own worker (or `_spawn_once`), never inline on the scheduler loop, so the 30-second Swing tick keeps running during the 15:35–15:40 window. | `eod_engine/scheduler.py:193`, `runner.py:255` |
| 10 | **Cap `MAX_STALE_IF_ERROR_MS`.** Five minutes of silently stale 200s is longer than an entire trading session. Cut to ~30 s and make the response *look* stale in the UI. | `iros-terminal/lib/server-live-cache.ts:62-74` |
| 11 | **Break the poll-rate feedback loop.** Do not let Swing's lock state select the poll rate for the whole desk; a stuck panel should back off, not accelerate. | `iros-terminal/lib/live-desk.ts:24-29` |

### P1 — this week

| # | Change |
|---|---|
| 9 | Book exits at the **observed mark**, not at the threshold. A stop is a market order; fill at the print that crossed it and report slippage. Pinning P&L to exactly −1 R is a correctness bug, not a rounding artefact. |
| 10 | Add the durable cursor to `_fetch_batch_quotes_chunked`; advance on every attempt, wrap modulo chunk count, log the real resume point. |
| 11 | Make `fetch_candles` raise/return a distinct rate-limited sentinel instead of `[]`, and have the readiness gates skip rather than fail-closed on throttling. |
| 12 | Release (or lease with expiry) `_SCHEDULED_REFRESH_LOCK` on stale detection. A stale refresh must not permanently wedge the desk. |
| 13 | Move `index_options` onto its own `INDEX_OPTIONS_STRATEGY_DB` file; set `synchronous=FULL` for the book. |
| 14 | Add a lifespan/shutdown hook that calls `SQLiteStore.shutdown()` / `PersistenceWorker.shutdown()`; log (do not `pass`) dropped batches. |
| 15 | Route `refresh_fixed_plan_close_marks` through `atomic_write_json`; make `_load_last_snapshot` use `load_json_with_fallback` so the `.bak` is actually read. |
| 16 | Fix `start_docker.bat:103` to stop the containers **before** packing. |
| 17 | Define the −20-point SL explicitly: which sleeve, which unit (index points vs premium points), and expose the **enforced per-position** `stopDistancePoints` in `longPremiumRiskPolicy` instead of the constant. |

### P2 — next sprint

| # | Change |
|---|---|
| 18 | Add a real supervisor: per-loop heartbeat + last-success timestamp for every live loop, exposed on one `/api/health/loops` endpoint, with alerting when any loop is > 2 poll intervals behind. |
| 19 | Persist rate-limit and cursor state to SQLite and expose it on the diagnostics endpoint so a post-restart incident is still diagnosable. |
| 20 | Make the Swing panel read the **in-memory Angel WebSocket** like Intraday and Index Options, with the snapshot file as fallback — not the other way round. This removes the single structural asymmetry that makes Swing the fragile panel. | `swing_v2/authoritative.py:100, 71-78` |
| 21 | When a Swing mark is unavailable, render it as unavailable. `authoritative.py:66-67` silently keeps the persisted price, which makes a frozen panel indistinguishable from a live one. | `swing_v2/authoritative.py:66-67` |
| 22 | Convert the three panel routes to `async def` (or explicitly size the AnyIO thread pool) so they stop sharing the 40-thread default limiter with the EOD candle workers. | `angel_one_feed.py:5498, 5625, 5707, 5748` |
| 23 | Fail-closed audit: enumerate every `except Exception: pass` on a persistence or risk path and convert each to a logged, metered, alerting failure. |
| 24 | Container-startup assertion: the boot sequence must verify the stage ledger, book freshness and feed coverage, and refuse to declare "ready" otherwise. |
| 25 | Replay test: kill the container at 10:00, 12:00, 14:00, 15:31 and 15:35 and assert exact P&L parity against the uninterrupted run. This is the regression test for §4.1. |
| 26 | Panel-freeze test: hang the Swing BFF route for 60 s and assert that Intraday keeps updating and that all panels raise a visible "no data" state. This is the regression test for §2.6. |

---

## 7. Corrections to saved project memory

- **`angel_one.batch_chunking`** — "paced 25-symbol chunks with a rotating cursor until cumulative
  coverage reaches 750/750" is **incorrect**. The chunk size and pacing are right; there is no cursor
  and no coverage bookkeeping. Corrected.
- **`angel_one.timeout_retry_policy`** — "3 retries with 0.5s/1.0s/1.5s backoff" is **incorrect**.
  The live path sleeps 0.5 s then 1.0 s (3 attempts, 8 s cap) on timeout only; the 0.5/1.0/1.5 ladder
  is in `_getmarketdata_with_retry`, which is dead code. Corrected.

---

## 8. What I could not confirm

1. **Why the container restarted at 15:11.** `RestartCount=0`, so it was a clean `compose` recreate,
   not a crash. No supervisor or deploy log was available to attribute it.
2. **Whether the 13:40:40 batch resolution ran in a previous container instance.** The current
   instance started at 15:11, so the in-memory state that produced those fills is gone. The
   persisted `closedAt`/`resolvedAt` gap of 32 s is consistent with a two-phase resolve but I cannot
   prove the sequence.
3. **The true post-entry path for BHEL / KALYANKJIL / ONGC.** `sessionHigh` values (422.0, 573.8,
   962.4) do exceed their stops, so the *triggers* look legitimate. Whether those highs were
   observed post-entry or seeded from the full day range cannot be determined from the persisted
   state alone — `_evaluate_live_scale_trail:466-476` only trusts extrema carrying
   `pathEvidenceVersion == post_entry_live_marks_v1`, and all three rows carry that flag, which is
   itself a claim I cannot independently verify.
4. **Whether `index_options_paper.json` is being written at all today.** The API reports 5 positions;
   the file has 0. The `persist` branch is at `index_options_live_authority.py:316-317`; I did not
   trace the gating condition above it.
5. **LLM provider quotas** (`LLM_PROVIDER_ORDER`) were not audited. `llm_client.llm_quota_resume_unix`
   suggests the same in-memory, non-persisted pattern as the Angel limiter.
6. **Angel One quota state at the time of the incident.** The diagnostics endpoints are in-memory and
   the container has already restarted, so the evidence is gone.
7. **Whether `_SCHEDULED_REFRESH_LOCK` was actually leaked.** `angel_one_feed.py:942-955` proves that
   a stale owner is *never* force-released and that no watchdog exists, but the current process
   started at 15:11 and the lock is now clear. Whether the pre-15:11 instance leaked it is
   unobservable after the fact. The persisted `market_refresh_already_running` on the host tree at
   15:04:57 is consistent with it, and is the strongest available circumstantial evidence.
8. **Which "lock" the operator actually saw.** There is no `systemLock` / `TRADE_LOCK` / `is_locked`
   identifier anywhere in the codebase. The two candidates are
   `swing_v2/regime.py:18` `HALT_NEW_LONGS` → `availableSlots = 0`, and
   `authoritative.py:109` `session["locked"]` from `locked_today or cash`. Both were active today;
   the live payload showed `locked: true, cashHeld: true, cashReason: UNIVERSE_COVERAGE_BELOW_90PCT`.
9. **Whether AnyIO thread-pool exhaustion actually occurred during EOD.** The structural combination
   is confirmed (sync `def` routes, 40-thread default limiter, `cpus: "2.0"`, `--workers 1`,
   12 EOD candle workers). That it *exhausted* today is inferred, not measured — the container
   carries no pool metrics.
10. **Why `index_options_paper.json` shows 0 positions while the API shows 5** (§4.4). The `persist`
    branch is at `index_options_live_authority.py:316-317`; the gating condition above it was not
    traced. Until that is resolved, treat SQLite as the only trustworthy index-options record.
11. **`intraday_session.json.lock` is not a factor.** `intraday_session_engine.py:99-131` uses
    `msvcrt.locking` / `fcntl.flock` — advisory OS locks used only inside `save_session`. The bare
    file on disk is an artifact of a native run and blocks nothing. Recorded so it is not
    re-investigated.
