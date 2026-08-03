---
name: iros-hedge-fund-terminal-standards
description: >-
  Deep implementation guide for trade_api / iros-terminal — complements the
  always-apply hedge-fund-terminal-standards rule with exact stack versions,
  snapshot paths, env defaults, UI patterns, and investigation workflows. Use
  when building features, debugging pipelines, or needing repo-specific detail
  beyond the baseline rule.
---

# IROS Hedge Fund Terminal Standards

**Complements** `.cursor/rules/hedge-fund-terminal-standards.mdc` (always applied). That rule sets desk tone, data integrity, funnel shape, parallelism, and cleanup. This skill adds implementation depth — do not contradict the rule.

## Desk standard

Treat this as a highly professional trading hedge-fund desk (Bloomberg-like terminal). Precision, clarity, institutional tone. No retail gimmicks.

- Copy and UI labels: terse, factual, scannable — not marketing fluff.
- Verdicts, scores, and risk language must read like a desk note, not a blog post.
- Avoid playful animations, emoji-heavy UI, or generic "AI assistant" framing.

## No assumptions — data facts only

Never invent prices, scores, win rates, Kelly, verdicts, news, or risk flags. If data is missing, show UNRATED/empty/honest fallback — never fabricate. Prefer live API + JSON snapshot facts.

| Situation | Required behavior |
|-----------|-------------------|
| Field missing from API/snapshot | Show `UNRATED`, `—`, or empty state with honest label |
| LLM unavailable | Use heuristic/fallback paths already in code; do not invent narrative |
| Stale snapshot | Surface staleness; refresh via existing cache/TTL paths |
| User asks for a number you cannot source | Say it is unavailable; do not estimate |

**Source-of-truth order:** live API response → JSON snapshot on disk → explicit env/config. Never hallucinate intermediate values.

## Stack (verified)

| Layer | Location | Details |
|-------|----------|---------|
| Frontend | `iros-terminal/` | Next.js 16, React 19, TypeScript, Tailwind 4 |
| Backend | `backend/` | FastAPI via `angel_one_feed.create_app()`; entry `backend/app/main.py` |
| Persistence | JSON only | **No database** — snapshot read/write, TTL reuse, cache-safe refresh |

### Frontend — `iros-terminal/`

- App Router; API routes in `iros-terminal/app/api/` proxy to FastAPI where applicable.
- UI: scannable terminal density, chart-first where relevant, clear BUY/conviction affordances.
- Match existing design system (slate/emerald/red palette, compact typography, tabular nums).
- No purple-gradient AI slop; no new visual language unless requested.
- See `iros-terminal/AGENTS.md` for Next.js 16 breaking-change notes before writing framework code.

### Backend — `backend/`

- Routes and market pipeline live in `backend/app/services/angel_one_feed.py` (`create_app()`).
- Supporting services: `intelligence_engine.py`, `ai_ticker_news.py`, `bulk_deals.py`, `stock_quality.py`, NSE/Trendlyne/RSS integrations.
- Extend existing modules; do not duplicate fetch or snapshot logic.

### Snapshots and caches (JSON only)

| File | Path | Role |
|------|------|------|
| Live market | `backend/app/services/last_market_snapshot.json` | Primary market payload; `GET /api/market-data` with `prefer_cache` |
| Bulk deals | `backend/app/data/bulk_deals_cache.json` | NSE bulk/block deal cache |
| Promoter holdings | `backend/app/data/promoter_holdings.json` | Promoter % cache |
| App state | `trade_api_snapshot.json` (repo root) | `scannerPicks`, `tickerNewsByTicker`, EOD/trade-outcome state |

TTL-gated reuse and on-demand refresh: `angel_one_feed.py`, `config/startup/refresh-data-on-demand.bat` → `.kilo/scripts/refresh-data-on-demand.ps1`.

**Do not introduce SQLite, Postgres, Redis, or ORMs unless explicitly requested.**

## Asset Matrix — env defaults and funnel

Display funnel (rule baseline): **500 → 200 → 50 → ≥10 BUY**. LLM (verdict + news summary) on **top 10 only**.

| Env var | Default | Defined in | Purpose |
|---------|---------|------------|---------|
| `VOLUME_PRESELECT_LIMIT` | `200` | `angel_one_feed.py` | Top-N by volume from ~500 quotes |
| `TOP_SELECTION_COUNT` | `50` | `intelligence_engine.py` | Ranked pool after volume screen |
| `LLM_DISPLAY_COUNT` | `10` | `intelligence_engine.py` | BUY display set receiving LLM verdict + news |

Do not expand LLM scope or change funnel semantics without explicit user approval. UI must show screened counts from live payload — never fabricate BUY badges or conviction.

## Parallelism

When fixing or investigating, prefer parallel subagents for independent layers:

| Layer | Focus |
|-------|-------|
| Frontend | `iros-terminal/app/components/`, `app/api/` |
| Backend | `angel_one_feed.py`, `intelligence_engine.py`, snapshot writers |
| Scripts | `config/startup/*.bat`, `*.ps1` |
| Reproduce | Live API, snapshot contents, browser verification |

Do not parallelize tightly coupled edits to the same file.

## Cleanup

Follow `.cursor/rules/cleanup-test-artifacts.mdc`. After browser or diagnostic runs, delete screenshots (`asset-matrix*`, `screenshot*`, `browser*`, `verified*`), `tmp_*` dumps, curl captures, and session-only logs. Scan workspace root, `tmp/`, `.tmp/`, and agent output dirs before finishing.

## NSE trading skills (swing analysis & risk)

When doing **swing analysis, technical setup, position sizing, stops, R:R, or multi-timeframe** work on Indian equities, read and apply the relevant installed skills from `.cursor/skills/` (sourced from [Bhala-Srinivash/nse-trading-skills](https://github.com/Bhala-Srinivash/nse-trading-skills), MIT license — see Attribution below).

Start with **`nse-trading-toolkit`** for full-stock orchestration; use individual skills for focused tasks.

### IROS constraints (override skill defaults)

| Rule | Requirement |
|------|-------------|
| Data source | **Only** `backend/app/services/last_market_snapshot.json` + live APIs (`angel_one_feed`, NSE/Trendlyne/RSS). **Never invent** prices, RSI, ATR, levels, or scores. |
| Market context | **NSE/BSE Indian equity** — INR notionals, IST session (9:15–15:30), circuit limits, T+1. |
| Persistence | **No database** — do not add ORMs or external data stores. |
| External brokers | Do **not** require Groww MCP or yfinance unless user explicitly connects them; prefer project snapshot/API fields first. |
| Scope | Use skills for **methodology and workflow**; surface missing data as `—` / UNRATED per desk standard. |

### Installed skills (invoke by folder name)

| Skill | Path | Use when |
|-------|------|----------|
| `nse-trading-toolkit` | `.cursor/skills/nse-trading-toolkit/` | Full stock analysis orchestrator (start here) |
| `technical-analysis` | `.cursor/skills/technical-analysis/` | Trend, S/R, volume, indicator dashboard |
| `multi-timeframe-analysis` | `.cursor/skills/multi-timeframe-analysis/` | Weekly/daily/hourly confluence scoring |
| `rsi-divergence` | `.cursor/skills/rsi-divergence/` | Regular/hidden divergence detection |
| `fibonacci-trading` | `.cursor/skills/fibonacci-trading/` | Retracement zones, extension targets |
| `position-sizing` | `.cursor/skills/position-sizing/` | Fixed fractional, ATR-based, Kelly sizing |
| `stop-loss-strategies` | `.cursor/skills/stop-loss-strategies/` | Structure, ATR, S/R, MA-based stops |
| `trailing-stops` | `.cursor/skills/trailing-stops/` | ATR/structure/MA/chandelier trails |
| `risk-reward-ratio` | `.cursor/skills/risk-reward-ratio/` | R:R filter, expected value, trade gate |

### Supplemental skills (cherry-picked, equity-relevant)

| Skill | Path | Use when |
|-------|------|----------|
| `risk-management` | `.cursor/skills/risk-management/` | Drawdown limits, exposure caps, circuit breakers |
| `portfolio-analytics` | `.cursor/skills/portfolio-analytics/` | Return/risk metrics, rolling performance |
| `regime-detection` | `.cursor/skills/regime-detection/` | Vol/trend regime classification |
| `walk-forward-validation` | `.cursor/skills/walk-forward-validation/` | Strategy backtest validation, overfit checks |
| `exit-strategies` | `.cursor/skills/exit-strategies/` | Systematic exits (quant layer; NSE stops above) |
| `pandas-ta` | `.cursor/skills/pandas-ta/` | Bulk indicator computation on OHLCV |
| `volatility-modeling` | `.cursor/skills/volatility-modeling/` | GARCH, EWMA, realized vol |

**How to invoke:** Ask naturally (e.g. "analyze RELIANCE using nse-trading-toolkit") or name a skill folder — Cursor auto-discovers by description. Read `SKILL.md` in the skill folder before applying.

## Quick path reference

| Area | Path |
|------|------|
| Always-apply rule | `.cursor/rules/hedge-fund-terminal-standards.mdc` |
| NSE trading skills | `.cursor/skills/` (9 NSE + 7 supplemental; see tables above) |
| Primary snapshot | `backend/app/services/last_market_snapshot.json` |
| FastAPI app factory | `backend/app/services/angel_one_feed.py` → `create_app()` |
| Intelligence / LLM funnel | `backend/app/services/intelligence_engine.py` |
| Terminal UI | `iros-terminal/app/components/` |
| Startup | `config/startup/start_app.bat` |

## Attribution

NSE trading skills from [Bhala-Srinivash/nse-trading-skills](https://github.com/Bhala-Srinivash/nse-trading-skills) (MIT License). Supplemental skills adapted from [gmh5225/claude-trading-skills](https://github.com/gmh5225/claude-trading-skills) (MIT License, © 2026 AGIPro). Not financial advice.
