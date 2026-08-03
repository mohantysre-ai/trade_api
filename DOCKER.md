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

**Repo-root launchers** (run from `d:\trade_api` — do not run native + Docker together):

| Script | Role |
|--------|------|
| `start-app.bat` | manual / native start (venv + Next) |
| `start-docker.bat` | Docker start (build if needed + healthy + tunnel) |
| `rebuild-docker.bat` | **after code changes** — no-cache rebuild, recreate, delete old images |
| `docker-refresh.bat` | Docker on-demand data refresh |
| `refresh-data.bat` | manual on-demand refresh (native or Docker on `:8000`) |

Flags: `start-docker.bat --no-build` / `--no-open`. `rebuild-docker.bat --cached` (faster). Stop: `config\startup\stop_docker.bat`.

### After every code change (Docker)

Container code is **not** live-mounted. Any change under `backend/` or `iros-terminal/` (or Dockerfiles/compose) requires:

```bat
rebuild-docker.bat
```

That builds new images, recreates containers, and prunes old/dangling images.

| Service    | URL                      |
|------------|--------------------------|
| Frontend   | http://localhost:3000    |
| Market API | http://localhost:8000/health |
| AI News    | http://localhost:8001/health |
| Public     | https://sigq.in (cloudflared container) |

**Cloudflare Tunnel (Docker):** `start-docker.bat` prepares credentials from `%USERPROFILE%\.cloudflared\` (one-time: `config\startup\setup-cloudflare-tunnel.bat`), kills any host `cloudflared`, then starts `iros-cloudflared` with `--profile tunnel`. Tunnel ingress targets `http://frontend:3000` on the compose network — not localhost.

```bash
docker compose ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
curl -fsS -o /dev/null -w "%{http_code}\n" http://localhost:3000/
```

### On-demand data refresh (Docker)

Refresh is **not** baked into the image — it is a runtime API call.

```bat
docker-refresh.bat
docker-refresh.bat --skip-news
docker-refresh.bat --pool "Nifty 500"
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

Rebuild: `rebuild-docker.bat` (or `docker compose build --no-cache` then up)

## Kubernetes (kind cluster `iros`)

Manifests in `k8s/`. Three pods in namespace `iros`:

| Pod | Image | Host port |
|-----|-------|-----------|
| `market-api` | `iros-market-api:latest` | 8000 |
| `ai-news` | `iros-market-api:latest` | 8001 |
| `frontend` | `iros-frontend:latest` | 3000 |

```bash
# Requires kind (winget install Kubernetes.kind)
kind create cluster --name iros --config k8s/kind-config.yaml
kind load docker-image iros-market-api:latest iros-frontend:latest --name iros
kubectl apply -f k8s/
# teardown: kubectl delete namespace iros
# optional: kind delete cluster --name iros
```

Uses `imagePullPolicy: Never` after `kind load docker-image`. NodePorts mapped via `k8s/kind-config.yaml`.
Do not run compose/native and kind together on the same ports.
