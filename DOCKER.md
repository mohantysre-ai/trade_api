# IROS Terminal — Docker deploy

## Prerequisites

- Docker Engine 24+ / Docker Desktop
- `backend/.env` with Angel One + LLM keys (copy from `backend/.env.example`)

## Quick start (local)

```bash
cp backend/.env.example backend/.env
# edit backend/.env with real secrets

docker compose up -d --build
```

**Windows BAT wrappers** (same ports as native `start_app.bat` — do not run both):

| Script | Role |
|--------|------|
| `config\startup\start_docker.bat` | `docker compose up -d --build` |
| `config\startup\start_docker.bat --no-build` | start without rebuild |
| `config\startup\docker-refresh.bat` | on-demand live refresh (HTTP → `:8000`) |
| `config\startup\stop_docker.bat` | `docker compose down` |
| `config\startup\start_app.bat` | native (non-Docker) launcher |
| `config\startup\start_k8s.bat` | 3 pods on local K8s (Docker Desktop / kind) |
| `config\startup\stop_k8s.bat` | delete `iros` namespace |

| Service    | URL                      |
|------------|--------------------------|
| Frontend   | http://localhost:3000    |
| Market API | http://localhost:8000/health |
| AI News    | http://localhost:8001/health |

```bash
docker compose ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:3000/
```

### On-demand data refresh (Docker)

Refresh is **not** baked into the image — it is a runtime API call.

```bat
config\startup\docker-refresh.bat
config\startup\docker-refresh.bat --skip-news
config\startup\docker-refresh.bat --pool "Nifty 500"
```

Or use the UI **Refresh** button at http://localhost:3000.
## Ship to a cloud VM

1. Install Docker on the VM (`curl -fsSL https://get.docker.com | sh`).
2. Copy the repo (or push images to a registry).
3. Place `backend/.env` on the VM (never commit secrets).
4. Run:

```bash
docker compose up -d --build
```

### Optional: push images to a registry

```bash
docker tag iros-market-api:latest YOUR_REGISTRY/iros-market-api:latest
docker tag iros-frontend:latest YOUR_REGISTRY/iros-frontend:latest
docker push YOUR_REGISTRY/iros-market-api:latest
docker push YOUR_REGISTRY/iros-frontend:latest
```

On the VM, set `image:` in compose to those tags and `docker compose pull && docker compose up -d`.

## Persistence

Named volumes keep JSON state across restarts (source code is not mounted):

- `iros-backend-data` → `/app/backend/app/data`
- `iros-eod-archive` → `/app/backend/app/services/eod_archive`
- `iros-desk-state` → `/app/state` (`trade_api_snapshot.json`, plan, alerts, session)

## Image size notes

Optimized Dockerfiles use:

- **Backend:** multi-stage build → venv copied into slim runtime; no `curl`; pip BuildKit cache
- **Frontend:** `node:20-alpine` + Next `standalone`; health via Node `fetch`; npm BuildKit cache

Rebuild: `docker compose build --no-cache` or `config\startup\start_docker.bat`

## Kubernetes (kind cluster `iros`)

Manifests in `k8s/`. Three pods in namespace `iros`:

| Pod | Image | Host port |
|-----|-------|-----------|
| `market-api` | `iros-market-api:latest` | 8000 |
| `ai-news` | `iros-market-api:latest` | 8001 |
| `frontend` | `iros-frontend:latest` | 3000 |

```bat
config\startup\start_k8s.bat              # create kind cluster + load images + deploy
config\startup\start_k8s.bat --rebuild    # rebuild images first
config\startup\stop_k8s.bat               # delete namespace
config\startup\stop_k8s.bat --cluster     # also delete kind cluster
```

Requires `kind` (`winget install Kubernetes.kind`). Uses `imagePullPolicy: Never` after `kind load docker-image`. NodePorts mapped via `k8s/kind-config.yaml`.
Do not run compose/native and kind together on the same ports.
