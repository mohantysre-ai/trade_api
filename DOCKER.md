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

## Stop / logs

```bash
docker compose logs -f --tail=100
docker compose down
```
