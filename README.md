# Alphix Terminal

**Institutional NSE/BSE trading desk — market snapshot, asset matrix, and forensic intelligence.**

Alphix Terminal (internally, IROS — Institutional Research Operating System / Live Market Intelligence) is a real-time Indian equity research and trading desk. It streams live NSE/BSE data from multiple providers, runs it through a weighted institutional scoring framework, and layers on LLM-driven analysis to produce trade-ready verdicts across swing, intraday, and index-options books — all the way through to an end-of-day review engine.

Live desk: **[sigq.in](https://sigq.in)**

---

## What it does

- **Live market data** across the Nifty 500 universe, sourced primarily from the NSE index snapshot, with Dhan ScanX and Angel One SmartAPI as fallback/enrichment providers, so a single missing feed never blanks the desk.
- **Institutional scoring** — a weighted confidence model (35% news sentiment + 35% Trendlyne technical signals + 30% IC Gates fundamentals) built on top of classic factor models (Piotroski F-Score, Altman Z-Score, Beneish M-Score, Magic Formula, CANSLIM, Minervini, QVMG).
- **AI-powered analysis** via a sequential multi-provider LLM router (NVIDIA, Groq, Cerebras, SambaNova, Hugging Face, OpenRouter, Omniroute, Gemini) with automatic failover — used for news summarization, IC verdict explanations, and Terminal Intelligence.
- **Multiple trading books** — Swing screener, Intraday ORB (Opening Range Breakout) scanner with VWAP/RSI/ATR-based stops and a breakeven engine, and an advisory Index Options chain with hard-gated `NO_TRADE` logic.
- **Desk automation** — scheduled morning lock, midday refreshes, and an afternoon LLM pass run on a timer, with a hard ceiling on daily position replacements and re-entries so the desk can't over-trade itself.
- **EOD engine** — end-of-day scorecards, trade proposals with human review, counterfactual analysis, and a monthly P&L rollup.
- **Forensic & sentiment panels** — SWOT analysis, technical analysis, confidence-checker, and a live editorial-style news wire per symbol.
- **Native mobile apps** for Android and iOS (Capacitor shells around the same live desk).

---

## Architecture

```
┌─────────────────────┐      ┌──────────────────────┐      ┌───────────────────────┐
│   iros-terminal      │ ───► │     market-api        │ ───► │  NSE / Dhan / Angel One │
│   (Next.js frontend) │      │  (FastAPI, :8000)      │      │  (live market data)     │
└─────────────────────┘      └──────────────────────┘      └───────────────────────┘
          │                             │
          │                             ▼
          │                   ┌──────────────────────┐      ┌───────────────────────┐
          └─────────────────► │      ai-news          │ ───► │  LLM provider router    │
                               │  (FastAPI, :8001)      │      │  (Gemini / Groq / etc.) │
                               └──────────────────────┘      └───────────────────────┘

Public traffic reaches the frontend through a Cloudflare Tunnel (sigq.in).
mobile/ wraps the same live frontend in a native WebView for Play Store / App Store.
```

`market-api` and `ai-news` are the same backend image running two different entrypoints, sharing state through named Docker volumes so desk JSON (sessions, snapshots, locked plans) survives restarts and travels between machines.

---

## Tech stack

| Layer | Stack |
|---|---|
| Backend | Python, FastAPI, uvicorn |
| Frontend | Next.js 16, React 19, Tailwind CSS 4, SWR, Motion |
| Market data | Angel One SmartAPI, Dhan ScanX, NSE index snapshot, yfinance, Screener.in |
| AI | Google Gemini + multi-provider router (NVIDIA, Groq, Cerebras, SambaNova, Hugging Face, OpenRouter, Omniroute) |
| Mobile | Capacitor (Android via Android Studio, iOS via Xcode) |
| Infra | Docker Compose, Docker Hub image distribution, Cloudflare Tunnel, optional `kind` Kubernetes cluster |

---

## Repository layout

```
trade_api/
├── backend/            FastAPI market-api + ai-news services, scoring engine, EOD engine
│   ├── app/            routes, services, models, data
│   └── README.md       backend setup + full endpoint/env reference
├── iros-terminal/       Next.js frontend (the desk UI)
├── mobile/              Capacitor Android/iOS wrapper around the live desk
├── config/
│   ├── docker/          desk-state image build
│   ├── cloudflare/       tunnel config + credentials (gitignored)
│   └── startup/          Windows launch scripts
├── docs/                index options data contract, LLM provider routing, desk notes
├── k8s/                 Kubernetes manifests for the `iros` kind cluster
├── docker-compose.yml   production stack (market-api, ai-news, frontend, tunnel)
├── DOCKER.md            Docker deploy, Hub image push/pull, k8s instructions
└── *.bat                Windows one-click start/rebuild/refresh scripts
```

---

## Getting started

### Prerequisites

- Python 3.11+ and Node 20+
- An [Angel One SmartAPI](https://smartapi.angelone.in/) app (API key + TOTP secret)
- Optional: a Dhan client ID/token (only needed for historical candles) and an LLM provider key (Gemini, Groq, etc.)

### Run natively

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env          # then fill in your credentials
python angel_one_feed.py --serve

# Frontend (separate terminal)
cd iros-terminal
npm install
npm run dev
```

The frontend runs at `http://localhost:3000` and polls the backend at `http://localhost:8000` by default. Full endpoint list, tunable environment variables, and the market-data response shape are documented in [`backend/README.md`](backend/README.md).

### Run with Docker

```bash
cp backend/.env.example backend/.env   # edit with real secrets
docker compose up -d --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Market API | http://localhost:8000/health |
| AI News | http://localhost:8001/health |
| Public (via Cloudflare Tunnel) | https://sigq.in |

Repo-root `.bat` launchers (`start-app.bat`, `start-docker.bat`, `rebuild-docker.bat`, `push-docker-hub.bat`, `start-from-hub.bat`) wrap the common native/Docker/Hub workflows — see [`DOCKER.md`](DOCKER.md) for the full deploy guide, including Docker Hub image distribution across machines and the optional `kind` Kubernetes setup.

### Mobile

```bash
cd mobile
npm install
npm run sync
npm run desk:prod       # point at https://sigq.in
npm run open:android    # or: npm run open:ios (macOS only)
```

See [`mobile/README.md`](mobile/README.md) for release-build steps and icon/splash generation.

---

## API overview

The backend exposes REST endpoints grouped roughly as:

- **Market data** — `/api/market-data`, `/api/live-prices`, `/api/sector-heatmap`, `/api/nse-symbols`, `/api/market-data/coverage`
- **News & AI intelligence** — `/api/news`, `/api/pulse-feed`, `/api/ticker-news`, `/api/market-intelligence`, `/api/terminal-intelligence`
- **Swing** — `/api/swing-screener`, `/api/swing-session`, `/api/swing-session/lock`
- **Intraday** — `/api/intraday-matrix`, `/api/intraday-session`, `/api/intraday-session/candidates`, `/api/intraday-session/commit`
- **Index options** — `/api/index-options`
- **Desk automation** — `/api/desk-ic`, `/api/desk-automation/status`, `/api/morning-prework/run`, `/api/orchestrated-refresh`
- **EOD engine** — `/api/eod/dates`, `/api/eod/summary/{date}`, `/api/eod/scorecards/{date}`, `/api/eod/proposals/{date}`, `/api/eod/run`
- **Health** — `/health`

This is a representative sample, not the full list — see [`backend/README.md`](backend/README.md) and `backend/app/api/routes/` for the complete, current set.

---

## Documentation index

| Doc | Covers |
|---|---|
| [`backend/README.md`](backend/README.md) | Backend setup, every tunable env var, response shapes |
| [`DOCKER.md`](DOCKER.md) | Docker Compose, Hub image push/pull, Cloudflare Tunnel, Kubernetes |
| [`mobile/README.md`](mobile/README.md) | Android/iOS build, release, and store-submission steps |
| [`docs/index-options.md`](docs/index-options.md) | Index Options data contract and hard-gate rules |
| [`docs/LLM_PROVIDER_ROUTING.md`](docs/LLM_PROVIDER_ROUTING.md) | Multi-provider LLM failover configuration |
| [`docs/PRIVACY_DATA_MAP.md`](docs/PRIVACY_DATA_MAP.md) | Data handling map |

---

## Security notes

- `backend/.env` holds live broker and LLM credentials — never commit it. Only `.env.example` (placeholder values) belongs in git.
- Rotate Angel One API keys, TOTP secrets, and LLM keys immediately if they're ever exposed in git history.
- Cloudflare Tunnel credentials (`config/cloudflare/credentials.json`) are gitignored and must be copied to each deployment machine manually.

## License

No license file is currently included in this repository — all rights reserved by the author unless a license is added.
