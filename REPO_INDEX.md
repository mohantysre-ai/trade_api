# REPO INDEX — trade_api (IROS / AlphiX Terminal)

> Structural index of the working tree, written from direct filesystem discovery.
> The MCP code graph is separate and VERIFIED HEALTHY — see §7.
> Machine root: `d:\trade_api` · host `SUV-SYSTEM` · shell `powershell`
> Re-generate: see "How to refresh" at the bottom.

## 1. What this is

Full-stack market-desk: Python/FastAPI **backend** + Next.js **iros-terminal** frontend,
serving NSE/BSE market data, screeners, EOD analytics, and the Quant V2 index-options desk.

## 2. Top-level layout

```
d:\trade_api\
├── backend\                 FastAPI service (Python)  ← market data, scanners, Quant V2
├── iros-terminal\           Next.js dashboard (App Router, TS/TSX)
├── config\                  docker / cloudflare / desk-state seed data
├── scripts\                 portable deploy + runtime bundle + one-off fix scripts
├── docs\                    (if present)
├── docker-compose.yml       container orchestration
├── start-app.bat            native start  → config\startup\start_app.bat
├── start-docker.bat         container start (same ports — do not run both)
├── README.md, AGENTS.md, AGENT.md, DOCKER.md, TODO.md
└── .codebase-memory\        stale repo-local graph export — NOT the live index (§7)
```

Runtime artifacts at root (state, not source): `last_market_snapshot.json` (~1.8 MB),
`trade_api_snapshot.json`, `swing_session.json`, `fixed_trade_plan.json`,
`intraday_session.json`, `alert_history.json`, `.api-test-ledger.sqlite3`.

## 3. Backend — `backend\`

Entry: `backend\app\main.py` (FastAPI app), plus `backend\app\config.py` and
`backend\app\dependencies.py`. (Root `backend\*.py` are ad-hoc check scripts, not entry points.)

Key subtrees:
- `backend\app\services\` — the domain logic. Notable: `index_options_live.py`,
  `index_options_replay.py`, `eod_index_options_report.py`, `angel_one_feed.py`,
  `index_options\runtime.py`, `index_options\radar_builder.py`, `index_options\replay.py`.
- `backend\app\services\index_options\` — Quant V2 package: `runtime.py` owns the
  durable strategy book (`strategy_book`, `strategy_eod`), `radar_builder.py` builds
  the payload, `replay.py` handles historical replay.
- Backend root one-off check scripts: `check_dhan.py`, `check_picks.py`,
  `check_snapshot*.py`, `evaluate_dhan.py`, `run_ti_check.py`.

Payload contract touched in this session: `index-options` returns `strategyBook`
(`positions`/`open`/`closed`/`authority`/`sessionDate`), `historicalExecution`
(`entryCount`/`openCount`/`closedCount`/`source`), `quantDecision`, `modularCandidates`,
`modularSelected`, `replayDiagnostics`, `qualificationHistoryAvailable`, `historicalQualification`.

## 4. Frontend — `iros-terminal\`

Next.js App Router. `package.json` scripts via `npm run`. Config: `next.config.ts`,
`tsconfig.json`, `eslint.config.mjs`, `postcss.config.mjs`, `Dockerfile`, `server-cluster.js`.

### `iros-terminal\app\`
- `api\<route>\route.ts` — backend proxies (28 routes). Index-options route:
  `app\api\index-options\route.ts` → `${MARKET_API_URL}/api/index-options`.
  Tab routes: `eod`, `intraday`, `intraday-matrix`, `swing-session`, `index-options`,
  `index-sparkline`, `market-data`, `nse-sector-heatmap`, `live-prices`, etc.
- `components\` — 22 panel/UI components. Largest: `EodAnalysisPanel.tsx` (102 KB),
  `AssetMetricsPanel.tsx` (89 KB), `ForensicPanel.tsx` (74 KB),
  `IntradayMatrixPanel.tsx` (63 KB), `RightDrawer.tsx` (40 KB),
  `EodReviewPanel.tsx` (36 KB), `QuantIndexOptionsPanel.tsx` (30 KB).
  Tab shells: SNAPSHOT / HEATMAP / SWING / INTRADAY / INDEX OPTIONS / EOD.

### `iros-terminal\lib\` (shared logic)
- `market-api.ts` (31 KB) — market data client + EOD index-options aggregation.
- `intelligence-summary.ts` (37 KB) — terminal-intelligence summarisation.
- `index-options-vm.ts` (21 KB) — **pure payload→display view model for the INDEX OPTIONS desk.**
- `desk-motion.tsx`, `motion-tokens.ts`, `drawer-research.ts`, `symbol-logo.ts`,
  `live-desk.ts`, `format-delta.ts`, `server-live-cache.ts`.
- Tests (node:test, run with `--experimental-strip-types`): `index-options-vm.test.mjs`,
  `eod-execution.test.mjs`, plus `eod-execution.ts`.

### Design system (used by all tabs)
`app\globals.css` defines: `.desk-card` (bordered section wrapper), `.desk-pill`
(+ `--ok/--warn/--muted/--info`), `.desk-panel-title`, `.desk-metric-grid`,
`.desk-metric-tile` (+ `.desk-metric-label`/`.desk-metric-value`/`.desk-metric-delta`),
`.desk-num`, `.signal-widget`, `.signal-live-orb`. CSS vars: `--terminal-line`,
`--terminal-panel`, `--terminal-panel-2`, `--surface`, `--surface-muted`,
`--fg-strong`, `--fg-muted`, `--fg-subtle`, `--glass-1/2`, `--radius-card`.
**Note:** `.desk-metric-grid` only sets `gap` (globals.css:2396); it has **no**
`display:grid` rule — containers must ALSO carry Tailwind's `grid` utility next to
`grid-cols-*`, or the tiles stack in one column.

## 5. Config & deploy

- `config\docker\desk-state\` — Dockerfile + `seed\archive\<date>.json` EOD book cache.
- `config\cloudflare\` — `config.docker.yml`, credentials, tunnel Dockerfile.
- `scripts\` — `deploy-portable.ps1/.sh`, `export-runtime-bundle.ps1/.sh`,
  `import-runtime-bundle.ps1/.sh`, `startup smoke-test.ps1`, `run-strix.sh`,
  and historical `fix_*.py` / `redesign_*.py` one-offs.
- `docker-compose.yml` + `DOCKER.md`; two start paths, same ports (mutually exclusive).

## 6. Conventions & commands

- **Lint:** `npx eslint <files>` (repo has `eslint.config.mjs`).
- **Typecheck:** `npx tsc --noEmit` (baseline: 0 errors).
- **Build:** `npm run build` in `iros-terminal\`.
- **Tests:** `node --experimental-strip-types --test lib/*.test.mjs`.
- **Windows tooling not on PATH by default:** prefix with
  `$env:Path = "C:\Program Files\nodejs;C:\Program Files\Git\cmd;" + $env:Path`.
- Source files are **CRLF** on checkout — an LF in-place edit can trip line-based tooling.

## 7. Code graph status (VERIFIED HEALTHY)

Two different stores exist — do not confuse them:

| Store | Path | Role |
|---|---|---|
| **Live index (authoritative)** | `C:\Users\Joker\.cache\codebase-memory-mcp\D-trade_api.db` | Used by the MCP daemon. **Valid and current.** |
| Repo-local export | `.codebase-memory\artifact.json` + `graph.db.zst` | Stale/zeroed copy — not the live index. Ignore it. |

Verified live-index contents (SQLite, read-only):
- project `D-trade_api` → `D:/trade_api`; coverage run `full` / **`complete`**, 504 files
- **8,321 nodes**, **32,181 edges**, 617 file hashes, 3,149 node vectors, 3,938 token vectors
- FTS tables present (`nodes_fts`); `QuantIndexOptionsPanel.tsx` has 16 nodes incl.
  `SectionCard`, `StatCard`, `ClosedPositionCard`, `buildIndexOptionsView`, `aggregateOpenGreeks`

Tables: `projects`, `file_hashes`, `nodes`, `edges`, `node_vectors`, `token_vectors`,
`lsp_surface`, `index_coverage`, `index_coverage_meta`, `nodes_fts`, `store_meta`.
`nodes` columns: `id, project, label, name, qualified_name, file_path, start_line, end_line, properties`.

**Auto-maintained:** a daemon watcher (`strategy=git`) re-indexes on change —
`cbm-daemon.log` shows repeated `watcher.changed project=D-trade_api` →
`index.supervisor.reap outcome=clean exit_code=0`. No manual re-index needed.

Recent per-run coverage reports: `C:\Users\Joker\.cache\codebase-memory-mcp\logs\D-trade_api-<epoch>.log`
(header `# codebase-memory-mcp index coverage report`; lists `parse_partial` lines only).

Other: large JSON state files at repo root are generated, not hand-edited.

## 8. How to refresh this index

```powershell
cd d:\trade_api
$ex='\\(node_modules|\.next|\.venv|\.uv-cache|\.loadtest-venv|\.test-venv|__pycache__|\.git|dist|build)\\'
# source file counts
foreach($e in @('*.py','*.ts','*.tsx','*.mjs')){ "$e " + (Get-ChildItem -Recurse -File -Filter $e |
  Where-Object { $_.FullName -notmatch $ex }).Count }
# frontend panels
Get-ChildItem iros-terminal\app\components -File | Sort-Object Length -Descending |
  Select-Object @{n='KB';e={[math]::Round($_.Length/1KB,1)}},Name
```
